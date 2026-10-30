"""Game constants, target names, HUD strings, keyboard definitions, and boss rules."""

from dataclasses import dataclass
from typing import Mapping

# Target and icon names
ALTAR = "符文祭坛"
BOSS = "骷髅"
PORTAL = "传送门"
SUPER_BALL = "超级球"
GIFT_BALL = "礼物球"
SUPER_BALLS = frozenset({SUPER_BALL, GIFT_BALL})

# Buttons & HUD prompts
PICK_UP_BUTTON = "拾取"
READY_BUTTON = "就绪"
DITTO_TITLE = "百变怪"
TEAM_VIEW = "你的队伍"
TEAM_VIEW_BUTTON = "返回选择"
LEAVE_BUTTONS = ("离开", "以后再说")
PORTAL_PROMPTS = ("传送门", "进入传送门", "离开圣地")
BOSS_PROMPTS = ("守护者", "头目", BOSS)

# Keyboard key mappings
KEY_NAMES = {"Esc": "Escape"}
JUMP_KEY = "Space"
INTERACT_KEY = "KeyE"
MAP_KEY = "Tab"

# Minimap-up is always W. 8 sectors of 45 degrees, counter-clockwise from east.
DIRECTION_KEYS = (
    {"KeyD"},
    {"KeyW", "KeyD"},
    {"KeyW"},
    {"KeyW", "KeyA"},
    {"KeyA"},
    {"KeyS", "KeyA"},
    {"KeyS"},
    {"KeyS", "KeyD"},
)

# Spatial thresholds (in minimap pixels or grid ratios)
ALTAR_ARRIVED_PX = 14
TARGET_ARRIVED_PX = 4
TEMP_TARGET_PX = 24
APPROACH_PX_PER_S = 20.0
INTERACT_PX = 20
CLOSE_TIMEOUT_PX = 45
ALTAR_PROGRESS_PX = 3
ZONE_PROGRESS = 0.01
GRID = 8

# Timers
POPUP_RETRY_S = 1.0
INTERACT_WAIT_S = 5.0
INTERACT_RETRY_S = 0.3

# Defaults
DEFAULT_TARGETS: Mapping[str, float] = {ALTAR: 10.0}

# Target weight: fixed float, or (start, end) growing as zone time runs out
Weight = float | tuple[float, float]


@dataclass(frozen=True)
class Card:
    key: str
    name: str
    rarity: str
    details: tuple[str, ...] = ()

    @property
    def is_locked_move(self) -> bool:
        """True if banishing this card would permanently lock an owned move at its current level."""
        return any("不会再升级" in d for d in self.details)


def canonical_target_name(name: str) -> str:
    """Normalize target names (e.g. gift ball alias)."""
    if name in SUPER_BALLS:
        return SUPER_BALL
    return name


@dataclass(frozen=True)
class BossRule:
    """Summon the area boss in zone N once the level reaches levels[N-1], or once only
    minutes_left[N-1] are left; from then on it comes before everything else."""

    levels: tuple[int, ...] = (35, 60, 80)
    minutes_left: tuple[float, ...] = (4, 8, 8)

    def ready(self, zone: int, level: int | None, seconds_left: int | None) -> bool:
        i = min(zone, len(self.levels)) - 1
        strong = level is not None and level >= self.levels[i]
        late = seconds_left is not None and seconds_left <= self.minutes_left[i] * 60
        return strong or late
