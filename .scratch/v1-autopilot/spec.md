Status: ready-for-agent

# Spec: PokéBonk Autopilot v1 — play one full run unattended

## Problem Statement

I play PokéBonk (https://pokebonk.com/, a three.js browser roguelike with a login and an online seasonal leaderboard). A run is long and repetitive: walk around a zone, touch altars and event objects, pick an upgrade card every level-up, kill the zone guardian before the countdown runs out, go through the portal, repeat for three zones, then trigger the final boss at the sanctuary. My daily missions are mostly "play N runs". I want a helper that plays a run for me while I use the PC for other things (or watch on a second monitor), without me having to keep the game focused or sit and press keys.

## Solution

A Python helper that opens my installed Chrome (with a dedicated profile I log into once) on PokéBonk at a fixed window size. I start a run myself, set the camera top-down, and press F8. From then on the helper plays the run: it picks cards in every choice popup by my configured priorities, walks toward the most valuable nearby map icons and presses E on them, stands in rune altar rings until they complete, explores unvisited parts of the zone when nothing is visible, goes for the guardian when 3:00 remain, enters the portal, and in the final sanctuary presses E to start the final boss. It jumps randomly the whole time. When the run ends (win or lose) it releases all keys and stops. F8 pauses/resumes at any time, and it pauses itself if it can't understand the screen.

## User Stories

### Setup and control
1. As a player, I want the helper to launch my installed Chrome with a dedicated profile, so that my real browser is untouched and I only log in once.
2. As a player, I want my login and game save to persist between helper sessions, so that I never have to log in again.
3. As a player, I want the game window to have a fixed size (1600×900), so that screen layout is consistent for recognition.
4. As a player, I want the game to keep running at full speed when the window is unfocused or covered, so that I can use the PC for other things while it plays.
5. As a player, I want to start the run myself (choose character, press start) and then hand over with F8, so that v1 does not need to automate menus.
6. As a player, I want to set the camera to a top-down angle myself before handing over, so that the helper never has to move the mouse.
7. As a player, I want F8 to pause the helper and immediately release every held key, so that I can take control instantly.
8. As a player, I want F8 again to resume from the current state, so that I can intervene briefly without restarting.
9. As a player, I want the helper to pause itself if it cannot recognise the screen for about 5 seconds, so that it never runs blind.
10. As a player, I want the helper to stop and release all keys when the win (胜利!) or lose (你倒下了!) screen appears, so that a finished run is left alone.
11. As a player, I want a readable console log of what the helper sees and decides (state, target, chosen card), so that I can understand and tune its behaviour.
12. As a player, I want strategy (card weights, icon tiers, timings) in an editable config file, so that I can change builds without touching code.

### Choice popups
13. As a player, I want every level-up popup (等级 N!, four cards with [1]–[4]) to be answered by the best-scoring card, so that my build follows my priorities.
14. As a player, I want cards scored by a weighted list of card names exactly as shown in the game (Chinese), so that I can express preferences directly.
15. As a player, I want unlisted cards to fall back to highest rarity, then the leftmost card, so that a choice is always made.
16. As a player, I want the helper never to use Refresh (F), Skip (X) or Banish (Z), so that limited resources are not wasted in v1.
17. As a player, I want the item-choice popup (你发现了道具!) handled by the same scoring, so that I get useful items.
18. As a player, I want Snorlax's blessing popup (卡比兽的祝福) handled by the same scoring, so that blessings match my build.
19. As a player, I want Ditto's copy-an-item popup handled by the same scoring, so that the best item gets copied.
20. As a player, I want the single-item pickup popup (你发现了一件道具!) always answered with E (pick up), so that items are never sold by accident.
21. As a player, I want Hypno's forget-a-move popup (引梦貘人) closed with 就绪 without forgetting anything, so that my moves are never lost.
22. As a player, I want an unknown popup that shows [1]-style choices to be answered with 1, so that new popup types don't block the run.
23. As a player, I want any other unrecognised modal to pause the helper, so that it doesn't press random keys in unknown UI.
24. As a player, I want the helper to stop moving while a popup is open, so that it doesn't walk into danger when the game resumes.

### Navigation and targets
25. As a player, I want the helper to steer using the always-visible corner minimap (player at centre, rotates with the camera so up = W), so that it can navigate without opening menus.
26. As a player, I want the helper to hold the right combination of W/A/S/D (including diagonals) toward the target, so that movement is direct.
27. As a player, I want targets chosen by tier and then by distance, so that valuable things come first without crossing the whole map for them.
28. As a player, I want tier 1 to be Snorlax, fossil ruins, free pokéball and the purple bomb icon, so that the most valuable events are taken first.
29. As a player, I want tier 2 to be ore piles, rune altars and challenge altars, plus Ditto and magnet only once 5:00 or less remain, so that mid-value targets are taken in order.
30. As a player, I want tier 3 to be curse altars and Porygon altars, only when tiers 1–2 have nothing visible, so that low-value targets fill idle time.
31. As a player, I want a tier-2 target preferred over a tier-1 target that is more than about 3× farther away, so that the helper doesn't run across the map.
32. As a player, I want pokéballs, cages, Gengar, shop, slot machine, mushrooms, berries, Rhyhorn, Hypno and the fusion machine ignored as targets in v1, so that the helper doesn't spend money or trigger unwanted effects.
33. As a player, I want the helper to press E on arriving at a target, so that the event triggers.
34. As a player, I want the helper to stay inside a rune altar's ring until it reaches 100% (the progress bubble disappears), with a 45-second cap, so that I get the blessing.
35. As a player, I want a target considered done when its icon disappears from the minimap, so that the helper moves on.
36. As a player, I want the helper to explore when no target is visible, because icons only appear when the player is close.
37. As a player, I want exploration to periodically hold Tab to see the floating zone map, read my absolute position, and mark an 8×8 grid of visited cells, so that it explores new ground instead of circling.
38. As a player, I want exploration to head to the nearest unvisited cell (preferring cells away from the map edge), so that coverage grows efficiently.
39. As a player, I want exploration to head toward an already-discovered wanted icon on the zone map when one exists beyond minimap range, so that known targets are not forgotten.
40. As a player, I want the helper to convert north-up zone-map directions into camera-relative WASD using the 北 marker's position on the minimap rim, so that exploration steering is correct at any camera yaw.

### Movement and survival
41. As a player, I want the helper to jump at random intervals of 0.8–1.4 s at all times, so that it clears terrain and dodges ground attacks.
42. As a player, I want small random variation in timings, so that inputs aren't perfectly mechanical.
43. As a player, I want the helper to detect being stuck (distance to target not shrinking for 8 s), so that it doesn't run into a wall forever.
44. As a player, I want stuck recovery to jump and slide (Shift) to one side, then the other, so that it gets around obstacles.
45. As a player, I want a target that still can't be reached after recovery to be skipped for 60 s, so that the helper tries something else.

### Zone progression and bosses
46. As a player, I want the helper to drop all other targets when the countdown reaches 3:00 and head to the guardian altar (skull icon), so that the guardian is fought before the timer runs out.
47. As a player, I want the helper to keep moving and jumping near the guardian while auto-attacks do the damage, so that it survives the fight.
48. As a player, I want the helper to recognise the "守护者已被击败" banner, so that it knows the zone is cleared.
49. As a player, I want the helper to search nearby for the "E 进入传送门" prompt after the guardian dies and press E, so that it advances to the next zone.
50. As a player, I want visited-cell and skipped-target memory reset on entering a new zone, so that each zone is explored fresh.
51. As a player, I want the helper, in the final sanctuary area (森林圣地), to walk to the sanctuary and press E at the "触碰圣地" prompt, so that the final boss starts.
52. As a player, I want the helper to keep moving and jumping during the final boss until the win or lose screen appears, so that the run completes.

## Implementation Decisions

- **Language/stack:** Python. Playwright drives the user's installed Chrome (channel "chrome") via a persistent context in a dedicated profile folder; viewport fixed at 1600×900. OpenCV + NumPy for minimap/zone-map icon detection. OCR (e.g. RapidOCR) only as a fallback for any UI that turns out to be canvas-rendered.
- **Background running:** launch flags disable background timer throttling, renderer backgrounding and Windows native occlusion calculation; an init script suppresses blur/visibilitychange so the game doesn't auto-pause.
- **Perception is DOM-first.** The 3D world is a three.js canvas, but HUD/popups (cards, timer, banners, E prompts, win/lose screens, zone-map legend) are expected to be HTML overlays. Read them from the DOM by visible text, not by brittle CSS class names, because the game is rebuilt frequently. Use pixels only for the minimap, the zone map icons, and the minimap 北 marker. The first manual spike verifies which parts are DOM.
- **Architecture: one pipeline behind one seam.** `Bot.step(frame) → commands`.
  - A **Frame** is `{screenshot, dom_snapshot, timestamp}` captured from the page.
  - **Perception** turns a Frame into an **Observation**: active popup kind + its options (name, rarity, tag, key), countdown timer, zone index / sanctuary flag, minimap icons (type, position relative to player), minimap north angle, visible E-prompt text, banners (guardian defeated), altar progress present/absent, end screen (win/lose/none), and — when Tab is held — zone-map player position and discovered icons.
  - **Policy** takes the Observation plus bot **Memory** (visited grid, skipped targets with expiry, current target and progress-watchdog, last-seen times, jump schedule) and the **Config**, and returns **Commands**: `press(key)`, `hold(keys)`, `release_all()`, `stop()`, `pause(reason)`.
  - A **Driver** executes Commands. The real driver wraps Playwright keyboard; a fake driver records commands for tests.
- **Policy priority order each step:** end screen → stop; popup → popup handler (movement released); timer ≤ 3:00 or guardian-phase/sanctuary → boss/portal routine; target visible → navigate to best target; otherwise → explore. Random jumps run alongside navigation, exploration and boss phases.
- **Card scoring:** score = configured name weight if listed, else rarity rank (少见 > 普通, extended as rarities are discovered); ties → leftmost. Same scorer for level-up, item choice, Snorlax blessing and Ditto copy.
- **Icon taxonomy** (from the zone-map legend; reference crops come from the user's screenshots): rune altar 未知图腾祭坛, guardian altar 守护者祭坛, free pokéball 免费精灵球, challenge altar 挑战祭坛, curse altar 诅咒祭坛, fossil ruins 化石遗迹, Rhyhorn 钻角犀兽的咆哮, Porygon altar 多边兽祭坛, fusion machine 正辉的机器, Meowth shop 喵喵, Ditto 百变怪, Hypno 引梦貘人, Snorlax 卡比兽, magnet 磁力, slot machine 老虎机, plus ore pile, pokéball, mushroom, berry, cage, Gengar portrait and purple bomb. Tiers and time gates live in config.
- **Steering:** the minimap rotates with the camera so minimap-up = W; target bearing → 8-way WASD with a dead-zone. Zone-map (north-up) bearings are rotated by the minimap 北 angle before mapping to WASD.
- **Exploration:** hold Tab about every 8 s for a brief peek; zone map → player cell in an 8×8 grid; mark visited; choose nearest unvisited non-edge cell.
- **Config file** (JSON or TOML, user-editable): card name weights, rarity order, icon tiers and time gates, boss trigger time (3:00), jump interval range, stuck timeout (8 s), skip duration (60 s), altar cap (45 s), Tab peek interval, unknown-screen pause timeout (5 s), hotkey (F8).
- **Hotkey:** F8 is a global OS hotkey (works while the browser is unfocused); pause releases all keys.
- **Humanization:** light randomness in jump intervals and reaction delays only.

## Testing Decisions

- **Good tests check external behaviour only:** given a recorded frame (or a short sequence of frames with timestamps), assert the commands the bot emits. Tests never assert on internal state, intermediate Observations, or private helpers, so perception and policy internals can be refactored freely.
- **Primary seam:** `Bot.step(frame) → commands`, with a fake driver/clock. Fixtures are the user's sample screenshots, plus DOM snapshots and short frame sequences recorded during the first live spike. Example cases:
  - level-up frame → press the highest-scoring card's key
  - item pickup frame → press E; forget-move frame → click 就绪
  - win / lose frame → release_all + stop
  - frame with rune altar icon up-right on minimap → hold W+D
  - countdown 2:59 with skull visible → steer toward skull even when tier-1 icons are visible
  - frame sequence with no distance progress for 8 s → recovery jump/slide, then target skipped
  - guardian-defeated banner then E-portal prompt → press E
  - unknown modal → pause
- **Secondary, only where tuning needs it:** perception-level fixture tests (e.g. "map.png yields 7 rune altars and 1 guardian altar"), still asserting observable output, not internals.
- **Not unit-tested:** the real Playwright driver, browser launch flags and the global hotkey. These are verified manually in the first spike.
- **Prior art:** none, as the repo is new. Use pytest with fixtures loaded from a samples folder.

## Out of Scope

- Starting runs from the main menu, character selection, playing N runs back-to-back, and pressing Enter to play again.
- Daily mission tracking and reward claiming.
- Spending money: pokéballs, cages, shop, slot machine.
- Escape mode based on HP or enemy density.
- Using Refresh, Skip or Banish.
- Fusion, forgetting moves, and Rhyhorn/Gengar/Hypno events as deliberate targets.
- Detecting enemies in the 3D view, and any mouse or camera control.
- Anti-cheat evasion beyond light timing randomness.

## Further Notes

- The user accepts that bot runs post scores to the seasonal leaderboard under their account.
- The game is rebuilt frequently (Vite build tag in the page head), so text-based DOM queries and config-driven icon templates are preferred over hard-coded coordinates.
- The user's sample screenshots were taken at about 2555×1270. Fixtures captured at 1600×900 during the spike will be the canonical ones, and icon templates need rescaling or recapture.
- The first implementation step should be a manual **spike**:
  - launch the browser and log in
  - confirm which UI is DOM
  - find the floating-map behaviour while Tab is held
  - check whether the top-down camera setting persists
  - record frames (screenshot + DOM) for every popup type, the win/lose screens, the portal prompt and the sanctuary prompt
- Open fact for the spike: whether the portal appears exactly where the guardian died. The current assumption is that it spawns nearby.
