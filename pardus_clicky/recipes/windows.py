"""Opening apps from the desktop and handling their windows."""

from ..i18n import _
from . import recipe
from .context import CLOSE_NAMES, MAXIMIZE_NAMES, MINIMIZE_NAMES, RecipeFailed
from .world import names_something


def _needs_app(text, world):
    app = world.find_app(text)
    return {"app": app} if app else None


def _maybe_app(text, world):
    """The named app, or None for 'this window'. Refuses names it doesn't know, so it never
    acts on the wrong window."""
    app = world.find_app(text)
    if app is None and names_something(text):
        return None
    return {"app": app}


def open_app_steps(ctx, app):
    """Open an app the way a person would: its panel icon, or the app grid."""
    pinned = ctx.shell(app_id=app.id, type_="TaskbarAppIcon", timeout=0)
    if pinned:
        ctx.click(pinned, _("It's on the panel at the bottom, so one click opens it. This is {name}.").format(
            name=app.spoken), label=app.name)
    else:
        ctx.open_app_grid()
        tile = ctx.shell(app_id=app.id, type_="AppIcon", timeout=2)
        if not tile:
            ctx.type(app.name, _("It's not on this page, so I'll type its name to search."))
            tile = ctx.shell(app_id=app.id, timeout=3) or ctx.shell(name=app.name, timeout=1)
            ctx.need(tile, app.name)
        ctx.click(tile, _("There it is: {name}. One click opens it.").format(name=app.spoken), label=app.name)
    return ctx.wait_window(app.id, timeout=10)


@recipe("open_app", examples=[
    "open the calculator", "start firefox", "launch the terminal", "open files", "open settings",
    "open the text editor", "run libreoffice writer", "I want to use the calculator", "start the web browser",
    "show me how to open the calculator", "how do I open settings", "how do I start an app",
    "where do I find the calculator app", "open the software center", "open the camera app",
], parse=_needs_app, keywords=("open", "launch", "start", "run"))
def open_app(ctx, app):
    if ctx.window(app):
        icon = ctx.shell(app_id=app.id, type_="TaskbarAppIcon", timeout=0)
        if icon:
            ctx.click(icon, _("It's already open, so its panel icon brings it to the front. This is {name}.").format(
                name=app.spoken), label=app.name)
            return
    if open_app_steps(ctx, app):
        ctx.finish(_("{name} is open.").format(name=app.name))
    else:
        ctx.finish(_("It's starting. It can take a moment to appear."))


@recipe("close_window", examples=[
    "close this window", "close the calculator", "close settings", "quit firefox", "exit this app",
    "close the files window", "get rid of this window", "how do I close a window", "shut this app",
], parse=_maybe_app, keywords=("close", "quit", "exit"))
def close_window(ctx, app=None):
    win = ctx.window(app)
    if not win:
        raise RecipeFailed(_("I don't see that window open."))
    button = ctx.window_button(win, CLOSE_NAMES)
    if button:
        ctx.click(button, _("The X at the top right of a window closes it."), label="Kapat")
    else:
        ctx.keys("alt+F4", _("I'll press Alt and F4. That closes the window in front."))
    ctx.finish(_("Closed."))


@recipe("minimize_window", examples=[
    "minimize this window", "minimise the calculator", "hide this window for now", "put the settings window away",
    "how do I minimize a window",
], parse=_maybe_app, keywords=("minimize", "minimise", "hide"))
def minimize_window(ctx, app=None):
    win = ctx.window(app)
    if not win:
        raise RecipeFailed(_("I don't see that window open."))
    button = ctx.need(ctx.window_button(win, MINIMIZE_NAMES), _("the minimise button"))
    ctx.click(button, _("The small line at the top right minimises the window. Its panel icon brings it back."))


@recipe("maximize_window", examples=[
    "maximize this window", "make this window full screen", "make the calculator bigger", "restore the window size",
    "make the window fill the screen", "how do I maximize a window",
], parse=_maybe_app, keywords=("maximize", "maximise", "bigger", "full screen", "restore"))
def maximize_window(ctx, app=None):
    win = ctx.window(app)
    if not win:
        raise RecipeFailed(_("I don't see that window open."))
    button = ctx.need(ctx.window_button(win, MAXIMIZE_NAMES), _("the maximise button"))
    if win.get("maximized"):
        ctx.click(button, _("The square button gives the window its old size back."))
    else:
        ctx.click(button, _("The square button at the top right makes the window fill the screen."))


@recipe("switch_to_app", examples=[
    "switch to firefox", "go back to the calculator", "show me the files window", "bring up settings",
    "switch to the terminal window", "how do I switch between windows",
], parse=_needs_app, keywords=("switch", "go back", "bring up"))
def switch_to_app(ctx, app):
    if not ctx.window(app) and not any(w["app_id"] == app.id for w in ctx.state()["windows"]):
        raise RecipeFailed(_("{name} isn't open right now.").format(name=app.name))
    icon = ctx.need(ctx.shell(app_id=app.id, type_="TaskbarAppIcon", timeout=1), app.name)
    ctx.click(icon, _("Every open app has an icon on the panel, and a click brings it to the front. This one is {name}.").format(
        name=app.spoken), label=app.name)


@recipe("show_desktop", examples=[
    "show the desktop", "minimize all windows", "hide all windows", "clear the screen", "I want to see my desktop",
    "get all these windows out of the way",
], keywords=("show the desktop", "all windows"))
def show_desktop(ctx):
    wins = ctx.windows()
    if not wins:
        ctx.finish(_("The desktop is already clear."))
        return
    first = True
    for win in wins:
        button = ctx.window_button(win, MINIMIZE_NAMES)
        if not button:
            continue
        ctx.click(button, _("The small line at the top right of each window minimises it.") if first else _("And this one."))
        first = False
    ctx.finish(_("Here's your desktop. The panel icons bring the windows back."))
