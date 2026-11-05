"""Command types emitted by policy (Bot) and executed by the driver."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseAll:
    """Release all currently held keys."""
    pass


@dataclass(frozen=True)
class Stop:
    """Stop the bot loop (e.g. game over or victory)."""
    reason: str


@dataclass(frozen=True)
class Pause:
    """Pause the bot and request user intervention."""
    reason: str


@dataclass(frozen=True)
class Press:
    """Press and release a key."""
    key: str


@dataclass(frozen=True)
class Click:
    """Click on text or an element in the game."""
    text: str
    selector: str | None = None


@dataclass(frozen=True)
class Hold:
    """Hold exactly these keys (releasing any others) until the next Hold or ReleaseAll."""
    keys: frozenset[str]


Command = ReleaseAll | Stop | Pause | Press | Click | Hold
