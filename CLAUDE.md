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

**Paper Trading Simulation v5 - ACTIVE** (Started 2026-02-16 15:12 UTC)
- All 9 strategies running with RESEARCH-BACKED parameters
- Virtual $1000 capital, fresh portfolio reset
- Process: PID 86122 (caffeinate -i python run_simulation.py)
- Log: `sovereign_hive/logs/simulation.log` (PERMANENT location, NOT /tmp/)

**Research-Backed Parameter Overhaul (2026-02-16 15:12 UTC):**
1. ✅ Kelly Fraction: 15% → 40% (15% was for $10M+ funds, not $1k)
2. ✅ Kelly: Removed confidence triple-penalty (was making $10 positions)
3. ✅ Max Positions: 12 → 6 (concentrate capital)
4. ✅ Position Cap: $100 → $200 (meaningful trades)
5. ✅ NEAR_CERTAIN: 95% → 93% (research shows profitable at 93%+)
6. ✅ DIP_BUY: -5% → -3% threshold, re-enabled
7. ✅ BINANCE_ARB: 5% → 3% edge (latency arb dead, model-based now)
8. ✅ MM price range: 15-85% → 5-95% (capturing low-price markets)
9. ✅ MM target profit: 1% → 2% per trip
10. ✅ MM bid/ask: added $0.01 floor (fixes rounding on low-price markets)

**First Cycle Results (Immediate Improvement!):**
- 5 positions in first 60 seconds (vs 0 new trades in 42+ hours before)
- 3 MM + 2 MEAN_REVERSION, $85-200 per position
- Previous problem: Kelly was sizing at $10-30 → rejected below $50 minimum

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
