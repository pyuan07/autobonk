"""Application runner: wires browser, controller, dashboard, hotkeys, and main loop."""

import logging
import threading
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from autobonk.config import Config, load_config
from autobonk.dashboard.hub import hub
from autobonk.dashboard.server import run_editor
from autobonk.runtime.frames import Frame, FrameRecorder, capture_frame
from autobonk.perception.dom import perceive
from autobonk.policy.bot import Bot
from autobonk.runtime.browser import launch
from autobonk.runtime.choices import DRAIN_INPUTS_SCRIPT, RECORD_INPUTS_SCRIPT, ChoiceLog, Input
from autobonk.runtime.controller import Controller
from autobonk.runtime.driver import KeyboardDriver
from autobonk.runtime.hotkeys import start_hotkeys

log = logging.getLogger("autobonk")


def run(config_path: Path = Path("autobonk.toml"), open_dashboard: bool = False) -> None:
    config = load_config(config_path)

    # Start dashboard server on a daemon thread so it's always accessible
    server = run_editor(config_path, port=8080, open_browser=open_dashboard)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    with sync_playwright() as playwright:
        context = launch(playwright, config)
        page = context.pages[0] if context.pages else context.new_page()
        context.add_init_script(RECORD_INPUTS_SCRIPT)
        page.goto(config.url)

        cdp = context.new_cdp_session(page)
        driver = KeyboardDriver(page.keyboard, page)
        choice_log = ChoiceLog(config.choices_file)

        def watch_player() -> None:
            """While paused: log which popup cards player picks (DOM only, no screenshot)."""
            inputs = [Input(i["kind"], i["value"]) for i in page.evaluate(DRAIN_INPUTS_SCRIPT)]
            now = time.time()
            choice_log.observe(perceive(Frame(b"", page.content(), now, page.url)).popup, inputs, now)

        bot = Bot(
            unknown_screen_pause_s=config.unknown_screen_pause_s,
            cards=config.cards,
            movement=config.movement,
            targets=config.targets,
            boss=config.boss,
            banish_threshold=config.banish_threshold,
            reroll_threshold=config.reroll_threshold,
            skip_threshold=config.skip_threshold,
        )

        controller = Controller(
            capture=lambda: capture_frame(page, cdp),
            recorder=FrameRecorder(config.frames_dir),
            driver=driver,
            bot=bot,
            step_capture=lambda: capture_frame(page, cdp, fast=True),
            watch=watch_player,
            dashboard_hub=hub,
        )

        listener = start_hotkeys({
            config.pause_hotkey: lambda: controller.submit("toggle_pause"),
            config.frame_hotkey: lambda: controller.submit("save_frame"),
        })

        log.info(
            "Ready. %s = start/pause the bot, %s = save frame to %s. Close the browser or Ctrl+C to quit.",
            config.pause_hotkey.upper(),
            config.frame_hotkey.upper(),
            config.frames_dir,
        )
        log.info("PAUSED")

        try:
            step_s = 1 / config.steps_per_second
            while not page.is_closed():
                started = time.monotonic()
                controller.poll()
                controller.tick()
                page.wait_for_timeout(max(10, (step_s - (time.monotonic() - started)) * 1000))
        except KeyboardInterrupt:
            pass
        except PlaywrightError as error:
            if not page.is_closed():
                raise
            log.debug("Page closed: %s", error)
        finally:
            listener.stop()
            for cleanup in (driver.release_all, context.close):
                try:
                    cleanup()
                except PlaywrightError:
                    pass
        log.info("Bye.")
