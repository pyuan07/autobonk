import json
from pathlib import Path

from autobonk.choices import ChoiceLog, Input
from autobonk.frames import load_frame
from autobonk.perception import perceive

FRAMES = Path(__file__).parent.parent / "fixtures" / "frames"


def popup_of(name: str):
    return perceive(load_frame(FRAMES / f"frame-20261028-{name}")).popup


LEVEL_UP = popup_of("021833-196")  # 咬住, 诅咒薰香, 好伤药, 命中强化
ITEM_PICKUP = popup_of("021610-030")  # 锐利之爪: 拾取 E / 出售 V
DITTO = popup_of("022106-745")  # no [n] keys


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_key_pressed_on_a_popup_records_the_offer_and_the_pick(tmp_path):
    log = ChoiceLog(tmp_path / "choices.jsonl")

    log.observe(LEVEL_UP, [], 100.0)
    log.observe(None, [Input("key", "3")], 100.1)

    [entry] = lines(tmp_path / "choices.jsonl")
    assert entry["title"] == "等级 2！"
    assert [card["name"] for card in entry["offered"]] == ["咬住", "诅咒薰香", "好伤药", "命中强化"]
    assert "+0.7 hp 再生" in entry["offered"][2]["details"]
    assert (entry["input"], entry["picked"]) == ("3", "好伤药")


def test_pickup_popup_records_pick_up_or_sell(tmp_path):
    log = ChoiceLog(tmp_path / "choices.jsonl")

    log.observe(ITEM_PICKUP, [], 100.0)
    log.observe(None, [Input("key", "v")], 100.1)

    assert lines(tmp_path / "choices.jsonl")[0]["picked"] == "出售 (+18 ₽)"


def test_clicked_card_is_matched_by_name(tmp_path):
    log = ChoiceLog(tmp_path / "choices.jsonl")

    log.observe(DITTO, [], 100.0)
    log.observe(None, [Input("click", "达人带\n效果绝佳的攻击伤害 +30%。")], 100.1)

    [entry] = lines(tmp_path / "choices.jsonl")
    assert entry["picked"] == "达人带"
    assert entry["offered"][-1]["details"] == ["效果绝佳的攻击伤害 +30%。"]


def test_inputs_without_a_popup_or_unrelated_keys_are_not_recorded(tmp_path):
    log = ChoiceLog(tmp_path / "choices.jsonl")

    log.observe(None, [Input("key", "w")], 100.0)
    log.observe(LEVEL_UP, [Input("key", "3")], 100.1)  # pressed before this popup was seen
    log.observe(LEVEL_UP, [Input("key", "w"), Input("key", "Tab")], 100.2)

    assert lines(tmp_path / "choices.jsonl") == []
