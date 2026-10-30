"""DOM parsing for HUD, popups, prompts, and status overlays."""

import math
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

import numpy as np

from autobonk.game import LEAVE_BUTTONS, TEAM_VIEW_BUTTON, Card
from autobonk.perception.icons import find_targets
from autobonk.perception.matching import Point, load_rgb
from autobonk.perception.minimap import CENTRE, find_altars, north_bearing
from autobonk.perception.zonemap import ZoneMap, read_zonemap
from autobonk.runtime.frames import Frame

EndScreen = Literal["win", "lose"]

END_TITLES: dict[str, EndScreen] = {"胜利": "win", "你倒下了": "lose"}
COUNTDOWN = re.compile(r"\+?\d{1,2}:\d{2}")
CARD_KEY = re.compile(r"\[(\d)\]")
CHARGE = re.compile(r"\d{1,3}%")
ZONE = re.compile(r"区域 \d+/\d+")
BOSS_DOWN = re.compile(r"(?:头目.+倒下了|(?:守护者|传说宝可梦)已被击败|通往下一区域的传送门已打开|进入传送门以通关地图)[!！]?")
SEALED = re.compile(r"封印中.(\d+)秒后苏醒")
IGNORED_BUTTONS = {"重试"}
TEAM_VIEW_BUTTON = "返回选择"

REROLL_RE = re.compile(r"刷新\s*\((\d+)\)")
SKIP_RE = re.compile(r"跳过\s*\((\d+)\)")
BANISH_RE = re.compile(r"放逐\s*\((\d+)\)")

PROMPT_RE = re.compile(
    r'<div class="prompt"(?![^>]*display\s*:\s*none)[^>]*>(?:<kbd[^>]*>([A-Za-z0-9]+)</kbd>)?(.*?)(?:</div>|$)',
    re.DOTALL,
)


@dataclass(frozen=True)
class Button:
    text: str
    key: str | None


@dataclass(frozen=True)
class Popup:
    title: str
    cards: tuple[Card, ...]
    buttons: tuple[Button, ...]

    @property
    def in_banish(self) -> bool:
        return any(b.text == "取消" for b in self.buttons)

    def count(self, regex: re.Pattern[str]) -> int:
        for b in self.buttons:
            m = regex.search(b.text)
            if m:
                return int(m.group(1))
        return 0

    @property
    def rerolls(self) -> int:
        return self.count(REROLL_RE)

    @property
    def skips(self) -> int:
        return self.count(SKIP_RE)

    @property
    def banishes(self) -> int:
        return self.count(BANISH_RE)


@dataclass(frozen=True)
class Observation:
    end_screen: EndScreen | None
    countdown: str | None
    popup: Popup | None = None
    altars: tuple[Point, ...] = ()
    charging: bool = False
    north: float | None = None
    zonemap: ZoneMap | None = None
    zone: str | None = None
    team_view: bool = False
    sealed_s: int | None = None
    targets: tuple[tuple[str, Point], ...] = ()
    level: int | None = None
    boss_down: bool = False
    prompt: tuple[str, str] | None = None
    portal: Point | None = None
    has_unopened_super_balls: bool = False

    @property
    def seconds_left(self) -> int | None:
        if self.countdown is None:
            return None
        if self.countdown.startswith("+"):
            return 0
        minutes, seconds = self.countdown.split(":")
        return int(minutes) * 60 + int(seconds)

    @property
    def zone_index(self) -> int | None:
        return int(self.zone.split()[1].split("/")[0]) if self.zone else None

    @property
    def recognised(self) -> bool:
        return self.end_screen is not None or self.countdown is not None or self.popup is not None


def perceive(frame: Frame, targets: tuple[str, ...] = ()) -> Observation:
    parsed = _parse(frame.dom_snapshot)
    nodes = parsed.nodes
    texts = [text for _, text in nodes]
    end_screen = next((END_TITLES[t.rstrip("!！")] for t in texts if t.rstrip("!！") in END_TITLES), None)
    countdown = next((t for t in texts if COUNTDOWN.fullmatch(t)), None)

    minimap_rgb = load_rgb(frame.minimap) if frame.minimap else None
    altars = (
        tuple(sorted(find_altars(minimap_rgb), key=lambda p: p[0] ** 2 + p[1] ** 2))
        if minimap_rgb is not None
        else ()
    )
    charging = any(tag == "span" and CHARGE.fullmatch(text) for tag, text in nodes)
    zone = next((t for t in texts if ZONE.fullmatch(t)), None)
    team_view = ("button", TEAM_VIEW_BUTTON) in nodes
    sealed = next((m for m in map(SEALED.fullmatch, texts) if m), None)
    portal = _portal(frame.dom_snapshot)
    prompt = _prompt(frame.dom_snapshot)
    has_unopened = bool(re.search(r"附近还有\d+个超级球没打开", frame.dom_snapshot))
    boss_down = any(BOSS_DOWN.fullmatch(t) for t in texts)

    return Observation(
        end_screen=end_screen,
        countdown=countdown,
        popup=_popup(nodes, parsed.scopes),
        altars=altars,
        charging=charging,
        north=north_bearing(minimap_rgb) if minimap_rgb is not None else None,
        zonemap=read_zonemap(frame.zonemap, targets),
        zone=zone,
        team_view=team_view,
        sealed_s=int(sealed.group(1)) if sealed else None,
        targets=_minimap_targets(minimap_rgb, targets) if minimap_rgb is not None else (),
        level=next((int(texts[i + 1]) for i, t in enumerate(texts[:-1]) if t == "Lv" and texts[i + 1].isdigit()), None),
        boss_down=boss_down,
        prompt=prompt,
        portal=portal,
        has_unopened_super_balls=has_unopened,
    )


def _minimap_targets(image: np.ndarray, targets: tuple[str, ...]) -> tuple[tuple[str, Point], ...]:
    if not targets:
        return ()
    found = [(name, (x - CENTRE, y - CENTRE)) for name, (x, y) in find_targets(image, list(targets))]
    return tuple(sorted(found, key=lambda t: t[1][0] ** 2 + t[1][1] ** 2))


def _popup(nodes: list[tuple[str, str]], scopes: list[tuple[int, ...]]) -> Popup | None:
    for start in reversed([i for i, (tag, _) in enumerate(nodes) if tag == "h1"]):
        container = scopes[start][-2] if len(scopes[start]) > 1 else None
        end = next((i for i in range(start + 1, len(nodes)) if container not in scopes[i]), len(nodes))
        body = nodes[start + 1:end]
        buttons, cards = _buttons(body), _cards(body)
        if buttons or any(card.key for card in cards):
            return Popup(nodes[start][1], cards, buttons)
    buttons = _buttons(nodes)
    if any(button.text in LEAVE_BUTTONS for button in buttons):
        return Popup("", _cards(nodes), buttons)
    return None


def _buttons(nodes: list[tuple[str, str]]) -> tuple[Button, ...]:
    return tuple(
        Button(text, nodes[i + 1][1] if i + 1 < len(nodes) and nodes[i + 1][0] == "kbd" else None)
        for i, (tag, text) in enumerate(nodes)
        if tag == "button" and text not in IGNORED_BUTTONS
    )


def _cards(nodes: list[tuple[str, str]]) -> tuple[Card, ...]:
    cards: list[Card] = []
    card: list[tuple[str, str]] = []
    for tag, text in nodes:
        key = CARD_KEY.fullmatch(text)
        if not key:
            card.append((tag, text))
            continue
        name = next((t for tg, t in card if tg == "h3"), "")
        rarity = next((t for tg, t in card if tg == "span"), "")
        details = tuple(t for t in (t for _, t in card) if t not in (name, rarity))
        cards.append(Card(key.group(1), name, rarity, details))
        card = []
    if cards:
        return tuple(cards)
    keyless: list[Card] = []
    for tag, text in nodes:
        if tag == "h3":
            keyless.append(Card("", text, ""))
        elif tag == "button":
            break
        elif keyless:
            last = keyless[-1]
            keyless[-1] = Card("", last.name, "", (*last.details, text))
    return tuple(keyless)


def _portal(html: str) -> Point | None:
    m = re.search(r'<div class="wlabel[^"]*"[^>]*style="([^"]*--p:[^"]*)"[^>]*data-k="nportal"[^>]*>', html)
    if m:
        style = m.group(1)
        m_pos = re.search(r'left:\s*([\d\.]+)px;\s*top:\s*([\d\.]+)px', style)
        if m_pos:
            left, top = float(m_pos.group(1)), float(m_pos.group(2))
            m_under = re.search(r'<div class="under"[^>]*style="left:\s*([\d\.]+)px;\s*top:\s*([\d\.]+)px', html)
            px, py = (float(m_under.group(1)), float(m_under.group(2))) if m_under else (800.0, 480.0)
            return (int(round((left - px) / 2.3)), int(round((top - py) / 2.3)))

    m_prompt = PROMPT_RE.search(html)
    if m_prompt and any(k in m_prompt.group(0) for k in ("进入传送门", "离开圣地")):
        return (0, 0)

    m_c = re.search(r'<div class="compass[^"]*"[^>]*data-k="portal".*?rotate\(([\d\.\-]+)rad\)', html, re.DOTALL)
    if m_c:
        rad = float(m_c.group(1))
        return (int(round(math.sin(rad) * 100.0)), int(round(-math.cos(rad) * 100.0)))

    return None


def _prompt(html: str) -> tuple[str, str] | None:
    m = PROMPT_RE.search(html)
    if not m:
        return None
    key = m.group(1) or "E"
    text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
    if not text or "钱不够" in text:
        return None
    return (key, text)


def _parse(html: str) -> "_VisibleText":
    parser = _VisibleText()
    parser.feed(html)
    parser.close()
    return parser


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_NO_TEXT = {"script", "style", "svg", "noscript", "template"}
_DISPLAY_NONE = re.compile(r"display\s*:\s*none")


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[tuple[str, str]] = []
        self.scopes: list[tuple[int, ...]] = []
        self._stack: list[tuple[str, bool, int]] = []
        self._next_id = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            return
        style = dict(attrs).get("style") or ""
        self._stack.append((tag, tag in _NO_TEXT or bool(_DISPLAY_NONE.search(style)), self._next_id))
        self._next_id += 1

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text and not any(hidden for _, hidden, _ in self._stack):
            self.nodes.append((self._stack[-1][0] if self._stack else "", text))
            self.scopes.append(tuple(element for _, _, element in self._stack))
