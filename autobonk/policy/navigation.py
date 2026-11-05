"""Navigation, steering, unstuck recovery, jumping, and interaction handling."""

import logging
import math
from typing import Protocol

from autobonk.commands import Command, Press
from autobonk.game import (
    ALTAR,
    ALTAR_PROGRESS_PX,
    BOSS,
    DIRECTION_KEYS,
    INTERACT_KEY,
    INTERACT_RETRY_S,
    INTERACT_WAIT_S,
    JUMP_KEY,
    MAP_KEY,
    PORTAL,
    SANCTUARY,
    SANCTUARY_PROMPTS,
    ZONE_PROGRESS,
    is_boss_prompt,
    is_portal_prompt,
)
from autobonk.perception.dom import Observation
from autobonk.policy.zone import distance

log = logging.getLogger(__name__)


def direction(bearing: float) -> frozenset[str]:
    """WASD for a minimap bearing (degrees clockwise from minimap-up), to nearest 45 degrees."""
    return frozenset(DIRECTION_KEYS[round((90 - bearing) / 45) % 8])


def orbit_bearing(
    target_x: float,
    target_y: float,
    orbit_radius: float = 6.0,
    clockwise: bool = True,
) -> float:
    """Calculates bearing (degrees clockwise from minimap-up) to orbit around (target_x, target_y).

    Includes proportional radial correction to keep distance near orbit_radius:
    - If too far outward, steers inward towards target
    - If too close inward, steers outward away from target
    - Otherwise, steers along the tangent
    """
    dist = math.hypot(target_x, target_y)
    bearing_to_target = math.degrees(math.atan2(target_x, -target_y))
    sign = -1.0 if clockwise else 1.0

    if dist > orbit_radius + 2.0:
        offset = 55.0  # Steer inward towards target
    elif dist < max(2.0, orbit_radius - 2.0):
        offset = 125.0  # Steer outward away from target
    else:
        offset = 90.0  # Pure tangent

    return (bearing_to_target + sign * offset) % 360.0


def time_orbit_bearing(
    elapsed_s: float,
    period_s: float = 3.6,
    initial_bearing: float = 0.0,
    clockwise: bool = True,
) -> float:
    """Calculates smoothly rotating bearing to trace a circular trajectory in open arena."""
    sign = 1.0 if clockwise else -1.0
    return (initial_bearing + sign * (360.0 * (elapsed_s / period_s))) % 360.0


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

        if obs.zonemap:
            player_pos = obs.zonemap.player
            mark: object = player_pos
            progressed = lambda last: isinstance(last, tuple) and distance(last, player_pos) >= ZONE_PROGRESS  # noqa: E731
        elif target_dist is not None:
            mark = target_dist
            progressed = lambda last: (last - mark) >= ALTAR_PROGRESS_PX  # noqa: E731
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

    def stuck_duration(self, now: float) -> float:
        if self._progress is not None:
            return max(0.0, now - self._progress[1])
        return 0.0


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
        at_target: bool = True,
        is_sanctuary: bool = False,
    ) -> tuple[list[Command], bool]:
        """Interacts with target. Returns (commands, timed_out)."""
        if self.interacted is None or self.interacted[0] != name:
            if not spam_e:
                # At the target but E not allowed yet: start the timer so it still times out.
                # Short of the target, record nothing: an approach in progress must keep the
                # unsticker working (it stands down while an interaction is recorded).
                if at_target:
                    self.interacted = (name, now, 0.0)
                return [], False
            log.info("at %s: pressing E", name)
            self.interacted = (name, now if at_target else 0.0, now)
            return [Press(INTERACT_KEY)], False

        _, started, last_pressed = self.interacted
        if started == 0.0 and at_target:
            started = now

        # Boss summons and portals can take longer than INTERACT_WAIT_S to react; never
        # give up on them. Only the target's own name decides this (it is the prompt text
        # when the bot walks up to a bare prompt): a boss or portal prompt that happens to be
        # on screen must not shield an unrelated target.
        is_boss_or_portal = (
            name in (BOSS, PORTAL, SANCTUARY)
            or is_portal_prompt(name)
            or is_boss_prompt(name)
            or (name == ALTAR and (is_sanctuary or any(k in prompt_text for k in SANCTUARY_PROMPTS)))
        )
        if started > 0.0 and (now - started >= INTERACT_WAIT_S):
            timed_out = not is_boss_or_portal
            if timed_out:
                self.interacted = None
                return [], timed_out
            started = now

        if spam_e and now - last_pressed >= INTERACT_RETRY_S:
            if last_pressed == 0.0:
                log.info("at %s: pressing E", name)
            self.interacted = (name, started, now)
            return [Press(INTERACT_KEY)], False

        self.interacted = (name, started, last_pressed)
        return [], False
