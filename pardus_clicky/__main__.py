"""Command line entry point.

    pardus-clicky                 start the app (it lives in the panel)
    pardus-clicky listen          start or stop listening (bound to the shortcut)
    pardus-clicky ask "TEXT"      run a typed request
    pardus-clicky type            open the "type a request" box
    pardus-clicky stop            stop the current task
    pardus-clicky settings        open settings
    pardus-clicky quit            quit the running app
    pardus-clicky doctor          check that this computer has everything Clicky needs
    pardus-clicky setup-local     download the offline speech and understanding models
"""

import sys

REMOTE = ("listen", "stop", "type", "settings", "quit")


def _remote(action, param=None):
    """Forward a command to the running app over D-Bus without loading GTK (fast for the shortcut)."""
    from gi.repository import Gio, GLib

    from . import APP_ID

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    running = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                            GLib.Variant("(s)", (APP_ID,)), GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE,
                            1000, None).unpack()[0]
    if not running:
        return False
    params = [GLib.Variant("s", param)] if param is not None else []
    bus.call_sync(APP_ID, "/" + APP_ID.replace(".", "/"), "org.gtk.Actions", "Activate",
                  GLib.Variant("(sava{sv})", (action, params, {})), None, Gio.DBusCallFlags.NONE, 3000, None)
    return True


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else ""
    if cmd in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    if cmd == "--version":
        from . import VERSION
        print(VERSION)
        return 0
    if cmd == "doctor":
        from .doctor import run
        return run()
    if cmd == "setup-local":
        from . import models
        from .config import Config
        lang = args[1] if len(args) > 1 else Config.load().get("language", "en")
        try:
            print(models.download(lang))
        except ImportError:
            print("The local AI packages are missing; run scripts/install.sh first.")
            return 1
        return 0
    if cmd in REMOTE and _remote(cmd):
        return 0
    if cmd in ("stop", "quit"):
        return 0
    if cmd == "ask" and len(args) > 1 and _remote("ask", " ".join(args[1:])):
        return 0
    from .app import main as app_main
    return app_main(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
