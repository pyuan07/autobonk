"""The bot: `Bot.step(frame) -> commands`, the one seam between perception/policy and the driver."""

import logging
from dataclasses import dataclass

from autobonk.frames import Frame
from autobonk.perception import Observation, perceive

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReleaseAll:
    pass


@dataclass(frozen=True)
class Stop:
    reason: str


@dataclass(frozen=True)
class Pause:
    reason: str


Command = ReleaseAll | Stop | Pause


class Bot:
    def __init__(self, unknown_screen_pause_s: float = 5.0):
        self._unknown_screen_pause_s = unknown_screen_pause_s
        self._unrecognised_since: float | None = None
        self._last_state: str | None = None

    def step(self, frame: Frame) -> list[Command]:
        observation = perceive(frame)
        self._log_state_change(observation)

        if observation.end_screen:
            return [ReleaseAll(), Stop(observation.end_screen)]

        if observation.recognised:
            self._unrecognised_since = None
            return []

        if self._unrecognised_since is None:
            self._unrecognised_since = frame.timestamp
        if frame.timestamp - self._unrecognised_since >= self._unknown_screen_pause_s:
            self._unrecognised_since = None
            return [ReleaseAll(), Pause(f"screen unrecognised for {self._unknown_screen_pause_s:g} s")]
        return []

    def _log_state_change(self, observation: Observation) -> None:
        state = observation.end_screen or ("playing" if observation.recognised else "unrecognised")
        if state != self._last_state:
            log.info("state: %s%s", state, f" (countdown {observation.countdown})" if observation.countdown else "")
            self._last_state = state
