"""Reads the corner minimap canvas (400x400 PNG, player at the centre, W = minimap-up)."""

import math
from pathlib import Path

import numpy as np

from autobonk.perception.matching import (
    Point,
    find_icons,
    load_rgb,
    load_template,
    match_many,
)

# Template paths (fallback to parent directory if in subpackage)
_PKG_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _PKG_DIR.parent
ALTAR_TEMPLATE = _PKG_DIR / "altar_crystal.png" if (_PKG_DIR / "altar_crystal.png").exists() else _ROOT_DIR / "altar_crystal.png"
NORTH_TEMPLATE = _PKG_DIR / "north_marker.png" if (_PKG_DIR / "north_marker.png").exists() else _ROOT_DIR / "north_marker.png"

ALTAR_MATCH = 0.5
NORTH_MATCH = 0.7
RIM = (160, 200)
CENTRE = 200


def find_altars(image: np.ndarray | bytes) -> list[Point]:
    if isinstance(image, bytes):
        if not image:
            return []
        image = load_rgb(image)
    return [(x - CENTRE, y - CENTRE) for x, y in find_icons(image, ALTAR_TEMPLATE, ALTAR_MATCH)]


def north_bearing(image: np.ndarray | bytes) -> float | None:
    """Where 北 sits on the rim, in degrees clockwise from minimap-up (W)."""
    if isinstance(image, bytes):
        if not image:
            return None
        image = load_rgb(image)
    template = load_template(NORTH_TEMPLATE)
    scores = match_many(image, [template])[0]
    half = template.shape[0] // 2
    ys, xs = np.mgrid[: scores.shape[0], : scores.shape[1]]
    distance = np.hypot(xs + half - CENTRE, ys + half - CENTRE)
    scores[(distance < RIM[0]) | (distance > RIM[1])] = -1
    y, x = np.unravel_index(scores.argmax(), scores.shape)
    if scores[y, x] < NORTH_MATCH:
        return None
    return math.degrees(math.atan2(x + half - CENTRE, CENTRE - (y + half)))
