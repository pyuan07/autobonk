"""Watches the player answer popups while the bot is paused, so their picks can be studied.

Each pick is appended to a JSONL file: the popup title, every card offered (with its effect
text) and the key pressed or card clicked.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from autobonk.perception import Popup

# Collects the player's keys and clicks in the page; `DRAIN_INPUTS_SCRIPT` hands them over.
RECORD_INPUTS_SCRIPT = """
(() => {
  window.__autobonkInputs = [];
  window.addEventListener('keydown', (event) => {
    if (!event.repeat) window.__autobonkInputs.push({kind: 'key', value: event.key});
  }, true);
  window.addEventListener('click', (event) => {
    const target = event.target.closest('button') || event.target;
    window.__autobonkInputs.push({kind: 'click', value: (target.innerText || '').trim()});
  }, true);
})();
"""
DRAIN_INPUTS_SCRIPT = "() => (window.__autobonkInputs || []).splice(0)"
# Buttons that only show information and don't answer the popup.
VIEW_BUTTONS = {"查看我的队伍"}


@dataclass(frozen=True)
class Input:
    kind: Literal["key", "click"]
    value: str


class ChoiceLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._showing: Popup | None = None  # the popup the player was looking at

    def observe(self, popup: Popup | None, inputs: list[Input], timestamp: float) -> None:
        """`inputs` happened since the previous call, so they answer the popup seen then."""
        if self._showing:
            for player_input in inputs:
                picked = _picked(self._showing, player_input)
                if picked:
                    self._write(self._showing, player_input, picked, timestamp)
                    break
        self._showing = popup

    def _write(self, popup: Popup, player_input: Input, picked: str, timestamp: float) -> None:
        entry = {
            "time": datetime.fromtimestamp(timestamp).isoformat(timespec="seconds"),
            "title": popup.title,
            "offered": [asdict(card) for card in popup.cards],
            "input": player_input.value,
            "picked": picked,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _picked(popup: Popup, player_input: Input) -> str | None:
    """The card or button the input chose, or None if it chose nothing on this popup."""
    buttons = [b for b in popup.buttons if b.text not in VIEW_BUTTONS]
    if player_input.kind == "key":
        key = player_input.value.lower()
        card = next((c for c in popup.cards if c.key and c.key == key), None)
        if card:
            return card.name
        button = next((b for b in buttons if b.key and _cap(b.key) == key), None)
        return button.text if button else None
    card = next((c for c in popup.cards if c.name and c.name in player_input.value), None)
    if card:
        return card.name
    button = next((b for b in buttons if b.text in player_input.value), None)
    return button.text if button else None


def _cap(key_cap: str) -> str:
    """Key cap as shown ("E", "Esc") -> KeyboardEvent.key, lower-cased."""
    return "escape" if key_cap == "Esc" else key_cap.lower()
