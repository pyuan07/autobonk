"""The bot: `Bot.step(frame) -> commands`, the one seam between perception/policy and the driver."""

import logging
from dataclasses import dataclass

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


Command = ReleaseAll | Stop | Pause | Press | Click


class Bot:
    def __init__(self, unknown_screen_pause_s: float = 5.0, cards: CardPrefs = CardPrefs()):
        self._unknown_screen_pause_s = unknown_screen_pause_s
        self._cards = cards
        self._unrecognised_since: float | None = None
        self._last_state: str | None = None
        self._answered: tuple[str, float] | None = None  # (popup title, when)

    def step(self, frame: Frame) -> list[Command]:
        observation = perceive(frame)
        self._log_state_change(observation)

        if observation.end_screen:
            return [ReleaseAll(), Stop(observation.end_screen)]

        if observation.popup:
            self._unrecognised_since = None
            return self._answer(observation.popup, frame.timestamp)

        if observation.recognised:
            self._unrecognised_since = None
            return []

        if self._unrecognised_since is None:
            self._unrecognised_since = frame.timestamp
        if frame.timestamp - self._unrecognised_since >= self._unknown_screen_pause_s:
            self._unrecognised_since = None
            return [ReleaseAll(), Pause(f"screen unrecognised for {self._unknown_screen_pause_s:g} s")]
        return []

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
