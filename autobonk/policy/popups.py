"""Policy for answering choice popups, modals, and team view."""

import logging
from typing import Sequence

from autobonk.commands import Click, Command, Pause, Press, ReleaseAll
from autobonk.game import (
    DITTO_TITLE,
    KEY_NAMES,
    MAP_KEY,
    PICK_UP_BUTTON,
    POPUP_RETRY_S,
    READY_BUTTON,
    TEAM_VIEW,
)
from autobonk.perception.dom import (
    BANISH_RE,
    LEAVE_BUTTONS,
    Popup,
    REROLL_RE,
    SKIP_RE,
)
from autobonk.policy.cards import Card, CardPrefs

log = logging.getLogger(__name__)


def key_name(cap: str) -> str:
    """Single letters are sent lower-case so no Shift is implied."""
    return KEY_NAMES.get(cap, cap.lower() if len(cap) == 1 else cap)


class PopupPolicy:
    def __init__(
        self,
        cards: CardPrefs,
        banish_threshold: float | None = -5.0,
        reroll_threshold: float | None = 0.0,
        skip_threshold: float | None = 0.0,
    ):
        self.cards = cards
        self.banish_threshold = banish_threshold
        self.reroll_threshold = reroll_threshold
        self.skip_threshold = skip_threshold
        self._answered: tuple[object, float] | None = None

    def close_team_view(self, now: float) -> list[Command]:
        """Letting go of Tab while a choice popup is open opens the team view.
        Tab goes back to the choice."""
        team_state = (TEAM_VIEW, (), False)
        if self._answered and self._answered[0] == team_state and now - self._answered[1] < POPUP_RETRY_S:
            return []
        self._answered = (team_state, now)
        log.info("team view open over the popup: Tab back to the choice")
        return [ReleaseAll(), Press(MAP_KEY)]

    def answer(self, popup: Popup, now: float) -> list[Command]:
        """Answer an open popup. If the key was missed after POPUP_RETRY_S, try again."""
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
            return self._choose_keyed(popup, keyed)

        buttons = {button.text: button for button in popup.buttons}
        pick_up = buttons.get(PICK_UP_BUTTON)
        if pick_up and pick_up.key:
            log.info("%s %s -> pick up", popup.title, ", ".join(c.name for c in popup.cards))
            return Press(key_name(pick_up.key))

        if popup.title.startswith(DITTO_TITLE) and popup.cards:
            card = self.cards.best(popup.cards)
            log.info("%s %s -> copy %s", popup.title, " | ".join(c.name for c in popup.cards), card.name)
            return Click(card.name)

        if READY_BUTTON in buttons:
            log.info("%s -> %s (nothing forgotten)", popup.title, READY_BUTTON)
            return Click(READY_BUTTON)

        leave = next((buttons[text] for text in LEAVE_BUTTONS if text in buttons), None)
        if leave:
            log.info("%s -> leave (%s)", popup.title or "untitled popup", leave.text)
            return Press(key_name(leave.key)) if leave.key else Click(leave.text)

        return None

    def _choose_keyed(self, popup: Popup, keyed: Sequence[Card]) -> Press | Click | None:
        if popup.in_banish:
            banishable = [c for c in keyed if not c.is_locked_move]
            if banishable:
                target = min(banishable, key=lambda c: self.cards.weight(c.name))
                log.info("%s [banish mode] -> banished [%s] %s", popup.title, target.key, target.name)
                return Press(target.key)
            cancel = next((b for b in popup.buttons if b.text == "取消"), None)
            if cancel:
                return Press(key_name(cancel.key)) if cancel.key else Click(cancel.text)
            return Press("Escape")

        if self.banish_threshold is not None and popup.banishes > 0:
            trash = [c for c in keyed if not c.is_locked_move and self.cards.weight(c.name) <= self.banish_threshold]
            if trash:
                banish_btn = next((b for b in popup.buttons if BANISH_RE.search(b.text)), None)
                key = key_name(banish_btn.key) if banish_btn and banish_btn.key else "z"
                log.info(
                    "%s -> banish (%s offered with weight <= %g, %d left)",
                    popup.title,
                    ", ".join(f"{c.name} ({self.cards.weight(c.name)})" for c in trash),
                    self.banish_threshold,
                    popup.banishes,
                )
                return Press(key)

        card = self.cards.best(keyed)
        best_weight = self.cards.weight(card.name)

        if self.reroll_threshold is None or best_weight > self.reroll_threshold:
            offered = " | ".join(f"[{c.key}] {c.name} ({c.rarity})" for c in keyed)
            log.info("%s %s -> picked [%s] %s", popup.title, offered, card.key, card.name)
            return Press(card.key)

        if popup.rerolls > 0:
            reroll_btn = next((b for b in popup.buttons if REROLL_RE.search(b.text)), None)
            key = key_name(reroll_btn.key) if reroll_btn and reroll_btn.key else "f"
            log.info(
                "%s -> reroll (best [%s] %s has weight %g <= %g, %d left)",
                popup.title,
                card.key,
                card.name,
                best_weight,
                self.reroll_threshold,
                popup.rerolls,
            )
            return Press(key)

        if self.skip_threshold is not None and best_weight < self.skip_threshold and popup.skips > 0:
            skip_btn = next((b for b in popup.buttons if SKIP_RE.search(b.text)), None)
            key = key_name(skip_btn.key) if skip_btn and skip_btn.key else "x"
            log.info(
                "%s -> skip (all cards negative, best [%s] %s has weight %g < %g, %d left)",
                popup.title,
                card.key,
                card.name,
                best_weight,
                self.skip_threshold,
                popup.skips,
            )
            return Press(key)

        offered = " | ".join(f"[{c.key}] {c.name} ({c.rarity})" for c in keyed)
        log.info("%s %s -> picked [%s] %s", popup.title, offered, card.key, card.name)
        return Press(card.key)
