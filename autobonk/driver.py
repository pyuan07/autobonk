"""Executes key commands through Playwright's keyboard (CDP, so the window needn't be focused)."""

from typing import Iterable, Protocol


class Keyboard(Protocol):
    def down(self, key: str) -> None: ...

    def up(self, key: str) -> None: ...


class KeyboardDriver:
    def __init__(self, keyboard: Keyboard):
        self._keyboard = keyboard
        self._held: set[str] = set()

    def hold(self, keys: Iterable[str]) -> None:
        for key in keys:
            if key not in self._held:
                self._keyboard.down(key)
                self._held.add(key)

    def release_all(self) -> None:
        held, self._held = self._held, set()
        for key in held:
            self._keyboard.up(key)
