"""User settings, stored in ~/.config/pardus-clicky/config.json.

The OpenAI key is kept out of config.json: it is read from the OPENAI_API_KEY
environment variable, or from ~/.config/pardus-clicky/openai.key (mode 600).
"""

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "pardus-clicky"
CONFIG_FILE = CONFIG_DIR / "config.json"
KEY_FILE = CONFIG_DIR / "openai.key"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "pardus-clicky"

DEFAULTS = {
    # Spoken and written language of the guide: "en" or "tr".
    "language": "en",
    # Who handles requests: "auto" = offline recipes first, the online model only for
    # what no recipe covers; "local" = never go online; "cloud" = always the online model.
    "brain": "auto",
    # Speech in and out: "auto" = on this computer when the local models are installed.
    "voice_engine": "auto",
    "whisper_beam": 1,
    # Model that looks at the screen and decides each step.
    "model": "gpt-5.6-terra",
    "reasoning_effort": "low",
    "stt_model": "gpt-4o-mini-transcribe",
    "tts_model": "gpt-4o-mini-tts",
    "voice": "marin",
    "speak": True,
    # PulseAudio/PipeWire source name; empty means the system default microphone.
    "mic_device": "",
    # Who does the clicking by default: "assistant" shows by doing it on screen,
    # "user" points and waits for the user to click.
    "performer": "assistant",
    # Pardus binds Super+C to the calculator; Super+Z is free and one-handed on a Turkish Q keyboard.
    "hotkey": "<Super>z",
    "max_steps": 30,
    "openai_base_url": "https://api.openai.com/v1",
}


class Config(dict):
    @classmethod
    def load(cls):
        cfg = cls(DEFAULTS)
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            print(f"config: ignoring unreadable {CONFIG_FILE}: {exc}")
        return cfg

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in self.items() if k != "openai_api_key"}
        CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @property
    def api_key(self):
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if key:
            return key
        try:
            return KEY_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            return str(self.get("openai_api_key", "")).strip()

    @staticmethod
    def set_api_key(key):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key.strip())
