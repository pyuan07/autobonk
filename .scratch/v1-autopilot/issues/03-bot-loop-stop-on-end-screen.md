# 03: Bot loop end-to-end — stop on win/lose

**What to build:** The full pipeline `Bot.step(frame) → commands` running both live (real Playwright driver, ~10 steps/s, enabled by F8) and in tests (fake driver + recorded frames). The only behaviour: on the win (胜利!) or lose (你倒下了!) screen, release all keys and stop; if the screen is unrecognised for 5 s, pause. Console log shows each step's recognised state and emitted commands.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Test: win frame → release_all + stop
- [ ] Test: lose frame → release_all + stop
- [ ] Test: 5 s of unrecognisable frames → pause
- [ ] Test: normal play frame → no stop/pause
- [ ] Live: pressing F8 during a run starts the loop; reaching the end screen stops it with no keys held