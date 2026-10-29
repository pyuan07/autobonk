import logging
import threading
from pathlib import Path

from autobonk.bot import Bot
from autobonk.controller import Controller
from autobonk.frames import Frame, FrameRecorder, load_frame

WIN_HTML = "<div class='timer'>1:50</div><h2>胜利！</h2>"


class FakeDriver:
    def __init__(self):
        self.calls = []

    def release_all(self):
        self.calls.append("release_all")

    def press(self, key):
        self.calls.append(f"press {key}")

    def click(self, text):
        self.calls.append(f"click {text}")


class FakeBot:
    def __init__(self):
        self.frames = []

    def step(self, frame):
        self.frames.append(frame)
        return []


def make_controller(tmp_path, capture=None, bot=None, html="<html></html>", driver=None):
    frame = Frame(b"png", html, 1761600000.0, "https://pokebonk.com/")
    driver = driver or FakeDriver()
    controller = Controller(
        capture=capture or (lambda: frame),
        recorder=FrameRecorder(tmp_path),
        driver=driver,
        bot=bot or FakeBot(),
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


def test_tick_does_nothing_while_paused(tmp_path):
    bot = FakeBot()
    controller, _, _ = make_controller(tmp_path, bot=bot)

    controller.tick()

    assert bot.frames == []


def test_tick_steps_the_bot_once_running(tmp_path):
    bot = FakeBot()
    controller, _, frame = make_controller(tmp_path, bot=bot)
    controller.submit("toggle_pause")
    controller.poll()

    controller.tick()

    assert bot.frames == [frame]


def test_end_screen_stops_the_loop_with_keys_released(tmp_path, caplog):
    controller, driver, _ = make_controller(tmp_path, bot=Bot(), html=WIN_HTML)
    caplog.set_level(logging.INFO)
    controller.submit("toggle_pause")
    controller.poll()
    driver.calls.clear()

    controller.tick()
    controller.tick()

    assert controller.paused
    assert driver.calls and set(driver.calls) == {"release_all"}
    assert "STOPPED (win)" in caplog.text


def test_pressed_card_key_reaches_the_driver_after_keys_are_released(tmp_path):
    level_up = load_frame(Path(__file__).parent.parent / "fixtures" / "frames" / "frame-20261028-022221-064")
    controller, driver, _ = make_controller(tmp_path, capture=lambda: level_up, bot=Bot())
    controller.submit("toggle_pause")
    controller.poll()
    driver.calls.clear()

    controller.tick()

    assert driver.calls == ["release_all", "press 1"]
    assert not controller.paused


def test_clicked_text_reaches_the_driver(tmp_path):
    hypno = load_frame(Path(__file__).parent.parent / "fixtures" / "frames" / "frame-20261028-022445-954")
    controller, driver, _ = make_controller(tmp_path, capture=lambda: hypno, bot=Bot())
    controller.submit("toggle_pause")
    controller.poll()
    driver.calls.clear()

    controller.tick()

    assert driver.calls == ["release_all", "click 就绪"]


def test_failed_driver_command_pauses_instead_of_crashing(tmp_path, caplog):
    class BrokenClickDriver(FakeDriver):
        def click(self, text):
            raise TimeoutError("not visible")

    hypno = load_frame(Path(__file__).parent.parent / "fixtures" / "frames" / "frame-20261028-022445-954")
    controller, _, _ = make_controller(tmp_path, capture=lambda: hypno, bot=Bot(), driver=BrokenClickDriver())
    caplog.set_level(logging.INFO)
    controller.submit("toggle_pause")
    controller.poll()

    controller.tick()

    assert controller.paused
    assert "not visible" in caplog.text


def test_paused_tick_watches_the_player_instead_of_stepping(tmp_path):
    bot, watched = FakeBot(), []
    controller = Controller(
        capture=lambda: None, recorder=FrameRecorder(tmp_path), driver=FakeDriver(), bot=bot,
        watch=lambda: watched.append(True),
    )

    controller.tick()

    assert watched == [True]
    assert bot.frames == []


def test_failed_watch_is_logged_not_raised(tmp_path, caplog):
    def broken():
        raise RuntimeError("page gone")

    controller = Controller(
        capture=lambda: None, recorder=FrameRecorder(tmp_path), driver=FakeDriver(), bot=FakeBot(), watch=broken,
    )

    controller.tick()

    assert "page gone" in caplog.text
