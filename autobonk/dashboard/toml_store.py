"""TOML storage and catalog loader for card weights, target weights, and profiles."""

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

from autobonk.game import ALTAR, BOSS, BossRule
from autobonk.policy.cards import blessing_key

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CATALOG_PATH = Path(__file__).resolve().parent.parent / "catalog_data.json"
DEFAULT_TARGET_WEIGHTS = {ALTAR: 10.0}
DEFAULT_RARITY_ORDER = ["招式", "传说", "史诗", "稀有", "少见", "普通"]


def load_catalog() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Loads stat blessings, vitamins, items, moves, and 151 pokemon list."""
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


def save_config_weights(
    toml_path: Path,
    baseline_weights: dict[str, float],
    rarity_order: list[str],
    active_pokemon: str | None = None,
    pokemon_profiles: dict[str, dict[str, float]] | None = None,
) -> None:
    content = toml_path.read_text(encoding="utf-8") if toml_path.exists() else ""
    other = _strip_tables(content, "cards")
    prefix = other.rstrip() + "\n\n" if other.strip() else ""

    lines = [prefix]
    lines.append("[cards]\n")
    if active_pokemon:
        lines.append(f"active_pokemon = {_quote(active_pokemon)}\n")
    lines.append("# How choice popups are answered: level-up, item choice, fossil ruins/blessing, Porygon, Snorlax, Ditto.\n")
    lines.append("# Card names exactly as the game shows them. Positive weight = prefer, negative = avoid, unlisted = 0.\n")
    lines.append("# The highest weight wins; equal weights fall back to rarity_order, then leftmost card.\n")
    lines.append('# Stat blessings: "+伤害" weighs every "+N% 伤害" roll, whatever the number.\n')
    lines.append(f"rarity_order = {json.dumps(rarity_order, ensure_ascii=False)}\n\n")

    lines.append("[cards.weights]\n")
    lines.append("# Baseline weights shared across all Pokémon (items, vitamins, general stats)\n")
    _write_weights_table(lines, baseline_weights)

    if pokemon_profiles:
        for poke_name in sorted(pokemon_profiles.keys()):
            p_weights = pokemon_profiles[poke_name]
            lines.append(f"[cards.pokemon.{_quote(poke_name)}]\n")
            lines.append(f"# Specific skill priorities and overrides for {_one_line(poke_name)}\n")
            _write_weights_table(lines, p_weights, keep_zero=True)

    _write_toml(toml_path, "".join(lines))


def build_full_card_list(toml_path: Path) -> dict[str, Any]:
    catalog, pokemon_151 = load_catalog()
    baseline_weights, rarity_order, active_pokemon, pokemon_profiles = read_config_weights(toml_path)

    baseline_weights = _drop_rolls(baseline_weights)
    pokemon_profiles = {p: _drop_rolls(w) for p, w in pokemon_profiles.items()}

    known_names = {c["name"] for c in catalog}
    extra_cards: list[dict[str, Any]] = []

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

    all_cards = catalog + sorted(extra_cards, key=lambda c: str(c["name"]))

    return {
        "cards": all_cards,
        "pokemon_151": pokemon_151,
        "baseline_weights": baseline_weights,
        "active_pokemon": active_pokemon,
        "pokemon_profiles": pokemon_profiles,
        "rarity_order": rarity_order,
    }


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
    tomllib.loads(new_toml)
    tmp_path = toml_path.with_name(toml_path.name + ".tmp")
    tmp_path.write_text(new_toml, encoding="utf-8")
    os.replace(tmp_path, toml_path)


_TABLE_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]")


def _strip_tables(content: str, root: str) -> str:
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
    return re.sub(r"[\r\n]+", " ", text)


def _quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


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
