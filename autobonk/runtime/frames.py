"""Frames: what the bot sees at one instant (screenshot + DOM snapshot + map canvases + timestamp)."""

import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class Frame:
    screenshot: bytes
    dom_snapshot: str
    timestamp: float
    url: str
    minimap: bytes = b""
    zonemap: bytes = b""


class Page(Protocol):
    @property
    def url(self) -> str: ...

    def content(self) -> str: ...

    def evaluate(self, expression: str) -> Any: ...


CANVAS_SCRIPT = """() => {
  try { return document.querySelector('%s')?.toDataURL('image/png') ?? ''; }
  catch (error) { return ''; }
}"""
MINIMAP_SCRIPT = CANVAS_SCRIPT % "canvas.minimap"
ZONEMAP_SCRIPT = CANVAS_SCRIPT % "canvas.bm-cv"


class CdpSession(Protocol):
    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...


def capture_frame(page: Page, cdp: CdpSession, clock: Callable[[], float] = time.time, *, fast: bool = False) -> Frame:
    timestamp = clock()
    screenshot = b""
    if not fast:
        params: dict[str, Any] = {"format": "png"}
        screenshot = base64.b64decode(cdp.send("Page.captureScreenshot", params)["data"])
    return Frame(
        screenshot, page.content(), timestamp, page.url, _canvas(page, MINIMAP_SCRIPT), _canvas(page, ZONEMAP_SCRIPT)
    )


def _canvas(page: Page, script: str) -> bytes:
    data_url = page.evaluate(script)
    return base64.b64decode(data_url.partition(",")[2]) if data_url else b""


class FrameRecorder:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def save(self, frame: Frame) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        stem = self._unique_stem(frame.timestamp)
        _file(stem, ".png").write_bytes(frame.screenshot)
        _file(stem, ".html").write_text(frame.dom_snapshot, encoding="utf-8")
        if frame.minimap:
            _file(stem, ".minimap.png").write_bytes(frame.minimap)
        if frame.zonemap:
            _file(stem, ".zonemap.png").write_bytes(frame.zonemap)
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
        minimap=_read(_file(stem, ".minimap.png")),
        zonemap=_read(_file(stem, ".zonemap.png")),
    )


def _read(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def _file(stem: Path, suffix: str) -> Path:
    return stem.parent / (stem.name + suffix)
