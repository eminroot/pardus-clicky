"""List what Clicky can find by name on screen, for writing recipes. Run in the
VM session with the app stopped (it borrows the app's bus name):

    python3 scripts/dev/elements.py shell [name]     GNOME Shell UI (panel, app grid, menus)
    python3 scripts/dev/elements.py a11y [app]       AT-SPI elements of app windows (desktop icons, Settings, ...)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from gi.repository import Gio, GLib  # noqa: E402

from pardus_clicky import APP_ID  # noqa: E402

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
owned = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                      GLib.Variant("(su)", (APP_ID, 4)), None, Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
if owned != 1:
    sys.exit("the Clicky app is running; stop it first (bin/pardus-clicky quit)")

what = sys.argv[1] if len(sys.argv) > 1 else "shell"
query = sys.argv[2] if len(sys.argv) > 2 else ""
if what == "shell":
    from pardus_clicky.shell import ShellDriver
    for el in ShellDriver(bus).find_elements(query):
        print(f'{el["type"]:<22} {el["name"][:48]:<48} {el["x"]:>5},{el["y"]:<5} {el["w"]}x{el["h"]} '
              f'{el["app_id"]} {"" if el["checked"] is None else "checked=" + str(el["checked"])}')
else:
    from pardus_clicky.a11y import A11y
    from pardus_clicky.shell import ShellDriver
    for el in A11y(ShellDriver(bus)).elements(app=query or None):
        print(f'{el.app[:14]:<14} {el.role:<16} {el.name[:50]:<50} {el.x:>5},{el.y:<5} {el.w}x{el.h} {",".join(el.states)}')
