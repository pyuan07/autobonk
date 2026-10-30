"""User-editable settings, loaded from a TOML file with defaults for anything missing."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from autobonk.cards import DEFAULT_RARITY_ORDER, CardPrefs


@dataclass(frozen=True)
class Config:
    url: str
    profile_dir: Path
    viewport_width: int
    viewport_height: int
    frames_dir: Path
    pause_hotkey: str
    frame_hotkey: str
    steps_per_second: float
    unknown_screen_pause_s: float
    cards: CardPrefs
    choices_file: Path
    active_pokemon: str | None = None
    jump_interval_s: tuple[float, float] = (0.8, 1.4)
    altar_charge_cap_s: float = 45.0


def load_config(path: Path) -> Config:
    """Load `path`; relative paths in it resolve against the file's folder."""
    path = Path(path)
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    base = path.parent

    browser = data.get("browser", {})
    frames = data.get("frames", {})
    hotkeys = data.get("hotkeys", {})
    bot = data.get("bot", {})
    cards = data.get("cards", {})
    pause_hotkey = hotkeys.get("pause", "f8").lower()
    frame_hotkey = hotkeys.get("frame", "f9").lower()
    if pause_hotkey == frame_hotkey:
        raise ValueError(f"{path}: pause and frame hotkeys are both {pause_hotkey!r}")

    # Resolve card weights: baseline [cards.weights] merged with [cards.pokemon.<active_pokemon>]
    weights = dict(cards.get("weights", {}))
    active_pokemon = cards.get("active_pokemon")
    pokemon_table = cards.get("pokemon", {})
    if active_pokemon and isinstance(pokemon_table, dict) and active_pokemon in pokemon_table:
        specific = pokemon_table[active_pokemon]
        if isinstance(specific, dict):
            weights.update(specific)

    return Config(
        url=browser.get("url", "https://pokebonk.com/"),
        profile_dir=base / browser.get("profile_dir", "profile"),
        viewport_width=browser.get("viewport_width", 1600),
        viewport_height=browser.get("viewport_height", 900),
        frames_dir=base / frames.get("dir", "fixtures/frames"),
        pause_hotkey=pause_hotkey,
        frame_hotkey=frame_hotkey,
        steps_per_second=bot.get("steps_per_second", 10),
        unknown_screen_pause_s=bot.get("unknown_screen_pause_s", 5),
        cards=CardPrefs(
            weights=weights,
            rarity_order=tuple(cards.get("rarity_order", DEFAULT_RARITY_ORDER)),
        ),
        choices_file=base / data.get("record", {}).get("choices_file", "logs/choices.jsonl"),
        active_pokemon=active_pokemon,
        jump_interval_s=tuple(bot.get("jump_interval_s", (0.8, 1.4))),
        altar_charge_cap_s=bot.get("altar_charge_cap_s", 45),
    )
