"""Turns hotkey events into actions on the main thread.

Hotkey callbacks fire on the OS listener's thread, but Playwright's sync API must only be
used from the thread that created it, so callbacks only `submit()` and the main loop `poll()`s.
"""

import logging
import queue
from typing import Callable, Literal, Protocol

from autobonk.bot import Command, Pause, ReleaseAll, Stop
from autobonk.frames import Frame, FrameRecorder

log = logging.getLogger(__name__)

Event = Literal["toggle_pause", "save_frame"]


class Driver(Protocol):
    def release_all(self) -> None: ...


class StepsFrames(Protocol):
    def step(self, frame: Frame) -> list[Command]: ...


class Controller:
    def __init__(
        self,
        capture: Callable[[], Frame],
        recorder: FrameRecorder,
        driver: Driver,
        bot: StepsFrames,
        step_capture: Callable[[], Frame] | None = None,
    ):
        """`capture` feeds saved frames; `step_capture` (default: `capture`) feeds bot steps."""
        self._capture = capture
        self._step_capture = step_capture or capture
        self._recorder = recorder
        self._driver = driver
        self._bot = bot
        self._events: queue.Queue[Event] = queue.Queue()
        # Paused until the player hands over with the pause hotkey.
        self.paused = True

    def submit(self, event: Event) -> None:
        """Thread-safe: queue an event for the next `poll()`."""
        self._events.put(event)

    def poll(self) -> None:
        """Handle every queued event. Call from the main (Playwright) thread."""
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return
            if event == "toggle_pause":
                self._toggle_pause()
            elif event == "save_frame":
                self._save_frame()

    def tick(self) -> None:
        """Run one bot step if running. Call from the main (Playwright) thread."""
        if self.paused:
            return
        try:
            commands = self._bot.step(self._step_capture())
        except Exception as error:
            self._halt(f"PAUSED (bot step failed: {error})")
            return
        for command in commands:
            self._execute(command)

    def _execute(self, command: Command) -> None:
        log.info("-> %s", command)
        if isinstance(command, ReleaseAll):
            self._driver.release_all()
        elif isinstance(command, Stop):
            self._halt(f"STOPPED ({command.reason})")
        elif isinstance(command, Pause):
            self._halt(f"PAUSED ({command.reason})")

    def _halt(self, message: str) -> None:
        self.paused = True
        self._driver.release_all()
        log.info("%s; press the pause hotkey to resume", message)

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self._driver.release_all()
        log.info("%s (all keys released)", "PAUSED" if self.paused else "RUNNING")

    def _save_frame(self) -> None:
        try:
            path = self._recorder.save(self._capture())
        except Exception as error:
            log.error("Could not save frame: %s", error)
            return
        log.info("Saved frame %s", path)
