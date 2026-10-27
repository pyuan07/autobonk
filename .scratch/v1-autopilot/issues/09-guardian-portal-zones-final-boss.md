# 09: Guardian, portal, zones and final boss

**What to build:** At ≤3:00 remaining the bot drops other targets and heads to the guardian altar (skull) and keeps moving and jumping while auto-attacks fight. On "守护者已被击败" it searches nearby for the "E 进入传送门" prompt and presses E. Zone memory (visited grid, skipped targets) resets in the new zone. In 森林圣地 it goes to the sanctuary, presses E at "触碰圣地", and keeps moving and jumping until the end screen.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] Test: 2:59 remaining with tier-1 icon and skull visible → steer to skull
- [ ] Test: guardian-defeated banner → portal search; portal prompt → E
- [ ] Test: after zone change, previously visited/skipped state is cleared
- [ ] Test: sanctuary prompt → E
- [ ] Live: bot clears zone 1 and enters zone 2 unattended