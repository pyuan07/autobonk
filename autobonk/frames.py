"""Frames: what the bot sees at one instant."""

from autobonk.runtime.frames import (
    CANVAS_SCRIPT,
    MINIMAP_SCRIPT,
    ZONEMAP_SCRIPT,
    CdpSession,
    Frame,
    FrameRecorder,
    Page,
    capture_frame,
    load_frame,
)

__all__ = [
    "CANVAS_SCRIPT",
    "MINIMAP_SCRIPT",
    "ZONEMAP_SCRIPT",
    "CdpSession",
    "Frame",
    "FrameRecorder",
    "Page",
    "capture_frame",
    "load_frame",
]
