# 01: Browser launcher + frame recorder

**What to build:** One command opens the installed Chrome on https://pokebonk.com/ with a dedicated persistent profile at a fixed 1600×900 viewport, with background-running flags (no timer throttling, no renderer backgrounding, no Windows occlusion calculation; blur/visibilitychange suppressed). The user logs in once and the login persists. A global F9 hotkey saves a **frame** (screenshot + DOM snapshot + timestamp) to a fixtures folder. A global F8 hotkey toggles paused/running and releases all held keys; both hotkeys work while the browser is unfocused.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Launch command opens Chrome (not bundled Chromium) on PokéBonk at 1600×900 with a dedicated profile folder
- [ ] After logging in once, relaunching does not require login again
- [ ] Game keeps rendering and the timer keeps running while the window is unfocused or covered
- [ ] F9 writes a frame (PNG screenshot, DOM HTML, timestamp metadata) with a unique name, from any focused app
- [ ] F8 toggles pause/resume from any focused app, logs the state, and releases all keys
- [ ] Project scaffold: dependency file, config file stub, pytest runs (even with zero tests)