# Looper v1.6

Vision-driven macro loop supervisor. Wraps any recorded macro (TinyTask,
Informaal, a compiled .exe) in a closed loop: it watches the screen for the
end screen, stops the playback, clicks through the menus back into a match,
and fires the macro again. RNG-proof — the recording length never has to
match the match length.

## Run

```
pip install -r requirements.txt
python main.py
```

## Setup flow

First run shows only the 3-step guide and a big status block. Click
**More options** in the header for the full editor (steps, tabs, log).

1. **Detection steps** (left panel, under More options)
   - Step 1 is the end-screen detector. Select it, hit **Select region on
     screen**, drag a box around something that ONLY appears on the end
     screen (the Retry button is perfect). Enable **Click when detected** if
     that image is the button itself.
   - Add more steps if your game needs extra clicks to get back into a match
     (Continue → lobby Play → map, etc.). Each step waits for its image, then
     optionally clicks it.
2. **Playback tab**
   - *Player app + macro file*: point it at `tinytask.exe` and your `.rec`.
     Looper launches TinyTask with the file and drives it via its play
     hotkey. Hotkey fields are press-to-record: click the field and press
     the actual keys.
   - *Standalone .exe*: your macro is compiled — Looper runs and kills
     the process directly. No hotkeys needed. Most reliable.
   - *Delay before playback* = map load time.
3. **Hotkeys tab** — global start / stop / panic keys (default F9 / F10 / F12),
   rebindable, work while the game is focused.
4. **Webhook tab** — paste a Discord webhook URL, hit Test. You get start /
   stop / error pings and a cycle counter on your phone via the Discord app.

## The loop

```
play macro ──► watch for end screen ──► stop playback ──► click Retry
     ▲                                                        │
     └────── wait map-load delay ◄── run remaining steps ◄────┘
```

- Match runs LONG (RNG): macro finishes early, Looper just keeps
  watching until the end screen actually shows up. No desync.
- Match runs SHORT: end screen appears mid-playback, playback is killed
  instantly, loop restarts clean.
- Every step has a timeout with a chosen fallback (restart cycle / skip
  step / stop + notify), so a missed popup can't hang the farm forever.

## Reference photos & win/loss

- **Your setup for this recording** (shown on the main window): capture one
  photo of your team and one of the act info. They're pinned to the profile
  so next time you open it you know exactly what to equip. Click a photo to
  enlarge it.
- **Win / Loss tab**: optionally capture what a "Victory" and "Defeat" look
  like (a small, always-the-same crop of each end screen). Looper then keeps
  a W/L record on the status block and reports the result in each Discord
  message.

## Notes

- Templates, photos, and profiles live in `%APPDATA%\Looper\`.
- Multiple profiles = multiple games; switch from the dropdown.
- Looper records the screen resolution when you capture, and auto-scales
  the search area and image if you later play at a different resolution
  (e.g. captured at 1920×1080, running at 2560×1440). Same-aspect changes
  (16:9) are handled; a very different aspect ratio may still need a
  re-capture.
