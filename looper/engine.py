"""The supervisor loop.

State machine per cycle:

    PLAYBACK RUNNING
        v  step 1 image appears (end screen)
    stop playback
        v  walk remaining steps (click Retry, menus, ...)
    wait pre-playback delay (map load)
        v
    start playback  ->  cycle++  ->  back to top

Runs on its own QThread; talks to the UI only through signals.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from . import capture, config, matcher, player, webhook


class LoopEngine(QThread):
    sig_log = Signal(str)
    sig_state = Signal(str)          # human-readable current state
    sig_cycle = Signal(int)          # completed cycle count
    sig_step = Signal(int)           # index of step being watched, -1 = none
    sig_stopped = Signal(str)        # reason ("" = user stop)

    def __init__(self, profile: config.Profile, hook: webhook.Webhook) -> None:
        super().__init__()
        self.p = profile
        self.hook = hook
        self._abort = False
        self._cycles = 0
        self._cache = matcher.TemplateCache()

    # -- control ---------------------------------------------------------
    def stop(self) -> None:
        self._abort = True

    # -- helpers ---------------------------------------------------------
    def _log(self, msg: str) -> None:
        self.sig_log.emit(msg)

    def _sleep(self, secs: float) -> bool:
        """Interruptible sleep. Returns False if aborted."""
        end = time.monotonic() + secs
        while time.monotonic() < end:
            if self._abort:
                return False
            time.sleep(min(0.05, max(0.0, end - time.monotonic())))
        return not self._abort

    def _watch(self, step: config.Step, idx: int) -> str:
        """Poll one step's region until match/timeout/abort.

        Returns 'match' | 'timeout' | 'abort'.
        """
        tpl = self._cache.get(step.template, self.p.grayscale)
        if tpl is None:
            self._log(f"[{step.name}] template missing: {step.template}")
            return "timeout"

        self.sig_step.emit(idx)
        region = step.region_dict
        origin = (region["left"], region["top"])
        deadline = (time.monotonic() + step.timeout) if step.timeout > 0 else None

        while not self._abort:
            frame = capture.grab(region)
            res = matcher.find(frame, tpl, step.threshold, origin, self.p.grayscale)
            if res.found:
                self._log(f"[{step.name}] matched ({res.confidence:.2f})")
                if step.click and res.center:
                    x = res.center[0] + step.click_offset[0]
                    y = res.center[1] + step.click_offset[1]
                    player.click(x, y)
                    self._log(f"[{step.name}] clicked ({x}, {y})")
                if not self._sleep(step.post_delay):
                    return "abort"
                return "match"
            if deadline and time.monotonic() > deadline:
                return "timeout"
            if not self._sleep(self.p.poll_interval):
                return "abort"
        return "abort"

    # -- main ------------------------------------------------------------
    def run(self) -> None:
        p = self.p
        steps = [s for s in p.steps if s.enabled and s.template and s.has_region]
        if not steps:
            self.sig_stopped.emit("Nothing to watch for yet - capture the end "
                                  "screen first (step 1 in the setup guide).")
            return

        mp = player.MacroPlayer(p, self._log)
        self.hook.mark_start()
        if p.webhook_on_start:
            self.hook.send("Farm started", f"Profile: **{p.name}**",
                           webhook.COLOR_START)
        reason = ""
        try:
            self.sig_state.emit("Getting ready")
            mp.prepare()

            # First playback: user starts the loop sitting inside a match, or
            # right where the macro expects to begin.
            if not self._sleep(p.pre_playback_delay):
                return
            self.sig_state.emit("Playing your macro")
            mp.start_playback()

            while not self._abort:
                # -- wait for the end screen (step 1) -----------------
                self.sig_state.emit(f"Watching for: {steps[0].name}")
                outcome = self._watch_first(steps[0], mp)
                if outcome == "abort":
                    break
                if outcome == "stop":
                    reason = (f"'{steps[0].name}' never showed up on screen, "
                              "so the loop stopped (that's what you chose for "
                              "this step). If the game looks different now, "
                              "re-capture the image.")
                    break

                # -- remaining navigation steps -----------------------
                restart = False
                for i, step in enumerate(steps[1:], start=1):
                    self.sig_state.emit(f"Watching for: {step.name}")
                    out = self._watch(step, i)
                    if out == "abort":
                        break
                    if out == "timeout":
                        self._log(f"[{step.name}] timeout -> {step.on_timeout}")
                        if step.on_timeout == config.ON_TIMEOUT_SKIP:
                            continue
                        if step.on_timeout == config.ON_TIMEOUT_STOP:
                            reason = (f"'{step.name}' never showed up on "
                                      "screen, so the loop stopped. If the "
                                      "game looks different now, re-capture "
                                      "the image for that step.")
                            self._abort = True
                            break
                        restart = True   # ON_TIMEOUT_RESTART
                        break
                if self._abort:
                    break

                self._cycles += 1
                self.sig_cycle.emit(self._cycles)
                if restart:
                    self._log("Starting over from step 1.")

                if (p.webhook_on_cycle and p.webhook_every > 0
                        and self._cycles % p.webhook_every == 0):
                    self.hook.send("Match finished", "", webhook.COLOR_CYCLE,
                                   {"Profile": p.name, "Matches": self._cycles})

                # -- relaunch the macro -------------------------------
                self.sig_state.emit("Waiting for the match to load")
                if not self._sleep(p.pre_playback_delay):
                    break
                self.sig_state.emit("Playing your macro")
                mp.start_playback()

        except FileNotFoundError as e:
            reason = str(e)
        except Exception as e:  # noqa: BLE001 - surface anything to the UI
            reason = f"{type(e).__name__}: {e}"
        finally:
            self.sig_step.emit(-1)
            mp.shutdown()
            if reason and p.webhook_on_error:
                self.hook.send("Farm stopped - needs your attention", reason,
                               webhook.COLOR_ERROR,
                               {"Profile": p.name, "Matches": self._cycles})
            elif p.webhook_on_stop:
                self.hook.send("Farm stopped", "", webhook.COLOR_STOP,
                               {"Profile": p.name, "Matches": self._cycles})
            self.sig_stopped.emit(reason)

    def _watch_first(self, step: config.Step, mp: player.MacroPlayer) -> str:
        """Step 1 = end-screen detector. On match, kill playback first, then
        (optionally) click -- clicking mid-playback would fight the macro.

        Returns 'ok' | 'stop' | 'abort'.
        """
        tpl = self._cache.get(step.template, self.p.grayscale)
        if tpl is None:
            return "stop"

        self.sig_step.emit(0)
        region = step.region_dict
        origin = (region["left"], region["top"])
        deadline = (time.monotonic() + step.timeout) if step.timeout > 0 else None

        while not self._abort:
            frame = capture.grab(region)
            res = matcher.find(frame, tpl, step.threshold, origin, self.p.grayscale)
            if res.found:
                self._log(f"[{step.name}] end screen ({res.confidence:.2f})")
                if self.p.stop_before_steps:
                    mp.stop_playback()
                    if not self._sleep(0.3):
                        return "abort"
                if step.click and res.center:
                    x = res.center[0] + step.click_offset[0]
                    y = res.center[1] + step.click_offset[1]
                    player.click(x, y)
                    self._log(f"[{step.name}] clicked ({x}, {y})")
                if not self._sleep(step.post_delay):
                    return "abort"
                return "ok"
            if deadline and time.monotonic() > deadline:
                self._log(f"[{step.name}] timeout -> {step.on_timeout}")
                if step.on_timeout == config.ON_TIMEOUT_STOP:
                    return "stop"
                # skip/restart both mean: end screen never came, macro is done
                # or stuck -- stop playback and try the cycle again.
                mp.stop_playback()
                deadline = ((time.monotonic() + step.timeout)
                            if step.timeout > 0 else None)
                continue
            if not self._sleep(self.p.poll_interval):
                return "abort"
        return "abort"
