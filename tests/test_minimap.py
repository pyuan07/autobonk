from pathlib import Path

import pytest

from autobonk.minimap import find_altars

FRAMES = Path(__file__).parent.parent / "fixtures" / "frames"


def minimap(name: str) -> bytes:
    return (FRAMES / f"frame-20261030-{name}.minimap.png").read_bytes()


# Offsets from the player (minimap centre), x right and y down, in minimap pixels.
@pytest.mark.parametrize(
    "name, where",
    [
        ("155200-971", (149, -60)),  # purple ring, up-right
        ("155204-484", (149, 0)),  # right
        ("155214-804", (51, 5)),  # just right of the player
        ("155220-116", (-2, -47)),  # straight up
        ("155222-698", (-2, -7)),  # under the player arrow, charging 8%
        ("155227-456", (-10, -4)),  # under the player arrow, charging 29%
        ("155651-230", (-82, 105)),  # down-left, beside a boss badge
        ("155654-906", (-35, 34)),
        ("155820-313", (-7, 134)),  # cyan ring variant
        ("160041-764", (-92, 17)),  # cyan ring variant
    ],
)
def test_finds_the_rune_altar(name, where):
    [(x, y)] = find_altars(minimap(name))
    assert abs(x - where[0]) <= 3 and abs(y - where[1]) <= 3


@pytest.mark.parametrize("name", ["155313-554", "155439-910", "155532-914", "155925-987"])
def test_no_altar_no_match(name):
    assert find_altars(minimap(name)) == []


def test_no_minimap_no_altars():
    assert find_altars(b"") == []
