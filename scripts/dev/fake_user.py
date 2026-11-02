"""Plays the user in tests: clicks or presses keys through Mutter's remote-desktop
API, exactly like a person at the machine (it does not go through Clicky).
Run inside the VM session:

    python3 scripts/dev/fake_user.py click X Y [left|right]
    python3 scripts/dev/fake_user.py keys super+z

GNOME shows its orange "sharing" icon for the second this runs.
"""

import sys
import time

from gi.repository import Gio, GLib

RD = "org.gnome.Mutter.RemoteDesktop"
SC = "org.gnome.Mutter.ScreenCast"
KEYSYMS = {"super": 0xffeb, "ctrl": 0xffe3, "alt": 0xffe9, "shift": 0xffe1, "escape": 0xff1b, "return": 0xff0d}
BUTTONS = {"left": 0x110, "right": 0x111}

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)


def call(dest, path, iface, method, params=None, reply=None):
    res = bus.call_sync(dest, path, iface, method, params, GLib.VariantType(reply) if reply else None,
                        Gio.DBusCallFlags.NONE, 10000, None)
    return res.unpack() if res else None


def main():
    (rd,) = call(RD, "/org/gnome/Mutter/RemoteDesktop", RD, "CreateSession", None, "(o)")
    sid = call(RD, rd, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (RD + ".Session", "SessionId")), "(v)")[0]
    (sc,) = call(SC, "/org/gnome/Mutter/ScreenCast", SC, "CreateSession",
                 GLib.Variant("(a{sv})", ({"remote-desktop-session-id": GLib.Variant("s", sid)},)), "(o)")
    (stream,) = call(SC, sc, SC + ".Session", "RecordMonitor", GLib.Variant("(sa{sv})", ("", {})), "(o)")
    call(RD, rd, RD + ".Session", "Start")
    time.sleep(0.3)
    try:
        if sys.argv[1] == "click":
            x, y = float(sys.argv[2]), float(sys.argv[3])
            button = BUTTONS[sys.argv[4] if len(sys.argv) > 4 else "left"]
            call(RD, rd, RD + ".Session", "NotifyPointerMotionAbsolute", GLib.Variant("(sdd)", (stream, x, y)))
            time.sleep(0.15)
            for pressed in (True, False):
                call(RD, rd, RD + ".Session", "NotifyPointerButton", GLib.Variant("(ib)", (button, pressed)))
                time.sleep(0.06)
        elif sys.argv[1] == "keys":
            syms = [KEYSYMS.get(k.lower(), ord(k.lower()) if len(k) == 1 else 0) for k in sys.argv[2].split("+")]
            for sym in syms:
                call(RD, rd, RD + ".Session", "NotifyKeyboardKeysym", GLib.Variant("(ub)", (sym, True)))
                time.sleep(0.05)
            for sym in reversed(syms):
                call(RD, rd, RD + ".Session", "NotifyKeyboardKeysym", GLib.Variant("(ub)", (sym, False)))
                time.sleep(0.05)
        time.sleep(0.3)
    finally:
        call(RD, rd, RD + ".Session", "Stop")


if __name__ == "__main__":
    main()
