from dataclasses import replace
from pathlib import Path

from autobonk.bot import Bot, Pause, ReleaseAll, Stop
from autobonk.frames import Frame, load_frame

FRAMES = Path(__file__).parent.parent / "fixtures" / "frames"


def recorded(name: str) -> Frame:
    return load_frame(FRAMES / f"frame-20261028-{name}")


WIN = recorded("023009-523")
PLAYING = recorded("021725-506")
LEVEL_UP = recorded("021833-196")
# No lose frame recorded yet: the win screen with the lose title in its place.
LOSE = replace(WIN, dom_snapshot=WIN.dom_snapshot.replace("<h2>胜利！</h2>", "<h2>你倒下了！</h2>"))


def unrecognised(timestamp: float) -> Frame:
    return Frame(b"", "<html><body><h1>Welcome, Trainer!</h1></body></html>", timestamp, "https://pokebonk.com/")


def test_win_screen_releases_keys_and_stops():
    assert Bot().step(WIN) == [ReleaseAll(), Stop("win")]


def test_lose_screen_releases_keys_and_stops():
    assert Bot().step(LOSE) == [ReleaseAll(), Stop("lose")]


def test_normal_play_emits_nothing():
    bot = Bot()

    assert bot.step(PLAYING) == []
    assert bot.step(LEVEL_UP) == []


def test_unrecognised_for_5_seconds_pauses():
    bot = Bot()

    assert bot.step(unrecognised(100.0)) == []
    assert bot.step(unrecognised(104.9)) == []
    assert bot.step(unrecognised(105.0)) == [ReleaseAll(), Pause("screen unrecognised for 5 s")]


def test_recognised_frame_resets_the_unrecognised_timer():
    bot = Bot()

    bot.step(unrecognised(100.0))
    bot.step(replace(PLAYING, timestamp=103.0))

    assert bot.step(unrecognised(107.0)) == []


def test_hidden_timer_does_not_count_as_recognised():
    hidden = Frame(b"", '<div style="display: none;"><div class="timer">9:34</div></div>', 0.0, "")
    bot = Bot()

    bot.step(hidden)

    assert bot.step(replace(hidden, timestamp=5.0)) == [ReleaseAll(), Pause("screen unrecognised for 5 s")]
