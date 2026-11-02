// Everything Clicky draws on screen: the buddy pointer, its label bubble,
// rings, the caption bar and sketches. Lives directly on the stage above the
// shell UI, so it stays visible over the overview, menus and the panel. Nothing
// here is reactive: clicks always fall through to whatever is underneath.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Pango from 'gi://Pango';
import PangoCairo from 'gi://PangoCairo';
import St from 'gi://St';
import Cairo from 'cairo';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PointerWatcher from 'resource:///org/gnome/shell/ui/pointerWatcher.js';

const ACCENT = [1.0, 0.353, 0.212];
const ACCENT_CSS = 'rgb(255, 90, 54)';
const INK_CSS = 'rgba(20, 22, 27, 0.94)';

const PALETTE = {
    coral: ACCENT,
    blue: [0.24, 0.55, 0.96],
    green: [0.18, 0.72, 0.45],
    yellow: [0.98, 0.78, 0.18],
    white: [1, 1, 1],
    black: [0.08, 0.08, 0.1],
};

// The buddy is a 96px box; the pointer tip sits at BOX_TIP inside it and the
// arrow body is centred a little below-right of the tip.
const BOX = 96;
const BOX_TIP = 32;
const BODY = 41;
const ARROW_TIP = 4;
const FOLLOW_OFFSET = [14, 16];

const now = () => GLib.get_monotonic_time() / 1000;
const easeInOutCubic = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function polylineLength(points) {
    let total = 0;
    for (let i = 1; i < points.length; i++)
        total += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    return total;
}

export class Overlay {
    constructor() {
        this._state = 'idle';
        this._level = 0;
        this._shownLevel = 0;
        this._mode = 'follow';
        this._pos = null;
        this._target = null;
        this._flight = null;
        this._shapes = [];
        this._rings = [];
        this._hidden = false;
        this._bubbleText = '';

        this._root = new St.Widget({name: 'clicky-overlay', reactive: false});
        global.stage.add_child(this._root);

        this._drawing = new St.DrawingArea({reactive: false});
        this._drawing.connect('repaint', area => this._paintShapes(area));
        this._root.add_child(this._drawing);

        this._buddy = new St.Widget({reactive: false, width: BOX, height: BOX, visible: false});
        this._halo = new St.DrawingArea({reactive: false, width: BOX, height: BOX, visible: false});
        this._halo.connect('repaint', area => this._paintHalo(area));
        this._spinner = new St.DrawingArea({reactive: false, width: 56, height: 56, x: BODY - 28, y: BODY - 28, visible: false});
        this._spinner.set_pivot_point(0.5, 0.5);
        this._spinner.connect('repaint', area => this._paintSpinner(area));
        this._pointer = new St.DrawingArea({reactive: false, width: 34, height: 34, x: BOX_TIP - ARROW_TIP, y: BOX_TIP - ARROW_TIP});
        this._pointer.connect('repaint', area => this._paintPointer(area));
        this._buddy.add_child(this._halo);
        this._buddy.add_child(this._spinner);
        this._buddy.add_child(this._pointer);
        this._root.add_child(this._buddy);

        this._bubble = new St.Label({
            reactive: false, opacity: 0,
            style: `background-color: ${INK_CSS}; color: #ffffff; border-radius: 10px; padding: 7px 12px; font-size: 14px; font-weight: 600;`,
        });
        this._bubble.clutter_text.line_wrap = true;
        this._root.add_child(this._bubble);

        this._caption = new St.Label({reactive: false, opacity: 0});
        this._caption.clutter_text.line_wrap = true;
        this._root.add_child(this._caption);

        this._timeline = new Clutter.Timeline({actor: this._root, duration: 1000, repeat_count: -1});
        this._timeline.connect('new-frame', () => this._tick());

        this._watch = PointerWatcher.getPointerWatcher().addWatch(16, (x, y) => this._onPointer(x, y));
        const [px, py] = global.get_pointer();
        this._onPointer(px, py);

        global.stage.connectObject(
            'notify::width', () => this._syncSize(),
            'notify::height', () => this._syncSize(),
            'child-added', (stage, child) => {
                if (child !== this._root)
                    stage.set_child_above_sibling(this._root, null);
            }, this);
        Main.sessionMode.connectObject('updated', () => this._syncVisible(), this);
        this._syncSize();
        this._syncVisible();
        this.setState('idle');
    }

    destroy() {
        this._watch?.remove();
        this._watch = null;
        this._flight?.resolve();
        this._flight = null;
        this._timeline.stop();
        global.stage.disconnectObject(this);
        Main.sessionMode.disconnectObject(this);
        this._root.destroy();
    }

    // ---- public API (called from service.js) ----

    setHidden(hidden) {
        this._hidden = hidden;
        this._syncVisible();
    }

    setState(state) {
        this._state = state;
        this._buddy.visible = state !== 'hidden';
        this._spinner.visible = state === 'thinking';
        this._halo.visible = state === 'listening' || state === 'speaking';
        this._pointer.opacity = state === 'idle' ? 215 : 255;
        if (state !== 'listening')
            this._level = 0;
        this._spinner.queue_repaint();
        this._halo.queue_repaint();
        this._kick();
    }

    setLevel(level) {
        this._level = Math.max(0, Math.min(1, level));
        this._kick();
    }

    flyTo(x, y, label, ms) {
        this._hideBubble();
        const [x0, y0] = this._pos ?? [x, y];
        const dx = x - x0, dy = y - y0;
        const dist = Math.hypot(dx, dy);
        // Bend the path into a gentle arc that bulges upwards, like a hand moving.
        let nx = -dy / (dist || 1), ny = dx / (dist || 1);
        if (ny > 0) {
            nx = -nx;
            ny = -ny;
        }
        const bend = Math.min(160, dist * 0.22);
        const duration = ms > 0 ? ms : Math.max(380, Math.min(1100, 300 + dist * 0.6));
        this._flight?.resolve();
        return new Promise(resolve => {
            this._flight = {
                x0, y0, x1: x, y1: y,
                cx: (x0 + x) / 2 + nx * bend, cy: (y0 + y) / 2 + ny * bend,
                start: now(), duration, label, resolve,
            };
            this._mode = 'fly';
            this._kick();
        });
    }

    home() {
        this._flight?.resolve();
        this._flight = null;
        this._mode = 'follow';
        this._hideBubble();
        this._kick();
    }

    ring(x, y, kind) {
        if (kind === 'off') {
            this._rings.forEach(r => r.destroy());
            this._rings = [];
            return;
        }
        const size = kind === 'click' ? 34 : 58;
        const ring = new St.Widget({
            reactive: false, width: size, height: size,
            x: Math.round(x - size / 2), y: Math.round(y - size / 2),
            style: `border: 3px solid ${ACCENT_CSS}; border-radius: ${size}px;`,
        });
        ring.set_pivot_point(0.5, 0.5);
        this._root.insert_child_below(ring, this._buddy);
        if (kind === 'click') {
            ring.set_scale(0.5, 0.5);
            ring.ease({
                scale_x: 1.9, scale_y: 1.9, opacity: 0, duration: 480,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onStopped: () => ring.destroy(),
            });
            return;
        }
        this._rings.push(ring);
        const loop = () => {
            if (!this._rings.includes(ring))
                return;
            ring.set_scale(0.6, 0.6);
            ring.opacity = 255;
            ring.ease({
                scale_x: 1.5, scale_y: 1.5, opacity: 0, duration: 1100,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: loop,
            });
        };
        loop();
    }

    caption(text, kind) {
        if (!text) {
            this._caption.remove_all_transitions();
            this._caption.ease({opacity: 0, duration: 200});
            return;
        }
        const styles = {
            say: 'font-size: 17px; color: #ffffff;',
            heard: 'font-size: 16px; color: #d6dae1; font-style: italic;',
            hint: 'font-size: 14px; color: #ffffff;',
        };
        this._caption.style = `background-color: rgba(20, 22, 27, 0.9); border-radius: 12px; padding: 10px 18px; ${styles[kind] ?? styles.say}`;
        this._caption.text = kind === 'heard' ? `“${text}”` : text;
        const area = Main.layoutManager.getWorkAreaForMonitor(Main.layoutManager.primaryIndex);
        const maxWidth = Math.min(780, area.width * 0.7);
        this._caption.set_width(-1);
        const [, natWidth] = this._caption.get_preferred_width(-1);
        const width = Math.min(natWidth, maxWidth);
        this._caption.set_width(width);
        const [, natHeight] = this._caption.get_preferred_height(width);
        this._caption.set_position(
            Math.round(area.x + (area.width - width) / 2),
            Math.round(area.y + area.height - natHeight - 28));
        this._caption.remove_all_transitions();
        this._caption.ease({opacity: 255, duration: 160});
    }

    draw(spec) {
        let start = now();
        for (const s of spec.shapes ?? []) {
            const shape = {
                ...s,
                rgb: PALETTE[s.color] ?? ACCENT,
                start,
                duration: spec.animate === false ? 0 : (s.kind === 'text' ? 260 : 600),
            };
            shape.points = this._shapePoints(shape);
            this._shapes.push(shape);
            start += shape.duration * 0.85;
        }
        this._drawing.queue_repaint();
        this._kick();
    }

    clearDrawings() {
        this._shapes = [];
        this._drawing.queue_repaint();
    }

    boxes() {
        const out = [];
        if (this._buddy.visible && this._pos)
            out.push([this._pos[0] - 8, this._pos[1] - 8, 70, 70]);
        for (const actor of [this._bubble, this._caption, ...this._rings]) {
            if (actor.opacity > 0 && actor.visible) {
                const [x, y] = actor.get_position();
                const [w, h] = actor.get_size();
                out.push([x - 16, y - 16, w + 32, h + 32]);
            }
        }
        for (const s of this._shapes) {
            const xs = (s.points.length ? s.points : [[s.x, s.y]]).map(p => p[0]);
            const ys = (s.points.length ? s.points : [[s.x, s.y]]).map(p => p[1]);
            const pad = s.kind === 'text' ? 400 : 24;
            out.push([Math.min(...xs) - 24, Math.min(...ys) - 24, Math.max(...xs) - Math.min(...xs) + pad, Math.max(...ys) - Math.min(...ys) + 48]);
        }
        return out.map(b => b.map(Math.round));
    }

    // ---- internals ----

    _syncSize() {
        this._root.set_size(global.stage.width, global.stage.height);
        this._drawing.set_size(global.stage.width, global.stage.height);
    }

    _syncVisible() {
        this._root.visible = !this._hidden && !Main.sessionMode.isLocked;
    }

    _kick() {
        if (!this._timeline.is_playing())
            this._timeline.start();
    }

    _onPointer(x, y) {
        this._target = [x + FOLLOW_OFFSET[0], y + FOLLOW_OFFSET[1]];
        if (!this._pos)
            this._setTip(...this._target);
        if (this._mode === 'follow')
            this._kick();
    }

    _setTip(x, y) {
        this._pos = [x, y];
        this._buddy.set_position(Math.round(x - BOX_TIP), Math.round(y - BOX_TIP));
        if (this._bubbleText)
            this._placeBubble();
    }

    _tick() {
        const t = now();
        let busy = false;

        if (this._flight) {
            const f = this._flight;
            const p = Math.min(1, (t - f.start) / f.duration);
            const e = easeInOutCubic(p);
            const x = (1 - e) * (1 - e) * f.x0 + 2 * (1 - e) * e * f.cx + e * e * f.x1;
            const y = (1 - e) * (1 - e) * f.y0 + 2 * (1 - e) * e * f.cy + e * e * f.y1;
            this._setTip(x, y);
            if (p >= 1) {
                this._flight = null;
                this._mode = 'pinned';
                this._showBubble(f.label);
                f.resolve();
            } else {
                busy = true;
            }
        } else if (this._mode === 'follow' && this._target) {
            const [tx, ty] = this._target;
            const [x, y] = this._pos ?? this._target;
            const nx = x + (tx - x) * 0.32, ny = y + (ty - y) * 0.32;
            if (Math.abs(tx - nx) < 0.6 && Math.abs(ty - ny) < 0.6) {
                this._setTip(tx, ty);
            } else {
                this._setTip(nx, ny);
                busy = true;
            }
        }

        if (this._state === 'thinking') {
            this._spinner.rotation_angle_z = (t * 0.4) % 360;
            busy = true;
        }
        if (this._state === 'listening' || this._state === 'speaking') {
            this._shownLevel += (this._level - this._shownLevel) * 0.35;
            this._halo.queue_repaint();
            busy = true;
        }
        if (this._shapes.some(s => s.duration && t < s.start + s.duration + 20)) {
            this._drawing.queue_repaint();
            busy = true;
        }
        if (!busy)
            this._timeline.stop();
    }

    _showBubble(text) {
        this._bubbleText = text ?? '';
        if (!this._bubbleText)
            return;
        this._bubble.text = this._bubbleText;
        this._bubble.set_width(-1);
        const [, natWidth] = this._bubble.get_preferred_width(-1);
        this._bubble.set_width(Math.min(natWidth, 320));
        this._placeBubble();
        this._bubble.remove_all_transitions();
        this._bubble.ease({opacity: 255, duration: 150});
    }

    _hideBubble() {
        this._bubbleText = '';
        this._bubble.remove_all_transitions();
        this._bubble.opacity = 0;
    }

    _placeBubble() {
        const [tx, ty] = this._pos;
        const [w, h] = this._bubble.get_size();
        let x = tx + 26, y = ty + 26;
        if (x + w > global.stage.width - 8)
            x = tx - 14 - w;
        if (y + h > global.stage.height - 8)
            y = ty - 14 - h;
        this._bubble.set_position(Math.round(Math.max(8, x)), Math.round(Math.max(8, y)));
    }

    _shapePoints(s) {
        switch (s.kind) {
        case 'line':
        case 'arrow':
            return [[s.x, s.y], [s.x2, s.y2]];
        case 'box':
            return [[s.x, s.y], [s.x2, s.y], [s.x2, s.y2], [s.x, s.y2], [s.x, s.y]];
        case 'circle': {
            const r = s.r ?? 40;
            const pts = [];
            for (let i = 0; i <= 72; i++) {
                const a = -Math.PI * 0.6 + (i / 72) * Math.PI * 2.08;
                pts.push([s.x + Math.cos(a) * r, s.y + Math.sin(a) * r]);
            }
            return pts;
        }
        case 'path':
            return s.points ?? [];
        default:
            return [];
        }
    }

    _paintShapes(area) {
        const cr = area.get_context();
        cr.setOperator(Cairo.Operator.CLEAR);
        cr.paint();
        cr.setOperator(Cairo.Operator.OVER);
        cr.setLineCap(Cairo.LineCap.ROUND);
        cr.setLineJoin(Cairo.LineJoin.ROUND);
        const t = now();
        for (const s of this._shapes) {
            const p = s.duration ? Math.max(0, Math.min(1, (t - s.start) / s.duration)) : 1;
            if (p <= 0)
                continue;
            if (s.kind === 'text') {
                this._paintText(cr, s.x, s.y, s.text ?? '', s.size ?? 22, p);
                continue;
            }
            this._strokePartial(cr, s.points, p, s.rgb, s.width ?? 4);
            if (s.kind === 'arrow' && p >= 1)
                this._arrowHead(cr, s);
            if (s.text && p >= 1)
                this._paintText(cr, s.points[0][0], s.points[0][1] - 34, s.text, 18, 1);
        }
        cr.$dispose();
    }

    _strokePartial(cr, points, progress, rgb, width) {
        if (points.length < 2)
            return;
        let remaining = polylineLength(points) * progress;
        const path = [points[0]];
        for (let i = 1; i < points.length && remaining > 0; i++) {
            const [ax, ay] = points[i - 1];
            const [bx, by] = points[i];
            const seg = Math.hypot(bx - ax, by - ay);
            if (seg <= remaining) {
                path.push(points[i]);
                remaining -= seg;
            } else {
                const k = remaining / seg;
                path.push([ax + (bx - ax) * k, ay + (by - ay) * k]);
                remaining = 0;
            }
        }
        const trace = () => {
            cr.moveTo(...path[0]);
            for (const pt of path.slice(1))
                cr.lineTo(...pt);
        };
        // A white halo under the colored stroke keeps it readable on any background.
        trace();
        cr.setSourceRGBA(1, 1, 1, 0.85);
        cr.setLineWidth(width + 4);
        cr.stroke();
        trace();
        cr.setSourceRGBA(rgb[0], rgb[1], rgb[2], 1);
        cr.setLineWidth(width);
        cr.stroke();
    }

    _arrowHead(cr, s) {
        const angle = Math.atan2(s.y2 - s.y, s.x2 - s.x);
        const len = 18;
        const trace = () => {
            for (const side of [-1, 1]) {
                const a = angle + Math.PI + side * 0.5;
                cr.moveTo(s.x2, s.y2);
                cr.lineTo(s.x2 + Math.cos(a) * len, s.y2 + Math.sin(a) * len);
            }
        };
        trace();
        cr.setSourceRGBA(1, 1, 1, 0.85);
        cr.setLineWidth((s.width ?? 4) + 4);
        cr.stroke();
        trace();
        cr.setSourceRGBA(s.rgb[0], s.rgb[1], s.rgb[2], 1);
        cr.setLineWidth(s.width ?? 4);
        cr.stroke();
    }

    _paintText(cr, x, y, text, size, alpha) {
        const layout = PangoCairo.create_layout(cr);
        layout.set_font_description(Pango.FontDescription.from_string(`Sans Bold ${Math.round(size)}px`));
        layout.set_text(text, -1);
        const [, logical] = layout.get_pixel_extents();
        const padX = 10, padY = 6;
        const w = logical.width + padX * 2, h = logical.height + padY * 2;
        const r = 8;
        cr.newSubPath();
        cr.arc(x + w - r, y + r, r, -Math.PI / 2, 0);
        cr.arc(x + w - r, y + h - r, r, 0, Math.PI / 2);
        cr.arc(x + r, y + h - r, r, Math.PI / 2, Math.PI);
        cr.arc(x + r, y + r, r, Math.PI, Math.PI * 1.5);
        cr.closePath();
        cr.setSourceRGBA(0.08, 0.09, 0.11, 0.88 * alpha);
        cr.fill();
        cr.moveTo(x + padX, y + padY);
        cr.setSourceRGBA(1, 1, 1, alpha);
        PangoCairo.show_layout(cr, layout);
    }

    _paintPointer(area) {
        const cr = area.get_context();
        const t = ARROW_TIP;
        const trace = (dx, dy) => {
            cr.moveTo(t + dx, t + dy);
            cr.lineTo(t + 5 + dx, t + 22 + dy);
            cr.lineTo(t + 10 + dx, t + 12.5 + dy);
            cr.lineTo(t + 22 + dx, t + 7 + dy);
            cr.closePath();
        };
        cr.setLineJoin(Cairo.LineJoin.ROUND);
        trace(1.2, 1.8);
        cr.setSourceRGBA(0, 0, 0, 0.28);
        cr.fill();
        trace(0, 0);
        cr.setSourceRGBA(ACCENT[0], ACCENT[1], ACCENT[2], 1);
        cr.fillPreserve();
        cr.setSourceRGBA(1, 1, 1, 1);
        cr.setLineWidth(2);
        cr.stroke();
        cr.$dispose();
    }

    _paintHalo(area) {
        const cr = area.get_context();
        let radius, alpha;
        if (this._state === 'listening') {
            radius = 16 + 22 * this._shownLevel;
            alpha = 0.35 + 0.4 * this._shownLevel;
        } else {
            const breath = (Math.sin(now() / 260) + 1) / 2;
            radius = 18 + 5 * breath;
            alpha = 0.22 + 0.12 * breath;
        }
        cr.arc(BODY, BODY, radius, 0, Math.PI * 2);
        cr.setSourceRGBA(ACCENT[0], ACCENT[1], ACCENT[2], alpha * 0.45);
        cr.fillPreserve();
        cr.setSourceRGBA(ACCENT[0], ACCENT[1], ACCENT[2], Math.min(1, alpha + 0.2));
        cr.setLineWidth(2.5);
        cr.stroke();
        cr.$dispose();
    }

    _paintSpinner(area) {
        const cr = area.get_context();
        cr.setLineCap(Cairo.LineCap.ROUND);
        cr.arc(28, 28, 22, 0, Math.PI * 1.35);
        cr.setSourceRGBA(1, 1, 1, 0.9);
        cr.setLineWidth(6);
        cr.stroke();
        cr.arc(28, 28, 22, 0, Math.PI * 1.35);
        cr.setSourceRGBA(ACCENT[0], ACCENT[1], ACCENT[2], 1);
        cr.setLineWidth(3.5);
        cr.stroke();
        cr.$dispose();
    }
}
