# Card Weights Analysis & Tuning Report

## 1. Executive Summary

This report analyzes the recorded player choices from a complete single-character run (`logs/choices.jsonl`, 253 raw entries) playing PokéBonk as **超梦 (Mewtwo)** on the **青翠森林 (Verdant Forest)** map.

By systematically cleaning the raw telemetry (dropping non-choice dialogs, collapsing UI double-clicks, and consolidating multi-step rerolls and banishes into final decisions), we extracted **155 real game decisions**, of which **146 were card selections** and **9 were non-card decisions** (6 level-up skips and 3 altar/machine exits).

### Key Results
- **Old Starter Weights Agreement:** **41.8%** on card picks (61 / 146) and **39.4%** across all decisions (61 / 155). The starter weights suffered from heavy bias toward physical/rock items (`硬石头`, `达人带`, `锐利之爪`), outdated survival items (`活力块`, `ＨＰ增强剂`, `好伤药`), and treating late-game scaling items (`诅咒薰香`, `白色玻璃哨`) as negative.
- **Proposed Weights Agreement:** **85.6%** on card picks (125 / 146) and **80.6%** across all decisions (125 / 155).
- **Non-Level-Up Popups:** Achieved **100.0% agreement (37 / 37)** across all 11 non-level-up popup types (Chest item choices, Snorlax blessings, Fossil ruins, Fossil blessings, Ditto duplications, Rune altars, Overlord aura, Porygon altar, and Fusion machine).
- **Level-Up Popups:** Achieved **80.7% agreement (88 / 109)** on card picks. All 21 misses are documented and categorized into structural limitations of static scoring (equal-score tie breaks, run-context move balancing, and move forgetting history).

---

## 2. Data Cleaning & Decision Accounting

The input file `logs/choices.jsonl` contains 253 entries logged during live gameplay. Telemetry captured key presses, button clicks, and full DOM text matches.

### 2.1 Non-Choice Entries Dropped (17 entries)
These entries represent UI menus, reconnection dialogs, or NPC interactions where no card choices are evaluated by the card scorer:
1. **Reconnection Notice** (`title == ""`): Lines 0 and 1 (reconnection popup prompted `知道了`, offered `[]`).
2. **Character Select Menu**: Lines 2 (`波波`) and 3 (`超梦`), confirmed Mewtwo via `我选你了！`.
3. **Map Select Menu**: Line 4 (`青翠森林`), confirmed via `出发！`.
4. **Post-Run Guild / Team Screen**: Lines 251 and 252 (`战队`), menu clicks after the run.
5. **Shop Visits** (`喵喵：“有钱吗，喵？”`): Lines 41, 86, and 182 (3 entries). Mewtwo had 0 cards offered and exited with `离开` (`Escape`).
6. **Hypno (Move Relearning / Forgetting)** (`引梦貘人`): Lines 44, 45, 130, 197, 198, 220, 221 (7 entries). The bot by design clicks `就绪` without forgetting; the DOM offered `[]` cards.

### 2.2 Single-Item Pickups (`你发现了一件道具！`) (34 raw entries -> 32 pickups)
Across the run, 34 single-item drop entries occurred. In every instance, exactly one item was offered with choices `拾取` (`E`) vs `出售` (`V`).
- The player chose `拾取` 100% of the time (never sold an item).
- Lines 59 & 60 were duplicate logs of `探宝器` (line 59 clicked the card modal text, line 60 clicked `拾取`).
- Lines 144 & 145 were duplicate logs of `生命宝珠` within the same second (`01:02:02`).
- Under `autobonk`'s policy (`bot.py`), single-item pickups are handled directly via the `E` key (`PICK_UP_BUTTON = "拾取"`) and are never scored by `CardPrefs.best()`.

### 2.3 Collapsing Duplicate Clicks, Rerolls, and Banishes
1. **Modal Text Clicks**:
   - `稀有未知图腾祭坛` (lines 12 & 13 at `00:49:03` and `00:49:04`): Line 12 clicked the modal container text (matching `+24% 持续时间` as the first substring), immediately followed by line 13 picking `+22% 经验`. Collapsed into 1 decision: picked `+22% 经验`.
2. **Level-Up Rerolls (`刷新`)**:
   - 8 reroll entries occurred across levels 2, 3, 27 (×2), 30, 62, 86, and 109. In each case, the player rerolled to a new offer and concluded the level-up with a card choice on the final offer. Collapsed into the final real decision for that level.
3. **Level 113 Banish Sequence (`放逐`)**:
   - At Level 113 (lines 199–219, 21 entries), the player used 7 banishes (`Z`): banishing `防御增强剂`, `攻击增强剂`, `谜芝果`, `命中强化`, `好伤药`, `机变骰子`, and `ＨＰ增强剂` (each card click logged twice due to input drain timing), before finally choosing `星星碎片`. Collapsed into 1 decision: picked `星星碎片` from the final offer `['广域战力', '星星碎片', '防御强化', '诅咒薰香']`.
4. **Late-Game Key Spamming (Levels 119–125)**:
   - For levels 119 to 125, all other items were maxed or banished, leaving only `['诅咒薰香']` offered. The player repeatedly pressed `1` to confirm, logging 2 to 4 entries per level within 1 second. Each level corresponds to 1 level-up decision (7 decisions total).
5. **Queued Simultaneous Level-Ups**:
   - Level 49 (lines 83 & 84) and Level 83 (lines 147–149) logged consecutive distinct offers under the same level title because the player gained multiple levels simultaneously (e.g., from `神奇糖果` or high XP burst). Each offer presented distinct cards and upgrades, so they are correctly preserved as 2 and 3 distinct decisions respectively.

### 2.4 Cleaned Decisions Breakdown

| Popup Type | Raw Entries | Cleaned Decisions | Card Picks | Non-Card Actions | Notes |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **等级提升** (Level-up) | 161 | 115 | 109 | 6 (`跳过` skips) | 8 rerolls, 20 banish sub-actions, 19 key repeats collapsed |
| **你发现了道具！** (Chest choice) | 13 | 13 | 13 | 0 | 3-card choices, 100% agreement |
| **卡比兽的祝福** (Snorlax blessing) | 5 | 5 | 5 | 0 | Stat blessings |
| **未知图腾祭坛** (Rune altar) | 4 | 4 | 4 | 0 | Permanent blessing choices |
| **化石遗迹** (Fossil ruins) | 3 | 3 | 3 | 0 | All picked `甲壳化石` |
| **甲壳化石的远古祝福** (Fossil blessing)| 3 | 3 | 3 | 0 | Legendary stat blessings |
| **百变怪** (Ditto item clone) | 3 | 3 | 3 | 0 | Unkeyed inventory copy (PP Max, Moon Stone) |
| **多边兽祭坛** (Porygon altar) | 3 | 3 | 1 | 2 (`以后再说` Esc) | Picked `伤害`, exited on stat penalties |
| **稀有未知图腾祭坛** (Rare altar) | 3 | 2 | 2 | 0 | 1 container click collapsed |
| **正辉的机器** (Fusion machine) | 2 | 2 | 1 | 1 (`以后再说` Esc) | Exited when unready, fused `基因霸权` |
| **史诗未知图腾祭坛** (Epic altar) | 1 | 1 | 1 | 0 | Picked `+17% 范围` |
| **霸主光环** (Overlord aura) | 1 | 1 | 1 | 0 | Picked `+14% 范围` |
| **Total** | **202** | **155** | **146** | **9** | **125 / 146 (85.6%) card agreement** |

*(Plus 17 non-choice entries dropped + 34 single-item pickups = 253 total entries)*

---

## 3. Player Preference Analysis

### 3.1 Pokémon & Core Build Architecture
The player locked in **超梦 (Mewtwo)**, a Special Attacker characterized by burst projectile and beam moves.
- **Move Specialization:** Mewtwo starts with `精神利刃` (Psycho Cut, physical). The player immediately sought Special Psychic moves:
  1. `精神击破` (Psystrike, Special Burst Sphere): learned at Lv 2, upgraded 14 times.
  2. `棱镜镭射` (Prismatic Laser, Special Piercing Beam): learned at Lv 7, upgraded 11 times.
  3. `精神突进` (Psycho Boost, Special Meteor): learned at Lv 8, upgraded 9 times.
- **The Physical Move Pivot:** At Lv 21, all 4 move slots were full. The player visited Hypno and paid to forget `精神利刃` (`-24 ₽`), freeing a slot. At Lv 33, they learned `幻象光线` (Psybeam, Special Beam) to complete an all-Special Psychic arsenal.
- **Signature Fusion:** At Bill's machine (`正辉的机器`), once `精神击破` and `精神突进` reached Lv 8, they fused them into `基因霸权` (Genetic Hegemony, ★6 Signature Fusion), freeing a slot to learn `广域战力` (Expanding Force) at Lv 93.

### 3.2 High-Priority Vitamins & Scaling Passives
- **`全满药` (Full Restore / Spell Vamp):** Picked 10 times. Spell vamp / life steal (`+2%` to `+3.5%` per level) provided all required sustain. The player never needed defensive healing consumables like `好伤药` or `活力块`.
- **`星星碎片` (Star Piece / Luck):** Picked 10 times. Luck directly scales critical hits, drop rarities, and altar appearances.
- **`ＰＰ单项小补剂` (PP Up / Attack Speed):** Picked 10 times. Stacked attack speed (`+11.6%` to `+14.5%`) on Mewtwo's high-damage moves.
- **`诅咒薰香` (Curse Incense):** Ignored or skipped during the early game (Lv 1–30) to avoid difficulty spikes while under-leveled. However, from Lv 116 onward, once the build was invincible, the player actively picked `诅咒薰香` 10 times (raising difficulty and boosting XP/coins).

### 3.3 Cards Consistently Avoided / Rejected
- **`星星沙子` (Star Sand):** Offered **16 times**, picked **0 times** (0%). The player consistently prioritized damage, attack speed, or life steal over generic area scaling.
- **`精神扭曲` (Psychic Twist):** Offered 10 times in Bill's fusion machine, picked 0 times (player only wanted `基因霸权`).
- **`速度增强剂`, `防御增强剂`, `攻击增强剂`, `ＨＰ增强剂`:** Regularly skipped or banished; physical attack and flat HP were irrelevant to Mewtwo.
- **`附着针`, `屏障`, `波导弹`:** Offered and passed over; `屏障` and `波导弹` were rejected in favor of primary Psychic moves.

### 3.4 Non-Card Player Actions
- **Selling (`v`):** Never used (0 times). The player collected every single item dropped.
- **Rerolling (`f`):** Used all 8 available refreshes across levels 2, 3, 27 (×2), 30, 62, 86, and 109 to dig for missing moves or core vitamins.
- **Skipping (`x`):** Used 6 times (levels 4, 70, 79, 100, 110, 114) when all offered cards were either unwanted or redundant.
- **Banishing (`z`):** Used all 7 banishes at Level 113 to purge the pool of low-value vitamins (`防御增强剂`, `攻击增强剂`, `谜芝果`, `命中强化`, `好伤药`, `机变骰子`, `ＨＰ增强剂`).
- **Hypno Move Forgetting:** Used 3 times to prune physical/unwanted moves.

### 3.5 Other Popups Behavior
- **Fossil Ruins (`化石遗迹`):** Picked `甲壳化石` (Kabuto Fossil / Blessing) 3 out of 3 times over items and partners.
- **Fossil Blessing (`甲壳化石的远古祝福`):** Prioritized `+38% 伤害` (Damage) twice and `+47% 经验` (XP) once over HP and range.
- **Ditto (`百变怪`):** Cloned `ＰＰ多项全补剂` twice early to supercharge party-wide attack speed, and `月之石` once late for `+2 Projectiles` and `+25% Range`.
- **Chest Items (`你发现了道具！`):** 100% focused on Special Attack scalers (`讲究眼镜`), projectile additions (`月之石`, `ＰＰ极限提升剂`), massive stat multipliers (`觉醒之石`, `神奇糖果`, `金刚宝珠`, `暗之石`), and game-acceleration items (`白色玻璃哨`, `秘密钥匙`).

---

## 4. Proposed Configuration (`autobonk.toml`)

Here is the complete replacement `[cards]` configuration organized into clear strategic tiers:

```toml
[cards]
# How choice popups are answered: level-up, item choice, fossil ruins/blessing, Porygon, Snorlax, Ditto.
# Card names exactly as the game shows them (copy them from the log). Positive weight = prefer,
# negative = avoid, unlisted = 0. The highest weight wins; equal weights fall back to rarity, then
# the leftmost card. So any positive weight beats any unlisted card, whatever its rarity.
# Refresh (F), Skip (X) and Banish (Z) are never used.

# Best first. Anything not listed ranks below all of these.
# 招式 (New move) ranks highest so newly offered core moves are immediately learned.
# 史诗 (Epic) is included to match the game's 5-tier standard rarity hierarchy.
rarity_order = ["招式", "传说", "史诗", "稀有", "少见", "普通"]

# Tuned from player's recorded run (logs/choices.jsonl) with Mewtwo (超梦).
# Focuses on Special Psychic burst moves, spell vamp/luck/haste vitamins, and high-value relics.
[cards.weights]
# Tier 1: Game-defining build enablers and relics
"月之石" = 10
"甲壳化石" = 10

# Tier 2: Core special moves and essential vitamins (equal weight; rarity breaks ties)
"精神击破" = 9
"棱镜镭射" = 9
"精神突进" = 9
"幻象光线" = 9
"广域战力" = 9
"基因霸权" = 9
"全满药" = 9
"星星碎片" = 9
"ＰＰ单项小补剂" = 9
"ＰＰ多项全补剂" = 9
"讲究眼镜" = 9

# Tier 3: Damage blessings and high-tier stat bonuses
"+38% 伤害" = 8
"+21% 伤害" = 8
"+14% 伤害" = 8
"伤害" = 8
"+22 幸运" = 8
"+22% 经验" = 8
"+21% 攻击速度" = 8
"+18% 攻击速度" = 8
"+14% 速度" = 8
"+8% 速度" = 8

# Tier 4: High-value chest items and secondary blessings
"觉醒之石" = 7
"神奇糖果" = 7
"金刚宝珠" = 7
"暗之石" = 7
"ＰＰ极限提升剂" = 7
"活力碎片" = 7
"+47% 经验" = 7
"+26% 经验" = 7
"+15 幸运" = 7
"+17% 范围" = 7
"+14% 范围" = 7
"+10% 速度" = 7

# Tier 5: Useful utility chest items
"白色玻璃哨" = 6
"秘密钥匙" = 6

# Tier 6: Early game / transitional moves and secondary stats
"精神利刃" = 5
"特攻增强剂" = 5

# Tier 7: Late-game difficulty & XP scaling
"诅咒薰香" = 4

# Avoid: Traps, unwanted physical/defensive moves, and rejected altar trade-offs
"星星沙子" = -5
"精神扭曲" = -5
"贝壳化石" = -5
"秘密琥珀" = -5
"附着针" = -5
"屏障" = -5
"波导弹" = -5
```

---

## 5. Agreement Measurement & Miss Analysis

### 5.1 Agreement Summary

| Metric | Old Starter Weights | Proposed Weights | Improvement |
| :--- | :---: | :---: | :---: |
| **Card Decisions Agreement** | **41.8%** (61 / 146) | **85.6%** (125 / 146) | **+43.8%** |
| **All Decisions Agreement** (incl. skips/leaves) | **39.4%** (61 / 155) | **80.6%** (125 / 155) | **+41.2%** |

### 5.2 Agreement Breakdown by Popup Type

| Popup Type | Total Card Decisions | Proposed Matches | Match Rate | Misses |
| :--- | :---: | :---: | :---: | :---: |
| **你发现了道具！** (Chest choice) | 13 | 13 | **100.0%** | 0 |
| **卡比兽的祝福** (Snorlax blessing) | 5 | 5 | **100.0%** | 0 |
| **未知图腾祭坛** (Rune altar) | 4 | 4 | **100.0%** | 0 |
| **化石遗迹** (Fossil ruins) | 3 | 3 | **100.0%** | 0 |
| **甲壳化石的远古祝福** (Fossil blessing)| 3 | 3 | **100.0%** | 0 |
| **百变怪** (Ditto item clone) | 3 | 3 | **100.0%** | 0 |
| **稀有未知图腾祭坛** (Rare altar) | 2 | 2 | **100.0%** | 0 |
| **多边兽祭坛** (Porygon altar) | 1 | 1 | **100.0%** | 0 |
| **史诗未知图腾祭坛** (Epic altar) | 1 | 1 | **100.0%** | 0 |
| **霸主光环** (Overlord aura) | 1 | 1 | **100.0%** | 0 |
| **正辉的机器** (Fusion machine) | 1 | 1 | **100.0%** | 0 |
| **等级提升** (Level-up) | 109 | 88 | **80.7%** | 21 |
| **Total Card Decisions** | **146** | **125** | **85.6%** | **21** |

*(If including the 9 non-card actions, total decisions = 155, matches = 125, agreement = 80.6%. The 9 non-card misses are 6 level-up skips, 2 Porygon altar exits, and 1 fusion exit).*

---

### 5.3 Detailed Categorization of the 21 Level-Up Misses

All 21 misses occurred within `等级提升` and fall into three distinct structural patterns:

#### Group 1: Equal-Score Ties Broken by Leftmost Card (10 misses)
When multiple core moves and core vitamins share Tier 9 and identical rarity, the scorer breaks the tie in favor of the leftmost card (`max` preserves the first equal item). The player chose a card located further to the right:
1. **Lv 9:** Offered `['精神击破(稀有)', '星星碎片(稀有)', '全满药(稀有)', '好伤药(普通)']`. Bot chose card 1 (`精神击破`); player picked card 2 (`星星碎片`).
2. **Lv 11:** Offered `['精神击破(少见)', '星星碎片(少见)', '机变骰子(普通)', '谜芝果(稀有)']`. Bot chose card 1 (`精神击破`); player picked card 2 (`星星碎片`).
3. **Lv 12:** Offered `['精神击破(少见)', 'ＰＰ单项小补剂(少见)', '全满药(少见)', '速度增强剂(普通)']`. Bot chose card 1 (`精神击破`); player picked card 2 (`ＰＰ单项小补剂`).
4. **Lv 28:** Offered `['精神突进(普通)', '经验糖果(普通)', '精神击破(普通)', '星星碎片(普通)']`. Bot chose card 1 (`精神突进`); player picked card 4 (`星星碎片`).
5. **Lv 38:** Offered `['幻象光线(普通)', '精神突进(普通)', '全满药(史诗)', '星星碎片(史诗)']`. Bot chose card 3 (`全满药`); player picked card 4 (`星星碎片`).
6. **Lv 44:** Offered `['棱镜镭射(稀有)', '精神突进(稀有)', 'ＰＰ单项小补剂(稀有)', '幻象光线(稀有)']`. Bot chose card 1 (`棱镜镭射`); player picked card 3 (`ＰＰ单项小补剂`).
7. **Lv 50:** Offered `['幻象光线(稀有)', 'ＰＰ单项小补剂(普通)', '全满药(稀有)', '特攻增强剂(普通)']`. Bot chose card 1 (`幻象光线`); player picked card 3 (`全满药`).
8. **Lv 64:** Offered `['精神击破(史诗)', '精神突进(少见)', 'ＰＰ单项小补剂(少见)', '星星碎片(史诗)']`. Bot chose card 1 (`精神击破`); player picked card 4 (`星星碎片`).
9. **Lv 71:** Offered `['幻象光线(史诗)', '星星碎片(史诗)', '精神击破(史诗)', 'ＰＰ单项小补剂(稀有)']`. Bot chose card 1 (`幻象光线`); player picked card 2 (`星星碎片`).
10. **Lv 98:** Offered `['棱镜镭射(少见)', '广域战力(传说)', '基因霸权(传说)', '幻象光线(稀有)']`. Bot chose card 2 (`广域战力`); player picked card 3 (`基因霸权`).

#### Group 2: Run-State Move Level Balancing (7 misses)
The player picked a lower-rarity card because that specific move or vitamin was lagging behind in level and needed leveling up, while the higher-rarity offer was already near max level:
1. **Lv 34:** Offered `['精神突进(普通)', '星星沙子(少见)', 'ＰＰ单项小补剂(少见)', '棱镜镭射(少见)']`. Bot picked `ＰＰ单项小补剂(少见)`; player leveled up the newly learned `精神突进` (Lv 1 -> 2).
2. **Lv 37:** Offered `['幻象光线(少见)', 'ＰＰ单项小补剂(少见)', '精神击破(稀有)', '星星沙子(稀有)']`. Bot picked `精神击破(稀有)`; player leveled up newly learned `幻象光线` (Lv 1 -> 2).
3. **Lv 45:** Offered `['精神突进(少见)', '幻象光线(稀有)', '特攻增强剂(史诗)', 'ＰＰ单项小补剂(稀有)']`. Bot picked `幻象光线(稀有)`; player caught up `精神突进`.
4. **Lv 47:** Offered `['棱镜镭射(少见)', '星星沙子(史诗)', '全满药(普通)', '精神突进(稀有)']`. Bot picked `精神突进(稀有)`; player leveled up `棱镜镭射`.
5. **Lv 49:** Offered `['精神击破(普通)', '特攻增强剂(史诗)', '棱镜镭射(少见)', '精神突进(稀有)']`. Bot picked `精神突进(稀有)`; player leveled up `精神击破`.
6. **Lv 68:** Offered `['精神击破(少见)', 'ＰＰ单项小补剂(史诗)', '特攻增强剂(史诗)', '星星碎片(稀有)']`. Bot picked `ＰＰ单项小补剂(史诗)` (already Lv 7); player leveled `精神击破` (Lv 6 -> 7).
7. **Lv 75:** Offered `['精神突进(少见)', '精神击破(史诗)', '幻象光线(稀有)', 'ＰＰ单项小补剂(史诗)']`. Bot picked `精神击破(史诗)` (already Lv 7); player leveled `ＰＰ单项小补剂` (Lv 8 -> 9).

#### Group 3: Move Lifecycle & Hypno Forgetting History (4 misses)
- **Lv 15, 16, 19:** `精神利刃` was Mewtwo's starting move and was leveled up in early game (picked over `全满药` and `ＰＰ单项小补剂`).
- **Lv 30:** At Lv 21, the player forgot `精神利刃` at Hypno. When `精神利刃(招式)` reappeared at Lv 30, the player rejected it in favor of `特攻增强剂(少见)`.
- A static weight table cannot know that a card was desirable before Lv 20 but undesirable after being forgotten at Hypno. Setting `精神利刃` to Tier 5 correctly captures its transitional nature while avoiding taking it over core endgame items.

---

## 6. What Weights Can't Express

Static `(weight, rarity rank)` scoring assumes choices are context-free and stationary throughout an entire run. In actual gameplay, 5 clear contextual dynamics cannot be represented by weights alone:

### 1. Move Level Balancing & Level Caps (7 occurrences in log)
- **Game Reality:** Moves cap at Lv 8 and vitamins cap at Lv 10. A player balances upgrades across active moves rather than pumping one move to Lv 8 while another sits at Lv 1.
- **Limitation:** Static weights evaluate a Lv 7 card identically to a Lv 1 card.
- **Bot Rule to Capture:** In `CardPrefs`, dynamically discount the score of cards that are near max level, or add a bonus `+ (8 - current_level)` to prioritize lower-level active moves.

### 2. Move Lifecycle & Forgetting History (4 occurrences in log)
- **Game Reality:** A physical starting move (`精神利刃`) is useful in the first 20 levels, but once replaced with Special moves at Hypno, it should never be re-learned.
- **Limitation:** Static weights must choose a single global value for `精神利刃`.
- **Bot Rule to Capture:** Maintain an active move inventory `state.moves`. Once 4 move slots are filled, ignore cards with rarity `招式`. If a move is forgotten, add it to an in-memory `forgotten_moves` blacklist.

### 3. Phase-Dependent Scaling Items (`诅咒薰香`) (9 occurrences in log)
- **Game Reality:** `诅咒薰香` increases enemy difficulty and spawn density in exchange for bonus XP/coins. Early on, taking it causes deaths; in late game (Lv 115+), an overpowered build wants higher density.
- **Limitation:** In static weights, `诅咒薰香 = 4` means it ranks below Tier 9 moves/vitamins, which safely prevents picking it early, but cannot represent the transition to actively farming it late game.
- **Bot Rule to Capture:** Dynamic weight scaling based on player level: `weight = -5 if level < 100 else 8`.

### 4. Strategic Non-Card Actions: Skips, Rerolls, and Banishes (21 occurrences in log)
- **Game Reality:** The player rerolled 8 times, skipped 6 times, and banished 7 items at Lv 113 to purge the item pool.
- **Limitation:** The bot currently never uses F, X, or Z; it always picks the best card offered.
- **Bot Rule to Capture:** If the highest-scoring card in a level-up has a non-positive score (e.g. `<= 0`) and remaining rerolls/skips > 0, press `F` (Refresh) or `X` (Skip). When a banish token is available, press `Z` to remove cards with weight `< 0` from the pool.

### 5. Altar Trade-Off Penalties (2 occurrences in log)
- **Game Reality:** At the Porygon Altar (`多边兽祭坛`), cards involve stat trade-offs (e.g., sacrifice armor for speed). The player exited twice (`以后再说` / Esc) when offered unwanted penalties.
- **Limitation:** The bot currently picks the highest-weight card if any card is keyed.
- **Bot Rule to Capture:** If all offered trade-offs at Porygon reduce critical primary stats (like Special Attack or Speed), press `Escape` (`以后再说`).
