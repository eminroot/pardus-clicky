"""Pardus Clicky application: panel icon, talk shortcut, listening and tasks.

The app has no main window. It sits in the panel, listens when the shortcut
is pressed, and runs one task at a time on a worker thread. Everything drawn
on screen goes through the shell extension (see shell.py).
"""

import logging
import shlex
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
except (ValueError, ImportError):
    AppIndicator = None

from . import APP_ID, APP_NAME, VERSION, a11y, hotkey, i18n, local_ai, recipes  # noqa: E402
from .a11y import A11y  # noqa: E402
from .agent import Agent  # noqa: E402
from .config import CACHE_DIR, Config  # noqa: E402
from .openai_api import ApiError, OpenAI  # noqa: E402
from .perform import Hands  # noqa: E402
from .recipes.matcher import Matcher  # noqa: E402
from .recipes.world import World  # noqa: E402
from .router import Router  # noqa: E402
from .shell import ShellDriver, ShellError  # noqa: E402
from .voice import Recorder, Speaker  # noqa: E402

log = logging.getLogger("pardus_clicky")

ICON_DIR = Path(__file__).resolve().parent / "data" / "icons"
STT_HINT = ("Pardus, GNOME, desktop, wallpaper, background, dark mode, folder, rename, trash, volume, "
            "Firefox, LibreOffice, Dosyalar, Ayarlar, Resimler, Belgeler, Clicky.")


def launcher_command(sub):
    local = Path(__file__).resolve().parent.parent / "bin" / "pardus-clicky"
    return f"{shlex.quote(str(local))} {sub}" if local.exists() else f"pardus-clicky {sub}"


def setup_logging():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in (RotatingFileHandler(CACHE_DIR / "clicky.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"),
                    logging.StreamHandler(sys.stderr)):
        handler.setFormatter(fmt)
        root.addHandler(handler)


class ClickyApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.config = Config.load()
        self._worker = None
        self._lock = threading.Lock()
        self._listening = False
        self._discard_recording = False
        self._next = None
        self._caption_timer = None
        self._ask_window = None
        self._settings_window = None
        self._indicator = None

    # ---- lifecycle ----

    def do_startup(self):
        Gtk.Application.do_startup(self)
        setup_logging()
        self.hold()
        a11y.run_on_main_loop()
        self.driver = ShellDriver()
        self.recorder = Recorder(self.config.get("mic_device", ""))
        self._build_clients()
        for name, param, handler in (("listen", None, self._on_listen), ("ask", "s", self._on_ask),
                                     ("stop", None, self._on_stop), ("type", None, self._on_type),
                                     ("settings", None, self._on_settings), ("quit", None, self._on_quit)):
            action = Gio.SimpleAction.new(name, GLib.VariantType(param) if param else None)
            action.connect("activate", handler)
            self.add_action(action)
        self._build_indicator()
        try:
            hotkey.ensure(self.config.get("hotkey"), launcher_command("listen"))
        except GLib.Error as exc:
            log.warning("could not register the shortcut: %s", exc.message)
        helper = self.driver.ping()
        log.info("%s %s started, shell helper %s", APP_NAME, VERSION, helper or "missing")
        if not helper:
            self._notify(i18n.text(self.config, "no_shell"))

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        cmd = args[0] if args else ""
        if cmd == "ask" and len(args) > 1:
            self.activate_action("ask", GLib.Variant("s", " ".join(args[1:])))
        elif cmd in ("listen", "stop", "type", "settings", "quit"):
            self.activate_action(cmd, None)
        return 0

    def do_activate(self):
        pass

    def _build_clients(self):
        """Speech and brains: on the computer when the local models are installed, else OpenAI."""
        cfg = self.config
        lang = cfg.get("language", "en")
        i18n.set_language(lang)
        have = local_ai.available(lang)
        engine = cfg.get("voice_engine", "auto")
        local_voice = engine == "local" or (engine == "auto" and have["whisper"] and have["piper"])
        self.api = OpenAI(cfg.api_key, cfg.get("openai_base_url"))
        if local_voice and have["whisper"]:
            self.stt = local_ai.LocalTranscriber(lang, beam_size=int(cfg.get("whisper_beam", 1)))
        else:
            self.stt = local_ai.CloudTranscriber(self.api, cfg) if cfg.api_key else None
        tts = local_ai.PiperTTS(lang) if local_voice and have["piper"] else local_ai.CloudTTS(self.api, cfg)
        self.speaker = Speaker(tts, cfg)
        self.hands = Hands(self.driver, self.speaker, cfg, self.listen_blocking)
        self.agent = Agent(self.api, self.hands, cfg)
        self.world = World()
        self.router = Router(self.hands, A11y(self.driver), self.world, cfg, self.agent)
        self.router.set_matcher(Matcher(recipes.load_all()))
        log.info("voice: %s, understanding: %s, online help: %s",
                 "on this computer" if isinstance(self.stt, local_ai.LocalTranscriber) else "OpenAI",
                 "embeddings" if have["embedder"] else "word overlap", "allowed" if cfg.get("brain", "auto") != "local" else "off")
        threading.Thread(target=self._warm_up, args=(have,), name="warm-up", daemon=True).start()

    def _warm_up(self, have):
        """Load the local models in the background so the first request is fast."""
        try:
            if have["embedder"]:
                self.router.set_matcher(Matcher(recipes.load_all(), local_ai.Embedder()))
            if isinstance(self.stt, local_ai.LocalTranscriber):
                self.stt.load()
            if isinstance(self.speaker.engine, local_ai.PiperTTS):
                self.speaker.engine.load()
            log.info("local models ready")
        except Exception:  # noqa: BLE001 - fall back to what already works
            log.exception("loading local models failed")

    # ---- actions (main thread) ----

    def _on_listen(self, *_):
        if self._listening:
            self.recorder.stop()
        elif self.router.running:
            if self.hands.waiting_for_user:
                self.hands.interject()
            else:
                self._run_next(self._listen_and_run)
                self.hands.cancel()
        else:
            self._run_next(self._listen_and_run)

    def _on_ask(self, _action, param):
        text = param.get_string().strip()
        if not text:
            return
        self._run_next(lambda: self._run_request(text))
        if self.router.running:
            self.hands.cancel()

    def _on_stop(self, *_):
        if self._listening:
            self._discard_recording = True
            self.recorder.stop()
        if self.router.running:
            self.hands.cancel()
        else:
            self._clear_drawings()

    def _on_type(self, *_):
        if self._ask_window is None:
            self._ask_window = AskWindow(self)
        self._ask_window.present_fresh()

    def _on_settings(self, *_):
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self)
        self._settings_window.show_all()
        self._settings_window.present()

    def _on_quit(self, *_):
        self._on_stop()
        try:
            self.driver.caption("", "")
            self.driver.set_state("idle")
        except ShellError:
            pass
        self.quit()

    # ---- the worker ----

    def _run_next(self, fn):
        """Run fn on the worker thread now, or right after the current task stops."""
        with self._lock:
            self._next = fn
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._work, name="clicky-task", daemon=True)
            self._worker.start()

    def _work(self):
        while True:
            with self._lock:
                fn, self._next = self._next, None
                if fn is None:
                    self._worker = None
                    break
            if self._caption_timer:
                self._caption_timer.cancel()
            try:
                if self._ready():
                    fn()
            except Exception:  # noqa: BLE001 - keep the app alive whatever a task does
                log.exception("task failed")
                self._caption(i18n.text(self.config, "error"))
        self._caption_timer = threading.Timer(4.0, self._tidy_up)
        self._caption_timer.start()

    def _tidy_up(self, drawings_after=16.0):
        """After a task: hide the caption now, and the sketches a little later."""
        self._caption("")
        self._caption_timer = threading.Timer(drawings_after, self._clear_drawings)
        self._caption_timer.start()

    def _clear_drawings(self):
        try:
            self.driver.clear_drawings()
        except ShellError:
            pass

    def _ready(self):
        if not self.driver.ping():
            self._notify(i18n.text(self.config, "no_shell"))
            return False
        return True

    def _listen_and_run(self):
        if self.stt is None:
            self._caption(i18n.text(self.config, "no_key"))
            GLib.idle_add(self._on_settings)
            return
        text = self.listen_blocking()
        if text:
            self._run_request(text)

    def _run_request(self, text):
        log.info("request: %s", text)
        self.router.handle(text)

    def listen_blocking(self):
        """Record one utterance and return its text, or None. Runs on the worker thread."""
        d = self.driver
        self._listening = True
        self._discard_recording = False
        def ready():
            d.set_state("listening")
            d.caption(i18n.text(self.config, "listening"), "hint")

        try:
            d.set_state("thinking")
            d.caption(i18n.text(self.config, "warming"), "hint")
            wav = self.recorder.record(on_level=self._level, on_ready=ready)
        finally:
            self._listening = False
        if not wav or self._discard_recording:
            d.caption(i18n.text(self.config, "heard_nothing") if not self._discard_recording else "", "hint")
            d.set_state("idle")
            return None
        d.set_state("thinking")
        started = time.monotonic()
        try:
            # Names on the desktop help the recognizer spell them the way they are written.
            hint = STT_HINT + " " + ", ".join(self.world.desktop_items()[:20])
            text = self.stt.transcribe(wav, language=self.config.get("language"), prompt=hint)
        except (ApiError, OSError, RuntimeError, ValueError) as exc:
            log.error("transcription failed: %s", exc)
            d.caption(i18n.text(self.config, "api_error"), "hint")
            d.set_state("idle")
            return None
        log.info("heard in %.2fs: %s", time.monotonic() - started, text)
        if not text:
            d.caption(i18n.text(self.config, "heard_nothing"), "hint")
            d.set_state("idle")
            return None
        d.caption(text, "heard")
        return text

    def _level(self, level):
        try:
            self.driver.set_level(level)
        except ShellError:
            pass

    def _caption(self, text):
        try:
            self.driver.caption(text, "hint")
        except ShellError:
            pass

    def _notify(self, body):
        note = Gio.Notification.new(APP_NAME)
        note.set_body(body)
        self.send_notification("clicky", note)

    # ---- panel icon ----

    def _build_indicator(self):
        if AppIndicator is None:
            log.warning("AyatanaAppIndicator3 is not available; no panel icon")
            return
        self._indicator = AppIndicator.Indicator.new(APP_ID, "tr.org.pardus.clicky-panel",
                                                     AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self._indicator.set_icon_theme_path(str(ICON_DIR))
        self._indicator.set_title(APP_NAME)
        self._indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self._rebuild_menu()

    def _rebuild_menu(self):
        if self._indicator is None:
            return
        menu = Gtk.Menu()
        shortcut = Gtk.accelerator_get_label(*Gtk.accelerator_parse(self.config.get("hotkey") or ""))
        for key, action, suffix in (("menu_talk", "listen", f"   {shortcut}" if shortcut else ""),
                                    ("menu_type", "type", ""), ("menu_stop", "stop", ""), (None, None, None),
                                    ("menu_settings", "settings", ""), ("menu_quit", "quit", "")):
            if key is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            item = Gtk.MenuItem(label=i18n.text(self.config, key) + suffix)
            item.connect("activate", lambda _w, a=action: self.activate_action(a, None))
            menu.append(item)
        menu.show_all()
        self._indicator.set_menu(menu)

    def apply_settings(self):
        self.config.save()
        self._build_clients()
        self.recorder.device = self.config.get("mic_device", "")
        self._rebuild_menu()
        try:
            hotkey.ensure(self.config.get("hotkey"), launcher_command("listen"))
        except GLib.Error as exc:
            log.warning("could not register the shortcut: %s", exc.message)


class AskWindow(Gtk.Window):
    """Type a request instead of speaking it."""

    def __init__(self, app):
        super().__init__(title=APP_NAME, application=app)
        self.app = app
        self.set_default_size(560, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_keep_above(True)
        self.set_resizable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(18)
        self.title = Gtk.Label(xalign=0)
        self.entry = Gtk.Entry()
        self.entry.connect("activate", self._submit)
        box.pack_start(self.title, False, False, 0)
        box.pack_start(self.entry, False, False, 0)
        self.add(box)
        self.connect("delete-event", lambda *_: self.hide() or True)
        self.connect("key-press-event", self._on_key)

    def present_fresh(self):
        cfg = self.app.config
        self.title.set_markup(f"<b>{GLib.markup_escape_text(i18n.text(cfg, 'ask_title'))}</b>")
        self.entry.set_placeholder_text(i18n.text(cfg, "ask_hint"))
        self.entry.set_text("")
        self.show_all()
        self.present()
        self.entry.grab_focus()

    def _on_key(self, _w, event):
        from gi.repository import Gdk
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def _submit(self, entry):
        text = entry.get_text().strip()
        self.hide()
        if text:
            # Let the window vanish before the first screenshot is taken.
            GLib.timeout_add(400, lambda: self.app.activate_action("ask", GLib.Variant("s", text)) and False)


class SettingsWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title=i18n.text(app.config, "settings_title"), application=app)
        self.app = app
        cfg = app.config
        self.set_default_size(480, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(False)
        grid = Gtk.Grid(column_spacing=14, row_spacing=12)
        grid.set_border_width(20)

        self.key = Gtk.Entry(visibility=False, hexpand=True)
        self.key.set_placeholder_text("sk-..." if not cfg.api_key else i18n.text(cfg, "key_saved"))
        self.language = Gtk.ComboBoxText()
        self.language.append("en", "English")
        self.language.append("tr", "Türkçe")
        self.language.set_active_id(cfg.get("language", "en"))
        self.speak = Gtk.Switch(active=bool(cfg.get("speak", True)), halign=Gtk.Align.START)
        self.performer = Gtk.ComboBoxText()
        self.performer.append("assistant", i18n.text(cfg, "performer_assistant"))
        self.performer.append("user", i18n.text(cfg, "performer_user"))
        self.performer.set_active_id(cfg.get("performer", "assistant"))
        self.shortcut = Gtk.Entry(text=cfg.get("hotkey", ""))
        self.online = Gtk.Switch(active=cfg.get("brain", "auto") != "local", halign=Gtk.Align.START)

        rows = (("settings_online", self.online), ("settings_key", self.key), ("settings_language", self.language),
                ("settings_speak", self.speak), ("settings_performer", self.performer),
                ("settings_shortcut", self.shortcut))
        for i, (label, widget) in enumerate(rows):
            grid.attach(Gtk.Label(label=i18n.text(cfg, label), xalign=0), 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)
        save = Gtk.Button(label=i18n.text(cfg, "save"), halign=Gtk.Align.END)
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._save)
        grid.attach(save, 1, len(rows), 1, 1)
        self.add(grid)
        self.connect("delete-event", lambda *_: self.hide() or True)

    def _save(self, _button):
        cfg = self.app.config
        if self.key.get_text().strip():
            Config.set_api_key(self.key.get_text())
            self.key.set_text("")
            self.key.set_placeholder_text(i18n.text(cfg, "key_saved"))
        cfg["language"] = self.language.get_active_id() or "en"
        cfg["speak"] = self.speak.get_active()
        cfg["performer"] = self.performer.get_active_id() or "assistant"
        cfg["hotkey"] = self.shortcut.get_text().strip()
        cfg["brain"] = "auto" if self.online.get_active() else "local"
        self.app.apply_settings()
        self.hide()


def main(argv):
    return ClickyApp().run(argv)
