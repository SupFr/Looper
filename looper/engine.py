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
    sig_result = Signal(int, int)    # running (wins, losses) tally
    sig_stopped = Signal(str)        # reason ("" = user stop)

    def __init__(self, profile: config.Profile, hook: webhook.Webhook) -> None:
        super().__init__()
        self.p = profile
        self.hook = hook
        self._abort = False
        self._cycles = 0
        self._wins = 0
        self._losses = 0
        self._cache = matcher.TemplateCache()

    def _locate(self, tpl_path: str, region: list[int], base: list[int],
                threshold: float) -> matcher.MatchResult:
        """Find a template on screen, correcting for a resolution change since
        capture. If the current screen is a different size than the one the
        template was captured on, the search area and the template are scaled
        to match, with a small sweep to absorb non-linear UI scaling."""
        tpl = self._cache.get(tpl_path, self.p.grayscale)
        if tpl is None or region[2] <= 0:
            return matcher.MatchResult(False, 0.0, None)

        x, y, w, h = region
        desk = capture.virtual_desktop()
        cur_w, cur_h = desk["width"], desk["height"]
        scales = (1.0,)

        if base and base[0] and base[1] and (base[0] != cur_w or base[1] != cur_h):
            sx, sy = cur_w / base[0], cur_h / base[1]
            s = (sx + sy) / 2.0
            # element moved to a scaled position and grew/shrank; grab a
            # padded area around where it should now be so we can't miss it
            cx, cy = (x + w / 2) * sx, (y + h / 2) * sy
            gw, gh = w * sx * 2, h * sy * 2
            gx, gy = cx - gw / 2, cy - gh / 2
            left = max(desk["left"], int(gx))
            top = max(desk["top"], int(gy))
            grab = {
                "left": left, "top": top,
                "width": min(int(gw), desk["left"] + cur_w - left),
                "height": min(int(gh), desk["top"] + cur_h - top),
            }
            scales = (s * 0.9, s, s * 1.1)
        else:
            grab = {"left": x, "top": y, "width": w, "height": h}

        if grab["width"] <= 0 or grab["height"] <= 0:
            return matcher.MatchResult(False, 0.0, None)
        frame = capture.grab(grab)
        return matcher.find(frame, tpl, threshold,
                            (grab["left"], grab["top"]), self.p.grayscale, scales)

    def _check_result(self) -> str:
        """On the end screen, decide win / loss / unknown from templates."""
        p = self.p
        win_r = self._locate(p.win_template, p.win_region, p.win_base,
                             p.result_threshold)
        loss_r = self._locate(p.loss_template, p.loss_region, p.loss_base,
                              p.result_threshold)
        win = win_r.confidence if win_r.found else -1.0
        loss = loss_r.confidence if loss_r.found else -1.0
        if win < 0 and loss < 0:
            return "unknown"
        return "win" if win >= loss else "loss"

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
        if self._cache.get(step.template, self.p.grayscale) is None:
            self._log(f"[{step.name}] template missing: {step.template}")
            return "timeout"

        self.sig_step.emit(idx)
        deadline = (time.monotonic() + step.timeout) if step.timeout > 0 else None

        while not self._abort:
            res = self._locate(step.template, step.region, step.base,
                               step.threshold)
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

    # -- preflight -------------------------------------------------------
    def _preflight(self, steps: list[config.Step]) -> str:
        """Everything that can fail should fail HERE, with a named fix,
        not twenty minutes into an unattended farm. Returns '' when OK."""
        from pathlib import Path

        if not steps:
            return ("Nothing to watch for yet - capture the end screen "
                    "first (step 1 in the setup guide).")

        desk = capture.virtual_desktop()
        for s in steps:
            if not Path(s.template).is_file():
                return (f"The captured image for '{s.name}' is missing from "
                        "this PC. Select the step and capture it again.")
            if self._cache.get(s.template, self.p.grayscale) is None:
                return (f"The captured image for '{s.name}' can't be read - "
                        "it may be corrupted. Select the step and capture "
                        "it again.")
            # A resolution change is fine now - _locate rescales the region -
            # as long as we know what resolution it was captured at. Only
            # fail when we can't rescale (legacy capture, no stored base) and
            # the region falls outside the current screen.
            resized = s.base and s.base[0] and s.base[1] and (
                s.base[0] != desk["width"] or s.base[1] != desk["height"])
            if not resized:
                x, y, w, h = s.region
                if (x < desk["left"] or y < desk["top"]
                        or x + w > desk["left"] + desk["width"]
                        or y + h > desk["top"] + desk["height"]):
                    return (f"The screen area for '{s.name}' is outside your "
                            "current display. Your screen setup (resolution or "
                            "monitors) changed since you captured it - select "
                            "the step and capture it again.")

        if self.p.mode == config.MODE_PLAYER:
            for label, spec in (("play", self.p.play_hotkey),
                                ("stop", self.p.stop_hotkey)):
                try:
                    player.parse_hotkey(spec)
                except ValueError as e:
                    return (f"The player's {label} hotkey (Playback tab) "
                            f"doesn't work: {e}")
        return ""

    # -- main ------------------------------------------------------------
    def run(self) -> None:
        p = self.p
        steps = [s for s in p.steps if s.enabled and s.template and s.has_region]
        problem = self._preflight(steps)
        if problem:
            self.sig_stopped.emit(problem)
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

                # -- win / loss (end screen is up, Retry not clicked yet) --
                result = self._check_result()
                if result == "win":
                    self._wins += 1
                    self._log("Result: WON")
                elif result == "loss":
                    self._losses += 1
                    self._log("Result: lost")
                if result != "unknown":
                    self.sig_result.emit(self._wins, self._losses)

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
                    fields = {"Profile": p.name, "Matches": self._cycles}
                    title = "Match finished"
                    color = webhook.COLOR_CYCLE
                    if result == "win":
                        title = "Match won ✅"
                        color = webhook.COLOR_START
                    elif result == "loss":
                        title = "Match lost ❌"
                        color = webhook.COLOR_ERROR
                    if self._wins or self._losses:
                        fields["Record"] = f"{self._wins}W / {self._losses}L"
                    self.hook.send(title, "", color, fields)

                # -- relaunch the macro -------------------------------
                self.sig_state.emit("Waiting for the match to load")
                if not self._sleep(p.pre_playback_delay):
                    break
                self.sig_state.emit("Playing your macro")
                mp.start_playback()

        except FileNotFoundError as e:
            reason = str(e)
        except Exception as e:  # noqa: BLE001 - surface anything to the UI
            reason = ("Something unexpected stopped the loop:\n"
                      f"{type(e).__name__}: {e}\n\n"
                      "Try starting it again. If it keeps happening, send "
                      "this message to whoever gave you Looper.")
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
        if self._cache.get(step.template, self.p.grayscale) is None:
            return "stop"

        self.sig_step.emit(0)
        deadline = (time.monotonic() + step.timeout) if step.timeout > 0 else None

        while not self._abort:
            res = self._locate(step.template, step.region, step.base,
                               step.threshold)
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
