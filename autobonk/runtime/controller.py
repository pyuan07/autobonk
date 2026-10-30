"""Turns hotkey events into actions on the main thread."""

import logging
import queue
import time
from typing import Callable, Iterable, Literal, Protocol

from autobonk.commands import Click, Command, Hold, Pause, Press, ReleaseAll, Stop
from autobonk.frames import Frame, FrameRecorder
from autobonk.hub import DashboardHub, hub

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
        dashboard_hub: DashboardHub | None = None,
    ):
        self._capture = capture
        self._step_capture = step_capture or capture
        self._recorder = recorder
        self._driver = driver
        self._bot = bot
        self._watch = watch
        self._hub = dashboard_hub or hub
        self._events: queue.Queue[Event] = queue.Queue()
        self.paused = True

    def submit(self, event: Event) -> None:
        self._events.put(event)

    def poll(self) -> None:
        while True:
            web_action = self._hub.pop_action()
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
        if self.paused:
            self._hub.update_status(
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

        # Sync telemetry with hub via clean status interface
        bot_status = getattr(self._bot, "status", None)
        zone = bot_status.zone if bot_status else ""
        target = bot_status.target if bot_status else ""
        charging = bot_status.charging if bot_status else False

        self._hub.update_status(
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
        self._hub.add_log(f"-> {command}")
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
            self._save_frame()
            self._halt(f"PAUSED ({command.reason})")

    def _halt(self, message: str) -> None:
        self.paused = True
        self._driver.release_all()
        log.info("%s; press the pause hotkey to resume", message)
        self._hub.add_log(message)
        self._hub.update_status(paused=True, connected=True, status_text=message)

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self._driver.release_all()
        state_msg = "PAUSED" if self.paused else "RUNNING"
        log.info("%s (all keys released)", state_msg)
        self._hub.add_log(f"状态切换为: {state_msg}")
        self._hub.update_status(paused=self.paused, connected=True, status_text=state_msg)

    def _save_frame(self) -> None:
        try:
            frame = self._capture()
            path = self._recorder.save(frame)
        except Exception as error:
            log.error("Could not save frame: %s", error)
            return
        log.info("Saved frame %s%s", path, " + minimap" if frame.minimap else " (no minimap)")
