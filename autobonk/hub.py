"""Central state hub shared between the bot controller and the local web dashboard."""

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class BotState:
    paused: bool = True
    connected: bool = False
    zone: str = ""
    level: int | None = None
    countdown: str = ""
    seconds_left: int | None = None
    target: str = ""
    target_distance: float | None = None
    status_text: str = "未连接"
    step_duration_ms: float = 0.0
    charging: bool = False
    stuck_seconds: float = 0.0
    recent_commands: list[str] = field(default_factory=list)
    recent_logs: list[str] = field(default_factory=list)


class DashboardHub:
    """Thread-safe hub to read bot status and dispatch control events (start/pause)."""

    def __init__(self, max_logs: int = 50):
        self._lock = threading.Lock()
        self._state = BotState()
        self._logs: deque[str] = deque(maxlen=max_logs)
        self._action_queue: deque[str] = deque()

    def update_status(
        self,
        *,
        paused: bool,
        connected: bool = True,
        zone: str = "",
        level: int | None = None,
        countdown: str = "",
        seconds_left: int | None = None,
        target: str = "",
        target_distance: float | None = None,
        status_text: str = "",
        step_duration_ms: float = 0.0,
        charging: bool = False,
        stuck_seconds: float = 0.0,
        commands: list[str] | None = None,
    ) -> None:
        with self._lock:
            self._state.paused = paused
            self._state.connected = connected
            self._state.zone = zone
            self._state.level = level
            self._state.countdown = countdown
            self._state.seconds_left = seconds_left
            self._state.target = target
            self._state.target_distance = target_distance
            self._state.status_text = status_text
            self._state.step_duration_ms = step_duration_ms
            self._state.charging = charging
            self._state.stuck_seconds = stuck_seconds
            if commands is not None:
                self._state.recent_commands = commands

    def add_log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        with self._lock:
            self._logs.append(entry)

    def get_snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = asdict(self._state)
            data["recent_logs"] = list(self._logs)
            return data

    def request_action(self, action: str) -> None:
        with self._lock:
            self._action_queue.append(action)

    def pop_action(self) -> str | None:
        with self._lock:
            if self._action_queue:
                return self._action_queue.popleft()
            return None


hub = DashboardHub()
