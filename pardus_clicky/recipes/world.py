"""What recipes need to understand a request: the installed apps, the items on
the desktop, and small parsers for names, on/off, numbers and ordinals."""

import configparser
import os
import re

from gi.repository import Gio, GLib

from ..a11y import norm

# The three icons Pardus puts on every desktop, with what people call them.
SPECIAL_ICONS = {
    "Ev": ("home", "home folder", "my home", "my files", "personal folder", "ev"),
    "Çöp": ("trash", "trash can", "bin", "recycle bin", "rubbish bin", "wastebasket", "cop"),
    "Bilgisayar": ("computer", "my computer", "this computer", "this pc", "drives", "disks", "bilgisayar"),
}

ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10, "last": -1, "next": 0, "another": 0, "different": 0}

# Edition words dropped to get the name people say ("Firefox ESR" -> "firefox").
EDITION_WORDS = {"esr", "lts", "beta", "nightly", "preview", "flatpak", "snap"}
# Executable prefixes that say nothing about the app ("gnome-calculator" -> "calculator").
GENERIC_PREFIXES = {"gnome", "org", "kde", "xdg", "python3", "env", "flatpak", "sh", "bash", "usr", "bin"}


# Suite names whose apps people call by the second word ("LibreOffice Writer" -> "writer").
BRANDS = {"libreoffice", "pardus", "gnu", "gnome"}
# Generic-name endings too vague to identify an app on their own ("File Manager" -> not "manager").
VAGUE = {"manager", "viewer", "program", "application", "tool", "utility", "client", "settings", "center", "app"}


def short_names(name, executable):
    """Extra names an app is called by: without edition words, without its suite name, and its program name."""
    names = set()
    words = norm(name or "").split()
    trimmed = [w for w in words if w not in EDITION_WORDS]
    if trimmed and trimmed != words:
        names.add(" ".join(trimmed))
    if len(trimmed) > 1 and trimmed[0] in BRANDS:
        names.add(" ".join(trimmed[1:]))
    base = os.path.basename((executable or "").split()[0]) if executable else ""
    parts = [p for p in re.split(r"[-_.]+", norm(base)) if p and p not in EDITION_WORDS and not p.isdigit()]
    while parts and parts[0] in GENERIC_PREFIXES:
        parts = parts[1:]
    if parts:
        names.add(" ".join(parts))
    return {n for n in names if len(n) > 2}


def generic_noun(generic_name):
    """'Web Browser' -> 'browser', so 'open the browser' finds Firefox."""
    words = norm(generic_name or "").split()
    return words[-1] if words and len(words[-1]) > 4 and words[-1] not in VAGUE else None


# Words in a window request that don't name an app ("close this window please").
WINDOW_WORDS = set("close quit exit shut minimize minimise maximize maximise restore hide bigger smaller full screen "
                   "this that the a my current active open window windows app application program it please now "
                   "for me can you could would get rid of put away make fill how do i".split())


def names_something(text):
    """True if a window request contains words beyond 'close this window' (an app we don't know, say)."""
    return any(w not in WINDOW_WORDS for w in spaced(text).split())


def spaced(text):
    """Normalized words separated by single spaces, with spaces at both ends."""
    return " " + " ".join(re.sub(r"[^\w.]+", " ", norm(text)).replace(". ", " ").strip(" .").split()) + " "


def has(text, *phrases):
    words = spaced(text)
    return any(spaced(p) in words for p in phrases)


class App:
    def __init__(self, app_id, name, english, terms):
        self.id = app_id
        self.name = name
        self.english = english
        self.terms = terms

    @property
    def spoken(self):
        """'Hesap Makinesi, that's the Calculator' style name for narration."""
        if self.english and norm(self.english) != norm(self.name):
            return f"{self.name}, the {self.english}"
        return self.name

    def __repr__(self):
        return f"<App {self.id} {self.name!r}>"


class World:
    def __init__(self):
        self._apps = None
        self.desktop_dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP) or \
            os.path.join(GLib.get_home_dir(), "Desktop")

    # ---- apps ----

    @property
    def apps(self):
        if self._apps is None:
            self._apps = []
            for info in Gio.AppInfo.get_all():
                if not info.should_show() or not isinstance(info, Gio.DesktopAppInfo):
                    continue
                terms = []
                for value, weight in ((info.get_name(), 3), (info.get_string("Name"), 3),
                                      (info.get_generic_name(), 2), (info.get_string("GenericName"), 2)):
                    if value:
                        terms.append((norm(value), weight))
                keywords = list(info.get_keywords() or []) + (info.get_string("Keywords") or "").split(";")
                terms += [(norm(k), 1) for k in keywords if len(k.strip()) > 2]
                for extra in short_names(info.get_string("Name"), info.get_executable()):
                    terms.append((extra, 2))
                for generic in (info.get_generic_name(), info.get_string("GenericName")):
                    noun = generic_noun(generic)
                    if noun:
                        terms.append((noun, 1))
                self._apps.append(App(info.get_id(), info.get_name(), info.get_string("Name"), terms))
        return self._apps

    def find_app(self, text):
        """The app named in the request (longest, most specific match), or None."""
        words = spaced(text)
        best = None
        for app in self.apps:
            for term, weight in app.terms:
                if len(term) > 2 and spaced(term) in words:
                    score = weight * 100 + len(term)
                    if best is None or score > best[0]:
                        best = (score, app)
        return best[1] if best else None

    def app_by_id(self, app_id):
        return next((a for a in self.apps if a.id == app_id), None)

    # ---- desktop items ----

    def desktop_items(self):
        """Labels of the icons on the desktop, as the desktop shows them."""
        labels = ["Ev", "Çöp"]
        try:
            names = sorted(os.listdir(self.desktop_dir))
        except OSError:
            names = []
        for name in names:
            if name.startswith("."):
                continue
            if name.endswith(".desktop"):
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                try:
                    parser.read(os.path.join(self.desktop_dir, name), encoding="utf-8")
                    entry = parser["Desktop Entry"]
                    lang = (os.environ.get("LANG") or "en").split(".")[0]
                    labels.append(entry.get(f"Name[{lang}]") or entry.get(f"Name[{lang.split('_')[0]}]") or entry.get("Name", name))
                except (KeyError, configparser.Error, OSError):
                    labels.append(name)
            else:
                labels.append(name)
        return labels

    def desktop_files(self):
        """Regular files on the desktop (not folders or launchers), by name."""
        try:
            return [n for n in sorted(os.listdir(self.desktop_dir))
                    if not n.startswith(".") and not n.endswith(".desktop")
                    and os.path.isfile(os.path.join(self.desktop_dir, n))]
        except OSError:
            return []

    def is_folder(self, label):
        return os.path.isdir(os.path.join(self.desktop_dir, label)) or label == "Ev"

    def find_item(self, text, exclude=()):
        """The desktop item named in the request, or None."""
        words = spaced(text)
        best = None
        for label in self.desktop_items():
            if label in exclude:
                continue
            keys = {norm(label), norm(os.path.splitext(label)[0])} | {norm(a) for a in SPECIAL_ICONS.get(label, ())}
            for key in keys:
                if len(key) > 1 and spaced(key) in words and (best is None or len(key) > best[0]):
                    best = (len(key), label)
        return best[1] if best else None

    # ---- small parsers ----

    @staticmethod
    def on_off(text):
        if has(text, "off", "disable", "deactivate", "turn off", "switch off", "stop", "no more"):
            return False
        if has(text, "on", "enable", "activate", "turn on", "switch on", "start", "use"):
            return True
        return None

    @staticmethod
    def name_after(text, *markers):
        """Text after 'called', 'named', ... keeping the user's capitals ('called Projects' -> 'Projects')."""
        markers = markers or ("called", "named", "name it", "titled")
        # Greedy prefix: the last marker wins ("I want to rename it to Work" -> "Work").
        pattern = r"^.*\b(?:" + "|".join(re.escape(m) for m in markers) + r")\s+[\"'“‘]?(.+?)[\"'”’]?\s*[.!?]*\s*$"
        found = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if not found:
            return None
        name = found.group(1).strip().strip("\"'“”‘’").strip()
        name = re.sub(r"^(the|a|an)\s+", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\s+(folder|file|please)$", "", name, flags=re.IGNORECASE)
        return name or None

    @staticmethod
    def ordinal(text):
        words = spaced(text).split()
        for word in words:
            if word in ORDINALS:
                return ORDINALS[word]
            found = re.fullmatch(r"(\d+)(st|nd|rd|th)?", word)
            if found and int(found.group(1)) < 50:
                return int(found.group(1))
        return None

    @staticmethod
    def percent(text):
        found = re.search(r"(\d{1,3})\s*(%|percent|per cent)", text, re.IGNORECASE)
        if found:
            return max(0, min(100, int(found.group(1))))
        if has(text, "half"):
            return 50
        if has(text, "max", "maximum", "full", "all the way up", "loudest"):
            return 100
        return None
