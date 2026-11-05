"""Zone exploration state, visited grid tracking, and boss phase lifecycle."""

import enum
import logging
import math

from autobonk.game import GRID
from autobonk.perception.zonemap import Position

SECTOR_GRID = 4


def sector_coord(position: Position) -> tuple[int, int]:
    """Convert normalized (0..1, 0..1) zone coordinates to 4x4 sector coordinates (0..3, 0..3)."""
    return min(max(int(position[0] * SECTOR_GRID), 0), SECTOR_GRID - 1), min(max(int(position[1] * SECTOR_GRID), 0), SECTOR_GRID - 1)


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


def turning_cost(centre: Position, player: Position, heading: float | None) -> float:
    """Calculates distance with a slight turning penalty to favor continuing in current heading."""
    d = distance(player, centre)
    if heading is None:
        return d
    dx, dy = centre[0] - player[0], centre[1] - player[1]
    cand_heading = math.degrees(math.atan2(dx, -dy))
    turn = abs((cand_heading - heading + 180.0) % 360.0 - 180.0)
    return d * (1.0 + (turn / 180.0) * 0.25)


class ZoneTracker:
    def __init__(self) -> None:
        self.zone: str | None = None
        self.is_sanctuary: bool = False
        self.visited: set[tuple[int, int]] = set()
        self.visited_sectors: set[tuple[int, int]] = set()
        self.zone_seconds: int | None = None
        self.boss_phase: BossPhase = BossPhase.WAITING
        self.heading: float | None = None  # North-up bearing toward target or unvisited cell
        self.zone_entered_at: float = 0.0
        self._last_seconds_left: int | None = None

    def reset(self) -> None:
        self.zone = None
        self.is_sanctuary = False
        self.visited.clear()
        self.visited_sectors.clear()
        self.zone_seconds = None
        self.boss_phase = BossPhase.WAITING
        self.heading = None
        self.zone_entered_at = 0.0
        self._last_seconds_left = None

    def update(
        self,
        zone_name: str | None,
        seconds_left: int | None,
        is_sanctuary: bool = False,
        now: float = 0.0,
    ) -> bool:
        """Update zone and timer. Returns True if zone changed (memory reset)."""
        zone_changed = False
        timer_jumped = (
            seconds_left is not None
            and seconds_left >= 570
            and self._last_seconds_left is not None
            and self._last_seconds_left < 500
        )
        if zone_name != self.zone or timer_jumped:
            log.info(
                "Entered new zone / reset: %s (previous: %s, timer_jumped=%s, sanctuary=%s)",
                zone_name,
                self.zone,
                timer_jumped,
                is_sanctuary,
            )
            self.zone = zone_name
            self.is_sanctuary = is_sanctuary
            self.visited.clear()
            self.visited_sectors.clear()
            self.heading = None
            self.zone_seconds = None
            self.boss_phase = BossPhase.WAITING
            self.zone_entered_at = now
            zone_changed = True
        elif is_sanctuary and not self.is_sanctuary:
            # The sanctuary marker can render a frame after the zone name: a zone never
            # stops being a sanctuary once seen as one.
            log.info("zone %s recognised as sanctuary", zone_name)
            self.is_sanctuary = True

        if seconds_left is not None:
            self._last_seconds_left = seconds_left
            if self.zone_seconds is None or seconds_left > self.zone_seconds:
                self.zone_seconds = seconds_left

        return zone_changed

    def mark_visited(self, player_pos: Position) -> None:
        self.visited.add(cell(player_pos))
        self.visited_sectors.add(sector_coord(player_pos))

    def nearest_unvisited(self, player: Position) -> Position:
        inner = [(col, row) for col in range(1, GRID - 1) for row in range(1, GRID - 1)]
        unvisited = [c for c in inner if c not in self.visited]
        if not unvisited:
            log.info("whole zone explored: starting over")
            self.visited = {cell(player)}
            unvisited = [c for c in inner if c not in self.visited]
        centres = [((col + 0.5) / GRID, (row + 0.5) / GRID) for col, row in unvisited]

        return min(centres, key=lambda c: turning_cost(c, player, self.heading))

    def nearest_unvisited_sector(self, player: Position) -> Position:
        all_sectors = [(col, row) for col in range(SECTOR_GRID) for row in range(SECTOR_GRID)]
        unvisited = [s for s in all_sectors if s not in self.visited_sectors]
        if not unvisited:
            log.info("all 16 sectors explored: starting over")
            self.visited_sectors = {sector_coord(player)}
            unvisited = [s for s in all_sectors if s not in self.visited_sectors]
        centres = [((col + 0.5) / SECTOR_GRID, (row + 0.5) / SECTOR_GRID) for col, row in unvisited]

        return min(centres, key=lambda c: turning_cost(c, player, self.heading))
