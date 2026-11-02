"""Microphone capture with voice-activity endpointing, and spoken replies."""

import array
import io
import logging
import math
import queue
import subprocess
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from .openai_api import ApiError  # noqa: E402

Gst.init(None)
log = logging.getLogger(__name__)

RATE = 16000
FRAME = 320  # 20 ms of 16 kHz mono


def frame_rms(chunk):
    samples = array.array("h", chunk)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class Endpointer:
    """Decides when speech starts and ends from per-frame loudness.

    Pure logic (no audio I/O) so it can be unit tested.
    """

    def __init__(self, end_silence=1.0, start_timeout=7.0, max_seconds=20.0, min_rms=350.0):
        self.end_silence = end_silence
        self.start_timeout = start_timeout
        self.max_seconds = max_seconds
        self.min_rms = min_rms
        self.noise = 0.0
        self.warmup = []
        self.recent = []
        self.started_at = None
        self.last_voice = None
        self.frames = 0

    @property
    def threshold(self):
        return max(self.min_rms, self.noise * 3.0)

    def feed(self, level):
        """Feed one 20 ms frame. Returns None to keep going, 'end' or 'timeout'."""
        t = self.frames * FRAME / RATE
        self.frames += 1
        # The quietest of the first frames is the room noise. Capped, so a user
        # who starts talking the instant they press the hotkey is still heard.
        if self.frames <= 5:
            self.warmup.append(level)
            self.noise = min(min(self.warmup), 1200.0)
        voiced = level > self.threshold
        if not voiced and self.frames > 5:
            self.noise = min(1200.0, self.noise * 0.95 + level * 0.05)
        self.recent = (self.recent + [voiced])[-6:]
        if self.started_at is None:
            if sum(self.recent) >= 4:
                self.started_at = max(0.0, t - 0.3)
                self.last_voice = t
            elif t > self.start_timeout:
                return "timeout"
        elif voiced:
            self.last_voice = t
        if self.started_at is not None and t - self.last_voice > self.end_silence:
            return "end"
        if t > self.max_seconds:
            return "end" if self.started_at is not None else "timeout"
        return None


def to_wav(pcm):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


class Recorder:
    def __init__(self, device=""):
        self.device = device
        self._stop = threading.Event()

    def stop(self):
        """Finish the current recording early (the user pressed the hotkey again)."""
        self._stop.set()

    def record(self, on_level=None, on_ready=None, **endpointer_args):
        """Blocks until the user stops talking. Returns WAV bytes, or None if nothing was said.

        on_ready is called when the first audio arrives: some microphones (a VM's
        in particular) take seconds to wake up, and the user should only start
        talking once they are told Clicky is listening.
        """
        self._stop.clear()
        src = f'pulsesrc device="{self.device}"' if self.device else "pulsesrc"
        pipe = Gst.parse_launch(
            f"{src} ! audioconvert ! audioresample ! audio/x-raw,format=S16LE,rate={RATE},channels=1 ! "
            "appsink name=sink sync=false emit-signals=false max-buffers=0")
        sink = pipe.get_by_name("sink")
        pipe.set_state(Gst.State.PLAYING)
        ep = Endpointer(**endpointer_args)
        pcm = bytearray()
        pending = b""
        result = None
        began = time.monotonic()
        try:
            while result is None:
                if self._stop.is_set():
                    result = "end" if ep.started_at is not None else "timeout"
                    break
                sample = sink.emit("try-pull-sample", 50 * Gst.MSECOND)
                if sample is None:
                    # No audio at all from the source (no microphone): give up.
                    if ep.frames == 0 and time.monotonic() - began > 15:
                        result = "timeout"
                    continue
                if ep.frames == 0 and not pending and on_ready:
                    on_ready()
                buf = sample.get_buffer()
                ok, info = buf.map(Gst.MapFlags.READ)
                if not ok:
                    continue
                pending += bytes(info.data)
                buf.unmap(info)
                while len(pending) >= FRAME * 2 and result is None:
                    chunk, pending = pending[:FRAME * 2], pending[FRAME * 2:]
                    pcm += chunk
                    level = frame_rms(chunk)
                    result = ep.feed(level)
                    if on_level and ep.frames % 3 == 0:
                        on_level(min(1.0, level / max(ep.threshold * 4, 4000)))
        finally:
            pipe.set_state(Gst.State.NULL)
        if result == "timeout" or ep.started_at is None:
            return None
        start = int(ep.started_at * RATE) * 2
        return to_wav(bytes(pcm[start:]))


class Utterance:
    """A sentence whose audio is being made (or downloaded) in the background."""

    def __init__(self, text, rate):
        self.text = text
        self.rate = rate
        self.chunks = queue.Queue()
        self.failed = False
        self.done = threading.Event()

    def wait(self, timeout=None):
        """Wait until this utterance has been spoken (when played with play_async)."""
        self.done.wait(timeout)


class Speaker:
    """Speaks short sentences through a TTS engine (Piper on the computer, or
    OpenAI), streaming so playback starts at the first audio; falls back to
    speech-dispatcher when the engine fails.

    An engine has `rate` (Hz) and `stream(text)` yielding 16-bit mono PCM.
    """

    def __init__(self, engine, config):
        self.engine = engine
        self.config = config
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="tts")
        self._stop = threading.Event()

    def prefetch(self, text):
        utterance = Utterance(text, self.engine.rate)
        if text and self.config.get("speak", True):
            self._pool.submit(self._fetch, utterance)
        else:
            utterance.chunks.put(None)
        return utterance

    def say(self, text):
        self.play(self.prefetch(text))

    def play_async(self, utterance):
        """Start speaking in the background; utterance.wait() blocks until it is done."""
        threading.Thread(target=self.play, args=(utterance,), name="speech", daemon=True).start()
        return utterance

    def stop(self):
        self._stop.set()

    def _fetch(self, utterance):
        started = time.monotonic()
        first = True
        try:
            for data in self.engine.stream(utterance.text):
                if first:
                    log.info("tts first audio after %.2fs", time.monotonic() - started)
                    utterance.rate = self.engine.rate
                    first = False
                utterance.chunks.put(data)
        except (ApiError, OSError, RuntimeError, ValueError) as exc:
            log.warning("tts failed, using speech-dispatcher: %s", exc)
            utterance.failed = True
        finally:
            utterance.chunks.put(None)

    def play(self, utterance):
        self._stop.clear()
        try:
            if utterance.text and self.config.get("speak", True):
                self._stream(utterance)
        finally:
            utterance.done.set()

    def _stream(self, utterance):
        try:
            first = utterance.chunks.get(timeout=25)
        except queue.Empty:
            log.warning("tts timed out")
            return
        if first is None:
            if utterance.failed:
                self._spd(utterance.text)
            return
        pipe = Gst.parse_launch(
            f"appsrc name=src format=time caps=audio/x-raw,format=S16LE,rate={utterance.rate},channels=1,layout=interleaved "
            "! audioconvert ! audioresample ! autoaudiosink name=out")
        src, out = pipe.get_by_name("src"), pipe.get_by_name("out")
        pipe.set_state(Gst.State.PLAYING)
        pts = 0
        pending = b""
        try:
            data = first
            while data is not None and not self._stop.is_set():
                pending += data
                usable = len(pending) - len(pending) % 2
                if usable:
                    buf = Gst.Buffer.new_wrapped(pending[:usable])
                    buf.pts = pts
                    buf.duration = usable // 2 * Gst.SECOND // utterance.rate
                    pts += buf.duration
                    src.emit("push-buffer", buf)
                    pending = pending[usable:]
                try:
                    data = utterance.chunks.get(timeout=25)
                except queue.Empty:
                    break
            src.emit("end-of-stream")
            # Some sinks (PipeWire on a VM, for one) post EOS seconds after the
            # sound has ended, so we also finish when the play position reaches the end.
            bus = pipe.get_bus()
            deadline = time.monotonic() + pts / Gst.SECOND + 10
            while time.monotonic() < deadline and not self._stop.is_set():
                msg = bus.timed_pop_filtered(30 * Gst.MSECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
                if msg is not None:
                    if msg.type == Gst.MessageType.ERROR:
                        log.warning("playback error: %s", msg.parse_error()[0].message)
                    break
                ok, position = out.query_position(Gst.Format.TIME)
                if ok and position >= pts - 40 * Gst.MSECOND:
                    break
        finally:
            pipe.set_state(Gst.State.NULL)

    def _spd(self, text):
        lang = self.config.get("language", "en")
        try:
            proc = subprocess.Popen(["spd-say", "-w", "-l", lang, text])
            while proc.poll() is None:
                if self._stop.is_set():
                    subprocess.run(["spd-say", "-S"], check=False)
                    proc.kill()
                    break
                time.sleep(0.1)
        except OSError as exc:
            log.warning("speech-dispatcher not available: %s", exc)
