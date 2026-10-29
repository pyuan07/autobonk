"""Turns a Frame into an Observation. DOM-first: HUD and popups are read by visible text."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

from autobonk.cards import Card
from autobonk.frames import Frame

EndScreen = Literal["win", "lose"]

END_TITLES: dict[str, EndScreen] = {"胜利": "win", "你倒下了": "lose"}
COUNTDOWN = re.compile(r"\d{1,2}:\d{2}")
LEVEL_UP_TITLE = re.compile(r"等级 \d+[!！]")
CARD_KEY = re.compile(r"\[(\d)\]")


@dataclass(frozen=True)
class Popup:
    title: str
    cards: tuple[Card, ...]


@dataclass(frozen=True)
class Observation:
    end_screen: EndScreen | None
    countdown: str | None
    popup: Popup | None = None

    @property
    def recognised(self) -> bool:
        return self.end_screen is not None or self.countdown is not None or self.popup is not None


def perceive(frame: Frame) -> Observation:
    nodes = visible_nodes(frame.dom_snapshot)
    texts = [text for _, text in nodes]
    end_screen = next((END_TITLES[t.rstrip("!！")] for t in texts if t.rstrip("!！") in END_TITLES), None)
    countdown = next((t for t in texts if COUNTDOWN.fullmatch(t)), None)
    return Observation(end_screen, countdown, _level_up(nodes))


def _level_up(nodes: list[tuple[str, str]]) -> Popup | None:
    """Cards follow the 等级 N！ title; each is a run of texts ending in its [n] key,
    with the rarity first and the name in an <h3>."""
    start = next((i for i, (_, text) in enumerate(nodes) if LEVEL_UP_TITLE.fullmatch(text)), None)
    if start is None:
        return None
    cards: list[Card] = []
    card: list[tuple[str, str]] = []
    for tag, text in nodes[start + 1:]:
        key = CARD_KEY.fullmatch(text)
        if not key:
            card.append((tag, text))
            continue
        name = next((t for tg, t in card if tg == "h3"), "")
        cards.append(Card(key.group(1), name, card[0][1] if card else ""))
        card = []
    return Popup(nodes[start][1], tuple(cards)) if cards else None


def visible_texts(html: str) -> list[str]:
    """Text nodes, stripped, skipping scripts/styles and subtrees hidden with inline display:none."""
    return [text for _, text in visible_nodes(html)]


def visible_nodes(html: str) -> list[tuple[str, str]]:
    """Like `visible_texts`, paired with each text's enclosing tag."""
    parser = _VisibleText()
    parser.feed(html)
    parser.close()
    return parser.nodes


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_NO_TEXT = {"script", "style", "svg", "noscript", "template"}
_DISPLAY_NONE = re.compile(r"display\s*:\s*none")


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[tuple[str, str]] = []
        self._stack: list[tuple[str, bool]] = []  # (tag, hides its content)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            return
        style = dict(attrs).get("style") or ""
        self._stack.append((tag, tag in _NO_TEXT or bool(_DISPLAY_NONE.search(style))))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text and not any(hidden for _, hidden in self._stack):
            self.nodes.append((self._stack[-1][0] if self._stack else "", text))
