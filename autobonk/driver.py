"""Executes commands through Playwright's keyboard and mouse (CDP, so the window needn't be focused)."""

from typing import Iterable, Protocol

from playwright.sync_api import Page

# A popup button that isn't clickable this soon is a perception mistake; fail fast and pause.
CLICK_TIMEOUT_MS = 1000


class Keyboard(Protocol):
    def down(self, key: str) -> None: ...

    def up(self, key: str) -> None: ...


class KeyboardDriver:
    def __init__(self, keyboard: Keyboard, page: Page | None = None):
        self._keyboard = keyboard
        self._page = page
        self._held: set[str] = set()

    def hold(self, keys: Iterable[str]) -> None:
        """Hold exactly `keys`: release held keys not among them, press the new ones."""
        keys = set(keys)
        for key in self._held - keys:
            self._keyboard.up(key)
            self._held.discard(key)
        for key in keys:
            if key not in self._held:
                self._keyboard.down(key)
                self._held.add(key)

    def press(self, key: str) -> None:
        self._keyboard.down(key)
        self._keyboard.up(key)

    def click(self, text: str) -> None:
        """Click the visible element whose text is exactly `text` (e.g. a popup button)."""
        if self._page is None:
            raise RuntimeError("this driver has no page to click on")
        self._page.get_by_text(text, exact=True).filter(visible=True).first.click(timeout=CLICK_TIMEOUT_MS)

    def release_all(self) -> None:
        held, self._held = self._held, set()
        for key in held:
            self._keyboard.up(key)
