# Sovereign Hive V4 - Performance & Operations

## Executive Summary

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Total Capital | $1,000 | $1,000 (sim) | Simulation |
| Win Rate | > 55% | - | Pending |
| Sharpe Ratio | > 1.0 | - | Pending |
| Max Drawdown | < 20% | - | Pending |
| Daily P&L | > $5 | - | Pending |
| Uptime | 99.5% | - | Pending |

---

## 1. Financial Metrics

### 1.1 Portfolio Performance

| Metric | Formula | Description |
|--------|---------|-------------|
| **Total P&L** | `sum(realized + unrealized)` | Net profit/loss since inception |
| **Realized P&L** | `sum(closed_trades)` | Profit from closed positions |
| **Unrealized P&L** | `sum(open_positions * (current - entry))` | Paper profit on open positions |
| **ROI** | `(current_value - initial) / initial * 100` | Return on investment % |
| **CAGR** | `(end/start)^(1/years) - 1` | Compound annual growth rate |

### 1.2 Risk Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| **Sharpe Ratio** | `(return - risk_free) / std_dev` | > 1.0 |
| **Sortino Ratio** | `(return - risk_free) / downside_dev` | > 1.5 |
| **Max Drawdown** | `max(peak - trough) / peak` | < 20% |
| **Current Drawdown** | `(peak - current) / peak` | < 10% |
| **Value at Risk (95%)** | `quantile(daily_returns, 0.05)` | < 5% |
| **Win Rate** | `winning_trades / total_trades` | > 55% |
| **Profit Factor** | `gross_profit / gross_loss` | > 1.5 |

### 1.3 Trade Statistics

| Metric | Description |
|--------|-------------|
| **Total Trades** | Number of completed round-trips |
| **Open Positions** | Currently held positions |
| **Avg Trade Size** | Mean position size in $ |
| **Avg Holding Time** | Mean time from entry to exit |
| **Avg Win** | Mean profit on winning trades |
| **Avg Loss** | Mean loss on losing trades |
| **Largest Win** | Best single trade |
| **Largest Loss** | Worst single trade |
| **Win/Loss Ratio** | `avg_win / avg_loss` |
| **Expectancy** | `(win_rate * avg_win) - (loss_rate * avg_loss)` |

---

## 2. Operational Metrics

### 2.1 System Health

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| **Uptime** | 99.5% | < 99% |
| **API Latency** | < 500ms | > 1000ms |
| **Order Fill Rate** | > 95% | < 90% |
| **Error Rate** | < 1% | > 5% |
| **Memory Usage** | < 500MB | > 1GB |
| **CPU Usage** | < 50% | > 80% |

### 2.2 Agent Performance

| Agent | Role | Key Metrics |
|-------|------|-------------|
| **ALPHA** | Scout | Opportunities found/hour, signal quality |
| **BETA** | Analyst | Vet accuracy, false positive rate |
| **GAMMA** | Sniper | Execution speed, slippage |
| **OMEGA** | Guardian | Risk interventions, loss prevention |

### 2.3 API Usage

| API | Daily Limit | Current Usage | Cost/Day |
|-----|-------------|---------------|----------|
| **Polymarket CLOB** | Unlimited | - | $0 |
| **Gamma API** | Unlimited | - | $0 |
| **NewsAPI** | 100 calls | - | $0 (free tier) |
| **Claude AI** | 50 calls | - | ~$0.005 |
| **Twitter** | Not active | - | $0 |

---

## 3. Strategy Performance

### 3.1 Strategy Breakdown

| Strategy | Trades | Win Rate | Avg P&L | Total P&L | Active |
|----------|--------|----------|---------|-----------|--------|
| Near-Certain Arb | 0 | - | - | $0 | Yes |
| Dip Buying | 0 | - | - | $0 | Yes |
| Volume Divergence | 0 | - | - | $0 | Yes |
| News Frontrunning | 0 | - | - | $0 | Yes |
| Resolution Timing | 0 | - | - | $0 | Yes |

### 3.2 Market Category Performance

| Category | Trades | Win Rate | P&L |
|----------|--------|----------|-----|
| Politics | 0 | - | $0 |
| Crypto | 0 | - | $0 |
| Sports | 0 | - | $0 |
| Entertainment | 0 | - | $0 |
| Science | 0 | - | $0 |

---

## 4. Architecture

### 4.1 System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    SOVEREIGN HIVE V4                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐       │
│  │  ALPHA  │  │  BETA   │  │  GAMMA  │  │  OMEGA  │       │
│  │ (Scout) │→ │(Analyst)│→ │(Sniper) │→ │(Guardian)│       │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘       │
│       │            │            │            │             │
│       └────────────┴────────────┴────────────┘             │
│                          │                                  │
│                    ┌─────▼─────┐                           │
│                    │ BLACKBOARD │                           │
│                    │  (State)   │                           │
│                    └─────┬─────┘                           │
│                          │                                  │
│       ┌──────────────────┼──────────────────┐              │
│       │                  │                  │              │
│  ┌────▼────┐       ┌─────▼─────┐      ┌────▼────┐         │
│  │  Redis  │       │  Trade    │      │ Metrics │         │
│  │ (Cache) │       │  History  │      │ Tracker │         │
│  └─────────┘       └───────────┘      └─────────┘         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Data Flow

```
NEWS SOURCE          MARKET DATA           EXECUTION
    │                    │                     │
    ▼                    ▼                     ▼
┌────────┐         ┌──────────┐          ┌─────────┐
│NewsAPI │         │Gamma API │          │CLOB API │
└───┬────┘         └────┬─────┘          └────┬────┘
    │                   │                     │
    ▼                   ▼                     ▼
┌────────┐         ┌──────────┐          ┌─────────┐
│Claude  │         │ Market   │          │ Order   │
│Analyzer│         │ Scanner  │          │ Manager │
└───┬────┘         └────┬─────┘          └────┬────┘
    │                   │                     │
    └───────────────────┼─────────────────────┘
                        │
                        ▼
                 ┌─────────────┐
                 │  BLACKBOARD │
                 │  (Signals)  │
                 └──────┬──────┘
                        │
                        ▼
                 ┌─────────────┐
                 │   AGENTS    │
                 │  (Execute)  │
                 └─────────────┘
```

### 4.3 Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Runtime | Python 3.11+ | Core application |
| Async | asyncio + aiohttp | Non-blocking I/O |
| State | Redis (optional) | Fast caching |
| Persistence | JSON files | Durable storage |
| AI | Claude 3 Haiku | Sentiment analysis |
| News | NewsAPI | Breaking news |
| Markets | Polymarket APIs | Trading data |
| Blockchain | Polygon | Settlement |

---

## 5. Risk Management

### 5.1 Position Limits

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Max Position Size** | 10% of capital | Single trade cap |
| **Max Open Positions** | 10 | Diversification |
| **Max Single Market** | 20% of capital | Concentration limit |
| **Daily Loss Limit** | 5% of capital | Circuit breaker |
| **Max Leverage** | 1x (no leverage) | Conservative |

### 5.2 Exit Rules

| Exit Type | Trigger | Action |
|-----------|---------|--------|
| **Take Profit** | +5% unrealized | Sell position |
| **Stop Loss** | -15% unrealized | Sell position |
| **Time Stop** | 7 days no movement | Review position |
| **Resolution** | Market resolves | Claim payout |
| **Emergency** | System halt | Close all |

### 5.3 Circuit Breakers

| Trigger | Action |
|---------|--------|
| Daily loss > 5% | Pause new trades for 24h |
| 3 consecutive losses | Reduce position size 50% |
| API errors > 10/hour | Alert + pause 1h |
| Drawdown > 15% | Manual review required |

---

## 6. Alerts & Monitoring

### 6.1 Alert Channels

| Channel | Use Case | Setup |
|---------|----------|-------|
| Console | Real-time logs | Default |
| Discord | Trade notifications | Webhook |
| Email | Daily reports | SMTP |
| SMS | Critical alerts | Twilio |

### 6.2 Alert Types

| Priority | Type | Trigger |
|----------|------|---------|
| **P0 Critical** | System down | Immediate page |
| **P1 High** | Large loss (> $50) | Immediate alert |
| **P2 Medium** | Trade executed | Log + Discord |
| **P3 Low** | Opportunity found | Log only |

### 6.3 Daily Report Contents

```
=== SOVEREIGN HIVE DAILY REPORT ===
Date: YYYY-MM-DD

PORTFOLIO
  Starting Balance: $X,XXX.XX
  Ending Balance:   $X,XXX.XX
  Daily P&L:        +/- $XX.XX (X.X%)

TRADES TODAY
  Opened: X
  Closed: X
  Win Rate: XX%

TOP PERFORMERS
  1. [Market] +$XX.XX
  2. [Market] +$XX.XX

WORST PERFORMERS
  1. [Market] -$XX.XX

RISK STATUS
  Open Positions: X
  Total Exposure: $XXX
  Max Drawdown: X.X%

API USAGE
  Claude: X/50 calls
  NewsAPI: X/100 calls

=================================
```

---

## 7. Simulation vs Live

### 7.1 Mode Comparison

| Feature | Simulation | Live |
|---------|------------|------|
| Market Data | Real | Real |
| Order Execution | Simulated | Real |
| Balance | Virtual $1,000 | Real USDC |
| P&L Tracking | Full | Full |
| Risk Limits | Same | Same |
| API Costs | Real | Real |

### 7.2 Switching to Live

```python
# Simulation mode (default)
python run_simulation.py

# Live trading (requires funding)
python run_simulation.py --live

# Required for live:
# 1. USDC balance > $50
# 2. POL for gas > 1 POL
# 3. Valid CLOB API credentials
```

---

## 8. Key Performance Indicators (KPIs)

### 8.1 Weekly Goals

| KPI | Target | Weight |
|-----|--------|--------|
| Win Rate | > 55% | 25% |
| Sharpe Ratio | > 1.0 | 25% |
| Max Drawdown | < 15% | 20% |
| Trade Count | > 20 | 15% |
| Uptime | > 99% | 15% |

### 8.2 Monthly Review

- Total trades executed
- Net P&L ($ and %)
- Strategy performance breakdown
- Risk incidents
- System improvements made
- API costs incurred

---

## 9. Glossary

| Term | Definition |
|------|------------|
| **P&L** | Profit and Loss |
| **Sharpe Ratio** | Risk-adjusted return (higher = better) |
| **Drawdown** | Peak-to-trough decline |
| **Win Rate** | Percentage of profitable trades |
| **Expectancy** | Average expected profit per trade |
| **Slippage** | Difference between expected and actual price |
| **CLOB** | Central Limit Order Book |
| **Condition ID** | Unique market identifier on Polymarket |

---

*Last Updated: 2026-02-08*
*Version: 4.0.0*
