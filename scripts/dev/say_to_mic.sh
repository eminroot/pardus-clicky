#!/usr/bin/env bash
# Voice test without a real microphone (run inside the VM session):
#
#   scripts/dev/say_to_mic.sh "show me how to change the wallpaper" [en|tr]
#
# Creates a virtual microphone (a PipeWire null sink whose monitor becomes the
# default source), presses "listen" like the shortcut does, then plays a TTS
# recording of the sentence into that microphone. The real default source is
# restored afterwards.
set -euo pipefail
TEXT="$1"
LANG_CODE="${2:-en}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WAV="${XDG_RUNTIME_DIR:-/tmp}/clicky-fake-utterance.wav"

cd "$ROOT"
python3 - "$TEXT" "$WAV" <<'PY'
import sys
from pardus_clicky.config import Config
from pardus_clicky.openai_api import OpenAI
cfg = Config.load()
open(sys.argv[2], "wb").write(OpenAI(cfg.api_key).speech(sys.argv[1], "gpt-4o-mini-tts", "alloy", fmt="wav"))
PY

REAL_SOURCE="$(pactl get-default-source)"
[[ "$REAL_SOURCE" == clicky_fake_mic_src ]] && REAL_SOURCE="$(pactl list short sources | awk '$2 ~ /^alsa_input/ {print $2; exit}')"
SINK_MOD="$(pactl load-module module-null-sink sink_name=clicky_fake_mic sink_properties=device.description=ClickyFakeMic)"
SRC_MOD="$(pactl load-module module-remap-source master=clicky_fake_mic.monitor source_name=clicky_fake_mic_src \
    source_properties=device.description=ClickyFakeMicSource)"
pactl set-default-source clicky_fake_mic_src
# Unload the fake mic afterwards: while it exists GNOME shows the microphone-in-use icon.
trap 'pactl set-default-source "$REAL_SOURCE"; pactl unload-module "$SRC_MOD"; pactl unload-module "$SINK_MOD"' EXIT

# TRIGGER=hotkey presses the real Super+Z shortcut instead of calling the CLI.
if [[ "${TRIGGER:-cli}" == hotkey ]]; then
    python3 scripts/dev/fake_user.py keys super+z
else
    bin/pardus-clicky listen
fi
sleep 2.0          # wait for "Listening..."
paplay --device=clicky_fake_mic "$WAV"
sleep 2.5          # let the recorder hear the silence after the sentence
echo "spoke: $TEXT"
