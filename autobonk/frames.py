"""Frames: what the bot sees at one instant (screenshot + DOM snapshot + minimap + timestamp).

A saved frame is three files sharing a stem: `<stem>.png`, `<stem>.html`, `<stem>.json`, plus
`<stem>.minimap.png` when a run's minimap was on screen.
"""

import base64
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class Frame:
    screenshot: bytes
    dom_snapshot: str
    timestamp: float
    url: str
    minimap: bytes = b""  # PNG of the minimap canvas (400x400, player at the centre); empty outside a run


class Page(Protocol):
    @property
    def url(self) -> str: ...

    def content(self) -> str: ...

    def evaluate(self, expression: str) -> Any: ...


# The minimap's own pixels, independent of window size and display scaling.
# toDataURL throws on a canvas tainted by cross-origin images; then there's no minimap.
MINIMAP_SCRIPT = """() => {
  try { return document.querySelector('canvas.minimap')?.toDataURL('image/png') ?? ''; }
  catch (error) { return ''; }
}"""


class CdpSession(Protocol):
    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...


def capture_frame(page: Page, cdp: CdpSession, clock: Callable[[], float] = time.time, *, fast: bool = False) -> Frame:
    """`fast` takes a JPEG instead of a PNG for live bot steps; saved frames use PNG.

    Screenshots go straight to Chrome over CDP with no clip: Playwright's page.screenshot sends
    a clip, which makes the headed window visibly flash/resize on a scaled (e.g. 125%) display.
    """
    timestamp = clock()
    params: dict[str, Any] = {"format": "jpeg", "quality": 70} if fast else {"format": "png"}
    screenshot = base64.b64decode(cdp.send("Page.captureScreenshot", params)["data"])
    return Frame(screenshot, page.content(), timestamp, page.url, _minimap(page))


def _minimap(page: Page) -> bytes:
    data_url = page.evaluate(MINIMAP_SCRIPT)
    return base64.b64decode(data_url.partition(",")[2]) if data_url else b""


class FrameRecorder:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def save(self, frame: Frame) -> Path:
        """Write `frame` under a unique stem; return the stem path (no suffix)."""
        self.directory.mkdir(parents=True, exist_ok=True)
        stem = self._unique_stem(frame.timestamp)
        _file(stem, ".png").write_bytes(frame.screenshot)
        _file(stem, ".html").write_text(frame.dom_snapshot, encoding="utf-8")
        if frame.minimap:
            _file(stem, ".minimap.png").write_bytes(frame.minimap)
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
        minimap=minimap.read_bytes() if (minimap := _file(stem, ".minimap.png")).exists() else b"",
    )


def _file(stem: Path, suffix: str) -> Path:
    return stem.parent / (stem.name + suffix)
