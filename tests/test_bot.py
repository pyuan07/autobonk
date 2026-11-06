import math
from dataclasses import replace
from pathlib import Path

import pytest

from autobonk.bot import BossRule, Bot, Click, Hold, Movement, Pause, Press, ReleaseAll, Stop
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
    assert Bot(auto_restart="never").step(WIN) == [ReleaseAll(), Stop("win")]


def test_lose_screen_releases_keys_and_stops():
    assert Bot(auto_restart="never").step(LOSE) == [ReleaseAll(), Stop("lose")]


def test_auto_restart_on_win_and_lose_clicks_retry():
    real_win = load_frame(FRAMES / "frame-20261104-160755-056")
    real_lose = load_frame(FRAMES / "frame-20261104-162335-963")
    assert Bot().step(WIN) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]
    assert Bot().step(LOSE) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]
    assert Bot().step(real_win) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]
    assert Bot().step(real_lose) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]


def test_auto_restart_debounces_clicks():
    bot = Bot()
    f1 = replace(WIN, timestamp=100.0)
    assert bot.step(f1) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]

    # Immediately on next frame 100ms later, debouncing yields only ReleaseAll
    f2 = replace(WIN, timestamp=100.1)
    assert bot.step(f2) == [ReleaseAll()]

    # After retry delay (1.5s), attempts next click
    f3 = replace(WIN, timestamp=101.6)
    assert bot.step(f3) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]


def test_auto_restart_max_retries_pauses():
    bot = Bot()
    assert bot.step(replace(WIN, timestamp=100.0)) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]
    assert bot.step(replace(WIN, timestamp=101.6)) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]
    assert bot.step(replace(WIN, timestamp=103.2)) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]

    # 4th attempt exceeds max_retries (3), emits Pause
    assert bot.step(replace(WIN, timestamp=104.8)) == [
        ReleaseAll(),
        Pause("Restart failed: '再来一次' still present after 3 clicks"),
    ]


def test_auto_restart_max_runs():
    bot = Bot(max_runs=1)
    # 1st run finishes -> reached max_runs, stops
    assert bot.step(WIN) == [ReleaseAll(), Stop("win")]

    bot2 = Bot(max_runs=2)
    # 1st run finishes -> clicks restart
    assert bot2.step(WIN) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]
    # New run in-game countdown seen
    bot2.step(PLAYING)
    # 2nd run finishes -> reached max_runs=2, stops
    assert bot2.step(WIN) == [ReleaseAll(), Stop("win")]


def test_auto_restart_tolerates_loading_screen():
    bot = Bot(restart_load_s=15.0)
    assert bot.step(replace(WIN, timestamp=100.0)) == [ReleaseAll(), Click("再来一次", selector=".sm-foot button.green")]

    # Transitioning / unrecognised screen starts right after at 100.1s
    assert bot.step(unrecognised(100.1)) == []
    assert bot.step(unrecognised(110.0)) == []
    assert bot.step(unrecognised(115.0)) == []

    # Exceeding loading budget (100.1 + 15.0 = 115.1s) pauses
    assert bot.step(unrecognised(115.2)) == [ReleaseAll(), Pause("screen unrecognised for 15 s")]


def test_auto_restart_resets_run_state_on_new_game():
    bot = Bot()
    # Simulate ignored target and dirty state in run 1
    bot._target_selector.ignore_target("符文祭坛", until=9999.0)
    assert not bot._target_selector.candidates([("符文祭坛", (10, 10))], now=100.0)

    # End screen triggers restart
    bot.step(replace(WIN, timestamp=100.0))

    # New game starts (countdown appears)
    bot.step(replace(PLAYING, timestamp=102.0))

    # In run 2, target is no longer ignored
    assert bot._target_selector.candidates([("符文祭坛", (10, 10))], now=102.0)
    assert bot.status().runs == 1
    assert bot.status().wins == 1


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
    assert Bot(reroll_threshold=None).step(LEVEL_UP_19) == [ReleaseAll(), Press("1")]
    assert Bot(cards=CardPrefs(rarity_order=("普通", "少见")), reroll_threshold=None).step(LEVEL_UP_19) == [ReleaseAll(), Press("3")]


def test_negative_weight_avoids_a_card():
    bot = Bot(cards=CardPrefs(weights={"双翼": -1, "防御强化": 1}))

    assert bot.step(LEVEL_UP_19) == [ReleaseAll(), Press("2")]


def test_level_up_rerolls_when_best_card_unwanted():
    # When best card weight <= 0 and rerolls are available, press F
    bot = Bot(cards=CardPrefs(weights={"双翼": 0}))
    assert bot.step(LEVEL_UP_19) == [ReleaseAll(), Press("f")]


def test_level_up_banishes_avoided_cards():
    # LEVEL_UP_19 cards: 双翼 (locked move), 防御强化, 金珠, ＨＰ增强剂
    # Avoid ＨＰ增强剂 (-5); 双翼 has "不会再升级" so it must not be banished
    bot = Bot(cards=CardPrefs(weights={"ＨＰ增强剂": -5, "双翼": -5}))
    # First step: enter banish mode
    assert bot.step(LEVEL_UP_19) == [ReleaseAll(), Press("z")]

    # Second step: inside banish mode (cancel button visible) -> pick card 4 (ＨＰ增强剂), never card 1 (双翼)
    banish_modal = replace(
        LEVEL_UP_19,
        dom_snapshot=LEVEL_UP_19.dom_snapshot.replace(
            '<button class="btn ghost small" style="display: none;">取消</button>',
            '<button class="btn ghost small">取消</button>',
        ),
    )
    assert bot.step(banish_modal) == [ReleaseAll(), Press("4")]


def test_level_up_skips_when_all_negative_and_no_rerolls():
    # If all cards are strictly negative and no rerolls left, press X
    no_reroll = replace(
        LEVEL_UP_19,
        dom_snapshot=LEVEL_UP_19.dom_snapshot.replace("刷新 (7)<kbd>F</kbd>", "刷新 (0)<kbd>F</kbd>"),
    )
    bot = Bot(cards=CardPrefs(weights={"双翼": -1, "防御强化": -1, "金珠": -1, "ＨＰ增强剂": -1}))
    assert bot.step(no_reroll) == [ReleaseAll(), Press("x")]


def test_open_popup_is_not_pressed_again_until_a_second_has_passed():
    bot = Bot()

    bot.step(LEVEL_UP_19)

    assert bot.step(replace(LEVEL_UP_19, timestamp=LEVEL_UP_19.timestamp + 0.9)) == []
    assert bot.step(replace(LEVEL_UP_19, timestamp=LEVEL_UP_19.timestamp + 1.0)) == [ReleaseAll(), Press("f")]


def test_card_weights_come_from_the_config_file(tmp_path):
    path = tmp_path / "autobonk.toml"
    path.write_text('[cards]\nweights = { "金珠" = 10 }\n', encoding="utf-8")

    bot = Bot(cards=load_config(path).cards)

    assert bot.step(LEVEL_UP_19) == [ReleaseAll(), Press("3")]


def test_level_up_log_lists_every_offered_card(caplog):
    caplog.set_level("INFO")

    Bot(cards=CardPrefs(weights={"双翼": 5})).step(LEVEL_UP_19)

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


def test_team_full_ally_join_modal_clicks_release_newcomer():
    f1 = load_frame(FRAMES / "frame-20261101-215615-503")
    assert Bot().step(f1) == [ReleaseAll(), Click("放生新来的")]

    f2 = load_frame(FRAMES / "frame-20261031-231041-203")
    assert Bot().step(f2) == [ReleaseAll(), Click("放生新来的")]


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
    assert perceive(recorded(name)).popup is None


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
    bot = Bot(movement=Movement(altar_orbit=False))
    bot.step(run_frame("155220-116", 100.0))

    assert bot.step(run_frame("155222-698", 100.1)) == [Hold(frozenset())]  # charging 8%


def test_orbits_in_altar_ring_while_charging():
    bot = Bot(movement=Movement(altar_orbit=True))
    bot.step(run_frame("155220-116", 100.0))

    # Bot orbits inside the ring (tangential step 'KeyA') rather than standing still
    assert bot.step(run_frame("155222-698", 100.1)) == [Hold(frozenset({"KeyA"}))]


def test_altar_charging_completion_immediately_departs():
    bot = Bot(movement=Movement(target_ignore_s=60))
    # 1. Altar charging starts
    bot.step(run_frame("155222-698", 100.0))
    assert bot.status().charging is True

    # 2. Next frame: charging finishes (e.g. 100% reached, charging=False).
    # Even if altar crystal is still visible on minimap, bot immediately ignores altar and holds Tab to explore!
    charged_frame = run_frame("155220-116", 101.0)
    cmds = bot.step(charged_frame)
    assert holds(cmds) == [Hold(frozenset({"Tab"}))]
    assert bot.status().charging is False
    assert bot.status().target == ""


def test_gives_up_on_an_altar_that_charges_longer_than_the_cap():
    bot = Bot(movement=Movement(altar_charge_cap_s=45))
    bot.step(run_frame("155222-698", 100.0))  # charging starts
    bot.step(run_frame("155227-456", 144.0))

    # Past the cap the altar is left: hold Tab to explore elsewhere, for target_ignore_s.
    assert holds(bot.step(run_frame("155227-456", 146.0))) == [Hold(frozenset({"Tab"}))]
    assert holds(bot.step(run_frame("155220-116", 147.0))) == []
    assert holds(bot.step(run_frame("155220-116", 207.0))) == [Hold(frozenset({"KeyW"}))]


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


def with_maps(name: str, minimap_of: str, zonemap: bytes = b"", timestamp: float = 100.0) -> Frame:
    """Frame `name` with the minimap of another frame and (Tab held) a zone map."""
    frame = run_frame(name, timestamp)
    return replace(frame, minimap=run_frame(minimap_of, 0).minimap, zonemap=zonemap)


ZONEMAP = (FRAMES / "frame-20261030-170001-415.zonemap.png").read_bytes()  # altar west of the player


def zonemap_without_altars() -> bytes:
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(ZONEMAP))
    image.paste(image.crop((500, 480, 560, 540)), (247, 292))  # grass over the altar at (277, 322)
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def test_nothing_on_the_minimap_holds_tab_to_read_the_zone_map():
    assert holds(Bot().step(run_frame("155925-987", 100.0))) == [Hold(frozenset({"Tab"}))]


def test_heads_for_an_altar_seen_on_the_zone_map_correcting_for_the_camera():
    # Zone map: altar to the west-north-west (bearing -71). Minimap: 北 at -79, so it shows at -150: down-left.
    frame = with_maps("155925-987", minimap_of="155925-987", zonemap=ZONEMAP)

    assert holds(Bot().step(frame)) == [Hold(frozenset({"Tab", "KeyS", "KeyA"}))]


def test_with_nothing_discovered_heads_for_the_nearest_unvisited_cell():
    # Player in cell (3, 3) of 8x8, near its east side: cell (4, 3) is nearest, bearing ~67.
    # Minimap 北 at -79, so it shows at ~-12: up.
    frame = with_maps("155925-987", minimap_of="155925-987", zonemap=zonemap_without_altars())

    assert holds(Bot().step(frame)) == [Hold(frozenset({"Tab", "KeyW"}))]


def test_an_altar_on_the_minimap_takes_over_and_lets_go_of_tab():
    bot = Bot()
    bot.step(with_maps("155925-987", minimap_of="155925-987", zonemap=ZONEMAP))

    assert holds(bot.step(run_frame("170001-415", 100.1))) == [Hold(frozenset({"KeyW"}))]


def test_stuck_walking_to_an_altar_sidesteps_then_walks_on():
    bot = Bot(movement=Movement(stuck_s=2.5, sidestep_s=0.6))
    steps = {round(t, 1): holds(bot.step(run_frame("155220-116", 100.0 + t))) for t in [i / 10 for i in range(40)]}

    assert steps[0.0] == [Hold(frozenset({"KeyW"}))]
    assert steps[2.5] == [Hold(frozenset({"KeyA"}))]  # altar no closer for 2.5 s: step left
    assert steps[3.1] == [Hold(frozenset({"KeyW"}))]  # then back on course


def test_sidesteps_alternate_left_and_right():
    bot = Bot(movement=Movement(stuck_s=2.5, sidestep_s=0.6))
    sides = [h.keys for t in range(80) for h in holds(bot.step(run_frame("155220-116", 100.0 + t / 10)))]

    assert sides[:4] == [{"KeyW"}, {"KeyA"}, {"KeyW"}, {"KeyD"}]


def test_moving_closer_is_not_stuck():
    bot = Bot(movement=Movement(stuck_s=2.5))
    bot.step(run_frame("155214-804", 100.0))  # altar 51 px away
    bot.step(run_frame("155220-116", 102.0))  # 47 px: progress, the stuck timer restarts

    assert holds(bot.step(run_frame("155220-116", 104.0))) == []  # only 2 s without progress


def test_unsticker_prefers_zonemap_player_progress_over_constant_target_dist():
    from autobonk.perception.dom import Observation
    from autobonk.perception.zonemap import ZoneMap
    from autobonk.policy.navigation import Unsticker

    unsticker = Unsticker(stuck_s=2.5, sidestep_s=0.6)
    zm1 = ZoneMap(player=(0.5, 0.5), altars=(), targets=())
    zm2 = ZoneMap(player=(0.55, 0.55), altars=(), targets=())

    obs1 = Observation(end_screen=None, countdown="05:00", zonemap=zm1)
    obs2 = Observation(end_screen=None, countdown="05:00", zonemap=zm2)

    keys = frozenset({"KeyW"})
    # target_dist is constant 100.0 (like compass direction vector)
    res1 = unsticker.unstick(keys, 0.0, obs1, 100.0, target_dist=100.0)
    assert res1 == keys

    # After 3s with player moving in zonemap, unsticker should NOT trigger sidestep
    res2 = unsticker.unstick(keys, 0.0, obs2, 103.0, target_dist=100.0)
    assert res2 == keys


TEAM_VIEW = run_frame("172455-857", 100.0)  # 等级 11！ with 你的队伍 laid over it (Tab let go mid-popup)


def test_team_view_over_a_popup_is_closed_with_tab_before_choosing():
    bot = Bot()

    assert bot.step(TEAM_VIEW) == [ReleaseAll(), Press("Tab")]
    assert bot.step(replace(TEAM_VIEW, timestamp=100.5)) == []
    assert bot.step(replace(TEAM_VIEW, timestamp=101.0)) == [ReleaseAll(), Press("Tab")]


def test_after_the_team_view_closes_the_card_is_chosen():
    bot = Bot(cards=CardPrefs(weights={"咬住": 1}))
    bot.step(TEAM_VIEW)

    [release, press] = bot.step(replace(LEVEL_UP, timestamp=100.2))

    assert release == ReleaseAll() and press.key in "1234"


def test_a_plain_popup_is_not_the_team_view():
    assert not perceive(LEVEL_UP).team_view
    assert perceive(TEAM_VIEW).team_view


SEALED = run_frame("173711-697", 100.0)  # standing on an altar: 封印中・13秒后苏醒


def test_reads_how_long_an_altar_stays_sealed():
    assert perceive(SEALED).sealed_s == 13
    assert perceive(run_frame("155220-116", 0.0)).sealed_s is None


def test_a_sealed_altar_is_left_to_explore_until_it_wakes():
    bot = Bot()

    assert holds(bot.step(SEALED)) == [Hold(frozenset({"Tab"}))]
    assert holds(bot.step(run_frame("155220-116", 112.0))) == []  # an altar ahead, still ignored
    assert holds(bot.step(run_frame("155220-116", 113.0))) == [Hold(frozenset({"KeyW"}))]


ORE_AND_BALLS = run_frame("173711-697", 100.0)  # minimap: 3 ore, 2 Poké Balls (nearest up-left), a coin


def test_finds_the_icons_asked_for_on_the_minimap():
    found = perceive(ORE_AND_BALLS, ("精灵球", "矿堆", "金币")).targets

    assert sorted(name for name, _ in found) == ["矿堆", "矿堆", "矿堆", "精灵球", "精灵球", "金币"]
    assert perceive(ORE_AND_BALLS).targets == ()  # nothing asked for, nothing matched


def test_walks_to_the_highest_weight_target_then_the_nearest():
    assert holds(Bot(targets={"精灵球": 5, "矿堆": 3}).step(ORE_AND_BALLS)) == [Hold(frozenset({"KeyW", "KeyA"}))]


def test_weight_zero_targets_are_never_visited():
    bot = Bot(targets={"精灵球": 0, "符文祭坛": 0})

    assert holds(bot.step(ORE_AND_BALLS)) == [Hold(frozenset({"Tab"}))]


def test_distance_factor_proximity_bonus():
    bot = Bot(targets={"A": 10, "B": 9, "C": 7, "Zero": 0}, movement=Movement(distance_factor=0.2))
    bot._now_weights = {"A": 10.0, "B": 9.0, "C": 7.0}

    # B at dist 20 (close) vs A at dist 180 (far):
    # B: norm_dist = 20/200 = 0.1 -> score = 9 * (1 + 0.2 * 0.9) = 10.62
    # A: norm_dist = 180/200 = 0.9 -> score = 10 * (1 + 0.2 * 0.1) = 10.2
    # Nearby weight 9 beats far weight 10:
    candidates = [("A", (180, 0)), ("B", (20, 0))]
    assert bot._best(candidates, (0, 0), scale=200.0)[0] == "B"

    # With distance_factor = 0 (pure weight priority):
    bot_strict = Bot(targets={"A": 10, "B": 9}, movement=Movement(distance_factor=0.0))
    bot_strict._now_weights = {"A": 10.0, "B": 9.0}
    assert bot_strict._best(candidates, (0, 0), scale=200.0)[0] == "A"

    # Even right next to the player, lower weight 7 cannot overtake far weight 10:
    # C: score = 7 * (1 + 0.2 * 1.0) = 8.4 < 10.2
    candidates_c = [("A", (180, 0)), ("C", (0, 0))]
    assert bot._best(candidates_c, (0, 0), scale=200.0)[0] == "A"

    # Weight 0 still gets score 0 and is never boosted:
    assert bot._candidate_score("Zero", (0, 0), (0, 0), 200.0)[0] == 0.0

    # Boss always beats regular targets regardless of distance:
    bot._now_weights["BOSS"] = math.inf
    assert bot._best([("B", (0, 0)), ("BOSS", (200, 200))], (0, 0), scale=200.0)[0] == "BOSS"


def standing_on(icon: str, timestamp: float) -> Frame:
    """A playing frame whose minimap shows only `icon` under the player."""
    from io import BytesIO

    from PIL import Image

    from autobonk.icons import ICON_DIR, ICONS

    minimap = Image.new("RGB", (400, 400), (130, 120, 140))
    minimap.paste(Image.open(ICON_DIR / ICONS[icon]), (190, 186))
    out = BytesIO()
    minimap.save(out, "PNG")
    return replace(run_frame("155925-987", timestamp), minimap=out.getvalue())


def test_presses_e_at_a_target_and_skips_it_when_nothing_happens():
    bot = Bot(targets={"喵喵": 5}, movement=Movement(target_ignore_s=60))

    assert Press("KeyE") in bot.step(standing_on("喵喵", 100.0))
    assert Press("KeyE") not in bot.step(standing_on("喵喵", 100.1))
    assert Press("KeyE") in bot.step(standing_on("喵喵", 101.0))  # spams E while waiting
    assert Press("KeyE") in bot.step(standing_on("喵喵", 102.0))  # still spams E with 3.0s timeout
    assert holds(bot.step(standing_on("喵喵", 103.0))) == []  # 3.0 s on: E did nothing, skip it
    assert holds(bot.step(standing_on("喵喵", 103.1))) == [Hold(frozenset({"Tab"}))]
    assert Press("KeyE") in bot.step(standing_on("喵喵", 166.0))


def test_instant_target_clearing_when_target_collected():
    bot = Bot(targets={"精灵球": 5})

    assert Press("KeyE") in bot.step(standing_on("精灵球", 100.0))

    # Next frame at 100.1s: item was collected, no targets on minimap!
    # Bot must NOT linger or spam E; it immediately clears target and explores with Tab
    empty_frame = replace(run_frame("155925-987", 100.1), minimap=b"")
    cmds = bot.step(empty_frame)
    assert Press("KeyE") not in cmds
    assert holds(cmds) == [Hold(frozenset({"Tab"}))]
    assert bot.status().target == ""


def test_target_ignore_by_instance_allows_another_same_target():
    bot = Bot(targets={"喵喵": 5}, movement=Movement(target_ignore_s=60))
    bot._now_weights = {"喵喵": 5.0}

    # First instance at (0.2, 0.2) fails after 5 seconds:
    bot._ignore_target("喵喵", 160.0, pos=(0.2, 0.2))

    # Candidate at (0.2, 0.2) is skipped:
    zonemap_candidates = [("喵喵", (0.205, 0.205)), ("喵喵", (0.8, 0.8))]
    filtered = bot._candidates(zonemap_candidates, now=110.0, is_zonemap=True)
    assert len(filtered) == 1
    assert filtered[0][1] == (0.8, 0.8)


def test_target_selection_hysteresis_prevents_flip_flopping():
    bot = Bot(targets={"A": 10, "B": 10}, movement=Movement(distance_factor=0.0))
    bot._now_weights = {"A": 10.0, "B": 10.0}

    # When no target is selected, highest/leftmost wins:
    candidates = [("A", (100, 0)), ("B", (100, 0))]
    assert bot._best(candidates, (0, 0))[0] == "A"

    # Once "B" is the active target, its hysteresis bonus keeps it active even if A is slightly better:
    bot._target = "B"
    # Challenger A has base weight 10.0. Current target B has base weight 9.0 (with 1.15 bonus: 10.35):
    bot._now_weights = {"A": 10.0, "B": 9.0}
    assert bot._best(candidates, (0, 0))[0] == "B"


def test_a_popup_after_e_means_it_worked():
    bot = Bot(targets={"精灵球": 5})
    bot.step(standing_on("精灵球", 100.0))
    bot.step(replace(LEVEL_UP, timestamp=100.5))

    assert Press("KeyE") in bot.step(standing_on("精灵球", 101.6))


def test_reads_level_time_left_and_the_boss_down_banner():
    seen = perceive(SEALED)

    assert (seen.level, seen.zone_index, seen.seconds_left) == (73, 2, 522)
    assert perceive(run_frame("155654-906", 0)).boss_down  # 头目水伊布倒下了！
    assert not perceive(run_frame("155532-914", 0)).boss_down  # 头目宝可梦！ (it just appeared)


def with_countdown(frame: Frame, countdown: str) -> Frame:
    return replace(frame, dom_snapshot=frame.dom_snapshot.replace(">8:42<", f">{countdown}<", 1))


def test_a_growing_weight_starts_at_its_start_weight_and_grows_as_time_runs_out():
    bot = Bot(targets={"精灵球": (0, 6)})

    assert holds(bot.step(with_countdown(ORE_AND_BALLS, "10:00"))) == [Hold(frozenset({"Tab"}))]  # weight 0
    assert holds(bot.step(replace(ORE_AND_BALLS, timestamp=101.0))) == [Hold(frozenset({"KeyW", "KeyA"}))]


def test_growing_weights_overtake_fixed_ones():
    bot = Bot(targets={"精灵球": (0, 10), "矿堆": 3})
    bot.step(with_countdown(ORE_AND_BALLS, "10:00"))  # Poké Balls 0 < ore 3

    bot.step(replace(ORE_AND_BALLS, timestamp=101.0))  # 8:42, 78 s of 600 gone: Poké Balls 1.3 < ore 3
    assert bot._now_weights == {"矿堆": 3.0, "精灵球": pytest.approx(1.3)}
    bot.step(with_countdown(ORE_AND_BALLS, "3:00"))
    assert bot._now_weights["精灵球"] == pytest.approx(7.0)


def test_boss_rule_level_or_time_per_zone():
    rule = BossRule(levels=(35, 60, 80), minutes_left=(4, 8, 8))

    assert rule.ready(1, 35, 500) and not rule.ready(1, 34, 500)
    assert rule.ready(1, 10, 240) and not rule.ready(1, 10, 241)
    assert rule.ready(2, 10, 480) and not rule.ready(2, 59, 481)
    assert rule.ready(3, 80, 600)


def test_the_boss_is_not_summoned_until_strong_enough():
    bot = Bot(boss=BossRule(levels=(99, 99, 99), minutes_left=(0, 0, 0)))

    assert Press("KeyE") not in bot.step(standing_on("骷髅", 100.0))


def test_once_strong_enough_the_boss_is_summoned_and_altars_are_left_while_it_chases():
    bot = Bot(boss=BossRule(levels=(1, 1, 1)))
    skull = replace(run_frame("155220-116", 100.0), minimap=standing_on("骷髅", 0).minimap)  # same zone as below

    assert Press("KeyE") in bot.step(skull)
    # Chased: the altar ahead is not walked to (it needs standing still); explore instead.
    assert holds(bot.step(run_frame("155220-116", 101.0))) == [Hold(frozenset({"Tab"}))]


def test_after_the_boss_falls_altars_count_again_and_it_is_not_summoned_twice():
    bot = Bot(boss=BossRule(levels=(1, 1, 1)))
    skull = replace(run_frame("155654-906", 100.0), minimap=standing_on("骷髅", 0).minimap)
    bot.step(skull)
    beaten = replace(run_frame("155654-906", 101.0), minimap=standing_on("骷髅", 0).minimap)

    assert Press("KeyE") not in bot.step(beaten)
    assert "骷髅" not in bot._now_weights and "传送门" in bot._now_weights


def test_visible_hud_prompt_presses_e_and_stops_moving():
    frame = replace(
        run_frame("155925-987", 100.0),
        dom_snapshot=run_frame("155925-987", 100.0).dom_snapshot + '<div class="prompt" style=""><kbd>E</kbd>打开超级球（免费）</div>',
    )
    bot = Bot()
    bot._held = frozenset({"KeyW"})
    commands = bot.step(frame)
    assert Hold(frozenset()) in commands
    assert Press("KeyE") in commands


def test_hud_prompt_with_not_enough_money_is_ignored():
    frame = replace(
        run_frame("155925-987", 100.0),
        dom_snapshot=run_frame("155925-987", 100.0).dom_snapshot + '<div class="prompt" style=""><kbd>E</kbd>老虎机 · 43 ₽（钱不够）</div>',
    )
    bot = Bot()
    assert Press("KeyE") not in bot.step(frame)


def test_boss_prompt_waits_until_strong_enough():
    frame = replace(
        run_frame("155925-987", 100.0),
        dom_snapshot=run_frame("155925-987", 100.0).dom_snapshot + '<div class="prompt" style=""><kbd>E</kbd>唤醒守护者</div>',
    )
    bot = Bot(boss=BossRule(levels=(99, 99, 99), minutes_left=(0, 0, 0)))
    assert Press("KeyE") not in bot.step(frame)



def test_boss_down_banners_and_portal_detection():
    # Guardian beaten banner (from 20261028 run)
    obs_guardian = perceive(load_frame(FRAMES / "frame-20261028-022542-352"))
    assert obs_guardian.boss_down
    assert obs_guardian.portal is not None

    # Head boss defeated banner
    obs_head = perceive(run_frame("155654-906", 0.0))
    assert obs_head.boss_down

    # Frame with toast warning: unopened super balls
    obs_toast = perceive(run_frame("160041-764", 0.0))
    assert obs_toast.has_unopened_super_balls
    assert obs_toast.portal is not None

    # Frame with active portal: read off the minimap icon (same scale as every target),
    # not the faded "传送门！" toast.
    obs_portal = perceive(run_frame("214628-985", 0.0))
    assert obs_portal.portal == (-10, -38)


def test_after_boss_opens_nearby_super_balls_before_entering_portal():
    f3 = run_frame("214628-985", 100.0)
    bot = Bot(targets={"符文祭坛": 7.0, "超级球": 10.0, "精灵球": 5.0})
    bot.step(f3)  # initialize zone to 区域 1/3
    bot._boss_beaten = True

    # 1. When super balls are nearby, bot targets super ball first
    obs_with_balls = perceive(f3, bot._icons)
    bot._move(obs_with_balls, 100.5)
    assert bot._target in ("超级球", "礼物球")

    # 2. If standing on portal prompt while super balls remain, do NOT enter portal
    obs_at_portal_with_balls = replace(obs_with_balls, prompt=("E", "进入传送门"), portal=(0, 0))
    portal_commands = bot._move(obs_at_portal_with_balls, 100.6)
    assert Press("KeyE") not in portal_commands

    # 3. When no super balls remain, bot targets portal and enters it
    obs_portal_only = replace(obs_with_balls, targets=())
    portal_move = bot._move(obs_portal_only, 101.0)
    assert bot._target == "传送门"
    assert Hold(frozenset({"KeyW"})) in portal_move

    # 4. At the portal with no super balls remaining, bot presses E
    obs_at_portal = replace(obs_with_balls, targets=(), portal=(0, 0), prompt=("E", "进入传送门"))
    enter_commands = bot._move(obs_at_portal, 101.5)
    assert Press("KeyE") in enter_commands


def test_remembers_close_target_position_when_player_arrow_blocks_icon():
    bot = Bot(targets={"百变怪": 10.0})
    base_obs = perceive(run_frame("155925-987", 100.0), bot._icons)

    # 1. Target seen at 20 px east: bot walks east and saves temp (x, y)
    obs_close = replace(base_obs, targets=(("百变怪", (20, 0)),))
    cmds1 = bot._move(obs_close, 100.0)
    assert Hold(frozenset({"KeyD"})) in cmds1
    assert Press("KeyE") in cmds1

    # 2. Next step (0.4 s later): player arrow covers the icon so targets=() on minimap.
    # Bot keeps walking east toward the remembered temp (x, y) and spams E instead of opening Tab!
    obs_blocked = replace(base_obs, targets=())
    cmds2 = bot._move(obs_blocked, 100.4)
    assert bot._held == frozenset({"KeyD"})
    assert Press("KeyE") in cmds2

    # 3. Once the remembered position reaches <= 4 px (at 101.0 s), bot stops on the spot and spams E.
    cmds3 = bot._move(obs_blocked, 101.0)
    assert Hold(frozenset()) in cmds3
    assert Press("KeyE") in cmds3

    # 4. Once interact timeout passes without popup/charging (e.g. blocked or no money), target is ignored and bot explores.
    cmds4 = bot._move(obs_blocked, 101.5)
    assert Hold(frozenset({"Tab"})) in cmds4


def test_overtime_countdown_is_recognised_with_negative_seconds_left():
    overtime = run_frame("232940-022", 100.0)
    obs = perceive(overtime)
    assert obs.countdown == "+1:09"
    assert obs.seconds_left == -69
    assert obs.recognised


def test_boss_rule_supports_overtime_negative_minutes():
    # Zone 1 requires 4 mins left, Zone 2 requires -3 mins (i.e. +03:00 overtime), Zone 3 requires -5 mins
    rule = BossRule(levels=(999, 999, 999), minutes_left=(4, -3, -5))

    # In Zone 2:
    # At normal 00:00 (seconds_left = 0): -3 * 60 = -180; 0 <= -180 is False
    assert not rule.ready(zone=2, level=50, seconds_left=0)
    # At overtime +02:00 (seconds_left = -120): -120 <= -180 is False
    assert not rule.ready(zone=2, level=50, seconds_left=-120)
    # At overtime +03:00 (seconds_left = -180): -180 <= -180 is True
    assert rule.ready(zone=2, level=50, seconds_left=-180)
    # At overtime +03:30 (seconds_left = -210): -210 <= -180 is True
    assert rule.ready(zone=2, level=50, seconds_left=-210)


def test_boss_on_zonemap_is_targeted_and_not_stopped_by_charging_altars():
    f1 = load_frame(FRAMES / "frame-20261030-232650-966")
    bot = Bot(boss=BossRule(levels=(35, 60, 80), minutes_left=(4, 8, 8)))
    cmds1 = bot.step(f1)
    # Boss is ready and chosen from the ZoneMap; bot heads toward it holding Tab
    assert bot._target == "骷髅"
    assert Hold(frozenset({"Tab", "KeyW", "KeyD"})) in cmds1

    # On a subsequent frame with an altar charging on the minimap, bot does NOT freeze in altar ring:
    # it keeps holding Tab + movement keys and does not release them.
    f2 = load_frame(FRAMES / "frame-20261030-232745-637")
    cmds2 = bot.step(f2)
    assert bot._target == "骷髅"
    assert bot._held == frozenset({"Tab", "KeyW", "KeyD"})
    assert Hold(frozenset()) not in cmds2


def test_boss_beaten_prioritizes_loot_over_portal():
    from unittest.mock import patch

    from autobonk.game import GIFT_BALL, INTERACT_KEY, PORTAL
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase

    bot = Bot()
    bot._zone_tracker.update("区域 1/3", 100)
    bot._zone_tracker.boss_phase = BossPhase.BEATEN

    obs_with_loot = Observation(
        end_screen=None,
        zone="区域 1/3",
        countdown="05:00",
        portal=(10, 10),
        prompt=("E", "进入传送门"),
        targets=((GIFT_BALL, (25, -15)),),
        has_unopened_super_balls=False,
    )
    dummy = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")

    with patch("autobonk.policy.bot.perceive", return_value=obs_with_loot):
        cmds = bot.step(dummy)

    assert bot._target_selector.current_target == GIFT_BALL
    # Entering portal is blocked while loot remains
    assert not any(getattr(c, "key", None) == INTERACT_KEY for c in cmds)

    # When loot is collected, portal is targeted and entered
    obs_cleared = Observation(
        end_screen=None,
        zone="区域 1/3",
        countdown="05:00",
        portal=(10, 10),
        prompt=("E", "进入传送门"),
        targets=(),
        has_unopened_super_balls=False,
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs_cleared):
        cmds = bot.step(dummy)

    assert bot._target_selector.current_target == PORTAL
    assert any(getattr(c, "key", None) == INTERACT_KEY for c in cmds)


def test_real_frame_001530_014_collects_loot_before_portal():
    from autobonk.game import GIFT_BALL, PORTAL, SUPER_BALL
    from autobonk.policy.zone import BossPhase

    frame = load_frame(FRAMES / "frame-20261031-001530-014")
    bot = Bot()
    bot._zone_tracker.update("区域 1/3", 100)
    bot._zone_tracker.boss_phase = BossPhase.BEATEN

    cmds = bot.step(frame)
    target = bot._target_selector.current_target
    assert target in (SUPER_BALL, GIFT_BALL)
    assert target != PORTAL
    assert not any(getattr(c, "key", None) == "KeyE" for c in cmds)


def test_sanctuary_flow_navigation_summon_and_exit():
    from unittest.mock import patch

    from autobonk.game import ALTAR, PORTAL
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase

    bot = Bot()
    # 1. Enter sanctuary: target is ALTAR with infinite weight
    obs_enter = Observation(
        end_screen=None,
        countdown="0:50",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
        altars=((0, -30),),
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs_enter):
        cmds = bot.step(load_frame(FRAMES / "frame-20261031-153043-487"))
    assert bot._target_selector.current_target == ALTAR
    assert bot._zone_tracker.boss_phase == BossPhase.WAITING

    # 2. At the altar: prompt [E] 触碰圣地 appears -> presses E while staying in WAITING until trigger disappears
    obs_at_altar = Observation(
        end_screen=None,
        countdown="0:48",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
        prompt=("E", "触碰圣地"),
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs_at_altar):
        cmds = bot.step(load_frame(FRAMES / "frame-20261031-153043-487"))
    assert any(getattr(c, "key", None) == "KeyE" for c in cmds)
    assert bot._boss_interacted is True
    assert bot._zone_tracker.boss_phase == BossPhase.WAITING

    # 2b. Altar prompt disappears (boss successfully summoned!) -> enters FIGHTING
    obs_fighting = Observation(
        end_screen=None,
        countdown="0:47",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs_fighting):
        bot.step(load_frame(FRAMES / "frame-20261031-153043-487"))
    assert bot._zone_tracker.boss_phase == BossPhase.FIGHTING

    # 3. Boss defeated: prompt [E] 离开圣地 appears -> boss is beaten, target is portal, presses E
    obs_beaten = Observation(
        end_screen=None,
        countdown="0:30",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
        prompt=("E", "离开圣地"),
        portal=(0, 0),
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs_beaten):
        cmds = bot.step(load_frame(FRAMES / "frame-20261031-153043-487"))
    assert bot._zone_tracker.boss_phase == BossPhase.BEATEN
    assert bot._target_selector.current_target == PORTAL
    assert any(getattr(c, "key", None) == "KeyE" for c in cmds)


def test_sanctuary_boss_summon_waits_for_trigger_disappear_and_does_not_timeout():
    from unittest.mock import patch

    from autobonk.game import ALTAR
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase
    from autobonk.runtime.frames import Frame

    bot = Bot()
    bot._zone_tracker.zone = "森林圣地"
    bot._zone_tracker.is_sanctuary = True
    bot._zone_tracker.boss_phase = BossPhase.WAITING

    # Step 1: Arrived at sanctuary altar, prompt is [E] 触碰圣地
    obs_altar = Observation(
        end_screen=None,
        countdown="0:45",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
        prompt=("E", "触碰圣地"),
    )
    f1 = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_altar):
        cmds1 = bot.step(f1)
    assert any(getattr(c, "key", None) == "KeyE" for c in cmds1)
    assert bot._boss_interacted is True
    assert bot._zone_tracker.boss_phase == BossPhase.WAITING

    # Step 2: 4 seconds later, prompt is STILL present (e.g. boss didn't trigger yet).
    # Bot MUST NOT time out with "E did nothing, skipping for 60s"!
    # It must stay targeting ALTAR and press E again.
    f2 = Frame(screenshot=b"", dom_snapshot="", timestamp=14.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_altar):
        cmds2 = bot.step(f2)
    assert bot._target_selector.current_target == ALTAR
    assert not bot._target_selector.is_skipped(ALTAR, 14.0)
    assert bot._zone_tracker.boss_phase == BossPhase.WAITING
    assert any(getattr(c, "key", None) == "KeyE" for c in cmds2)

    # Step 3: Trigger icon / prompt disappears (boss successfully summoned!)
    obs_fighting = Observation(
        end_screen=None,
        countdown="0:40",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
    )
    f3 = Frame(screenshot=b"", dom_snapshot="", timestamp=14.5, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_fighting):
        bot.step(f3)
    assert bot._zone_tracker.boss_phase == BossPhase.FIGHTING

    # Step 4: If trigger prompt reappears after 1s in FIGHTING, it reverts to WAITING
    f4 = Frame(screenshot=b"", dom_snapshot="", timestamp=16.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_altar):
        bot.step(f4)
    assert bot._zone_tracker.boss_phase == BossPhase.WAITING


def test_sanctuary_final_boss_fighting_orbits_arena_center():
    from unittest.mock import patch

    from autobonk.commands import Hold
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase
    from autobonk.runtime.frames import Frame

    bot = Bot()
    bot._zone_tracker.zone = "森林圣地"
    bot._zone_tracker.is_sanctuary = True
    bot._zone_tracker.boss_phase = BossPhase.FIGHTING
    bot._boss_summoned_at = 10.0

    obs_fighting = Observation(
        end_screen=None,
        countdown="0:40",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
    )
    directions_seen: set[frozenset[str]] = set()
    for t in [10.0, 10.9, 11.8, 12.7]:
        frame = Frame(screenshot=b"", dom_snapshot="", timestamp=t, url="")
        with patch("autobonk.policy.bot.perceive", return_value=obs_fighting):
            cmds = bot.step(frame)
        assert bot._target_selector.current_target == "最终Boss"
        for c in cmds:
            if isinstance(c, Hold) and c.keys:
                directions_seen.add(c.keys)
    assert len(directions_seen) >= 3



def test_sanctuary_boss_beaten_prioritizes_loot_over_exit():
    from unittest.mock import patch

    from autobonk.game import GIFT_BALL, PORTAL, SUPER_BALL
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase

    bot = Bot()
    bot._zone_tracker.zone = "森林圣地"
    bot._zone_tracker.is_sanctuary = True
    bot._zone_tracker.boss_phase = BossPhase.BEATEN

    # Sanctuary boss is defeated, exit portal prompt is active at (0, 0),
    # but there is a Gift Ball dropped 20px away.
    obs_loot = Observation(
        end_screen=None,
        countdown="0:30",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
        portal=(0, 0),
        prompt=("E", "离开圣地"),
        targets=((GIFT_BALL, (20, 0)), (SUPER_BALL, (40, 0))),
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs_loot):
        cmds = bot.step(load_frame(FRAMES / "frame-20261031-153043-487"))

    # Bot MUST NOT exit yet; it must prioritize GIFT_BALL and steer toward it
    assert bot._target_selector.current_target == GIFT_BALL
    assert not any(getattr(c, "key", None) == "KeyE" for c in cmds)

    # After picking up loot (targets empty), bot targets PORTAL and presses E
    obs_exit = Observation(
        end_screen=None,
        countdown="0:25",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
        portal=(0, 0),
        prompt=("E", "离开圣地"),
        targets=(),
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs_exit):
        cmds_exit = bot.step(load_frame(FRAMES / "frame-20261031-153043-487"))

    assert bot._target_selector.current_target == PORTAL
    assert any(getattr(c, "key", None) == "KeyE" for c in cmds_exit)


def test_sanctuary_navigates_normally_when_zonemap_is_open():
    from unittest.mock import patch

    from autobonk.game import ALTAR
    from autobonk.perception.dom import Observation
    from autobonk.perception.zonemap import ZoneMap

    bot = Bot()
    obs = Observation(
        end_screen=None,
        countdown="0:50",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
        zonemap=ZoneMap(player=(0.5, 0.5), altars=((0.5, 0.4),), targets=()),
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs):
        bot.step(load_frame(FRAMES / "frame-20261031-153043-487"))
    assert bot._target_selector.current_target == ALTAR


def test_sanctuary_ignores_lingering_defeat_banner_when_waiting():
    from unittest.mock import patch

    from autobonk.game import ALTAR
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase

    bot = Bot()
    # Simulates entering sanctuary immediately after defeating zone 3 boss:
    # A victory banner is still lingering in DOM texts (boss_down=True),
    # but the sanctuary boss has not been summoned yet (WAITING).
    obs_enter_with_banner = Observation(
        end_screen=None,
        countdown="0:59",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
        boss_down=True,
        level=155,
        altars=((0, -30),),
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs_enter_with_banner):
        bot.step(load_frame(FRAMES / "frame-20261031-153043-487"))
    assert bot._zone_tracker.boss_phase == BossPhase.WAITING
    assert bot._target_selector.current_target == ALTAR


def test_sanctuary_in_view_exit_portal_navigates_to_victory():
    from autobonk.game import PORTAL
    from autobonk.policy.zone import BossPhase

    frame = load_frame(FRAMES / "frame-20261031-174520-714")
    obs = perceive(frame)
    # The exit portal is on the minimap, down-right of the player
    assert obs.portal == (21, 17)

    bot = Bot()
    bot._zone_tracker.zone = "森林圣地"
    bot._zone_tracker.is_sanctuary = True
    bot._zone_tracker.boss_phase = BossPhase.FIGHTING

    cmds = bot.step(frame)
    assert bot._zone_tracker.boss_phase == BossPhase.BEATEN
    assert bot._target_selector.current_target == PORTAL
    # Moves toward south-east (where portal is)
    hold = next((c for c in cmds if hasattr(c, "keys")), None)
    assert hold is not None
    assert "KeyS" in hold.keys and "KeyD" in hold.keys






def test_wayside_sub_target_picked_up_en_route_to_distant_main_target():
    from unittest.mock import patch

    from autobonk.game import ALTAR, SUPER_BALL
    from autobonk.perception.dom import Observation

    bot = Bot(targets={ALTAR: 10.0, SUPER_BALL: 8.0})
    obs = Observation(
        end_screen=None,
        countdown="08:00",
        zone="绿茵森林",
        altars=((0, -160),),
        targets=((SUPER_BALL, (5, -40)),),
    )
    dummy = Frame(screenshot=b"", dom_snapshot="", timestamp=1.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs):
        bot.step(dummy)

    status = bot.status()
    assert status.main_target == ALTAR
    assert status.sub_target == SUPER_BALL
    assert "KeyW" in bot._held


def test_wayside_sub_target_ignores_backtracking_items():
    from unittest.mock import patch

    from autobonk.game import ALTAR, COIN
    from autobonk.perception.dom import Observation

    bot = Bot(targets={ALTAR: 10.0, COIN: 2.0})
    # Target 1: far behind the player (0, 80)
    obs = Observation(
        end_screen=None,
        countdown="08:00",
        zone="绿茵森林",
        altars=((0, -150),),
        targets=((COIN, (0, 80)),),
    )
    dummy = Frame(screenshot=b"", dom_snapshot="", timestamp=1.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs):
        bot.step(dummy)

    status = bot.status()
    assert status.main_target == ALTAR
    assert status.sub_target == ""

    # Target 2: right behind the player (0, 5). Even though detour is only 10px,
    # forward hemisphere dot-product check prevents turning backwards.
    obs_close_behind = Observation(
        end_screen=None,
        countdown="08:00",
        zone="绿茵森林",
        altars=((0, -150),),
        targets=((COIN, (0, 5)),),
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs_close_behind):
        bot.step(dummy)

    status = bot.status()
    assert status.main_target == ALTAR
    assert status.sub_target == ""


def test_sub_target_hysteresis_prevents_jitter_between_close_items():
    from autobonk.game import COIN, POKEBALL
    from autobonk.policy.targets import TargetSelector

    ts = TargetSelector(targets={POKEBALL: 5.0, COIN: 5.0})
    ts.active_weights = {POKEBALL: 5.0, COIN: 5.0}

    candidates = [
        (COIN, (12, -50)),
        (POKEBALL, (-12, -50)),
    ]
    # Initially without lock, one wins
    first = ts.find_sub_target(candidates, "ALTAR", (0, -150))
    assert first is not None
    ts.sub_target = first[0]

    # With sub_target locked, even if the other item is slightly closer (11px vs 12px),
    # hysteresis (20% bonus) keeps the current sub_target locked
    other_name = POKEBALL if first[0] == COIN else COIN
    slightly_shifted_candidates = [
        (first[0], (12, -50)),
        (other_name, (-11, -50)),
    ]
    second = ts.find_sub_target(slightly_shifted_candidates, "ALTAR", (0, -150))
    assert second is not None
    assert second[0] == first[0]


def test_sub_target_allowances_hot_reloaded():
    bot = Bot()
    assert bot._target_selector.sub_target_base_allowance == 12.0
    assert bot._target_selector.sub_target_weight_factor == 3.0

    bot.reload_config(
        sub_target_base_allowance=25.0,
        sub_target_weight_factor=6.0,
    )
    assert bot._target_selector.sub_target_base_allowance == 25.0
    assert bot._target_selector.sub_target_weight_factor == 6.0


def test_boss_activation_keeps_waiting_and_targets_boss_if_skull_remains():
    from unittest.mock import patch

    from autobonk.game import BOSS, BossRule
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase

    bot = Bot(boss=BossRule(levels=(1, 1, 1)))

    # Step 1: At skull altar with prompt, bot presses E
    obs_summon = Observation(
        end_screen=None,
        countdown="07:30",
        zone="区域 2/3",
        zone_idx=2,
        level=52,
        prompt=("E", "唤醒守护者"),
        targets=((BOSS, (0, 0)),),
    )
    dummy = Frame(screenshot=b"", dom_snapshot="", timestamp=100.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_summon):
        cmds1 = bot.step(dummy)

    assert any(getattr(c, "key", None) == "KeyE" for c in cmds1)

    # Step 2: Next frame, skull icon is STILL on minimap and prompt is still active (E did not trigger)
    # Bot must NOT transition to FIGHTING; must stay in WAITING and continue targeting BOSS
    obs_untriggered = Observation(
        end_screen=None,
        countdown="07:29",
        zone="区域 2/3",
        zone_idx=2,
        level=52,
        prompt=("E", "唤醒守护者"),
        targets=((BOSS, (0, 0)),),
    )
    dummy2 = Frame(screenshot=b"", dom_snapshot="", timestamp=101.2, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_untriggered):
        cmds2 = bot.step(dummy2)

    assert bot._zone_tracker.boss_phase == BossPhase.WAITING
    assert bot._target_selector.current_target == BOSS
    assert any(getattr(c, "key", None) == "KeyE" for c in cmds2)


def test_popup_during_charging_does_not_abandon_or_ignore_altar():
    from unittest.mock import patch

    from autobonk.game import ALTAR, Card
    from autobonk.perception.dom import Button, Observation, Popup

    bot = Bot()
    # 1. Altar is charging
    obs_charging = Observation(
        end_screen=None,
        countdown="07:00",
        zone="区域 1/3",
        charging=True,
        altars=((0, 0),),
    )
    dummy = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_charging):
        bot.step(dummy)

    assert bot.status().charging is True
    assert bot._target_selector.current_target == ALTAR

    # 2. A level-up popup appears mid-charge!
    popup = Popup(
        title="升级啦！",
        cards=(Card(key="c1", name="撞击", rarity="普通"),),
        buttons=(Button(text="选择 [1]", key="1"),),
    )
    obs_popup = Observation(
        end_screen=None,
        countdown="07:00",
        zone="区域 1/3",
        charging=True,
        altars=((0, 0),),
        popup=popup,
    )
    dummy_popup = Frame(screenshot=b"", dom_snapshot="", timestamp=10.5, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_popup):
        bot.step(dummy_popup)

    # Bot must NOT ignore the altar and must keep ALTAR as current target
    assert not bot._target_selector.is_skipped(ALTAR, 11.0)
    assert bot._target_selector.current_target == ALTAR
    assert bot.status().charging is True


def test_level_up_mid_transit_preserves_main_target_and_tab_hold():
    from unittest.mock import patch

    from autobonk.game import MAP_KEY, SUPER_BALL, Card
    from autobonk.perception.dom import Button, Observation, Popup
    from autobonk.perception.zonemap import ZoneMap

    bot = Bot(targets={SUPER_BALL: 10.0})
    # 1. Player is exploring with Tab held, targeting SUPER_BALL on zonemap (to the east)
    obs_zone = Observation(
        end_screen=None,
        countdown="07:00",
        zone="区域 1/3",
        zonemap=ZoneMap(player=(0.5, 0.5), altars=(), targets=((SUPER_BALL, (0.8, 0.5)),)),
        north=0.0,
    )
    d1 = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_zone):
        bot.step(d1)

    assert bot.status().main_target == SUPER_BALL
    assert bot.status().target == SUPER_BALL
    assert MAP_KEY in bot._held

    # 2. Level up popup appears while Tab is held mid-transit!
    popup = Popup(
        title="等级 2！",
        cards=(Card(key="1", name="撞击", rarity="普通"),),
        buttons=(Button(text="选择 [1]", key="1"), Button(text="查看我的队伍", key="Tab")),
    )
    obs_popup = Observation(
        end_screen=None,
        countdown="07:00",
        zone="区域 1/3",
        popup=popup,
    )
    d2 = Frame(screenshot=b"", dom_snapshot="", timestamp=10.5, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_popup):
        cmds2 = bot.step(d2)

    # Bot must NOT release Tab (which would trigger Team View over popup in game)
    assert Hold(frozenset({MAP_KEY})) in cmds2
    assert ReleaseAll() not in cmds2
    assert Press("1") in cmds2

    # Target must NOT be cleared or set to 探索漫游!
    assert bot._target_selector.current_target == SUPER_BALL
    assert bot.status().main_target == SUPER_BALL
    assert bot.status().target == SUPER_BALL
    assert bot._held == frozenset({MAP_KEY})

    # 3. Popup closes, next frame zonemap continues seamlessly without needing to recalculate from scratch
    d3 = Frame(screenshot=b"", dom_snapshot="", timestamp=10.6, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_zone):
        cmds3 = bot.step(d3)

    assert bot.status().main_target == SUPER_BALL
    assert bot.status().target == SUPER_BALL
    # Movement keys are re-engaged immediately toward target while keeping Tab held
    assert any(isinstance(c, Hold) and MAP_KEY in c.keys and "KeyD" in c.keys for c in cmds3)


def test_level_up_mid_transit_preserves_minimap_target_and_temp_target():
    from unittest.mock import patch

    from autobonk.game import SUPER_BALL, Card
    from autobonk.perception.dom import Button, Observation, Popup

    bot = Bot(targets={SUPER_BALL: 10.0})
    # 1. Player is navigating to SUPER_BALL on minimap (at (0, -20))
    obs_mini = Observation(
        end_screen=None,
        countdown="07:00",
        zone="区域 1/3",
        targets=((SUPER_BALL, (0, -20)),),
    )
    d1 = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_mini):
        bot.step(d1)

    assert bot.status().main_target == SUPER_BALL
    assert bot._target_selector.current_target == SUPER_BALL

    # 2. Level up popup appears
    popup = Popup(
        title="等级 2！",
        cards=(Card(key="1", name="撞击", rarity="普通"),),
        buttons=(Button(text="选择 [1]", key="1"),),
    )
    obs_popup = Observation(
        end_screen=None,
        countdown="07:00",
        zone="区域 1/3",
        popup=popup,
    )
    d2 = Frame(screenshot=b"", dom_snapshot="", timestamp=10.5, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs_popup):
        cmds2 = bot.step(d2)

    assert ReleaseAll() in cmds2
    assert Press("1") in cmds2
    # Target and temp target must NOT be cleared to None
    assert bot._target_selector.current_target == SUPER_BALL
    assert bot.status().target == SUPER_BALL
    assert bot.status().main_target == SUPER_BALL


def test_altar_knockback_triggers_reentry_instead_of_abandoning():
    from unittest.mock import patch

    from autobonk.game import ALTAR
    from autobonk.perception.dom import Observation

    bot = Bot()
    # 1. Charging at altar center (0, 0)
    obs1 = Observation(
        end_screen=None,
        countdown="07:00",
        zone="区域 1/3",
        charging=True,
        altars=((0, 0),),
    )
    d1 = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs1):
        bot.step(d1)
    assert bot.status().charging is True

    # 2. Monsters knock player back to 20px (altar at (0, -20)), charging becomes False for 0.5s
    obs2 = Observation(
        end_screen=None,
        countdown="06:59",
        zone="区域 1/3",
        charging=False,
        altars=((0, -20),),
    )
    d2 = Frame(screenshot=b"", dom_snapshot="", timestamp=10.5, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs2):
        bot.step(d2)

    # Bot should steer north (KeyW) back to altar, not abandon it!
    assert not bot._target_selector.is_skipped(ALTAR, 11.0)
    assert bot._target_selector.current_target == ALTAR
    assert "KeyW" in bot._held


def test_strict_boss_lifecycle_waiting_to_fighting_to_beaten_with_loot_and_portal():
    from unittest.mock import patch

    from autobonk.game import BOSS, GIFT_BALL, PORTAL, SUPER_BALL, BossRule
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase

    bot = Bot(boss=BossRule(levels=(20, 20, 20)))

    # Step 1: Waiting phase, level 17 (requirement NOT met yet).
    # Even if wild alpha dies (boss_down=True) or portal is mistakenly detected, phase MUST stay WAITING!
    obs1 = Observation(
        end_screen=None,
        countdown="07:50",
        zone="区域 1/3",
        zone_idx=1,
        level=17,
        boss_down=True,
        portal=(50, 50),
        altars=((0, 0),),
        targets=((BOSS, (100, 100)),),
    )
    d1 = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs1):
        bot.step(d1)
    assert bot._zone_tracker.boss_phase == BossPhase.WAITING
    assert bot._target_selector.current_target != BOSS

    # Step 2: Requirement met (Lv 20)! Bot targets 骷髅 and moves toward it.
    obs2 = Observation(
        end_screen=None,
        countdown="07:30",
        zone="区域 1/3",
        zone_idx=1,
        level=20,
        altars=((0, 0),),
        targets=((BOSS, (40, 0)),),
    )
    d2 = Frame(screenshot=b"", dom_snapshot="", timestamp=15.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs2):
        bot.step(d2)
    assert bot._target_selector.current_target == BOSS
    assert bot._zone_tracker.boss_phase == BossPhase.WAITING

    # Step 3: Arrived at 骷髅, prompt appears -> presses E.
    # But 骷髅 is still present -> MUST stay in WAITING and repeat pressing E!
    obs3 = Observation(
        end_screen=None,
        countdown="07:28",
        zone="区域 1/3",
        zone_idx=1,
        level=20,
        prompt=("E", "唤醒守护者"),
        targets=((BOSS, (0, 0)),),
    )
    d3 = Frame(screenshot=b"", dom_snapshot="", timestamp=20.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs3):
        cmds3 = bot.step(d3)
    assert any(getattr(c, "key", None) == "KeyE" for c in cmds3)
    assert bot._zone_tracker.boss_phase == BossPhase.WAITING
    assert bot._boss_interacted is True

    # Step 4: Next frame, 骷髅 is STILL on minimap and prompt still active (summon taking a moment).
    # Bot stays in WAITING and presses E again!
    d4 = Frame(screenshot=b"", dom_snapshot="", timestamp=20.4, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs3):
        cmds4 = bot.step(d4)
    assert any(getattr(c, "key", None) == "KeyE" for c in cmds4)
    assert bot._zone_tracker.boss_phase == BossPhase.WAITING

    # Step 5: 骷髅 disappears (触发成功!) -> enters FIGHTING!
    obs5 = Observation(
        end_screen=None,
        countdown="07:25",
        zone="区域 1/3",
        zone_idx=1,
        level=20,
        targets=(),
    )
    d5 = Frame(screenshot=b"", dom_snapshot="", timestamp=21.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs5):
        bot.step(d5)
    assert bot._zone_tracker.boss_phase == BossPhase.FIGHTING

    # Step 6: Boss is beaten + portal appears -> enters BEATEN!
    # Nearby boss loot (超级球 and 礼物球) is on the minimap.
    obs6 = Observation(
        end_screen=None,
        countdown="07:00",
        zone="区域 1/3",
        zone_idx=1,
        level=21,
        boss_down=True,
        portal=(80, 80),
        targets=((SUPER_BALL, (0, 0)), (GIFT_BALL, (25, 0))),
    )
    d6 = Frame(screenshot=b"", dom_snapshot="", timestamp=30.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs6):
        cmds6 = bot.step(d6)
    assert bot._zone_tracker.boss_phase == BossPhase.BEATEN
    # Bot focuses on closest boss loot (SUPER_BALL) first, not the portal!
    assert any(getattr(c, "key", None) == "KeyE" for c in cmds6)

    # Step 7: SUPER_BALL collected, now picks up GIFT_BALL
    obs7 = Observation(
        end_screen=None,
        countdown="06:58",
        zone="区域 1/3",
        zone_idx=1,
        level=21,
        portal=(80, 80),
        targets=((GIFT_BALL, (10, 0)),),
    )
    d7 = Frame(screenshot=b"", dom_snapshot="", timestamp=31.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs7):
        bot.step(d7)
    assert bot._target_selector.current_target == GIFT_BALL

    # Step 8: All loot collected -> targets PORTAL and heads to next stage!
    obs8 = Observation(
        end_screen=None,
        countdown="06:55",
        zone="区域 1/3",
        zone_idx=1,
        level=21,
        portal=(80, 80),
        targets=(),
    )
    d8 = Frame(screenshot=b"", dom_snapshot="", timestamp=32.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs8):
        bot.step(d8)
    assert bot._target_selector.current_target == PORTAL

    # Step 9: At portal with prompt -> presses E to enter!
    obs9 = Observation(
        end_screen=None,
        countdown="06:50",
        zone="区域 1/3",
        zone_idx=1,
        level=21,
        portal=(0, 0),
        prompt=("E", "进入传送门"),
        targets=(),
    )
    d9 = Frame(screenshot=b"", dom_snapshot="", timestamp=34.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs9):
        cmds9 = bot.step(d9)
    assert any(getattr(c, "key", None) == "KeyE" for c in cmds9)


def test_does_not_press_portal_e_from_far_away():
    from unittest.mock import patch

    from autobonk.game import PORTAL
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase
    from autobonk.runtime.controller import Hold

    bot = Bot(targets={"传送门": 10.0})
    bot._zone_tracker.zone = "区域 1/3"
    bot._zone_tracker.boss_phase = BossPhase.BEATEN
    obs = Observation(
        end_screen=None,
        countdown="05:00",
        zone="区域 1/3",
        zone_idx=1,
        portal=(0, -25),
        prompt=("E", "进入传送门"),
        targets=(),
    )
    frame = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs):
        cmds = bot.step(frame)

    assert bot._target_selector.current_target == PORTAL
    # Must move toward portal (KeyW), must NOT press E yet from 25px away!
    assert any(isinstance(c, Hold) and "KeyW" in c.keys for c in cmds)
    assert not any(getattr(c, "key", None) == "KeyE" for c in cmds)


def test_sanctuary_waiting_goes_to_altar_even_if_portal_visible():
    from unittest.mock import patch

    from autobonk.game import ALTAR
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase

    bot = Bot()
    obs = Observation(
        end_screen=None,
        countdown="0:00",
        zone="森林圣地",
        zone_idx=4,
        is_sanctuary=True,
        portal=(15, 20),
        altars=((0, -35),),
        targets=(),
    )
    frame = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs):
        bot.step(frame)

    assert bot._zone_tracker.boss_phase == BossPhase.WAITING
    assert bot._target_selector.current_target == ALTAR


def test_target_keeps_moving_until_matching_prompt_or_close():
    from unittest.mock import patch

    from autobonk.perception.dom import Observation
    from autobonk.runtime.controller import Hold

    bot = Bot(targets={"矿堆": 10.0})
    # Target is at 3px away, no prompt yet -> bot must continue moving!
    obs = Observation(
        end_screen=None,
        countdown="05:00",
        zone="区域 1/3",
        zone_idx=1,
        targets=(("矿堆", (0, -3)),),
    )
    frame = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs):
        cmds = bot.step(frame)

    assert any(isinstance(c, Hold) and "KeyW" in c.keys for c in cmds)


def test_unrelated_prompt_does_not_stop_movement_toward_target():
    from unittest.mock import patch

    from autobonk.game import SUPER_BALL
    from autobonk.perception.dom import Observation
    from autobonk.runtime.controller import Hold

    bot = Bot(targets={"超级球": 10.0})
    # Target is super ball 20px north; unrelated rock prompt is active
    obs = Observation(
        end_screen=None,
        countdown="05:00",
        zone="区域 1/3",
        zone_idx=1,
        prompt=("E", "碎岩"),
        targets=((SUPER_BALL, (0, -20)),),
    )
    frame = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs):
        cmds = bot.step(frame)

    assert bot._target_selector.current_target == SUPER_BALL
    # Bot must NOT stop moving toward the ball
    assert any(isinstance(c, Hold) and "KeyW" in c.keys for c in cmds)


def test_offscreen_portal_prioritizes_active_compass_over_hidden_wlabel():
    """Frame 115842-759 has a stale, hidden wlabel (display:none) at (-52, -36) from boss death,

    and an active edge compass (264m) pointing to South-East (46, 89).
    Perception must resolve portal to (46, 89) and bot must steer toward the portal (KeyD + KeyS),
    not get stuck in the mountain wall (KeyA + KeyW).
    """
    from autobonk.game import PORTAL
    from autobonk.policy.zone import BossPhase
    from autobonk.runtime.controller import Hold

    f = replace(load_frame(FRAMES / "frame-20261101-115842-759"), timestamp=0.0)
    obs = perceive(f)

    # 1. Perception prioritizes the active compass over the hidden ghost label
    assert obs.portal == (46, 89)
    assert not obs.has_unopened_super_balls

    # 2. In beaten phase, bot navigates directly toward portal (South-East: KeyD + KeyS)
    bot = Bot()
    bot._zone_tracker.zone = obs.zone
    bot._zone_tracker.boss_phase = BossPhase.BEATEN

    commands = bot._move(obs, now=10.0)
    assert bot._target_selector.current_target == PORTAL
    assert any(isinstance(c, Hold) and {"KeyD", "KeyS"}.issubset(c.keys) for c in commands)


def test_is_portal_prompt_dynamic_and_matches_target():
    from autobonk.game import ALTAR, PORTAL, is_portal_prompt, prompt_matches_target

    # Standard prompts
    assert is_portal_prompt("传送门")
    assert is_portal_prompt("进入传送门")
    assert is_portal_prompt("离开圣地")

    # Dynamic biome sanctuary entrance prompts
    assert is_portal_prompt("进入森林圣地")
    assert is_portal_prompt("进入沙漠圣地")
    assert is_portal_prompt("进入海岸圣地")
    assert is_portal_prompt("进入火山圣地")
    assert is_portal_prompt("进入圣地")
    assert is_portal_prompt("进入天空湖")

    # Exclusions (boss triggers, normal items)
    assert not is_portal_prompt("触碰圣地")
    assert not is_portal_prompt("唤醒守护者")
    assert not is_portal_prompt("打开超级球")
    assert not is_portal_prompt("")

    # prompt_matches_target contract
    assert prompt_matches_target("进入森林圣地", PORTAL)
    assert prompt_matches_target("进入火山圣地", PORTAL)
    assert prompt_matches_target("进入天空湖", PORTAL)
    assert not prompt_matches_target("触碰圣地", PORTAL)
    assert prompt_matches_target("触碰圣地", ALTAR)


def test_zone3_sanctuary_portal_presses_e_at_close_distance():
    from unittest.mock import patch

    from autobonk.game import INTERACT_KEY, PORTAL
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase
    from autobonk.runtime.controller import Press

    bot = Bot()
    bot._zone_tracker.zone = "区域 3/3"
    bot._zone_tracker.boss_phase = BossPhase.BEATEN

    obs = Observation(
        end_screen=None,
        countdown="02:56",
        zone="区域 3/3",
        zone_idx=3,
        level=141,
        portal=(0, 1),
        prompt=("E", "进入森林圣地"),
        targets=(),
    )
    frame = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs):
        cmds = bot.step(frame)

    assert bot._target_selector.current_target == PORTAL
    assert any(isinstance(c, Press) and c.key == INTERACT_KEY for c in cmds)


def test_boss_beaten_never_targets_field_objects_or_ores():
    from unittest.mock import patch

    from autobonk.game import PORTAL
    from autobonk.perception.dom import Observation
    from autobonk.policy.zone import BossPhase

    bot = Bot(targets={"矿堆": 10.0, "引梦貘人": 8.0})
    bot._zone_tracker.zone = "区域 1/3"
    bot._zone_tracker.boss_phase = BossPhase.BEATEN

    # Minimap has ores and wild pokemon, portal is None initially
    obs = Observation(
        end_screen=None,
        countdown="02:14",
        zone="区域 1/3",
        zone_idx=1,
        level=73,
        portal=None,
        prompt=None,
        targets=(("矿堆", (23, -10)), ("引梦貘人", (100, 50))),
    )
    frame = Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url="")
    with patch("autobonk.policy.bot.perceive", return_value=obs):
        bot.step(frame)

    # Bot must NOT target 矿堆 or 引梦貘人!
    assert bot._target_selector.current_target != "矿堆"
    assert bot._target_selector.current_target != "引梦貘人"
    assert bot._target_selector.current_target in (PORTAL, None)
    assert "矿堆" not in bot._target_selector.active_weights
    assert "引梦貘人" not in bot._target_selector.active_weights


def test_hidden_portal_compass_is_a_dead_node():
    """Frame 215615 is zone 3/3 with 9:08 left: no portal is open yet. The display:none
    portal compass still carries its last bearing from the previous zone; reading it
    would mark a boss beaten that was never fought."""
    f = load_frame(FRAMES / "frame-20261101-215615-503")
    assert perceive(f).portal is None
    # Same frozen compass before the guardian is even woken (prompt 唤醒守护者).
    assert perceive(load_frame(FRAMES / "frame-20261028-022353-323")).portal is None





def test_generic_prompt_matches_a_regular_target_only_within_interact_range():
    from unittest.mock import patch

    from autobonk.game import is_generic_prompt, prompt_matches_target
    from autobonk.perception.dom import Observation

    # Icon names rarely appear in prompts, so no name-based match for an unrelated prompt.
    assert not prompt_matches_target("老虎机 · 每次 40 ₽", "矿堆")
    assert prompt_matches_target("碎岩", "矿堆")
    assert is_generic_prompt("老虎机 · 每次 40 ₽")
    assert not is_generic_prompt("进入传送门")
    assert not is_generic_prompt("唤醒守护者")

    def keeps_walking(distance: int) -> bool:
        bot = Bot(targets={"矿堆": 10.0})
        obs = Observation(
            end_screen=None,
            countdown="05:00",
            zone="区域 1/3",
            zone_idx=1,
            prompt=("E", "老虎机 · 每次 40 ₽"),
            targets=(("矿堆", (0, -distance)),),
        )
        with patch("autobonk.policy.bot.perceive", return_value=obs):
            cmds = bot.step(Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url=""))
        assert bot._target_selector.current_target == "矿堆"
        return any(isinstance(c, Hold) and "KeyW" in c.keys for c in cmds)

    # 40 px away an unrelated slot machine prompt must not count as arrival: keep walking.
    assert keeps_walking(40)


def test_leaving_a_popup_never_ignores_the_portal():
    from unittest.mock import patch

    from autobonk.game import PORTAL
    from autobonk.perception.dom import Button, Observation, Popup

    bot = Bot()
    bot._target_selector.current_target = PORTAL
    obs = Observation(
        end_screen=None,
        countdown=None,
        popup=Popup("喵喵的商店", (), (Button("离开", "Esc"),)),
        prompt=("E", "和喵喵交谈（商店）"),
    )
    with patch("autobonk.policy.bot.perceive", return_value=obs):
        bot.step(Frame(screenshot=b"", dom_snapshot="", timestamp=10.0, url=""))
    assert not bot._target_selector.is_skipped(PORTAL, 11.0)
    assert bot._target_selector.is_skipped("和喵喵交谈（商店）", 11.0)


def test_regular_target_times_out_even_with_a_portal_prompt_on_screen():
    from autobonk.game import INTERACT_WAIT_S, PORTAL
    from autobonk.policy.navigation import ApproachHandler

    approach = ApproachHandler()
    approach.interact("牢笼", 1.0, prompt_text="进入传送门")
    _, timed_out = approach.interact("牢笼", INTERACT_WAIT_S + 1.1, prompt_text="进入传送门")
    assert timed_out

    # The portal itself never gives up.
    approach.reset()
    approach.interact(PORTAL, 1.0, prompt_text="进入传送门")
    _, timed_out = approach.interact(PORTAL, INTERACT_WAIT_S + 1.1, prompt_text="进入传送门")
    assert not timed_out

    # A target E may not be pressed on yet still starts the timer.
    approach.reset()
    approach.interact("牢笼", 1.0, spam_e=False)
    _, timed_out = approach.interact("牢笼", INTERACT_WAIT_S + 1.1, spam_e=False)
    assert timed_out


def test_sanctuary_flag_latches_when_it_renders_after_the_zone_name():
    from autobonk.policy.zone import ZoneTracker

    tracker = ZoneTracker()
    assert tracker.update("森林圣地", 59, is_sanctuary=False)
    assert not tracker.is_sanctuary
    assert not tracker.update("森林圣地", 58, is_sanctuary=True)
    assert tracker.is_sanctuary
    tracker.update("森林圣地", 57, is_sanctuary=False)
    assert tracker.is_sanctuary


def test_card_opacity_one_is_not_faded():
    from autobonk.perception.dom import _parse

    parsed = _parse(
        '<div style="opacity: 1; transition: opacity .2s">'
        '<button class="card" style="--rc: 1"><h3>甲</h3></button>'
        '<button class="card mini" style="opacity: 0.45;"><h3>乙</h3></button></div>'
    )
    faded = {text: parsed.card_faded[cid] for (_, text), cid in zip(parsed.nodes, parsed.card_ids, strict=False) if cid is not None}
    assert faded == {"甲": False, "乙": True}


def test_hot_reload_can_turn_thresholds_and_the_boss_rule_off():
    bot = Bot(targets={"矿堆": 10.0}, boss=BossRule(), banish_threshold=-5.0)
    bot.reload_config(sub_target_weight_factor=6.0)  # partial reload keeps everything else
    assert bot._popups.banish_threshold == -5.0
    assert bot._target_selector.boss == BossRule()
    assert "矿堆" in bot._target_selector._weights

    bot.reload_config(banish_threshold=None, boss=None)
    assert bot._popups.banish_threshold is None
    assert bot._target_selector.boss is None
    assert "骷髅" not in bot._target_selector.icons
    assert "矿堆" in bot._target_selector._weights


def test_bare_portal_or_boss_prompt_target_never_times_out():
    """With no icon, the bot interacts with the prompt itself, so the prompt is the name."""
    from autobonk.game import INTERACT_WAIT_S
    from autobonk.policy.navigation import ApproachHandler

    for name in ("进入传送门", "进入森林圣地", "唤醒守护者"):
        approach = ApproachHandler()
        approach.interact(name, 1.0, prompt_text=name)
        _, timed_out = approach.interact(name, INTERACT_WAIT_S + 1.1, prompt_text=name)
        assert not timed_out, name


def test_approach_short_of_target_records_no_interaction():
    """Recording one stands the unsticker down, so a target behind a wall would pin the bot."""
    from autobonk.policy.navigation import ApproachHandler

    approach = ApproachHandler()
    approach.interact("牢笼", 1.0, spam_e=False, at_target=False)
    assert approach.interacted is None


def test_portal_is_read_from_the_minimap_icon_when_shown():
    """The minimap icon gives the portal in the same frame and scale as the other targets, and
    it only exists once the boss is down: it never shows on a minimap with a skull."""
    obs = perceive(load_frame(FRAMES / "frame-20261101-175308-923"))
    assert obs.portal == (-9, 51)
    assert all(name != "传送门" for name, _ in obs.targets)


def test_match_many_rejects_mixed_template_sizes():
    import numpy as np

    from autobonk.perception.matching import match_many

    image = np.zeros((64, 64, 3))
    with pytest.raises(ValueError):
        match_many(image, [np.ones((28, 28, 3)), np.ones((32, 32, 3))])


def test_in_game_pause_overlay_resumes_with_escape():
    pause_html = (
        '<div id="hud"><div class="timer">9:34</div></div>'
        '<div class="modal"><div class="panel sm pz">'
        '<div class="sm-hero pz-hero"><small><i class="pz-pill">暂停</i></small><h2>皮卡丘</h2></div>'
        "</div></div>"
    )
    frame = Frame(b"", pause_html, 10.0, "https://pokebonk.com/")
    obs = perceive(frame)
    assert obs.game_paused is True

    bot = Bot()
    assert bot.step(frame) == [ReleaseAll(), Press("Escape")]
    assert bot.step(Frame(b"", pause_html, 10.2, "https://pokebonk.com/")) == []
    assert bot.step(Frame(b"", pause_html, 11.2, "https://pokebonk.com/")) == [ReleaseAll(), Press("Escape")]


def test_hidden_or_fading_pause_overlay_is_not_paused():
    """Escape on a dead pause node would open the menu: hidden/faded panels must be ignored."""
    for modal_style in ('style="display: none;"', 'style="opacity: 0;"'):
        html = (
            f'<div class="modal sm-modal" {modal_style}><div class="panel sm pz">'
            '<div class="sm-hero pz-hero"><small><i class="pz-pill">暂停</i></small></div></div></div>'
        )
        frame = Frame(b"", html, 10.0, "https://pokebonk.com/")
        assert perceive(frame).game_paused is False
        assert Press("Escape") not in Bot().step(frame)


def test_pause_fixture_is_detected():
    frame = load_frame(Path("fixtures/frames/frame-20261030-155532-914"))
    assert perceive(frame).game_paused is True
