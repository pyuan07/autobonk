"""Local web GUI for viewing and editing PokéBonk card weights and map target weights in autobonk.toml."""

import argparse
import json
import os
import re
import socket
import tomllib
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from autobonk.cards import blessing_key
from autobonk.bot import BOSS, BossRule
from autobonk.icons import ICON_DIR, ITEM_ICONS, POKEMON_ICONS
from autobonk.minimap import ALTAR_TEMPLATE

ROOT_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = Path(__file__).resolve().parent / "catalog_data.json"
UI_HTML_PATH = Path(__file__).resolve().parent / "editor_ui.html"
TARGETS_HTML_PATH = Path(__file__).resolve().parent / "targets_ui.html"
ALTAR_NAME = "符文祭坛"
DEFAULT_TARGET_WEIGHTS = {ALTAR_NAME: 10.0}
# Every map icon the bot can look for, grouped as the targets page shows them: name -> image.
TARGET_GROUPS: list[tuple[str, dict[str, Path]]] = [
    ("祭坛", {ALTAR_NAME: ALTAR_TEMPLATE}),
    ("物品与设施", {name: ICON_DIR / file for name, file in ITEM_ICONS.items() if name != BOSS}),
    ("宝可梦（商店、教学、头目）", {name: ICON_DIR / file for name, file in POKEMON_ICONS.items()}),
]
TARGET_IMAGES = {name: path for _, icons in TARGET_GROUPS for name, path in icons.items()}
TARGET_IMAGES[BOSS] = ICON_DIR / ITEM_ICONS[BOSS]
DEFAULT_RARITY_ORDER = ["招式", "传说", "史诗", "稀有", "少见", "普通"]


def load_catalog() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Loads stat blessings, vitamins, items, moves, and the 151 pokemon list."""
    if not CATALOG_PATH.exists():
        return [], []
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    cards: list[dict[str, Any]] = []
    cards.extend(data.get("blessings", []))
    cards.extend(data.get("vitamins", []))
    cards.extend(data.get("items", []))
    cards.extend(data.get("moves", []))
    pokemon_151 = data.get("pokemon_151", [])
    return cards, pokemon_151


def read_config_weights(
    toml_path: Path,
) -> tuple[dict[str, float], list[str], str | None, dict[str, dict[str, float]]]:
    """Reads baseline weights, rarity_order, active_pokemon, and pokemon_profiles from toml."""
    if not toml_path.exists():
        return {}, list(DEFAULT_RARITY_ORDER), None, {}

    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    cards_section = data.get("cards", {})

    baseline_weights = dict(cards_section.get("weights", {}))
    rarity_order = list(cards_section.get("rarity_order", DEFAULT_RARITY_ORDER))
    active_pokemon = cards_section.get("active_pokemon")

    raw_pokemon = cards_section.get("pokemon", {})
    pokemon_profiles: dict[str, dict[str, float]] = {}
    if isinstance(raw_pokemon, dict):
        for poke_name, w_dict in raw_pokemon.items():
            if isinstance(w_dict, dict):
                pokemon_profiles[poke_name] = {k: float(v) for k, v in w_dict.items()}

    return baseline_weights, rarity_order, active_pokemon, pokemon_profiles


def read_target_weights(toml_path: Path) -> tuple[dict[str, Any], BossRule]:
    """[targets.weights] (a number, or [start, end]) and [targets.boss]."""
    data = tomllib.loads(toml_path.read_text(encoding="utf-8")) if toml_path.exists() else {}
    targets = data.get("targets", {})
    boss = targets.get("boss", {})
    default = BossRule()
    rule = BossRule(tuple(boss.get("levels", default.levels)), tuple(boss.get("minutes_left", default.minutes_left)))
    return dict(targets.get("weights", DEFAULT_TARGET_WEIGHTS)), rule


def save_target_weights(toml_path: Path, weights: dict[str, Any], boss: BossRule | None = None) -> None:
    """Rewrites [targets.weights] and [targets.boss] (apart from the card weights); every other table is kept."""
    content = toml_path.read_text(encoding="utf-8") if toml_path.exists() else ""
    boss = boss or read_target_weights(toml_path)[1]
    other = _strip_tables(content, "targets")
    lines = [other.rstrip() + "\n\n" if other.strip() else ""]
    lines.append("[targets.weights]\n")
    lines.append("# Map icons to walk to (edit in the weight editor that run.bat opens). The highest weight goes\n")
    lines.append("# first, then the nearest; 0 or unlisted = never. [start, end]: the weight grows from start\n")
    lines.append("# to end as the zone's time runs out. At an altar the bot stands in the ring; at anything else\n")
    lines.append("# it presses E. Each icon listed costs ~15 ms per step to look for.\n")
    for name, weight in sorted(weights.items(), key=lambda item: -max(_ends(item[1]))):
        start, end = _ends(weight)
        if max(start, end) > 0:
            lines.append(f"{_quote(name)} = {_number(start) if start == end else f'[{_number(start)}, {_number(end)}]'}\n")
    lines.append("\n[targets.boss]\n")
    lines.append("# The area boss (骷髅): summoned with E in zone N once the level reaches levels[N-1], or once\n")
    lines.append("# only minutes_left[N-1] are left; then it comes first. While it chases, altars are left.\n")
    lines.append(f"levels = [{', '.join(_number(v) for v in boss.levels)}]\n")
    lines.append(f"minutes_left = [{', '.join(_number(v) for v in boss.minutes_left)}]\n")
    _write_toml(toml_path, "".join(lines))


def _ends(weight: Any) -> tuple[float, float]:
    return (weight[0], weight[1]) if isinstance(weight, (list, tuple)) else (weight, weight)


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _target_weights(weights: Any) -> dict[str, Any]:
    if not isinstance(weights, dict):
        raise ValueError("weights must be an object of name -> number or [start, end]")
    out: dict[str, Any] = {}
    for name, value in weights.items():
        ends = value if isinstance(value, list) else [value]
        if len(ends) not in (1, 2) or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in ends):
            raise ValueError(f"weight for {name!r} is not a number or [start, end]: {value!r}")
        out[str(name)] = value
    return out


def _boss_from(data: Any) -> BossRule:
    if not isinstance(data, dict):
        raise ValueError("boss must be an object")
    rule = BossRule(tuple(data.get("levels", ())), tuple(data.get("minutes_left", ())))
    if len(rule.levels) != 3 or len(rule.minutes_left) != 3:
        raise ValueError("boss needs 3 levels and 3 minutes_left, one per zone")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (*rule.levels, *rule.minutes_left)):
        raise ValueError("boss levels and minutes_left must be numbers")
    return rule


def _write_toml(toml_path: Path, text: str) -> None:
    new_toml = text.rstrip() + "\n"
    tomllib.loads(new_toml)  # never write a file the bot can't read
    tmp_path = toml_path.with_name(toml_path.name + ".tmp")
    tmp_path.write_text(new_toml, encoding="utf-8")
    os.replace(tmp_path, toml_path)


def target_list(toml_path: Path) -> dict[str, Any]:
    weights, boss = read_target_weights(toml_path)

    def icon(name: str) -> dict[str, Any]:
        start, end = _ends(weights.get(name, 0))
        return {"name": name, "start": start, "end": end}

    return {
        "groups": [{"title": title, "icons": [icon(name) for name in icons]} for title, icons in TARGET_GROUPS],
        "boss": {"name": BOSS, "levels": list(boss.levels), "minutes_left": list(boss.minutes_left)},
    }


def save_config_weights(
    toml_path: Path,
    baseline_weights: dict[str, float],
    rarity_order: list[str],
    active_pokemon: str | None = None,
    pokemon_profiles: dict[str, dict[str, float]] | None = None,
) -> None:
    """Rewrites [cards], [cards.weights], and [cards.pokemon.<name>]; every other table is kept as is."""
    content = toml_path.read_text(encoding="utf-8") if toml_path.exists() else ""
    other = _strip_tables(content, "cards")
    prefix = other.rstrip() + "\n\n" if other.strip() else ""

    lines = [prefix]
    lines.append("[cards]\n")
    if active_pokemon:
        lines.append(f"active_pokemon = {_quote(active_pokemon)}\n")
    lines.append(
        "# How choice popups are answered: level-up, item choice, fossil ruins/blessing, Porygon, Snorlax, Ditto.\n"
    )
    lines.append(
        "# Card names exactly as the game shows them. Positive weight = prefer, negative = avoid, unlisted = 0.\n"
    )
    lines.append(
        "# The highest weight wins; equal weights fall back to rarity_order, then leftmost card.\n"
    )
    lines.append(
        '# Stat blessings: "+伤害" weighs every "+N% 伤害" roll, whatever the number.\n'
    )
    lines.append(f"rarity_order = {json.dumps(rarity_order, ensure_ascii=False)}\n\n")

    # Baseline weights
    lines.append("[cards.weights]\n")
    lines.append("# Baseline weights shared across all Pokémon (items, vitamins, general stats)\n")
    _write_weights_table(lines, baseline_weights)

    # Pokémon specific profiles
    if pokemon_profiles:
        for poke_name in sorted(pokemon_profiles.keys()):
            p_weights = pokemon_profiles[poke_name]
            lines.append(f"[cards.pokemon.{_quote(poke_name)}]\n")
            lines.append(f"# Specific skill priorities and overrides for {_one_line(poke_name)}\n")
            # 0 is kept here: it sets a shared weight back to neutral for this Pokémon.
            _write_weights_table(lines, p_weights, keep_zero=True)

    _write_toml(toml_path, "".join(lines))


_TABLE_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]")


def _strip_tables(content: str, root: str) -> str:
    """Drops [root] and every [root.*] table (they get rewritten); keeps all other tables and comments."""
    kept: list[str] = []
    inside = False
    for line in content.splitlines(keepends=True):
        header = _TABLE_HEADER.match(line)
        if header:
            name = header.group(1)
            inside = name == root or name.startswith(root + ".")
        if not inside:
            kept.append(line)
    return "".join(kept)


def _one_line(text: str) -> str:
    return re.sub(r"[\r\n]+", " ", text)  # keeps a name from breaking out of a # comment


def _quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # a JSON string is a valid TOML basic string


def _write_weights_table(
    lines: list[str], weights: dict[str, float], keep_zero: bool = False
) -> None:
    active = {k: v for k, v in weights.items() if keep_zero or v != 0}
    scores = sorted(set(active.values()), reverse=True)
    if not scores:
        lines.append("\n")
        return

    for score in scores:
        card_names = sorted([k for k, v in active.items() if v == score])
        score_val = int(score) if float(score).is_integer() else score
        if score > 0:
            lines.append(f"# Priority {score_val}\n")
        elif score == 0:
            lines.append("# Neutral (0): ignore the shared weight\n")
        else:
            lines.append(f"# Avoid ({score_val})\n")
        for name in card_names:
            lines.append(f"{_quote(name)} = {score_val}\n")
        lines.append("\n")


def build_full_card_list(
    toml_path: Path,
) -> dict[str, Any]:
    """Merges catalog with custom cards and profiles from autobonk.toml."""
    catalog, pokemon_151 = load_catalog()
    baseline_weights, rarity_order, active_pokemon, pokemon_profiles = read_config_weights(
        toml_path
    )

    # Roll-specific blessings ("+38% 伤害") are ignored by the bot; drop them so saving writes stats only.
    baseline_weights = _drop_rolls(baseline_weights)
    pokemon_profiles = {p: _drop_rolls(w) for p, w in pokemon_profiles.items()}

    known_names = {c["name"] for c in catalog}
    extra_cards = []

    # Gather any card names mentioned in baseline or any pokemon profile
    all_weight_keys = set(baseline_weights.keys())
    for p_dict in pokemon_profiles.values():
        all_weight_keys.update(p_dict.keys())

    for name in all_weight_keys:
        if name not in known_names:
            category = "其他"
            stat = "化石 / 多边兽 / 特殊效果"
            if name.startswith("+"):
                category = "祝福"
                stat = "属性祝福（不在目录中）"
            elif "化石" in name or "琥珀" in name:
                stat = "化石遗迹自选"
            extra_cards.append({
                "name": name,
                "category": category,
                "rarity": "其他",
                "stat": stat,
                "desc": stat,
                "pokemon": None,
            })

    all_cards = catalog + sorted(extra_cards, key=lambda c: c["name"])

    return {
        "cards": all_cards,
        "pokemon_151": pokemon_151,
        "baseline_weights": baseline_weights,
        "active_pokemon": active_pokemon,
        "pokemon_profiles": pokemon_profiles,
        "rarity_order": rarity_order,
    }


def _drop_rolls(weights: dict[str, float]) -> dict[str, float]:
    return {name: w for name, w in weights.items() if blessing_key(name) is None}


def _numeric(weights: Any) -> dict[str, float]:
    if not isinstance(weights, dict):
        raise ValueError("weights must be an object of card name -> number")
    out: dict[str, float] = {}
    for name, value in weights.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"weight for {name!r} is not a number: {value!r}")
        out[str(name)] = value
    return out


def make_handler(config_path: Path):
    class WeightEditorHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def log_request(self, code: Any = "-", size: Any = "-") -> None:
            pass

        def _send(self, status: HTTPStatus, content_type: str, body: str | bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8" if isinstance(body, str) else content_type)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body.encode("utf-8") if isinstance(body, str) else body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(HTTPStatus.OK, "text/html", UI_HTML_PATH.read_text(encoding="utf-8"))
            elif path == "/targets":
                self._send(HTTPStatus.OK, "text/html", TARGETS_HTML_PATH.read_text(encoding="utf-8"))
            elif path == "/api/targets":
                data = target_list(config_path)
                data["config_path"] = str(config_path)
                self._send(HTTPStatus.OK, "application/json", json.dumps(data, ensure_ascii=False))
            elif path.startswith("/icons/") and unquote(path[len("/icons/"):]) in TARGET_IMAGES:
                self._send(HTTPStatus.OK, "image/png", TARGET_IMAGES[unquote(path[len("/icons/"):])].read_bytes())
            elif path == "/api/data":
                data = build_full_card_list(config_path)
                data["config_path"] = str(config_path)
                self._send(HTTPStatus.OK, "application/json", json.dumps(data, ensure_ascii=False))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def _same_origin(self) -> bool:
            # Other sites open in the browser can POST to localhost. Requiring JSON forces a CORS
            # preflight (never answered here); Host blocks DNS rebinding; Origin blocks the rest.
            host = f"127.0.0.1:{self.server.server_address[1]}"
            origin = self.headers.get("Origin")
            return (
                self.headers.get("Content-Type", "").startswith("application/json")
                and self.headers.get("Host") == host
                and origin in (None, f"http://{host}")
            )

        def do_POST(self) -> None:
            if self.path not in ("/api/save", "/api/targets"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not self._same_origin():
                self._send(
                    HTTPStatus.FORBIDDEN,
                    "application/json",
                    json.dumps({"status": "error", "error": "cross-origin save refused"}),
                )
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body.decode("utf-8"))
                if self.path == "/api/targets":
                    save_target_weights(
                        config_path, _target_weights(data.get("weights", {})), _boss_from(data.get("boss", {}))
                    )
                    self._send(HTTPStatus.OK, "application/json", json.dumps({"status": "ok"}))
                    return
                baseline_weights = data.get("baseline_weights", {})
                # If legacy payload sent 'weights', treat as baseline
                if not baseline_weights and "weights" in data:
                    baseline_weights = data["weights"]
                profiles = data.get("pokemon_profiles") or {}
                if not isinstance(profiles, dict):
                    raise ValueError("pokemon_profiles must be an object")

                save_config_weights(
                    config_path,
                    baseline_weights=_numeric(baseline_weights),
                    rarity_order=[str(r) for r in data.get("rarity_order", [])],
                    active_pokemon=data.get("active_pokemon") or None,
                    pokemon_profiles={str(p): _numeric(w) for p, w in profiles.items()},
                )
                res = {"status": "ok"}
                status = HTTPStatus.OK
            except Exception as exc:
                res = {"status": "error", "error": str(exc)}
                status = HTTPStatus.BAD_REQUEST
            self._send(status, "application/json", json.dumps(res, ensure_ascii=False))

    return WeightEditorHandler


def find_free_port(preferred_port: int) -> int:
    for port in range(preferred_port, preferred_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred_port


def run_editor(config_path: Path, port: int = 8080, open_browser: bool = True) -> None:
    config_path = Path(config_path).resolve()
    actual_port = find_free_port(port)
    server_address = ("127.0.0.1", actual_port)
    handler_class = make_handler(config_path)
    httpd = HTTPServer(server_address, handler_class)

    url = f"http://127.0.0.1:{actual_port}/"
    print("\n=======================================================")
    print("  PokéBonk Weight Editor is running! (cards /, map targets /targets)")
    print(f"  Config: {config_path}")
    print(f"  Open in browser: {url}")
    print("  Press Ctrl+C to stop the server.")
    print("=======================================================\n")

    if open_browser:
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="PokéBonk Card Weight Editor GUI")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT_DIR / "autobonk.toml",
        help="Path to autobonk.toml",
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Local server port (default: 8080)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Don't open browser automatically"
    )
    args = parser.parse_args()

    run_editor(config_path=args.config, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
