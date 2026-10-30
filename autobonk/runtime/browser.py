"""Launches installed Chrome with persistent profile and anti-throttling flags."""

from pathlib import Path
from typing import Protocol

from playwright.sync_api import BrowserContext, Playwright

BACKGROUND_ARGS = [
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--disable-features=CalculateNativeWinOcclusion,Translate,MediaRouter,OptimizationHints",
]

KEEP_FOCUSED_SCRIPT = """
(() => {
  Object.defineProperty(Document.prototype, 'hidden', { get: () => false, configurable: true });
  Object.defineProperty(Document.prototype, 'visibilityState', { get: () => 'visible', configurable: true });
  Document.prototype.hasFocus = () => true;
  const swallow = (event) => {
    if (event.target === window || event.target === document) event.stopImmediatePropagation();
  };
  window.addEventListener('blur', swallow, true);
  document.addEventListener('visibilitychange', swallow, true);
  window.addEventListener('visibilitychange', swallow, true);
})();
"""

WINDOW_CHROME_WIDTH, WINDOW_CHROME_HEIGHT = 16, 140


class BrowserConfig(Protocol):
    @property
    def profile_dir(self) -> Path: ...

    @property
    def viewport_width(self) -> int: ...

    @property
    def viewport_height(self) -> int: ...


def launch(playwright: Playwright, config: BrowserConfig) -> BrowserContext:
    config.profile_dir.mkdir(parents=True, exist_ok=True)
    width, height = config.viewport_width, config.viewport_height
    context = playwright.chromium.launch_persistent_context(
        config.profile_dir,
        channel="chrome",
        headless=False,
        viewport={"width": width, "height": height},
        args=[
            *BACKGROUND_ARGS,
            f"--window-size={width + WINDOW_CHROME_WIDTH},{height + WINDOW_CHROME_HEIGHT}",
        ],
        ignore_default_args=["--enable-automation"],
    )
    context.add_init_script(KEEP_FOCUSED_SCRIPT)
    return context
