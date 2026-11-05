"""Policy for answering choice popups, modals, and team view."""

import logging
from collections.abc import Sequence

from autobonk.commands import Click, Command, Pause, Press, ReleaseAll
from autobonk.game import (
    BANISH_CANCEL_BUTTON,
    DITTO_TITLE,
    HYPNO_TITLE,
    KEY_NAMES,
    MAP_KEY,
    PICK_UP_BUTTON,
    POPUP_RETRY_S,
    READY_BUTTON,
    RELEASE_NEWCOMER,
    TEAM_VIEW,
    UNCHANGED,
    Unchanged,
)
from autobonk.perception.dom import (
    BANISH_RE,
    LEAVE_BUTTONS,
    REROLL_RE,
    SKIP_RE,
    Popup,
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
        plan_fallback_reroll_threshold: float | None = None,
    ):
        self.cards = cards
        self.banish_threshold = banish_threshold
        self.reroll_threshold = reroll_threshold
        self.skip_threshold = skip_threshold
        self.plan_fallback_reroll_threshold = plan_fallback_reroll_threshold
        self._answered: tuple[object, float] | None = None
        self.last_was_leave: bool = False

    def reset(self) -> None:
        self._answered = None
        self.last_was_leave = False

    def reload_config(
        self,
        cards: CardPrefs | Unchanged = UNCHANGED,
        banish_threshold: float | None | Unchanged = UNCHANGED,
        reroll_threshold: float | None | Unchanged = UNCHANGED,
        skip_threshold: float | None | Unchanged = UNCHANGED,
        plan_fallback_reroll_threshold: float | None | Unchanged = UNCHANGED,
    ) -> None:
        """UNCHANGED keeps a value; None disables a threshold."""
        if cards is not UNCHANGED:
            self.cards = cards
        if banish_threshold is not UNCHANGED:
            self.banish_threshold = banish_threshold
        if reroll_threshold is not UNCHANGED:
            self.reroll_threshold = reroll_threshold
        if skip_threshold is not UNCHANGED:
            self.skip_threshold = skip_threshold
        if plan_fallback_reroll_threshold is not UNCHANGED:
            self.plan_fallback_reroll_threshold = plan_fallback_reroll_threshold

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
        action, is_leave = self._choose(popup)
        self.last_was_leave = is_leave
        if action is None:
            return [ReleaseAll(), Pause(f"unknown popup: {popup.title}")]
        return [ReleaseAll(), action]

    def _choose(self, popup: Popup) -> tuple[Press | Click | None, bool]:
        keyed = [card for card in popup.cards if card.key]
        if keyed:
            return self._choose_keyed(popup, keyed), False

        buttons = {button.text: button for button in popup.buttons}
        pick_up = buttons.get(PICK_UP_BUTTON)
        if pick_up and pick_up.key:
            log.info("%s %s -> pick up", popup.title, ", ".join(c.name for c in popup.cards))
            return Press(key_name(pick_up.key)), False

        if (
            any(any(RELEASE_NEWCOMER in d for d in c.details) or c.name == RELEASE_NEWCOMER for c in popup.cards)
            or any(b.text == RELEASE_NEWCOMER for b in popup.buttons)
        ):
            log.info("%s -> %s (team full, dismiss newcomer)", popup.title, RELEASE_NEWCOMER)
            return Click(RELEASE_NEWCOMER), False

        if popup.title.startswith(DITTO_TITLE) and popup.cards:
            selectable = [c for c in popup.cards if not c.is_maxed]
            if selectable:
                card = self.cards.best(selectable)
                log.info("%s %s -> copy %s", popup.title, " | ".join(c.name for c in selectable), card.name)
                return Click(card.name), False

        if popup.title.startswith(HYPNO_TITLE) or (READY_BUTTON in buttons and popup.forget_moves):
            moves = popup.forget_moves
            if len(moves) > 1:
                negative_moves = [m for m in moves if self.cards.weight(m.name) <= -1.0]
                if negative_moves:
                    target_move = min(negative_moves, key=lambda m: self.cards.weight(m.name))
                    log.info("%s -> forget %s (weight %g)", popup.title, target_move.name, self.cards.weight(target_move.name))
                    return Click(f"忘记: {target_move.name}", selector=f'.item-row:has-text("{target_move.name}") button'), False
            log.info("%s -> %s (nothing forgotten, %d moves)", popup.title, READY_BUTTON, len(moves))
            return Click(READY_BUTTON), True

        if READY_BUTTON in buttons:
            log.info("%s -> %s (nothing forgotten)", popup.title, READY_BUTTON)
            return Click(READY_BUTTON), True

        leave = next((buttons[text] for text in LEAVE_BUTTONS if text in buttons), None)
        if leave:
            log.info("%s -> leave (%s)", popup.title or "untitled popup", leave.text)
            action = Press(key_name(leave.key)) if leave.key else Click(leave.text)
            return action, True

        return None, False

    def _choose_keyed(self, popup: Popup, keyed: Sequence[Card]) -> Press | Click | None:
        if popup.in_banish:
            banishable = [c for c in keyed if not c.is_locked_move and not c.in_plan]
            if banishable:
                target = min(banishable, key=lambda c: self.cards.weight(c.name))
                log.info("%s [banish mode] -> banished [%s] %s", popup.title, target.key, target.name)
                return Press(target.key)
            cancel = next((b for b in popup.buttons if b.text == BANISH_CANCEL_BUTTON), None)
            if cancel:
                return Press(key_name(cancel.key)) if cancel.key else Click(cancel.text)
            return Press("Escape")

        if self.banish_threshold is not None and popup.banishes > 0:
            trash = [c for c in keyed if not c.is_locked_move and not c.in_plan and self.cards.weight(c.name) <= self.banish_threshold]
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

        has_plan = any(c.in_plan for c in keyed)
        should_reroll = False
        if not card.in_plan:
            if not has_plan and self.plan_fallback_reroll_threshold is not None:
                if best_weight < self.plan_fallback_reroll_threshold and popup.rerolls > 0:
                    should_reroll = True
            elif self.reroll_threshold is not None and best_weight <= self.reroll_threshold and popup.rerolls > 0:
                should_reroll = True

        if should_reroll:
            reroll_btn = next((b for b in popup.buttons if REROLL_RE.search(b.text)), None)
            key = key_name(reroll_btn.key) if reroll_btn and reroll_btn.key else "f"
            log.info(
                "%s -> reroll (best [%s] %s has weight %g, plan=%s, %d left)",
                popup.title,
                card.key,
                card.name,
                best_weight,
                has_plan,
                popup.rerolls,
            )
            return Press(key)

        if not card.in_plan and self.skip_threshold is not None and best_weight < self.skip_threshold and popup.skips > 0:
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
