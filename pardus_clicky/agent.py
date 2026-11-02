"""The guide's loop: screenshot -> model -> one visible step -> new screenshot.

Each model turn is exactly one tool call (see tools.py). Requests are
stateless (store=false): the conversation is kept here, with encrypted
reasoning passed back and only the last few screenshots kept as images.
"""

import json
import logging
import threading
import time

from . import i18n, prompts, tools, vision
from .openai_api import ApiError
from .shell import ShellError

log = logging.getLogger(__name__)

KEEP_IMAGES = 2
WATCH_INTERVAL = 0.6
USER_WAIT_LIMIT = 120.0
NUDGE_AFTER = 25.0
CHANGE_THRESHOLD = 0.006
USER_ACTIONS = ("click", "double_click", "right_click", "drag", "scroll", "type", "keys")


class Cancelled(Exception):
    pass


class Clock:
    """Collects how long each phase of a step took, for the log."""

    def __init__(self):
        self._t = time.monotonic()
        self._parts = []

    def mark(self, name):
        now = time.monotonic()
        self._parts.append(f"{name} {now - self._t:.2f}s")
        self._t = now

    def __str__(self):
        return ", ".join(self._parts)


def trim_images(items, keep=KEEP_IMAGES):
    """Copy of the conversation where only the newest `keep` screenshots stay images."""
    seen = 0
    out = []
    for item in reversed(items):
        content = item.get("content") if item.get("role") == "user" else item.get("output") \
            if item.get("type") == "function_call_output" else None
        if isinstance(content, list) and any(p.get("type") == "input_image" for p in content):
            seen += 1
            if seen > keep:
                stripped = [p if p.get("type") != "input_image" else {"type": "input_text", "text": "(older screenshot removed)"}
                            for p in content]
                item = dict(item, **({"content": stripped} if "content" in item else {"output": stripped}))
        out.append(item)
    out.reverse()
    return out


def split_combos(keys):
    """'ctrl+a, BackSpace' -> ['ctrl+a', 'BackSpace']. Commas or spaces separate key presses."""
    return [c for c in keys.replace(",", " ").split() if c.strip("+")]


def scale_shape(shape, shot):
    """Map a draw-tool shape from screenshot pixels to screen coordinates."""
    k = shot.stage_width / shot.width
    out = {"kind": shape.get("kind"), "color": shape.get("color") or "coral"}
    if shape.get("text"):
        out["text"] = shape["text"]
    out["x"], out["y"] = shot.to_stage(shape.get("x") or 0, shape.get("y") or 0)
    if shape.get("x2") is not None and shape.get("y2") is not None:
        out["x2"], out["y2"] = shot.to_stage(shape["x2"], shape["y2"])
    if shape.get("r") is not None:
        out["r"] = shape["r"] * k
    if shape.get("points"):
        out["points"] = [list(shot.to_stage(p[0], p[1])) for p in shape["points"] if len(p) >= 2]
    if out["kind"] == "text":
        out["size"] = 22 * k
    return out


class Agent:
    def __init__(self, api, driver, speaker, config, listen):
        self.api = api
        self.driver = driver
        self.speaker = speaker
        self.config = config
        self.listen = listen
        self.running = False
        self.waiting_for_user = False
        self._cancel = threading.Event()
        self._interject = threading.Event()

    # ---- control from the app ----

    def cancel(self):
        self._cancel.set()
        self.speaker.stop()

    def interject(self):
        """The user pressed the hotkey while Clicky waits for them to do a step."""
        self._interject.set()

    # ---- the loop ----

    def run(self, request):
        self.running = True
        self._cancel.clear()
        self._interject.clear()
        d = self.driver
        try:
            d.clear_drawings()
            d.rings_off()
            d.set_state("thinking")
            shot, state = self._look()
            items = [{"role": "user", "content": [
                {"type": "input_text", "text": prompts.first_message(request, state, shot)},
                {"type": "input_image", "image_url": shot.data_url(), "detail": "high"},
            ]}]
            for _ in range(int(self.config.get("max_steps", 30))):
                self._check()
                output = self._think(items, state).get("output", [])
                items.extend(o for o in output if o.get("type") in ("reasoning", "function_call", "message"))
                calls = [o for o in output if o.get("type") == "function_call"]
                if not calls:
                    said = " ".join(c.get("text", "") for o in output if o.get("type") == "message"
                                    for c in o.get("content", []))
                    self._say(said.strip() or i18n.text(self.config, "error"))
                    return
                call = calls[0]
                for extra in calls[1:]:
                    items.append({"type": "function_call_output", "call_id": extra["call_id"],
                                  "output": "Skipped: one step per turn."})
                try:
                    args = json.loads(call.get("arguments") or "{}")
                except ValueError:
                    args = {}
                log.info("tool %s %s", call["name"], json.dumps(args, ensure_ascii=False)[:300])
                if call["name"] == "finish":
                    self._say(args.get("say", ""))
                    return
                result = self._dispatch(call["name"], args, shot)
                self._check()
                d.set_state("thinking")
                shot, state = self._look()
                items.append({"type": "function_call_output", "call_id": call["call_id"], "output": [
                    {"type": "input_text", "text": f"{result}\n\n{prompts.describe_state(state, shot)}"},
                    {"type": "input_image", "image_url": shot.data_url(), "detail": "high"},
                ]})
            self._say(i18n.text(self.config, "too_many_steps"))
        except Cancelled:
            log.info("task cancelled")
        except ApiError as exc:
            log.error("api error: %s", exc)
            self._say_safely(i18n.text(self.config, "api_error"))
        except ShellError as exc:
            log.error("shell error: %s", exc)
            self._say_safely(i18n.text(self.config, "error"))
        finally:
            self.running = False
            self.waiting_for_user = False
            for fn, args in ((d.rings_off, ()), (d.home, ()), (d.set_state, ("idle",))):
                try:
                    fn(*args)
                except ShellError:
                    pass

    def _check(self):
        if self._cancel.is_set():
            raise Cancelled()

    def _look(self):
        started = time.monotonic()
        shot = vision.capture(self.driver)
        state = self.driver.state()
        log.info("look %.2fs", time.monotonic() - started)
        return shot, state

    def _think(self, items, state):
        payload = {
            "model": self.config["model"],
            "instructions": prompts.instructions(self.config, state.get("windows", [])),
            "input": trim_images(items),
            "tools": tools.ALL,
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "reasoning": {"effort": self.config.get("reasoning_effort", "low")},
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        started = time.monotonic()
        response = self.api.respond(payload)
        usage = response.get("usage", {})
        log.info("model %.1fs, tokens in %s out %s", time.monotonic() - started,
                 usage.get("input_tokens"), usage.get("output_tokens"))
        return response

    def _dispatch(self, name, args, shot):
        try:
            if name == "step":
                return self._step(args, shot)
            if name == "draw":
                return self._draw(args, shot)
            if name == "ask_user":
                return self._ask(args)
            return f"Unknown tool {name}."
        except ShellError as exc:
            # Tell the model what failed (a bad key name, say) so it can try another way.
            log.warning("step failed: %s", exc)
            return f"That step failed: {exc}. Nothing was done; try another way."

    # ---- tools ----

    def _step(self, args, shot):
        d = self.driver
        action = args.get("action") or "point"
        performer = args.get("performer") or self.config.get("performer", "assistant")
        target = None
        if args.get("x") is not None and args.get("y") is not None:
            target = shot.to_stage(args["x"], args["y"])
        if action in ("click", "double_click", "right_click", "drag", "point") and target is None:
            return f"Error: {action} needs x and y."
        if action == "drag" and (args.get("x2") is None or args.get("y2") is None):
            return "Error: drag needs x2 and y2."

        clock = Clock()
        speech = self.speaker.play_async(self.speaker.prefetch(args.get("say", "")))
        d.caption(args.get("say", ""), "say")
        d.set_state("speaking")
        if target:
            d.fly_to(*target, args.get("label", ""))
            clock.mark("fly")
        speech.wait(60)
        clock.mark("speech")
        self._check()

        try:
            if action == "point":
                return "Shown to the user."
            if action == "wait":
                time.sleep(1.5)
                return "Waited 1.5 seconds."
            if performer == "user" and action in USER_ACTIONS:
                return self._wait_for_user(action, target, args, shot)
            d.set_state("acting")
            self._perform(action, target, args, shot)
            clock.mark("act")
            self._settle()
            clock.mark("settle")
            d.home()
            return "Done."
        finally:
            log.info("step timing: %s", clock)

    def _perform(self, action, target, args, shot):
        d = self.driver
        if action in ("click", "double_click", "right_click"):
            d.glide(*target)
            d.ring(*target, "click")
            d.click("right" if action == "right_click" else "left", 2 if action == "double_click" else 1)
        elif action == "drag":
            end = shot.to_stage(args["x2"], args["y2"])
            d.glide(*target)
            d.button("left", True)
            time.sleep(0.2)
            d.glide(*end, 900)
            time.sleep(0.2)
            d.button("left", False)
        elif action == "scroll":
            if target:
                d.glide(*target)
            d.scroll(args.get("amount") or 3)
        elif action == "type":
            # No click here: a click would drop a selection the user expects to
            # be replaced (rename boxes open with the old name selected).
            if target:
                d.glide(*target)
            d.type_text(args.get("text") or "")
        elif action == "keys":
            for combo in split_combos(args.get("keys") or ""):
                d.keys(combo)
                time.sleep(0.12)

    def _settle(self, max_wait=3.0):
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

    def _wait_for_user(self, action, target, args, shot):
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
                self._check()
                if self._interject.is_set():
                    self._interject.clear()
                    reply = self.listen()
                    verdict = i18n.classify(reply, self.config.get("language", "en"))
                    if verdict == "stop":
                        raise Cancelled()
                    if verdict == "do_it":
                        d.rings_off()
                        d.set_state("acting")
                        self._perform(action, target, args, shot)
                        self._settle()
                        d.home()
                        return "The user asked you to do this step, so you did it."
                    if verdict == "next":
                        return "The user says they did it."
                    if reply:
                        return f'While you waited, the user said: "{reply}"'
                    d.set_state("waiting")
                    base = vision.fingerprint(d)
                    continue
                time.sleep(WATCH_INTERVAL)
                if base.changed_fraction(vision.fingerprint(d)) > CHANGE_THRESHOLD:
                    time.sleep(0.6)
                    return "The user did it: the screen changed."
                elapsed = time.monotonic() - started
                if not nudged and elapsed > NUDGE_AFTER:
                    nudged = True
                    self._say(i18n.text(self.config, "nudge"))
                    d.set_state("waiting")
                    base = vision.fingerprint(d)
                if elapsed > USER_WAIT_LIMIT:
                    return "The user has not done it after two minutes."
        finally:
            self.waiting_for_user = False
            d.rings_off()

    def _draw(self, args, shot):
        d = self.driver
        shapes = [scale_shape(s, shot) for s in args.get("shapes") or []]
        speech = self.speaker.play_async(self.speaker.prefetch(args.get("say", "")))
        if args.get("clear_first"):
            d.clear_drawings()
        d.caption(args.get("say", ""), "say")
        d.set_state("speaking")
        d.draw(shapes)
        speech.wait(60)
        return f"Drew {len(shapes)} shape(s). They stay on screen."

    def _ask(self, args):
        self._say(args.get("question", ""))
        reply = self.listen()
        if not reply:
            return "The user did not answer."
        return f'The user answered: "{reply}"'

    def _say(self, text):
        if not text:
            return
        speech = self.speaker.prefetch(text)
        self.driver.caption(text, "say")
        self.driver.set_state("speaking")
        self.speaker.play(speech)

    def _say_safely(self, text):
        try:
            self._say(text)
        except ShellError:
            self.speaker.say(text)
