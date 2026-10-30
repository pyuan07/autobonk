"""Turns a Frame into an Observation. DOM-first: HUD and popups are read by visible text."""

from autobonk.perception.dom import (
    BANISH_RE,
    CHARGE,
    COUNTDOWN,
    END_TITLES,
    IGNORED_BUTTONS,
    LEAVE_BUTTONS,
    REROLL_RE,
    SEALED,
    SKIP_RE,
    Button,
    EndScreen,
    Observation,
    Popup,
    perceive,
)

__all__ = [
    "BANISH_RE",
    "CHARGE",
    "COUNTDOWN",
    "END_TITLES",
    "IGNORED_BUTTONS",
    "LEAVE_BUTTONS",
    "REROLL_RE",
    "SEALED",
    "SKIP_RE",
    "Button",
    "EndScreen",
    "Observation",
    "Popup",
    "perceive",
]
