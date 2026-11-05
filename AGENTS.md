## Agent skills

### Issue tracker

Local markdown in `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical five-role labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context (`GLOSSARY.md` + `docs/adr/`). See `docs/agents/domain.md`.

### Architecture

Modular layout in `autobonk/`: `perception/` (vision, DOM), `policy/` (state, choices, navigation), `runtime/` (CDP, driver, hotkeys). See `README.md#architecture`.

### Fast checks

- Policy: `uv run pytest tests/test_bot.py tests/test_controller.py -q`
- Types: `uv run mypy autobonk`
- Lint: `uv run ruff check autobonk tests` (`--fix` for imports and simple rewrites; review `--unsafe-fixes` before keeping them)
- Everything at once: `check.bat`
- Full suite: `uv run pytest`

### Engineering principles

- **Root cause over symptom-patching:** Always diagnose and repair the underlying state invariant or data-source lifecycle failure. Never introduce ad-hoc timeouts, temporary suppressions, or workaround heuristics that leave flawed perception/policy assumptions intact.
- **DOM visibility invariant:** DOM elements bearing `display: none`, `visibility: hidden`, or zero/fading opacity are dead nodes; never treat them as active in-world targets. Always prioritize authoritative HUD trackers (`compass`, `prompt`) over ephemeral notification toasts (`wlabel`).

