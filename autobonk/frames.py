"""Frames: what the bot sees at one instant (screenshot + DOM snapshot + timestamp).

A saved frame is three files sharing a stem: `<stem>.png`, `<stem>.html`, `<stem>.json`.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True)
class Frame:
    screenshot: bytes
    dom_snapshot: str
    timestamp: float
    url: str


class Page(Protocol):
    @property
    def url(self) -> str: ...

    def screenshot(self) -> bytes: ...

    def content(self) -> str: ...


def capture_frame(page: Page, clock: Callable[[], float] = time.time) -> Frame:
    timestamp = clock()
    return Frame(page.screenshot(), page.content(), timestamp, page.url)


class FrameRecorder:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def save(self, frame: Frame) -> Path:
        """Write `frame` under a unique stem; return the stem path (no suffix)."""
        self.directory.mkdir(parents=True, exist_ok=True)
        stem = self._unique_stem(frame.timestamp)
        _file(stem, ".png").write_bytes(frame.screenshot)
        _file(stem, ".html").write_text(frame.dom_snapshot, encoding="utf-8")
        meta = {
            "timestamp": frame.timestamp,
            "time": datetime.fromtimestamp(frame.timestamp).isoformat(timespec="milliseconds"),
            "url": frame.url,
        }
        _file(stem, ".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return stem

    def _unique_stem(self, timestamp: float) -> Path:
        moment = datetime.fromtimestamp(timestamp)
        base = f"frame-{moment:%Y%m%d-%H%M%S}-{moment.microsecond // 1000:03d}"
        stem, n = self.directory / base, 1
        while _file(stem, ".json").exists():
            n += 1
            stem = self.directory / f"{base}-{n}"
        return stem


def load_frame(stem: Path) -> Frame:
    stem = Path(stem)
    meta = json.loads(_file(stem, ".json").read_text(encoding="utf-8"))
    return Frame(
        screenshot=_file(stem, ".png").read_bytes(),
        dom_snapshot=_file(stem, ".html").read_text(encoding="utf-8"),
        timestamp=meta["timestamp"],
        url=meta["url"],
    )


def _file(stem: Path, suffix: str) -> Path:
    return stem.parent / (stem.name + suffix)
