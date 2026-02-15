# Sovereign Hive - Decentralized Trading Firm

A multi-agent autonomous trading system for Polymarket.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    BLACKBOARD (blackboard.json)              │
│  ┌──────────────┬───────────────┬────────────────────────┐  │
│  │ opportunities│ vetted_trades │ active_positions       │  │
│  └──────────────┴───────────────┴────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
       ▲                ▲                    ▲
       │ WRITE          │ WRITE              │ READ/WRITE
       │                │                    │
┌──────┴─────┐   ┌──────┴──────┐   ┌────────┴────────┐
│   ALPHA    │   │    BETA     │   │     GAMMA       │
│  (Scout)   │──▶│  (Analyst)  │──▶│    (Sniper)     │
│            │   │             │   │                 │
│ Math-based │   │ News/LLM    │   │ Order Execution │
│ Anomaly    │   │ Validation  │   │                 │
└────────────┘   └─────────────┘   └─────────────────┘
                                           │
                                           ▼
                              ┌────────────────────┐
                              │      OMEGA         │
                              │    (Guardian)      │
                              │                    │
                              │ Risk Monitoring    │
                              │ Position Tracking  │
                              └────────────────────┘
```

## Agents

### Agent ALPHA - The Scout
**File:** `agents/alpha_scout.py`
**Directive:** Mathematical Discovery. Keyword-blind anomaly detection.

Anomaly Types:
- `ARBITRAGE` - Price > $0.98 (near-certain outcomes)
- `DIP_BUY` - High volume + significant price drop
- `VOLUME_SPIKE` - 2x normal volume activity
- `MISPRICING` - Wide spread on liquid market

### Agent BETA - The Analyst
**File:** `agents/beta_analyst.py`
**Directive:** Semantic Validation. Cross-references discoveries with news/LLM.

Verdicts:
- `VETTED` - Safe to trade
- `REJECTED` - Trap/noise
- `PENDING` - Needs manual review

### Agent GAMMA - The Sniper
**File:** `agents/gamma_sniper.py`
**Directive:** Capital Deployment. Executes optimized limit orders.

Features:
- Maker-first order placement (lower fees)
- Position sizing based on available capital
- Respects price limits per strategy

### Agent OMEGA - The Guardian
**File:** `agents/omega_guardian.py`
**Directive:** Compliance/Audit. Monitors risk and portfolio health.

Responsibilities:
- Track active positions
- Monitor for market resolution
- Enforce risk limits
- Gas balance alerts

## Usage

### Single Scan Cycle (Dry Run)
```bash
cd sovereign_hive
python run_hive.py --scan
```

### Check Status
```bash
python run_hive.py --status
```

### Run Individual Agents
```bash
# Scout only
python agents/alpha_scout.py --once

# Analyst only
python agents/beta_analyst.py --once

# Sniper (dry run)
python agents/gamma_sniper.py

# Sniper (LIVE - real orders!)
python agents/gamma_sniper.py --live

# Guardian
python agents/omega_guardian.py --once
```

### Continuous Mode
```bash
# Dry run (safe)
python run_hive.py

# Live trading (requires confirmation)
python run_hive.py --live
```

### Emergency Controls
```bash
# Halt all trading
python agents/omega_guardian.py --halt

# Resume trading
python agents/omega_guardian.py --resume
```

## Blackboard Schema

```json
{
  "opportunities": [
    {
      "condition_id": "0x...",
      "question": "Market question",
      "anomaly_type": "ARBITRAGE|DIP_BUY|VOLUME_SPIKE|MISPRICING",
      "score": 0.0,
      "best_bid": 0.0,
      "best_ask": 0.0,
      "status": "PENDING|VETTED|REJECTED"
    }
  ],
  "vetted_trades": [],
  "active_positions": [],
  "risk_state": "HEALTHY|WARNING|CRITICAL|HALTED",
  "wallet_balances": {"usdc": 0, "pol": 0},
  "alerts": []
}
```

## Risk Limits (Configurable)

| Limit | Default | Description |
|-------|---------|-------------|
| MAX_SINGLE_POSITION | $10 | Max per market |
| MAX_TOTAL_EXPOSURE | $50 | Max total deployed |
| MIN_GAS_BALANCE | 1.0 POL | Gas alert threshold |
| MAX_LOSS_PERCENT | 20% | Stop loss trigger |
| MAX_PRICE_ARBITRAGE | $0.998 | Don't buy arb above this |

## Files

```
sovereign_hive/
├── blackboard.json      # Shared state (the "brain")
├── run_hive.py          # Master orchestrator
├── README.md            # This file
├── agents/
│   ├── alpha_scout.py   # Mathematical anomaly detection
│   ├── beta_analyst.py  # News/LLM validation
│   ├── gamma_sniper.py  # Order execution
│   └── omega_guardian.py # Risk monitoring
├── data/                # Historical data (optional)
└── logs/                # Agent logs (optional)
```
