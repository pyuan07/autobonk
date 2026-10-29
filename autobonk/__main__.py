"""`python -m autobonk`: open PokéBonk in Chrome and listen for the global hotkeys."""

import argparse
import logging
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from autobonk.bot import Bot
from autobonk.browser import launch
from autobonk.choices import DRAIN_INPUTS_SCRIPT, RECORD_INPUTS_SCRIPT, ChoiceLog, Input
from autobonk.config import load_config
from autobonk.controller import Controller
from autobonk.driver import KeyboardDriver
from autobonk.frames import Frame, FrameRecorder, capture_frame
from autobonk.perception import perceive
from autobonk.hotkeys import start_hotkeys

log = logging.getLogger("autobonk")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="autobonk", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("autobonk.toml"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    config = load_config(args.config)

    with sync_playwright() as playwright:
        context = launch(playwright, config)
        page = context.pages[0] if context.pages else context.new_page()
        context.add_init_script(RECORD_INPUTS_SCRIPT)
        page.goto(config.url)

        cdp = context.new_cdp_session(page)
        driver = KeyboardDriver(page.keyboard, page)
        choice_log = ChoiceLog(config.choices_file)

        def watch_player() -> None:
            """While paused: log which popup cards the player picks (DOM only, no screenshot)."""
            inputs = [Input(i["kind"], i["value"]) for i in page.evaluate(DRAIN_INPUTS_SCRIPT)]
            now = time.time()
            choice_log.observe(perceive(Frame(b"", page.content(), now, page.url)).popup, inputs, now)

        controller = Controller(
            capture=lambda: capture_frame(page, cdp),
            recorder=FrameRecorder(config.frames_dir),
            driver=driver,
            bot=Bot(config.unknown_screen_pause_s, config.cards),
            step_capture=lambda: capture_frame(page, cdp, fast=True),
            watch=watch_player,
        )
        listener = start_hotkeys({
            config.pause_hotkey: lambda: controller.submit("toggle_pause"),
            config.frame_hotkey: lambda: controller.submit("save_frame"),
        })
        log.info(
            "Ready. %s = start/pause the bot, %s = save frame to %s. Close the browser or Ctrl+C to quit.",
            config.pause_hotkey.upper(), config.frame_hotkey.upper(), config.frames_dir,
        )
        log.info("PAUSED")

        try:
            step_s = 1 / config.steps_per_second
            while not page.is_closed():
                started = time.monotonic()
                controller.poll()
                controller.tick()
                # wait_for_timeout keeps Playwright's event loop pumping, unlike time.sleep.
                page.wait_for_timeout(max(10, (step_s - (time.monotonic() - started)) * 1000))
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
