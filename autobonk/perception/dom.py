"""DOM parsing for HUD, popups, prompts, and status overlays."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Literal

import numpy as np

from autobonk.game import (
    BANISH_CANCEL_BUTTON,
    BANISH_RE,
    LEAVE_BUTTONS,
    PORTAL,
    REROLL_RE,
    RESTART_BUTTON,
    SKIP_RE,
    TEAM_VIEW_BUTTON,
    Card,
    is_portal_prompt,
)
from autobonk.perception.icons import find_targets
from autobonk.perception.matching import Point, load_rgb
from autobonk.perception.minimap import CENTRE, find_altars, north_bearing
from autobonk.perception.zonemap import ZoneMap, read_zonemap

if TYPE_CHECKING:
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

PROMPT_RE = re.compile(
    r'<div class="prompt"(?![^>]*display\s*:\s*none)[^>]*>(?:<kbd[^>]*>([A-Za-z0-9]+)</kbd>)?(.*?)(?:</div>|$)',
    re.DOTALL,
)


@dataclass(frozen=True)
class Button:
    text: str
    key: str | None


@dataclass(frozen=True)
class ForgetMove:
    name: str
    raw_name: str
    tags: str
    button_text: str


@dataclass(frozen=True)
class Popup:
    title: str
    cards: tuple[Card, ...]
    buttons: tuple[Button, ...]
    forget_moves: tuple[ForgetMove, ...] = ()

    @property
    def in_banish(self) -> bool:
        return any(b.text == BANISH_CANCEL_BUTTON for b in self.buttons)

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
    gold: int | None = None
    ball_price: int | None = None
    zone_idx: int | None = None
    total_zones: int | None = None
    is_sanctuary: bool = False
    can_restart: bool = False

    @property
    def seconds_left(self) -> int | None:
        if self.countdown is None:
            return None
        is_overtime = self.countdown.startswith("+")
        raw = self.countdown[1:] if is_overtime else self.countdown
        minutes, seconds = raw.split(":")
        total = int(minutes) * 60 + int(seconds)
        return -total if is_overtime else total

    @property
    def zone_index(self) -> int | None:
        if self.zone_idx is not None:
            return self.zone_idx
        if self.zone and " " in self.zone and "/" in self.zone:
            try:
                return int(self.zone.split()[1].split("/")[0])
            except (ValueError, IndexError):
                pass
        return None

    @property
    def recognised(self) -> bool:
        return self.end_screen is not None or self.countdown is not None or self.popup is not None


def _zone_info(html: str, texts: list[str]) -> tuple[str | None, int | None, int | None, bool]:
    m_zone = re.search(r'<span class="ht-zone">([^<]+)</span>', html)
    zone_name = m_zone.group(1).strip() if m_zone else None

    m_pips = re.search(r'<div class="ht-pips">(.*?)</div>', html, re.DOTALL)
    zone_index: int | None = None
    total_zones: int | None = None
    is_sanctuary = False
    if m_pips:
        pips = re.findall(r'<i class="([^"]*)"[^>]*title="([^"]*)"', m_pips.group(1))
        if pips:
            total_zones = len(pips)
            for i, (cls, title) in enumerate(pips, 1):
                classes = cls.split()
                if "now" in classes:
                    zone_index = i
                    if "sanct" in classes or "圣地" in title:
                        is_sanctuary = True
                    break
            if zone_index is None and zone_name:
                for i, (cls, title) in enumerate(pips, 1):
                    if title in zone_name or zone_name in title:
                        zone_index = i
                        if "sanct" in cls.split() or "圣地" in title:
                            is_sanctuary = True
                        break
            if zone_index is None:
                done_count = sum(1 for cls, _ in pips if "done" in cls.split())
                if done_count > 0:
                    zone_index = min(done_count, total_zones)
                    last_cls, last_title = pips[-1]
                    if done_count == total_zones and ("sanct" in last_cls.split() or "圣地" in last_title):
                        is_sanctuary = True

    if not zone_name:
        zone_name = next((t for t in texts if ZONE.fullmatch(t)), None)

    if zone_index is None and zone_name:
        m_fallback = re.search(r"区域 (\d+)/(\d+)", zone_name)
        if m_fallback:
            zone_index = int(m_fallback.group(1))
            total_zones = int(m_fallback.group(2))
        elif "圣地" in zone_name or "角" in zone_name:
            is_sanctuary = True

    return zone_name, zone_index, total_zones, is_sanctuary


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
    zone, zone_idx, total_zones, is_sanctuary = _zone_info(frame.dom_snapshot, texts)
    team_view = ("button", TEAM_VIEW_BUTTON) in nodes
    sealed = next((m for m in map(SEALED.fullmatch, texts) if m), None)
    minimap_icons = _minimap_targets(minimap_rgb, (*targets, PORTAL)) if minimap_rgb is not None else ()
    portal = _portal(frame.dom_snapshot, next((p for name, p in minimap_icons if name == PORTAL), None))
    prompt = _prompt(frame.dom_snapshot)
    has_unopened = bool(
        re.search(r"附近还有\d+个超级球没打开", frame.dom_snapshot)
        or any(
            is_dom_visible(m.group(0))
            for m in re.finditer(r'<[^>]*data-k=["\'](?:n?freechest|n?freeball)["\'][^>]*>', frame.dom_snapshot)
        )
    )
    boss_down = any(BOSS_DOWN.fullmatch(t) for t in texts)
    gold, ball_price = _wallet(frame.dom_snapshot)
    can_restart = ("button", RESTART_BUTTON) in nodes

    return Observation(
        end_screen=end_screen,
        countdown=countdown,
        popup=_popup(nodes, parsed.scopes, parsed.card_ids, parsed.card_faded, html=frame.dom_snapshot),
        altars=altars,
        charging=charging,
        north=north_bearing(minimap_rgb) if minimap_rgb is not None else None,
        zonemap=read_zonemap(frame.zonemap, targets),
        zone=zone,
        zone_idx=zone_idx,
        total_zones=total_zones,
        is_sanctuary=is_sanctuary,
        team_view=team_view,
        sealed_s=int(sealed.group(1)) if sealed else None,
        targets=tuple((name, p) for name, p in minimap_icons if name != PORTAL),
        level=next((int(texts[i + 1]) for i, t in enumerate(texts[:-1]) if t == "Lv" and texts[i + 1].isdigit()), None),
        boss_down=boss_down,
        prompt=prompt,
        portal=portal,
        has_unopened_super_balls=has_unopened,
        gold=gold,
        ball_price=ball_price,
        can_restart=can_restart,
    )


def _minimap_targets(image: np.ndarray, targets: tuple[str, ...]) -> tuple[tuple[str, Point], ...]:
    if not targets:
        return ()
    found = [(name, (x - CENTRE, y - CENTRE)) for name, (x, y) in find_targets(image, list(targets))]
    return tuple(sorted(found, key=lambda t: t[1][0] ** 2 + t[1][1] ** 2))


def _popup(
    nodes: list[tuple[str, str]],
    scopes: list[tuple[int, ...]],
    card_ids: list[int | None] | None = None,
    card_faded: dict[int, bool] | None = None,
    html: str = "",
) -> Popup | None:
    forget_moves = _forget_moves(html) if html else ()
    for start in reversed([i for i, (tag, _) in enumerate(nodes) if tag == "h1"]):
        container = scopes[start][-2] if len(scopes[start]) > 1 else None
        end = next((i for i in range(start + 1, len(nodes)) if container not in scopes[i]), len(nodes))
        body = nodes[start + 1:end]
        body_card_ids = card_ids[start + 1:end] if card_ids is not None else None
        buttons, cards = _buttons(body), _cards(body, body_card_ids, card_faded)
        if buttons or cards or forget_moves:
            return Popup(nodes[start][1], cards, buttons, forget_moves=forget_moves)
    buttons = _buttons(nodes)
    if any(button.text in LEAVE_BUTTONS for button in buttons):
        return Popup("", _cards(nodes, card_ids, card_faded), buttons, forget_moves=forget_moves)
    return None


def _forget_moves(html: str) -> tuple[ForgetMove, ...]:
    modal_m = re.search(r'class="modal shop-modal">(.*?)</div>\s*<button[^>]*class="btn shop-exit"', html, re.DOTALL)
    if not modal_m:
        return ()
    moves: list[ForgetMove] = []
    for m in re.finditer(r'<div class="item-row">(.*?)<button[^>]*>(.*?)</button>', modal_m.group(1), re.DOTALL):
        row_html, btn_text = m.group(1), m.group(2)
        if "typeicon" not in row_html:
            continue
        h4 = re.search(r'<h4>(.*?)</h4>', row_html)
        muted = re.search(r'<div class="muted">(.*?)</div>', row_html)
        if h4:
            raw_name = h4.group(1).strip()
            name = raw_name.split("·")[0].strip()
            tags = muted.group(1).strip() if muted else ""
            moves.append(ForgetMove(name=name, raw_name=raw_name, tags=tags, button_text=btn_text.strip()))
    return tuple(moves)


def _buttons(nodes: list[tuple[str, str]]) -> tuple[Button, ...]:
    return tuple(
        Button(text, nodes[i + 1][1] if i + 1 < len(nodes) and nodes[i + 1][0] == "kbd" else None)
        for i, (tag, text) in enumerate(nodes)
        if tag == "button" and text not in IGNORED_BUTTONS
    )


def _cards(
    nodes: list[tuple[str, str]],
    card_ids: list[int | None] | None = None,
    card_faded: dict[int, bool] | None = None,
) -> tuple[Card, ...]:
    if card_ids is not None:
        groups: dict[int, list[tuple[str, str]]] = {}
        for (tag, text), cid in zip(nodes, card_ids, strict=False):
            if cid is not None:
                groups.setdefault(cid, []).append((tag, text))
        cards: list[Card] = []
        for cid, card_nodes in groups.items():
            key_m = next((CARD_KEY.fullmatch(t) for _, t in card_nodes if CARD_KEY.fullmatch(t)), None)
            key = key_m.group(1) if key_m else ""
            name = next((t for tg, t in card_nodes if tg == "h3"), "")
            rarity = next((t for tg, t in card_nodes if tg == "span"), "")
            details = tuple(t for tg, t in card_nodes if t not in (name, rarity) and not CARD_KEY.fullmatch(t))
            faded = (card_faded or {}).get(cid, False)
            in_plan = any("在你的计划中" in t for _, t in card_nodes)
            cards.append(Card(key, name, rarity, details, is_maxed=faded, in_plan=in_plan))
        if cards:
            return tuple(cards)

    cards_list: list[Card] = []
    card: list[tuple[str, str]] = []
    for tag, text in nodes:
        key = CARD_KEY.fullmatch(text)
        if not key:
            card.append((tag, text))
            continue
        name = next((t for tg, t in card if tg == "h3"), "")
        rarity = next((t for tg, t in card if tg == "span"), "")
        details = tuple(t for t in (t for _, t in card) if t not in (name, rarity))
        in_plan = any("在你的计划中" in t for _, t in card)
        cards_list.append(Card(key.group(1), name, rarity, details, in_plan=in_plan))
        card = []
    if cards_list:
        return tuple(cards_list)
    keyless: list[Card] = []
    for tag, text in nodes:
        if tag == "h3":
            keyless.append(Card("", text, ""))
        elif tag == "button":
            break
        elif keyless:
            last = keyless[-1]
            keyless[-1] = Card(
                "",
                last.name,
                "",
                (*last.details, text),
                in_plan=last.in_plan or ("在你的计划中" in text),
            )
    return tuple(keyless)


def is_dom_visible(style_or_tag: str) -> bool:
    """True if a DOM element is rendered and visible (not display:none, not visibility:hidden, not faded)."""
    if "display: none" in style_or_tag or "display:none" in style_or_tag or "visibility: hidden" in style_or_tag:
        return False
    m = re.search(r"opacity:\s*([\d\.]+)", style_or_tag)
    return not (m and float(m.group(1)) <= 0.05)


def _portal(html: str, minimap_icon: Point | None = None) -> Point | None:
    """Where the portal is, in minimap pixels from the player. Most authoritative first."""
    # 1. Direct interaction prompt at portal
    m_prompt = PROMPT_RE.search(html)
    if m_prompt:
        prompt_content = re.sub(r"<[^>]+>", "", m_prompt.group(2)).strip()
        if is_portal_prompt(prompt_content) or is_portal_prompt(m_prompt.group(0)):
            return (0, 0)

    # 1b. Portal icon on the minimap: same frame and scale as every other target.
    if minimap_icon is not None:
        return minimap_icon

    # 2. Tracking compass. The HUD has one compass slot followed by its on-screen tag
    # (.compass.mktag); data-k says what it tracks. Off-screen, the compass shows at the
    # edge with a bearing; on-screen, the compass hides and the mktag marks the spot.
    # Hidden elements are dead nodes and never give a position.
    m_compass_tag = re.search(r'<div [^>]*data-k="portal"[^>]*>', html)
    if m_compass_tag and "compass" in m_compass_tag.group(0):
        if is_dom_visible(m_compass_tag.group(0)):
            m_rot = re.search(r'rotate\(([\d\.\-]+)rad\)', html[m_compass_tag.end():m_compass_tag.end() + 300])
            if m_rot:
                rad = float(m_rot.group(1))
                return (int(round(math.sin(rad) * 100.0)), int(round(-math.cos(rad) * 100.0)))
        else:
            m_mktag = re.compile(r'<div class="compass(?: mktag)?"[^>]*>').search(html, m_compass_tag.end())
            if m_mktag and "mktag" in m_mktag.group(0) and is_dom_visible(m_mktag.group(0)):
                m_pos = re.search(r'left:\s*([\d\.]+)px;\s*top:\s*([\d\.]+)px', m_mktag.group(0))
                if m_pos:
                    left, top = float(m_pos.group(1)), float(m_pos.group(2))
                    m_under = re.search(r'<div class="under"[^>]*style="left:\s*([\d\.]+)px;\s*top:\s*([\d\.]+)px', html)
                    px, py = (float(m_under.group(1)), float(m_under.group(2))) if m_under else (800.0, 480.0)
                    return (int(round((left - px) / 2.3)), int(round((top - py) / 2.3)))

    # 3. Fallback: on-screen wlabel when compass is not active
    m = re.search(r'<div class="wlabel[^"]*"[^>]*style="([^"]*--p:[^"]*)"[^>]*data-k="nportal"[^>]*>', html)
    if m:
        style = m.group(1)
        m_pos = re.search(r'left:\s*([\d\.]+)px;\s*top:\s*([\d\.]+)px', style)
        if m_pos:
            left, top = float(m_pos.group(1)), float(m_pos.group(2))
            m_under = re.search(r'<div class="under"[^>]*style="left:\s*([\d\.]+)px;\s*top:\s*([\d\.]+)px', html)
            px, py = (float(m_under.group(1)), float(m_under.group(2))) if m_under else (800.0, 480.0)
            return (int(round((left - px) / 2.3)), int(round((top - py) / 2.3)))

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


def _wallet(html: str) -> tuple[int | None, int | None]:
    m_k = re.search(r'class="wallet"[^>]*data-k="([^"]+)"', html)
    if m_k:
        parts = m_k.group(1).split("|")
        if len(parts) >= 2:
            gold = int(parts[0]) if parts[0].isdigit() else None
            ball = int(parts[1]) if parts[1].isdigit() else None
            return gold, ball
    m_gold = re.search(r'class="wl-gold[^"]*"[^>]*>.*?<b>(\d+)</b>', html, re.DOTALL)
    m_ball = re.search(r'class="wl-chip wl-ball"[^>]*>.*?<em>(\d+)</em>', html, re.DOTALL)
    gold = int(m_gold.group(1)) if m_gold else None
    ball = int(m_ball.group(1)) if m_ball else None
    return gold, ball


def _parse(html: str) -> _VisibleText:
    parser = _VisibleText()
    parser.feed(html)
    parser.close()
    return parser


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_NO_TEXT = {"script", "style", "svg", "noscript", "template"}
_DISPLAY_NONE = re.compile(r"display\s*:\s*none")
_OPACITY = re.compile(r"opacity\s*:\s*([\d.]+)")
# Maxed cards render at opacity 0.45; "opacity: 1" or a transition is not a fade.
_FADED_OPACITY = 0.6


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[tuple[str, str]] = []
        self.scopes: list[tuple[int, ...]] = []
        self.card_ids: list[int | None] = []
        self.card_faded: dict[int, bool] = {}
        self._stack: list[tuple[str, bool, int, int | None, bool]] = []
        self._next_id = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            return
        attrs_dict = dict(attrs)
        style = attrs_dict.get("style") or ""
        classes = (attrs_dict.get("class") or "").split()
        parent_card_id = self._stack[-1][3] if self._stack else None
        parent_faded = self._stack[-1][4] if self._stack else False

        is_this_card = "card" in classes and tag in ("button", "div")
        card_id = self._next_id if is_this_card else parent_card_id
        m_opacity = _OPACITY.search(style)
        is_faded = (m_opacity is not None and float(m_opacity.group(1)) <= _FADED_OPACITY) or (
            "disabled" in attrs_dict
        ) or parent_faded

        self._stack.append(
            (tag, tag in _NO_TEXT or bool(_DISPLAY_NONE.search(style)), self._next_id, card_id, is_faded)
        )
        self._next_id += 1

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text and not any(hidden for _, hidden, _, _, _ in self._stack):
            last = self._stack[-1]
            self.nodes.append((last[0], text))
            self.scopes.append(tuple(element for _, _, element, _, _ in self._stack))
            self.card_ids.append(last[3])
            if last[3] is not None:
                self.card_faded[last[3]] = last[4]
