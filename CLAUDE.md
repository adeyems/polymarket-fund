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

**Paper Trading Simulation v10 - LIVE-READY** (Fresh restart 2026-02-22 11:26 UTC)
- 6 strategies running with **fresh $1,000 each** ($6,000 total)
- **Infrastructure**: Fee modeling, MM fill probability (60%), slippage (20bps), feeRateBps signing, WebSocket price feed (opt-in), taker slippage (liquidity-based), API retry with backoff, atomic portfolio writes, JSON corruption recovery
- Process PIDs: MM=57151, DIP=57717, NC=58282, NZ=58848, VS=59411, NRA=59973
- Log: `sovereign_hive/logs/simulation.log` (PERMANENT location, NOT /tmp/)
- Tests: 815 passing

**Autonomous Monitor (self-healing):**
- Runs every 30 min via launchd (`com.sovereignhive.automonitor`)
- Discord reports every 3h: 01, 04, 07, 10, 13, 16, 19, 22 UTC
- Daily deep analysis at 07:00 UTC (`com.sovereignhive.dailyanalysis`)
- Can detect crashes, fix code bugs, restart processes, pause underperforming strategies
- State: `tools/monitor_state.json` | Journal: `tools/monitor_journal.md`

**Data-Driven AI Pipeline (from 88.5M trade analysis):**
- Phase 1: Discovery (heuristic spread/volume/liquidity filter)
- Phase 2: Gemini AI deep screen + NewsAPI headlines + empirical intelligence, 1hr cache
- Phase 3: Portfolio diversification (max 2/sector, 40% sector cap)
- Phase 4: Execute with AI-recommended spread (adaptive, not fixed 2%)
- MM sweet spot: 0.50-0.70 (Kelly +29-48%), fallback: 0.80-0.95 (Kelly +4-20%)
- Min 2-day resolution (0-1d blocked), max 30-day resolution
- Crypto penalized (-0.10 confidence), politics/economics preferred

**EC2 Infrastructure (ca-central-1, STOPPED):**
- Instance: i-08a9ff0a3fc646e5d (16.54.60.150 when running)
- Wallet: 0x572FA217B5981d5f9F337a5eD5561084C665AD9A ($20 USDC.e + ~79 POL)
- Status: STOPPED (no charges). Start when ready for live.

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
STRATEGY_FILTER=DIP_BUY nohup caffeinate -i python -u sovereign_hive/run_simulation.py >> sovereign_hive/logs/dip_buy.log 2>&1 &
STRATEGY_FILTER=NEAR_CERTAIN nohup caffeinate -i python -u sovereign_hive/run_simulation.py >> sovereign_hive/logs/near_certain.log 2>&1 &
STRATEGY_FILTER=NEAR_ZERO nohup caffeinate -i python -u sovereign_hive/run_simulation.py >> sovereign_hive/logs/near_zero.log 2>&1 &
STRATEGY_FILTER=VOLUME_SURGE nohup caffeinate -i python -u sovereign_hive/run_simulation.py >> sovereign_hive/logs/volume_surge.log 2>&1 &
STRATEGY_FILTER=NEG_RISK_ARB nohup caffeinate -i python -u sovereign_hive/run_simulation.py >> sovereign_hive/logs/neg_risk_arb.log 2>&1 &
```

**ALWAYS CHECK AGENT LOG** (`.agent/AGENT_LOG.md`) for current status before starting work.
