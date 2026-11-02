"""What a recipe can do. Every step is visible: the pointer flies to the target,
a short sentence is spoken and captioned, then Clicky clicks (or, in guide
mode, waits for the user to click). Targets are found by name: GNOME Shell's
own UI through the extension, app windows through AT-SPI."""

import logging
import os
import time

from .. import i18n
from ..a11y import norm
from ..i18n import _

log = logging.getLogger(__name__)

MINIMIZE_NAMES = ("Simge durumuna küçült", "Küçült", "Minimize")
CLOSE_NAMES = ("Kapat", "Close")
MAXIMIZE_NAMES = ("Ekranı Kapla", "Önceki Boyut", "Pencereyi Geri Yükle", "Geri Yükle", "Maximize", "Restore")


class RecipeFailed(Exception):
    """A recipe cannot go on. The message is said to the user (or the online agent takes over)."""


class Target:
    def __init__(self, x, y, w=0, h=0, name="", checked=None, value=None, states=()):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.name = name
        self.checked = checked
        self.value = value
        self.states = set(states)

    @property
    def center(self):
        return self.x + self.w / 2, self.y + self.h / 2

    @classmethod
    def from_shell(cls, el):
        return cls(el["x"], el["y"], el["w"], el["h"], el["name"], el.get("checked"), el.get("value"))

    @classmethod
    def from_ui(cls, el):
        return cls(el.x, el.y, el.w, el.h, el.name, "checked" in el.states or "pressed" in el.states, None, el.states)

    @classmethod
    def point(cls, x, y, name=""):
        return cls(x, y, 0, 0, name)

    def __repr__(self):
        return f"<Target {self.name!r} @{int(self.x)},{int(self.y)} {int(self.w)}x{int(self.h)}>"


def clean_label(text):
    return "".join(ch for ch in text if ch not in "​‌‍⁠﻿­")


class Ctx:
    def __init__(self, hands, a11y, world, config, performer):
        self.hands = hands
        self.d = hands.driver
        self.a11y = a11y
        self.world = world
        self.config = config
        self.performer = performer

    # ---- looking ----

    def state(self):
        return self.d.state()

    def shell(self, name=None, app_id=None, type_=None, exact=False, timeout=3.0):
        """A GNOME Shell element (panel, app grid, system menu) by name, app id or type."""
        deadline = time.monotonic() + timeout
        while True:
            found = self.d.find_elements(name or "", app_id or "", type_ or "", exact)
            if found:
                best = next((el for el in found if el.get("reactive")), found[0])
                return Target.from_shell(best)
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.2)

    def ui(self, name=None, role=None, app=None, window=None, exact=False, timeout=4.0):
        """An element inside an app window (desktop icons, Settings, dialogs) by name and role."""
        el = self.a11y.wait_for(name=name, role=role, app=app, window=window, timeout=timeout, exact=exact)
        return Target.from_ui(el) if el else None

    def menu_item(self, name, window="Desktop Icons", timeout=3.0):
        return self.ui(name, role="menu", window=window, timeout=timeout)

    def icons(self):
        """Desktop icons as (label, whole-tile target)."""
        els = self.a11y.elements(window="Desktop Icons")
        tiles = [e for e in els if e.role == "filler"]
        out = []
        for label in (e for e in els if e.role == "label"):
            cx, cy = label.center
            tile = next((t for t in tiles if t.x <= cx <= t.x + t.w and t.y <= cy <= t.y + t.h), None)
            target = Target.from_ui(tile or label)
            target.name = clean_label(label.name)
            out.append((target.name, target))
        return out

    def icon(self, name, timeout=2.0):
        want = {norm(name), norm(os.path.splitext(name)[0])}
        deadline = time.monotonic() + timeout
        while True:
            for label, target in self.icons():
                if norm(label) in want or norm(os.path.splitext(label)[0]) in want:
                    return target
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.3)

    def windows(self):
        return [w for w in self.state()["windows"] if not w["minimized"]]

    def window(self, app=None):
        """The open window of `app` (an App), or the focused window."""
        wins = self.windows()
        if app is None:
            return next((w for w in wins if w["focused"]), wins[0] if wins else None)
        return next((w for w in wins if w["app_id"] == app.id), None) or \
            next((w for w in wins if norm(app.name) in norm(w["title"]) or norm(app.name) == norm(w["app"])), None)

    def window_button(self, win, names):
        for name in names:
            hits = self.a11y.find(name=name, role="button", window=win["title"], exact=True)
            if hits:
                return Target.from_ui(hits[0])
        return None

    def wait_window(self, app_id, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for w in self.state()["windows"]:
                if w["app_id"] == app_id and not w["minimized"]:
                    return w
            time.sleep(0.4)
        return None

    def wait_until(self, check, timeout=5.0, interval=0.3):
        deadline = time.monotonic() + timeout
        while True:
            if check():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)

    def need(self, target, what):
        if target is None:
            raise RecipeFailed(_("I can't find {what} on the screen.").format(what=what))
        return target

    # ---- doing ----

    def say(self, text):
        self.hands.say(text)

    def point(self, target, say, label=None):
        self.hands.show(say, target.center, target.name if label is None else label)

    def circle(self, target, say, label=None, color="coral"):
        """Point at a target and circle it, to explain what it is."""
        cx, cy = target.center
        radius = max(26, min(90, max(target.w, target.h) / 2 + 10))
        self.d.draw([{"kind": "circle", "x": cx, "y": cy, "r": radius, "color": color}])
        self.point(target, say, label)

    def click(self, target, say, label=None):
        self._step("click", target, say, label)

    def double_click(self, target, say, label=None):
        self._step("double_click", target, say, label)

    def right_click(self, target, say, label=None):
        self._step("right_click", target, say, label)

    def drag(self, source, dest, say, label=None):
        self._step("drag", source, say, label, end=dest)

    def type(self, text, say, target=None):
        self._step("type", target, say, label="", text=text)

    def keys(self, combo, say):
        self._step("keys", None, say, label="", keys=combo)

    def quietly(self, combo):
        """A housekeeping key press (closing a menu) that needs no explanation."""
        self.d.keys(combo)
        time.sleep(0.3)

    def _step(self, action, target, say, label=None, end=None, text=None, keys=None):
        self.hands.check()
        pos = target.center if target else None
        self.hands.show(say, pos, (target.name if target else "") if label is None else label)

        def perform():
            self.hands.act(action, pos, end=end.center if end else None, text=text, keys=keys)

        if self.performer == "user":
            outcome, _reply = self.hands.wait_for_user(pos, perform)
            if outcome == "timeout":
                raise RecipeFailed(_("Let's stop here. Ask me again whenever you like."))
        else:
            perform()

    def confirm(self, question):
        self.say(question)
        reply = self.hands.listen()
        return i18n.classify_yes_no(reply, self.config.get("language", "en")) is True

    def ask(self, question):
        self.say(question)
        return self.hands.listen()

    def finish(self, say):
        self.say(say)

    # ---- common routes ----

    def desktop_spot(self):
        """A point on the visible desktop, away from windows and icons, or None."""
        st = self.state()
        area = st["work_area"]
        wins = [w for w in st["windows"] if not w["minimized"]]
        icons = [t for _, t in self.icons()]

        def free(x, y):
            for w in wins:
                if w["x"] - 14 <= x <= w["x"] + w["w"] + 14 and w["y"] - 14 <= y <= w["y"] + w["h"] + 14:
                    return False
            for t in icons:
                if t.x - 24 <= x <= t.x + t.w + 24 and t.y - 24 <= y <= t.y + t.h + 24:
                    return False
            return True

        for fy in (0.55, 0.4, 0.7, 0.25, 0.85, 0.12):
            for fx in (0.62, 0.75, 0.5, 0.86, 0.38, 0.25, 0.95):
                x, y = area["x"] + area["width"] * fx, area["y"] + area["height"] * fy
                if free(x, y):
                    return Target.point(x, y, _("empty desktop"))
        return None

    def reveal_desktop(self):
        """Minimise windows, visibly, until some desktop shows. Returns an empty spot."""
        for _attempt in range(8):
            spot = self.desktop_spot()
            if spot:
                return spot
            wins = self.windows()
            if not wins:
                break
            win = wins[0]
            button = self.window_button(win, MINIMIZE_NAMES)
            if button:
                self.click(button, _("I'll minimise this window so we can see the desktop."))
            else:
                self.keys("super+h", _("I'll press Super and H to minimise this window."))
        raise RecipeFailed(_("I can't see any free space on the desktop."))

    def open_desktop_menu(self, say=None):
        spot = self.reveal_desktop()
        self.right_click(spot, say or _("First, right-click an empty part of the desktop."))
        if not self.menu_item("Yeni Klasör", timeout=3):
            raise RecipeFailed(_("The desktop menu didn't open."))

    def open_app_grid(self, say=None):
        if self.state()["overview"]:
            return
        button = self.need(self.shell("Uygulamaları Göster", timeout=1), "Uygulamaları Göster")
        self.click(button, say or _("Click the Pardus button at the bottom left. It shows all your apps."))
        self.wait_until(lambda: self.state()["overview"], 3)

    def open_system_menu(self, say=None):
        button = self.need(self.shell(type_="QuickSettings", timeout=1), _("the system menu"))
        self.click(button, say or _("Click the icons at the bottom right to open the system menu."), label=_("system menu"))
        if not self.shell(type_="LockItem", timeout=3):
            raise RecipeFailed(_("The system menu didn't open."))

    def open_calendar(self, say=None):
        clock = self.need(self.shell(type_="DateMenuButton", timeout=1), _("the clock"))
        self.click(clock, say or _("Click the clock at the bottom right."), label=_("clock"))
        if not self.shell(type_="TodayButton", timeout=3):
            raise RecipeFailed(_("The calendar didn't open."))
