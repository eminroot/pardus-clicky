"""How the desktop looks: wallpaper, dark style and accent color."""

from ..a11y import norm
from ..i18n import _
from . import recipe
from .context import RecipeFailed, Target
from .world import has

# Words people use for the Pardus 25 default wallpaper (its name is "Bilge").
DEFAULT_WALLPAPER = ("mountain", "default", "original", "bilge", "pardus one", "standard", "usual")

ACCENTS = {
    "blue": "Mavi", "teal": "Ördekbaşı", "turquoise": "Ördekbaşı", "cyan": "Ördekbaşı", "green": "Yeşil",
    "yellow": "Sarı", "orange": "Turuncu", "red": "Kırmızı", "pink": "Pembe", "purple": "Mor", "violet": "Mor",
    "gray": "Kayrak", "grey": "Kayrak", "slate": "Kayrak",
}


def open_appearance(ctx, say=None):
    """Desktop menu -> Arka Planı Değiştir... opens Settings on the Görünüm page."""
    ctx.open_desktop_menu()
    item = ctx.need(ctx.menu_item("Arka Planı Değiştir"), "Arka Planı Değiştir...")
    ctx.click(item, say or _("Choose Arka Planı Değiştir, which means Change Background."))
    if not ctx.ui("Resim Ekle", role="button", window="Ayarlar", timeout=10):
        raise RecipeFailed(_("The background settings didn't open."))


def wallpapers(ctx):
    """Wallpaper thumbnails visible on the Görünüm page (they sit below the Resim Ekle button)."""
    add = ctx.ui("Resim Ekle", role="button", window="Ayarlar", timeout=0)
    found = ctx.a11y.find(role="toggle button", window="Ayarlar")
    return [Target.from_ui(e) for e in found if add is None or e.y > add.y + add.h]


def _parse_wallpaper(text, world):
    if has(text, *DEFAULT_WALLPAPER):
        return {"pick": "default"}
    number = world.ordinal(text)
    if number:
        return {"pick": number}
    return {"pick": "next"}


@recipe("change_wallpaper", examples=[
    "change the wallpaper", "change my desktop background", "show me how to change the wallpaper",
    "set a new background picture", "put a different picture behind my icons", "I'm bored of this background",
    "use the mountain wallpaper again", "pick the second wallpaper", "how do I change the desktop picture",
], parse=_parse_wallpaper, keywords=("wallpaper", "background", "backdrop", "desktop picture"))
def change_wallpaper(ctx, pick="next"):
    open_appearance(ctx)
    thumbs = wallpapers(ctx)
    if not thumbs:
        raise RecipeFailed(_("I can't see the wallpapers on this page."))
    current = next((i for i, t in enumerate(thumbs) if t.checked), -1)
    if pick == "default":
        choice = next((t for t in thumbs if norm(t.name) == "bilge"), thumbs[0])
    elif isinstance(pick, int) and pick != 0:
        choice = thumbs[pick - 1] if 0 < pick <= len(thumbs) else thumbs[-1]
    else:
        choice = thumbs[(current + 1) % len(thumbs)]
    if choice.checked:
        ctx.circle(choice, _("This one is already your wallpaper. The tick shows which one is in use."))
        return
    ctx.click(choice, _("These pictures are the backgrounds. Clicking one sets it right away."), label=_("wallpaper"))
    if pick == "default":
        ctx.finish(_("The original Pardus wallpaper is back."))
    else:
        ctx.finish(_("That's your new wallpaper. You can pick another one here any time."))


def _parse_dark(text, world):
    if has(text, "toggle", "flip"):
        return {"on": None}
    if has(text, "light mode", "light theme", "light style", "normal colors", "normal colours", "white theme",
           "lighter", "bright mode", "default style"):
        return {"on": False}
    choice = world.on_off(text)
    if choice is not None:
        return {"on": choice}
    if has(text, "dark", "darker", "night", "black"):
        return {"on": True}
    return {"on": None}


@recipe("dark_mode", examples=[
    "turn on dark mode", "switch to the dark theme", "make the screen dark", "turn off dark mode",
    "go back to light mode", "use the light theme", "how do I turn on dark mode", "make everything dark",
    "my eyes hurt, make it darker", "toggle dark style",
], parse=_parse_dark, keywords=("dark", "light mode", "light theme", "dark style"))
def dark_mode(ctx, on=None):
    ctx.open_system_menu()
    toggle = ctx.need(ctx.shell(type_="DarkModeToggle", timeout=2), "Koyu Biçem")
    want = (not toggle.checked) if on is None else on
    if bool(toggle.checked) == want:
        ctx.circle(toggle, _("Koyu Biçem, which means Dark Style, is already on.") if want
                   else _("Koyu Biçem, which means Dark Style, is already off."))
    else:
        ctx.click(toggle, _("This switch is Koyu Biçem, which means Dark Style."))
        ctx.wait_until(lambda: bool((ctx.shell(type_="DarkModeToggle", timeout=0) or toggle).checked) == want, 2)
    ctx.quietly("Escape")
    ctx.finish(_("Dark style is on. The same switch turns it off.") if want else _("Light style is back."))


def _parse_accent(text, world):
    for english, turkish in ACCENTS.items():
        if has(text, english) or has(text, turkish):
            return {"color": turkish, "english": english}
    return None


@recipe("accent_color", examples=[
    "change the accent color to green", "make the highlight color purple", "set the system color to orange",
    "I want red buttons", "change the theme color to pink", "make the selection color yellow",
], parse=_parse_accent, keywords=("accent", "highlight color", "theme color"))
def accent_color(ctx, color, english):
    open_appearance(ctx, _("Accent colors are on the same page as the wallpaper. Choose Arka Planı Değiştir."))
    swatch = ctx.need(ctx.ui(color, role="toggle button", window="Ayarlar", exact=True, timeout=4), color)
    if swatch.checked:
        ctx.circle(swatch, _("{english} is already your accent color.").format(english=english.capitalize()))
        return
    ctx.click(swatch, _("Under Vurgu Rengi, which means Accent Color, click the {english} circle.").format(english=english),
              label=color)
    ctx.finish(_("Buttons and highlights are {english} now.").format(english=english))
