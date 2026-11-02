// D-Bus face of the shell helper. The Clicky app (bus name tr.org.pardus.clicky)
// is the only caller allowed, the same way GNOME guards its own screenshot API.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {DBusSenderChecker} from 'resource:///org/gnome/shell/misc/util.js';

import {Overlay} from './overlay.js';
import {Input} from './input.js';
import * as Elements from './elements.js';

const BUS_NAME = 'tr.org.pardus.clicky.Shell';
const OBJECT_PATH = '/tr/org/pardus/clicky/Shell';
const CLIENT_NAME = 'tr.org.pardus.clicky';

const IFACE = `
<node>
  <interface name="tr.org.pardus.clicky.Shell">
    <method name="Ping"><arg type="s" direction="out" name="version"/></method>
    <method name="Reload"/>
    <method name="GetState"><arg type="s" direction="out" name="json"/></method>
    <method name="FindElements">
      <arg type="s" direction="in" name="query_json"/>
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="Screenshot">
      <arg type="s" direction="in" name="path"/>
      <arg type="b" direction="in" name="hide_overlay"/>
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="SetState"><arg type="s" direction="in" name="state"/></method>
    <method name="SetLevel"><arg type="d" direction="in" name="level"/></method>
    <method name="FlyTo">
      <arg type="d" direction="in" name="x"/>
      <arg type="d" direction="in" name="y"/>
      <arg type="s" direction="in" name="label"/>
      <arg type="u" direction="in" name="duration_ms"/>
    </method>
    <method name="Home"/>
    <method name="Ring">
      <arg type="d" direction="in" name="x"/>
      <arg type="d" direction="in" name="y"/>
      <arg type="s" direction="in" name="kind"/>
    </method>
    <method name="Caption">
      <arg type="s" direction="in" name="text"/>
      <arg type="s" direction="in" name="kind"/>
    </method>
    <method name="Draw"><arg type="s" direction="in" name="json"/></method>
    <method name="ClearDrawings"/>
    <method name="PointerGlide">
      <arg type="d" direction="in" name="x"/>
      <arg type="d" direction="in" name="y"/>
      <arg type="u" direction="in" name="duration_ms"/>
    </method>
    <method name="PointerButton">
      <arg type="u" direction="in" name="button"/>
      <arg type="b" direction="in" name="pressed"/>
    </method>
    <method name="Click">
      <arg type="u" direction="in" name="button"/>
      <arg type="u" direction="in" name="count"/>
    </method>
    <method name="Scroll">
      <arg type="i" direction="in" name="steps"/>
      <arg type="b" direction="in" name="horizontal"/>
    </method>
    <method name="Keys"><arg type="s" direction="in" name="combo"/></method>
    <method name="Type">
      <arg type="s" direction="in" name="text"/>
      <arg type="u" direction="in" name="delay_ms"/>
    </method>
  </interface>
</node>`;

const WINDOW_TYPES = Object.fromEntries(Object.entries(Meta.WindowType).map(([name, value]) => [value, name.toLowerCase()]));

function windowInfo(win, tracker) {
    const r = win.get_frame_rect();
    const b = win.get_buffer_rect();
    const app = tracker.get_window_app(win);
    return {
        type: WINDOW_TYPES[win.get_window_type()] ?? '',
        title: win.get_title() ?? '',
        app: app?.get_name() ?? '',
        app_id: app?.get_id() ?? '',
        wm_class: win.get_wm_class() ?? '',
        pid: win.get_pid(),
        x: r.x, y: r.y, w: r.width, h: r.height,
        buffer: [b.x, b.y, b.width, b.height],
        focused: win.has_focus(),
        minimized: win.minimized,
        maximized: win.is_maximized?.() ?? false,
    };
}

export class Service {
    constructor({version, reload}) {
        this._version = version;
        this._reload = reload;
        this._overlay = new Overlay();
        this._input = new Input();
        this._checker = new DBusSenderChecker([CLIENT_NAME]);

        const guarded = {
            GetState: () => new GLib.Variant('(s)', [JSON.stringify(this._state())]),
            FindElements: query => new GLib.Variant('(s)', [JSON.stringify(Elements.find(JSON.parse(query)))]),
            Screenshot: async (path, hide) => new GLib.Variant('(s)', [JSON.stringify(await this._screenshot(path, hide))]),
            SetState: state => this._overlay.setState(state),
            SetLevel: level => this._overlay.setLevel(level),
            FlyTo: (x, y, label, ms) => this._overlay.flyTo(x, y, label, ms),
            Home: () => this._overlay.home(),
            Ring: (x, y, kind) => this._overlay.ring(x, y, kind),
            Caption: (text, kind) => this._overlay.caption(text, kind),
            Draw: json => this._overlay.draw(JSON.parse(json)),
            ClearDrawings: () => this._overlay.clearDrawings(),
            PointerGlide: (x, y, ms) => this._input.glideTo(x, y, ms),
            PointerButton: (button, pressed) => this._input.button(button, pressed),
            Click: (button, count) => this._input.click(button, count),
            Scroll: (steps, horizontal) => this._input.scroll(steps, horizontal),
            Keys: combo => this._input.keys(combo),
            Type: (text, delay) => this._input.type(text, delay),
        };
        for (const [name, fn] of Object.entries(guarded)) {
            this[`${name}Async`] = async (params, invocation) => {
                try {
                    await this._checker.checkInvocation(invocation);
                    const result = await fn(...params);
                    invocation.return_value(result instanceof GLib.Variant ? result : null);
                } catch (e) {
                    if (e instanceof GLib.Error)
                        invocation.return_gerror(e);
                    else
                        invocation.return_error_literal(Gio.DBusError, Gio.DBusError.FAILED, `${e.message ?? e}`);
                }
            };
        }

        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
        this._nameId = Gio.bus_own_name_on_connection(Gio.DBus.session, BUS_NAME,
            Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT | Gio.BusNameOwnerFlags.REPLACE, null, null);
        console.log(`[clicky] shell helper ${this._version} ready`);
    }

    destroy() {
        Gio.bus_unown_name(this._nameId);
        this._dbus.unexport();
        this._checker.destroy?.();
        this._input.destroy();
        this._overlay.destroy();
    }

    Ping() {
        return this._version;
    }

    Reload() {
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            this._reload();
            return GLib.SOURCE_REMOVE;
        });
    }

    _state() {
        const tracker = Shell.WindowTracker.get_default();
        const types = [Meta.WindowType.NORMAL, Meta.WindowType.DIALOG, Meta.WindowType.MODAL_DIALOG, Meta.WindowType.UTILITY];
        // list_all_windows also has the desktop-icons window and popup menus, which
        // the AT-SPI lookups need to place their elements.
        const all = global.display.sort_windows_by_stacking(global.display.list_all_windows());
        const windows = all.filter(w => types.includes(w.get_window_type()) && !w.is_skip_taskbar());
        const [px, py] = global.get_pointer();
        const primary = Main.layoutManager.primaryIndex;
        const area = Main.layoutManager.getWorkAreaForMonitor(primary);
        return {
            stage: [global.stage.width, global.stage.height],
            pointer: [px, py],
            overview: Main.overview.visible,
            locked: Main.sessionMode.isLocked,
            work_area: {x: area.x, y: area.y, width: area.width, height: area.height},
            monitors: Main.layoutManager.monitors.map(m => ({x: m.x, y: m.y, width: m.width, height: m.height, scale: m.geometry_scale})),
            windows: windows.reverse().map(w => windowInfo(w, tracker)),
            // Every window, including the desktop-icons window; used to place AT-SPI coordinates.
            surfaces: all.reverse().map(w => windowInfo(w, tracker)),
        };
    }

    async _screenshot(path, hideOverlay) {
        const file = Gio.File.new_for_path(path);
        const stream = file.replace(null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
        if (hideOverlay)
            this._overlay.setHidden(true);
        try {
            const shooter = new Shell.Screenshot();
            await shooter.screenshot(false, stream);
        } finally {
            stream.close(null);
            if (hideOverlay)
                this._overlay.setHidden(false);
        }
        return {
            stage: [global.stage.width, global.stage.height],
            overlay_boxes: hideOverlay ? [] : this._overlay.boxes(),
        };
    }
}
