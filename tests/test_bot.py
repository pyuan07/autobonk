from dataclasses import replace
from pathlib import Path

from autobonk.bot import Bot, Pause, Press, ReleaseAll, Stop
from autobonk.cards import CardPrefs
from autobonk.config import load_config
from autobonk.frames import Frame, load_frame

FRAMES = Path(__file__).parent.parent / "fixtures" / "frames"


def recorded(name: str) -> Frame:
    return load_frame(FRAMES / f"frame-20261028-{name}")


WIN = recorded("023009-523")
PLAYING = recorded("021725-506")
LEVEL_UP = recorded("021833-196")  # 招式 咬住, 普通 诅咒薰香, 普通 好伤药, 普通 命中强化
LEVEL_UP_19 = recorded("022221-064")  # 少见 双翼, 少见 防御强化, 普通 金珠, 少见 ＨＰ增强剂
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


def test_level_up_presses_the_weighted_card():
    bot = Bot(cards=CardPrefs(weights={"命中强化": 5}))

    assert bot.step(LEVEL_UP) == [ReleaseAll(), Press("4")]


def test_level_up_without_listed_cards_picks_highest_rarity_then_leftmost():
    assert Bot().step(LEVEL_UP_19) == [ReleaseAll(), Press("1")]
    assert Bot(cards=CardPrefs(rarity_order=("普通", "少见"))).step(LEVEL_UP_19) == [ReleaseAll(), Press("3")]


def test_negative_weight_avoids_a_card():
    bot = Bot(cards=CardPrefs(weights={"双翼": -1}))

    assert bot.step(LEVEL_UP_19) == [ReleaseAll(), Press("2")]


def test_level_up_never_refreshes_skips_or_banishes():
    for frame in (LEVEL_UP, LEVEL_UP_19):
        pressed = {c.key for c in Bot().step(frame) if isinstance(c, Press)}
        assert pressed and not pressed & {"F", "f", "X", "x", "Z", "z"}


def test_open_popup_is_not_pressed_again_until_a_second_has_passed():
    bot = Bot()

    bot.step(LEVEL_UP_19)

    assert bot.step(replace(LEVEL_UP_19, timestamp=LEVEL_UP_19.timestamp + 0.9)) == []
    assert bot.step(replace(LEVEL_UP_19, timestamp=LEVEL_UP_19.timestamp + 1.0)) == [ReleaseAll(), Press("1")]


def test_card_weights_come_from_the_config_file(tmp_path):
    path = tmp_path / "autobonk.toml"
    path.write_text('[cards]\nweights = { "金珠" = 10 }\n', encoding="utf-8")

    bot = Bot(cards=load_config(path).cards)

    assert bot.step(LEVEL_UP_19) == [ReleaseAll(), Press("3")]


def test_level_up_log_lists_every_offered_card(caplog):
    caplog.set_level("INFO")

    Bot().step(LEVEL_UP_19)

    for offered in ("[1] 双翼 (少见)", "[2] 防御强化 (少见)", "[3] 金珠 (普通)", "[4] ＨＰ增强剂 (少见)"):
        assert offered in caplog.text
    assert "picked [1] 双翼" in caplog.text
