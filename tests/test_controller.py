import logging
import threading

from autobonk.controller import Controller
from autobonk.frames import Frame, FrameRecorder, load_frame


class FakeDriver:
    def __init__(self):
        self.calls = []

    def release_all(self):
        self.calls.append("release_all")


def make_controller(tmp_path, capture=None):
    frame = Frame(b"png", "<html></html>", 1761600000.0, "https://pokebonk.com/")
    driver = FakeDriver()
    controller = Controller(
        capture=capture or (lambda: frame),
        recorder=FrameRecorder(tmp_path),
        driver=driver,
    )
    return controller, driver, frame


def test_starts_paused(tmp_path):
    controller, _, _ = make_controller(tmp_path)

    assert controller.paused


def test_toggle_flips_state_releases_keys_and_logs_each_time(tmp_path, caplog):
    controller, driver, _ = make_controller(tmp_path)
    caplog.set_level(logging.INFO)

    controller.submit("toggle_pause")
    controller.poll()
    assert not controller.paused

    controller.submit("toggle_pause")
    controller.poll()
    assert controller.paused

    assert driver.calls == ["release_all", "release_all"]
    assert "RUNNING" in caplog.text and "PAUSED" in caplog.text


def test_save_frame_writes_captured_frame(tmp_path):
    controller, _, frame = make_controller(tmp_path)

    controller.submit("save_frame")
    controller.poll()

    [json_file] = tmp_path.glob("*.json")
    assert load_frame(json_file.with_suffix("")) == frame


def test_events_submitted_from_another_thread_are_handled_on_poll(tmp_path):
    controller, driver, _ = make_controller(tmp_path)

    worker = threading.Thread(target=controller.submit, args=("toggle_pause",))
    worker.start()
    worker.join()
    assert driver.calls == []

    controller.poll()
    assert driver.calls == ["release_all"]


def test_failed_capture_is_logged_not_raised(tmp_path, caplog):
    def broken():
        raise RuntimeError("page closed")

    controller, _, _ = make_controller(tmp_path, capture=broken)

    controller.submit("save_frame")
    controller.poll()

    assert "page closed" in caplog.text
    assert list(tmp_path.iterdir()) == []
