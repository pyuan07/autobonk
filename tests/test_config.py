from pathlib import Path

import pytest

from autobonk.config import load_config


def test_missing_file_gives_defaults(tmp_path):
    config = load_config(tmp_path / "nope.toml")

    assert config.url == "https://pokebonk.com/"
    assert (config.viewport_width, config.viewport_height) == (1600, 900)
    assert config.pause_hotkey == "f8"
    assert config.frame_hotkey == "f9"
    assert config.choices_file == tmp_path / "logs" / "choices.jsonl"


def test_file_overrides_defaults_and_paths_resolve_against_file(tmp_path):
    path = tmp_path / "autobonk.toml"
    path.write_text(
        '[browser]\nprofile_dir = "my-profile"\n\n'
        '[frames]\ndir = "out/frames"\n\n'
        '[hotkeys]\npause = "f7"\n',
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.profile_dir == tmp_path / "my-profile"
    assert config.frames_dir == tmp_path / "out" / "frames"
    assert config.pause_hotkey == "f7"
    assert config.frame_hotkey == "f9"


def test_target_weights_come_from_their_own_table(tmp_path):
    path = tmp_path / "autobonk.toml"
    path.write_text('[targets.weights]\n"精灵球" = 5\n\n[cards.weights]\n"精灵球" = 1\n', encoding="utf-8")

    assert load_config(path).targets == {"精灵球": 5}
    assert load_config(tmp_path / "nope.toml").targets == {"符文祭坛": 10}


def test_repo_config_stub_loads():
    config = load_config(Path(__file__).parent.parent / "autobonk.toml")

    assert config.url == "https://pokebonk.com/"
    assert config.distance_factor == 0.2


def test_distance_factor_configurable_or_defaults(tmp_path):
    path = tmp_path / "autobonk.toml"
    path.write_text('[bot]\ndistance_factor = 0.35\n', encoding="utf-8")

    assert load_config(path).distance_factor == 0.35
    assert load_config(tmp_path / "nope.toml").distance_factor == 0.2


def test_sub_target_allowances_configurable_or_defaults(tmp_path):
    path = tmp_path / "autobonk.toml"
    path.write_text('[bot]\nsub_target_base_allowance = 20.0\nsub_target_weight_factor = 5.0\n', encoding="utf-8")

    cfg = load_config(path)
    assert cfg.sub_target_base_allowance == 20.0
    assert cfg.sub_target_weight_factor == 5.0

    default_cfg = load_config(tmp_path / "nope.toml")
    assert default_cfg.sub_target_base_allowance == 12.0
    assert default_cfg.sub_target_weight_factor == 3.0


def test_same_key_for_both_hotkeys_is_rejected(tmp_path):
    path = tmp_path / "autobonk.toml"
    path.write_text('[hotkeys]\npause = "F9"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="f9"):
        load_config(path)


def test_plan_fallback_reroll_threshold_and_weight_cap(tmp_path):
    path = tmp_path / "autobonk.toml"
    path.write_text(
        '[cards]\nplan_fallback_reroll_threshold = 8.5\n\n'
        '[cards.weights]\n"神卡" = 15\n"普通卡" = 6\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.plan_fallback_reroll_threshold == 8.5
    # Clamped at 10.0
    assert config.cards.weight("神卡") == 10.0
    assert config.cards.weight("普通卡") == 6.0
