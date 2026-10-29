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
CARD_KEY = re.compile(r"\[(\d)\]")
# The "还有 N 个图像未加载 [重试]" corner notice is not a popup.
IGNORED_BUTTONS = {"重试"}
# Buttons that close a popup without choosing anything.
LEAVE_BUTTONS = ("离开", "以后再说")


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

    @property
    def recognised(self) -> bool:
        return self.end_screen is not None or self.countdown is not None or self.popup is not None


def perceive(frame: Frame) -> Observation:
    nodes = visible_nodes(frame.dom_snapshot)
    texts = [text for _, text in nodes]
    end_screen = next((END_TITLES[t.rstrip("!！")] for t in texts if t.rstrip("!！") in END_TITLES), None)
    countdown = next((t for t in texts if COUNTDOWN.fullmatch(t)), None)
    return Observation(end_screen, countdown, _popup(nodes))


def _popup(nodes: list[tuple[str, str]]) -> Popup | None:
    """A popup is an <h1> followed by buttons or [n] keys; banners are an <h1> with neither.
    Untitled popups (slot machine) are recognised by a leave button alone."""
    for start in reversed([i for i, (tag, _) in enumerate(nodes) if tag == "h1"]):
        body = nodes[start + 1:]
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
