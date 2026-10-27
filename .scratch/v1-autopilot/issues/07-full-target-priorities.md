# 07: Full target priorities + stuck recovery

**What to build:** All target icons with tiers from config — tier 1: Snorlax, fossil ruins, free pokéball, purple bomb; tier 2: ore pile, rune altar, challenge altar, plus Ditto and magnet only at ≤5:00 remaining; tier 3: curse altar, Porygon altar (only when tiers 1–2 have nothing). Nearest within the highest tier, but a lower tier wins if the higher-tier target is >3× farther. All other icons ignored. A target is done when its icon disappears. Stuck (no distance progress for 8 s) → jump+slide (Shift) one side, then the other, then skip the target for 60 s.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Test: tier-1 and tier-2 icons visible → steer to tier 1
- [ ] Test: tier-1 icon >3× farther than a tier-2 icon → steer to tier 2
- [ ] Test: Ditto/magnet ignored at 5:01, targeted at 5:00
- [ ] Test: ignored icons (pokéball, cage, shop, slot, mushroom, berry, Gengar, Rhyhorn, Hypno, fusion) never targeted
- [ ] Test: 8 s without progress → recovery sequence, then target skipped for 60 s
- [ ] Perception test: every target icon type detected on minimap fixtures