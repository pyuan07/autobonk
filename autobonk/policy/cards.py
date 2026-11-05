"""Card scoring and preference definitions."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from autobonk.game import Card

DEFAULT_RARITY_ORDER = ("传说", "稀有", "少见", "普通")

# Stat blessings read "+38% 伤害", "+63 最大 HP", "+1.2 再生": a number that changes every run, then the stat.
_BLESSING = re.compile(r"^\+\s*\d+(?:\.\d+)?\s*%?\s*(\S.*)$")


def blessing_key(name: str) -> str | None:
    """"+38% 伤害" -> "+伤害", so one weight covers a stat whatever its roll. None if not a stat blessing."""
    match = _BLESSING.match(name.strip())
    return "+" + _compact(match.group(1)) if match else None


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


@dataclass(frozen=True)
class CardPrefs:
    weights: Mapping[str, float] = field(default_factory=dict)
    rarity_order: tuple[str, ...] = DEFAULT_RARITY_ORDER
    _stat_weights: dict[str, float] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        stats = {_compact(k): v for k, v in self.weights.items() if k.startswith("+") and blessing_key(k) is None}
        object.__setattr__(self, "_stat_weights", stats)

    def best(self, cards: Sequence[Card]) -> Card:
        """Choose the best card according to plan and weight preferences:
        - If any card is in_plan and all non-plan cards have weight < 9:
          plan cards win, picking the highest (weight, rarity) among plan cards.
        - Otherwise (no plan cards, or any non-plan card has weight >= 9):
          highest (weight, rarity) among all cards.
        Unlisted names weigh 0; ties go to the leftmost card.
        """
        if not cards:
            raise ValueError("cards must not be empty")
        has_plan = any(c.in_plan for c in cards)
        if has_plan:
            has_high_non_plan = any(not c.in_plan and self.weight(c.name) >= 9.0 for c in cards)
            if not has_high_non_plan:
                return max((c for c in cards if c.in_plan), key=self._score)
        return max(cards, key=self._score)

    def weight(self, name: str) -> float:
        """A blessing ("+38% 伤害") weighs as its stat ("+伤害"); any other card by its exact name; else 0."""
        key = blessing_key(name)
        if key:
            return self._stat_weights.get(key, 0.0)
        return self.weights.get(name, 0.0)

    def _score(self, card: Card) -> tuple[float, int]:
        order = self.rarity_order
        rank = len(order) - order.index(card.rarity) if card.rarity in order else 0
        return self.weight(card.name), rank
