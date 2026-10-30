"""Navigation, steering, unstuck recovery, jumping, and interaction handling."""

import logging
import math
from typing import Protocol

from autobonk.commands import Command, Press
from autobonk.game import (
    ALTAR_PROGRESS_PX,
    DIRECTION_KEYS,
    INTERACT_KEY,
    INTERACT_RETRY_S,
    INTERACT_WAIT_S,
    JUMP_KEY,
    MAP_KEY,
    PORTAL_PROMPTS,
    ZONE_PROGRESS,
)
from autobonk.perception.dom import Observation
from autobonk.policy.zone import distance

log = logging.getLogger(__name__)


def direction(bearing: float) -> frozenset[str]:
    """WASD for a minimap bearing (degrees clockwise from minimap-up), to nearest 45 degrees."""
    return frozenset(DIRECTION_KEYS[round((90 - bearing) / 45) % 8])


class Uniform(Protocol):
    def uniform(self, a: float, b: float) -> float: ...


class JumpScheduler:
    def __init__(self, rng: Uniform, interval: tuple[float, float] = (0.8, 1.4)):
        self.rng = rng
        self.interval = interval
        self.next_jump: float | None = None

    def reset(self) -> None:
        self.next_jump = None

    def tick(self, now: float) -> list[Command]:
        if self.next_jump is None:
            self.next_jump = now + self.rng.uniform(*self.interval)
            return []
        if now < self.next_jump:
            return []
        self.next_jump = now + self.rng.uniform(*self.interval)
        return [Press(JUMP_KEY)]


class Unsticker:
    def __init__(self, stuck_s: float = 2.5, sidestep_s: float = 0.6):
        self.stuck_s = stuck_s
        self.sidestep_s = sidestep_s
        self._progress: tuple[object, float] | None = None
        self._sidestep: tuple[frozenset[str], float] | None = None
        self._sidestep_left = True

    def reset(self) -> None:
        self._progress = None
        self._sidestep = None

    def unstick(
        self,
        keys: frozenset[str],
        bearing: float | None,
        obs: Observation,
        now: float,
        target_dist: float | None,
    ) -> frozenset[str]:
        if self._sidestep:
            sidestep_keys, until = self._sidestep
            if now < until:
                return sidestep_keys | (keys & {MAP_KEY})
            self._sidestep = None
            self._progress = None

        if not (keys - {MAP_KEY}) or bearing is None:
            self._progress = None
            return keys

        if target_dist is not None:
            mark: object = target_dist
            progressed = lambda last: (last - mark) >= ALTAR_PROGRESS_PX  # noqa: E731
        elif obs.zonemap:
            mark = obs.zonemap.player
            progressed = lambda last: distance(last, mark) >= ZONE_PROGRESS  # noqa: E731
        else:
            return keys

        if self._progress is None or type(self._progress[0]) is not type(mark) or progressed(self._progress[0]):
            self._progress = (mark, now)
            return keys

        if now - self._progress[1] < self.stuck_s:
            return keys

        side = -90 if self._sidestep_left else 90
        self._sidestep_left = not self._sidestep_left
        sidestep = direction(bearing + side)
        log.info("stuck for %g s: sidestepping %s", self.stuck_s, "left" if side < 0 else "right")
        self._sidestep = (sidestep, now + self.sidestep_s)
        return sidestep | (keys & {MAP_KEY})


class ApproachHandler:
    def __init__(self, target_ignore_s: float = 60.0):
        self.target_ignore_s = target_ignore_s
        self.interacted: tuple[str, float, float] | None = None  # (target, started_at, last_pressed_at)

    def reset(self) -> None:
        self.interacted = None

    def interact(
        self,
        name: str,
        now: float,
        *,
        spam_e: bool = True,
        prompt_text: str = "",
        pos: tuple[float, float] | None = None,
        on_timeout_ignore: None | tuple[object, ...] = None,
    ) -> tuple[list[Command], bool]:
        """Interacts with target. Returns (commands, timed_out)."""
        if self.interacted is None or self.interacted[0] != name:
            if not spam_e:
                self.interacted = (name, now, 0.0)
                return [], False
            log.info("at %s: pressing E", name)
            self.interacted = (name, now, now)
            return [Press(INTERACT_KEY)], False

        _, started, last_pressed = self.interacted
        if now - started >= INTERACT_WAIT_S:
            timed_out = name not in PORTAL_PROMPTS
            self.interacted = None
            return [], timed_out

        if spam_e and now - last_pressed >= INTERACT_RETRY_S:
            if last_pressed == 0.0:
                log.info("at %s: pressing E", name)
            self.interacted = (name, started, now)
            return [Press(INTERACT_KEY)], False

        return [], False
