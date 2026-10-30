"""Zone exploration state, visited grid tracking, and boss phase lifecycle."""

import enum
import logging
import math

from autobonk.game import GRID
from autobonk.perception.zonemap import Position

log = logging.getLogger(__name__)


class BossPhase(enum.Enum):
    WAITING = "waiting"
    FIGHTING = "fighting"
    BEATEN = "beaten"


def cell(position: Position) -> tuple[int, int]:
    """Convert normalized (0..1, 0..1) zone coordinates to grid coordinates."""
    return min(int(position[0] * GRID), GRID - 1), min(int(position[1] * GRID), GRID - 1)


def distance(a: Position, b: Position) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class ZoneTracker:
    def __init__(self) -> None:
        self.zone: str | None = None
        self.visited: set[tuple[int, int]] = set()
        self.zone_seconds: int | None = None
        self.boss_phase: BossPhase = BossPhase.WAITING
        self.heading: float | None = None  # North-up bearing toward target or unvisited cell

    def update(self, zone_name: str | None, seconds_left: int | None) -> bool:
        """Update zone and timer. Returns True if zone changed (memory reset)."""
        zone_changed = False
        if zone_name != self.zone:
            log.info("Entered new zone: %s (previous: %s)", zone_name, self.zone)
            self.zone = zone_name
            self.visited.clear()
            self.heading = None
            self.zone_seconds = None
            self.boss_phase = BossPhase.WAITING
            zone_changed = True

        if seconds_left is not None:
            if self.zone_seconds is None or seconds_left > self.zone_seconds:
                self.zone_seconds = seconds_left

        return zone_changed

    def mark_visited(self, player_pos: Position) -> None:
        self.visited.add(cell(player_pos))

    def nearest_unvisited(self, player: Position) -> Position:
        inner = [(col, row) for col in range(1, GRID - 1) for row in range(1, GRID - 1)]
        unvisited = [c for c in inner if c not in self.visited]
        if not unvisited:
            log.info("whole zone explored: starting over")
            self.visited = {cell(player)}
            unvisited = [c for c in inner if c not in self.visited]
        centres = [((col + 0.5) / GRID, (row + 0.5) / GRID) for col, row in unvisited]
        return min(centres, key=lambda centre: distance(player, centre))
