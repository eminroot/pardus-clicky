"""The online guide: screenshot -> model -> one visible step -> new screenshot.

Used for requests no offline recipe covers (see router.py). Each model turn is
exactly one tool call (see tools.py). Requests are stateless (store=false):
the conversation is kept here, with encrypted reasoning passed back and only
the last few screenshots kept as images.
"""

import json
import logging
import time

from . import i18n, prompts, tools, vision
from .openai_api import ApiError
from .perform import USER_ACTIONS, Cancelled
from .shell import ShellError

log = logging.getLogger(__name__)

KEEP_IMAGES = 2


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


USER_OUTCOMES = {
    "changed": "The user did it: the screen changed.",
    "assistant": "The user asked you to do this step, so you did it.",
    "next": "The user says they did it.",
    "timeout": "The user has not done it after two minutes.",
}


class Agent:
    def __init__(self, api, hands, config):
        self.api = api
        self.hands = hands
        self.driver = hands.driver
        self.config = config

    def run(self, request, note=""):
        """Work on `request` until finished. `note` tells the model what already happened."""
        d = self.driver
        self.hands.check()
        try:
            d.rings_off()
            d.set_state("thinking")
            shot, state = self._look()
            text = prompts.first_message(request, state, shot)
            if note:
                text += f"\n\nNote: {note}"
            items = [{"role": "user", "content": [
                {"type": "input_text", "text": text},
                {"type": "input_image", "image_url": shot.data_url(), "detail": "high"},
            ]}]
            for _ in range(int(self.config.get("max_steps", 30))):
                self.hands.check()
                output = self._think(items, state).get("output", [])
                items.extend(o for o in output if o.get("type") in ("reasoning", "function_call", "message"))
                calls = [o for o in output if o.get("type") == "function_call"]
                if not calls:
                    said = " ".join(c.get("text", "") for o in output if o.get("type") == "message"
                                    for c in o.get("content", []))
                    self.hands.say(said.strip() or i18n.text(self.config, "error"))
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
                    self.hands.say(args.get("say", ""))
                    return
                result = self._dispatch(call["name"], args, shot)
                self.hands.check()
                d.set_state("thinking")
                shot, state = self._look()
                items.append({"type": "function_call_output", "call_id": call["call_id"], "output": [
                    {"type": "input_text", "text": f"{result}\n\n{prompts.describe_state(state, shot)}"},
                    {"type": "input_image", "image_url": shot.data_url(), "detail": "high"},
                ]})
            self.hands.say(i18n.text(self.config, "too_many_steps"))
        except Cancelled:
            log.info("task cancelled")
        except ApiError as exc:
            log.error("api error: %s", exc)
            self._say_safely(i18n.text(self.config, "api_error"))
        except ShellError as exc:
            log.error("shell error: %s", exc)
            self._say_safely(i18n.text(self.config, "error"))

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
        action = args.get("action") or "point"
        performer = args.get("performer") or self.config.get("performer", "assistant")
        target = None
        if args.get("x") is not None and args.get("y") is not None:
            target = shot.to_stage(args["x"], args["y"])
        if action in ("click", "double_click", "right_click", "drag", "point") and target is None:
            return f"Error: {action} needs x and y."
        if action == "drag" and (args.get("x2") is None or args.get("y2") is None):
            return "Error: drag needs x2 and y2."
        end = shot.to_stage(args["x2"], args["y2"]) if action == "drag" else None

        clock = Clock()
        self.hands.show(args.get("say", ""), target, args.get("label", ""))
        clock.mark("show")
        try:
            if action == "point":
                return "Shown to the user."
            if action == "wait":
                time.sleep(1.5)
                return "Waited 1.5 seconds."

            def perform():
                self.hands.act(action, target, end=end, text=args.get("text"), keys=args.get("keys"),
                               amount=args.get("amount"))

            if performer == "user" and action in USER_ACTIONS:
                outcome, reply = self.hands.wait_for_user(target, perform)
                if outcome == "said":
                    return f'While you waited, the user said: "{reply}"'
                return USER_OUTCOMES[outcome]
            perform()
            clock.mark("act")
            return "Done."
        finally:
            log.info("step timing: %s", clock)

    def _draw(self, args, shot):
        d = self.driver
        shapes = [scale_shape(s, shot) for s in args.get("shapes") or []]
        speech = self.hands.speaker.play_async(self.hands.speaker.prefetch(args.get("say", "")))
        if args.get("clear_first"):
            d.clear_drawings()
        d.caption(args.get("say", ""), "say")
        d.set_state("speaking")
        d.draw(shapes)
        speech.wait(60)
        return f"Drew {len(shapes)} shape(s). They stay on screen."

    def _ask(self, args):
        self.hands.say(args.get("question", ""))
        reply = self.hands.listen()
        if not reply:
            return "The user did not answer."
        return f'The user answered: "{reply}"'

    def _say_safely(self, text):
        try:
            self.hands.say(text)
        except (ShellError, Cancelled):
            self.hands.speaker.say(text)
