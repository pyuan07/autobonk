# autobonk

PokéBonk autopilot and dashboard assistant.

## Features

- **Automated gameplay:** Top-down navigation, rune altar charging, boss summoning, super-ball prioritization, portal navigation, and random jump evasions.
- **Card & popup policy:** Automatic level-up choice scoring, banish/reroll/skip thresholds, item pickups, Ditto clones, and Hypno move management.
- **Web Dashboard & Editor:** Real-time bot status, live telemetry, interactive card weight editor (`/`), and map target priority manager (`/targets`) at `http://localhost:8080`.
- **Background operation:** Custom browser flags and visibility scripts keep the game ticking even when the window is covered or unfocused.

## Setup

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

Uses your installed Google Chrome (no extra `playwright install` needed).

## Run

```sh
.venv/Scripts/python -m autobonk --open-dashboard
```

Or double-click `run.bat` to launch Chrome and open the Web Dashboard automatically.

Opens Chrome on `https://pokebonk.com/` at a 1600×900 viewport with its dedicated profile in `profile/`. Log in once; the session persists there. Settings live in `autobonk.toml`.

### Global Hotkeys (work while another app is focused)

- **F8**: Toggle paused / running and release all held keys (starts paused).
- **F9**: Save the current frame (`.png` screenshot, `.html` DOM snapshot, `.json` metadata, and map canvases) to `fixtures/frames/`.

*Note: The game continues running while unfocused or covered, but **do not minimize** the Chrome window (Chrome stops rendering minimized windows).*

## Architecture

For an in-depth breakdown of all internal mechanics, perception pipelines, state machines, math models, and edge-case handling (in Chinese), see [DETAILS.md](file:///e:/Projects/autobonk/DETAILS.md).

```
autobonk/
├── commands.py          # Command primitives (Press, Hold, Click, ReleaseAll, Stop, Pause)
├── game.py              # Game constants, target names, HUD strings, BossRule
├── config.py            # TOML configuration parser and dataclass
├── app.py               # Main runtime orchestrator
├── perception/          # Vision and DOM perception
│   ├── matching.py      # FFT template matching & spectra cache
│   ├── minimap.py       # Altar and north marker detection
│   ├── zonemap.py       # Full-zone Tab map reader
│   ├── icons.py         # Catalog icon detection
│   └── dom.py           # DOM HUD and popup parser
├── policy/              # Decision-making and state machine
│   ├── bot.py           # Main Bot coordinator (exposes .status)
│   ├── popups.py        # Card, banish, reroll, skip, and modal policy
│   ├── targets.py       # Dynamic weights, proximity scoring, and hysteresis
│   ├── navigation.py    # WASD steering, unstuck recovery, and jumping
│   ├── zone.py          # Zone visited-grid and boss lifecycle
│   └── cards.py         # Card preferences and stat blessing parser
├── runtime/             # System integration
│   ├── controller.py    # Event queue and bot execution loop
│   ├── driver.py        # Playwright keyboard/mouse driver
│   ├── browser.py       # Chrome persistent launcher
│   ├── frames.py        # Frame capture and recording
│   ├── hotkeys.py       # Global OS hotkey listener
│   └── choices.py       # Player choice observation logger
└── dashboard/           # Local web server and live hub
    ├── hub.py           # Thread-safe telemetry state hub
    ├── server.py        # HTTP handler and REST API
    ├── toml_store.py    # Config reading and writing
    └── editor.py        # Standalone editor CLI
```

## Testing & Type Checking

```sh
.venv/Scripts/python -m pytest
.venv/Scripts/python -m mypy autobonk
```
