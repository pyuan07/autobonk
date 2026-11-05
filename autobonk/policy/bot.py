"""The bot: orchestrates perception, popup choices, navigation, and targets."""

import logging
import math
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from autobonk.commands import Command, Hold, Pause, Press, ReleaseAll, Stop
from autobonk.game import (
    ALTAR,
    ALTAR_ARRIVED_PX,
    BOSS,
    CLOSE_TIMEOUT_PX,
    CORE_TARGETS,
    EXPLORE,
    INTERACT_KEY,
    INTERACT_PX,
    MAP_KEY,
    PORTAL,
    SANCTUARY,
    TARGET_ARRIVED_PX,
    UNCHANGED,
    BossRule,
    Unchanged,
    Weight,
    is_boss_prompt,
    is_generic_prompt,
    is_portal_prompt,
    prompt_matches_target,
)
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
    orbit_bearing,
    time_orbit_bearing,
)
from autobonk.policy.popups import PopupPolicy
from autobonk.policy.runs import RunLifecycle
from autobonk.policy.targets import TargetSelector
from autobonk.policy.zone import BossPhase, ZoneTracker
from autobonk.runtime.frames import Frame

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Movement:
    jump_interval_s: tuple[float, float] = (0.8, 1.4)
    altar_charge_cap_s: float = 45.0
    target_ignore_s: float = 60.0
    stuck_s: float = 2.5
    sidestep_s: float = 0.6
    distance_factor: float = 0.2
    altar_orbit: bool = True
    rng: Uniform = field(default_factory=random.Random)


@dataclass
class BotStatus:
    zone: str = ""
    target: str = ""
    charging: bool = False
    held: frozenset[str] = field(default_factory=frozenset)
    status_text: str = ""
    level: int | None = None
    countdown: str = ""
    seconds_left: int | None = None
    target_distance: float | None = None
    boss_phase: str = "waiting"
    boss_ready: bool = False
    nav_mode: str = "minimap"
    stuck_seconds: float = 0.0
    main_target: str = ""
    sub_target: str = ""
    sub_target_distance: float | None = None
    runs: int = 0
    wins: int = 0
    losses: int = 0


@dataclass(frozen=True)
class PromptState:
    """The on-screen E prompt as this step judged it."""

    text: str
    ok: bool  # E may be pressed on it: not ignored, not a held portal, not an unready boss
    boss_not_ready: bool  # a boss summon prompt while the boss rule says not yet
    portal_held: bool  # a portal prompt while boss loot is still lying around


def _sanctuary_exit(obs: Observation) -> Point:
    """The sanctuary exit opens at the altar; straight ahead when no altar is on the minimap."""
    return obs.altars[0] if obs.altars else (0, -30)


class Bot:
    def __init__(
        self,
        unknown_screen_pause_s: float = 5.0,
        cards: CardPrefs | None = None,
        movement: Movement | None = None,
        targets: Mapping[str, Weight] | None = None,
        boss: BossRule | None = None,
        banish_threshold: float | None = -5.0,
        reroll_threshold: float | None = 0.0,
        skip_threshold: float | None = 0.0,
        plan_fallback_reroll_threshold: float | None = None,
        sub_target_base_allowance: float = 12.0,
        sub_target_weight_factor: float = 3.0,
        auto_restart: str = "always",
        max_runs: int = 0,
        restart_load_s: float = 20.0,
    ):
        self._unknown_screen_pause_s = unknown_screen_pause_s
        self._movement = movement or Movement()
        self._runs = RunLifecycle(
            auto_restart=auto_restart,
            max_runs=max_runs,
            restart_load_s=restart_load_s,
        )

        # Modular components
        self._popups = PopupPolicy(
            cards=cards if cards is not None else CardPrefs(),
            banish_threshold=banish_threshold,
            reroll_threshold=reroll_threshold,
            skip_threshold=skip_threshold,
            plan_fallback_reroll_threshold=plan_fallback_reroll_threshold,
        )
        self._target_selector = TargetSelector(
            targets=targets,
            boss=boss,
            distance_factor=self._movement.distance_factor,
            sub_target_base_allowance=sub_target_base_allowance,
            sub_target_weight_factor=sub_target_weight_factor,
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
        self._last_obs: Observation | None = None
        self._last_distance_px: float | None = None
        self._last_sub_distance_px: float | None = None
        self._last_nav_mode: str = "minimap"
        self._last_heartbeat_s: float = 0.0
        self._last_logged_target: str | None = None
        self._last_logged_sub_target: str | None = None
        self._last_boss_ready: bool = False
        self._just_interacted_target: str | None = None
        self._boss_interacted: bool = False
        self._boss_interacted_at: float = 0.0
        self._boss_summoned_at: float | None = None
        self._last_boss_zone_pos: Position | None = None

    def reload_config(
        self,
        cards: CardPrefs | Unchanged = UNCHANGED,
        targets: Mapping[str, Weight] | None | Unchanged = UNCHANGED,
        boss: BossRule | None | Unchanged = UNCHANGED,
        movement: Movement | Unchanged = UNCHANGED,
        banish_threshold: float | None | Unchanged = UNCHANGED,
        reroll_threshold: float | None | Unchanged = UNCHANGED,
        skip_threshold: float | None | Unchanged = UNCHANGED,
        plan_fallback_reroll_threshold: float | None | Unchanged = UNCHANGED,
        sub_target_base_allowance: float | Unchanged = UNCHANGED,
        sub_target_weight_factor: float | Unchanged = UNCHANGED,
        auto_restart: str | Unchanged = UNCHANGED,
        max_runs: int | Unchanged = UNCHANGED,
        restart_load_s: float | Unchanged = UNCHANGED,
    ) -> None:
        """Dynamically reload card weights, target weights, boss rules, and thresholds.
        UNCHANGED keeps a setting; None turns a threshold or the boss rule off."""
        if movement is not UNCHANGED:
            self._movement = movement
            self._jumper.interval = movement.jump_interval_s
            self._unsticker.stuck_s = movement.stuck_s
            self._unsticker.sidestep_s = movement.sidestep_s
            self._approach.target_ignore_s = movement.target_ignore_s
        self._popups.reload_config(
            cards=cards,
            banish_threshold=banish_threshold,
            reroll_threshold=reroll_threshold,
            skip_threshold=skip_threshold,
            plan_fallback_reroll_threshold=plan_fallback_reroll_threshold,
        )
        self._target_selector.reload_config(
            targets=targets,
            boss=boss,
            distance_factor=UNCHANGED if movement is UNCHANGED else movement.distance_factor,
            sub_target_base_allowance=sub_target_base_allowance,
            sub_target_weight_factor=sub_target_weight_factor,
        )
        self._runs.reload_config(
            auto_restart=None if auto_restart is UNCHANGED else auto_restart,
            max_runs=None if max_runs is UNCHANGED else max_runs,
            restart_load_s=None if restart_load_s is UNCHANGED else restart_load_s,
        )
        log.info("Bot configuration reloaded dynamically")

    def status(self) -> BotStatus:
        obs = self._last_obs
        level = obs.level if obs else None
        countdown = (obs.countdown or "") if obs else ""
        seconds_left = obs.seconds_left if obs else None
        zone_index = obs.zone_index if obs else None

        boss_ready = False
        if (
            self._target_selector.boss
            and level is not None
            and seconds_left is not None
            and zone_index is not None
        ):
            boss_ready = self._target_selector.boss.ready(zone_index, level, seconds_left)

        stuck_s = 0.0
        if hasattr(self._unsticker, "stuck_duration"):
            stuck_s = self._unsticker.stuck_duration(time.monotonic())

        main_t = self._target_selector.current_target or ""
        sub_t = self._target_selector.sub_target or ""
        effective_t = sub_t or main_t

        return BotStatus(
            zone=self._zone_tracker.zone or (obs.zone if obs else "") or "",
            target=effective_t,
            charging=self._charging_since is not None,
            held=self._held,
            status_text=self._last_state or "running",
            level=level,
            countdown=countdown,
            seconds_left=seconds_left,
            target_distance=self._last_sub_distance_px if sub_t else self._last_distance_px,
            boss_phase=self._zone_tracker.boss_phase.value,
            boss_ready=boss_ready,
            nav_mode=self._last_nav_mode,
            stuck_seconds=stuck_s,
            main_target=main_t,
            sub_target=sub_t,
            sub_target_distance=self._last_sub_distance_px,
            runs=self._runs.run_count,
            wins=self._runs.wins,
            losses=self._runs.losses,
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

    def _reset_run_state(self) -> None:
        self._zone_tracker.reset()
        self._target_selector.reset()
        self._approach.reset()
        self._unsticker.reset()
        self._jumper.reset()
        self._popups.reset()
        self._held = frozenset()
        self._bearing = None
        self._charging_since = None
        self._unrecognised_since = None
        self._last_state = None
        self._last_distance_px = None
        self._last_sub_distance_px = None
        self._last_nav_mode = "minimap"
        self._last_logged_target = None
        self._last_logged_sub_target = None
        self._last_boss_ready = False
        self._just_interacted_target = None
        self._boss_interacted = False
        self._boss_interacted_at = 0.0
        self._boss_summoned_at = None
        self._last_boss_zone_pos = None

    def step(self, frame: Frame) -> list[Command]:
        obs = perceive(frame, self._target_selector.icons)
        self._last_obs = obs
        self._log_state_change(obs)

        if obs.end_screen:
            self._reset_run_state()
            return self._release(
                self._runs.on_end_screen(
                    obs.end_screen,
                    obs.can_restart,
                    frame.timestamp,
                )
            )

        if obs.team_view:
            self._unrecognised_since = None
            self._jumper.reset()
            return self._release(self._popups.close_team_view(frame.timestamp))

        if obs.popup:
            self._unrecognised_since = None
            self._jumper.reset()
            last_target = self._approach.interacted[0] if self._approach.interacted else None
            cur_target = self._target_selector.current_target
            prompt_text = obs.prompt[1] if obs.prompt else ""
            commands = self._release(self._popups.answer(obs.popup, frame.timestamp))
            if self._popups.last_was_leave:
                self._approach.reset()
                self._target_selector.clear_temp_target()
                self._charging_since = None
                until = frame.timestamp + self._movement.target_ignore_s
                targets_to_ignore = set()
                if prompt_text:
                    targets_to_ignore.add(prompt_text)
                    targets_to_ignore.add(prompt_text.split("·")[0].split("：")[0].split(":")[0].strip())
                if last_target:
                    targets_to_ignore.add(last_target)
                if cur_target:
                    targets_to_ignore.add(cur_target)
                if obs.popup.title:
                    targets_to_ignore.add(obs.popup.title.split("·")[0].split("：")[0].split(":")[0].strip())
                for t in targets_to_ignore:
                    # Leaving a shop or NPC popup must not hide the zone's own flow:
                    # altar, boss and portal stay reachable.
                    if t and t not in CORE_TARGETS and is_generic_prompt(t):
                        self._target_selector.ignore_target(t, until)
                self._target_selector.current_target = None
            else:
                if self._charging_since is not None:
                    self._target_selector.current_target = ALTAR
            return commands

        if obs.countdown:
            if self._runs.on_in_game(frame.timestamp):
                self._reset_run_state()
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
        timeout = self._runs.unknown_screen_timeout(self._unknown_screen_pause_s)
        if frame.timestamp - self._unrecognised_since >= timeout:
            self._unrecognised_since = None
            return self._release([ReleaseAll(), Pause(f"screen unrecognised for {timeout:g} s")])
        return []

    def _release(self, commands: list[Command]) -> list[Command]:
        if ReleaseAll() in commands:
            if (
                MAP_KEY in self._held
                and Press(MAP_KEY) not in commands
                and not any(isinstance(c, (Stop, Pause)) for c in commands)
            ):
                new_commands: list[Command] = []
                for c in commands:
                    if isinstance(c, ReleaseAll):
                        new_commands.append(Hold(frozenset({MAP_KEY})))
                    else:
                        new_commands.append(c)
                self._held = frozenset({MAP_KEY})
                return new_commands
            self._held = frozenset()
        return commands

    def _update_boss_defeat(self, obs: Observation, now: float) -> None:
        """Detects whether the area boss has been defeated and updates boss phase accordingly."""
        if self._zone_tracker.boss_phase == BossPhase.BEATEN:
            return

        has_skull = any(name == BOSS for name, _ in obs.targets) or (
            obs.zonemap is not None and any(name == BOSS for name, _ in obs.zonemap.targets)
        )
        is_summon_prompt = bool(obs.prompt and is_boss_prompt(obs.prompt[1]))

        # In sanctuary, the boss trigger icon is the altar on minimap (or skull if present) or "触碰圣地" prompt
        has_boss_trigger = (
            (bool(obs.altars) or is_summon_prompt or has_skull)
            if obs.is_sanctuary
            else (has_skull or is_summon_prompt)
        )

        # In WAITING phase:
        # Check if the boss summon has successfully triggered (trigger icon and prompt disappeared after interaction)
        if self._zone_tracker.boss_phase == BossPhase.WAITING:
            if self._boss_interacted:
                if not has_boss_trigger or (obs.boss_down and not obs.is_sanctuary):
                    target_label = "sanctuary altar" if obs.is_sanctuary else "骷髅 altar"
                    log.info("%s disappeared / boss summoned: entering FIGHTING phase", target_label)
                    self._zone_tracker.boss_phase = BossPhase.FIGHTING
                    self._boss_summoned_at = now
                    self._boss_interacted = False
            else:
                return

        if self._zone_tracker.boss_phase == BossPhase.WAITING:
            return

        # In FIGHTING phase:
        # Revert to WAITING if boss trigger icon or summon prompt is still present (summon didn't trigger).
        if has_boss_trigger and not obs.boss_down and obs.portal is None:
            if self._boss_summoned_at is None or now - self._boss_summoned_at >= 1.0:
                log.info("boss trigger icon / summon prompt still present on map: area boss not activated yet, returning to waiting")
                self._zone_tracker.boss_phase = BossPhase.WAITING
                return

        boss_defeated = False
        if obs.boss_down or obs.portal is not None or (obs.prompt and is_portal_prompt(obs.prompt[1])):
            boss_defeated = True
        elif obs.is_sanctuary and self._zone_tracker.boss_phase == BossPhase.FIGHTING and obs.has_unopened_super_balls:
            log.info("sanctuary boss defeated: free super ball / reward chest appeared")
            boss_defeated = True

        if boss_defeated and self._zone_tracker.boss_phase != BossPhase.BEATEN:
            if obs.is_sanctuary:
                log.info("final boss (sanctuary) beaten: collecting loot then exiting")
            else:
                log.info("area boss beaten: collecting loot then entering portal")
            self._zone_tracker.boss_phase = BossPhase.BEATEN

    def _enter_frame(self, obs: Observation, now: float) -> Observation:
        """Track the zone, reset per-zone memory on a change, and return the observation with
        the zone's latched sanctuary flag (the HUD marker can lag the zone name)."""
        if self._zone_tracker.update(obs.zone, obs.seconds_left, obs.is_sanctuary, now=now):
            self._target_selector.reset_zone()
            self._boss_interacted = False
            self._boss_summoned_at = None
            self._last_boss_zone_pos = None
            self._approach.reset()
        if self._zone_tracker.is_sanctuary != obs.is_sanctuary:
            obs = replace(obs, is_sanctuary=self._zone_tracker.is_sanctuary)
        self._update_boss_defeat(obs, now)
        return obs

    def _move(self, obs: Observation, now: float) -> list[Command]:
        """One in-play step: update memory, judge the prompt, steer by the best map, then unstick."""
        obs = self._enter_frame(obs, now)
        if obs.zonemap:
            for name, zp in obs.zonemap.targets:
                if name == BOSS:
                    self._last_boss_zone_pos = zp
        self._settle_last_interaction(obs)
        self._target_selector.weigh(obs, now, self._zone_tracker.zone_seconds, self._zone_tracker.boss_phase)
        self._skip_sealed_altar(obs, now)
        self._track_altar_charge(obs, now)
        prompt = self._judge_prompt(obs, now)

        if obs.is_sanctuary and self._zone_tracker.boss_phase == BossPhase.FIGHTING:
            keys, commands, distance_px = self._orbit_arena(now)
        elif obs.zonemap:
            keys, commands, distance_px = self._navigate_zonemap(obs, now, prompt)
        else:
            keys, commands, distance_px = self._navigate_minimap(obs, now, prompt)
        self._last_distance_px = distance_px

        self._log_boss_readiness(obs)
        self._log_decisions(obs, now, distance_px)
        return self._apply_keys(keys, commands, obs, now, distance_px, prompt.text)

    def _settle_last_interaction(self, obs: Observation) -> None:
        """If the target E was pressed on last step is gone, drop it."""
        if self._just_interacted_target is not None:
            target_done = self._just_interacted_target
            self._just_interacted_target = None
            visible_names = {name for name, _ in obs.targets}
            if not obs.prompt and target_done not in visible_names and not obs.charging:
                self._target_selector.clear_temp_target()
                self._approach.reset()
                if self._target_selector.current_target == target_done:
                    self._target_selector.current_target = None

    def _skip_sealed_altar(self, obs: Observation, now: float) -> None:
        if obs.sealed_s is not None and not self._target_selector.is_skipped(ALTAR, now):
            log.info("altar sealed for %d s: exploring meanwhile", obs.sealed_s)
            self._target_selector.ignore_target(ALTAR, now + obs.sealed_s)

    def _track_altar_charge(self, obs: Observation, now: float) -> None:
        """Hold the altar while it charges; once charged (or capped), ignore it and move on."""
        nearby_altar_dist = min((math.hypot(x, y) for x, y in obs.altars), default=None)
        target = self._target_selector.current_target or ALTAR
        if obs.charging and (self._target_selector.current_target is None or self._target_selector.current_target == ALTAR):
            self._target_selector.current_target = ALTAR
            self._approach.reset()
            self._target_selector.clear_temp_target()
            if self._charging_since is None:
                self._charging_since = now
            if now - self._charging_since > self._movement.altar_charge_cap_s and not self._target_selector.is_skipped(target, now):
                log.info("%s still charging after %g s: moving on", target, self._movement.altar_charge_cap_s)
                self._target_selector.ignore_target(target, now + self._movement.target_ignore_s)
        else:
            if self._charging_since is not None and (nearby_altar_dist is None or nearby_altar_dist > 35.0):
                log.info("altar charging completed: moving on to next target")
                altar_pos = obs.zonemap.player if obs.zonemap else None
                self._target_selector.ignore_target(ALTAR, now + self._movement.target_ignore_s, pos=altar_pos)
                self._target_selector.clear_temp_target()
                self._target_selector.current_target = None
                self._approach.reset()
                self._charging_since = None
            elif nearby_altar_dist is None or nearby_altar_dist > 35.0:
                self._charging_since = None

    def _judge_prompt(self, obs: Observation, now: float) -> PromptState:
        """Decide whether E may go to the on-screen prompt."""
        prompt_text = ""
        boss_not_ready = False
        portal_held = False
        prompt_ok = False
        if obs.prompt and (not obs.charging or (self._target_selector.current_target is not None and self._target_selector.current_target != ALTAR)):
            _, prompt_text = obs.prompt
            boss_not_ready = is_boss_prompt(prompt_text) and (
                not obs.is_sanctuary
                and (
                    not self._target_selector.boss
                    or self._zone_tracker.boss_phase == BossPhase.BEATEN
                    or not (
                        obs.zone_index
                        and self._target_selector.boss.ready(obs.zone_index, obs.level, obs.seconds_left)
                    )
                )
            )
            portal_held = is_portal_prompt(prompt_text) and self._target_selector.has_nearby_boss_loot(obs, now)
            prompt_ok = not boss_not_ready and not portal_held and not self._target_selector.is_skipped(prompt_text, now)
        prompt = PromptState(prompt_text, prompt_ok, boss_not_ready, portal_held)
        return prompt

    def _orbit_arena(self, now: float) -> tuple[frozenset[str], list[Command], float | None]:
        """Sanctuary final boss: circle the arena while the fight lasts."""
        self._last_nav_mode = "arena_orbit"
        self._target_selector.current_target = "最终Boss"
        self._target_selector.sub_target = None
        self._last_sub_distance_px = None
        elapsed = now - (self._boss_summoned_at or now)
        self._bearing = time_orbit_bearing(elapsed, period_s=3.6)
        keys = direction(self._bearing)
        commands: list[Command] = []
        return keys, commands, None

    def _navigate_zonemap(
        self, obs: Observation, now: float, prompt: PromptState
    ) -> tuple[frozenset[str], list[Command], float | None]:
        """Tab held: pick the target on the zone map, steer by the minimap once close."""
        assert obs.zonemap is not None
        prompt_text, prompt_ok = prompt.text, prompt.ok
        keys: frozenset[str] = frozenset()
        commands: list[Command] = []
        distance_px: float | None = None
        can_afford_ball = obs.gold is None or obs.ball_price is None or obs.gold >= obs.ball_price
        self._last_nav_mode = "zonemap"
        zone = obs.zonemap
        self._zone_tracker.mark_visited(zone.player)
        zone_targets = [(ALTAR, p) for p in zone.altars] + list(zone.targets)
        if EXPLORE in self._target_selector.active_weights:
            unvisited_sector = self._zone_tracker.nearest_unvisited_sector(zone.player)
            if unvisited_sector is not None:
                zone_targets.append((EXPLORE, unvisited_sector))
        candidates = self._target_selector.candidates(zone_targets, now, is_zonemap=True, can_afford_pokeball=can_afford_ball)
        target_pos: Position | None = None

        if self._zone_tracker.boss_phase == BossPhase.BEATEN and not self._target_selector.has_nearby_boss_loot(obs, now):
            self._target_selector.current_target = PORTAL
            target_pos = self._portal_zone_pos(obs)
        elif prompt_ok and is_boss_prompt(prompt_text):
            self._target_selector.current_target = BOSS
            target_pos = zone.player
        elif candidates:
            best_name, target_pos = self._target_selector.best(candidates, zone.player, scale=1.0)
            self._target_selector.current_target = best_name
        elif self._zone_tracker.boss_phase == BossPhase.BEATEN:
            target_pos = self._portal_zone_pos(obs)
            portal_known = obs.portal is not None or target_pos is not None
            self._target_selector.current_target = PORTAL if portal_known else None
        else:
            self._target_selector.current_target, target_pos = None, self._zone_tracker.nearest_unvisited(zone.player)

        if target_pos is not None:
            dx, dy = target_pos[0] - zone.player[0], target_pos[1] - zone.player[1]
            self._zone_tracker.heading = math.degrees(math.atan2(dx, -dy))

        matching_minimap: list[Point] = []
        cur_t = self._target_selector.current_target
        if cur_t == ALTAR:
            matching_minimap = list(obs.altars)
        elif cur_t == PORTAL:
            if obs.portal is not None:
                matching_minimap = [obs.portal]
            elif obs.is_sanctuary:
                matching_minimap = [_sanctuary_exit(obs)]
        elif cur_t and cur_t != EXPLORE:
            matching_minimap = [p for name, p in obs.targets if name == cur_t]

        zone_dist = math.hypot(dx, dy) if target_pos is not None else 0.0
        boss_wanted = BOSS in self._target_selector.active_weights and cur_t != BOSS

        # Check for wayside sub-target on minimap while traveling on zonemap
        sub_cand: tuple[str, tuple[int, int]] | None = None
        if not boss_wanted and not obs.charging and cur_t and self._zone_tracker.heading is not None:
            approx_bearing = (self._zone_tracker.heading + (obs.north or 0.0)) % 360.0
            rad = math.radians(approx_bearing)
            approx_dist = min(300.0, max(60.0, zone_dist * 1000.0))
            approx_main_pos = (approx_dist * math.sin(rad), -approx_dist * math.cos(rad))
            instant_candidates = self._target_selector.candidates(obs.targets, now, can_afford_pokeball=can_afford_ball)
            sub_cand = self._target_selector.find_sub_target(instant_candidates, cur_t, approx_main_pos)

        if sub_cand is not None:
            sub_name, (sx, sy) = sub_cand
            self._target_selector.sub_target = sub_name
            sub_dist = math.hypot(sx, sy)
            self._last_sub_distance_px = sub_dist
            sub_keys, commands = self._steer_and_interact(
                sub_name, sx, sy, sub_dist, prompt, now, zone.player
            )
            keys = (sub_keys | {MAP_KEY}) if sub_keys else frozenset({MAP_KEY})
            if Press(INTERACT_KEY) in commands:
                self._just_interacted_target = sub_name
        elif not boss_wanted and obs.charging and (cur_t is None or cur_t == ALTAR) and not self._target_selector.is_skipped(ALTAR, now):
            self._target_selector.sub_target = None
            self._last_sub_distance_px = None
            keys, distance_px = self._hold_altar_ring(obs)
        elif matching_minimap and (target_pos is None or zone_dist < 0.25):
            self._target_selector.sub_target = None
            self._last_sub_distance_px = None
            mx, my = min(matching_minimap, key=lambda p: p[0] ** 2 + p[1] ** 2)
            distance_px = math.hypot(mx, my)
            keys, commands = self._steer_and_interact(
                cur_t, mx, my, distance_px, prompt, now, zone.player
            )
            if Press(INTERACT_KEY) in commands:
                self._just_interacted_target = cur_t
        elif prompt_ok and (cur_t != BOSS or is_boss_prompt(prompt_text)):
            commands = self._interact_with_prompt(prompt_text, now, pos=zone.player)
        else:
            self._target_selector.sub_target = None
            self._last_sub_distance_px = None
            if self._zone_tracker.heading is not None:
                if obs.north is not None:
                    self._bearing = obs.north + self._zone_tracker.heading
                if self._bearing is not None:
                    keys = direction(self._bearing) | {MAP_KEY}
                else:
                    keys = frozenset({MAP_KEY})
            else:
                keys = frozenset({MAP_KEY})
        return keys, commands, distance_px

    def _navigate_minimap(
        self, obs: Observation, now: float, prompt: PromptState
    ) -> tuple[frozenset[str], list[Command], float | None]:
        """No zone map: walk to the best icon on the minimap, or explore."""
        prompt_text, prompt_ok = prompt.text, prompt.ok
        keys: frozenset[str] = frozenset()
        commands: list[Command] = []
        distance_px: float | None = None
        can_afford_ball = obs.gold is None or obs.ball_price is None or obs.gold >= obs.ball_price
        extra_targets: list[tuple[str, tuple[int, int]]] = []
        if self._zone_tracker.boss_phase == BossPhase.BEATEN and not self._target_selector.has_nearby_boss_loot(obs, now):
            if obs.portal is not None:
                extra_targets.append((PORTAL, obs.portal))
            elif obs.is_sanctuary:
                extra_targets.append((PORTAL, _sanctuary_exit(obs)))
        self._last_nav_mode = "minimap"
        extra_altars = (
            [(ALTAR, (0, -30))]
            if obs.is_sanctuary and not obs.altars and self._zone_tracker.boss_phase == BossPhase.WAITING
            else []
        )
        visible_candidates = self._target_selector.candidates(
            [(ALTAR, p) for p in obs.altars] + extra_altars + list(obs.targets) + extra_targets,
            now,
            can_afford_pokeball=can_afford_ball,
        )
        is_moving = bool(self._held - {MAP_KEY})
        minimap_candidates = self._target_selector.with_temp_target(visible_candidates, now, is_moving)
        boss_wanted = BOSS in self._target_selector.active_weights and not any(name == BOSS for name, _ in minimap_candidates)

        cur_t = self._target_selector.current_target
        if not boss_wanted and obs.charging and (cur_t is None or cur_t == ALTAR) and not self._target_selector.is_skipped(ALTAR, now):
            keys, distance_px = self._hold_altar_ring(obs)
        elif minimap_candidates and not boss_wanted:
            best_name, (x, y) = self._target_selector.best(minimap_candidates, (0, 0), scale=200.0)
            self._target_selector.current_target = best_name
            distance_px = math.hypot(x, y)
            self._target_selector.update_temp_target(best_name, distance_px, (float(x), float(y)), visible_candidates, now)

            # Check for wayside sub-target
            sub_cand = self._target_selector.find_sub_target(visible_candidates, best_name, (float(x), float(y)))
            if sub_cand is not None and not obs.charging:
                sub_name, (sx, sy) = sub_cand
                self._target_selector.sub_target = sub_name
                sub_dist = math.hypot(sx, sy)
                self._last_sub_distance_px = sub_dist
                keys, commands = self._steer_and_interact(
                    sub_name, sx, sy, sub_dist, prompt, now, None
                )
                if Press(INTERACT_KEY) in commands and (sub_dist <= TARGET_ARRIVED_PX or prompt_ok):
                    self._just_interacted_target = sub_name
            else:
                self._target_selector.sub_target = None
                self._last_sub_distance_px = None
                keys, commands = self._steer_and_interact(
                    best_name, x, y, distance_px, prompt, now, None
                )
                if Press(INTERACT_KEY) in commands and (distance_px <= TARGET_ARRIVED_PX or prompt_ok):
                    self._just_interacted_target = best_name
        elif prompt_ok and (not boss_wanted or is_boss_prompt(prompt_text)):
            commands = self._interact_with_prompt(prompt_text, now)
        else:
            self._target_selector.sub_target = None
            self._last_sub_distance_px = None
            if not boss_wanted and cur_t != BOSS:
                self._target_selector.current_target = None
                self._approach.reset()
            keys = self._explore(obs, now)
        return keys, commands, distance_px

    def _log_boss_readiness(self, obs: Observation) -> None:
        if (
            self._target_selector.boss
            and obs.level is not None
            and obs.seconds_left is not None
            and obs.zone_index is not None
        ):
            is_ready = self._target_selector.boss.ready(obs.zone_index, obs.level, obs.seconds_left)
            if is_ready != self._last_boss_ready:
                self._last_boss_ready = is_ready
                idx = min(obs.zone_index, len(self._target_selector.boss.levels)) - 1
                req_level = self._target_selector.boss.levels[idx]
                req_sec = int(self._target_selector.boss.minutes_left[idx] * 60)
                if is_ready:
                    log.info(
                        "[Boss判定] 条件达成! 等级 %d >= %d 且 剩余时间 %s <= %d分 (阶段: %s) -> 锁定骷髅",
                        obs.level,
                        req_level,
                        obs.countdown or "--:--",
                        req_sec // 60,
                        self._zone_tracker.boss_phase.value,
                    )
                else:
                    log.info(
                        "[Boss判定] 暂不满足: 等级 %d/%d, 剩余时间 %s/%d分 (阶段: %s)",
                        obs.level,
                        req_level,
                        obs.countdown or "--:--",
                        req_sec // 60,
                        self._zone_tracker.boss_phase.value,
                    )

    def _log_decisions(self, obs: Observation, now: float, distance_px: float | None) -> None:
        """Log target changes, plus a heartbeat every 5 s."""
        # Check target changes
        cur_t = self._target_selector.current_target
        cur_sub = self._target_selector.sub_target
        if cur_t != self._last_logged_target or cur_sub != self._last_logged_sub_target:
            sub_str = f" [顺路: {cur_sub} ({self._last_sub_distance_px:.0f}px)]" if cur_sub and self._last_sub_distance_px is not None else ""
            dist_str = f", 距主目标: {distance_px:.0f}px" if distance_px is not None else ""
            log.info(
                "[目标决策] 目标变更: 主目标 [%s]%s (模式: %s%s)",
                cur_t or "探索漫游",
                sub_str,
                self._last_nav_mode,
                dist_str,
            )
            self._last_logged_target = cur_t
            self._last_logged_sub_target = cur_sub

        # 5-second periodic heartbeat log
        if now - self._last_heartbeat_s >= 5.0:
            self._last_heartbeat_s = now
            keys_str = ",".join(sorted(self._held)) if self._held else "None"
            boss_info = self._zone_tracker.boss_phase.value
            if self._last_boss_ready:
                boss_info += "(条件满足)"
            target_str = cur_t or "探索漫游"
            if cur_sub and self._last_sub_distance_px is not None:
                target_str += f" (顺路: {cur_sub} {self._last_sub_distance_px:.0f}px)"
            dist_str = f" 距主目标={distance_px:.0f}px" if distance_px is not None else ""
            log.info(
                "[State] %s | Lv %s | %s | 目标: %s%s | Boss: %s | 导航: %s | 按键: [%s]",
                self._zone_tracker.zone or "未知区域",
                obs.level if obs.level is not None else "?",
                obs.countdown or "--:--",
                target_str,
                dist_str,
                boss_info,
                "大地图(Tab)" if obs.zonemap else "小地图",
                keys_str,
            )

    def _apply_keys(
        self,
        keys: frozenset[str],
        commands: list[Command],
        obs: Observation,
        now: float,
        distance_px: float | None,
        prompt_text: str,
    ) -> list[Command]:
        """Unstick if needed, stand still while summoning the boss, and send only key changes."""
        if self._approach.interacted is not None:
            self._unsticker.reset()
        active_distance = self._last_sub_distance_px if self._target_selector.sub_target is not None else distance_px
        keys = self._unsticker.unstick(keys, self._bearing, obs, now, active_distance)
        if any(c == Press(INTERACT_KEY) for c in commands) and is_boss_prompt(prompt_text):
            keys = frozenset()
        if keys != self._held:
            self._held = keys
            commands = [Hold(keys)] + commands
        return commands

    def _hold_altar_ring(self, obs: Observation) -> tuple[frozenset[str], float | None]:
        """While the altar charges: walk into its ring, then orbit inside it."""
        if not obs.altars:
            return frozenset(), None
        mx, my = min(obs.altars, key=lambda p: p[0] ** 2 + p[1] ** 2)
        distance_px = math.hypot(mx, my)
        if distance_px > ALTAR_ARRIVED_PX:
            self._bearing = math.degrees(math.atan2(mx, -my))
        elif self._movement.altar_orbit:
            self._bearing = orbit_bearing(mx, my, orbit_radius=6.0)
        else:
            return frozenset(), distance_px
        return direction(self._bearing), distance_px

    def _interact_with_prompt(self, prompt_text: str, now: float, pos: Position | None = None) -> list[Command]:
        """No icon to walk to, but a valid prompt is up: press E on whatever it belongs to."""
        if is_boss_prompt(prompt_text):
            self._target_selector.current_target = BOSS
        self._target_selector.sub_target = None
        self._last_sub_distance_px = None
        commands = self._interact(prompt_text, now, spam_e=True, prompt_text=prompt_text, pos=pos)
        if Press(INTERACT_KEY) in commands:
            self._just_interacted_target = prompt_text
        return commands

    def _portal_zone_pos(self, obs: Observation) -> Position | None:
        """Where to head on the zone map once the boss is beaten. None while the portal is
        already on the minimap (steer by that instead) or nothing better is known."""
        if obs.portal is not None or obs.zonemap is None:
            return None
        if obs.is_sanctuary:
            return obs.zonemap.altars[0] if obs.zonemap.altars else (0.5, 0.5)
        return self._last_boss_zone_pos

    def _steer_and_interact(
        self,
        target_name: str | None,
        x: float,
        y: float,
        distance_px: float,
        prompt: PromptState,
        now: float,
        pos: Position | None,
    ) -> tuple[frozenset[str], list[Command]]:
        prompt_text, prompt_ok = prompt.text, prompt.ok
        boss_not_ready, portal_held = prompt.boss_not_ready, prompt.portal_held
        is_sanctuary = self._zone_tracker.is_sanctuary
        keys: frozenset[str] = frozenset()
        commands: list[Command] = []
        matching_prompt = prompt_ok and (
            prompt_matches_target(prompt_text, target_name)
            or (
                distance_px <= INTERACT_PX
                and target_name not in CORE_TARGETS
                and is_generic_prompt(prompt_text)
            )
        )
        if target_name == ALTAR and not (prompt_ok and (is_sanctuary or "触碰圣地" in prompt_text)):
            if distance_px > ALTAR_ARRIVED_PX:
                self._bearing = math.degrees(math.atan2(x, -y))
                keys = direction(self._bearing)
            if matching_prompt or (prompt_ok and "触碰圣地" in prompt_text):
                commands = self._interact(target_name or "", now, spam_e=True, prompt_text=prompt_text, pos=pos, at_target=True)
        else:
            stop_dist = TARGET_ARRIVED_PX if matching_prompt else 2
            if distance_px > stop_dist:
                self._bearing = math.degrees(math.atan2(x, -y))
                keys = direction(self._bearing)
            at_target = matching_prompt or distance_px <= TARGET_ARRIVED_PX
            if (
                distance_px <= CLOSE_TIMEOUT_PX
                or matching_prompt
                or (self._approach.interacted is not None and self._approach.interacted[0] == target_name)
            ):
                if target_name == PORTAL:
                    can_press_e = distance_px <= INTERACT_PX and matching_prompt and not portal_held
                else:
                    can_press_e = (distance_px <= INTERACT_PX or prompt_ok) and not boss_not_ready and not portal_held
                commands = self._interact(
                    target_name or "", now, spam_e=can_press_e, prompt_text=prompt_text, pos=pos, at_target=at_target
                )
        return keys, commands

    def _interact(
        self,
        name: str,
        now: float,
        *,
        spam_e: bool = True,
        prompt_text: str = "",
        pos: tuple[float, float] | None = None,
        at_target: bool = True,
    ) -> list[Command]:
        if not name:
            return []
        is_boss_trigger = (
            name in (BOSS, SANCTUARY)
            or is_boss_prompt(name)
            or is_boss_prompt(prompt_text)
            or (self._zone_tracker.is_sanctuary and name == ALTAR)
        )
        if is_boss_trigger and spam_e and at_target:
            log.info("interacting with boss altar (%s): pressing E", name)
            self._boss_interacted = True
            self._boss_interacted_at = now
            if pos is not None:
                self._last_boss_zone_pos = (float(pos[0]), float(pos[1]))

        commands, timed_out = self._approach.interact(
            name,
            now,
            spam_e=spam_e,
            prompt_text=prompt_text,
            pos=pos,
            at_target=at_target,
            is_sanctuary=self._zone_tracker.is_sanctuary,
        )
        if timed_out:
            log.info("%s: E did nothing (not enough money?), skipping for %g s", name, self._movement.target_ignore_s)
            until = now + self._movement.target_ignore_s
            self._target_selector.ignore_target(name, until, pos=pos)
            if prompt_text and not is_portal_prompt(prompt_text):
                self._target_selector.ignore_target(prompt_text, until, pos=pos)
            self._target_selector.clear_temp_target()
        return commands

    def _explore(self, obs: Observation, now: float) -> frozenset[str]:
        if self._zone_tracker.heading is not None:
            if obs.north is not None:
                self._bearing = obs.north + self._zone_tracker.heading
            if self._bearing is not None:
                return direction(self._bearing) | {MAP_KEY}
        if obs.is_sanctuary:
            if self._zone_tracker.boss_phase == BossPhase.FIGHTING:
                elapsed = now - (self._boss_summoned_at or now)
                self._bearing = time_orbit_bearing(elapsed, period_s=3.6)
                return direction(self._bearing)
            move_keys = direction(self._bearing) if self._bearing is not None else frozenset({"KeyW"})
            return move_keys
        return frozenset({MAP_KEY})

    def _log_state_change(self, observation: Observation) -> None:
        state = (
            observation.end_screen
            or ("game_paused" if observation.game_paused else None)
            or ("playing" if observation.recognised else "unrecognised")
        )
        if state != self._last_state:
            log.info("state: %s%s", state, f" (countdown {observation.countdown})" if observation.countdown else "")
            self._last_state = state

    # Backward-compatible helper methods for existing tests
    def _weigh(self, obs: Observation, now: float) -> dict[str, float]:
        obs = self._enter_frame(obs, now)
        return self._target_selector.weigh(obs, now, self._zone_tracker.zone_seconds, self._zone_tracker.boss_phase)

    def _candidates(self, found: Sequence[tuple[str, Point]], now: float, is_zonemap: bool = False, can_afford_pokeball: bool = True) -> list[tuple[str, Point]]:
        return self._target_selector.candidates(found, now, is_zonemap=is_zonemap, can_afford_pokeball=can_afford_pokeball)

    def _best(self, candidates: Sequence[tuple[str, Point]], origin: tuple[float, float], scale: float = 200.0) -> tuple[str, Point]:
        return self._target_selector.best(candidates, origin, scale=scale)

    def _candidate_score(self, name: str, pos: tuple[float, float], origin: tuple[float, float], scale: float, is_current: bool = False) -> tuple[float, float]:
        return self._target_selector.score_candidate(name, pos, origin, scale, is_current=is_current)

    def _ignore_target(self, name: str, until: float, pos: tuple[float, float] | None = None) -> None:
        self._target_selector.ignore_target(name, until, pos=pos)
