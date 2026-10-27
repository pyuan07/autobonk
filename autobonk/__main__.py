"""`python -m autobonk`: open PokéBonk in Chrome and listen for the global hotkeys."""

import argparse
import logging
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from autobonk.browser import launch
from autobonk.config import load_config
from autobonk.controller import Controller
from autobonk.driver import KeyboardDriver
from autobonk.frames import FrameRecorder, capture_frame
from autobonk.hotkeys import start_hotkeys

log = logging.getLogger("autobonk")

POLL_MS = 50


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="autobonk", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("autobonk.toml"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    config = load_config(args.config)

    with sync_playwright() as playwright:
        context = launch(playwright, config)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(config.url)

        driver = KeyboardDriver(page.keyboard)
        controller = Controller(
            capture=lambda: capture_frame(page),
            recorder=FrameRecorder(config.frames_dir),
            driver=driver,
        )
        listener = start_hotkeys({
            config.pause_hotkey: lambda: controller.submit("toggle_pause"),
            config.frame_hotkey: lambda: controller.submit("save_frame"),
        })
        log.info(
            "Ready. %s = pause/resume, %s = save frame to %s. Close the browser or Ctrl+C to quit.",
            config.pause_hotkey.upper(), config.frame_hotkey.upper(), config.frames_dir,
        )
        log.info("PAUSED")

        try:
            while not page.is_closed():
                controller.poll()
                page.wait_for_timeout(POLL_MS)
        except KeyboardInterrupt:
            pass
        except PlaywrightError as error:
            if not page.is_closed():
                raise
            log.debug("Page closed: %s", error)
        finally:
            listener.stop()
            # Either step fails harmlessly if the browser is already gone.
            for cleanup in (driver.release_all, context.close):
                try:
                    cleanup()
                except PlaywrightError:
                    pass
        log.info("Bye.")


if __name__ == "__main__":
    main()
