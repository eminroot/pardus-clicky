#!/usr/bin/env bash
# Installs Pardus Clicky for the current user from this checkout:
# shell extension, app menu entry, autostart and the talk shortcut.
# Run it inside the Pardus GNOME session:  ./scripts/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UUID="clicky@pardus.org.tr"
EXT_DIR="$HOME/.local/share/gnome-shell/extensions"
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
ICON="$ROOT/pardus_clicky/data/icons/tr.org.pardus.clicky.svg"

chmod +x "$ROOT/bin/pardus-clicky"

# Everything Clicky uses ships with Pardus GNOME; this only fills gaps.
need=()
python3 -c 'import gi; gi.require_version("Gtk","3.0"); gi.require_version("Gst","1.0")' 2>/dev/null || need+=(python3-gi gir1.2-gtk-3.0 gir1.2-gstreamer-1.0)
python3 -c 'import gi; gi.require_version("AyatanaAppIndicator3","0.1")' 2>/dev/null || need+=(gir1.2-ayatanaappindicator3-0.1)
if ((${#need[@]})); then
    echo "Installing: ${need[*]}"
    sudo apt-get install -y "${need[@]}"
fi

# Offline mode: Whisper (hearing), Piper (voice) and a small sentence model, in a
# venv that still sees the system GTK. About 0.6 GB of models, downloaded once.
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/pardus-clicky/venv"
if [[ "${CLICKY_SKIP_LOCAL:-}" != 1 ]]; then
    python3 -c 'import ensurepip' 2>/dev/null || sudo apt-get install -y python3-venv
    [[ -x "$VENV/bin/python" ]] || python3 -m venv --system-site-packages "$VENV"
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q faster-whisper piper-tts
    "$ROOT/bin/pardus-clicky" setup-local
fi

mkdir -p "$EXT_DIR" "$APPS_DIR" "$AUTOSTART_DIR"
ln -sfn "$ROOT/extension/$UUID" "$EXT_DIR/$UUID"
python3 - "$UUID" <<'PY'
import ast, subprocess, sys
uuid = sys.argv[1]
raw = subprocess.run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"], capture_output=True, text=True).stdout
current = ast.literal_eval(raw.replace("@as ", "").strip() or "[]")
if uuid not in current:
    subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions", str(current + [uuid])], check=True)
PY

sed -e "s|@EXEC@|$ROOT/bin/pardus-clicky|" -e "s|@ICON@|$ICON|" "$ROOT/data/tr.org.pardus.clicky.desktop" > "$APPS_DIR/tr.org.pardus.clicky.desktop"
sed -e "s|@EXEC@|$ROOT/bin/pardus-clicky|" -e "s|@ICON@|$ICON|" "$ROOT/data/tr.org.pardus.clicky.desktop" > "$AUTOSTART_DIR/tr.org.pardus.clicky.desktop"

if gdbus call --session --dest tr.org.pardus.clicky.Shell --object-path /tr/org/pardus/clicky/Shell \
        --method tr.org.pardus.clicky.Shell.Ping >/dev/null 2>&1; then
    echo "Shell helper is running."
else
    echo "Log out and back in once so GNOME loads the Clicky shell helper."
fi
if [[ ! -s "$HOME/.config/pardus-clicky/openai.key" && -z "${OPENAI_API_KEY:-}" ]]; then
    echo "Add your OpenAI key: Clicky icon in the panel > Settings, or save it to ~/.config/pardus-clicky/openai.key"
fi
echo "Installed. Start it from the app grid (Pardus Clicky) or run: $ROOT/bin/pardus-clicky"
