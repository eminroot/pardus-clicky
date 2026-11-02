"""The desktop itself: its right-click menu, the icons on it and the trash."""

import os
import re

from ..i18n import _
from . import recipe
from .context import RecipeFailed
from .world import has

SPECIAL = ("Ev", "Çöp", "Bilgisayar")
SPOKEN = {"Ev": "Ev, your home folder", "Çöp": "Çöp, the trash", "Bilgisayar": "Bilgisayar, your computer"}

# Where organize_desktop puts each kind of file. Folder names follow Pardus's own (Turkish) ones.
CATEGORIES = [
    ("Resimler", "pictures", {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".heic", ".tif", ".tiff"}),
    ("Belgeler", "documents", {".txt", ".pdf", ".odt", ".ods", ".odp", ".doc", ".docx", ".xls", ".xlsx", ".ppt",
                               ".pptx", ".md", ".rtf", ".csv"}),
    ("Müzik", "music", {".mp3", ".ogg", ".oga", ".wav", ".flac", ".m4a", ".opus"}),
    ("Videolar", "videos", {".mp4", ".mkv", ".webm", ".avi", ".mov", ".ogv"}),
    ("Arşivler", "archives", {".zip", ".tar", ".gz", ".xz", ".bz2", ".7z", ".rar", ".deb"}),
]

DOCUMENT_KINDS = [
    (("spreadsheet", "excel", "calc", "table"), "Hesap Tablosu", "spreadsheet"),
    (("presentation", "slides", "slide", "powerpoint", "impress"), "Sunum Dosyası", "presentation"),
    (("word", "writer", "document for writing", "letter", "word processor"), "Kelime İşlemci", "word processor document"),
    (("text", "note", "notes", "txt"), "Metin Belgesi", "text document"),
]

SORTS = [
    (("descending", "reverse", "z to a", "backwards"), "Azalan Şekilde Ada Göre Sırala", "by name, from Z to A"),
    (("date", "modified", "newest", "recent", "time", "latest"), "Değiştirilme Zamanına Göre Sırala", "by date"),
    (("type", "kind", "extension"), "Türe Göre Sırala", "by type"),
    (("size", "biggest", "largest", "smallest"), "Boyuta Göre Sırala", "by size"),
    (("name", "alphabetical", "alphabet", "a to z"), "Ada Göre Sırala", "by name"),
]


def spoken(label):
    return SPOKEN.get(label, label)


def make_folder(ctx, name, first=True):
    """Desktop menu -> Yeni Klasör -> type the name -> Tamam. Shared with organize_desktop."""
    ctx.open_desktop_menu(None if first else _("Right-click the desktop again."))
    item = ctx.need(ctx.menu_item("Yeni Klasör"), "Yeni Klasör")
    ctx.click(item, _("Choose Yeni Klasör, which means New Folder.") if first else
              _("Yeni Klasör again, for {name}.").format(name=name))
    ok = ctx.ui("Tamam", role="button", window="Desktop Icons", timeout=3)
    ctx.type(name, _("The name box is open with its text selected, so I just type {name}.").format(name=name)
             if first else _("I'll type {name}.").format(name=name))
    if ok:
        ctx.click(ok, _("Tamam means OK. That creates the folder.") if first else _("Tamam."))
    else:
        ctx.keys("Return", _("Return confirms the name."))
    if not ctx.icon(name, timeout=3):
        raise RecipeFailed(_("The {name} folder didn't appear.").format(name=name))


@recipe("new_folder", examples=[
    "make a new folder on the desktop", "create a folder called Projects", "new folder named photos",
    "how do I make a folder on my desktop", "add a folder to my desktop", "create a new directory",
    "make a folder called homework",
], parse=lambda text, world: {"name": world.name_after(text)}, keywords=("folder", "directory"))
def new_folder(ctx, name=None):
    if not name:
        name = (ctx.ask(_("What should I call the folder?")) or "").strip(" .!?") or "Yeni Klasör"
    existing = ctx.icon(name, timeout=0)
    if existing:
        ctx.circle(existing, _("You already have a folder called {name}. Here it is.").format(name=name))
        return
    make_folder(ctx, name)
    ctx.circle(ctx.icon(name), _("Done. Your {name} folder is on the desktop.").format(name=name))


def _parse_document(text, world):
    for words, item, english in DOCUMENT_KINDS:
        if has(text, *words):
            return {"item": item, "english": english, "name": world.name_after(text)}
    return {"item": "Metin Belgesi", "english": "text document", "name": world.name_after(text)}


@recipe("new_document", examples=[
    "create a new text document on the desktop", "make a new spreadsheet", "new document called notes",
    "make an empty presentation on my desktop", "create a text file", "how do I make a new document",
], parse=_parse_document, keywords=("document", "text file", "spreadsheet", "presentation"))
def new_document(ctx, item, english, name=None):
    before = set(ctx.world.desktop_items())
    ctx.open_desktop_menu()
    sub = ctx.need(ctx.menu_item("Yeni Belge"), "Yeni Belge")
    ctx.click(sub, _("Yeni Belge, which means New Document, opens a small list."))
    kind = ctx.need(ctx.menu_item(item), item)
    ctx.click(kind, _("{item} makes an empty {english}.").format(item=item, english=english))
    ok = ctx.ui("Tamam", role="button", window="Desktop Icons", timeout=2)
    if ok and name:
        ctx.type(name, _("I'll name it {name}.").format(name=name))
        ctx.click(ok, _("Tamam."))
    elif ok:
        ctx.click(ok, _("I'll keep the suggested name."))
    created = [n for n in ctx.world.desktop_items() if n not in before]
    target = ctx.icon(created[0], timeout=2) if created else None
    if target:
        ctx.circle(target, _("Here's your new {english}. Double-click it to start writing.").format(english=english))
    else:
        ctx.finish(_("The new {english} is on your desktop.").format(english=english))


def _parse_rename(text, world):
    head = re.split(r"\bto\b|\binto\b|\bas\b", text, flags=re.IGNORECASE)[0]
    return {"old": world.find_item(head) or world.find_item(text), "new": world.name_after(text, "to", "into", "as")}


@recipe("rename_item", examples=[
    "rename the Projects folder to Work", "change the name of notes.txt to todo.txt", "rename this file",
    "how do I rename a folder on my desktop", "give the folder a new name", "rename Projects as Archive",
], parse=_parse_rename, keywords=("rename",))
def rename_item(ctx, old=None, new=None):
    if not old:
        old = ctx.world.find_item(ctx.ask(_("Which one should I rename?")) or "")
        if not old:
            raise RecipeFailed(_("I couldn't tell which item you mean."))
    if old in ("Ev", "Çöp"):
        raise RecipeFailed(_("{name} can't be renamed.").format(name=old))
    if not new:
        new = (ctx.ask(_("What should the new name be?")) or "").strip(" .!?")
        if not new:
            raise RecipeFailed(_("I didn't catch the new name."))
    icon = ctx.need(ctx.icon(old), old)
    ctx.right_click(icon, _("Right-click {name} to see what you can do with it.").format(name=old))
    item = ctx.need(ctx.menu_item("Yeniden Adlandır"), "Yeniden Adlandır")
    ctx.click(item, _("Choose Yeniden Adlandır, which means Rename."))
    ok = ctx.ui("Tamam", role="button", window="Desktop Icons", timeout=2) or \
        ctx.ui("Yeniden Adlandır", role="button", window="Desktop Icons", timeout=0.5)
    ctx.type(new, _("The old name is selected, so I just type the new one: {name}.").format(name=new))
    if ok:
        ctx.click(ok, _("Then confirm."))
    else:
        ctx.keys("Return", _("Return confirms it."))
    renamed = ctx.icon(new, timeout=3)
    if not renamed:
        raise RecipeFailed(_("The name didn't change. Maybe that name is already taken."))
    ctx.circle(renamed, _("Renamed to {name}.").format(name=new))


@recipe("delete_item", examples=[
    "delete the Projects folder", "put deneme.txt in the trash", "remove this file from my desktop",
    "throw away the old folder", "how do I delete a file on the desktop", "get rid of notes.txt",
], parse=lambda text, world: {"name": world.find_item(text, exclude=SPECIAL)},
    keywords=("delete", "remove", "throw away", "trash"))
def delete_item(ctx, name=None):
    if not name:
        name = ctx.world.find_item(ctx.ask(_("Which item should I move to the trash?")) or "", exclude=SPECIAL)
        if not name:
            raise RecipeFailed(_("I couldn't tell which item you mean."))
    icon = ctx.need(ctx.icon(name), name)
    ctx.point(icon, _("This is {name}.").format(name=name))
    if not ctx.confirm(_("Should I move it to the trash? Say yes or no.")):
        ctx.finish(_("Okay, I'll leave it where it is."))
        return
    ctx.right_click(icon, _("Right-click it to see the options."))
    item = ctx.need(ctx.menu_item("Çöpe Taşı"), "Çöpe Taşı")
    ctx.click(item, _("Choose Çöpe Taşı, which means Move to Trash."))
    ctx.wait_until(lambda: ctx.icon(name, timeout=0) is None, 3)
    trash = ctx.icon("Çöp", timeout=0)
    message = _("It's in the trash now. You can still get it back from Çöp until you empty it.")
    if trash:
        ctx.circle(trash, message)
    else:
        ctx.finish(message)


@recipe("open_item", examples=[
    "open my home folder", "open the trash", "open the Projects folder", "open deneme.txt",
    "show me what's in the trash", "open my computer", "how do I open a folder on my desktop", "look inside Projects",
], parse=lambda text, world: ({"name": n} if (n := world.find_item(text)) else None), keywords=("open", "inside"))
def open_item(ctx, name):
    icon = ctx.need(ctx.icon(name), name)
    ctx.double_click(icon, _("Double-click {name} to open it.").format(name=spoken(name)), label=name)
    ctx.finish(_("It's open."))


def _parse_move(text, world):
    found = re.search(r"\b(?:move|put|drag|drop|place)\s+(?P<item>.+?)\s+(?:in|into|inside|to|onto)\s+(?P<folder>.+)$",
                      text, re.IGNORECASE)
    if not found:
        return None
    item = world.find_item(found.group("item"), exclude=SPECIAL)
    folder = world.find_item(found.group("folder"))
    if not item or not folder or item == folder or not world.is_folder(folder):
        return None
    return {"item": item, "folder": folder}


@recipe("move_into", examples=[
    "move deneme.txt into the Projects folder", "put the notes file in Belgeler", "drag this picture into Resimler",
    "how do I move a file into a folder", "put report.txt inside the Work folder",
], parse=_parse_move, keywords=("move", "put", "drag"))
def move_into(ctx, item, folder):
    source = ctx.need(ctx.icon(item), item)
    dest = ctx.need(ctx.icon(folder), folder)
    ctx.drag(source, dest, _("To move a file, drag it onto the folder and let go."), label=item)
    ctx.wait_until(lambda: ctx.icon(item, timeout=0) is None, 3)
    ctx.finish(_("{item} is inside {folder} now.").format(item=item, folder=folder))


@recipe("organize_desktop", examples=[
    "organize my desktop", "tidy up my desktop", "clean up the files on my desktop", "sort my desktop files into folders",
    "organize my files", "put my pictures and documents into folders", "my desktop is messy",
], keywords=("organize", "organise", "tidy", "clean up", "messy"))
def organize_desktop(ctx):
    plan = []
    for folder, meaning, extensions in CATEGORIES:
        files = [f for f in ctx.world.desktop_files() if os.path.splitext(f)[1].lower() in extensions]
        if files:
            plan.append((folder, meaning, files))
    if not plan:
        ctx.finish(_("There are no loose files on your desktop to sort."))
        return
    summary = ", ".join(f"{len(files)} {meaning}" for _f, meaning, files in plan)
    ctx.say(_("I see {summary}. I'll give each kind its own folder.").format(summary=summary))
    first_folder = first_drag = True
    for folder, meaning, files in plan:
        if not ctx.icon(folder, timeout=0):
            ctx.say(_("First a folder for the {meaning}: {folder}.").format(meaning=meaning, folder=folder))
            make_folder(ctx, folder, first=first_folder)
            first_folder = False
        for name in files:
            source = ctx.need(ctx.icon(name), name)
            dest = ctx.need(ctx.icon(folder), folder)
            ctx.drag(source, dest, _("Now I drag each file onto its folder. {name} goes into {folder}.").format(
                name=name, folder=folder) if first_drag else _("{name} goes into {folder}.").format(name=name, folder=folder),
                label=name)
            first_drag = False
            ctx.wait_until(lambda n=name: ctx.icon(n, timeout=0) is None, 3)
    ctx.finish(_("Done. Your desktop files are sorted into folders."))


@recipe("arrange_icons", examples=[
    "arrange the desktop icons", "line up the icons", "tidy up the icons", "put the icons in order",
    "the icons are all over the place",
], keywords=("icons", "arrange", "line up"))
def arrange_icons(ctx):
    ctx.open_desktop_menu()
    item = ctx.need(ctx.menu_item("Simgeleri Sırala"), "Simgeleri Sırala")
    ctx.click(item, _("Simgeleri Sırala, which means Arrange Icons, lines them all up."))
    ctx.finish(_("The icons are in order."))


def _parse_sort(text, world):
    for words, item, english in SORTS:
        if has(text, *words):
            return {"item": item, "english": english}
    return None


@recipe("sort_icons", examples=[
    "sort the desktop icons by name", "sort my desktop by date", "order the icons by size", "sort the files by type",
    "sort desktop items from z to a",
], parse=_parse_sort, keywords=("sort", "order by"))
def sort_icons(ctx, item, english):
    ctx.open_desktop_menu()
    sub = ctx.need(ctx.menu_item("Sırala"), "Sırala...")
    ctx.click(sub, _("Sırala means Sort. It opens the sorting choices."))
    choice = ctx.need(ctx.menu_item(item), item)
    ctx.click(choice, _("{item} sorts them {english}.").format(item=item, english=english))
    ctx.finish(_("Your desktop is sorted {english}.").format(english=english))


@recipe("select_all", examples=["select all the icons on the desktop", "select everything on my desktop",
                                "highlight all desktop files"], keywords=("select all", "select everything"))
def select_all(ctx):
    ctx.open_desktop_menu()
    item = ctx.need(ctx.menu_item("Tümünü Seç"), "Tümünü Seç")
    ctx.click(item, _("Tümünü Seç means Select All."))
    ctx.finish(_("Everything on the desktop is selected. Click an empty spot to undo that."))


@recipe("empty_trash", examples=["empty the trash", "clear the recycle bin", "delete everything in the trash",
                                 "how do I empty the trash"], keywords=("empty the trash", "empty trash", "recycle bin"))
def empty_trash(ctx):
    trash = ctx.need(ctx.icon("Çöp"), "Çöp")
    ctx.right_click(trash, _("Right-click Çöp, the trash."))
    item = ctx.need(ctx.menu_item("Çöpü Boşalt"), "Çöpü Boşalt")
    if "sensitive" not in item.states:
        ctx.quietly("Escape")
        ctx.finish(_("The trash is already empty."))
        return
    ctx.point(item, _("Çöpü Boşalt means Empty Trash. Files in there are deleted for good."))
    if not ctx.confirm(_("Should I empty it? Say yes or no.")):
        ctx.quietly("Escape")
        ctx.finish(_("Okay, the trash stays as it is."))
        return
    ctx.click(item, _("Emptying it now."))
    confirm = ctx.shell(name="Çöpü Boşalt", exact=True, timeout=2) or \
        ctx.ui("Çöpü Boşalt", role="button", timeout=1, exact=True) or ctx.ui("Boşalt", role="button", timeout=0.5)
    if confirm:
        ctx.click(confirm, _("And confirm."))
    ctx.finish(_("The trash is empty."))


@recipe("show_desktop_in_files", examples=["show the desktop folder in files", "open the desktop in the file manager",
                                           "where are my desktop files stored"], keywords=("desktop folder", "file manager"))
def show_desktop_in_files(ctx):
    ctx.open_desktop_menu()
    item = ctx.need(ctx.menu_item("Masaüstünü Dosyalar"), "Masaüstünü Dosyalarda Göster")
    ctx.click(item, _("This item opens the desktop as a normal folder in Dosyalar, the file manager."))
    ctx.finish(_("These are the files on your desktop."))


@recipe("icon_settings", examples=["change the desktop icon size", "make the desktop icons bigger", "desktop icon settings",
                                   "hide the trash icon from the desktop", "make the icons smaller"],
        keywords=("icon size", "icon settings", "bigger icons", "smaller icons"))
def icon_settings(ctx):
    ctx.open_desktop_menu()
    item = ctx.need(ctx.menu_item("Masaüstü Simgeleri Ayarları"), "Masaüstü Simgeleri Ayarları")
    ctx.click(item, _("Masaüstü Simgeleri Ayarları means Desktop Icons Settings. Icon size and which icons show are in here."))
    ctx.finish(_("Pick what you like in this window."))


@recipe("display_settings", examples=["change the screen resolution", "open display settings", "make everything bigger on screen",
                                      "change the scale of the screen", "set up my monitor"],
        keywords=("resolution", "display", "monitor", "scale"))
def display_settings(ctx):
    ctx.open_desktop_menu()
    item = ctx.need(ctx.menu_item("Görüntü Ayarları"), "Görüntü Ayarları")
    ctx.click(item, _("Görüntü Ayarları means Display Settings."))
    ctx.finish(_("Resolution and scale are on this page. Changes ask before they stay."))
