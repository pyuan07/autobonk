"""Map icons the bot can walk to (other than rune altars), matched on the minimap and the zone map."""

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from autobonk.perception.matching import load_template, match_many

ICON_DIR = Path(__file__).resolve().parent.parent / "icons"

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

POKEMON_ICONS = {
    "喵喵": "meowth.png",
    "引梦貘人": "hypno.png",
    "耿鬼": "gengar.png",
    "卡比兽": "snorlax.png",
    "百变怪": "ditto.png",
    "多边兽": "porygon.png",
    "火暴猴": "primeape.png",
    "铁甲犀牛": "rhydon.png",
    "吉利蛋": "chansey.png",
}

# Icons the bot reads for the zone's flow, never weighted targets (kept out of the editor).
# The portal only appears once the area boss is down.
FLOW_ICONS = {
    "传送门": "portal.png",
}

ICONS = {**ITEM_ICONS, **POKEMON_ICONS, **FLOW_ICONS}
ICON_MATCH = 0.65

Icon = tuple[str, tuple[int, int]]  # (name, centre in image pixels)


def find_targets(
    image: np.ndarray,
    names: Sequence[str] | None = None,
    step: int = 1,
    threshold: float | None = None,
) -> list[Icon]:
    """Every catalogued icon (or just `names`) in the image, best match first.
    `step` > 1 matches on every step-th pixel: faster on large maps."""
    query_names = list(ICONS) if names is None else [n for n in names if n in ICONS]
    if not query_names:
        return []

    # Map template file -> canonical name to report for this query
    template_to_names: dict[str, list[str]] = {}
    for name in query_names:
        template_file = ICONS[name]
        template_to_names.setdefault(template_file, []).append(name)

    unique_files = list(template_to_names.keys())
    templates = [load_template(ICON_DIR / f)[::step, ::step] for f in unique_files]
    found: list[tuple[float, Icon]] = []
    effective_thresh = threshold if threshold is not None else (ICON_MATCH if step == 1 else 0.55)

    sub_image = image[::step, ::step] if step > 1 else image
    for template_file, template, scores in zip(unique_files, templates, match_many(sub_image, templates), strict=False):
        size = template.shape[0]
        # For templates shared by aliases (like 超级球 and 礼物球), pick one to avoid duplicates at same location
        shared_names = template_to_names[template_file]
        primary_name = shared_names[0]

        while True:
            y, x = np.unravel_index(scores.argmax(), scores.shape)
            if scores[y, x] < effective_thresh:
                break
            score = float(scores[y, x])
            pos = ((int(x) + size // 2) * step, (int(y) + size // 2) * step)
            found.append((score, (primary_name, pos)))
            scores[max(0, y - size):y + size, max(0, x - size):x + size] = -1

    return [icon for _, icon in sorted(found, key=lambda f: -f[0])]
