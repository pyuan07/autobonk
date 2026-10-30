from pathlib import Path

from autobonk.zonemap import read_zonemap

ZONEMAP = Path(__file__).parent.parent / "fixtures" / "frames" / "frame-20261030-170001-415.zonemap.png"
BORDER, SIDE = 28, 681  # the dashed zone border inside the 738x738 canvas


def at(x: int, y: int) -> tuple[float, float]:
    return (x - BORDER) / SIDE, (y - BORDER) / SIDE


def close(a, b, tolerance=0.01):
    return abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance


def test_reads_the_player_arrow_position():
    zone = read_zonemap(ZONEMAP.read_bytes())

    assert close(zone.player, at(357, 349))


def test_reads_discovered_rune_altars():
    zone = read_zonemap(ZONEMAP.read_bytes())

    [altar] = zone.altars
    assert close(altar, at(277, 322))


def test_no_zone_map_while_tab_is_up():
    assert read_zonemap(b"") is None
