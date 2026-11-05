import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from autobonk.config import load_config
from autobonk.editor import (
    build_full_card_list,
    load_catalog,
    make_handler,
    read_config_weights,
    save_config_weights,
    save_target_weights,
)


def serve(toml_path: Path) -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), make_handler(toml_path))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_load_catalog():
    cards, pokemon_151 = load_catalog()
    assert len(cards) >= 180
    assert len(pokemon_151) == 151
    names = {c["name"] for c in cards}
    assert {"大师球", "攻击增强剂", "精神利刃", "+伤害"} <= names

    moves = {c["name"]: c for c in cards if c.get("category") == "招式"}
    assert moves["精神利刃"]["damage_type"] == "物理"
    assert moves["精神击破"]["damage_type"] == "特殊"


def test_save_and_read_config_weights_with_profiles(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    toml_path.write_text(
        '[browser]\nurl = "https://pokebonk.com/"\n\n'
        '[cards]\nrarity_order = ["传说", "普通"]\n\n[cards.weights]\n"月之石" = 10\n',
        encoding="utf-8",
    )

    save_config_weights(
        toml_path,
        baseline_weights={"月之石": 10, "活力块": 8, "精神利刃": 5, "屏障": -5},
        rarity_order=["招式", "传说", "稀有", "普通"],
        active_pokemon="超梦",
        pokemon_profiles={"超梦": {"精神击破": 9, "精神利刃": -5}},
    )

    cfg = load_config(toml_path)
    assert cfg.url == "https://pokebonk.com/"
    assert cfg.active_pokemon == "超梦"
    assert cfg.cards.rarity_order == ("招式", "传说", "稀有", "普通")
    assert cfg.cards.weights["月之石"] == 10
    assert cfg.cards.weights["精神击破"] == 9
    assert cfg.cards.weights["精神利刃"] == -5  # the profile overrides the shared weight

    baseline, _, active, profiles = read_config_weights(toml_path)
    assert baseline["精神利刃"] == 5
    assert active == "超梦"
    assert profiles == {"超梦": {"精神击破": 9, "精神利刃": -5}}

    content = toml_path.read_text(encoding="utf-8")
    assert "# Priority 10" in content
    assert "# Avoid (-5)" in content


def test_unset_active_pokemon_stays_unset(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    toml_path.write_text('[cards.weights]\n"月之石" = 10\n', encoding="utf-8")

    assert build_full_card_list(toml_path)["active_pokemon"] is None


def test_a_profile_zero_overrides_the_shared_weight(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    save_config_weights(
        toml_path,
        baseline_weights={"神奇糖果": 7},
        rarity_order=["传说"],
        active_pokemon="皮卡丘",
        pokemon_profiles={"皮卡丘": {"神奇糖果": 0}},
    )

    assert load_config(toml_path).cards.weights["神奇糖果"] == 0


def test_build_full_card_list(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    toml_path.write_text(
        '[cards]\nrarity_order = ["传说", "普通"]\n\n'
        '[cards.weights]\n"+伤害" = 8\n"自定义卡牌" = 6\n\n'
        '[cards.pokemon."超梦"]\n"化石卡" = 3\n',
        encoding="utf-8",
    )

    data = build_full_card_list(toml_path)

    assert len(data["cards"]) >= 180
    assert data["baseline_weights"] == {"+伤害": 8, "自定义卡牌": 6}
    assert data["pokemon_profiles"] == {"超梦": {"化石卡": 3}}
    names = {c["name"] for c in data["cards"]}
    assert {"自定义卡牌", "化石卡"} <= names


def test_roll_specific_blessings_are_dropped_on_load(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    toml_path.write_text(
        '[cards.weights]\n"+38% 伤害" = 8\n"+14% 伤害" = 5\n"+63 最大 HP" = 4\n', encoding="utf-8"
    )

    data = build_full_card_list(toml_path)

    assert data["baseline_weights"] == {}
    names = {c["name"] for c in data["cards"]}
    assert "+伤害" in names and "+38% 伤害" not in names


def test_save_keeps_tables_after_cards_and_quotes_names(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    toml_path.write_text(
        '[cards]\nrarity_order = ["传说"]\n\n[cards.weights]\n"月之石" = 10\n\n'
        '[later]\n# keep me\nvalue = 1\n',
        encoding="utf-8",
    )

    save_config_weights(toml_path, baseline_weights={'他说"好"': 3}, rarity_order=["传说"])

    content = toml_path.read_text(encoding="utf-8")
    assert "[later]\n# keep me\nvalue = 1" in content
    assert load_config(toml_path).cards.weights == {'他说"好"': 3}


def test_a_profile_name_cannot_break_out_of_its_comment(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    name = '坏\n[browser]\nurl = "x"'

    save_config_weights(
        toml_path, baseline_weights={}, rarity_order=["传说"],
        active_pokemon=name, pokemon_profiles={name: {"月之石": 1}},
    )

    cfg = load_config(toml_path)
    assert cfg.url == "https://pokebonk.com/"
    assert cfg.cards.weights == {"月之石": 1}


def test_handler_server_end_to_end(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    toml_path.write_text(
        '[cards]\nrarity_order = ["传说", "普通"]\n\n[cards.weights]\n"月之石" = 10\n', encoding="utf-8"
    )
    server, port = serve(toml_path)

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            assert resp.status == 200
            assert "PokéBonk" in resp.read().decode("utf-8")

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/cards") as resp:
            assert resp.status == 200
            assert "PokéBonk 卡牌配置" in resp.read().decode("utf-8")

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/data") as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["baseline_weights"]["月之石"] == 10
            assert data["config_path"] == str(toml_path)
            assert len(data["cards"]) >= 180

        payload = json.dumps({
            "baseline_weights": {"月之石": 10, "神奇糖果": 7},
            "rarity_order": ["招式", "传说", "史诗", "普通"],
            "active_pokemon": "超梦",
            "pokemon_profiles": {"超梦": {"精神击破": 9}},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/save", data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            assert json.loads(resp.read().decode("utf-8"))["status"] == "ok"

        cfg = load_config(toml_path)
        assert cfg.active_pokemon == "超梦"
        assert cfg.cards.weights == {"月之石": 10, "神奇糖果": 7, "精神击破": 9}
    finally:
        server.shutdown()
        server.server_close()


def test_save_refuses_cross_origin_requests(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    toml_path.write_text('[cards.weights]\n"月之石" = 10\n', encoding="utf-8")
    server, port = serve(toml_path)
    body = json.dumps({"baseline_weights": {"x": 1}, "rarity_order": []}).encode("utf-8")

    def post(headers: dict[str, str]) -> int:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/save", data=body, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status
        except urllib.error.HTTPError as err:
            return err.code

    try:
        assert post({"Content-Type": "text/plain"}) == 403
        assert post({"Content-Type": "application/json", "Origin": "https://evil.example"}) == 403
        assert post({"Content-Type": "application/json", "Host": f"evil.example:{port}"}) == 403
        assert '"月之石" = 10' in toml_path.read_text(encoding="utf-8")
        assert post({"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"}) == 200
    finally:
        server.shutdown()
        server.server_close()


def test_save_clamps_weights_to_ten(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    toml_path.write_text('[cards.weights]\n"月之石" = 10\n', encoding="utf-8")
    server, port = serve(toml_path)
    body = json.dumps({"baseline_weights": {"神卡": 15, "正常卡": 8}, "rarity_order": []}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/save",
        data=body,
        headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
        content = toml_path.read_text(encoding="utf-8")
        # Should be clamped to 10
        assert '"神卡" = 10' in content
        assert '"正常卡" = 8' in content
    finally:
        server.shutdown()
        server.server_close()


def test_target_weights_are_saved_apart_from_card_weights(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    toml_path.write_text(
        '[bot]\nstuck_s = 2.5\n\n[targets.weights]\n"符文祭坛" = 10\n\n[cards.weights]\n"月之石" = 10\n',
        encoding="utf-8",
    )

    save_target_weights(toml_path, {"符文祭坛": 10, "精灵球": 5})
    save_config_weights(toml_path, {"月之石": 9}, ["普通"])

    cfg = load_config(toml_path)
    assert cfg.targets == {"符文祭坛": 10, "精灵球": 5}
    assert cfg.cards.weights == {"月之石": 9}
    assert cfg.stuck_s == 2.5


def test_targets_page_lists_every_icon_with_its_image_and_saves(tmp_path: Path):
    toml_path = tmp_path / "autobonk.toml"
    toml_path.write_text('[cards.weights]\n"月之石" = 10\n', encoding="utf-8")
    server, port = serve(toml_path)
    base = f"http://127.0.0.1:{port}"

    try:
        with urllib.request.urlopen(f"{base}/targets") as resp:
            assert "PokéBonk 地图目标" in resp.read().decode("utf-8")
        with urllib.request.urlopen(f"{base}/api/targets") as resp:
            data = json.loads(resp.read())
        icons = [icon for group in data["groups"] for icon in group["icons"]]
        assert {"name": "符文祭坛", "start": 10, "end": 10} in icons
        assert {"name": "喵喵", "start": 0, "end": 0} in icons
        assert data["boss"] == {"name": "骷髅", "levels": [35, 60, 80], "minutes_left": [4, 8, 8]}
        for icon in icons + [data["boss"]]:
            with urllib.request.urlopen(f"{base}/icons/{urllib.parse.quote(icon['name'])}") as resp:
                assert resp.headers["Content-Type"] == "image/png"

        req = urllib.request.Request(
            f"{base}/api/targets",
            data=json.dumps({
                "weights": {"精灵球": [0, 6], "符文祭坛": 10},
                "boss": {"levels": [30, 60, 80], "minutes_left": [4, 8, 8]},
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            assert json.loads(resp.read())["status"] == "ok"
        cfg = load_config(toml_path)
        assert cfg.targets == {"精灵球": (0, 6), "符文祭坛": 10}
        assert cfg.boss.levels == (30, 60, 80)
        assert cfg.cards.weights == {"月之石": 10}
    finally:
        server.shutdown()
        server.server_close()
