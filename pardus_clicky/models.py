"""On-device models: where they live and how to fetch them.

Everything is downloaded once (by scripts/install.sh or `pardus-clicky
setup-local`) into ~/.local/share/pardus-clicky/models; after that Clicky's
local mode works without internet.
"""

import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "pardus-clicky"
MODELS_DIR = DATA_DIR / "models"
VENV_DIR = DATA_DIR / "venv"

# Speech to text (faster-whisper). English-only models are faster and more accurate for English.
WHISPER_MODELS = {"en": "small.en", "tr": "small"}

# Speech output (Piper voices from rhasspy/piper-voices).
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
PIPER_VOICES = {
    "en": ("en_US-lessac-medium", "en/en_US/lessac/medium"),
    "tr": ("tr_TR-dfki-medium", "tr/tr_TR/dfki/medium"),
}

# Sentence embeddings for understanding requests (quantized MiniLM, about 23 MB).
EMBEDDER_NAME = "all-MiniLM-L6-v2"
EMBEDDER_FILES = {
    "model.onnx": "https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/main/onnx/model_quantized.onnx",
    "tokenizer.json": "https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/main/tokenizer.json",
}


def whisper_dir(lang):
    return MODELS_DIR / "whisper" / WHISPER_MODELS.get(lang, WHISPER_MODELS["en"])


def piper_paths(lang):
    name, _ = PIPER_VOICES.get(lang, PIPER_VOICES["en"])
    folder = MODELS_DIR / "piper"
    return folder / f"{name}.onnx", folder / f"{name}.onnx.json"


def embedder_dir():
    return MODELS_DIR / "embedder" / EMBEDDER_NAME


def status(lang):
    """Which local models are present for a language."""
    voice, voice_cfg = piper_paths(lang)
    return {
        "whisper": (whisper_dir(lang) / "model.bin").exists(),
        "piper": voice.exists() and voice_cfg.exists(),
        "embedder": all((embedder_dir() / name).exists() for name in EMBEDDER_FILES),
    }


def _fetch(url, dest, log):
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"downloading {dest.name}")
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".part-")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(resp, out, 1 << 20)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def download(lang="en", log=print):
    """Fetch every local model for `lang`. Needs the venv with faster-whisper."""
    from faster_whisper import download_model

    target = whisper_dir(lang)
    if not (target / "model.bin").exists():
        log(f"downloading speech recognition model {target.name}")
        download_model(target.name, output_dir=str(target))
    voice, voice_cfg = piper_paths(lang)
    _, path = PIPER_VOICES.get(lang, PIPER_VOICES["en"])
    _fetch(f"{PIPER_BASE}/{path}/{voice.name}", voice, log)
    _fetch(f"{PIPER_BASE}/{path}/{voice_cfg.name}", voice_cfg, log)
    for name, url in EMBEDDER_FILES.items():
        _fetch(url, embedder_dir() / name, log)
    return status(lang)
