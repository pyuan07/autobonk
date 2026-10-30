# Spike findings (ticket 02), 2026-10-28

One full run (win), 32 frames in `fixtures/frames/`, game build v0.8.60, 1600×900.

## DOM vs canvas

| UI | Where | Notes |
|---|---|---|
| Cards / choice popups | **DOM** | Title, rarity (普通/少见/稀有/传说…), name, description, key `[1]`–`[4]` all present as text |
| Countdown timer | **DOM** | e.g. `9:34`; resets to ~9:50 on each new zone |
| Zone index | **DOM** | `区域 1/3` … `区域 3/3`; sanctuary shows the sanctuary name (`雷鸣角`) instead |
| Banners | **DOM** | `守护者已被击败！` + `通往下一区域的传送门已打开`; final: `传说宝可梦已被击败！` + `进入传送门以通关地图` |
| E prompts | **DOM** | Text right after an `E` key cap: `进入传送门`, `触碰圣地`, `唤醒守护者`, `离开圣地`, `碎岩`, `打开精灵球 · 16 ₽` … |
| Progress bubble | **DOM** | Plain `NN%` text (rune altar 35–37%, ore pile 90%/20%) |
| End screen | **DOM** | `胜利！` plus stats. Lose screen not yet recorded |
| Minimap | **canvas** | `<canvas class="minimap" width=400 height=400>`, rotates with camera, has 北/南/东/西 rim markers |
| Tab zone map | **canvas** | Extra `<canvas class="bm-cv" 738×738>` appears only while Tab is held; north-up with 北/南/东/西 |
| 3D world | **canvas** | `<canvas id="game" data-engine="three.js r186">` |

**Hidden elements stay in the DOM.** Banners, popups and pills are toggled with inline
`style="display: none;"` (e.g. `喵喵来访`, `围困！快移动` are in every frame). Perception must
skip any element with a `display: none` ancestor. Some may be hidden by CSS classes or media
queries (`请旋转你的设备` is in every frame), so if inline-style filtering proves leaky, the
recorder should also save visibility-aware text (`innerText`) per frame.

## Answers to open facts

- **Top-down camera persists between runs:** yes (user).
- **Tab during play:** shows the floating zone map overlay (user; frame `022817-887`).
- **Portal spawn:** near where the guardian dies (user). Prompt `E 进入传送门` appears with the banner.
- **New fact: the final boss doesn't end the run.** After `传说宝可梦已被击败！` the player must
  enter a portal (`进入传送门以通关地图`); the prompt becomes `E 离开圣地`, and only then does `胜利！`
  show. Ticket 09's sanctuary routine needs this extra step.
- **New popup types seen:** fossil ruins (`化石遗迹`, choices `[1]`–`[3]` + `以后再说 Esc`), fossil
  blessing (`甲壳化石的远古祝福`, `[1]`–`[3]`), Porygon altar (`多边兽祭坛`, `[1]`–`[3]` + Esc),
  shop (`喵喵`, `离开 Esc`), slot machine (`火箭队赌场`, `离开 E`), fusion machine (`正辉的机器`).
  Ditto (`百变怪：我复制哪件道具？`) lists items **without** `[n]` keys, plus `以后再说`.
- **Screenshot and DOM are captured ~100 ms apart** (rune bubble 35% in PNG vs 37% in HTML). Fine
  for fixtures; keep in mind for exact-match tests.

## Frame index

| Frame | Shows |
|---|---|
| 021610-030 | Item pickup `你发现了一件道具！` (锐利之爪, 拾取 E / 出售 V) |
| 021725-506 | Rune altar in progress (35%), minimap with icons (not top-down) |
| 021742-082 | Fossil ruins popup |
| 021748-698 | Fossil blessing popup (3× 传说) |
| 021758-119 | `E 唤醒守护者` prompt, zone 1 |
| 021816-856 | Item pickup (白色玻璃哨), free pokéball prompt |
| 021833-196 | Level-up `等级 2！` (4 cards, 刷新/跳过/放逐) |
| 021847-879 | Item choice `你发现了道具！` (3 items + `无`) |
| 021944-020 | Meowth shop |
| 022011-249 | Porygon altar popup |
| 022025-333 | Item pickup from curse altar (Bicycle, 稀有) |
| 022033-536 | Slot machine |
| 022059-218 | Fusion machine |
| 022106-745 | Ditto copy popup |
| 022218-807 | Support-boss joined banner, berry prompt |
| 022221-064 | Level-up `等级 19！` (upgrade card 强化) |
| 022229-633 | `E 进入传送门`, zone 1 |
| 022315-480 | Zone 2 start (timer reset 9:50), ore pile 20% |
| 022353-323 | Zone 2 guardian `暴鲤龙` woken |
| 022358-494 | Zone 2 guardian fight |
| 022445-954 | Hypno forget popup (`就绪`) |
| 022456-714 | Item choice (paid pokéball) |
| 022542-352 | `守护者已被击败！` banner + `E 进入传送门` |
| 022620-908 | Zone 3 guardian `电击兽` |
| 022814-797 | Sanctuary `E 触碰圣地` |
| 022817-887 | Tab held in sanctuary (floating map) |
| 022828-598 | Final boss phase 1/3 |
| 022902-715 | Final boss phase 2/3 |
| 022929-215 | Final boss phase 3/3 |
| 022959-972 | `传说宝可梦已被击败！` banner |
| 023007-101 | `E 离开圣地` after final boss |
| 023009-523 | Win screen `胜利！` |

## Still missing

- Lose screen (`你倒下了！`)
- Snorlax blessing (`卡比兽的祝福`), if it appears
- Tab held in a normal zone (only the sanctuary map was captured)
- A top-down frame with several icon types on the minimap
- Icon reference crops at 1600×900 for the taxonomy

## Minimap facts (user, 2026-10-30)

- The minimap rotates with the camera, but **W always moves toward minimap-up** (so minimap steering needs no heading).
- **Red dot = enemy, yellow dot = elite enemy.**
- The Tab zone map is north-up and does not rotate; it shows far more icons than the minimap.
- The camera turns only when the player drags left/right; the bot never drags, so the heading is fixed for a run.
  Read it from the minimap's 北 rim marker to map Tab-map (north-up) directions onto WASD.
- Holding Tab keeps the game running (you can move and be hit) and the minimap stays visible; the map shows only while held.
