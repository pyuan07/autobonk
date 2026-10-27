"""Turns a Frame into an Observation. DOM-first: HUD and popups are read by visible text."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

from autobonk.frames import Frame

EndScreen = Literal["win", "lose"]

END_TITLES: dict[str, EndScreen] = {"胜利": "win", "你倒下了": "lose"}
COUNTDOWN = re.compile(r"\d{1,2}:\d{2}")


@dataclass(frozen=True)
class Observation:
    end_screen: EndScreen | None
    countdown: str | None

    @property
    def recognised(self) -> bool:
        return self.end_screen is not None or self.countdown is not None


def perceive(frame: Frame) -> Observation:
    texts = visible_texts(frame.dom_snapshot)
    end_screen = next((END_TITLES[t.rstrip("!！")] for t in texts if t.rstrip("!！") in END_TITLES), None)
    countdown = next((t for t in texts if COUNTDOWN.fullmatch(t)), None)
    return Observation(end_screen, countdown)


def visible_texts(html: str) -> list[str]:
    """Text nodes, stripped, skipping scripts/styles and subtrees hidden with inline display:none."""
    parser = _VisibleText()
    parser.feed(html)
    parser.close()
    return parser.texts


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_NO_TEXT = {"script", "style", "svg", "noscript", "template"}
_DISPLAY_NONE = re.compile(r"display\s*:\s*none")


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []
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
            self.texts.append(text)
