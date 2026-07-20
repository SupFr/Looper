# Product

## Register

product

## Platform

web

*(Desktop Qt app — no native mobile rulebook applies; treat as a windowed product UI.)*

## Users

The owner and their friends: casual Roblox players who farm tower-defense games overnight with recorded macros (TinyTask / Informaal). They receive a single `Looper.exe` over Discord, are not technical, and will not read documentation. They use it while a game is running fullscreen on the same PC, often setting it up once and leaving it unattended for hours.

## Product Purpose

Looper wraps any recorded macro in a closed loop: it watches the screen for the game's end screen, stops playback, clicks back into a match, and replays — making blind recordings RNG-proof. Success: a friend goes from double-clicking the .exe to a running farm in under 5 minutes, without asking the owner for help.

## Positioning

The only macro tool where the recording length never has to match the match length — the end screen is the sync point, not the clock.

## Brand Personality

Friendly, simple, guided. The app should feel like a helpful companion, not a power tool. Setup reads as a short checklist, defaults are pre-filled, and the one thing to do next is always obvious. Calm confidence over technical density.

## Anti-references

- Hacker/cheat-hub aesthetic: no neon green on black, no skulls, no "injector" energy. Friends must never feel they're running sketchy software.
- Raw developer-tool density where a first-run user faces a wall of settings with no guidance.

## Design Principles

- **The next step is always obvious.** At any moment the UI should point at exactly one action: capture a region, pick a macro, press Start.
- **Defaults do the work.** Every field ships pre-filled with the value that works for TinyTask + a Roblox TD game; editing is optional, not required.
- **Glanceable at a distance.** The running state (cycles, current step, playing/watching) must read from across the room — this app runs unattended.
- **Errors explain themselves.** A timeout or missing file says what happened and what to click, in plain words, never a stack trace.

## Accessibility & Inclusion

Basics: readable contrast on the dark theme, clear labels on every control, no flashing or strobing content. No formal WCAG target.
