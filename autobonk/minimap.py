"""Reads the corner minimap canvas (400x400 PNG, player at the centre, W = minimap-up)."""

from autobonk.perception.matching import (
    Point,
    find_icons,
    load_rgb,
    match_many,
)
from autobonk.perception.matching import (
    load_template as _template,
)
from autobonk.perception.minimap import (
    ALTAR_MATCH,
    ALTAR_TEMPLATE,
    CENTRE,
    NORTH_MATCH,
    NORTH_TEMPLATE,
    RIM,
    find_altars,
    north_bearing,
)

__all__ = [
    "Point",
    "find_icons",
    "load_rgb",
    "_template",
    "match_many",
    "ALTAR_MATCH",
    "ALTAR_TEMPLATE",
    "CENTRE",
    "NORTH_MATCH",
    "NORTH_TEMPLATE",
    "RIM",
    "find_altars",
    "north_bearing",
]
