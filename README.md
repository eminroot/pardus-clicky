# Pardus Clicky

A voice guide for the Pardus desktop. You press a shortcut, say what you want
("show me how to change my wallpaper", "organise my Projects folder"), and
Clicky does it the way a person would: a visible pointer flies to each button,
clicks, types, and explains every step out loud. It can also sketch on the
screen (circles, arrows, notes, diagrams) to explain things.

It never runs scripts or terminal commands. Everything happens through the
normal interface, so the user can watch and learn.

Built for the TEKNOFEST Pardus competition. This is the **desktop** part of a
larger project that will add one Pardus app per development session (terminal,
whiteboard, music player, ...). See [AGENTS.md](AGENTS.md) for the plan.

## What works today

Tested end to end on Pardus 25.2 GNOME (GNOME 48, Wayland) in a VM:

| Request (spoken or typed) | What Clicky did |
|---|---|
| "Show me how to change the desktop wallpaper" | App grid → Ayarlar → Görünüm → clicked a wallpaper |
| "Change my wallpaper back to the mountain picture" | Right-click desktop → Arka Planı Değiştir... → picked it |
| "Make a new folder on my desktop called Projects" | Right-click → Yeni Klasör → typed the name |
| "Organise my Projects folder: pictures into Resimler, text files into Belgeler" | Opened it in Dosyalar, made both folders, dragged the 4 files in |
| "What are these icons on my desktop? Draw on the screen to explain them." | Circled each icon with an arrow and a label |
| "Guide me, I want to open the calculator by myself" | Pointed at each step and waited until the user clicked |

A step takes about 7 seconds: thinking (about 2 s), speaking the sentence,
moving and clicking.

## Using it

- **Super+Z**: start talking. Clicky shows *Listening...* when the microphone
  is live and stops by itself when you stop talking. Press again to finish early.
- While Clicky is working, Super+Z interrupts it and listens again.
- When Clicky is waiting for you to click (guide mode), press Super+Z and say
  "do it" to let it do that step, "done" to continue, or "stop".
- The panel icon (white arrow, bottom right) has: Talk, Type a request,
  Stop, Settings, Quit.

Two ways of working, picked from what you say:

- **Show me / do it**: Clicky does the steps itself while you watch.
- **Guide me / let me do it**: Clicky points, you click, it waits and continues.

## Install (Pardus GNOME)

```bash
git clone <this repo> ~/pardus-clicky
```

```bash
cd ~/pardus-clicky && ./scripts/install.sh
```

Then:

1. Log out and back in once (GNOME only loads a new shell extension at login).
2. Save your OpenAI API key: panel icon > Settings, or
   `~/.config/pardus-clicky/openai.key`.
3. Check everything:

```bash
~/pardus-clicky/bin/pardus-clicky doctor
```

Nothing needs pip: the app uses Python 3, PyGObject, GTK 3 and GStreamer,
which ship with Pardus. The installer adds the panel-icon library if missing.

## How it works

```
 voice ──► Recorder (GStreamer, end-of-speech detection)
              │ wav
              ▼
         OpenAI transcription ──► text
              │
              ▼
   ┌──── Agent loop (pardus_clicky/agent.py) ─────────────────────────┐
   │ screenshot + window list ──► OpenAI Responses (gpt-5.6-terra)    │
   │      ◄── one tool call: step / draw / ask_user / finish          │
   │ step: pointer flies there, sentence is spoken (OpenAI TTS),      │
   │       then the click/drag/typing happens, or Clicky waits for    │
   │       the user to do it; then a new screenshot                   │
   └──────────────────────────────────────────────────────────────────┘
              │ D-Bus (tr.org.pardus.clicky.Shell)
              ▼
   GNOME Shell extension clicky@pardus.org.tr
   draws the pointer, bubbles, captions and sketches above everything
   (also over the app grid), takes screenshots, and moves the real
   pointer and keyboard through Clutter virtual devices
```

## Settings

`~/.config/pardus-clicky/config.json` (all optional):

| Key | Default | Meaning |
|---|---|---|
| `language` | `en` | `en` or `tr`: spoken language and captions |
| `performer` | `assistant` | default when the request does not say: `assistant` does it, `user` points |
| `model` | `gpt-5.6-terra` | model that looks at the screen and plans each step |
| `reasoning_effort` | `low` | |
| `stt_model` / `tts_model` / `voice` | `gpt-4o-mini-transcribe` / `gpt-4o-mini-tts` / `marin` | speech in and out |
| `speak` | `true` | `false` keeps Clicky silent (captions only) |
| `mic_device` | `""` | PipeWire source name; empty uses the default microphone |
| `hotkey` | `<Super>z` | Super+C is Pardus's calculator key, so Z it is |
| `max_steps` | `30` | safety limit per request |

The API key is read from `OPENAI_API_KEY`, or `~/.config/pardus-clicky/openai.key`.

## Privacy

During a request Clicky sends to OpenAI: the voice clip, screenshots of the
screen, and the titles of open windows. Requests use `store: false`, so OpenAI
does not keep the conversation. Nothing is sent while Clicky is idle, and the
microphone is only open while it is listening.

## Commands

```
pardus-clicky                 start (lives in the panel)
pardus-clicky listen          start or stop listening (what Super+Z runs)
pardus-clicky ask "TEXT"      run a typed request
pardus-clicky stop            stop the current task
pardus-clicky doctor          check this computer
```

Log: `~/.cache/pardus-clicky/clicky.log`.
