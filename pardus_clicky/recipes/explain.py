"""Explaining the desktop: a guided tour, 'where is ...', and what Clicky can do."""

from ..i18n import _
from . import recipe
from .world import spaced

# What people ask about -> how to find it -> what to say. Order matters for the tour.
THINGS = [
    (("app menu", "start menu", "applications", "all apps", "all my apps", "pardus button", "pardus menu", "app grid",
      "launcher", "apps"),
     lambda c: c.shell("Uygulamaları Göster", timeout=1),
     "This is the Pardus button. It opens all your apps."),
    (("firefox", "browser", "web browser", "internet browser"),
     lambda c: c.shell(app_id="firefox-esr.desktop", type_="TaskbarAppIcon", timeout=0),
     "This is Firefox, the web browser."),
    (("files app", "file manager", "dosyalar"),
     lambda c: c.shell(app_id="org.gnome.Nautilus.desktop", type_="TaskbarAppIcon", timeout=0),
     "This is Dosyalar, the file manager."),
    (("software center", "app store", "store", "install apps", "install programs", "software"),
     lambda c: c.shell(app_id="tr.org.pardus.software.desktop", type_="TaskbarAppIcon", timeout=0),
     "This is the Pardus Software Center. New apps are installed from here."),
    (("clock", "time", "date", "calendar", "notifications", "notification"),
     lambda c: c.shell(type_="DateMenuButton", timeout=0),
     "This is the clock. Click it for the calendar and your notifications."),
    (("volume", "sound", "network", "internet", "wifi", "wi fi", "power", "battery", "shut down", "shutdown",
      "system menu", "quick settings", "settings menu", "dark mode"),
     lambda c: c.shell(type_="QuickSettings", timeout=0),
     "These icons open the system menu: sound, network, dark style and power."),
    (("home folder", "home", "my files", "my folder", "documents folder"),
     lambda c: c.icon("Ev", timeout=0),
     "This is Ev, your home folder. Your documents, pictures and downloads live inside it."),
    (("trash", "bin", "recycle bin", "trash can", "deleted files"),
     lambda c: c.icon("Çöp", timeout=0),
     "This is Çöp, the trash. Deleted files wait here until you empty it."),
    (("computer", "my computer", "drives", "disks", "usb", "flash drive"),
     lambda c: c.icon("Bilgisayar", timeout=0),
     "This is Bilgisayar. It shows your disks and USB drives."),
    (("clipboard", "copied text"),
     lambda c: c.shell(type_="ClipboardIndicator", timeout=0),
     "This is the clipboard history. It remembers what you copied."),
    (("updates", "updater", "update"),
     lambda c: c.shell(name="Pardus Güncelleyici", type_="IndicatorStatusIcon", timeout=0),
     "This is the Pardus updater. It tells you when updates are ready."),
]
TOUR = (0, 1, 2, 3, 4, 5, 6, 7, 8)


def _parse_thing(text, world):
    words = spaced(text)
    best = None
    for thing in THINGS:
        for phrase in thing[0]:
            if spaced(phrase) in words and (best is None or len(phrase) > best[0]):
                best = (len(phrase), thing)
    return {"thing": best[1]} if best else None


@recipe("where_is", examples=[
    "where is the trash", "where's the clock", "where can I find the volume", "show me the app menu",
    "where is my home folder", "point at the wifi settings", "where do I shut down the computer",
    "what is that icon at the bottom right", "where are my notifications",
], parse=_parse_thing, keywords=("where", "find", "point"))
def where_is(ctx, thing):
    phrases, find, text = thing
    target = ctx.need(find(ctx), phrases[0])
    ctx.circle(target, _(text))


@recipe("tour", examples=[
    "give me a tour of the desktop", "explain my desktop", "what is on my screen", "show me around",
    "what are all these things", "I'm new here, show me the basics", "explain the panel",
    "what can I find on this desktop", "teach me the desktop",
], keywords=("tour", "show me around", "basics", "explain"))
def tour(ctx):
    ctx.say(_("Here's a quick tour of your desktop."))
    for index in TOUR:
        _phrases, find, text = THINGS[index]
        target = find(ctx)
        if target:
            ctx.circle(target, _(text))
    ctx.finish(_("That's the desktop. Ask me to open something, or to change how it looks."))


@recipe("help", examples=["what can you do", "help", "what are you", "how can you help me", "what should I ask you",
                          "who are you"], keywords=("help", "what can you do"))
def help_(ctx):
    ctx.say(_("I'm Clicky. I can open apps, change the wallpaper or dark style, make, rename and tidy folders on "
              "your desktop, set the volume, take screenshots, and show you where things are. Just ask."))


@recipe("thanks", examples=["thank you", "thanks", "great job", "well done", "nice, thanks", "that's all"])
def thanks(ctx):
    ctx.say(_("You're welcome."))
