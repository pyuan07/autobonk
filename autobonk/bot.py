"""The bot: `Bot.step(frame) -> commands`, the one seam between perception/policy and the driver."""

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Mapping, Protocol, TypeVar

from autobonk.cards import CardPrefs
from autobonk.frames import Frame
from autobonk.perception import (
    BANISH_RE,
    LEAVE_BUTTONS,
    Observation,
    Popup,
    REROLL_RE,
    SKIP_RE,
    perceive,
)
from autobonk.zonemap import Position

log = logging.getLogger(__name__)
T = TypeVar("T", bound=tuple[float, float])

# If a popup is still open this long after answering it, the key was missed: press again.
POPUP_RETRY_S = 1.0
PICK_UP_BUTTON = "拾取"  # item pickup; its neighbour 出售 (sell) is never used
READY_BUTTON = "就绪"  # Hypno: close without forgetting a move
DITTO_TITLE = "百变怪"
TEAM_VIEW = "你的队伍"
# Key caps as shown in the game -> keyboard key names.
KEY_NAMES = {"Esc": "Escape"}
JUMP_KEY = "Space"
# Minimap-up is always W, whichever way the camera faces. Sectors of 45 degrees, counter-clockwise from east.
DIRECTION_KEYS = (
    {"KeyD"}, {"KeyW", "KeyD"}, {"KeyW"}, {"KeyW", "KeyA"},
    {"KeyA"}, {"KeyS", "KeyA"}, {"KeyS"}, {"KeyS", "KeyD"},
)
# Closer than this (minimap pixels) the player is at the target (in an altar's ring): stop walking.
ALTAR_ARRIVED_PX = 14
TARGET_ARRIVED_PX = 4  # walk right onto non-altar targets unless the HUD prompt is already open
TEMP_TARGET_PX = 24  # remember a close target's (x, y) so the player arrow can't hide its icon
APPROACH_PX_PER_S = 20.0  # how fast a remembered target's offset shrinks while walking toward it
INTERACT_PX = 20  # start spamming E once this close to a non-altar target
CLOSE_TIMEOUT_PX = 45  # once within this range, give up on the target if not taken in INTERACT_WAIT_S
ALTAR = "符文祭坛"  # rune altars' name in [targets.weights]; every other name is an icon in autobonk.icons
DEFAULT_TARGETS = {ALTAR: 10.0}
BOSS = "骷髅"  # the area boss: E summons it (BossRule says when), then it chases the player
PORTAL = "传送门"
SUPER_BALL = "超级球"
GIFT_BALL = "礼物球"
SUPER_BALLS = frozenset({SUPER_BALL, GIFT_BALL})
INTERACT_KEY = "KeyE"  # at a target other than an altar (shop, chest...); without the money nothing happens
INTERACT_WAIT_S = 5.0  # after trying for 5 s with no popup or charging, skip the target
INTERACT_RETRY_S = 0.3  # spam E at this interval while close to the target
MAP_KEY = "Tab"  # held while exploring: the zone map shows, the game keeps running
GRID = 8  # the zone is explored as GRID x GRID cells; edge cells are never targets
ALTAR_PROGRESS_PX = 3  # getting this much closer to the target (minimap pixels) counts as progress
ZONE_PROGRESS = 0.01  # moving this far on the zone map (fraction of the zone) counts as progress


@dataclass(frozen=True)
class ReleaseAll:
    pass


@dataclass(frozen=True)
class Stop:
    reason: str


@dataclass(frozen=True)
class Pause:
    reason: str


@dataclass(frozen=True)
class Press:
    key: str


@dataclass(frozen=True)
class Click:
    text: str


@dataclass(frozen=True)
class Hold:
    """Hold exactly these keys (releasing any others) until the next Hold or ReleaseAll."""

    keys: frozenset[str]


Command = ReleaseAll | Stop | Pause | Press | Click | Hold
# A target's weight: fixed, or (at the zone's start, when its time is up), growing in between.
Weight = float | tuple[float, float]


@dataclass(frozen=True)
class BossRule:
    """Summon the area boss in zone N once the level reaches levels[N-1], or once only
    minutes_left[N-1] are left; from then on it comes before everything else."""

    levels: tuple[int, ...] = (35, 60, 80)
    minutes_left: tuple[float, ...] = (4, 8, 8)

    def ready(self, zone: int, level: int | None, seconds_left: int | None) -> bool:
        i = min(zone, len(self.levels)) - 1
        strong = level is not None and level >= self.levels[i]
        late = seconds_left is not None and seconds_left <= self.minutes_left[i] * 60
        return strong or late


class Uniform(Protocol):
    def uniform(self, a: float, b: float) -> float: ...


@dataclass(frozen=True)
class Movement:
    jump_interval_s: tuple[float, float] = (0.8, 1.4)
    altar_charge_cap_s: float = 45.0
    target_ignore_s: float = 60.0  # a target left (charge cap, E did nothing) is skipped this long
    stuck_s: float = 2.5  # no progress toward the target this long: sidestep
    sidestep_s: float = 0.6
    distance_factor: float = 0.2  # closer targets get up to +(distance_factor * 100)% score bonus
    rng: Uniform = field(default_factory=random.Random)


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
        """`targets`: map icon name -> weight. Targets are scored by weight with a proximity bonus
        (up to movement.distance_factor, default +20%); 0 or less is never visited. `boss`: when to
        summon the area boss (骷髅); None never."""
        self._unknown_screen_pause_s = unknown_screen_pause_s
        self._cards = cards
        self._banish_threshold = banish_threshold
        self._reroll_threshold = reroll_threshold
        self._skip_threshold = skip_threshold
        self._movement = movement or Movement()
        weights = DEFAULT_TARGETS if targets is None else targets
        self._weights = {name: w if isinstance(w, tuple) else (w, w) for name, w in weights.items()}
        self._weights = {name: w for name, w in self._weights.items() if max(w) > 0 and name != BOSS}
        self._boss = boss
        if SUPER_BALL in self._weights and GIFT_BALL not in self._weights:
            self._weights[GIFT_BALL] = self._weights[SUPER_BALL]
        elif GIFT_BALL in self._weights and SUPER_BALL not in self._weights:
            self._weights[SUPER_BALL] = self._weights[GIFT_BALL]
        icon_names = set(name for name in self._weights if name != ALTAR)
        if boss:
            icon_names.add(BOSS)
        icon_names.add(SUPER_BALL)
        icon_names.add(GIFT_BALL)
        self._icons = tuple(icon_names)
        self._now_weights: dict[str, float] = {}  # this step's weights
        self._zone_seconds: int | None = None  # the zone's countdown when first seen: its whole time
        self._boss_fight = False  # summoned and chasing: keep moving, no altars
        self._boss_beaten = False
        self._held: frozenset[str] = frozenset()
        self._next_jump: float | None = None
        self._charging_since: float | None = None
        self._ignored: dict[str, float] = {}  # target name -> skipped until (sealed, charge cap, E did nothing)
        self._ignored_instances: list[tuple[str, tuple[float, float], float]] = []  # (name, (zx, zy), until)
        self._target: str | None = None  # the kind of target being walked to or stood at
        self._interacted: tuple[str, float, float] | None = None  # (target, started_at, last_pressed_at)
        self._temp_target: tuple[str, tuple[float, float], float] | None = None  # (target, (x, y), when)
        self._zone: str | None = None
        self._visited: set[tuple[int, int]] = set()  # zone-map cells the player has been in
        self._heading: float | None = None  # exploring toward this compass bearing (north-up)
        self._bearing: float | None = None  # minimap bearing being walked
        self._progress: tuple[object, float] | None = None  # (last progress mark, when)
        self._sidestep: tuple[frozenset[str], float] | None = None  # (keys, until)
        self._sidestep_left = True
        self._unrecognised_since: float | None = None
        self._last_state: str | None = None
        self._answered: tuple[object, float] | None = None  # (popup state, when)

    def step(self, frame: Frame) -> list[Command]:
        observation = perceive(frame, self._icons)
        self._log_state_change(observation)

        if observation.end_screen:
            return self._release([ReleaseAll(), Stop(observation.end_screen)])

        if observation.team_view:
            self._unrecognised_since = None
            self._next_jump = None
            return self._release(self._close_team_view(frame.timestamp))

        if observation.popup:
            self._unrecognised_since = None
            self._next_jump = None
            self._interacted = None
            self._temp_target = None
            return self._release(self._answer(observation.popup, frame.timestamp))

        if observation.countdown:
            self._unrecognised_since = None
            move_cmds = self._move(observation, frame.timestamp)
            if Press(INTERACT_KEY) in move_cmds or (self._interacted is not None and not self._held):
                return move_cmds
            return move_cmds + self._jump(frame.timestamp)

        if observation.recognised:
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

    def _move(self, observation: Observation, now: float) -> list[Command]:
        """Walk to the best target on the minimap (highest weight, then nearest), else explore.
        At an altar stand in the ring while it charges (up to the cap); at anything else press E.
        Sealed altars, ones still charging at the cap and targets E did nothing for are skipped a while."""
        self._now_weights = self._weigh(observation, now)
        if observation.sealed_s is not None and not self._skipped(ALTAR, now):
            log.info("altar sealed for %d s: exploring meanwhile", observation.sealed_s)
            self._ignored[ALTAR] = now + observation.sealed_s
        target = self._target or ALTAR
        if observation.charging and (self._target is None or self._target == ALTAR):
            self._interacted = None
            self._temp_target = None
            if self._charging_since is None:
                self._charging_since = now
            if now - self._charging_since > self._movement.altar_charge_cap_s and not self._skipped(target, now):
                log.info("%s still charging after %g s: moving on", target, self._movement.altar_charge_cap_s)
                self._ignore_target(target, now + self._movement.target_ignore_s)
        else:
            self._charging_since = None

        prompt_text = ""
        boss_not_ready = False
        portal_held = False
        prompt_ok = False
        if observation.prompt and (not observation.charging or (self._target is not None and self._target != ALTAR)):
            _, prompt_text = observation.prompt
            boss_not_ready = any(k in prompt_text for k in ("守护者", "头目", BOSS)) and (
                not self._boss or self._boss_beaten or not (
                    observation.zone_index and self._boss.ready(observation.zone_index, observation.level, observation.seconds_left)
                )
            )
            portal_held = ("传送门" in prompt_text or "离开圣地" in prompt_text) and self._has_nearby_super_balls(observation, now)
            prompt_ok = not boss_not_ready and not portal_held and not self._skipped(prompt_text, now)

        keys: frozenset[str] = frozenset()
        commands: list[Command] = []
        distance: float | None = None
        extra_targets: list[tuple[str, tuple[int, int]]] = []
        if self._boss_beaten and observation.portal is not None and not self._has_nearby_super_balls(observation, now):
            extra_targets.append((PORTAL, observation.portal))

        if observation.zonemap:
            zone = observation.zonemap
            self._visited.add(_cell(zone.player))
            zone_targets = [(ALTAR, p) for p in zone.altars] + list(zone.targets)
            candidates = self._candidates(zone_targets, now, is_zonemap=True)
            target_pos: Position | None = None
            if self._boss_beaten and observation.portal is not None and not self._has_nearby_super_balls(observation, now):
                self._target = PORTAL
            elif candidates:
                self._target, target_pos = self._best(candidates, zone.player, scale=1.0)
            else:
                self._target, target_pos = None, self._nearest_unvisited(zone.player)

            if target_pos is not None:
                dx, dy = target_pos[0] - zone.player[0], target_pos[1] - zone.player[1]
                self._heading = math.degrees(math.atan2(dx, -dy))

            matching_minimap: list[Point] = []
            if self._target == ALTAR:
                matching_minimap = list(observation.altars)
            elif self._target == PORTAL and observation.portal is not None:
                matching_minimap = [observation.portal]
            elif self._target:
                matching_minimap = [p for name, p in observation.targets if name == self._target]

            zone_dist = math.hypot(dx, dy) if target_pos is not None else 0.0
            if observation.charging and (self._target is None or self._target == ALTAR) and not self._skipped(ALTAR, now):
                pass
            elif matching_minimap and (target_pos is None or zone_dist < 0.25):
                mx, my = min(matching_minimap, key=lambda p: p[0] ** 2 + p[1] ** 2)
                distance = math.hypot(mx, my)
                if self._target == ALTAR:
                    if distance > ALTAR_ARRIVED_PX:
                        self._bearing = math.degrees(math.atan2(mx, -my))
                        keys = _direction(self._bearing)
                else:
                    if distance > TARGET_ARRIVED_PX and not prompt_ok:
                        self._bearing = math.degrees(math.atan2(mx, -my))
                        keys = _direction(self._bearing)
                    if distance <= CLOSE_TIMEOUT_PX or prompt_ok or (self._interacted is not None and self._interacted[0] == self._target):
                        can_press_e = (distance <= INTERACT_PX or prompt_ok) and not boss_not_ready and not portal_held
                        commands = self._interact(self._target, now, spam_e=can_press_e, prompt_text=prompt_text, pos=zone.player)
            elif prompt_ok:
                commands = self._interact(prompt_text, now, spam_e=True, pos=zone.player)
            else:
                if self._heading is not None and observation.north is not None:
                    self._bearing = observation.north + self._heading
                    keys = _direction(self._bearing) | {MAP_KEY}
                else:
                    keys = frozenset({MAP_KEY})
        else:
            visible_candidates = self._candidates(
                [(ALTAR, p) for p in observation.altars] + list(observation.targets) + extra_targets,
                now,
            )
            candidates = self._with_temp_target(visible_candidates, now)
            boss_wanted = BOSS in self._now_weights and not any(name == BOSS for name, _ in candidates)
            if observation.charging and (self._target is None or self._target == ALTAR) and not self._skipped(ALTAR, now):
                pass
            elif candidates and not boss_wanted:
                self._target, (x, y) = self._best(candidates, (0, 0), scale=200.0)
                distance = math.hypot(x, y)
                if self._target != ALTAR and distance <= TEMP_TARGET_PX:
                    if any(n == self._target and math.hypot(px, py) <= TEMP_TARGET_PX for n, (px, py) in visible_candidates):
                        self._temp_target = (self._target, (float(x), float(y)), now)
                    elif self._temp_target is None or self._temp_target[0] != self._target:
                        self._temp_target = (self._target, (float(x), float(y)), now)
                elif self._target == ALTAR or distance > TEMP_TARGET_PX:
                    self._temp_target = None

                if self._target == ALTAR:
                    if distance > ALTAR_ARRIVED_PX:
                        self._bearing = math.degrees(math.atan2(x, -y))
                        keys = _direction(self._bearing)
                else:
                    if distance > TARGET_ARRIVED_PX and not prompt_ok:
                        self._bearing = math.degrees(math.atan2(x, -y))
                        keys = _direction(self._bearing)
                    if distance <= CLOSE_TIMEOUT_PX or prompt_ok or (self._interacted is not None and self._interacted[0] == self._target):
                        can_press_e = (distance <= INTERACT_PX or prompt_ok) and not boss_not_ready and not portal_held
                        commands = self._interact(self._target, now, spam_e=can_press_e, prompt_text=prompt_text)
            elif prompt_ok:
                commands = self._interact(prompt_text, now, spam_e=True)
            else:
                keys = self._explore(observation, now)
        keys = self._unstick(keys, observation, now, distance)
        if keys != self._held:
            self._held = keys
            commands = [Hold(keys)] + commands
        return commands

    def _with_temp_target(
        self, candidates: list[tuple[str, tuple[int, int]]], now: float
    ) -> list[tuple[str, tuple[int, int]]]:
        """Keep a close target's temporary (x, y) when the player arrow on the minimap covers its icon."""
        if self._temp_target is None:
            return candidates
        t_name, (tx, ty), last_t = self._temp_target
        if t_name not in self._now_weights or self._skipped(t_name, now):
            self._temp_target = None
            return candidates
        if any(name == t_name and math.hypot(px, py) <= TEMP_TARGET_PX for name, (px, py) in candidates):
            return candidates
        dt = max(0.0, now - last_t)
        dist = math.hypot(tx, ty)
        if (self._held - {MAP_KEY}) and dist > 0:
            new_dist = max(0.0, dist - APPROACH_PX_PER_S * dt)
            scale = new_dist / dist
            tx, ty = tx * scale, ty * scale
        self._temp_target = (t_name, (tx, ty), now)
        return candidates + [(t_name, (int(round(tx)), int(round(ty))))]

    def _has_nearby_super_balls(self, observation: Observation, now: float) -> bool:
        if self._skipped(SUPER_BALL, now) or self._skipped(GIFT_BALL, now):
            return False
        if observation.has_unopened_super_balls:
            return True
        return any(
            name in SUPER_BALLS and not self._skipped(name, now)
            for name, _ in observation.targets
        )

    def _weigh(self, observation: Observation, now: float) -> dict[str, float]:
        """This step's target weights: each grows from its start to its end weight as the zone's
        time runs out. The boss outranks everything once BossRule says so; while it chases, no altars.
        After boss fight, nearby super balls are opened first, then the portal is entered."""
        if observation.zone != self._zone:
            self._zone, self._visited, self._heading = observation.zone, set(), None
            self._zone_seconds, self._boss_fight, self._boss_beaten = None, False, False
            self._ignored_instances = []
        left = observation.seconds_left
        if left is not None and (self._zone_seconds is None or left > self._zone_seconds):
            self._zone_seconds = left
        progress = 1 - left / self._zone_seconds if left is not None and self._zone_seconds else 0.0
        weights = {name: start + (end - start) * progress for name, (start, end) in self._weights.items()}
        if (observation.boss_down or (self._boss_fight and observation.portal is not None)) and not self._boss_beaten:
            log.info("area boss beaten")
            self._boss_fight, self._boss_beaten = False, True
        if self._boss_fight:
            weights.pop(ALTAR, None)
        elif self._boss_beaten:
            if self._has_nearby_super_balls(observation, now):
                weights[SUPER_BALL] = math.inf
                weights[GIFT_BALL] = math.inf
            elif observation.portal is not None:
                weights[PORTAL] = math.inf
        elif self._boss and not self._boss_beaten and observation.zone_index:
            if self._boss.ready(observation.zone_index, observation.level, left):
                weights[BOSS] = math.inf
        return {name: w for name, w in weights.items() if w > 0}

    def _candidates(
        self,
        found: list[tuple[str, T]],
        now: float,
        player_pos: tuple[float, float] | None = None,
        is_zonemap: bool = False,
    ) -> list[tuple[str, T]]:
        candidates = []
        for name, where in found:
            if name not in self._now_weights:
                continue
            if is_zonemap:
                target_pos = (float(where[0]), float(where[1]))
            elif player_pos is not None:
                target_pos = player_pos
            else:
                target_pos = None
            if not self._skipped(name, now, target_pos):
                candidates.append((name, where))
        return candidates

    def _best(
        self,
        candidates: list[tuple[str, T]],
        origin: tuple[float, float],
        scale: float = 200.0,
    ) -> tuple[str, T]:
        current = self._target
        return max(
            candidates,
            key=lambda c: self._candidate_score(c[0], c[1], origin, scale, is_current=(c[0] == current)),
        )

    def _candidate_score(
        self,
        name: str,
        pos: tuple[float, float],
        origin: tuple[float, float],
        scale: float,
        is_current: bool = False,
    ) -> tuple[float, float]:
        dist = math.hypot(pos[0] - origin[0], pos[1] - origin[1])
        weight = self._now_weights.get(name, 0.0)
        if weight <= 0:
            return (0.0, -dist)
        if math.isinf(weight):
            return (math.inf, -dist)
        norm_dist = min(dist / scale, 1.0) if scale > 0 else 0.0
        score = weight * (1.0 + self._movement.distance_factor * (1.0 - norm_dist))
        # 15% hysteresis bonus to the currently chosen target to prevent flip-flopping
        if is_current:
            score *= 1.15
        return (score, -dist)

    def _skipped(self, name: str, now: float, pos: tuple[float, float] | None = None) -> bool:
        if now < self._ignored.get(name, 0.0):
            return True
        if pos is not None:
            for ign_name, (ix, iy), until in self._ignored_instances:
                if now < until and (ign_name == name or (name in SUPER_BALLS and ign_name in SUPER_BALLS)):
                    if math.hypot(pos[0] - ix, pos[1] - iy) < 0.08:
                        return True
        return False

    def _ignore_target(self, name: str, until: float, pos: tuple[float, float] | None = None) -> None:
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

    def _interact(
        self,
        name: str,
        now: float,
        *,
        spam_e: bool = True,
        prompt_text: str = "",
        pos: tuple[float, float] | None = None,
    ) -> list[Command]:
        """Spam E while close; if the target is still not taken INTERACT_WAIT_S later, skip its kind a while."""
        if self._interacted is None or self._interacted[0] != name:
            if not spam_e:
                self._interacted = (name, now, 0.0)
                return []
            log.info("at %s: pressing E", name)
            self._interacted = (name, now, now)
            if name == BOSS or "守护者" in name:
                log.info("area boss summoned: it chases us, so keep moving and leave the altars")
                self._boss_fight = True
            return [Press(INTERACT_KEY)]
        _, started, last_pressed = self._interacted
        if now - started >= INTERACT_WAIT_S:
            if name not in (PORTAL, "进入传送门", "离开圣地"):
                log.info("%s: E did nothing (not enough money?), skipping for %g s", name, self._movement.target_ignore_s)
                until = now + self._movement.target_ignore_s
                self._ignore_target(name, until, pos=pos)
                if prompt_text and prompt_text not in (PORTAL, "进入传送门", "离开圣地"):
                    self._ignore_target(prompt_text, until, pos=pos)
            self._interacted = None
            self._temp_target = None
            return []
        if spam_e and now - last_pressed >= INTERACT_RETRY_S:
            if last_pressed == 0.0:
                log.info("at %s: pressing E", name)
                if name == BOSS or "守护者" in name:
                    log.info("area boss summoned: it chases us, so keep moving and leave the altars")
                    self._boss_fight = True
            self._interacted = (name, started, now)
            return [Press(INTERACT_KEY)]
        return []

    def _explore(self, observation: Observation, now: float) -> frozenset[str]:
        """Nothing on the minimap: hold Tab and head for the best target on the zone map, else the
        nearest unvisited cell, turning the north-up bearing into minimap-up WASD."""
        zone = observation.zonemap
        if zone:
            self._visited.add(_cell(zone.player))
            candidates = self._candidates([(ALTAR, p) for p in zone.altars] + list(zone.targets), now)
            if candidates:
                self._target, target = self._best(candidates, zone.player, scale=1.0)
            else:
                target = self._nearest_unvisited(zone.player)
            dx, dy = target[0] - zone.player[0], target[1] - zone.player[1]
            self._heading = math.degrees(math.atan2(dx, -dy))
        if self._heading is None or observation.north is None:
            return frozenset({MAP_KEY})
        self._bearing = observation.north + self._heading
        return _direction(self._bearing) | {MAP_KEY}

    def _unstick(
        self, keys: frozenset[str], observation: Observation, now: float, distance: float | None
    ) -> frozenset[str]:
        """Walking without progress for `stuck_s`: step left (then right, alternating) for `sidestep_s`.
        Progress is getting closer to the minimap target (`distance`), else moving on the zone map."""
        if self._sidestep:
            sidestep, until = self._sidestep
            if now < until:
                return sidestep | (keys & {MAP_KEY})
            self._sidestep, self._progress = None, None
        if not keys - {MAP_KEY} or self._bearing is None:
            self._progress = None
            return keys
        if distance is not None:
            mark: object = distance
            progressed = lambda last: last - mark >= ALTAR_PROGRESS_PX  # noqa: E731
        elif observation.zonemap:
            mark = observation.zonemap.player
            progressed = lambda last: _distance(last, mark) >= ZONE_PROGRESS  # noqa: E731
        else:
            return keys
        if self._progress is None or type(self._progress[0]) is not type(mark) or progressed(self._progress[0]):
            self._progress = (mark, now)
            return keys
        if now - self._progress[1] < self._movement.stuck_s:
            return keys
        side = -90 if self._sidestep_left else 90
        self._sidestep_left = not self._sidestep_left
        sidestep = _direction(self._bearing + side)
        log.info("stuck for %g s: sidestepping %s", self._movement.stuck_s, "left" if side < 0 else "right")
        self._sidestep = (sidestep, now + self._movement.sidestep_s)
        return sidestep | (keys & {MAP_KEY})

    def _nearest_unvisited(self, player: Position) -> Position:
        inner = [(col, row) for col in range(1, GRID - 1) for row in range(1, GRID - 1)]
        unvisited = [cell for cell in inner if cell not in self._visited]
        if not unvisited:
            log.info("whole zone explored: starting over")
            self._visited = {_cell(player)}
            unvisited = [cell for cell in inner if cell not in self._visited]
        centres = [((col + 0.5) / GRID, (row + 0.5) / GRID) for col, row in unvisited]
        return min(centres, key=lambda centre: _distance(player, centre))

    def _jump(self, now: float) -> list[Command]:
        if self._next_jump is None:
            self._next_jump = now + self._movement.rng.uniform(*self._movement.jump_interval_s)
            return []
        if now < self._next_jump:
            return []
        self._next_jump = now + self._movement.rng.uniform(*self._movement.jump_interval_s)
        return [Press(JUMP_KEY)]

    def _close_team_view(self, now: float) -> list[Command]:
        """Letting go of Tab while a choice popup is open (it came up mid-exploration) opens the
        team view over it. Tab goes back to the choice."""
        team_state = (TEAM_VIEW, (), False)
        if self._answered and self._answered[0] == team_state and now - self._answered[1] < POPUP_RETRY_S:
            return []
        self._answered = (team_state, now)
        log.info("team view open over the popup: Tab back to the choice")
        return [ReleaseAll(), Press(MAP_KEY)]

    def _answer(self, popup: Popup, now: float) -> list[Command]:
        popup_state = (popup.title, tuple(c.name for c in popup.cards), popup.in_banish)
        if self._answered and self._answered[0] == popup_state and now - self._answered[1] < POPUP_RETRY_S:
            return []
        self._answered = (popup_state, now)
        action = self._choose(popup)
        if action is None:
            return [ReleaseAll(), Pause(f"unknown popup: {popup.title}")]
        return [ReleaseAll(), action]

    def _choose(self, popup: Popup) -> Press | Click | None:
        keyed = [card for card in popup.cards if card.key]
        if keyed:
            if popup.in_banish:
                banishable = [c for c in keyed if not c.is_locked_move]
                if banishable:
                    target = min(banishable, key=lambda c: self._cards.weight(c.name))
                    log.info("%s [banish mode] -> banished [%s] %s", popup.title, target.key, target.name)
                    return Press(target.key)
                cancel = next((b for b in popup.buttons if b.text == "取消"), None)
                if cancel:
                    return Press(_key(cancel.key)) if cancel.key else Click(cancel.text)
                return Press("Escape")

            if self._banish_threshold is not None and popup.banishes > 0:
                trash = [
                    c for c in keyed
                    if not c.is_locked_move and self._cards.weight(c.name) <= self._banish_threshold
                ]
                if trash:
                    banish_btn = next((b for b in popup.buttons if BANISH_RE.search(b.text)), None)
                    key = _key(banish_btn.key) if banish_btn and banish_btn.key else "z"
                    log.info(
                        "%s -> banish (%s offered with weight <= %g, %d left)",
                        popup.title,
                        ", ".join(f"{c.name} ({self._cards.weight(c.name)})" for c in trash),
                        self._banish_threshold,
                        popup.banishes,
                    )
                    return Press(key)

            card = self._cards.best(keyed)
            best_weight = self._cards.weight(card.name)

            if self._reroll_threshold is None or best_weight > self._reroll_threshold:
                offered = " | ".join(f"[{c.key}] {c.name} ({c.rarity})" for c in keyed)
                log.info("%s %s -> picked [%s] %s", popup.title, offered, card.key, card.name)
                return Press(card.key)

            if popup.rerolls > 0:
                reroll_btn = next((b for b in popup.buttons if REROLL_RE.search(b.text)), None)
                key = _key(reroll_btn.key) if reroll_btn and reroll_btn.key else "f"
                log.info(
                    "%s -> reroll (best [%s] %s has weight %g <= %g, %d left)",
                    popup.title,
                    card.key,
                    card.name,
                    best_weight,
                    self._reroll_threshold,
                    popup.rerolls,
                )
                return Press(key)

            if self._skip_threshold is not None and best_weight < self._skip_threshold and popup.skips > 0:
                skip_btn = next((b for b in popup.buttons if SKIP_RE.search(b.text)), None)
                key = _key(skip_btn.key) if skip_btn and skip_btn.key else "x"
                log.info(
                    "%s -> skip (all cards negative, best [%s] %s has weight %g < %g, %d left)",
                    popup.title,
                    card.key,
                    card.name,
                    best_weight,
                    self._skip_threshold,
                    popup.skips,
                )
                return Press(key)

            offered = " | ".join(f"[{c.key}] {c.name} ({c.rarity})" for c in keyed)
            log.info("%s %s -> picked [%s] %s", popup.title, offered, card.key, card.name)
            return Press(card.key)
        buttons = {button.text: button for button in popup.buttons}
        pick_up = buttons.get(PICK_UP_BUTTON)
        if pick_up and pick_up.key:
            log.info("%s %s -> pick up", popup.title, ", ".join(c.name for c in popup.cards))
            return Press(_key(pick_up.key))
        if popup.title.startswith(DITTO_TITLE) and popup.cards:
            card = self._cards.best(popup.cards)
            log.info("%s %s -> copy %s", popup.title, " | ".join(c.name for c in popup.cards), card.name)
            return Click(card.name)
        if READY_BUTTON in buttons:
            log.info("%s -> %s (nothing forgotten)", popup.title, READY_BUTTON)
            return Click(READY_BUTTON)
        leave = next((buttons[text] for text in LEAVE_BUTTONS if text in buttons), None)
        if leave:
            log.info("%s -> leave (%s)", popup.title or "untitled popup", leave.text)
            return Press(_key(leave.key)) if leave.key else Click(leave.text)
        return None

    def _log_state_change(self, observation: Observation) -> None:
        state = observation.end_screen or ("playing" if observation.recognised else "unrecognised")
        if state != self._last_state:
            log.info("state: %s%s", state, f" (countdown {observation.countdown})" if observation.countdown else "")
            self._last_state = state


def _direction(bearing: float) -> frozenset[str]:
    """WASD for a minimap bearing (degrees clockwise from minimap-up), to the nearest 45 degrees."""
    return frozenset(DIRECTION_KEYS[round((90 - bearing) / 45) % 8])


def _cell(position: Position) -> tuple[int, int]:
    return min(int(position[0] * GRID), GRID - 1), min(int(position[1] * GRID), GRID - 1)


def _distance(a: Position, b: Position) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _key(cap: str) -> str:
    """Single letters are sent lower-case so no Shift is implied."""
    return KEY_NAMES.get(cap, cap.lower() if len(cap) == 1 else cap)
