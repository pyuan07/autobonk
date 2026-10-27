# 06: Random jumping + steering to rune altars

**What to build:** During play the bot jumps (Space) at random 0.8–1.4 s intervals. It detects rune altar icons (未知图腾祭坛, crystal) on the corner minimap, holds the 8-way WASD combination toward the nearest one (minimap-up = W, with a dead-zone), presses E on arrival, and stays inside the ring until the progress bubble disappears (cap 45 s).

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Test: frame with rune altar up-right on minimap → hold W+D
- [ ] Test: altar at minimap centre → E pressed, movement stays near ring while progress visible
- [ ] Test: frame sequence shows jumps at randomised intervals within the configured range
- [ ] Perception test: minimap crops yield correct rune altar positions
- [ ] Live: bot walks to a visible rune altar and completes it