# 08: Exploration with the floating zone map

**What to build:** When no target is visible on the minimap, the bot holds Tab briefly about every 8 s to read the floating zone map: player position and discovered icons. It keeps an 8×8 visited grid for the zone and heads to the nearest unvisited non-edge cell, or toward a discovered wanted icon beyond minimap range. North-up zone-map bearings are converted to WASD using the 北 marker angle on the minimap rim.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Perception test: zone-map frame → correct player position and icon list
- [ ] Perception test: minimap frames → correct 北 angle
- [ ] Test: empty minimap → Tab peek, then steer toward nearest unvisited cell with yaw-corrected WASD
- [ ] Test: discovered tier-1 icon on zone map → steer toward it
- [ ] Live: with nothing nearby, bot covers new ground instead of circling