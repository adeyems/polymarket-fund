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

**Paper Trading Simulation v6 - ACTIVE** (Started 2026-02-17 ~14:58 UTC)
- All 9 strategies running with AI market screening
- Virtual $1000 capital, fresh portfolio reset
- Process: PID 35771 (caffeinate -i python run_simulation.py)
- Log: `sovereign_hive/logs/simulation.log` (PERMANENT location, NOT /tmp/)

**New: AI Market Quality Filter (2026-02-17):**
- Gemini AI screens every MM market before trading (free tier)
- Hard 30-day max resolution filter for MM (prevents capital lock-up)
- Expanded meme market exclusion list ($1M, billion dollar, etc.)

**EC2 Infrastructure (ca-central-1, STOPPED):**
- Instance: i-08a9ff0a3fc646e5d (16.54.60.150 when running)
- Wallet: 0x572FA217B5981d5f9F337a5eD5561084C665AD9A ($20 USDC.e + ~79 POL)
- Status: STOPPED (no charges). Start when ready for live.
- All CLOB orders cancelled, no open positions.

**Live Trading Test Results (2026-02-17):**
- Successfully placed real CLOB orders from Montreal EC2
- Bug found: "CANCELED" (American) vs "CANCELLED" (British) - fixed
- Bug found: No AI screening = bot picked absurd markets (BTC $1M) - fixed
- Decision: Return to paper trading until AI filter is proven

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
