"""Decides who handles a request: an offline recipe first, the online agent
only for what no recipe covers (and only when allowed and online).

config["brain"]: "auto" (recipes, then online), "local" (recipes only, never
online), "cloud" (always the online agent, the session-1 behaviour).
"""

import logging
import threading
import time

from gi.repository import Gio

from . import i18n
from .i18n import _
from .perform import Cancelled
from .recipes.context import Ctx, RecipeFailed
from .shell import ShellError

log = logging.getLogger(__name__)


class Router:
    def __init__(self, hands, a11y, world, config, agent):
        self.hands = hands
        self.a11y = a11y
        self.world = world
        self.config = config
        self.agent = agent
        self.matcher = None
        self.running = False
        self._lock = threading.Lock()

    def set_matcher(self, matcher):
        self.matcher = matcher

    def cloud_ok(self):
        if self.config.get("brain", "auto") == "local" or self.agent is None or not self.config.api_key:
            return False
        return Gio.NetworkMonitor.get_default().get_network_available()

    def handle(self, text):
        d = self.hands.driver
        self.running = True
        started = time.monotonic()
        self.hands.reset()
        try:
            d.clear_drawings()
            d.rings_off()
            brain = self.config.get("brain", "auto")
            match = self.matcher.match(text, self.world) if self.matcher and brain != "cloud" else None
            if match:
                self._run_recipe(text, match)
            elif self.cloud_ok():
                log.info("no recipe; asking the online agent")
                self.agent.run(text)
            else:
                self.hands.say(i18n.text(self.config, "unknown_offline"))
        except Cancelled:
            log.info("task cancelled")
        except ShellError as exc:
            log.error("shell error: %s", exc)
            self._say_quietly(i18n.text(self.config, "error"))
        finally:
            self.running = False
            for fn, args in ((d.rings_off, ()), (d.home, ()), (d.set_state, ("idle",))):
                try:
                    fn(*args)
                except ShellError:
                    pass
            log.info("done in %.1fs", time.monotonic() - started)

    def _run_recipe(self, text, match):
        performer = match.performer or self.config.get("performer", "assistant")
        log.info("recipe %s %s (score %.2f, %s)", match.recipe.id,
                 {k: getattr(v, "id", v) for k, v in match.slots.items()}, match.score, performer)
        ctx = Ctx(self.hands, self.a11y, self.world, self.config, performer)
        try:
            match.recipe.run(ctx, **match.slots)
        except RecipeFailed as exc:
            log.warning("recipe %s stopped: %s", match.recipe.id, exc)
            if self.cloud_ok():
                self.hands.say(_("Let me look at the screen and try another way."))
                self.agent.run(text, note=f"An offline recipe ({match.recipe.id}) tried first and stopped: {exc}")
            else:
                self.hands.say(str(exc))

    def _say_quietly(self, message):
        try:
            self.hands.say(message)
        except (ShellError, Cancelled):
            pass
