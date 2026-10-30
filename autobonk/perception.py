"""Turns a Frame into an Observation. DOM-first: HUD and popups are read by visible text."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

from autobonk.cards import Card
from autobonk.frames import Frame
from autobonk.minimap import Point, find_altars, north_bearing
from autobonk.zonemap import ZoneMap, read_zonemap

EndScreen = Literal["win", "lose"]

END_TITLES: dict[str, EndScreen] = {"胜利": "win", "你倒下了": "lose"}
COUNTDOWN = re.compile(r"\d{1,2}:\d{2}")
CARD_KEY = re.compile(r"\[(\d)\]")
# The progress bubble over a rune altar (or ore pile) the player stands in: a bare "29%".
CHARGE = re.compile(r"\d{1,3}%")
ZONE = re.compile(r"区域 \d+/\d+")
# The "还有 N 个图像未加载 [重试]" corner notice is not a popup.
IGNORED_BUTTONS = {"重试"}
# Buttons that close a popup without choosing anything.
LEAVE_BUTTONS = ("离开", "以后再说")
# The team view ("你的队伍") laid over a choice popup; its button goes back to the choice.
TEAM_VIEW_BUTTON = "返回选择"


@dataclass(frozen=True)
class Button:
    text: str
    key: str | None  # key cap shown right after the text, e.g. "E" or "Esc"


@dataclass(frozen=True)
class Popup:
    title: str  # the <h1>; "" for untitled popups (slot machine)
    cards: tuple[Card, ...]  # choices; key "" when the popup shows no [n] keys (Ditto, shop)
    buttons: tuple[Button, ...]


@dataclass(frozen=True)
class Observation:
    end_screen: EndScreen | None
    countdown: str | None
    popup: Popup | None = None
    altars: tuple[Point, ...] = ()  # rune altars on the minimap, nearest first
    charging: bool = False  # a progress bubble shows: stay put until it finishes
    north: float | None = None  # 北 on the minimap rim, degrees clockwise from minimap-up
    zonemap: ZoneMap | None = None  # only while Tab is held
    zone: str | None = None  # "区域 1/3"
    team_view: bool = False  # the team view covers the popup: its keys do nothing until it closes

    @property
    def recognised(self) -> bool:
        return self.end_screen is not None or self.countdown is not None or self.popup is not None


def perceive(frame: Frame) -> Observation:
    parsed = _parse(frame.dom_snapshot)
    nodes = parsed.nodes
    texts = [text for _, text in nodes]
    end_screen = next((END_TITLES[t.rstrip("!！")] for t in texts if t.rstrip("!！") in END_TITLES), None)
    countdown = next((t for t in texts if COUNTDOWN.fullmatch(t)), None)
    altars = tuple(sorted(find_altars(frame.minimap), key=lambda p: p[0] ** 2 + p[1] ** 2))
    charging = any(tag == "span" and CHARGE.fullmatch(text) for tag, text in nodes)
    zone = next((t for t in texts if ZONE.fullmatch(t)), None)
    team_view = ("button", TEAM_VIEW_BUTTON) in nodes
    return Observation(
        end_screen, countdown, _popup(nodes, parsed.scopes), altars, charging,
        north_bearing(frame.minimap), read_zonemap(frame.zonemap), zone, team_view,
    )


def _popup(nodes: list[tuple[str, str]], scopes: list[tuple[int, ...]]) -> Popup | None:
    """A popup is an <h1> with buttons or [n] keys inside the h1's own container (.modal);
    banners (.bn-txt, .stageintro) hold only text, and HUD buttons elsewhere don't count.
    Untitled popups (slot machine) are recognised by a leave button alone."""
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
    """Each card is a run of texts ending in its [n] key, with the rarity in its first <span>
    and the name in an <h3>. Without [n] keys, every <h3> is a keyless card."""
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


def visible_texts(html: str) -> list[str]:
    """Text nodes, stripped, skipping scripts/styles and subtrees hidden with inline display:none."""
    return [text for _, text in visible_nodes(html)]


def visible_nodes(html: str) -> list[tuple[str, str]]:
    """Like `visible_texts`, paired with each text's enclosing tag."""
    return _parse(html).nodes


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
        self.scopes: list[tuple[int, ...]] = []  # per node: ids of its open elements, outermost first
        self._stack: list[tuple[str, bool, int]] = []  # (tag, hides its content, element id)
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
