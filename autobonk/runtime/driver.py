"""Executes commands through Playwright's keyboard and mouse."""

from collections.abc import Iterable
from typing import Protocol

from playwright.sync_api import Page

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

    def click(self, text: str, selector: str | None = None) -> None:
        if self._page is None:
            raise RuntimeError("this driver has no page to click on")
        locator = self._page.locator(selector) if selector else self._page.get_by_text(text, exact=True)
        # Compute layout box and dispatch a real CDP mouse click (isTrusted === true) without
        # Locator.click()'s compositor-frame wait, which would hang while the window is minimized.
        box = locator.filter(visible=True).first.bounding_box(timeout=CLICK_TIMEOUT_MS)
        if box is None:
            raise TimeoutError(f"Element has no bounding box: {selector or text}")
        self._page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    def release_all(self) -> None:
        held, self._held = self._held, set()
        for key in held:
            self._keyboard.up(key)
