from dataclasses import replace
from pathlib import Path

import pytest

from autobonk.bot import Bot, Click, Hold, Movement, Pause, Press, ReleaseAll, Stop
from autobonk.cards import CardPrefs
from autobonk.config import load_config
from autobonk.frames import Frame, load_frame
from autobonk.perception import perceive

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


ITEM_CHOICE = recorded("021847-879")  # 普通 硬石头, 普通 吉利拳, 少见 文柚果
ITEM_PICKUP = recorded("021610-030")  # 拾取 E / 出售 V
DITTO = recorded("022106-745")  # 活力块, 吃剩的东西, 锐利之爪, ... 达人带 (no [n] keys)
HYPNO = recorded("022445-954")  # 忘记 ×7, 就绪


@pytest.mark.parametrize(
    "name, expected",
    [
        ("021847-879", "3"),  # item choice: the only 少见
        ("021742-082", "1"),  # fossil ruins: unknown rarities -> leftmost
        ("021748-698", "1"),  # fossil blessing: all 传说 -> leftmost
        ("022011-249", "1"),  # Porygon altar
    ],
)
def test_keyed_choice_popups_press_the_best_card(name, expected):
    assert Bot().step(recorded(name)) == [ReleaseAll(), Press(expected)]


def test_keyed_choice_popups_use_card_weights():
    bot = Bot(cards=CardPrefs(weights={"吉利拳": 5}))

    assert bot.step(ITEM_CHOICE) == [ReleaseAll(), Press("2")]


def test_item_pickup_presses_pick_up_never_sell():
    assert Bot().step(ITEM_PICKUP) == [ReleaseAll(), Press("e")]
    assert Bot().step(recorded("022025-333")) == [ReleaseAll(), Press("e")]


def test_ditto_clicks_the_best_item_by_name():
    assert Bot().step(DITTO) == [ReleaseAll(), Click("活力块")]
    assert Bot(cards=CardPrefs(weights={"达人带": 5})).step(DITTO) == [ReleaseAll(), Click("达人带")]


def test_hypno_clicks_ready_without_forgetting_anything():
    assert Bot().step(HYPNO) == [ReleaseAll(), Click("就绪")]


@pytest.mark.parametrize(
    "name, leave",
    [
        ("021944-020", Press("Escape")),  # Meowth shop: 离开 Esc
        ("022059-218", Press("Escape")),  # fusion machine: 以后再说 Esc
        ("022033-536", Click("离开")),  # slot machine: 离开, no key
    ],
)
def test_money_and_fusion_popups_are_left(name, leave):
    assert Bot().step(recorded(name)) == [ReleaseAll(), leave]


@pytest.mark.parametrize(
    "name",
    [
        "022542-352",  # 守护者已被击败！ banner
        "022218-807",  # support boss joined banner
        "022353-323",  # boss name banner
        "022814-797",  # "an image hasn't loaded" corner notice with a 重试 button
    ],
)
def test_banners_and_notices_are_not_popups(name):
    assert Bot().step(recorded(name)) == []


@pytest.mark.parametrize(
    "name",
    [
        "155532-914",  # 头目宝可梦！ boss banner while the pause menu's buttons sit later in the DOM
        "155654-906",  # 头目水伊布倒下了！ banner next to the visible 放生 pill
        "160041-764",  # 森林之心 zone intro
    ],
)
def test_banners_followed_by_hud_buttons_are_not_popups(name):
    assert perceive(load_frame(FRAMES / f"frame-20261030-{name}")).popup is None


def popup(body: str) -> Frame:
    return Frame(b"", f'<div class="timer">8:00</div><div class="modal">{body}</div>', 100.0, "")


def test_unknown_popup_with_numbered_options_presses_the_best_one():
    frame = popup("<h1>新事件！</h1><div><span>普通</span><h3>甲</h3><div>[1]</div></div>"
                  "<div><span>少见</span><h3>乙</h3><div>[2]</div></div>")

    assert Bot().step(frame) == [ReleaseAll(), Press("2")]


def test_unknown_popup_without_options_pauses():
    frame = popup("<h1>新事件！</h1><button>确定</button>")

    assert Bot().step(frame) == [ReleaseAll(), Pause("unknown popup: 新事件！")]


def run_frame(name: str, timestamp: float) -> Frame:
    """A frame from the 2026-10-30 run (in play, minimap saved) at a chosen time."""
    return replace(load_frame(FRAMES / f"frame-20261030-{name}"), timestamp=timestamp)


@pytest.mark.parametrize(
    "name, keys",
    [
        ("155200-971", {"KeyD"}),  # altar right and a little up
        ("155220-116", {"KeyW"}),  # straight up: minimap-up is always W
        ("155651-230", {"KeyS", "KeyA"}),  # down-left
        ("155820-313", {"KeyS"}),  # straight down (cyan ring)
    ],
)
def test_walks_toward_the_nearest_rune_altar(name, keys):
    assert Bot().step(run_frame(name, 100.0)) == [Hold(frozenset(keys))]


def test_holding_the_same_direction_is_not_repeated():
    bot = Bot()
    bot.step(run_frame("155220-116", 100.0))

    assert bot.step(run_frame("155220-116", 100.1)) == []


def test_stands_still_in_the_ring_while_the_altar_charges():
    bot = Bot()
    bot.step(run_frame("155220-116", 100.0))

    assert bot.step(run_frame("155222-698", 100.1)) == [Hold(frozenset())]  # charging 8%


def test_gives_up_on_an_altar_that_charges_longer_than_the_cap():
    bot = Bot(movement=Movement(altar_charge_cap_s=45))
    bot.step(run_frame("155222-698", 100.0))  # charging starts
    bot.step(run_frame("155227-456", 144.0))

    # Past the cap the altar is ignored (no steering back onto it) until the bubble goes away.
    assert holds(bot.step(run_frame("155227-456", 146.0))) == []
    assert holds(bot.step(run_frame("155220-116", 147.0))) == [Hold(frozenset({"KeyW"}))]


def holds(commands):
    return [command for command in commands if isinstance(command, Hold)]


def test_popup_releases_movement_and_steering_resumes_after():
    bot = Bot()
    bot.step(run_frame("155220-116", 100.0))
    assert bot.step(replace(LEVEL_UP, timestamp=100.1))[0] == ReleaseAll()

    assert bot.step(run_frame("155220-116", 100.2)) == [Hold(frozenset({"KeyW"}))]


class FixedIntervals:
    def __init__(self, *intervals: float):
        self._intervals = list(intervals)

    def uniform(self, low: float, high: float) -> float:
        interval = self._intervals.pop(0)
        assert low <= interval <= high
        return interval


def test_jumps_at_random_intervals_while_playing():
    bot = Bot(movement=Movement(jump_interval_s=(0.8, 1.4), rng=FixedIntervals(1.0, 1.3, 0.9, 1.0)))
    times = [100.0 + 0.1 * i for i in range(40)]
    jumps = [t for t in times if Press("Space") in bot.step(run_frame("155925-987", t))]

    assert [round(t - 100, 1) for t in jumps] == [1.0, 2.3, 3.2]


def test_no_jumping_in_popups():
    bot = Bot(movement=Movement(rng=FixedIntervals(0.8, 0.8)))
    bot.step(run_frame("155313-554", 100.0))  # 稀有未知图腾祭坛 reward popup is open in this frame

    assert Press("Space") not in bot.step(run_frame("155313-554", 101.0))
