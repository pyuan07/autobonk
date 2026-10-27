"""User-editable settings, loaded from a TOML file with defaults for anything missing."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    url: str
    profile_dir: Path
    viewport_width: int
    viewport_height: int
    frames_dir: Path
    pause_hotkey: str
    frame_hotkey: str


def load_config(path: Path) -> Config:
    """Load `path`; relative paths in it resolve against the file's folder."""
    path = Path(path)
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    base = path.parent

    browser = data.get("browser", {})
    frames = data.get("frames", {})
    hotkeys = data.get("hotkeys", {})
    pause_hotkey = hotkeys.get("pause", "f8").lower()
    frame_hotkey = hotkeys.get("frame", "f9").lower()
    if pause_hotkey == frame_hotkey:
        raise ValueError(f"{path}: pause and frame hotkeys are both {pause_hotkey!r}")
    return Config(
        url=browser.get("url", "https://pokebonk.com/"),
        profile_dir=base / browser.get("profile_dir", "profile"),
        viewport_width=browser.get("viewport_width", 1600),
        viewport_height=browser.get("viewport_height", 900),
        frames_dir=base / frames.get("dir", "fixtures/frames"),
        pause_hotkey=pause_hotkey,
        frame_hotkey=frame_hotkey,
    )
