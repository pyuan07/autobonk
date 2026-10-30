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


def test_same_key_for_both_hotkeys_is_rejected(tmp_path):
    path = tmp_path / "autobonk.toml"
    path.write_text('[hotkeys]\npause = "F9"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="f9"):
        load_config(path)
