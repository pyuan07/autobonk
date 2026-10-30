"""Reads the floating zone map (canvas.bm-cv, 738x738, north-up), shown only while Tab is held.

Positions are fractions of the zone (0..1, x east and y south) inside its dashed border.
"""

from dataclasses import dataclass

import numpy as np

from autobonk.icons import find_targets
from autobonk.minimap import ALTAR_MATCH, ALTAR_TEMPLATE, find_icons, load_rgb

BORDER = (28, 709)  # the dashed zone border, in canvas pixels
PLAYER_COLOUR = (255, 225, 74)  # the yellow player arrow
PLAYER_TOLERANCE = 30
PLAYER_WINDOW = 24  # the arrow fits in this square; gold icon rings are thinner and spread out
# Icons are matched at half resolution (4x faster): a discovered altar scores 0.74, other icons <= 0.34.
ICON_STEP = 2

Position = tuple[float, float]


@dataclass(frozen=True)
class ZoneMap:
    player: Position
    altars: tuple[Position, ...]  # discovered rune altars
    targets: tuple[tuple[str, Position], ...] = ()  # other icons asked for, by name


def read_zonemap(png: bytes, targets: tuple[str, ...] = ()) -> ZoneMap | None:
    """`targets`: names of icons (autobonk.icons) to look for besides altars, each ~13 ms."""
    if not png:
        return None
    image = load_rgb(png)
    player = _player(image)
    if player is None:
        return None
    altars = tuple(_position(x, y) for x, y in find_icons(image, ALTAR_TEMPLATE, ALTAR_MATCH, ICON_STEP))
    found = tuple((name, _position(x, y)) for name, (x, y) in find_targets(image, list(targets)))
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
