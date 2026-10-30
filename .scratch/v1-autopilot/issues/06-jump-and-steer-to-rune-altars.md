# 06: Random jumping + steering to rune altars

**What to build:** During play the bot jumps (Space) at random 0.8–1.4 s intervals. It detects rune altar icons (未知图腾祭坛, crystal) on the corner minimap, holds the 8-way WASD combination toward the nearest one (minimap-up = W, with a dead-zone), stops in the ring, and stays there while the progress bubble (`div.charge` with `NN%`) shows (cap 45 s).
The altar needs no E: standing in the ring charges it (recorded 2026-10-30).

**Blocked by:** 03

**Status:** ready-for-agent

- [x] Test: altar on the minimap → hold the 8-way WASD toward it (minimap-up = W)
- [x] Test: altar at minimap centre / progress visible → stop and stay; give up after the cap
- [x] Test: frame sequence shows jumps at randomised intervals within the configured range
- [x] Perception test: minimap crops yield correct rune altar positions
- [ ] Live: bot walks to a visible rune altar and completes it