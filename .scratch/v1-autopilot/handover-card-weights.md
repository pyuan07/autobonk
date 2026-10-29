# Handover: derive card weights from the player's recorded picks

## Context

`autobonk` is a Python helper that plays the browser roguelike PokéBonk (https://pokebonk.com/, Chinese UI).
When a choice popup opens (level-up, item choice, Snorlax blessing, fossil ruins, Porygon altar, Ditto
copy …), the bot scores the offered cards and picks the best. Right now the weights are a guessed
starter set. The player has just played **one full run themselves**, with one fixed Pokémon, while the
helper recorded every popup pick they made. Your job is to turn that recording into card weights
that make the bot pick the way the player does.

Repo: `E:\Projects\autobonk`, branch `master`. Python venv at `.venv`
(run `.venv\Scripts\python`; set `PYTHONIOENCODING=utf-8` when printing Chinese to the console).

## Input: `logs/choices.jsonl`

There are 251 lines, one per pick, in this format:

```json
{"time": "2026-10-30T00:51:02", "title": "等级 2！",
 "offered": [{"key": "1", "name": "咬住", "rarity": "招式", "details": ["新", "新招式", "..."]}, ...],
 "input": "3", "picked": "好伤药"}
```

- `offered[].key` is `"1"`–`"4"` for numbered cards, and `""` when the popup has no number keys (Ditto).
- `rarity` is the first `<span>` of the card. On level-up it is 普通/少见/稀有/史诗/传说. A new-move card
  shows `招式`. Fossil and Porygon cards show category words (道具/祝福/伙伴, 重新编译).
- `details` is the rest of the card's visible text: effect lines, `新` (new) vs `强化` (upgrade), and level
  arrows like `等级 3 → 4（最高 8）`. Use it to understand what a card does and whether it's a move.
- `input` is the key pressed (`"1"`, `"e"`, `"v"`, `"Escape"`, `"f"` …) or the full text of the clicked
  card or button (e.g. `"史诗\n强化\n<name>…"`).
- `picked` is the resolved choice: a card name, or a button text such as `拾取`, `出售 (+18 ₽)`, `就绪`,
  `离开`, `以后再说`, `刷新 (8)`.

Known noise and quirks. Check these yourself, don't assume:

- **Menu and notice entries:** a few have no game choice. Examples are the character select
  (`波波`/`超梦` → `我选你了！`), the map select (`青翠森林` → `出发！`) and the untitled "我们找回了你的上一局 → 知道了"
  notice. The last character picked (it looks like **超梦**) is probably the fixed Pokémon; confirm it from the log.
- **Repeated titles:** some titles repeat (e.g. `等级 113` ×21). These may be rerolls (`f` / `刷新`),
  consecutive picks, or clicks counted twice. Check `input` and `time` before treating repeats as
  separate decisions.
- **Popup types not seen before:** `未知图腾祭坛` / `稀有未知图腾祭坛` / `史诗未知图腾祭坛` (rune altar
  rewards), `霸主光环`, `卡比兽的祝福`. Describe what they offered and what was picked.

## How the bot scores (`autobonk/cards.py`, config in `autobonk.toml` → `[cards]`)

- **Score:** each card's score is `(weight, rarity rank)`, and the highest score wins. Ties go to the leftmost card.
- **Weight:** `weights[name]`. Unlisted names weigh 0. Positive means prefer, negative means avoid. Any
  positive weight therefore beats any unlisted card, whatever its rarity.
- **Rarity rank:** comes from `rarity_order` (best first). Rarities not listed rank below all listed ones.
- **Names must match exactly** as shown, including full-width characters (e.g. `ＨＰ增强剂`).
- **Shared weights:** one weights table serves every popup type. The bot never presses Refresh (F), Skip (X)
  or Banish (Z). It always picks up single items (E), clicks 就绪 on Hypno (forgets nothing) and leaves
  the shop, fusion machine and slot machine.

Current config shape (the `[cards.weights]` table must stay last in the file):

```toml
[cards]
rarity_order = ["传说", "稀有", "少见", "普通"]

[cards.weights]
"活力块" = 10
"诅咒薰香" = -5
```

## What to do

1. **Clean the data.** Drop the non-choice entries. Collapse duplicates and rerolls into real decisions,
   and say how many real decisions remain per popup type.
2. **Analyse the player's preferences.**
   - **Moves:** new moves vs move upgrades vs passive items/vitamins, and which moves they kept upgrading.
   - **Ranking:** which names they consistently take, and which they consistently pass over or avoid.
   - **Rarity:** how much rarity matters to them versus the specific name. Note that the log contains 史诗,
     which is missing from the current `rarity_order`.
   - **Non-card actions:** whether they ever sold (`v`), rerolled, skipped, banished, or forgot a move
     at Hypno. These are behaviours the bot doesn't copy.
   - **Other popups:** fossil, Porygon, Snorlax, Ditto and rune-altar choices.
3. **Propose weights.** Write a complete replacement `[cards]` section (`rarity_order` + `[cards.weights]`)
   in tiers, with a short comment per tier.
4. **Measure agreement.** Replay every cleaned decision through the scorer and report how often it
   reproduces the player's pick, overall and per popup type. List the misses. Use `CardPrefs(weights=...,
   rarity_order=...).best(cards)` from `autobonk.cards`, building `Card(key, name, rarity)` objects for the
   offered cards. For keyless popups (Ditto) the bot uses the same `best`. Iterate on the weights to raise
   agreement, but don't overfit single one-off picks.
5. **List what weights can't express.** Examples: a choice that depends on context (current level,
   stack count `你有 x/10`, max move level, timer) or on the run's state. For each, say how often it
   occurred and what bot rule would capture it.

## Deliverables

- **A report** at `.scratch/v1-autopilot/card-weights-analysis.md`. It contains the cleaning summary, the
  preference analysis, the proposed `[cards]` section, the agreement numbers with the misses, and the
  list of what weights can't express.
- **The config change:** replace only the `[cards]` section of `autobonk.toml` (including `[cards.weights]`)
  with your proposal. Keep the comment lines that explain the rules.
- **Then** run `.venv\Scripts\python -m pytest -q`; all tests must still pass. If a test depends on the
  old starter weights, report it rather than changing it.

## Constraints

- Don't change any Python code, and don't touch other sections of `autobonk.toml`.
- Don't commit. The player reviews first.
- `logs/` is personal play data and is git-ignored, so leave it there and don't copy it into the repo.
