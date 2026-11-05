"""Tracks run boundaries, run counts, win/lose statistics, and auto-restart policy."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from autobonk.commands import Click, Command, Pause, ReleaseAll, Stop
from autobonk.game import RESTART_BUTTON

if TYPE_CHECKING:
    from autobonk.perception.dom import EndScreen

log = logging.getLogger(__name__)

AutoRestartMode = Literal["always", "win", "lose", "never"]
RESTART_SELECTOR = ".sm-foot button.green"


@dataclass
class RunLifecycle:
    auto_restart: str = "always"
    max_runs: int = 0
    restart_load_s: float = 20.0
    retry_delay_s: float = 1.5
    max_retries: int = 3

    run_count: int = 0
    wins: int = 0
    losses: int = 0
    restarting: bool = False
    _last_click_t: float = 0.0
    _click_attempts: int = 0
    _last_end_screen: EndScreen | None = None

    def reload_config(
        self,
        auto_restart: str | None = None,
        max_runs: int | None = None,
        restart_load_s: float | None = None,
    ) -> None:
        if auto_restart is not None:
            self.auto_restart = auto_restart.lower()
        if max_runs is not None:
            self.max_runs = max_runs
        if restart_load_s is not None:
            self.restart_load_s = restart_load_s

    def should_restart(self, end_screen: EndScreen, can_restart: bool = True) -> bool:
        if not can_restart:
            return False
        mode = self.auto_restart.lower()
        if mode == "never":
            return False
        if mode == "win" and end_screen != "win":
            return False
        if mode == "lose" and end_screen != "lose":
            return False
        return self.max_runs <= 0 or self.run_count < self.max_runs

    def on_end_screen(
        self,
        end_screen: EndScreen,
        can_restart: bool,
        now: float,
    ) -> list[Command]:
        """Handle an end-screen frame: either Stop or Click retry."""
        if not self.restarting:
            self.restarting = True
            self._click_attempts = 0
            self._last_click_t = 0.0
            self._last_end_screen = end_screen
            self.run_count += 1
            if end_screen == "win":
                self.wins += 1
            else:
                self.losses += 1
            log.info(
                "Run %d ended: %s (total: %d wins, %d losses)",
                self.run_count,
                end_screen,
                self.wins,
                self.losses,
            )

        if not self.should_restart(end_screen, can_restart):
            self.restarting = False
            return [ReleaseAll(), Stop(end_screen)]

        # Debounce click attempts
        if now - self._last_click_t < self.retry_delay_s:
            return [ReleaseAll()]

        if self._click_attempts >= self.max_retries:
            self.restarting = False
            log.warning(
                "Restart failed: %s button still present after %d clicks",
                RESTART_BUTTON,
                self._click_attempts,
            )
            return [
                ReleaseAll(),
                Pause(
                    f"Restart failed: '{RESTART_BUTTON}' still present after {self._click_attempts} clicks"
                ),
            ]

        self._click_attempts += 1
        self._last_click_t = now
        log.info(
            "Clicking %s to start a new game (attempt %d/%d)",
            RESTART_BUTTON,
            self._click_attempts,
            self.max_retries,
        )
        return [ReleaseAll(), Click(RESTART_BUTTON, selector=RESTART_SELECTOR)]

    def on_in_game(self, now: float) -> bool:
        """Call when an in-game frame (countdown) appears. Returns True if transitioning from restarting."""
        if self.restarting:
            self.restarting = False
            self._click_attempts = 0
            self._last_click_t = 0.0
            log.info("New run active (starting run %d)", self.run_count + 1)
            return True
        return False

    def unknown_screen_timeout(self, default_timeout_s: float) -> float:
        """Return loading timeout grace period if in restarting state, else default."""
        return self.restart_load_s if self.restarting else default_timeout_s
