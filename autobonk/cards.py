"""Card scoring, shared by every choice popup (level-up, item choice, Snorlax blessing, Ditto copy)."""

from collections.abc import Sequence
from dataclasses import dataclass, field

DEFAULT_RARITY_ORDER = ("传说", "稀有", "少见", "普通")


@dataclass(frozen=True)
class Card:
    key: str
    name: str
    rarity: str


@dataclass(frozen=True)
class CardPrefs:
    # Card name exactly as shown in the game -> weight. Positive = prefer, negative = avoid.
    weights: dict[str, float] = field(default_factory=dict)
    # Best first. Rarities not listed rank below all listed ones.
    rarity_order: tuple[str, ...] = DEFAULT_RARITY_ORDER

    def best(self, cards: Sequence[Card]) -> Card:
        """Highest (weight, rarity rank); unlisted names weigh 0; ties go to the leftmost card."""
        return max(cards, key=self._score)  # max keeps the first of equal scores

    def _score(self, card: Card) -> tuple[float, int]:
        order = self.rarity_order
        rank = len(order) - order.index(card.rarity) if card.rarity in order else 0
        return self.weights.get(card.name, 0), rank
