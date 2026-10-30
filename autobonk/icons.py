"""Map icons the bot can walk to (other than rune altars), matched on the minimap and the zone map.

Each template is the 28x28 middle of an icon, inside its ring. On the recorded maps every icon
scores >= 0.76 against its own kind and <= 0.56 against any other.
"""

from pathlib import Path

import numpy as np

from autobonk.minimap import _template, match_many

ICON_DIR = Path(__file__).parent / "icons"
# Name as shown in the editor and autobonk.toml [targets.weights] -> template file.
ITEM_ICONS = {
    "精灵球": "pokeball.png",
    "超级球": "gift.png",
    "礼物球": "gift.png",
    "矿堆": "ore.png",
    "金币": "coin.png",
    "牢笼": "lock.png",
    "蘑菇": "mushroom.png",
    "水滴": "slime.png",
    "双剑": "swords.png",
    "毒球": "poison.png",
    "磁铁": "magnet.png",
    "骷髅": "skull.png",
    "绿水晶": "crystal.png",
    "融合机": "fusion.png",
}
# Pokémon faces: shops, tutors and bosses.
POKEMON_ICONS = {
    "喵喵": "meowth.png",
    "引梦貘人": "hypno.png",
    "耿鬼": "gengar.png",
    "卡比兽": "snorlax.png",
    "百变怪": "ditto.png",
    "多边兽": "porygon.png",
    "火暴猴": "primeape.png",
    "铁甲犀牛": "rhydon.png",
}
ICONS = {**ITEM_ICONS, **POKEMON_ICONS}
ICON_MATCH = 0.65

Icon = tuple[str, tuple[int, int]]  # (name, centre in image pixels)


def find_targets(image: np.ndarray, names: list[str] | None = None) -> list[Icon]:
    """Every catalogued icon (or just `names`) in the image, best match first."""
    names = list(ICONS) if names is None else [n for n in names if n in ICONS]
    if not names:
        return []
    templates = [_template(ICON_DIR / ICONS[name]) for name in names]
    found: list[tuple[float, Icon]] = []
    for name, template, scores in zip(names, templates, match_many(image, templates)):
        size = template.shape[0]
        while True:
            y, x = np.unravel_index(scores.argmax(), scores.shape)
            if scores[y, x] < ICON_MATCH:
                break
            found.append((float(scores[y, x]), (name, (int(x) + size // 2, int(y) + size // 2))))
            scores[max(0, y - size):y + size, max(0, x - size):x + size] = -1
    return [icon for _, icon in sorted(found, key=lambda f: -f[0])]
