"""Smoke test for the shell extension. Run inside the VM session while the
Clicky app is NOT running (this script borrows its bus name, which the
extension requires from callers):

    cd ~/pardus-clicky && python3 scripts/dev/overlay_demo.py [overview]
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from gi.repository import Gio  # noqa: E402

from pardus_clicky import APP_ID  # noqa: E402
from pardus_clicky.shell import ShellDriver  # noqa: E402

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
reply = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                      __import__("gi.repository.GLib", fromlist=["GLib"]).Variant("(su)", (APP_ID, 4)),
                      None, Gio.DBusCallFlags.NONE, 2000, None)
assert reply.unpack()[0] == 1, "the Clicky app is running; stop it first"

d = ShellDriver(bus)
print("ping", d.ping())
st = d.state()
print("stage", st["stage"], "pointer", st["pointer"], "overview", st["overview"], "windows", [w["title"] for w in st["windows"]])
w, h = st["stage"]

d.set_state("listening")
for i in range(30):
    d.set_level(abs(((i % 10) - 5) / 5))
    time.sleep(0.05)
d.set_state("thinking")
d.caption("Show me how to change the wallpaper", "heard")
time.sleep(1.0)
d.set_state("speaking")
d.caption("First, right-click an empty part of the desktop.", "say")
d.fly_to(w * 0.25, h * 0.6, "Empty desktop")
d.ring(w * 0.25, h * 0.6, "attention")
time.sleep(1.2)
d.draw([
    {"kind": "circle", "x": int(w * 0.035), "y": 60, "r": 46, "color": "coral"},
    {"kind": "arrow", "x": int(w * 0.25), "y": int(h * 0.3), "x2": int(w * 0.06), "y2": 110, "color": "blue", "text": "Ev = Home"},
    {"kind": "text", "x": int(w * 0.4), "y": int(h * 0.25), "text": "c² = a² + b²", "size": 28},
    {"kind": "path", "points": [[int(w * 0.4), int(h * 0.45)], [int(w * 0.4), int(h * 0.65)], [int(w * 0.55), int(h * 0.65)], [int(w * 0.4), int(h * 0.45)]], "color": "green"},
])
time.sleep(2.0)
if len(sys.argv) > 1 and sys.argv[1] == "overview":
    d.rings_off()
    d.caption("Opening the app grid.", "say")
    d.fly_to(32, h - 24, "Uygulamaları Göster")
    d.glide(32, h - 24)
    d.ring(32, h - 24, "click")
    d.click("left")
    time.sleep(1.5)
    d.fly_to(w * 0.45, h * 0.7, "Hesap Makinesi")
    time.sleep(1.5)
print("done; overlay left on screen")
