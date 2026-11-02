"""The bottom-right corner: sound, lock, power, screenshots, the clock and notifications."""

from datetime import datetime

from ..i18n import _
from . import recipe
from .context import Target
from .world import has

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")

POWER = {  # menu item, what it does, what to say when clicking it (translated when used)
    "restart": ("Yeniden Başlat", "restart the computer", "Yeniden Başlat means Restart."),
    "logout": ("Oturumu Kapat", "log you out", "Oturumu Kapat means Log Out."),
    "suspend": ("Askıya Al", "put the computer to sleep", "Askıya Al means Suspend. The computer sleeps until you wake it."),
    "off": ("Gücü Kapat", "turn the computer off", "Gücü Kapat means Power Off."),
}


def _parse_volume(text, world):
    if has(text, "unmute", "sound back", "turn the sound on", "turn sound on"):
        return {"mode": "unmute", "level": None}
    if has(text, "mute", "silence", "no sound", "turn off the sound", "turn the sound off", "quiet please"):
        return {"mode": "mute", "level": None}
    level = world.percent(text)
    if level is not None:
        return {"mode": "set", "level": level}
    if has(text, "up", "louder", "increase", "raise", "higher", "more"):
        return {"mode": "up", "level": None}
    if has(text, "down", "quieter", "lower", "decrease", "softer", "less", "too loud"):
        return {"mode": "down", "level": None}
    return {"mode": "show", "level": None}


@recipe("volume", examples=[
    "turn the volume up", "make it louder", "turn the sound down", "it's too loud", "mute the sound",
    "unmute", "set the volume to 50 percent", "how do I change the volume", "volume to maximum", "make it quieter",
], parse=_parse_volume, keywords=("volume", "louder", "quieter", "mute", "sound"))
def volume(ctx, mode="show", level=None):
    ctx.open_system_menu()
    if mode in ("mute", "unmute"):
        button = ctx.need(ctx.shell(name="Sessiz", timeout=2) or ctx.shell(name="Sesi Aç", timeout=0), _("the mute button"))
        ctx.click(button, _("The speaker button next to the slider turns the sound off and on."), label=_("mute"))
        ctx.quietly("Escape")
        ctx.finish(_("Sound is off.") if mode == "mute" else _("Sound is back on."))
        return
    slider = ctx.need(ctx.shell(name="Ses", type_="Slider", exact=True, timeout=2), _("the volume slider"))
    current = slider.value if slider.value is not None else 0.5
    if mode == "show":
        ctx.point(slider, _("This slider sets the volume. Further right is louder."), label=_("volume"))
        ctx.finish(_("Drag it or click where you want it."))
        return
    goal = {"up": current + 0.2, "down": current - 0.2}.get(mode, (level or 0) / 100)
    goal = max(0.0, min(1.0, goal))
    x = slider.x + 6 + (slider.w - 12) * goal
    ctx.click(Target.point(x, slider.y + slider.h / 2, "Ses"),
              _("Click on the volume slider where you want it. Further right is louder."), label=_("volume"))
    ctx.quietly("Escape")
    ctx.finish(_("The volume is at about {percent} percent.").format(percent=round(goal * 100)))


@recipe("lock_screen", examples=["lock the screen", "lock my computer", "how do I lock the screen", "lock it"],
        keywords=("lock",))
def lock_screen(ctx):
    ctx.open_system_menu()
    lock = ctx.need(ctx.shell(type_="LockItem", timeout=2), "Ekranı Kilitle")
    ctx.point(lock, _("This padlock is Ekranı Kilitle, which means Lock Screen."))
    if not ctx.confirm(_("Should I lock the screen now? Say yes or no.")):
        ctx.quietly("Escape")
        ctx.finish(_("Okay, not locking."))
        return
    ctx.click(lock, _("Locking. Type your password to come back."))


def _parse_power(text, world):
    if has(text, "restart", "reboot"):
        return {"action": "restart"}
    if has(text, "log out", "logout", "log off", "sign out"):
        return {"action": "logout"}
    if has(text, "sleep", "suspend"):
        return {"action": "suspend"}
    if has(text, "shut down", "shutdown", "power off", "turn off the computer", "switch off the computer",
           "turn the computer off"):
        return {"action": "off"}
    return None


@recipe("power", examples=[
    "shut down the computer", "turn off the computer", "restart the computer", "reboot", "log out",
    "sign out of my account", "put the computer to sleep", "how do I shut down",
], parse=_parse_power, keywords=("shut down", "restart", "log out", "reboot", "power off", "sleep"))
def power(ctx, action):
    label, what, meaning = POWER[action]
    what, meaning = _(what), _(meaning)
    if not ctx.confirm(_("Do you want me to {what}? Unsaved work could be lost. Say yes or no.").format(what=what)):
        ctx.finish(_("Okay, nothing changes."))
        return
    ctx.open_system_menu()
    menu = ctx.need(ctx.shell(type_="ShutdownItem", timeout=2), "Gücü Kapat Menüsü")
    ctx.click(menu, _("The power button opens the power options."))
    item = ctx.need(ctx.shell(name=label, timeout=2), label)
    ctx.click(item, meaning)
    if action != "suspend":
        button = ctx.shell(name=label, exact=True, timeout=3)
        if button:
            ctx.click(button, _("And confirm it here."))


@recipe("screenshot", examples=["take a screenshot", "capture the screen", "how do I take a screenshot",
                                "save a picture of my screen", "screen capture"], keywords=("screenshot", "capture"))
def screenshot(ctx):
    ctx.open_system_menu()
    item = ctx.need(ctx.shell(type_="ScreenshotItem", timeout=2), "Ekran Görüntüsü Al")
    ctx.click(item, _("This camera button is Ekran Görüntüsü Al, which means Take Screenshot."))
    capture = ctx.shell(name="Ekran Görüntüsü Yakala", timeout=3) or ctx.shell(name="Yakala", timeout=0)
    if not capture:
        ctx.finish(_("Choose the area, then press the big round button to take it."))
        return
    ctx.click(capture, _("The big round button takes the picture."))
    ctx.finish(_("Done. Screenshots go to the Resimler folder, inside Ekran Görüntüleri."))


@recipe("what_time", examples=["what time is it", "what's the date today", "what day is it", "tell me the time",
                               "what's today's date", "is it Monday"],
        parse=lambda text, world: {} if has(text, "time", "date", "day", "clock", "hour", "month", "year",
                                            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
                                            "sunday") else None,
        keywords=("time", "date", "day"))
def what_time(ctx):
    now = datetime.now()
    clock = ctx.shell(type_="DateMenuButton", timeout=1)
    hour = now.strftime("%I:%M").lstrip("0") + (" in the morning" if now.hour < 12 else " in the afternoon" if now.hour < 18 else " in the evening")
    text = _("It's {time}, {day} {month} {date}.").format(time=hour, day=DAYS[now.weekday()], month=MONTHS[now.month - 1],
                                                       date=now.day)
    if clock:
        ctx.circle(clock, text + " " + _("The clock is always here at the bottom right."), label=_("clock"))
    else:
        ctx.say(text)


@recipe("show_calendar", examples=["show me the calendar", "open the calendar", "show my notifications",
                                   "where are my notifications", "what's in my notifications"],
        keywords=("calendar", "notifications"))
def show_calendar(ctx):
    ctx.open_calendar(_("Click the clock at the bottom right. It opens the calendar and your notifications."))
    ctx.finish(_("Notifications are on the left, the calendar is on the right. Press Escape to close it."))


@recipe("do_not_disturb", examples=["turn on do not disturb", "stop showing notifications", "turn off do not disturb",
                                    "silence notifications", "I don't want any popups"],
        parse=lambda text, world: {"on": False if world.on_off(text) is False and has(text, "disturb") else True},
        keywords=("disturb", "notifications"))
def do_not_disturb(ctx, on=True):
    ctx.open_calendar()
    switch = ctx.need(ctx.shell(name="Rahatsız Etme", type_="St_Button", exact=True, timeout=2), "Rahatsız Etme")
    if bool(switch.checked) == on:
        ctx.circle(switch, _("Rahatsız Etme, which means Do Not Disturb, is already on.") if on
                   else _("Rahatsız Etme, which means Do Not Disturb, is already off."))
    else:
        ctx.click(switch, _("This switch is Rahatsız Etme, which means Do Not Disturb."))
    ctx.quietly("Escape")
    ctx.finish(_("Popups are silenced. They still collect here.") if on else _("Notifications will pop up again."))


@recipe("clear_notifications", examples=["clear my notifications", "delete all notifications", "dismiss the notifications",
                                         "get rid of these notifications"], keywords=("clear", "notifications"))
def clear_notifications(ctx):
    ctx.open_calendar()
    button = ctx.shell(name="Tüm bildirimleri temizle", timeout=1)
    if not button:
        ctx.quietly("Escape")
        ctx.finish(_("There are no notifications to clear."))
        return
    ctx.click(button, _("This button clears them all."), label=_("clear all"))
    ctx.quietly("Escape")
    ctx.finish(_("Notifications cleared."))
