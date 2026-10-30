"""Debug inspection script for saved frames."""

import argparse
import math
import sys
from pathlib import Path

from autobonk.config import load_config
from autobonk.frames import load_frame
from autobonk.game import ALTAR, BOSS
from autobonk.perception import perceive
from autobonk.policy.bot import Bot


def debug_frame(stem_path: Path, config_path: Path = Path("autobonk.toml"), save_overlay: bool = True) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config(config_path)

    bot = Bot(cards=cfg.cards, movement=cfg.movement, targets=cfg.targets, boss=cfg.boss)

    frame = load_frame(stem_path)
    obs = perceive(frame, bot._icons)

    print("=" * 60)
    print(f"FRAME DEBUG: {stem_path.name}")
    print("=" * 60)
    print(f"Zone:             {obs.zone} (index: {obs.zone_index})")
    print(f"Countdown:        {obs.countdown} ({obs.seconds_left}s remaining)")
    print(f"Player Level:     {obs.level}")
    print(f"Prompt:           {obs.prompt}")
    print(f"Boss Down:        {obs.boss_down}")
    print(f"Has Portal:       {obs.portal}")
    print(f"Has Unopened:     {obs.has_unopened_super_balls}")

    # Boss Readiness
    print("\n--- BOSS RULE STATUS ---")
    if cfg.boss and obs.zone_index:
        i = min(obs.zone_index, len(cfg.boss.levels)) - 1
        req_lvl = cfg.boss.levels[i]
        req_min = cfg.boss.minutes_left[i]
        is_ready = cfg.boss.ready(obs.zone_index, obs.level, obs.seconds_left)
        strong = obs.level is not None and obs.level >= req_lvl
        late = obs.seconds_left is not None and obs.seconds_left <= req_min * 60
        print(f"Zone {obs.zone_index} Boss Rule: Level >= {req_lvl} OR Time <= {req_min:.1f}m ({req_min*60:.0f}s)")
        print(f"  Level condition met? {strong} (current: {obs.level}, required: {req_lvl})")
        print(f"  Time condition met?  {late} (current: {obs.seconds_left}s, required: <= {req_min*60:.0f}s)")
        print(f"  --> Boss ready?      {is_ready}")
    else:
        print("No boss configured or zone index missing.")

    # Target Weights
    weights = bot._weigh(obs, 0.0)
    print("\n--- ACTIVE WEIGHTS (TOP 5 + BOSS) ---")
    sorted_weights = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    for name, w in sorted_weights[:5]:
        print(f"  {name:10s}: {w}")
    if BOSS in weights and BOSS not in [n for n, _ in sorted_weights[:5]]:
        print(f"  {BOSS:10s}: {weights[BOSS]}")

    # Map Detections
    print("\n--- MAP DETECTIONS ---")
    print(f"Minimap Altars:   {obs.altars}")
    print(f"Minimap Targets:  {obs.targets}")
    if obs.zonemap:
        print(f"Zonemap Player:   ({obs.zonemap.player[0]:.3f}, {obs.zonemap.player[1]:.3f})")
        print(f"Zonemap Altars:   {len(obs.zonemap.altars)} found")
        print(f"Zonemap Targets:  {len(obs.zonemap.targets)} found:")
        for name, (tx, ty) in obs.zonemap.targets:
            p_dist = math.hypot(tx - obs.zonemap.player[0], ty - obs.zonemap.player[1])
            is_boss_marker = " [TARGET BOSS]" if name == BOSS else ""
            print(f"    - {name:10s} at ({tx:.3f}, {ty:.3f}) dist={p_dist:.3f}{is_boss_marker}")
    else:
        print("Zonemap:          Not opened (Tab not held in this frame)")

    # Bot Step Decision
    print("\n--- BOT DECISION ---")
    plan = bot.step(frame)
    print(f"Target chosen:    {bot._target}")
    print(f"Target Heading:   {bot._heading:.1f}°" if bot._heading is not None else "Target Heading:   None")
    print(f"Minimap Bearing:  {bot._bearing:.1f}°" if bot._bearing is not None else "Minimap Bearing:  None")
    print(f"Commands issued:  {plan}")

    # Optional Overlay Image Generation
    if save_overlay and obs.zonemap:
        try:
            from PIL import Image, ImageDraw
            from autobonk.zonemap import BORDER
            zm_path = stem_path.with_suffix(".zonemap.png")
            if zm_path.exists():
                img = Image.open(zm_path).convert("RGB")
                draw = ImageDraw.Draw(img)
                low, high = BORDER
                span = high - low
                px, py = obs.zonemap.player
                pt_x, pt_y = low + px * span, low + py * span
                draw.ellipse([pt_x - 12, pt_y - 12, pt_x + 12, pt_y + 12], outline=(255, 0, 0), width=4)
                for name, (tx, ty) in obs.zonemap.targets:
                    tx_px, ty_px = low + tx * span, low + ty * span
                    color = (255, 0, 255) if name == BOSS else (255, 255, 0)
                    draw.rectangle([tx_px - 8, ty_px - 8, tx_px + 8, ty_px + 8], outline=color, width=3)
                    if name == BOSS:
                        draw.line([pt_x, pt_y, tx_px, ty_px], fill=(0, 255, 255), width=3)
                out_file = Path(".scratch") / f"{stem_path.name}_annotated.png"
                out_file.parent.mkdir(parents=True, exist_ok=True)
                img.save(out_file)
                print(f"\nOverlay map saved to: {out_file}")
        except Exception as e:
            print(f"Could not generate overlay image: {e}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Debug a saved frame")
    parser.add_argument("frame", nargs="?", help="Frame JSON stem or filename")
    args = parser.parse_args()

    if args.frame:
        target = Path(args.frame)
        if target.suffix:
            target = target.with_suffix("")
    else:
        # Pick latest frame
        frames = sorted(Path("fixtures/frames").glob("frame-*.json"))
        if not frames:
            print("No frames found in fixtures/frames")
            sys.exit(1)
        target = frames[-2].with_suffix("") if len(frames) >= 2 and "001530" in frames[-1].name else frames[-1].with_suffix("")

    debug_frame(target)
