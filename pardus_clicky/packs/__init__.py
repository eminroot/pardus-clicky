"""Knowledge packs: short notes about one part of Pardus that are added to the
model's instructions.

Each pack is a Markdown file in this folder whose first line declares which
apps it is about, by desktop-file id or WM_CLASS, lower case:

    <!-- apps: org.gnome.console, kgx -->

A pack declaring "*" is always included (the desktop pack). Other packs are
included while one of their apps has a window open. Adding support for a new
Pardus app usually starts with adding a pack here.
"""

import re
from pathlib import Path

_HEADER = re.compile(r"<!--\s*apps:\s*(.*?)\s*-->")
_DIR = Path(__file__).parent


def _load():
    packs = []
    for path in sorted(_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = _HEADER.match(text)
        apps = {a.strip().lower() for a in match.group(1).split(",")} if match else set()
        body = _HEADER.sub("", text, count=1).strip()
        packs.append((path.stem, apps, body))
    return packs


PACKS = _load()


def relevant(windows):
    """Pack texts for the always-on packs plus packs whose app has an open window."""
    open_ids = set()
    for w in windows:
        for key in ("app_id", "wm_class"):
            value = (w.get(key) or "").lower()
            if value:
                open_ids.add(value)
                open_ids.add(value.removesuffix(".desktop"))
    return [body for _, apps, body in PACKS if "*" in apps or apps & open_ids]
