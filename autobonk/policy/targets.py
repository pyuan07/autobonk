"""Target weighing, scoring, candidate filtering, and temporary target tracking."""

import logging
import math
from typing import Mapping, Sequence, TypeVar

from autobonk.game import (
    ALTAR,
    APPROACH_PX_PER_S,
    BOSS,
    DEFAULT_TARGETS,
    GIFT_BALL,
    PORTAL,
    SUPER_BALL,
    SUPER_BALLS,
    TEMP_TARGET_PX,
    BossRule,
    Weight,
)
from autobonk.perception.dom import Observation
from autobonk.policy.zone import BossPhase

log = logging.getLogger(__name__)
T = TypeVar("T", bound=tuple[float, float])


class TargetSelector:
    def __init__(
        self,
        targets: Mapping[str, Weight] | None = None,
        boss: BossRule | None = None,
        distance_factor: float = 0.2,
    ):
        raw_weights = DEFAULT_TARGETS if targets is None else targets
        self._weights: dict[str, tuple[float, float]] = {
            name: (w if isinstance(w, tuple) else (w, w))
            for name, w in raw_weights.items()
        }
        # Filter out <= 0 weights and boss from static weights
        self._weights = {name: w for name, w in self._weights.items() if max(w) > 0 and name != BOSS}

        # Normalize super ball and gift ball aliases
        if SUPER_BALL in self._weights and GIFT_BALL not in self._weights:
            self._weights[GIFT_BALL] = self._weights[SUPER_BALL]
        elif GIFT_BALL in self._weights and SUPER_BALL not in self._weights:
            self._weights[SUPER_BALL] = self._weights[GIFT_BALL]

        self.boss = boss
        self.distance_factor = distance_factor

        icon_names = set(name for name in self._weights if name != ALTAR)
        if boss:
            icon_names.add(BOSS)
        icon_names.add(SUPER_BALL)
        icon_names.add(GIFT_BALL)
        self.icons: tuple[str, ...] = tuple(icon_names)

        self.active_weights: dict[str, float] = {}
        self.current_target: str | None = None
        self._ignored: dict[str, float] = {}  # target name -> until timestamp
        self._ignored_instances: list[tuple[str, tuple[float, float], float]] = []  # (name, (zx, zy), until)
        self._temp_target: tuple[str, tuple[float, float], float] | None = None  # (name, (x, y), last_t)

    def reset_zone(self) -> None:
        self._ignored_instances.clear()
        self._temp_target = None
        self.current_target = None

    def weigh(
        self,
        obs: Observation,
        now: float,
        zone_seconds: int | None,
        boss_phase: BossPhase,
    ) -> dict[str, float]:
        left = obs.seconds_left
        progress = 1.0 - left / zone_seconds if left is not None and zone_seconds else 0.0
        weights = {name: start + (end - start) * progress for name, (start, end) in self._weights.items()}

        if boss_phase == BossPhase.FIGHTING:
            weights.pop(ALTAR, None)
        elif boss_phase == BossPhase.BEATEN:
            if self.has_nearby_super_balls(obs, now):
                weights[SUPER_BALL] = math.inf
                weights[GIFT_BALL] = math.inf
            elif obs.portal is not None:
                weights[PORTAL] = math.inf
        elif self.boss and boss_phase == BossPhase.WAITING and obs.zone_index:
            if self.boss.ready(obs.zone_index, obs.level, left):
                weights[BOSS] = math.inf

        self.active_weights = {name: w for name, w in weights.items() if w > 0}
        return self.active_weights

    def has_nearby_super_balls(self, obs: Observation, now: float) -> bool:
        if self.is_skipped(SUPER_BALL, now) or self.is_skipped(GIFT_BALL, now):
            return False
        if obs.has_unopened_super_balls:
            return True
        return any(
            name in SUPER_BALLS and not self.is_skipped(name, now)
            for name, _ in obs.targets
        )

    def is_skipped(self, name: str, now: float, pos: tuple[float, float] | None = None) -> bool:
        if now < self._ignored.get(name, 0.0):
            return True
        if pos is not None:
            for ign_name, (ix, iy), until in self._ignored_instances:
                if now < until and (ign_name == name or (name in SUPER_BALLS and ign_name in SUPER_BALLS)):
                    if math.hypot(pos[0] - ix, pos[1] - iy) < 0.08:
                        return True
        return False

    def ignore_target(self, name: str, until: float, pos: tuple[float, float] | None = None) -> None:
        if pos is not None:
            self._ignored_instances.append((name, pos, until))
            if name in SUPER_BALLS:
                self._ignored_instances.append((SUPER_BALL, pos, until))
                self._ignored_instances.append((GIFT_BALL, pos, until))
        else:
            self._ignored[name] = until
            if name in SUPER_BALLS:
                self._ignored[SUPER_BALL] = until
                self._ignored[GIFT_BALL] = until

    def candidates(
        self,
        found: Sequence[tuple[str, T]],
        now: float,
        is_zonemap: bool = False,
    ) -> list[tuple[str, T]]:
        result: list[tuple[str, T]] = []
        for name, where in found:
            if name not in self.active_weights:
                continue
            target_pos = (float(where[0]), float(where[1])) if is_zonemap else None
            if not self.is_skipped(name, now, target_pos):
                result.append((name, where))
        return result

    def best(
        self,
        candidates: Sequence[tuple[str, T]],
        origin: tuple[float, float],
        scale: float = 200.0,
    ) -> tuple[str, T]:
        current = self.current_target
        return max(
            candidates,
            key=lambda c: self.score_candidate(c[0], c[1], origin, scale, is_current=(c[0] == current)),
        )

    def score_candidate(
        self,
        name: str,
        pos: tuple[float, float],
        origin: tuple[float, float],
        scale: float,
        is_current: bool = False,
    ) -> tuple[float, float]:
        dist = math.hypot(pos[0] - origin[0], pos[1] - origin[1])
        weight = self.active_weights.get(name, 0.0)
        if weight <= 0:
            return (0.0, -dist)
        if math.isinf(weight):
            return (math.inf, -dist)
        norm_dist = min(dist / scale, 1.0) if scale > 0 else 0.0
        score = weight * (1.0 + self.distance_factor * (1.0 - norm_dist))
        # 15% hysteresis bonus to the currently chosen target to prevent flip-flopping
        if is_current:
            score *= 1.15
        return (score, -dist)

    def with_temp_target(
        self,
        candidates: Sequence[tuple[str, tuple[int, int]]],
        now: float,
        is_moving: bool,
    ) -> list[tuple[str, tuple[int, int]]]:
        """Keep a close target's temporary (x, y) when player arrow covers its icon on minimap."""
        c_list = list(candidates)
        if self._temp_target is None:
            return c_list
        t_name, (tx, ty), last_t = self._temp_target
        if t_name not in self.active_weights or self.is_skipped(t_name, now):
            self._temp_target = None
            return c_list
        if any(name == t_name and math.hypot(px, py) <= TEMP_TARGET_PX for name, (px, py) in c_list):
            return c_list
        dt = max(0.0, now - last_t)
        dist = math.hypot(tx, ty)
        if is_moving and dist > 0:
            new_dist = max(0.0, dist - APPROACH_PX_PER_S * dt)
            scale = new_dist / dist
            tx, ty = tx * scale, ty * scale
        self._temp_target = (t_name, (tx, ty), now)
        return c_list + [(t_name, (int(round(tx)), int(round(ty))))]

    def update_temp_target(
        self,
        target_name: str,
        distance: float,
        pos: tuple[float, float],
        visible_candidates: Sequence[tuple[str, tuple[int, int]]],
        now: float,
    ) -> None:
        if target_name != ALTAR and distance <= TEMP_TARGET_PX:
            if any(n == target_name and math.hypot(px, py) <= TEMP_TARGET_PX for n, (px, py) in visible_candidates):
                self._temp_target = (target_name, pos, now)
            elif self._temp_target is None or self._temp_target[0] != target_name:
                self._temp_target = (target_name, pos, now)
        elif target_name == ALTAR or distance > TEMP_TARGET_PX:
            self._temp_target = None

    def clear_temp_target(self) -> None:
        self._temp_target = None
