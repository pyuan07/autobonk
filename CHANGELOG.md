# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.1] - 2026-10-31

### Fixed
- **Sanctuary Entrance & Boss Phase Protection (圣地入场与Boss阶段判定保护)**:
  - Fixed a bug where lingering victory banners (e.g. "守护者已被击败！") or exit portals from Zone 3 caused the bot to immediately mark the Sanctuary Boss as `BEATEN` upon entering `森林圣地`.
  - Prevented premature transition to `BEATEN` in sanctuary when `boss_phase == BossPhase.WAITING`: the bot now strictly targets the central sanctuary altar (`ALTAR` with `math.inf` weight) to summon the final boss before expecting victory conditions.
  - Added a 5-second zone entry cooldown (`zone_entered_at`) in `ZoneTracker` to ignore residual defeat banners and portals during scene transitions.
- **In-View Sanctuary Exit Portal Perception (视野内圣地传送门感知与通关交互)**:
  - Enhanced `_portal()` in `dom.py` to parse on-screen marker tags (`.compass.mktag`) when the edge compass (`.compass[data-k="portal"]`) is hidden (`display: none`) due to the portal being in camera view.
  - Calculated exact in-world relative coordinates from `.compass.mktag` to player center.
  - Resolves the issue where defeating the final boss left the bot stranded 9 meters away from the exit portal without pressing `[E] 离开圣地` to complete the run.

---

## [0.3.0] - 2026-10-31

### Added
- **Wayside Sub-Target Navigation (顺路途经目标机制)**:
  - Added `find_sub_target` to `TargetSelector` calculating detour penalty:
    $$\Delta d = d_{\text{player}} + d_{\text{sub\_main}} - d_{\text{main}}$$
  - Dynamic detour tolerance based on item importance: $\Delta d_{\max} = 12.0\text{px} + 3.0 \times \text{Weight}$.
  - Supports instant pickups (Super Ball, Gift Ball, Pokéball, Coin, Bonk Coin) along the path toward distant objectives (such as Altars or Bosses).
  - Works seamlessly while holding `Tab` in Zonemap mode and in Minimap mode without releasing or canceling the main objective.
  - Automatically clears sub-target upon successful collection or timeout, instantly resuming course to the main target.
  - Added `main_target`, `sub_target`, and `sub_target_distance` telemetry across `BotStatus`, `DashboardHub`, and `Controller`.
- **Dedicated Live Dashboard & Multi-View UI (独立运行仪表盘与三栏导航)**:
  - Created modern `dashboard_ui.html` served at root (`/`) focusing entirely on bot operation and live telemetry.
  - **Dual Target Tracking Card**: Visually separates Strategic Main Target from Wayside Sub-Target with real-time distance and "★ 顺手拾取中" status badges.
  - **Operation Banner**: Large one-click Start/Pause toggle button and clear status indication (`● 运行中` / `⏸ 已暂停`).
  - **Live Decision Log**: Full-width live scrolling console highlighting target switches, boss phases, and wayside pickups.
  - Unified responsive topbar navigation across all views: `[ 📊 运行仪表盘 ]` (`/`), `[ 🎴 卡牌权重配置 ]` (`/cards`), and `[ 🎯 地图目标设置 ]` (`/targets`).

### Changed
- Refactored web server routing in `server.py` to serve `/` (Dashboard), `/cards` (Cards editor), and `/targets` (Map targets).
- Added comprehensive unit tests in `tests/test_bot.py` verifying en-route sub-target selection and backtracking rejection.

### Fixed
- **Premature Altar Abandonment (修复祭坛开到一半跑掉的问题)**:
  - Fixed level-up/card-choice popups mid-charge triggering an erroneous 60-second altar blacklist and target clearance; the bot now firmly preserves `_charging_since` and maintains `current_target = ALTAR` across popup choice dialogs.
  - Added monster knockback recovery and debounce: if knocked out of the charging circle (within 35px), the bot steers back into the altar ring instead of falsely declaring charge completion and abandoning the altar.
  - Disabled space jumps while charging in the altar ring to prevent collision recoil and accidental ring exits.
  - Added unit tests `test_popup_during_charging_does_not_abandon_or_ignore_altar` and `test_altar_knockback_triggers_reentry_instead_of_abandoning`.

---

## [0.2.0] - 2026-10-31

### Added
- **Build Plan Recognition ("在你的计划中")**:
  - Added `in_plan: bool` property to `Card` model.
  - Automatically parses the game's `.bp-badge` element containing `在你的计划中` (or title `它在你的配置计划中`) across all card-offering popups (level-up choices, item pickups, Ditto transformations).
  - Added unit test grounded in real captured gameplay frame (`frame-20261031-140201-536`).
- **In-Plan Card Priority & Cut-in Rule**:
  - Planned cards always beat non-plan cards whose configured weight is `< 9.0` (even if the planned move has default 0 weight).
  - High-value universal picks (`weight >= 9.0`, e.g. Master Ball, Awakening Stone, Max Potion) can cut in and compete with planned cards by numerical score `(weight, rarity)`.
  - Multiple planned cards in the same choice resolve by `weight > rarity`, falling back to leftmost card on ties.
- **Banish Protection**:
  - Cards marked `in_plan == True` are strictly immune to banishment, even if assigned negative weights.
- **Configurable Plan Fallback Reroll**:
  - Added `plan_fallback_reroll_threshold` (default `7.0`) under `[cards]` in `autobonk.toml`.
  - When no planned cards appear in an offer, the bot automatically rerolls if the best card offered has weight `< 7.0` (and `rerolls > 0`).
  - When rerolls are exhausted (`rerolls == 0`), skips are preserved for true negative/penalty cards (`weight < 0.0`) instead of being wasted on positive cards below 7.
- **Weight Cap of 10.0**:
  - Enforced a hard upper limit of `10.0` for card weights across `config.py` loading, `toml_store.py` persistence, and the Web Dashboard UI (`editor_ui.html`).

### Changed
- Modular package restructuring: split monolithic modules into domain-focused subpackages (`perception/`, `policy/`, `runtime/`, `dashboard/`).

### Fixed
- Fixed circular import between `autobonk.perception.dom` and `autobonk.runtime.frames` by using `from __future__ import annotations` and `TYPE_CHECKING`.

---

## [0.1.2] - 2026-10-31

### Added
- Zone map navigation with proximity bonus distance factor (`distance_factor = 0.2`).
- Area boss summoning logic: summon boss (骷髅) once level or overtime timer threshold is met.
- Post-boss portal navigation and unopened super balls pickup.
- Web dashboard hub with state monitoring and dynamic hot-reload for `autobonk.toml`.

---

## [0.1.1] - 2026-10-30

### Added
- Rune altar charging timeout (`altar_charge_cap_s`) and sealed altar handling.
- Anti-stuck detection with random sidestepping (`stuck_s`, `sidestep_s`).
- Web UI card weight editor with stat blessing compaction and per-Pokémon profiles.
- Automatic team view closing with `Tab` when opened over popups.

---

## [0.1.0] - 2026-10-28

### Added
- Core autopilot bot loop with game win/loss screen detection and pause controls.
- Raw Chrome DevTools Protocol (CDP) screencasting and non-intrusive headless capture.
- Automated choice popup answering by configured card weights, rarity fallbacks, and player choice logger.
- Frame recorder triggered by hotkey (`F9`) saving screenshot, minimap canvas, and DOM snapshots.
