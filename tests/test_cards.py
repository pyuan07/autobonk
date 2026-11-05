from autobonk.cards import Card, CardPrefs, blessing_key


def blessings(*names_and_rarities: tuple[str, str]) -> list[Card]:
    return [Card(str(i), name, rarity) for i, (name, rarity) in enumerate(names_and_rarities, 1)]


def test_blessing_key_drops_the_rolled_number():
    assert blessing_key("+38% 伤害") == "+伤害"
    assert blessing_key("+63 最大 HP") == "+最大HP"
    assert blessing_key("+1.2 再生") == "+再生"
    assert blessing_key("月之石") is None
    assert blessing_key("伤害") is None


def test_stat_weight_covers_every_roll_of_that_stat():
    prefs = CardPrefs(weights={"+范围": 8, "+伤害": 9})
    offered = blessings(("+24 最大 HP", "传说"), ("+17% 范围", "稀有"), ("+14% 伤害", "少见"))

    assert prefs.best(offered).name == "+14% 伤害"


def test_stat_key_spacing_does_not_matter():
    assert CardPrefs(weights={"+最大 HP": 5}).weight("+63 最大 HP") == 5
    assert CardPrefs(weights={"+最大HP": 5}).weight("+63 最大 HP") == 5


def test_a_roll_specific_key_is_ignored():
    assert CardPrefs(weights={"+38% 伤害": 8}).weight("+38% 伤害") == 0
    assert CardPrefs(weights={"+伤害": 3, "+38% 伤害": 8}).weight("+38% 伤害") == 3


def test_equal_stat_weights_fall_back_to_rarity():
    prefs = CardPrefs(weights={"+伤害": 8, "+速度": 8}, rarity_order=("传说", "史诗", "稀有"))
    offered = blessings(("+21% 伤害", "稀有"), ("+22% 速度", "史诗"))

    assert prefs.best(offered).name == "+22% 速度"


def test_in_plan_flag_from_details():
    c = Card("1", "鸣雷风暴", "招式", ("新", "在你的计划中"))
    assert c.in_plan is True


def test_in_plan_beats_lower_non_plan_cards():
    prefs = CardPrefs(weights={"+伤害": 8, "防御增强剂": 5})
    plan_card = Card("1", "鸣雷风暴", "招式", in_plan=True)
    damage = Card("2", "+38% 伤害", "稀有", in_plan=False)
    defense = Card("3", "防御增强剂", "普通", in_plan=False)

    assert prefs.best([damage, plan_card, defense]) == plan_card


def test_high_weight_non_plan_competes_with_plan_card():
    # 10-weight flute beats 9-weight plan card
    prefs = CardPrefs(weights={"宝可梦之笛": 10, "鸣雷风暴": 9})
    flute = Card("1", "宝可梦之笛", "普通", in_plan=False)
    storm = Card("2", "鸣雷风暴", "招式", in_plan=True)

    assert prefs.best([storm, flute]) == flute

    # 9-weight item beats 0-weight (unconfigured) plan card
    prefs2 = CardPrefs(weights={"全满药": 9})
    potion = Card("1", "全满药", "普通", in_plan=False)
    unweighted_storm = Card("2", "鸣雷风暴", "招式", in_plan=True)

    assert prefs2.best([unweighted_storm, potion]) == potion


def test_multiple_plan_cards_tie_break_by_weight_then_rarity():
    prefs = CardPrefs(weights={"招式A": 8, "招式B": 9}, rarity_order=("传说", "史诗", "招式", "普通"))
    a = Card("1", "招式A", "招式", in_plan=True)
    b = Card("2", "招式B", "招式", in_plan=True)
    assert prefs.best([a, b]) == b

    # Equal weight -> rarity order
    prefs_equal = CardPrefs(weights={"招式A": 8, "招式B": 8}, rarity_order=("传说", "史诗", "招式", "普通"))
    a_rare = Card("1", "招式A", "史诗", in_plan=True)
    b_common = Card("2", "招式B", "普通", in_plan=True)
    assert prefs_equal.best([b_common, a_rare]) == a_rare

