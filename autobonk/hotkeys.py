"""Global OS hotkeys that fire whichever app has focus."""

from typing import Callable

from pynput import keyboard


def start_hotkeys(bindings: dict[str, Callable[[], None]]) -> keyboard.GlobalHotKeys:
    """Start listening for single keys like "f8". Callbacks run on the listener's thread."""
    listener = keyboard.GlobalHotKeys({f"<{key}>": callback for key, callback in bindings.items()})
    listener.start()
    return listener
