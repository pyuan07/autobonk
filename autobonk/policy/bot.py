"""The bot: orchestrates perception, popup choices, navigation, and targets."""

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from autobonk.commands import Command, Hold, Pause, Press, ReleaseAll, Stop
from autobonk.game import (
    ALTAR,
    ALTAR_ARRIVED_PX,
    BOSS,
    BOSS_PROMPTS,
    CLOSE_TIMEOUT_PX,
    DEFAULT_TARGETS,
    INTERACT_KEY,
    INTERACT_PX,
    MAP_KEY,
    PORTAL,
    PORTAL_PROMPTS,
    SUPER_BALL,
    SUPER_BALLS,
    TARGET_ARRIVED_PX,
    BossRule,
    Weight,
)
from autobonk.runtime.frames import Frame
from autobonk.perception.dom import Observation, perceive
from autobonk.perception.matching import Point
from autobonk.perception.zonemap import Position
from autobonk.policy.cards import CardPrefs
from autobonk.policy.navigation import (
    ApproachHandler,
    JumpScheduler,
    Uniform,
    Unsticker,
    direction,
)
from autobonk.policy.popups import PopupPolicy
from autobonk.policy.targets import TargetSelector
from autobonk.policy.zone import BossPhase, ZoneTracker

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Movement:
    jump_interval_s: tuple[float, float] = (0.8, 1.4)
    altar_charge_cap_s: float = 45.0
    target_ignore_s: float = 60.0
    stuck_s: float = 2.5
    sidestep_s: float = 0.6
    distance_factor: float = 0.2
    rng: Uniform = field(default_factory=random.Random)


@dataclass
class BotStatus:
    zone: str = ""
    target: str = ""
    charging: bool = False
    held: frozenset[str] = field(default_factory=frozenset)
    status_text: str = ""


class Bot:
    def __init__(
        self,
        unknown_screen_pause_s: float = 5.0,
        cards: CardPrefs = CardPrefs(),
        movement: Movement | None = None,
        targets: Mapping[str, Weight] | None = None,
        boss: BossRule | None = None,
        banish_threshold: float | None = -5.0,
        reroll_threshold: float | None = 0.0,
        skip_threshold: float | None = 0.0,
    ):
        self._unknown_screen_pause_s = unknown_screen_pause_s
        self._movement = movement or Movement()

        # Modular components
        self._popups = PopupPolicy(
            cards=cards,
            banish_threshold=banish_threshold,
            reroll_threshold=reroll_threshold,
            skip_threshold=skip_threshold,
        )
        self._target_selector = TargetSelector(
            targets=targets,
            boss=boss,
            distance_factor=self._movement.distance_factor,
        )
        self._zone_tracker = ZoneTracker()
        self._jumper = JumpScheduler(self._movement.rng, self._movement.jump_interval_s)
        self._unsticker = Unsticker(self._movement.stuck_s, self._movement.sidestep_s)
        self._approach = ApproachHandler(self._movement.target_ignore_s)

        # State tracking
        self._held: frozenset[str] = frozenset()
        self._bearing: float | None = None
        self._charging_since: float | None = None
        self._unrecognised_since: float | None = None
        self._last_state: str | None = None

    @property
    def status(self) -> BotStatus:
        return BotStatus(
            zone=self._zone_tracker.zone or "",
            target=self._target_selector.current_target or "",
            charging=self._charging_since is not None,
            held=self._held,
            status_text=self._last_state or "running",
        )

    # Backward-compatible property facades for tests
    @property
    def _target(self) -> str | None:
        return self._target_selector.current_target

    @_target.setter
    def _target(self, val: str | None) -> None:
        self._target_selector.current_target = val

    @property
    def _zone(self) -> str | None:
        return self._zone_tracker.zone

    @_zone.setter
    def _zone(self, val: str | None) -> None:
        self._zone_tracker.zone = val

    @property
    def _now_weights(self) -> dict[str, float]:
        return self._target_selector.active_weights

    @_now_weights.setter
    def _now_weights(self, val: dict[str, float]) -> None:
        self._target_selector.active_weights = val

    @property
    def _boss_beaten(self) -> bool:
        return self._zone_tracker.boss_phase == BossPhase.BEATEN

    @_boss_beaten.setter
    def _boss_beaten(self, val: bool) -> None:
        self._zone_tracker.boss_phase = BossPhase.BEATEN if val else BossPhase.WAITING

    @property
    def _boss_fight(self) -> bool:
        return self._zone_tracker.boss_phase == BossPhase.FIGHTING

    @_boss_fight.setter
    def _boss_fight(self, val: bool) -> None:
        self._zone_tracker.boss_phase = BossPhase.FIGHTING if val else BossPhase.WAITING

    @property
    def _icons(self) -> tuple[str, ...]:
        return self._target_selector.icons

    @property
    def _heading(self) -> float | None:
        return self._zone_tracker.heading

    @_heading.setter
    def _heading(self, val: float | None) -> None:
        self._zone_tracker.heading = val

    def step(self, frame: Frame) -> list[Command]:
        obs = perceive(frame, self._target_selector.icons)
        self._log_state_change(obs)

        if obs.end_screen:
            return self._release([ReleaseAll(), Stop(obs.end_screen)])

        if obs.team_view:
            self._unrecognised_since = None
            self._jumper.reset()
            return self._release(self._popups.close_team_view(frame.timestamp))

        if obs.popup:
            self._unrecognised_since = None
            self._jumper.reset()
            self._approach.reset()
            self._target_selector.clear_temp_target()
            return self._release(self._popups.answer(obs.popup, frame.timestamp))

        if obs.countdown:
            self._unrecognised_since = None
            move_cmds = self._move(obs, frame.timestamp)
            if Press(INTERACT_KEY) in move_cmds or (self._approach.interacted is not None and not self._held):
                return move_cmds
            return move_cmds + self._jumper.tick(frame.timestamp)

        if obs.recognised:
            self._unrecognised_since = None
            return []

        if self._unrecognised_since is None:
            self._unrecognised_since = frame.timestamp
        if frame.timestamp - self._unrecognised_since >= self._unknown_screen_pause_s:
            self._unrecognised_since = None
            return self._release([ReleaseAll(), Pause(f"screen unrecognised for {self._unknown_screen_pause_s:g} s")])
        return []

    def _release(self, commands: list[Command]) -> list[Command]:
        if ReleaseAll() in commands:
            self._held = frozenset()
        return commands

    def _move(self, obs: Observation, now: float) -> list[Command]:
        # 1. Update zone and weights
        if self._zone_tracker.update(obs.zone, obs.seconds_left):
            self._target_selector.reset_zone()

        # Boss defeat detection
        if (obs.boss_down or (self._zone_tracker.boss_phase == BossPhase.FIGHTING and obs.portal is not None)) and self._zone_tracker.boss_phase != BossPhase.BEATEN:
            log.info("area boss beaten")
            self._zone_tracker.boss_phase = BossPhase.BEATEN

        self._target_selector.weigh(obs, now, self._zone_tracker.zone_seconds, self._zone_tracker.boss_phase)

        # 2. Check sealed altar
        if obs.sealed_s is not None and not self._target_selector.is_skipped(ALTAR, now):
            log.info("altar sealed for %d s: exploring meanwhile", obs.sealed_s)
            self._target_selector.ignore_target(ALTAR, now + obs.sealed_s)

        # 3. Check charging
        target = self._target_selector.current_target or ALTAR
        if obs.charging and (self._target_selector.current_target is None or self._target_selector.current_target == ALTAR):
            self._approach.reset()
            self._target_selector.clear_temp_target()
            if self._charging_since is None:
                self._charging_since = now
            if now - self._charging_since > self._movement.altar_charge_cap_s and not self._target_selector.is_skipped(target, now):
                log.info("%s still charging after %g s: moving on", target, self._movement.altar_charge_cap_s)
                self._target_selector.ignore_target(target, now + self._movement.target_ignore_s)
        else:
            self._charging_since = None

        # 4. Prompt validity check
        prompt_text = ""
        boss_not_ready = False
        portal_held = False
        prompt_ok = False
        if obs.prompt and (not obs.charging or (self._target_selector.current_target is not None and self._target_selector.current_target != ALTAR)):
            _, prompt_text = obs.prompt
            boss_not_ready = any(k in prompt_text for k in BOSS_PROMPTS) and (
                not self._target_selector.boss
                or self._zone_tracker.boss_phase == BossPhase.BEATEN
                or not (
                    obs.zone_index
                    and self._target_selector.boss.ready(obs.zone_index, obs.level, obs.seconds_left)
                )
            )
            portal_held = any(k in prompt_text for k in PORTAL_PROMPTS) and self._target_selector.has_nearby_super_balls(obs, now)
            prompt_ok = not boss_not_ready and not portal_held and not self._target_selector.is_skipped(prompt_text, now)

        keys: frozenset[str] = frozenset()
        commands: list[Command] = []
        distance_px: float | None = None
        extra_targets: list[tuple[str, tuple[int, int]]] = []
        if self._zone_tracker.boss_phase == BossPhase.BEATEN and obs.portal is not None and not self._target_selector.has_nearby_super_balls(obs, now):
            extra_targets.append((PORTAL, obs.portal))

        # 5. Zonemap navigation branch
        if obs.zonemap:
            zone = obs.zonemap
            self._zone_tracker.mark_visited(zone.player)
            zone_targets = [(ALTAR, p) for p in zone.altars] + list(zone.targets)
            candidates = self._target_selector.candidates(zone_targets, now, is_zonemap=True)
            target_pos: Position | None = None

            if self._zone_tracker.boss_phase == BossPhase.BEATEN and obs.portal is not None and not self._target_selector.has_nearby_super_balls(obs, now):
                self._target_selector.current_target = PORTAL
            elif candidates:
                best_name, target_pos = self._target_selector.best(candidates, zone.player, scale=1.0)
                self._target_selector.current_target = best_name
            else:
                self._target_selector.current_target, target_pos = None, self._zone_tracker.nearest_unvisited(zone.player)

            if target_pos is not None:
                dx, dy = target_pos[0] - zone.player[0], target_pos[1] - zone.player[1]
                self._zone_tracker.heading = math.degrees(math.atan2(dx, -dy))

            matching_minimap: list[Point] = []
            cur_t = self._target_selector.current_target
            if cur_t == ALTAR:
                matching_minimap = list(obs.altars)
            elif cur_t == PORTAL and obs.portal is not None:
                matching_minimap = [obs.portal]
            elif cur_t:
                matching_minimap = [p for name, p in obs.targets if name == cur_t]

            zone_dist = math.hypot(dx, dy) if target_pos is not None else 0.0
            if obs.charging and (cur_t is None or cur_t == ALTAR) and not self._target_selector.is_skipped(ALTAR, now):
                pass
            elif matching_minimap and (target_pos is None or zone_dist < 0.25):
                mx, my = min(matching_minimap, key=lambda p: p[0] ** 2 + p[1] ** 2)
                distance_px = math.hypot(mx, my)
                keys, commands = self._steer_and_interact(
                    cur_t, mx, my, distance_px, prompt_ok, boss_not_ready, portal_held, prompt_text, now, zone.player
                )
            elif prompt_ok:
                commands = self._interact(prompt_text, now, spam_e=True, pos=zone.player)
            else:
                if self._zone_tracker.heading is not None and obs.north is not None:
                    self._bearing = obs.north + self._zone_tracker.heading
                    keys = direction(self._bearing) | {MAP_KEY}
                else:
                    keys = frozenset({MAP_KEY})

        # 6. Minimap navigation branch
        else:
            visible_candidates = self._target_selector.candidates(
                [(ALTAR, p) for p in obs.altars] + list(obs.targets) + extra_targets,
                now,
            )
            is_moving = bool(self._held - {MAP_KEY})
            minimap_candidates = self._target_selector.with_temp_target(visible_candidates, now, is_moving)
            boss_wanted = BOSS in self._target_selector.active_weights and not any(name == BOSS for name, _ in minimap_candidates)

            cur_t = self._target_selector.current_target
            if obs.charging and (cur_t is None or cur_t == ALTAR) and not self._target_selector.is_skipped(ALTAR, now):
                pass
            elif minimap_candidates and not boss_wanted:
                best_name, (x, y) = self._target_selector.best(minimap_candidates, (0, 0), scale=200.0)
                self._target_selector.current_target = best_name
                distance_px = math.hypot(x, y)
                self._target_selector.update_temp_target(best_name, distance_px, (float(x), float(y)), visible_candidates, now)

                keys, commands = self._steer_and_interact(
                    best_name, x, y, distance_px, prompt_ok, boss_not_ready, portal_held, prompt_text, now, None
                )
            elif prompt_ok:
                commands = self._interact(prompt_text, now, spam_e=True)
            else:
                keys = self._explore(obs, now)

        # 7. Unstick recovery
        keys = self._unsticker.unstick(keys, self._bearing, obs, now, distance_px)
        if keys != self._held:
            self._held = keys
            commands = [Hold(keys)] + commands
        return commands

    def _steer_and_interact(
        self,
        target_name: str | None,
        x: float,
        y: float,
        distance_px: float,
        prompt_ok: bool,
        boss_not_ready: bool,
        portal_held: bool,
        prompt_text: str,
        now: float,
        pos: Position | None,
    ) -> tuple[frozenset[str], list[Command]]:
        keys: frozenset[str] = frozenset()
        commands: list[Command] = []
        if target_name == ALTAR:
            if distance_px > ALTAR_ARRIVED_PX:
                self._bearing = math.degrees(math.atan2(x, -y))
                keys = direction(self._bearing)
        else:
            if distance_px > TARGET_ARRIVED_PX and not prompt_ok:
                self._bearing = math.degrees(math.atan2(x, -y))
                keys = direction(self._bearing)
            if (
                distance_px <= CLOSE_TIMEOUT_PX
                or prompt_ok
                or (self._approach.interacted is not None and self._approach.interacted[0] == target_name)
            ):
                can_press_e = (distance_px <= INTERACT_PX or prompt_ok) and not boss_not_ready and not portal_held
                commands = self._interact(target_name or "", now, spam_e=can_press_e, prompt_text=prompt_text, pos=pos)
        return keys, commands

    def _interact(
        self,
        name: str,
        now: float,
        *,
        spam_e: bool = True,
        prompt_text: str = "",
        pos: tuple[float, float] | None = None,
    ) -> list[Command]:
        if not name:
            return []
        if (name == BOSS or "守护者" in name) and (self._approach.interacted is None or self._approach.interacted[0] != name):
            log.info("area boss summoned: it chases us, so keep moving and leave the altars")
            self._zone_tracker.boss_phase = BossPhase.FIGHTING

        commands, timed_out = self._approach.interact(
            name, now, spam_e=spam_e, prompt_text=prompt_text, pos=pos
        )
        if timed_out:
            log.info("%s: E did nothing (not enough money?), skipping for %g s", name, self._movement.target_ignore_s)
            until = now + self._movement.target_ignore_s
            self._target_selector.ignore_target(name, until, pos=pos)
            if prompt_text and prompt_text not in PORTAL_PROMPTS:
                self._target_selector.ignore_target(prompt_text, until, pos=pos)
            self._target_selector.clear_temp_target()
        return commands

    def _explore(self, obs: Observation, now: float) -> frozenset[str]:
        if self._zone_tracker.heading is None or obs.north is None:
            return frozenset({MAP_KEY})
        self._bearing = obs.north + self._zone_tracker.heading
        return direction(self._bearing) | {MAP_KEY}

    def _log_state_change(self, observation: Observation) -> None:
        state = observation.end_screen or ("playing" if observation.recognised else "unrecognised")
        if state != self._last_state:
            log.info("state: %s%s", state, f" (countdown {observation.countdown})" if observation.countdown else "")
            self._last_state = state

    # Backward-compatible helper methods for existing tests
    def _weigh(self, obs: Observation, now: float) -> dict[str, float]:
        if self._zone_tracker.update(obs.zone, obs.seconds_left):
            self._target_selector.reset_zone()
        if (obs.boss_down or (self._zone_tracker.boss_phase == BossPhase.FIGHTING and obs.portal is not None)) and self._zone_tracker.boss_phase != BossPhase.BEATEN:
            self._zone_tracker.boss_phase = BossPhase.BEATEN
        return self._target_selector.weigh(obs, now, self._zone_tracker.zone_seconds, self._zone_tracker.boss_phase)

    def _candidates(self, found: Sequence[tuple[str, Point]], now: float, is_zonemap: bool = False) -> list[tuple[str, Point]]:
        return self._target_selector.candidates(found, now, is_zonemap=is_zonemap)

    def _best(self, candidates: Sequence[tuple[str, Point]], origin: tuple[float, float], scale: float = 200.0) -> tuple[str, Point]:
        return self._target_selector.best(candidates, origin, scale=scale)

    def _candidate_score(self, name: str, pos: tuple[float, float], origin: tuple[float, float], scale: float, is_current: bool = False) -> tuple[float, float]:
        return self._target_selector.score_candidate(name, pos, origin, scale, is_current=is_current)

    def _ignore_target(self, name: str, until: float, pos: tuple[float, float] | None = None) -> None:
        self._target_selector.ignore_target(name, until, pos=pos)
