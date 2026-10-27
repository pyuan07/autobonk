# autobonk

PokéBonk autopilot. See `.scratch/v1-autopilot/spec.md` for the plan.

## Setup

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

Uses your installed Google Chrome (no `playwright install` needed).

## Run

```sh
.venv/Scripts/python -m autobonk            # or: .venv/Scripts/autobonk
```

Opens Chrome on https://pokebonk.com/ at a 1600×900 viewport with its own profile in `profile/`.
Log in once; the login persists there. Settings live in `autobonk.toml`.

Global hotkeys (work while another app is focused):

- **F9** saves a frame to `fixtures/frames/`: `frame-<time>.png` (screenshot), `.html` (DOM), `.json` (timestamp, URL).
- **F8** toggles paused/running and releases every held key. Starts paused.

The game keeps running while the window is unfocused or covered, but **don't minimize it**:
Chrome stops rendering minimized windows.

## Test

```sh
.venv/Scripts/python -m pytest
```
