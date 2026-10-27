from autobonk.frames import FrameRecorder, capture_frame, load_frame


class FakePage:
    url = "https://pokebonk.com/"

    def __init__(self, html="<html><body>等级 3!</body></html>"):
        self.html = html

    def screenshot(self, type="png", quality=None):
        return b"\x89PNG fake" if type == "png" else b"JPEG fake"

    def content(self):
        return self.html


def test_saved_frame_loads_back_identically(tmp_path):
    frame = capture_frame(FakePage(), clock=lambda: 1761600000.25)

    path = FrameRecorder(tmp_path).save(frame)

    assert load_frame(path) == frame
    assert frame.screenshot == b"\x89PNG fake"
    assert frame.dom_snapshot == "<html><body>等级 3!</body></html>"
    assert frame.timestamp == 1761600000.25
    assert frame.url == "https://pokebonk.com/"


def test_frame_is_written_as_png_html_and_json(tmp_path):
    path = FrameRecorder(tmp_path).save(capture_frame(FakePage(), clock=lambda: 0.0))

    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".html", ".json", ".png"]
    assert all(p.stem == path.name for p in tmp_path.iterdir())


def test_frames_saved_at_the_same_instant_get_unique_names(tmp_path):
    recorder = FrameRecorder(tmp_path / "frames")
    frame = capture_frame(FakePage(), clock=lambda: 1761600000.0)

    first = recorder.save(frame)
    second = recorder.save(frame)

    assert first != second
    assert len(list((tmp_path / "frames").iterdir())) == 6


def test_fast_capture_takes_a_jpeg():
    assert capture_frame(FakePage(), fast=True).screenshot == b"JPEG fake"
