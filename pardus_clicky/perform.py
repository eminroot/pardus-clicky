"""Visible actions, shared by the offline recipes and the online agent.

A step always looks the same to the user: the pointer flies to the target
while a short sentence is spoken and captioned, then the real pointer or
keyboard does the action (Clicky does it), or Clicky rings the target and
waits until the screen shows the user did it (guide mode).
"""

import logging
import threading
import time

from . import i18n, vision

log = logging.getLogger(__name__)

WATCH_INTERVAL = 0.6
USER_WAIT_LIMIT = 120.0
NUDGE_AFTER = 25.0
CHANGE_THRESHOLD = 0.006
USER_ACTIONS = ("click", "double_click", "right_click", "drag", "scroll", "type", "keys")


class Cancelled(Exception):
    """The user stopped the task (shortcut, Stop menu item or "stop")."""


def split_combos(keys):
    """'ctrl+a, BackSpace' -> ['ctrl+a', 'BackSpace']. Commas or spaces separate key presses."""
    return [c for c in keys.replace(",", " ").split() if c.strip("+")]


class Hands:
    def __init__(self, driver, speaker, config, listen):
        self.driver = driver
        self.speaker = speaker
        self.config = config
        self.listen = listen
        self.cancel_event = threading.Event()
        self.interjection = threading.Event()
        self.waiting_for_user = False

    # ---- control ----

    def reset(self):
        self.cancel_event.clear()
        self.interjection.clear()

    def cancel(self):
        self.cancel_event.set()
        self.speaker.stop()

    def interject(self):
        """The user pressed the shortcut while Clicky waits for them to do a step."""
        self.interjection.set()

    def check(self):
        if self.cancel_event.is_set():
            raise Cancelled()

    # ---- speaking and showing ----

    def say(self, text):
        if not text:
            return
        speech = self.speaker.prefetch(text)
        self.driver.caption(text, "say")
        self.driver.set_state("speaking")
        self.speaker.play(speech)
        self.check()

    def show(self, say, target=None, label=""):
        """Fly to the target (screen coordinates) with a label while `say` is spoken."""
        speech = self.speaker.play_async(self.speaker.prefetch(say))
        self.driver.caption(say, "say")
        self.driver.set_state("speaking")
        if target:
            self.driver.fly_to(*target, label)
        speech.wait(60)
        self.check()

    # ---- doing ----

    def act(self, action, target=None, end=None, text=None, keys=None, amount=None):
        """Do an action with the real pointer or keyboard, then wait for the screen to settle."""
        d = self.driver
        d.set_state("acting")
        if action in ("click", "double_click", "right_click"):
            d.glide(*target)
            d.ring(*target, "click")
            d.click("right" if action == "right_click" else "left", 2 if action == "double_click" else 1)
        elif action == "drag":
            d.glide(*target)
            d.button("left", True)
            time.sleep(0.2)
            d.glide(*end, 900)
            time.sleep(0.25)
            d.button("left", False)
        elif action == "scroll":
            if target:
                d.glide(*target)
            d.scroll(amount or 3)
        elif action == "type":
            # No click here: a click would drop a selection the user expects to
            # be replaced (rename boxes open with the old name selected).
            if target:
                d.glide(*target)
            d.type_text(text or "")
        elif action == "keys":
            for combo in split_combos(keys or ""):
                d.keys(combo)
                time.sleep(0.12)
        self.settle()
        d.home()

    def settle(self, max_wait=3.0):
        """Wait until the screen stops changing after an action (menus, windows opening)."""
        time.sleep(0.6)
        previous = vision.fingerprint(self.driver)
        started = time.monotonic()
        while time.monotonic() - started < max_wait:
            time.sleep(0.3)
            current = vision.fingerprint(self.driver)
            if previous.changed_fraction(current) < 0.002:
                return
            previous = current

    def wait_for_user(self, target, perform):
        """Guide mode: ring the target and wait for the user to act.

        Returns (outcome, reply): "changed" when the screen changed, "assistant"
        when the user said "do it" (and `perform()` was run), "next" when they
        said they did it, "said" with their words, or "timeout".
        """
        d = self.driver
        self.waiting_for_user = True
        if target:
            d.ring(*target, "attention")
        d.set_state("waiting")
        try:
            base = vision.fingerprint(d)
            started = time.monotonic()
            nudged = False
            while True:
                self.check()
                if self.interjection.is_set():
                    self.interjection.clear()
                    reply = self.listen()
                    verdict = i18n.classify(reply, self.config.get("language", "en"))
                    if verdict == "stop":
                        raise Cancelled()
                    if verdict == "do_it":
                        d.rings_off()
                        perform()
                        return "assistant", reply
                    if verdict == "next":
                        return "next", reply
                    if reply:
                        return "said", reply
                    d.set_state("waiting")
                    base = vision.fingerprint(d)
                    continue
                time.sleep(WATCH_INTERVAL)
                if base.changed_fraction(vision.fingerprint(d)) > CHANGE_THRESHOLD:
                    time.sleep(0.6)
                    return "changed", None
                elapsed = time.monotonic() - started
                if not nudged and elapsed > NUDGE_AFTER:
                    nudged = True
                    self.say(i18n.text(self.config, "nudge"))
                    d.set_state("waiting")
                    base = vision.fingerprint(d)
                if elapsed > USER_WAIT_LIMIT:
                    return "timeout", None
        finally:
            self.waiting_for_user = False
            d.rings_off()
