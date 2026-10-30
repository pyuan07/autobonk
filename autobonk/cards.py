"""Card scoring, shared by every choice popup (level-up, item choice, Snorlax blessing, Ditto copy)."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

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
class Card:
    key: str
    name: str
    rarity: str
    details: tuple[str, ...] = field(default=(), compare=False)  # effect text, for logs only

    @property
    def is_locked_move(self) -> bool:
        """True if banishing this card would permanently lock an owned move at its current level."""
        return any("不会再升级" in d for d in self.details)


@dataclass(frozen=True)
class CardPrefs:
    # Card name exactly as shown in the game -> weight. Positive = prefer, negative = avoid.
    # "+伤害" style keys weigh every stat blessing of that stat ("+14% 伤害", "+38% 伤害", ...).
    weights: Mapping[str, float] = field(default_factory=dict)
    # Best first. Rarities not listed rank below all listed ones.
    rarity_order: tuple[str, ...] = DEFAULT_RARITY_ORDER
    _stat_weights: dict[str, float] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Blessings weigh by stat only; a roll-specific key ("+38% 伤害") is ignored.
        stats = {_compact(k): v for k, v in self.weights.items() if k.startswith("+") and blessing_key(k) is None}
        object.__setattr__(self, "_stat_weights", stats)

    def best(self, cards: Sequence[Card]) -> Card:
        """Highest (weight, rarity rank); unlisted names weigh 0; ties go to the leftmost card."""
        return max(cards, key=self._score)  # max keeps the first of equal scores

    def weight(self, name: str) -> float:
        """A blessing ("+38% 伤害") weighs as its stat ("+伤害"); any other card by its exact name; else 0."""
        key = blessing_key(name)
        if key:
            return self._stat_weights.get(key, 0)
        return self.weights.get(name, 0)

    def _score(self, card: Card) -> tuple[float, int]:
        order = self.rarity_order
        rank = len(order) - order.index(card.rarity) if card.rarity in order else 0
        return self.weight(card.name), rank
