// Real pointer and keyboard events through Clutter virtual devices. These go
// through the compositor like a physical mouse, so they work on Wayland and
// do not need the screen-sharing portal.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const MODIFIERS = {
    ctrl: 'Control_L', control: 'Control_L', shift: 'Shift_L', alt: 'Alt_L',
    super: 'Super_L', meta: 'Super_L', win: 'Super_L', altgr: 'ISO_Level3_Shift',
};
const NAMES = {
    enter: 'Return', return: 'Return', esc: 'Escape', escape: 'Escape', tab: 'Tab',
    space: 'space', backspace: 'BackSpace', delete: 'Delete', del: 'Delete',
    up: 'Up', down: 'Down', left: 'Left', right: 'Right', home: 'Home', end: 'End',
    pageup: 'Page_Up', pagedown: 'Page_Down', insert: 'Insert', menu: 'Menu', print: 'Print',
};

const sleep = ms => new Promise(resolve => {
    GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
        resolve();
        return GLib.SOURCE_REMOVE;
    });
});

export function keyvalFor(name) {
    const lower = name.toLowerCase();
    const mapped = MODIFIERS[lower] ?? NAMES[lower] ?? name;
    if (/^f\d{1,2}$/i.test(mapped))
        return Clutter[`KEY_F${mapped.slice(1)}`];
    const keyval = Clutter[`KEY_${mapped}`];
    if (keyval !== undefined)
        return keyval;
    if ([...name].length === 1)
        return Clutter.unicode_to_keysym(name.codePointAt(0));
    throw new Error(`unknown key "${name}"`);
}

export class Input {
    constructor() {
        const seat = global.stage.context.get_backend().get_default_seat();
        this._pointer = seat.create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);
        this._keyboard = seat.create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
        this._glide = null;
    }

    destroy() {
        this._glide?.timeline.stop();
        this._glide?.resolve();
        this._glide = null;
        this._pointer = null;
        this._keyboard = null;
    }

    moveTo(x, y) {
        this._pointer.notify_absolute_motion(GLib.get_monotonic_time(), x, y);
    }

    // Moves the real pointer along a soft curve so the user can follow it.
    //
    // The path never sweeps along the panel: while a panel menu is open, GNOME
    // opens whichever panel button the pointer passes over (like a menu bar),
    // so crossing the clock on the way to the system menu would swap menus.
    // Leaving or entering the panel therefore goes straight up or down first.
    async glideTo(x, y, ms) {
        const [x0, y0] = global.get_pointer();
        const area = Main.layoutManager.getWorkAreaForMonitor(Main.layoutManager.primaryIndex);
        const top = area.y + 6, bottom = area.y + area.height - 6;
        const inPanel = py => py < top || py > bottom;
        const edge = py => (py < top ? top + 10 : bottom - 10);
        const total = Math.hypot(x - x0, y - y0);
        const legs = [];
        if (inPanel(y0) && !inPanel(y) && Math.abs(x - x0) > 30)
            legs.push([x0, edge(y0)]);
        if (inPanel(y) && !inPanel(y0) && Math.abs(x - x0) > 30)
            legs.push([x, edge(y)]);
        legs.push([x, y]);
        for (const [lx, ly] of legs) {
            const [sx, sy] = global.get_pointer();
            const share = total ? Math.hypot(lx - sx, ly - sy) / total : 1;
            // eslint-disable-next-line no-await-in-loop
            await this._glideLeg(lx, ly, ms > 0 ? ms * share : 0);
        }
    }

    _glideLeg(x, y, ms) {
        this._glide?.timeline.stop();
        this._glide?.resolve();
        const [x0, y0] = global.get_pointer();
        const dist = Math.hypot(x - x0, y - y0);
        const duration = ms > 0 ? Math.max(120, ms) : Math.max(160, Math.min(900, 160 + dist * 0.5));
        // Bend upwards, away from the bottom panel.
        const bend = Math.min(90, dist * 0.12);
        let nx = -(y - y0) / (dist || 1), ny = (x - x0) / (dist || 1);
        if (ny > 0) {
            nx = -nx;
            ny = -ny;
        }
        const cx = (x0 + x) / 2 + nx * bend;
        const cy = (y0 + y) / 2 + ny * bend;
        return new Promise(resolve => {
            const timeline = new Clutter.Timeline({actor: global.stage, duration});
            timeline.set_progress_mode(Clutter.AnimationMode.EASE_IN_OUT_CUBIC);
            timeline.connect('new-frame', () => {
                const e = timeline.get_progress();
                this.moveTo(
                    (1 - e) * (1 - e) * x0 + 2 * (1 - e) * e * cx + e * e * x,
                    (1 - e) * (1 - e) * y0 + 2 * (1 - e) * e * cy + e * e * y);
            });
            timeline.connect('completed', () => {
                this.moveTo(x, y);
                this._glide = null;
                resolve();
            });
            this._glide = {timeline, resolve};
            timeline.start();
        });
    }

    button(button, pressed) {
        this._pointer.notify_button(GLib.get_monotonic_time(), button,
            pressed ? Clutter.ButtonState.PRESSED : Clutter.ButtonState.RELEASED);
    }

    async click(button, count) {
        for (let i = 0; i < Math.max(1, count); i++) {
            this.button(button, true);
            await sleep(55);
            this.button(button, false);
            await sleep(85);
        }
    }

    async scroll(steps, horizontal) {
        const direction = horizontal
            ? (steps > 0 ? Clutter.ScrollDirection.RIGHT : Clutter.ScrollDirection.LEFT)
            : (steps > 0 ? Clutter.ScrollDirection.DOWN : Clutter.ScrollDirection.UP);
        for (let i = 0; i < Math.abs(steps); i++) {
            this._pointer.notify_discrete_scroll(GLib.get_monotonic_time(), direction, Clutter.ScrollSource.WHEEL);
            await sleep(45);
        }
    }

    _key(keyval, pressed) {
        this._keyboard.notify_keyval(GLib.get_monotonic_time(), keyval,
            pressed ? Clutter.KeyState.PRESSED : Clutter.KeyState.RELEASED);
    }

    async keys(combo) {
        const keyvals = combo.split('+').map(part => part.trim()).filter(Boolean).map(keyvalFor);
        for (const keyval of keyvals) {
            this._key(keyval, true);
            await sleep(30);
        }
        for (const keyval of [...keyvals].reverse()) {
            this._key(keyval, false);
            await sleep(20);
        }
    }

    async type(text, delayMs) {
        for (const ch of text) {
            const keyval = ch === '\n' ? Clutter.KEY_Return : Clutter.unicode_to_keysym(ch.codePointAt(0));
            this._key(keyval, true);
            await sleep(12);
            this._key(keyval, false);
            await sleep(delayMs > 0 ? delayMs : 35);
        }
    }
}
