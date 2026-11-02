// Finds GNOME Shell's own UI elements (panel buttons, app grid icons, menus,
// quick settings) by name, with their position on screen. Client windows are
// not walked here; the app reads those through AT-SPI.

import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

function namesOf(actor) {
    const names = [];
    const add = value => {
        if (typeof value === 'string' && value.trim() && !names.includes(value.trim()))
            names.push(value.trim());
    };
    add(actor.accessible_name);
    if (actor.app?.get_name)
        add(actor.app.get_name());
    if (actor instanceof St.Label)
        add(actor.text);
    if (actor instanceof St.Button && typeof actor.label === 'string')
        add(actor.label);
    add(actor.label_actor?.text);
    add(actor.title);
    return names;
}

function onScreen(x, y, w, h) {
    return w > 1 && h > 1 && x + w > 0 && y + h > 0 && x < global.stage.width && y < global.stage.height;
}

export function collect() {
    const out = [];
    const skip = new Set([global.window_group]);
    const walk = (actor, depth) => {
        if (depth > 60 || skip.has(actor) || !actor.visible || actor.opacity === 0)
            return;
        const names = namesOf(actor);
        if (names.length && actor.mapped) {
            const [x, y] = actor.get_transformed_position();
            const [w, h] = actor.get_transformed_size();
            if (onScreen(x, y, w, h)) {
                out.push({
                    name: names[0], names,
                    type: actor.constructor.name ?? '',
                    style: actor.style_class ?? '',
                    app_id: actor.app?.get_id?.() ?? '',
                    reactive: actor.reactive,
                    checked: actor.checked ?? null,
                    value: typeof actor.value === 'number' ? actor.value : null,
                    max: typeof actor.maximum_value === 'number' ? actor.maximum_value : null,
                    x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h),
                });
            }
        }
        for (const child of actor.get_children())
            walk(child, depth + 1);
    };
    walk(Main.layoutManager.uiGroup, 0);
    return out;
}

// query: {name, app_id, type, exact}. Names match case-insensitively; without
// `exact` a query name matching the start of an element name also counts.
export function find(query) {
    const want = (query.name ?? '').toLocaleLowerCase('tr');
    return collect().filter(el => {
        if (query.app_id && el.app_id.toLowerCase() !== query.app_id.toLowerCase())
            return false;
        if (query.type && el.type !== query.type)
            return false;
        if (!want)
            return true;
        return el.names.some(n => {
            const have = n.toLocaleLowerCase('tr');
            return query.exact ? have === want : have === want || have.startsWith(want);
        });
    });
}
