"""Client for the Clicky GNOME Shell extension (D-Bus name tr.org.pardus.clicky.Shell).

The extension draws the buddy pointer, captions and sketches above the whole
desktop, takes screenshots and injects real pointer and keyboard events.
All coordinates here are stage coordinates (logical screen pixels).
"""

import json

from gi.repository import Gio, GLib

BUS_NAME = "tr.org.pardus.clicky.Shell"
OBJECT_PATH = "/tr/org/pardus/clicky/Shell"
IFACE = "tr.org.pardus.clicky.Shell"

BUTTONS = {"left": 1, "middle": 2, "right": 3}


class ShellError(Exception):
    pass


class ShellDriver:
    def __init__(self, connection=None):
        self._bus = connection or Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def _call(self, method, signature=None, args=(), reply=None, timeout_ms=8000):
        params = GLib.Variant(signature, tuple(args)) if signature else None
        try:
            res = self._bus.call_sync(BUS_NAME, OBJECT_PATH, IFACE, method, params,
                                      GLib.VariantType(reply) if reply else None,
                                      Gio.DBusCallFlags.NO_AUTO_START, timeout_ms, None)
        except GLib.Error as exc:
            raise ShellError(exc.message) from None
        return res.unpack() if res is not None else None

    # perception

    def ping(self):
        try:
            return self._call("Ping", reply="(s)", timeout_ms=2000)[0]
        except ShellError:
            return None

    def state(self):
        return json.loads(self._call("GetState", reply="(s)")[0])

    def find_elements(self, name="", app_id="", type_="", exact=False):
        """GNOME Shell UI elements (panel, app grid, menus) matching a name, with screen boxes."""
        query = {"name": name, "app_id": app_id, "type": type_, "exact": exact}
        return json.loads(self._call("FindElements", "(s)", (json.dumps(query),), "(s)")[0])

    def screenshot(self, path, hide_overlay=True):
        return json.loads(self._call("Screenshot", "(sb)", (path, hide_overlay), "(s)", timeout_ms=10000)[0])

    # overlay

    def set_state(self, state):
        self._call("SetState", "(s)", (state,))

    def set_level(self, level):
        self._call("SetLevel", "(d)", (float(level),))

    def fly_to(self, x, y, label="", ms=0):
        self._call("FlyTo", "(ddsu)", (float(x), float(y), label or "", int(ms)), timeout_ms=5000)

    def home(self):
        self._call("Home")

    def ring(self, x, y, kind):
        self._call("Ring", "(dds)", (float(x), float(y), kind))

    def rings_off(self):
        self._call("Ring", "(dds)", (0.0, 0.0, "off"))

    def caption(self, text, kind="say"):
        self._call("Caption", "(ss)", (text or "", kind))

    def draw(self, shapes, animate=True):
        self._call("Draw", "(s)", (json.dumps({"shapes": shapes, "animate": animate}),))

    def clear_drawings(self):
        self._call("ClearDrawings")

    # input

    def glide(self, x, y, ms=0):
        self._call("PointerGlide", "(ddu)", (float(x), float(y), int(ms)), timeout_ms=5000)

    def button(self, button, pressed):
        self._call("PointerButton", "(ub)", (BUTTONS.get(button, button), bool(pressed)))

    def click(self, button="left", count=1):
        self._call("Click", "(uu)", (BUTTONS.get(button, button), int(count)))

    def scroll(self, steps, horizontal=False):
        self._call("Scroll", "(ib)", (int(steps), bool(horizontal)), timeout_ms=15000)

    def keys(self, combo):
        self._call("Keys", "(s)", (combo,))

    def type_text(self, text, delay_ms=35):
        self._call("Type", "(su)", (text, int(delay_ms)), timeout_ms=max(8000, len(text) * (delay_ms + 40) + 2000))
