# AGENTS.md

Notes for coding agents (and people) working on Pardus Clicky. Read this
before changing anything. README.md explains what the product does.

## The project and how it is built

Pardus Clicky brings the idea of clicky.ai (an AI that teaches by showing you,
with its own pointer, where to click) to Pardus, Turkey's national Linux
distribution, for the TEKNOFEST Pardus competition.

The work is split into many short sessions, **one part of Pardus per session**:

| Session | Scope | Status |
|---|---|---|
| 1 | Desktop: panel, app grid, desktop icons and menu, Settings basics, Files basics, voice in/out, pointer overlay, drawing | done (this code) |
| next | One app each: terminal, Pardus whiteboard / Pardus Pen, music player, Files in depth, Firefox, LibreOffice, ... | todo |
| later | Turkish voice and captions as the default | wired, not tested end to end |
| later | XFCE edition (X11) | not started |
| last | Combine everything, polish for the jury | todo |

Stay inside your session's scope. Quality on one app beats shallow support for many.

## Non-negotiable product rules

1. **No scripts.** Clicky never opens a terminal, runs commands or edits files
   directly. Every change happens through visible clicks, menus and typing in
   the normal UI, so the user can learn. The model is told this in
   `prompts.py`; keep it that way when adding tools.
2. **Visible and explained.** Every action is preceded by the pointer flying
   to the target and a short spoken sentence (also shown as a caption).
3. **One step per model turn**, then a fresh screenshot. Never let the model
   batch blind actions.
4. **Confirm before anything destructive** (delete, empty trash, uninstall,
   log out, passwords) through `ask_user`.
5. **Copy style** (the project owner is strict about this): short, human
   sentences; no em dashes or `--` in anything the user sees (spoken, captions,
   labels, drawings, UI); no implementation details in the UI; no generic
   "AI-looking" boxes of icon + title + description.
6. **Git**: commit under the owner's identity only. No `Co-Authored-By`, no
   "Generated with" lines. Commit or push only when asked.

## Repository map

```
pardus_clicky/            the app (Python 3.13 + PyGObject, GTK 3, GStreamer; no pip deps)
  __main__.py             CLI; forwards listen/ask/stop to the running app over D-Bus
  app.py                  Gtk.Application: panel icon, actions, worker thread, listening, windows
  agent.py                the loop: screenshot -> model -> one step -> screenshot
  tools.py                function-tool schemas (strict) the model calls: step, draw, ask_user, finish
  prompts.py              system instructions + per-step state text
  packs/                  knowledge packs (Markdown) per part of Pardus; desktop.md is always on
  shell.py                D-Bus client of the GNOME Shell extension
  vision.py               screenshots for the model; change detection while waiting for the user
  voice.py                Recorder (mic + end-of-speech), Speaker (streamed TTS playback)
  openai_api.py           tiny stdlib client: responses, transcriptions, speech (+ streaming)
  hotkey.py               registers Super+Z as a GNOME custom shortcut
  i18n.py                 UI strings EN/TR, spoken reply words ("do it", "tamam", ...)
  doctor.py               `pardus-clicky doctor`
  data/icons/             app and panel icons
extension/clicky@pardus.org.tr/   GNOME Shell 46-49 extension
  extension.js            tiny loader (supports hot reload, see below)
  lib/service.js          D-Bus API tr.org.pardus.clicky.Shell, caller check
  lib/overlay.js          pointer, bubble, rings, caption, sketches (all non-reactive)
  lib/input.js            real pointer/keyboard via Clutter virtual devices
bin/pardus-clicky         launcher from a checkout
scripts/install.sh        per-user install (extension link, menu entry, autostart)
scripts/dev/              VM tooling (see below)
tests/test_logic.py       unit tests (run on Pardus)
secrets/                  gitignored: openai.key, vm_ed25519 (+ .pub), vm_ip
```

## Architecture in detail

### Why a GNOME Shell extension

Pardus 25 GNOME runs Wayland. Three things an assistant needs are locked down
there, and the extension solves all of them from inside the compositor:

- **Drawing above everything.** An Xwayland overlay window works over normal
  windows but GNOME hides it while the app grid/overview is open, and the Pardus
  button opens exactly that. Our actors live on the stage above `uiGroup`, so
  they show over the overview, menus and the panel.
- **Screenshots.** `org.gnome.Shell.Screenshot` refuses outside callers. Inside
  the shell, `Shell.Screenshot` works.
- **Input.** Clutter virtual devices give real clicks and key presses without
  the screen-sharing portal or root.

The extension only answers callers that own the bus name `tr.org.pardus.clicky`
(the app), like GNOME's own `DBusSenderChecker`. `Ping` and `Reload` are open.

Mutter's own `org.gnome.Mutter.RemoteDesktop` + `ScreenCast` also work for
input and capture without a prompt (see `scripts/dev/fake_user.py`), but they
show the orange sharing indicator; the app does not use them.

### D-Bus API (`tr.org.pardus.clicky.Shell`, `/tr/org/pardus/clicky/Shell`)

| Method | What it does |
|---|---|
| `Ping() -> s` | version; unguarded |
| `Reload()` | re-import `lib/` without logging out; unguarded |
| `GetState() -> s` | JSON: stage size, pointer, overview open, work area, monitors, windows (title, app, frame rect, focus) |
| `Screenshot(s path, b hide_overlay) -> s` | PNG to path; JSON with stage size and overlay boxes (for masking) |
| `SetState(s)` | pointer look: idle, listening, thinking, speaking, acting, waiting, hidden |
| `SetLevel(d)` | mic level 0..1 for the listening halo |
| `FlyTo(d x, d y, s label, u ms)` | pointer flies on a curve, then shows the label; returns on arrival |
| `Home()` | pointer goes back to trailing the real cursor |
| `Ring(d x, d y, s kind)` | `click` ripple, `attention` loop, `off` |
| `Caption(s text, s kind)` | subtitle bar above the panel; kinds `say`, `heard`, `hint`; empty text hides |
| `Draw(s json)` / `ClearDrawings()` | sketches: circle, arrow, box, line, path, text; colors coral, blue, green, yellow, white, black |
| `PointerGlide(d x, d y, u ms)` | moves the real pointer on a curve |
| `PointerButton(u button, b pressed)`, `Click(u button, u count)` | 1 left, 2 middle, 3 right |
| `Scroll(i steps, b horizontal)`, `Keys(s combo)`, `Type(s text, u delay_ms)` | keyboard uses keysyms, so the Turkish layout just works |

All coordinates are stage (logical screen) pixels. The model works in
screenshot pixels; `vision.Shot.to_stage()` converts.

### The agent loop

- Stateless Responses API calls (`store: false`), encrypted reasoning passed
  back, only the newest 2 screenshots kept as images (`trim_images`).
- `tool_choice: required`, `parallel_tool_calls: false`: one tool per turn.
- `step` fields: `say`, `label`, `action` (click, double_click, right_click,
  drag, scroll, type, keys, point, wait), `performer` (assistant/user), coords,
  `text`, `keys` (comma-separated combos), `amount`.
- `performer: user` means: point, ring, wait until the screen changes
  (`vision.fingerprint`, overlay masked out), or until the user presses the
  shortcut and says "do it" / "done" / "stop".
- Errors from a step (bad key name, ...) go back to the model as the tool
  result, so it can try another way.
- `type` does not click first: rename boxes open with the old name selected,
  and a click would drop the selection. The model clicks fields in a separate step.

### Speech

- Recorder: GStreamer `pulsesrc`, 16 kHz mono, energy-based end-of-speech
  (`Endpointer`, unit tested). It calls `on_ready` when the first audio
  arrives; only then does the caption say "Listening...".
- Speaker: OpenAI TTS streamed as raw PCM into a GStreamer `appsrc`, so speech
  starts after about 1 s. The end is detected from the sink's play position,
  not EOS (EOS arrives seconds late on some sinks). Falls back to `spd-say`.
- The pointer flies while the sentence is being fetched and spoken.

### Knowledge packs (how to add an app)

`pardus_clicky/packs/*.md`. The first line names the apps the pack is about:

```
<!-- apps: org.gnome.console, kgx -->
```

Values are desktop-file ids or WM_CLASS, lower case (see `GetState` windows
for the exact strings). `*` means always included. A pack is added to the
model's instructions while one of its apps has a window open.

To add support for an app in a new session:

1. Open the app in the VM and screenshot every screen you care about
   (`scripts/dev/vm.sh shot`). Write down the exact Turkish labels.
2. Write `packs/<app>.md`: layout, where things are, the common tasks as short
   recipes, gotchas (what needs a double-click, which dialogs pop up).
   Only verified facts.
3. If the app needs a capability the tools lack (for example drawing inside a
   whiteboard with the real pen), add it to `tools.py` + `agent.py` (and the
   extension if it needs the compositor). Keep schemas strict; the unit test
   checks them.
4. Run real requests on the VM, by text and by voice, in both modes. Read
   `~/.cache/pardus-clicky/clicky.log` (every step logs its tool call and timing).
5. Add the verified requests to the README table.

## The test VM

The owner develops on Windows; Pardus runs in **VMware Workstation**:
`C:\Users\eminb\Documents\Virtual Machines\Pardus 25\Pardus 25.vmx`
(Pardus 25.2 GNOME, user `pardus`, password `pardus`, NAT network).

Already set up in the VM: `open-vm-tools-desktop`, `openssh-server`, our SSH
key (`secrets/vm_ed25519`), screen lock and blanking off, and a WirePlumber fix
for VMware audio (see Gotchas). The checkout lives at `~/pardus-clicky`, the
extension is linked into `~/.local/share/gnome-shell/extensions/`.

From Git Bash on the host:

```bash
scripts/dev/vm.sh deploy            # copy the checkout (and secrets/openai.key) to the VM
scripts/dev/vm.sh restart           # restart the app in the GNOME session
scripts/dev/vm.sh sh 'cmd'          # run in the session (DBus/Wayland env set)
scripts/dev/vm.sh shot out.png      # screenshot taken by VMware (shows exactly what the user sees)
scripts/dev/vm.sh reload-ext        # reload extension lib/ without logging out
scripts/dev/vm.sh logs              # app log + extension messages
```

Inside the VM (via `vm.sh sh`):

```bash
cd ~/pardus-clicky && bin/pardus-clicky ask "show me how to ..."   # typed request
TRIGGER=hotkey scripts/dev/say_to_mic.sh "spoken request" en        # real Super+Z + a virtual microphone
python3 scripts/dev/fake_user.py click X Y                          # play the user (guide mode)
python3 scripts/dev/fake_user.py keys super+z
python3 scripts/dev/overlay_demo.py [overview]                      # extension smoke test (app must be stopped)
python3 -m unittest discover -s tests                               # unit tests
bin/pardus-clicky doctor
```

If the VM is off: `vmrun -T ws start "<vmx>" gui`, then the user (or you,
via the console) logs in. VMware Tools must be running for `vm.sh shot`.

## Gotchas (each one cost time)

- **VMware audio**: PipeWire's default timer scheduling underruns on VMware HD
  Audio (272 xruns; a 2 s sound took 6 s; the mic took 6.8 s to open).
  Fixed in the VM with `~/.config/wireplumber/wireplumber.conf.d/50-vmware-audio.conf`
  (`api.alsa.headroom = 8192`, `api.alsa.disable-tsched = true`,
  `session.suspend-timeout-seconds = 0`), then
  `systemctl --user restart wireplumber pipewire pipewire-pulse`. This is VM only.
- **New extension = one re-login** on Wayland. After that, use `Reload`.
  Changes to `extension.js` itself (the loader) or `metadata.json` still need a re-login.
- **Screen lock** blocks input injection ("Session creation inhibited") and
  hides the overlay. Unlock with `loginctl unlock-session <id>`.
- **Super+C** is Pardus's calculator key, hence Super+Z.
- **pkill -f** patterns must not match your own SSH command line (use `[p]attern`).
- **Files written on Windows**: `.gitattributes` forces LF; a CRLF shell
  script fails on Pardus.
- The overlay demo and anything else calling the extension must own the bus
  name `tr.org.pardus.clicky`, so stop the app first.
- The model calls `point` + `wait` instead of waiting for a user click unless
  the prompt says so explicitly (fixed in `prompts.py`; keep that paragraph).
- Typing into a selected field: never click first (see agent loop).
- The app grid order changes between sessions; never hard-code positions.

## Known limits and next steps

- Only the GNOME edition. XFCE (X11) needs an X11 driver: an override-redirect
  overlay window, XTest input and a root-window screenshot, behind the same
  methods as `shell.py`.
- Turkish (`language: tr`) is wired through prompts, captions, TTS and the
  reply words, but has not been tested end to end yet.
- Grounding is vision only. Accessibility (AT-SPI) coordinates of GNOME Shell
  widgets could make clicks pixel-exact in a later session.
- The talk shortcut is press-to-start (GNOME has no hold-to-talk custom keys).
- Per-step latency is about 7 s: model 1.5 to 4 s, speech 2 to 4 s, action and
  settle about 1.5 s.
