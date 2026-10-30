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
    bot = Bot()
    bot.step(run_frame("155220-116", 100.0))

    assert bot.step(run_frame("155222-698", 100.1)) == [Hold(frozenset())]  # charging 8%


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


TEAM_VIEW = run_frame("172455-857", 100.0)  # 等级 11！ with 你的队伍 laid over it (Tab let go mid-popup)


def test_team_view_over_a_popup_is_closed_with_tab_before_choosing():
    bot = Bot()

    assert bot.step(TEAM_VIEW) == [ReleaseAll(), Press("Tab")]
    assert bot.step(replace(TEAM_VIEW, timestamp=100.5)) == []
    assert bot.step(replace(TEAM_VIEW, timestamp=101.0)) == [ReleaseAll(), Press("Tab")]


def test_after_the_team_view_closes_the_card_is_chosen():
    bot = Bot()
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
    assert holds(bot.step(standing_on("喵喵", 105.0))) == []  # 5.0 s on: E did nothing, skip it
    assert holds(bot.step(standing_on("喵喵", 105.1))) == [Hold(frozenset({"Tab"}))]
    assert Press("KeyE") in bot.step(standing_on("喵喵", 166.0))


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
    bot.step(standing_on("骷髅", 100.0))
    beaten = replace(run_frame("155654-906", 101.0), minimap=standing_on("骷髅", 0).minimap)

    assert Press("KeyE") not in bot.step(beaten)
    assert "骷髅" not in bot._now_weights and "符文祭坛" in bot._now_weights


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

    # Frame with active portal
    obs_portal = perceive(run_frame("214628-985", 0.0))
    assert obs_portal.portal == (-14, -82)


def test_after_boss_opens_nearby_super_balls_before_entering_portal():
    f3 = run_frame("214628-985", 100.0)
    bot = Bot(targets={"符文祭坛": 7.0, "超级球": 10.0, "精灵球": 5.0})
    bot.step(f3)  # initialize zone to 区域 1/3
    bot._boss_beaten = True

    # 1. When super balls are nearby, bot targets super ball first
    obs_with_balls = perceive(f3, bot._icons)
    commands = bot._move(obs_with_balls, 100.5)
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

    # 4. If 5 s pass without popup/charging (e.g. blocked or no money), target is ignored and bot explores.
    bot._move(obs_blocked, 105.1)
    cmds4 = bot._move(obs_blocked, 105.2)
    assert Hold(frozenset({"Tab"})) in cmds4


def test_overtime_countdown_is_recognised_with_zero_seconds_left():
    overtime = run_frame("232940-022", 100.0)
    obs = perceive(overtime)
    assert obs.countdown == "+1:09"
    assert obs.seconds_left == 0
    assert obs.recognised


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


