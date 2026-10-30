"""Watches player popup answers while bot is paused to record choice data."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from autobonk.perception.dom import Popup

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
VIEW_BUTTONS = {"查看我的队伍"}


@dataclass(frozen=True)
class Input:
    kind: Literal["key", "click"]
    value: str


class ChoiceLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._showing: Popup | None = None

    def observe(self, popup: Popup | None, inputs: list[Input], timestamp: float) -> None:
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
    return "escape" if key_cap == "Esc" else key_cap.lower()
