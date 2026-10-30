"""The bot: `Bot.step(frame) -> commands`, the one seam between perception/policy and the driver."""

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Protocol

from autobonk.cards import CardPrefs
from autobonk.frames import Frame
from autobonk.perception import LEAVE_BUTTONS, Observation, Popup, perceive

log = logging.getLogger(__name__)

# If a popup is still open this long after answering it, the key was missed: press again.
POPUP_RETRY_S = 1.0
PICK_UP_BUTTON = "拾取"  # item pickup; its neighbour 出售 (sell) is never used
READY_BUTTON = "就绪"  # Hypno: close without forgetting a move
DITTO_TITLE = "百变怪"
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
        self._altars_ignored = False  # an altar outlasted the charge cap; ignored until its bubble goes
        self._unrecognised_since: float | None = None
        self._last_state: str | None = None
        self._answered: tuple[str, float] | None = None  # (popup title, when)

    def step(self, frame: Frame) -> list[Command]:
        observation = perceive(frame)
        self._log_state_change(observation)

        if observation.end_screen:
            return self._release([ReleaseAll(), Stop(observation.end_screen)])

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
        """Walk to the nearest rune altar; stand in its ring while it charges (up to the cap)."""
        if observation.charging:
            if self._charging_since is None:
                self._charging_since = now
            if now - self._charging_since > self._movement.altar_charge_cap_s and not self._altars_ignored:
                log.info("altar still charging after %g s: moving on", self._movement.altar_charge_cap_s)
                self._altars_ignored = True
        else:
            self._charging_since = None
            self._altars_ignored = False

        keys: frozenset[str] = frozenset()
        if self._altars_ignored:
            keys = self._held
        elif observation.altars and not observation.charging:
            x, y = observation.altars[0]
            if math.hypot(x, y) > ALTAR_ARRIVED_PX:
                sector = round(math.degrees(math.atan2(-y, x)) / 45) % 8
                keys = frozenset(DIRECTION_KEYS[sector])
        if keys == self._held:
            return []
        self._held = keys
        return [Hold(keys)]

    def _jump(self, now: float) -> list[Command]:
        if self._next_jump is None:
            self._next_jump = now + self._movement.rng.uniform(*self._movement.jump_interval_s)
            return []
        if now < self._next_jump:
            return []
        self._next_jump = now + self._movement.rng.uniform(*self._movement.jump_interval_s)
        return [Press(JUMP_KEY)]

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


def _key(cap: str) -> str:
    """Single letters are sent lower-case so no Shift is implied."""
    return KEY_NAMES.get(cap, cap.lower() if len(cap) == 1 else cap)
