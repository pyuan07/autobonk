"""Game constants, target names, HUD strings, keyboard definitions, and boss rules."""

import enum
import re
from collections.abc import Mapping
from dataclasses import dataclass

# Target and icon names
ALTAR = "符文祭坛"
SANCTUARY = "圣地"
BOSS = "骷髅"
PORTAL = "传送门"
POKEBALL = "精灵球"
SUPER_BALL = "超级球"
GIFT_BALL = "礼物球"
COIN = "金币"
CHANSEY = "吉利蛋"
EXPLORE = "探索未知"
SUPER_BALLS = frozenset({SUPER_BALL, GIFT_BALL})
BOSS_LOOT = frozenset({SUPER_BALL, GIFT_BALL})
# The zone's own flow: never ignored because an unrelated popup was left.
CORE_TARGETS = frozenset({ALTAR, SANCTUARY, BOSS, PORTAL})

# Buttons & HUD prompts
PICK_UP_BUTTON = "拾取"
READY_BUTTON = "就绪"
RELEASE_NEWCOMER = "放生新来的"
RESTART_BUTTON = "再来一次"
DITTO_TITLE = "百变怪"
HYPNO_TITLE = "引梦貘人"
TEAM_VIEW = "你的队伍"
TEAM_VIEW_BUTTON = "返回选择"
LEAVE_BUTTONS = ("离开", "以后再说", "关闭")
PORTAL_PROMPTS = ("传送门", "进入传送门", "离开圣地", "进入圣地")
BOSS_PROMPTS = ("守护者", "头目", "触碰圣地", "触碰", "传说宝可梦", BOSS)
SANCTUARY_PROMPTS = ("触碰圣地", "触碰")

def is_portal_prompt(prompt_text: str) -> bool:
    """Whether an on-screen prompt represents a stage transition portal.

    Matches:
    - Standard portals: "传送门", "进入传送门"
    - Biome-specific sanctuary portals: "进入天空湖", "进入森林圣地", "进入沙漠圣地", etc.
    - Final victory exit: "离开圣地"
    Excludes boss awakening prompts like "触碰圣地" or "唤醒守护者".
    """
    if not prompt_text:
        return False
    if "触碰" in prompt_text or "唤醒" in prompt_text:
        return False
    return "进入" in prompt_text or "离开" in prompt_text or "传送门" in prompt_text

# Level-up modal actions
BANISH_CANCEL_BUTTON = "取消"
LOCKED_MOVE_WARNING = "不会再升级"
REROLL_RE = re.compile(r"刷新\s*\((\d+)\)")
SKIP_RE = re.compile(r"跳过\s*\((\d+)\)")
BANISH_RE = re.compile(r"放逐\s*\((\d+)\)")

# Keyboard key mappings
KEY_NAMES = {"Esc": "Escape"}
JUMP_KEY = "Space"
INTERACT_KEY = "KeyE"
MAP_KEY = "Tab"

# Minimap-up is always KeyW (screen-up). 8 sectors of 45 degrees, counter-clockwise from east.
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
INTERACT_WAIT_S = 3.0
INTERACT_RETRY_S = 0.3

class Unchanged(enum.Enum):
    """Hot-reload marker: keep the current value. None is a real value there (disabled)."""

    UNCHANGED = 0


UNCHANGED = Unchanged.UNCHANGED

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
    is_maxed: bool = False
    in_plan: bool = False

    def __post_init__(self) -> None:
        if not self.is_maxed and (
            any("已满" in d for d in self.details) or "已满" in self.rarity
        ):
            object.__setattr__(self, "is_maxed", True)
        if not self.in_plan and any("在你的计划中" in d for d in self.details):
            object.__setattr__(self, "in_plan", True)

    @property
    def is_locked_move(self) -> bool:
        """True if banishing this card would permanently lock an owned move at its current level."""
        return any(LOCKED_MOVE_WARNING in d for d in self.details)


def canonical_target_name(name: str) -> str:
    """Normalize target names (e.g. gift ball alias)."""
    if name in SUPER_BALLS:
        return SUPER_BALL
    return name


def prompt_matches_target(prompt_text: str, target_name: str | None) -> bool:
    """Whether an on-screen HUD prompt belongs to the given target."""
    if not prompt_text or not target_name:
        return False
    # Boss prompt only matches Boss and Altar/Sanctuary
    if any(k in prompt_text for k in BOSS_PROMPTS):
        return target_name == BOSS or target_name in (ALTAR, SANCTUARY)
    # Portal prompt only matches Portal
    if is_portal_prompt(prompt_text):
        return target_name == PORTAL
    # If target is Boss or Portal, they only match their respective prompts
    if target_name == BOSS:
        return any(k in prompt_text for k in BOSS_PROMPTS)
    if target_name == PORTAL:
        return is_portal_prompt(prompt_text)
    if target_name in (ALTAR, SANCTUARY):
        return "触碰" in prompt_text or "圣地" in prompt_text

    # Direct substring matches
    if target_name in prompt_text or prompt_text in target_name:
        return True
    if target_name == "矿堆" and "碎岩" in prompt_text:
        return True
    if target_name in SUPER_BALLS and "超级球" in prompt_text:
        return True
    return bool(target_name == POKEBALL and "精灵球" in prompt_text)


def is_boss_prompt(prompt_text: str) -> bool:
    """A prompt (or a target named after one) that summons the area or sanctuary boss."""
    return bool(prompt_text) and any(k in prompt_text for k in BOSS_PROMPTS) and not is_portal_prompt(prompt_text)


def is_generic_prompt(prompt_text: str) -> bool:
    """A prompt that is neither a boss summon nor a portal. Map icon names rarely appear in
    the prompt (卡比兽, 牢笼, 喵喵 ...), so such a prompt can belong to any regular target the
    player is standing at; callers decide by distance."""
    return bool(prompt_text) and not any(k in prompt_text for k in BOSS_PROMPTS) and not is_portal_prompt(prompt_text)


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
