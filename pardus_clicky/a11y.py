"""Finds elements inside app windows (desktop icons, Settings, dialogs) through
AT-SPI, by role and name, with their position on screen.

On Wayland, GTK 4 apps report positions relative to their own window, so each
AT-SPI window is matched to the compositor's window (same process, same
title) and shifted by that window's position.

libatspi is not thread-safe and keeps a cache that its events update on the
main loop. Inside the app, queries therefore run on the main thread
(run_on_main_loop) and every search starts from a cleared cache, so a menu
that opened a moment ago is seen.
"""

import threading
import time
import unicodedata

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib  # noqa: E402

_marshal = False


def run_on_main_loop(enabled=True):
    """Called by the app: from now on, queries from other threads hop to the GTK main loop."""
    global _marshal
    _marshal = enabled


def _on_main(fn, *args, **kwargs):
    if not _marshal or threading.current_thread() is threading.main_thread():
        return fn(*args, **kwargs)
    box = {}
    done = threading.Event()

    def task():
        try:
            box["value"] = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised on the calling thread
            box["error"] = exc
        finally:
            done.set()
        return GLib.SOURCE_REMOVE

    GLib.idle_add(task)
    if not done.wait(30):
        raise TimeoutError("accessibility query timed out")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def norm(text):
    """Accent-, case- and ellipsis-insensitive form for matching labels ('Görünüm' == 'gorunum')."""
    text = (text or "").replace("…", "...").replace("’", "'").replace("ʼ", "'")
    # The desktop icons put zero-width spaces into file names so they can wrap.
    text = "".join(ch for ch in text if ch not in "​‌‍⁠﻿­")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().replace("ı", "i").split())


class Element:
    __slots__ = ("app", "window", "role", "name", "x", "y", "w", "h", "states")

    def __init__(self, app, window, role, name, x, y, w, h, states):
        self.app, self.window, self.role, self.name = app, window, role, name
        self.x, self.y, self.w, self.h = x, y, w, h
        self.states = states

    @property
    def center(self):
        return self.x + self.w / 2, self.y + self.h / 2

    def has(self, state):
        return state in self.states

    def __repr__(self):
        return f"<{self.role} {self.name!r} @{self.x},{self.y} {self.w}x{self.h}>"


INTERESTING_STATES = {
    Atspi.StateType.FOCUSED: "focused", Atspi.StateType.SELECTED: "selected",
    Atspi.StateType.CHECKED: "checked", Atspi.StateType.PRESSED: "pressed",
    Atspi.StateType.EXPANDED: "expanded", Atspi.StateType.SENSITIVE: "sensitive",
    Atspi.StateType.EDITABLE: "editable",
}


class A11y:
    def __init__(self, driver):
        self.driver = driver

    def elements(self, app=None, window=None, max_nodes=4000):
        """Every named, showing element of matching apps/windows (app or window title substring)."""
        return _on_main(self._elements, app, window, max_nodes)

    def _elements(self, app, window, max_nodes):
        surfaces = self.driver.state().get("surfaces", [])
        desktop = Atspi.get_desktop(0)
        desktop.clear_cache()
        out = []
        budget = [max_nodes]
        for i in range(desktop.get_child_count()):
            application = desktop.get_child_at_index(i)
            if application is None:
                continue
            try:
                app_name = application.get_name() or ""
                pid = application.get_process_id()
                frames = []
                for j in range(application.get_child_count()):
                    frame = application.get_child_at_index(j)
                    if frame is not None and frame.get_state_set().contains(Atspi.StateType.SHOWING):
                        frames.append((frame, frame.get_name() or ""))
            except GLib.Error:
                continue
            titles = [t for _, t in frames]
            # Filters pick the app; then all its showing top-levels are walked,
            # because menus and popovers are separate, untitled top-levels.
            if app and norm(app) not in norm(app_name) and not any(norm(app) in norm(t) for t in titles):
                continue
            if window and not any(norm(window) in norm(t) for t in titles):
                continue
            for frame, title in frames:
                place = self._placement(frame, pid, title, titles, surfaces)
                self._walk(frame, app_name, title or (titles[0] if titles else ""), place, out, budget, 0, surfaces)
        return out

    def find(self, name=None, role=None, app=None, window=None, exact=False, states=()):
        """Elements whose name matches (start of name unless exact) and role contains `role`."""
        want = norm(name) if name else None
        hits = []
        for el in self.elements(app=app, window=window):
            if role and role not in el.role:
                continue
            if want is not None:
                have = norm(el.name)
                if not (have == want or (not exact and have.startswith(want))):
                    continue
            if any(s not in el.states for s in states):
                continue
            hits.append(el)
        return hits

    def wait_for(self, name=None, role=None, app=None, window=None, timeout=5.0, exact=False):
        """Poll until an element shows up; returns the first match or None."""
        deadline = time.monotonic() + timeout
        while True:
            hits = self.find(name=name, role=role, app=app, window=window, exact=exact)
            if hits or time.monotonic() > deadline:
                return hits[0] if hits else None
            time.sleep(0.25)

    @staticmethod
    def _placement(frame, pid, title, titles, surfaces):
        """How to turn this top-level's AT-SPI extents into screen pixels.

        Returns (coord_type, dx, dy, clip). GTK 4 on Wayland reports zeros (or
        nonsense) for SCREEN extents but correct WINDOW extents, so those are
        shifted by the compositor's position of that window: the frame for
        normal windows, the buffer for popup menus (matched by process and
        size). Toolkits that report real SCREEN extents (X11 apps) are used as
        they are.
        """
        same_pid = [s for s in surfaces if s.get("pid") == pid]
        if not title:
            # Matched by size only: the compositor and AT-SPI can see different
            # process ids for the same app (the desktop icons do).
            popup = _popup_surface(frame, surfaces)
            if popup:
                bx, by, bw, bh = popup["buffer"]
                return Atspi.CoordType.WINDOW, bx, by, (bx, by, bw, bh), popup
        match = [s for s in same_pid if title and s.get("title") == title] or \
                [s for s in same_pid if s.get("title") in titles and s.get("title")] or same_pid
        clip = None
        if match:
            s = match[0]
            clip = (s["x"], s["y"], s["w"], s["h"])
        if _screen_coords_work(frame) or not match:
            return Atspi.CoordType.SCREEN, 0, 0, None if not title else clip, None
        return Atspi.CoordType.WINDOW, match[0]["x"], match[0]["y"], clip, None

    def _walk(self, node, app_name, title, place, out, budget, depth, surfaces=None):
        if depth > 40 or budget[0] <= 0:
            return
        budget[0] -= 1
        coord, dx, dy, clip, popup = place
        try:
            state = node.get_state_set()
            if not state.contains(Atspi.StateType.SHOWING):
                return
            if popup is not None:
                # A submenu is its own popup window, but AT-SPI files it inside
                # the parent menu with coordinates relative to itself. A container
                # at 0,0 with the size of another popup window starts such a part.
                inner = _popup_surface(node, surfaces or [], exclude=popup)
                if inner:
                    bx, by, bw, bh = inner["buffer"]
                    place = coord, dx, dy, clip, popup = Atspi.CoordType.WINDOW, bx, by, (bx, by, bw, bh), inner
            name = node.get_name() or ""
            role = node.get_role_name() or ""
            if name:
                ext = node.get_extents(coord)
                x, y = ext.x + dx, ext.y + dy
                cx, cy = x + ext.width / 2, y + ext.height / 2
                visible = clip is None or (clip[0] <= cx <= clip[0] + clip[2] and clip[1] <= cy <= clip[1] + clip[3])
                if ext.width > 0 and ext.height > 0 and visible:
                    states = {label for st, label in INTERESTING_STATES.items() if state.contains(st)}
                    out.append(Element(app_name, title, role, name, x, y, ext.width, ext.height, states))
            count = node.get_child_count()
        except GLib.Error:
            return
        for k in range(min(count, 500)):
            try:
                child = node.get_child_at_index(k)
            except GLib.Error:
                continue
            if child is not None:
                self._walk(child, app_name, title, place, out, budget, depth + 1, surfaces)


POPUP_TYPES = {"dropdown_menu", "popup_menu", "menu", "combo", "tooltip", "utility", "override_other", "dialog",
               "modal_dialog"}


def _popup_surface(frame, surfaces, exclude=None):
    """The compositor's popup window for an AT-SPI node at 0,0 with that popup's size."""
    try:
        ext = frame.get_extents(Atspi.CoordType.WINDOW)
    except GLib.Error:
        return None
    if ext.width <= 2 or ext.height <= 2 or (exclude is not None and (ext.x or ext.y)):
        return None
    popups = [s for s in surfaces if s.get("type") in POPUP_TYPES and s is not exclude]
    for s in popups:
        bw, bh = s["buffer"][2], s["buffer"][3]
        if abs(bw - ext.width) <= 2 and abs(bh - ext.height) <= 2:
            return s
    return None


def _screen_coords_work(frame, depth=0):
    """True if some sized descendant reports a non-zero SCREEN position."""
    try:
        ext = frame.get_extents(Atspi.CoordType.SCREEN)
        if (ext.x or ext.y) and ext.width > 0:
            return True
        if depth >= 7:
            return False
        for k in range(min(frame.get_child_count(), 6)):
            child = frame.get_child_at_index(k)
            if child is not None and _screen_coords_work(child, depth + 1):
                return True
    except GLib.Error:
        pass
    return False
