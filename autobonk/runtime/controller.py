"""Turns hotkey events into actions on the main thread."""

import logging
import queue
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal, Protocol

from autobonk.commands import Click, Command, Hold, Pause, Press, ReleaseAll, Stop
from autobonk.dashboard.hub import DashboardHub, hub
from autobonk.runtime.frames import Frame, FrameRecorder

log = logging.getLogger(__name__)

Event = Literal["toggle_pause", "save_frame"]


class Driver(Protocol):
    def release_all(self) -> None: ...

    def hold(self, keys: Iterable[str]) -> None: ...

    def press(self, key: str) -> None: ...

    def click(self, text: str, selector: str | None = None) -> None: ...


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
        self._config_path: Path | None = None
        self._config_mtime: float = 0.0

    def submit(self, event: Event) -> None:
        self._events.put(event)

    def poll(self) -> None:
        self._check_reload()
        while True:
            web_action = self._hub.pop_action()
            if web_action == "start" and self.paused or web_action == "pause" and not self.paused or web_action == "toggle_pause":
                self._toggle_pause()

            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return
            if event == "toggle_pause":
                self._toggle_pause()
            elif event == "save_frame":
                self._save_frame()

    def set_config_path(self, path: Path) -> None:
        self._config_path = Path(path)
        if self._config_path.exists():
            self._config_mtime = self._config_path.stat().st_mtime

    def _check_reload(self) -> None:
        if not self._config_path or not self._config_path.exists():
            return
        try:
            mtime = self._config_path.stat().st_mtime
            if mtime > self._config_mtime:
                self._config_mtime = mtime
                self.reload_config()
        except OSError:
            pass

    def reload_config(self) -> None:
        if not self._config_path or not self._config_path.exists():
            return
        try:
            from autobonk.config import load_config
            cfg = load_config(self._config_path)
            if hasattr(self._bot, "reload_config"):
                self._bot.reload_config(
                    cards=cfg.cards,
                    targets=cfg.targets,
                    boss=cfg.boss,
                    movement=cfg.movement,
                    banish_threshold=cfg.banish_threshold,
                    reroll_threshold=cfg.reroll_threshold,
                    skip_threshold=cfg.skip_threshold,
                    plan_fallback_reroll_threshold=cfg.plan_fallback_reroll_threshold,
                    sub_target_base_allowance=cfg.sub_target_base_allowance,
                    sub_target_weight_factor=cfg.sub_target_weight_factor,
                    auto_restart=cfg.auto_restart,
                    max_runs=cfg.max_runs,
                    restart_load_s=cfg.restart_load_s,
                )
                self._hub.add_log("配置热重载成功: autobonk.toml 已更新")
                log.info("Hot-reloaded config from %s", self._config_path)
        except Exception as error:
            log.error("Failed to hot-reload config: %s", error)
            self._hub.add_log(f"配置重载失败: {error}")

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
        status_getter = getattr(self._bot, "status", None)
        bot_status = status_getter() if callable(status_getter) else None

        self._hub.update_status(
            paused=False,
            connected=True,
            zone=getattr(bot_status, "zone", "") if bot_status else "",
            level=getattr(bot_status, "level", None) if bot_status else None,
            countdown=getattr(bot_status, "countdown", "") if bot_status else "",
            seconds_left=getattr(bot_status, "seconds_left", None) if bot_status else None,
            target=getattr(bot_status, "target", "") if bot_status else "",
            target_distance=getattr(bot_status, "target_distance", None) if bot_status else None,
            status_text=f"执行中 ({len(commands)} 指令)" if commands else "规划中",
            step_duration_ms=round(step_ms, 1),
            charging=getattr(bot_status, "charging", False) if bot_status else False,
            stuck_seconds=round(getattr(bot_status, "stuck_seconds", 0.0), 1) if bot_status else 0.0,
            commands=[str(c) for c in commands],
            boss_phase=getattr(bot_status, "boss_phase", "waiting") if bot_status else "waiting",
            boss_ready=getattr(bot_status, "boss_ready", False) if bot_status else False,
            nav_mode=getattr(bot_status, "nav_mode", "minimap") if bot_status else "minimap",
            held_keys=sorted(getattr(bot_status, "held", [])) if bot_status else [],
            main_target=getattr(bot_status, "main_target", "") if bot_status else "",
            sub_target=getattr(bot_status, "sub_target", "") if bot_status else "",
            sub_target_distance=getattr(bot_status, "sub_target_distance", None) if bot_status else None,
            runs=getattr(bot_status, "runs", 0) if bot_status else 0,
            wins=getattr(bot_status, "wins", 0) if bot_status else 0,
            losses=getattr(bot_status, "losses", 0) if bot_status else 0,
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
            self._driver.click(command.text, selector=command.selector)
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
