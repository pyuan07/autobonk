"""Local web GUI for viewing and editing PokéBonk card weights in autobonk.toml."""

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

from autobonk.cards import blessing_key

ROOT_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = Path(__file__).resolve().parent / "catalog_data.json"
UI_HTML_PATH = Path(__file__).resolve().parent / "editor_ui.html"
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


def save_config_weights(
    toml_path: Path,
    baseline_weights: dict[str, float],
    rarity_order: list[str],
    active_pokemon: str | None = None,
    pokemon_profiles: dict[str, dict[str, float]] | None = None,
) -> None:
    """Rewrites [cards], [cards.weights], and [cards.pokemon.<name>]; every other table is kept as is."""
    content = toml_path.read_text(encoding="utf-8") if toml_path.exists() else ""
    other = _strip_cards_tables(content)
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

    new_toml = "".join(lines).rstrip() + "\n"
    tomllib.loads(new_toml)  # never write a file the bot can't read
    tmp_path = toml_path.with_name(toml_path.name + ".tmp")
    tmp_path.write_text(new_toml, encoding="utf-8")
    os.replace(tmp_path, toml_path)


_TABLE_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]")


def _strip_cards_tables(content: str) -> str:
    """Drops [cards] and every [cards.*] table (they get rewritten); keeps all other tables and comments."""
    kept: list[str] = []
    in_cards = False
    for line in content.splitlines(keepends=True):
        header = _TABLE_HEADER.match(line)
        if header:
            name = header.group(1)
            in_cards = name == "cards" or name.startswith("cards.")
        if not in_cards:
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

        def _send(self, status: HTTPStatus, content_type: str, body: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(HTTPStatus.OK, "text/html", UI_HTML_PATH.read_text(encoding="utf-8"))
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
            if self.path != "/api/save":
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
    print("  PokéBonk Card Weight Editor is running!")
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
