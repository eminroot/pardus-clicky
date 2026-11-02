// Pardus Clicky shell helper.
//
// This file is only a loader. The real work lives in lib/service.js so it can
// be reloaded while developing (the Reload D-Bus method) without logging out:
// GNOME Shell on Wayland cannot restart, and ES modules are cached by URL, so a
// reload copies lib/ to a fresh runtime folder and imports it from there.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

function copyDir(src, dest) {
    dest.make_directory_with_parents(null);
    const children = src.enumerate_children('standard::name,standard::type', Gio.FileQueryInfoFlags.NONE, null);
    let info;
    while ((info = children.next_file(null))) {
        const name = info.get_name();
        if (info.get_file_type() === Gio.FileType.DIRECTORY)
            copyDir(src.get_child(name), dest.get_child(name));
        else
            src.get_child(name).copy(dest.get_child(name), Gio.FileCopyFlags.OVERWRITE, null, null);
    }
}

export default class ClickyExtension extends Extension {
    enable() {
        this._enabled = true;
        this._load(this.dir.get_child('lib')).catch(e => console.error('[clicky] load failed', e));
    }

    disable() {
        this._enabled = false;
        this._service?.destroy();
        this._service = null;
    }

    async _load(libDir) {
        const module = await import(libDir.get_child('service.js').get_uri());
        if (!this._enabled)
            return;
        this._service?.destroy();
        this._service = new module.Service({
            version: `${this.metadata.version}`,
            reload: () => this._reload(),
        });
    }

    _reload() {
        const base = GLib.build_filenamev([GLib.get_user_runtime_dir(), 'clicky-shell']);
        const dest = Gio.File.new_for_path(GLib.build_filenamev([base, `${Date.now()}`]));
        copyDir(this.dir.get_child('lib'), dest);
        this._load(dest).catch(e => console.error('[clicky] reload failed', e));
    }
}
