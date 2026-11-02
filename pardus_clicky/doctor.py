"""`pardus-clicky doctor`: checks that this computer has what Clicky needs and
says how to fix what is missing. Works even when GTK cannot load."""

import os
import shutil
import subprocess
import sys
import urllib.request

OK, WARN, FAIL = "ok  ", "warn", "FAIL"


def _check_gi(namespace, version):
    try:
        import gi
        gi.require_version(namespace, version)
        __import__("gi.repository." + namespace, fromlist=[namespace])
        return True
    except (ImportError, ValueError):
        return False


def run():
    results = []

    def report(status, what, fix=""):
        results.append(status)
        print(f"[{status}] {what}" + (f"\n        fix: {fix}" if fix and status != OK else ""))

    report(OK if sys.version_info >= (3, 11) else FAIL, f"Python {sys.version.split()[0]}", "Pardus 25 ships Python 3.13")
    try:
        import gi  # noqa: F401
        report(OK, "PyGObject")
    except ImportError:
        report(FAIL, "PyGObject", "sudo apt install python3-gi")
        return 1
    for ns, ver, pkg in (("Gtk", "3.0", "gir1.2-gtk-3.0"), ("Gst", "1.0", "gir1.2-gstreamer-1.0"),
                         ("GdkPixbuf", "2.0", "gir1.2-gdkpixbuf-2.0")):
        report(OK if _check_gi(ns, ver) else FAIL, f"{ns} {ver} bindings", f"sudo apt install {pkg}")
    report(OK if _check_gi("AyatanaAppIndicator3", "0.1") else WARN, "panel icon (AyatanaAppIndicator3)",
           "sudo apt install gir1.2-ayatanaappindicator3-0.1")

    if _check_gi("Gst", "1.0"):
        from gi.repository import Gst
        Gst.init(None)
        missing = [e for e in ("pulsesrc", "audioconvert", "audioresample", "appsink", "playbin")
                   if Gst.ElementFactory.find(e) is None]
        report(OK if not missing else FAIL, "audio elements" + (f" (missing {', '.join(missing)})" if missing else ""),
               "sudo apt install gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-pulseaudio")

    session = os.environ.get("XDG_SESSION_TYPE", "?")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "?")
    report(OK if "GNOME" in desktop else WARN, f"desktop {desktop} ({session})",
           "Clicky currently supports the GNOME edition of Pardus; XFCE support is planned")

    from .shell import ShellDriver
    try:
        version = ShellDriver().ping()
    except Exception:  # noqa: BLE001
        version = None
    report(OK if version else FAIL, f"shell helper {'v' + version if version else 'not running'}",
           "run scripts/install.sh, then log out and back in once")

    from .config import Config
    cfg = Config.load()
    report(OK if cfg.api_key else FAIL, "OpenAI API key", "put it in ~/.config/pardus-clicky/openai.key or Settings")
    if cfg.api_key:
        try:
            req = urllib.request.Request(cfg.get("openai_base_url", "https://api.openai.com/v1") + "/models",
                                         headers={"Authorization": f"Bearer {cfg.api_key}"})
            urllib.request.urlopen(req, timeout=8).close()
            report(OK, "OpenAI reachable, key accepted")
        except Exception as exc:  # noqa: BLE001
            report(FAIL, f"OpenAI request failed: {exc}", "check the internet connection and the key")

    if shutil.which("pactl"):
        source = subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True).stdout.strip()
        report(OK if source else WARN, f"microphone: {source or 'none'}", "plug in or enable a microphone")
    print()
    if FAIL in results:
        print("Some checks failed.")
        return 1
    print("All good.")
    return 0
