# 04: Level-up auto-pick

**What to build:** When the level-up popup (等级 N!, cards with [1]–[4]) is open, the bot releases movement and presses the key of the best card: configured name weight (Chinese card names) → else rarity rank (少见 > 普通 …) → else leftmost. Never Refresh (F), Skip (X) or Banish (Z). Weights live in the editable config.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Test: level-up frame with a weighted card in slot 4 → release movement, press "4"
- [ ] Test: no listed cards → highest rarity wins; tie → leftmost
- [ ] Test: F, X, Z are never emitted
- [ ] Changing a weight in config changes the pick without code changes
- [ ] Live: a full run's level-ups are all answered automatically