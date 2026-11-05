from pathlib import Path

from autobonk.zonemap import read_zonemap

FRAMES = Path(__file__).parent.parent / "fixtures" / "frames"

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


def test_finds_the_icons_asked_for():
    zone = read_zonemap((FRAMES / "frame-20261030-174232-152.zonemap.png").read_bytes(), ("喵喵", "骷髅"))

    assert sorted(name for name, _ in zone.targets) == ["喵喵", "骷髅"]
    [(_, (x, y))] = [t for t in zone.targets if t[0] == "喵喵"]
    assert 0.45 < x < 0.5 and y < 0.02  # top middle


def test_heading_continuity_prefers_forward_cell():
    from autobonk.policy.zone import ZoneTracker
    tracker = ZoneTracker()
    inner = [(col, row) for col in range(1, 7) for row in range(1, 7)]
    for c in inner:
        if c not in [(3, 2), (3, 4)]:
            tracker.visited.add(c)
    player = (3.5 / 8, 3.5 / 8)  # cell (3, 3) center

    tracker.heading = 0.0  # North (towards row 2)
    assert tracker.nearest_unvisited(player) == (0.4375, 0.3125)

    tracker.heading = 180.0  # South (towards row 4)
    assert tracker.nearest_unvisited(player) == (0.4375, 0.5625)
