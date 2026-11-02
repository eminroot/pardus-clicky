"""Unit tests for the parts that do not need a running desktop.
Run on Pardus (the modules import PyGObject):  python3 -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pardus_clicky import i18n, packs, prompts, tools  # noqa: E402
from pardus_clicky.agent import scale_shape, split_combos, trim_images  # noqa: E402
from pardus_clicky.vision import Shot  # noqa: E402
from pardus_clicky.voice import Endpointer  # noqa: E402


def run_endpointer(levels, **kw):
    ep = Endpointer(**kw)
    for level in levels:
        result = ep.feed(level)
        if result:
            return result, ep
    return None, ep


class EndpointerTest(unittest.TestCase):
    def test_speech_then_silence_ends(self):
        frames = [80] * 20 + [3000] * 50 + [80] * 60  # 0.4 s quiet, 1 s speech, 1.2 s quiet
        result, ep = run_endpointer(frames)
        self.assertEqual(result, "end")
        self.assertAlmostEqual(ep.started_at, 0.4 - 0.3 + 0.06, delta=0.1)

    def test_silence_times_out(self):
        result, ep = run_endpointer([80] * 500, start_timeout=3.0)
        self.assertEqual(result, "timeout")
        self.assertIsNone(ep.started_at)

    def test_user_talking_from_the_first_frame_is_heard(self):
        # Noise floor is capped, so loud first frames do not hide the speech.
        result, ep = run_endpointer([4000] * 60 + [80] * 60)
        self.assertEqual(result, "end")
        self.assertIsNotNone(ep.started_at)

    def test_short_click_is_not_speech(self):
        result, ep = run_endpointer([80] * 20 + [5000] * 2 + [80] * 400, start_timeout=3.0)
        self.assertEqual(result, "timeout")


class ClassifyTest(unittest.TestCase):
    def test_english(self):
        self.assertEqual(i18n.classify("Do it for me.", "en"), "do_it")
        self.assertEqual(i18n.classify("Okay!", "en"), "next")
        self.assertEqual(i18n.classify("stop", "en"), "stop")
        self.assertIsNone(i18n.classify("what does this button do when I press it twice", "en"))
        self.assertIsNone(i18n.classify("", "en"))

    def test_turkish(self):
        self.assertEqual(i18n.classify("Sen yap.", "tr"), "do_it")
        self.assertEqual(i18n.classify("tamam", "tr"), "next")
        self.assertEqual(i18n.classify("Dur!", "tr"), "stop")

    def test_stop_wins_over_next(self):
        self.assertEqual(i18n.classify("okay stop", "en"), "stop")


class AgentHelpersTest(unittest.TestCase):
    def test_trim_keeps_newest_images(self):
        img = {"type": "input_image", "image_url": "data:x"}
        items = [{"role": "user", "content": [{"type": "input_text", "text": "hi"}, img]}]
        for i in range(3):
            items.append({"type": "function_call", "call_id": str(i), "name": "step", "arguments": "{}"})
            items.append({"type": "function_call_output", "call_id": str(i), "output": [{"type": "input_text", "text": "ok"}, img]})
        trimmed = trim_images(items, keep=2)
        images = [p for it in trimmed for p in (it.get("content") or it.get("output") or [])
                  if isinstance(p, dict) and p.get("type") == "input_image"]
        self.assertEqual(len(images), 2)
        self.assertEqual(trimmed[0]["content"][1]["type"], "input_text")
        self.assertIs(items[0]["content"][1], img, "the original list must not be modified")

    def test_split_combos(self):
        self.assertEqual(split_combos("ctrl+a, BackSpace"), ["ctrl+a", "BackSpace"])
        self.assertEqual(split_combos("Return"), ["Return"])
        self.assertEqual(split_combos(" , "), [])

    def test_scale_shape_maps_to_screen(self):
        shot = Shot(b"", 960, 540, 1920, 1080)
        out = scale_shape({"kind": "circle", "x": 100, "y": 50, "x2": None, "y2": None, "r": 20,
                           "text": None, "points": None, "color": "blue"}, shot)
        self.assertEqual((out["x"], out["y"], out["r"]), (200, 100, 40))
        path = scale_shape({"kind": "path", "x": 0, "y": 0, "x2": None, "y2": None, "r": None, "text": None,
                            "points": [[10, 10], [20, 30]], "color": "green"}, shot)
        self.assertEqual(path["points"], [[20, 20], [40, 60]])


class ShotTest(unittest.TestCase):
    def test_mapping_and_clamping(self):
        shot = Shot(b"", 1280, 720, 2560, 1440)
        self.assertEqual(shot.to_stage(640, 360), (1280, 720))
        self.assertEqual(shot.to_stage(5000, -10), (1279 * 2, 0))
        self.assertEqual(shot.from_stage(1280, 720), (640, 360))


class PromptTest(unittest.TestCase):
    def test_state_description_uses_screenshot_pixels(self):
        shot = Shot(b"", 960, 540, 1920, 1080)
        state = {"pointer": [1000, 500], "overview": False, "windows": [
            {"app": "Dosyalar", "title": "Projects", "x": 400, "y": 200, "w": 800, "h": 600, "focused": True}]}
        text = prompts.describe_state(state, shot)
        self.assertIn("(500, 250)", text)
        self.assertIn('Dosyalar: "Projects" at (200, 100) size 400x300 [focused]', text)

    def test_instructions_include_language_and_desktop_pack(self):
        text = prompts.instructions({"language": "en", "performer": "assistant"}, [])
        self.assertIn("Speak English", text)
        self.assertIn("Uygulamaları Göster", text)


class PacksTest(unittest.TestCase):
    def test_app_pack_only_when_window_open(self):
        saved = packs.PACKS
        try:
            packs.PACKS = [("desktop", {"*"}, "DESK"), ("console", {"org.gnome.console"}, "CONSOLE")]
            self.assertEqual(packs.relevant([]), ["DESK"])
            self.assertEqual(packs.relevant([{"app_id": "org.gnome.Console.desktop"}]), ["DESK", "CONSOLE"])
        finally:
            packs.PACKS = saved


class ToolSchemaTest(unittest.TestCase):
    def check_strict(self, schema, where):
        if isinstance(schema, dict):
            if schema.get("type") == "object" or "object" in (schema.get("type") or []):
                props = schema.get("properties", {})
                self.assertEqual(set(schema.get("required", [])), set(props), f"{where}: strict mode needs every property required")
                self.assertIs(schema.get("additionalProperties"), False, f"{where}: additionalProperties must be false")
            for key, value in schema.items():
                self.check_strict(value, f"{where}.{key}")
        elif isinstance(schema, list):
            for i, value in enumerate(schema):
                self.check_strict(value, f"{where}[{i}]")

    def test_all_tools_are_strict_valid(self):
        for tool in tools.ALL:
            self.assertTrue(tool["strict"])
            self.check_strict(tool["parameters"], tool["name"])


if __name__ == "__main__":
    unittest.main()
