"""The bot: `Bot.step(frame) -> commands`, the one seam between perception/policy and the driver."""

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Protocol

from autobonk.cards import CardPrefs
from autobonk.frames import Frame
from autobonk.perception import LEAVE_BUTTONS, Observation, Popup, perceive
from autobonk.zonemap import Position

log = logging.getLogger(__name__)

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
# Closer than this (minimap pixels) the player is in the altar's ring: stop walking.
ALTAR_ARRIVED_PX = 14
MAP_KEY = "Tab"  # held while exploring: the zone map shows, the game keeps running
GRID = 8  # the zone is explored as GRID x GRID cells; edge cells are never targets
ALTAR_PROGRESS_PX = 3  # getting this much closer to an altar (minimap pixels) counts as progress
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


class Uniform(Protocol):
    def uniform(self, a: float, b: float) -> float: ...


@dataclass(frozen=True)
class Movement:
    jump_interval_s: tuple[float, float] = (0.8, 1.4)
    altar_charge_cap_s: float = 45.0
    altar_ignore_s: float = 60.0  # after the cap, explore elsewhere this long before coming back
    stuck_s: float = 2.5  # no progress toward the target this long: sidestep
    sidestep_s: float = 0.6
    rng: Uniform = field(default_factory=random.Random)


class Bot:
    def __init__(
        self, unknown_screen_pause_s: float = 5.0, cards: CardPrefs = CardPrefs(), movement: Movement | None = None
    ):
        self._unknown_screen_pause_s = unknown_screen_pause_s
        self._cards = cards
        self._movement = movement or Movement()
        self._held: frozenset[str] = frozenset()
        self._next_jump: float | None = None
        self._charging_since: float | None = None
        self._altars_ignored_until = 0.0  # altars sealed or outlasting the charge cap: explore meanwhile
        self._zone: str | None = None
        self._visited: set[tuple[int, int]] = set()  # zone-map cells the player has been in
        self._heading: float | None = None  # exploring toward this compass bearing (north-up)
        self._bearing: float | None = None  # minimap bearing being walked
        self._progress: tuple[object, float] | None = None  # (last progress mark, when)
        self._sidestep: tuple[frozenset[str], float] | None = None  # (keys, until)
        self._sidestep_left = True
        self._unrecognised_since: float | None = None
        self._last_state: str | None = None
        self._answered: tuple[str, float] | None = None  # (popup title, when)

    def step(self, frame: Frame) -> list[Command]:
        observation = perceive(frame)
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
            return self._release(self._answer(observation.popup, frame.timestamp))

        if observation.countdown:
            self._unrecognised_since = None
            return self._move(observation, frame.timestamp) + self._jump(frame.timestamp)

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
        """Walk to the nearest rune altar; stand in its ring while it charges (up to the cap).
        Sealed altars, and ones still charging at the cap, are left for a while to explore."""
        ignored = now < self._altars_ignored_until
        if observation.sealed_s is not None and not ignored:
            log.info("altar sealed for %d s: exploring meanwhile", observation.sealed_s)
            self._altars_ignored_until = now + observation.sealed_s
        if observation.charging:
            if self._charging_since is None:
                self._charging_since = now
            if now - self._charging_since > self._movement.altar_charge_cap_s and not ignored:
                log.info("altar still charging after %g s: moving on", self._movement.altar_charge_cap_s)
                self._altars_ignored_until = now + self._movement.altar_ignore_s
        else:
            self._charging_since = None
        ignored = now < self._altars_ignored_until

        keys: frozenset[str] = frozenset()
        if ignored:
            keys = self._explore(observation, altars=False)
        elif observation.charging:
            pass
        elif observation.altars:
            x, y = observation.altars[0]
            if math.hypot(x, y) > ALTAR_ARRIVED_PX:
                self._bearing = math.degrees(math.atan2(x, -y))
                keys = _direction(self._bearing)
        else:
            keys = self._explore(observation)
        keys = self._unstick(keys, observation, now, altars=not ignored)
        if keys == self._held:
            return []
        self._held = keys
        return [Hold(keys)]

    def _explore(self, observation: Observation, altars: bool = True) -> frozenset[str]:
        """Nothing on the minimap: hold Tab and head for a discovered altar on the zone map
        (unless `altars` is off), else the nearest unvisited cell, turning the north-up
        bearing into minimap-up WASD."""
        if observation.zone != self._zone:
            self._zone, self._visited, self._heading = observation.zone, set(), None
        zone = observation.zonemap
        if zone:
            self._visited.add(_cell(zone.player))
            target = min(zone.altars if altars else (), key=lambda a: _distance(zone.player, a), default=None)
            if target is None:
                target = self._nearest_unvisited(zone.player)
            dx, dy = target[0] - zone.player[0], target[1] - zone.player[1]
            self._heading = math.degrees(math.atan2(dx, -dy))
        if self._heading is None or observation.north is None:
            return frozenset({MAP_KEY})
        self._bearing = observation.north + self._heading
        return _direction(self._bearing) | {MAP_KEY}

    def _unstick(self, keys: frozenset[str], observation: Observation, now: float, altars: bool = True) -> frozenset[str]:
        """Walking without progress for `stuck_s`: step left (then right, alternating) for `sidestep_s`."""
        if self._sidestep:
            sidestep, until = self._sidestep
            if now < until:
                return sidestep | (keys & {MAP_KEY})
            self._sidestep, self._progress = None, None
        if not keys - {MAP_KEY} or self._bearing is None:
            self._progress = None
            return keys
        if observation.altars and altars:
            mark: object = math.hypot(*observation.altars[0])
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
        if self._answered and self._answered[0] == TEAM_VIEW and now - self._answered[1] < POPUP_RETRY_S:
            return []
        self._answered = (TEAM_VIEW, now)
        log.info("team view open over the popup: Tab back to the choice")
        return [ReleaseAll(), Press(MAP_KEY)]

    def _answer(self, popup: Popup, now: float) -> list[Command]:
        if self._answered and self._answered[0] == popup.title and now - self._answered[1] < POPUP_RETRY_S:
            return []
        self._answered = (popup.title, now)
        action = self._choose(popup)
        if action is None:
            return [ReleaseAll(), Pause(f"unknown popup: {popup.title}")]
        return [ReleaseAll(), action]

    def _choose(self, popup: Popup) -> Press | Click | None:
        keyed = [card for card in popup.cards if card.key]
        if keyed:
            card = self._cards.best(keyed)
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
