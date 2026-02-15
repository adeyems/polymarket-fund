# Claude Code Instructions

Agent workspace: `.agent/`

| File | Purpose |
|------|---------|
| `AGENT_RULES.md` | General rules (copy to other projects) |
| `PROJECT_RULES.md` | QuesQuant-specific rules |
| `AGENT_LOG.md` | Activity log (add entries to TOP) |
| `HANDOVER.md` | Handover guide |
| `todo.md` | Task tracking |
| `lessons.md` | Self-improvement notes |

## Session Logging (IMPORTANT)

**At the START of each session:** Read `.agent/AGENT_LOG.md` to understand recent context.

**At the END of each session (or periodically):** Add a log entry to the TOP of `.agent/AGENT_LOG.md` with:
- Date/time
- What was worked on
- Key decisions made
- Current status (what's running, P&L, etc.)
- Next steps

This prevents context loss across sessions.

## Current Project Status

**Paper Trading Simulation - ACTIVE** (Started 2026-02-13 10:33 UTC)
- All 9 strategies running together with 100% realistic parameters
- Virtual $1000 capital with CORRECTED execution model
- Process: PID 40862 (caffeinate -i python run_simulation.py)
- Log: `sovereign_hive/logs/simulation.log` (PERMANENT location, NOT /tmp/)

**Recent Critical Fixes Applied (2026-02-13 10:35 UTC):**
1. ✅ MM Spread: 0.5% → 2% (realistic bid/ask spread)
2. ✅ Fill Rate: 100% → 60% probabilistic (realistic fills)
3. ✅ Slippage: Added 0.2% average slippage on MM exits
4. ✅ Kelly Criterion: Disabled for MEAN_REVERSION (was causing capital destruction)
5. ✅ Min Position Size: $5 → $50 (too small to matter before)
6. ✅ MM Hold Time: 24h → 4h (realistic market making timeout)

**Expected Behavior Changes:**
```
BEFORE (Unrealistic)          AFTER (Realistic)
-----------------------------------
MM Win Rate: 99.3% -------> ~70% (realistic)
MM Returns: +116% --------> +20-30% (realistic)
MEAN_REVERSION: 0 trades --> executing trades (Kelly disabled)
Min Position: $5 ---------> $50 (meaningful positions)
```

**Monitor Simulation:**
```bash
# Follow live trading
tail -f sovereign_hive/logs/simulation.log

# Check current balance & P&L
tail -100 sovereign_hive/logs/simulation.log | grep -E "Total Value|Total P&L|ROI"
```

**To Restart After Mac Reboot:**
```bash
cd /Users/qudus-mac/PycharmProjects/polymarket-fund
nohup caffeinate -i python -u sovereign_hive/run_simulation.py >> sovereign_hive/logs/simulation.log 2>&1 &
```

**ALWAYS CHECK AGENT LOG** (`.agent/AGENT_LOG.md`) for current status before starting work.
**Status Details**: See 2026-02-13 10:35 UTC entry in AGENT_LOG.md
