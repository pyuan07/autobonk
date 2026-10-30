"""Turns hotkey events into actions on the main thread.

Hotkey callbacks fire on the OS listener's thread, but Playwright's sync API must only be
used from the thread that created it, so callbacks only `submit()` and the main loop `poll()`s.
"""

import logging
import queue
import time
from typing import Callable, Iterable, Literal, Protocol

from autobonk.bot import Click, Command, Hold, Pause, Press, ReleaseAll, Stop
from autobonk.frames import Frame, FrameRecorder
from autobonk.hub import hub

log = logging.getLogger(__name__)

Event = Literal["toggle_pause", "save_frame"]


class Driver(Protocol):
    def release_all(self) -> None: ...

    def hold(self, keys: Iterable[str]) -> None: ...

    def press(self, key: str) -> None: ...

    def click(self, text: str) -> None: ...


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
        watch: Callable[[], None] | None = None,
    ):
        """`capture` feeds saved frames; `step_capture` (default: `capture`) feeds bot steps;
        `watch` runs instead of a bot step while paused (the player is playing)."""
        self._capture = capture
        self._step_capture = step_capture or capture
        self._recorder = recorder
        self._driver = driver
        self._bot = bot
        self._watch = watch
        self._events: queue.Queue[Event] = queue.Queue()
        # Paused until the player hands over with the pause hotkey.
        self.paused = True

    def submit(self, event: Event) -> None:
        """Thread-safe: queue an event for the next `poll()`."""
        self._events.put(event)

    def poll(self) -> None:
        """Handle every queued event. Call from the main (Playwright) thread."""
        while True:
            # Check web hub requests first
            web_action = hub.pop_action()
            if web_action == "start" and self.paused:
                self._toggle_pause()
            elif web_action == "pause" and not self.paused:
                self._toggle_pause()
            elif web_action == "toggle_pause":
                self._toggle_pause()

            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return
            if event == "toggle_pause":
                self._toggle_pause()
            elif event == "save_frame":
                self._save_frame()

    def tick(self) -> None:
        """Run one bot step if running, else watch the player. Call from the main (Playwright) thread."""
        if self.paused:
            hub.update_status(
                paused=True,
                connected=True,
                status_text="已暂停",
            )
            if self._watch:
                try:
                    self._watch()
                except Exception as error:
                    log.error("Watching the player failed: %s", error)
            return
        t0 = time.monotonic()
        try:
            frame = self._step_capture()
            commands = self._bot.step(frame)
        except Exception as error:
            self._halt(f"PAUSED (bot step failed: {error})")
            return
        step_ms = (time.monotonic() - t0) * 1000.0

        # Sync telemetry with hub
        bot_obj = getattr(self._bot, "_bot", self._bot)
        zone = getattr(bot_obj, "_zone", "") or ""
        target = getattr(bot_obj, "_target", "") or ""
        charging = getattr(bot_obj, "_charging_since", None) is not None
        hub.update_status(
            paused=False,
            connected=True,
            zone=zone,
            target=target,
            status_text=f"执行中 ({len(commands)} 指令)" if commands else "规划中",
            step_duration_ms=round(step_ms, 1),
            charging=charging,
            commands=[str(c) for c in commands],
        )

        for command in commands:
            try:
                self._execute(command)
            except Exception as error:
                self._halt(f"PAUSED ({command} failed: {error})")
                return

    def _execute(self, command: Command) -> None:
        log.info("-> %s", command)
        hub.add_log(f"-> {command}")
        if isinstance(command, ReleaseAll):
            self._driver.release_all()
        elif isinstance(command, Hold):
            self._driver.hold(command.keys)
        elif isinstance(command, Press):
            self._driver.press(command.key)
        elif isinstance(command, Click):
            self._driver.click(command.text)
        elif isinstance(command, Stop):
            self._halt(f"STOPPED ({command.reason})")
        elif isinstance(command, Pause):
            self._save_frame()  # keep the screen the bot couldn't handle, to teach it later
            self._halt(f"PAUSED ({command.reason})")

    def _halt(self, message: str) -> None:
        self.paused = True
        self._driver.release_all()
        log.info("%s; press the pause hotkey to resume", message)
        hub.add_log(message)
        hub.update_status(paused=True, connected=True, status_text=message)

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self._driver.release_all()
        state_msg = "PAUSED" if self.paused else "RUNNING"
        log.info("%s (all keys released)", state_msg)
        hub.add_log(f"状态切换为: {state_msg}")
        hub.update_status(paused=self.paused, connected=True, status_text=state_msg)

    def _save_frame(self) -> None:
        try:
            frame = self._capture()
            path = self._recorder.save(frame)
        except Exception as error:
            log.error("Could not save frame: %s", error)
            return
        log.info("Saved frame %s%s", path, " + minimap" if frame.minimap else " (no minimap)")
