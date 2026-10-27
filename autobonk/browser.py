"""Launches the installed Chrome on a dedicated, persistent profile, tuned to keep running in the background."""

from playwright.sync_api import BrowserContext, Playwright

from autobonk.config import Config

# Playwright already passes the first three by default; they are listed so the intent survives
# Playwright changes. Chrome honours only the last --disable-features switch, so this one
# replaces Playwright's default list: keep the entries that matter for an interactive session.
BACKGROUND_ARGS = [
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--disable-features=CalculateNativeWinOcclusion,Translate,MediaRouter,OptimizationHints",
]

# Runs before any page script: the page always believes it is visible and focused, and
# never hears window blur or visibilitychange, so the game doesn't auto-pause.
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

# Room for the tab strip and address bar around the fixed viewport.
WINDOW_CHROME_WIDTH, WINDOW_CHROME_HEIGHT = 16, 140


def launch(playwright: Playwright, config: Config) -> BrowserContext:
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
        # Drops the "controlled by automated software" bar, which would steal vertical space.
        ignore_default_args=["--enable-automation"],
    )
    context.add_init_script(KEEP_FOCUSED_SCRIPT)
    return context
