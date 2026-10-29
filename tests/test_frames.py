import base64

from autobonk.frames import FrameRecorder, capture_frame, load_frame


class FakePage:
    url = "https://pokebonk.com/"

    def __init__(self, html="<html><body>等级 3!</body></html>"):
        self.html = html

    def content(self):
        return self.html


class FakeCdp:
    def __init__(self):
        self.sent = []

    def send(self, method, params=None):
        self.sent.append((method, params))
        image = b"\x89PNG fake" if params["format"] == "png" else b"JPEG fake"
        return {"data": base64.b64encode(image).decode()}


def test_saved_frame_loads_back_identically(tmp_path):
    frame = capture_frame(FakePage(), FakeCdp(), clock=lambda: 1761600000.25)

    path = FrameRecorder(tmp_path).save(frame)

    assert load_frame(path) == frame
    assert frame.screenshot == b"\x89PNG fake"
    assert frame.dom_snapshot == "<html><body>等级 3!</body></html>"
    assert frame.timestamp == 1761600000.25
    assert frame.url == "https://pokebonk.com/"


def test_frame_is_written_as_png_html_and_json(tmp_path):
    path = FrameRecorder(tmp_path).save(capture_frame(FakePage(), FakeCdp(), clock=lambda: 0.0))

    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".html", ".json", ".png"]
    assert all(p.stem == path.name for p in tmp_path.iterdir())


def test_frames_saved_at_the_same_instant_get_unique_names(tmp_path):
    recorder = FrameRecorder(tmp_path / "frames")
    frame = capture_frame(FakePage(), FakeCdp(), clock=lambda: 1761600000.0)

    first = recorder.save(frame)
    second = recorder.save(frame)

    assert first != second
    assert len(list((tmp_path / "frames").iterdir())) == 6


def test_fast_capture_takes_a_jpeg_saved_capture_a_png():
    cdp = FakeCdp()

    saved = capture_frame(FakePage(), cdp, clock=lambda: 0.0)
    fast = capture_frame(FakePage(), cdp, clock=lambda: 0.0, fast=True)

    assert (saved.screenshot, fast.screenshot) == (b"\x89PNG fake", b"JPEG fake")


def test_screenshots_go_straight_to_chrome_without_a_clip():
    # Playwright's page.screenshot sends a clip, which makes a headed window flash at 125% scaling.
    cdp = FakeCdp()

    capture_frame(FakePage(), cdp, clock=lambda: 0.0)
    capture_frame(FakePage(), cdp, clock=lambda: 0.0, fast=True)

    assert [method for method, _ in cdp.sent] == ["Page.captureScreenshot"] * 2
    assert all("clip" not in params for _, params in cdp.sent)
