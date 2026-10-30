import base64

from autobonk.frames import FrameRecorder, capture_frame, load_frame


class FakePage:
    url = "https://pokebonk.com/"

    def __init__(self, html="<html><body>等级 3!</body></html>"):
        self.html = html

    def content(self):
        return self.html

    def evaluate(self, script):
        return ""  # no minimap canvas outside a run


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


MINIMAP_PNG = b"\x89PNG minimap"


class FakeGamePage(FakePage):
    """A page in a run: the minimap canvas hands back its own image as a data URL."""

    def evaluate(self, script):
        return "data:image/png;base64," + base64.b64encode(MINIMAP_PNG).decode()


def test_frame_carries_the_minimap_canvas_image():
    assert capture_frame(FakeGamePage(), FakeCdp(), clock=lambda: 0.0).minimap == MINIMAP_PNG


def test_minimap_is_saved_beside_the_frame_and_loads_back(tmp_path):
    frame = capture_frame(FakeGamePage(), FakeCdp(), clock=lambda: 0.0)

    path = FrameRecorder(tmp_path).save(frame)

    assert (tmp_path / (path.name + ".minimap.png")).read_bytes() == MINIMAP_PNG
    assert load_frame(path) == frame


ZONEMAP_PNG = b"\x89PNG zonemap"


class FakeTabPage(FakePage):
    """Tab held: the floating zone map canvas (canvas.bm-cv) is on screen too."""

    def evaluate(self, script):
        image = ZONEMAP_PNG if "bm-cv" in script else MINIMAP_PNG
        return "data:image/png;base64," + base64.b64encode(image).decode()


def test_zone_map_is_saved_beside_the_frame_and_loads_back(tmp_path):
    frame = capture_frame(FakeTabPage(), FakeCdp(), clock=lambda: 0.0)

    path = FrameRecorder(tmp_path).save(frame)

    assert frame.zonemap == ZONEMAP_PNG
    assert (tmp_path / (path.name + ".zonemap.png")).read_bytes() == ZONEMAP_PNG
    assert load_frame(path) == frame


def test_without_a_minimap_canvas_the_frame_has_no_minimap(tmp_path):
    frame = capture_frame(FakePage(), FakeCdp(), clock=lambda: 0.0)
    path = FrameRecorder(tmp_path).save(frame)

    assert frame.minimap == b""
    assert not (tmp_path / (path.name + ".minimap.png")).exists()
    assert load_frame(path).minimap == b""
    assert frame.zonemap == b""
    assert not (tmp_path / (path.name + ".zonemap.png")).exists()
