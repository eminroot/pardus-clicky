"""On-device engines: Whisper (faster-whisper) hears, Piper speaks, and a small
sentence-embedding model (MiniLM, ONNX) helps understand requests.

They live in the venv created by scripts/install.sh; importing this module
works without them, and `available()` says what can be used.
"""

import io
import logging
import os
import threading
import wave

from . import models

log = logging.getLogger(__name__)


def available(lang):
    """Which local engines can run: needs both the Python packages and the models."""
    have = models.status(lang)
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        have["whisper"] = False
    try:
        import piper  # noqa: F401
    except ImportError:
        have["piper"] = False
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError:
        have["embedder"] = False
    return have


class LocalTranscriber:
    """Speech to text with faster-whisper on the CPU. Loads the model once, lazily."""

    def __init__(self, lang, beam_size=1):
        self.lang = lang
        self.beam_size = beam_size
        self._model = None
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(str(models.whisper_dir(self.lang)), device="cpu",
                                           compute_type="int8", cpu_threads=os.cpu_count() or 4)
        return self._model

    def transcribe(self, wav, language=None, prompt=None):
        import numpy as np
        with wave.open(io.BytesIO(wav)) as w:
            pcm = w.readframes(w.getnframes())
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        lang = (language or self.lang).split("_")[0]
        segments, _ = self.load().transcribe(
            audio, language=lang if not models.WHISPER_MODELS.get(lang, "").endswith(".en") else "en",
            beam_size=self.beam_size, initial_prompt=prompt, condition_on_previous_text=False,
            vad_filter=False, without_timestamps=True, temperature=0.0)
        return " ".join(s.text.strip() for s in segments).strip()


class PiperTTS:
    """Text to speech with a Piper voice; yields raw 16-bit mono PCM."""

    def __init__(self, lang):
        self.lang = lang
        self._voice = None
        self._lock = threading.Lock()
        self.rate = 22050

    def load(self):
        with self._lock:
            if self._voice is None:
                from piper import PiperVoice
                model, config = models.piper_paths(self.lang)
                self._voice = PiperVoice.load(str(model), config_path=str(config))
                self.rate = self._voice.config.sample_rate
        return self._voice

    def stream(self, text):
        for chunk in self.load().synthesize(text):
            yield chunk.audio_int16_bytes


class CloudTTS:
    """Text to speech with OpenAI, streamed as 24 kHz PCM."""

    INSTRUCTIONS = {
        "en": "Speak English in a warm, calm and clear voice, like a patient teacher sitting next to the user. Natural, relaxed pace.",
        "tr": "Türkçe konuş. Sıcak, sakin ve net bir sesle, kullanıcının yanında oturan sabırlı bir öğretmen gibi. Doğal ve rahat bir tempo.",
    }

    def __init__(self, api, config):
        self.api = api
        self.config = config
        self.rate = 24000

    def stream(self, text):
        lang = self.config.get("language", "en")
        return self.api.speech_stream(text, self.config["tts_model"], self.config["voice"],
                                      instructions=self.INSTRUCTIONS.get(lang))


class CloudTranscriber:
    def __init__(self, api, config):
        self.api = api
        self.config = config

    def transcribe(self, wav, language=None, prompt=None):
        return self.api.transcribe(wav, self.config["stt_model"], language=language, prompt=prompt)


class Embedder:
    """Sentence vectors from a quantized MiniLM; cosine similarity = dot product."""

    def __init__(self):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        folder = models.embedder_dir()
        self._np = np
        self._tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self._tok.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tok.enable_truncation(max_length=64)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.log_severity_level = 3
        self._session = ort.InferenceSession(str(folder / "model.onnx"), options, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}

    def encode(self, texts):
        np = self._np
        batch = self._tok.encode_batch(list(texts))
        feed = {"input_ids": np.array([e.ids for e in batch], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in batch], dtype=np.int64)}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.array([e.type_ids for e in batch], dtype=np.int64)
        hidden = self._session.run(None, feed)[0]
        mask = feed["attention_mask"][..., None].astype(np.float32)
        vectors = (hidden * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
