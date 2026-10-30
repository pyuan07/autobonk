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
