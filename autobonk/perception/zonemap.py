"""Reads the floating zone map (canvas.bm-cv, 738x738, north-up), shown only while Tab is held."""

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from autobonk.perception.icons import find_targets
from autobonk.perception.matching import (
    find_icons,
    load_rgb,
)
from autobonk.perception.minimap import ALTAR_MATCH, ALTAR_TEMPLATE

BORDER = (28, 709)  # the dashed zone border, in canvas pixels
PLAYER_COLOUR = (255, 225, 74)  # the yellow player arrow
PLAYER_TOLERANCE = 30
PLAYER_WINDOW = 24  # the arrow fits in this square
ICON_STEP = 2

Position = tuple[float, float]


@dataclass(frozen=True)
class ZoneMap:
    player: Position
    altars: tuple[Position, ...]  # discovered rune altars
    targets: tuple[tuple[str, Position], ...] = ()  # other icons asked for, by name


def read_zonemap(png: bytes, targets: Sequence[str] = ()) -> ZoneMap | None:
    """Read player position, altars, and targets from zone map PNG."""
    if not png:
        return None
    image = load_rgb(png)
    player = _player(image)
    if player is None:
        return None
    altars = tuple(_position(x, y) for x, y in find_icons(image, ALTAR_TEMPLATE, ALTAR_MATCH, ICON_STEP))
    found = tuple((name, _position(x, y)) for name, (x, y) in find_targets(image, targets))
    return ZoneMap(player, altars, found)


def _player(image: np.ndarray) -> Position | None:
    """Centre of the densest patch of arrow-yellow pixels."""
    yellow = (np.abs(image - PLAYER_COLOUR).sum(axis=2) < PLAYER_TOLERANCE).astype(np.float64)
    w = PLAYER_WINDOW
    sums = np.pad(yellow.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    counts = sums[w:, w:] - sums[:-w, w:] - sums[w:, :-w] + sums[:-w, :-w]
    y, x = np.unravel_index(counts.argmax(), counts.shape)
    if counts[y, x] < w:
        return None
    patch_ys, patch_xs = np.nonzero(yellow[y:y + w, x:x + w])
    return _position(x + patch_xs.mean(), y + patch_ys.mean())


def _position(x: float, y: float) -> Position:
    low, high = BORDER
    return (x - low) / (high - low), (y - low) / (high - low)
