"""Registers the talk shortcut as a GNOME custom keybinding.

GNOME does not let apps grab global keys on Wayland, so the shortcut runs
`pardus-clicky listen`, which forwards to the running app over D-Bus.
"""

from gi.repository import Gio

BASE = "org.gnome.settings-daemon.plugins.media-keys"
PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/pardus-clicky/"


def _available():
    return Gio.SettingsSchemaSource.get_default().lookup(BASE, True) is not None


def ensure(binding, command, name="Pardus Clicky"):
    if not binding or not _available():
        return False
    media = Gio.Settings.new(BASE)
    paths = list(media.get_strv("custom-keybindings"))
    if PATH not in paths:
        media.set_strv("custom-keybindings", paths + [PATH])
    entry = Gio.Settings.new_with_path(f"{BASE}.custom-keybinding", PATH)
    for key, value in (("name", name), ("command", command), ("binding", binding)):
        if entry.get_string(key) != value:
            entry.set_string(key, value)
    Gio.Settings.sync()
    return True


def remove():
    if not _available():
        return
    media = Gio.Settings.new(BASE)
    media.set_strv("custom-keybindings", [p for p in media.get_strv("custom-keybindings") if p != PATH])
    Gio.Settings.new_with_path(f"{BASE}.custom-keybinding", PATH).reset("binding")
    Gio.Settings.sync()
