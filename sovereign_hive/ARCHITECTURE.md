# Sovereign Hive V4 - Complete System Architecture

**Document Version:** 1.0
**Last Updated:** 2026-02-09
**Status:** Active Development (Simulation Mode)

---

## Executive Summary

Sovereign Hive is an autonomous multi-agent trading system for Polymarket prediction markets. It uses real-time market data from Polymarket's Gamma API, AI-powered news sentiment analysis (Claude 3.5 Haiku), and cross-exchange arbitrage scanning (Binance) to identify and execute profitable trades.

**Current State:**
- **Mode:** Paper trading with real market data
- **Capital:** $1,000 virtual (simulation)
- **Positions:** 8 open positions worth ~$555
- **Cash:** $444.56
- **ROI:** ~0% (unrealized, positions not yet resolved)
- **Strategies Active:** 5 defined, but only 2 triggered (NEAR_CERTAIN: 1, NEAR_ZERO: 6, MID_RANGE: 1, DIP_BUY: 0, VOLUME_SURGE: 0)

---

## 1. System Architecture Overview

```
                    ┌─────────────────────────────────────────────┐
                    │            SOVEREIGN HIVE V4                │
                    │         Autonomous Trading System           │
                    └─────────────────────────────────────────────┘
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           │                            │                            │
           ▼                            ▼                            ▼
   ┌───────────────┐          ┌─────────────────┐          ┌─────────────────┐
   │ DATA SOURCES  │          │  TRADING ENGINE │          │   PERSISTENCE   │
   │               │          │                 │          │                 │
   │ • Gamma API   │─────────▶│ • MarketScanner │─────────▶│ • portfolio.json│
   │ • Binance API │          │ • NewsAnalyzer  │          │ • blackboard.json│
   │ • NewsAPI     │          │ • TradingEngine │          │ • trade_history │
   │ • Claude API  │          │ • Portfolio     │          │                 │
   └───────────────┘          └─────────────────┘          └─────────────────┘
                                        │
                                        ▼
                              ┌─────────────────┐
                              │   EXECUTION     │
                              │                 │
                              │ • AsyncExecutor │
                              │ • CLOB Client   │
                              │ • Retry Logic   │
                              └─────────────────┘
```

---

## 2. Core Components

### 2.1 Trading Engine (`run_simulation.py`)

The main orchestrator that runs the trading loop.

**Responsibilities:**
- Coordinate scanning, evaluation, and execution
- Manage position lifecycle (entry, monitoring, exit)
- Track portfolio state and P&L
- Generate strategy A/B test reports

**Main Loop:**
```python
while running:
    1. check_exits()          # Check TP/SL on open positions
    2. get_active_markets()   # Fetch 100 liquid markets
    3. find_opportunities()   # Apply all strategies
    4. evaluate_opportunity() # News sentiment check
    5. execute_trade()        # Paper or live execution
    6. sleep(60)              # 60-second scan interval
```

### 2.2 Market Scanner (`MarketScanner`)

Fetches and analyzes Polymarket data.

**API Endpoint:** `https://gamma-api.polymarket.com/markets`

**Market Data Fields Used:**
| Field | Description |
|-------|-------------|
| `conditionId` | Unique market identifier |
| `question` | Market question text |
| `bestAsk` | Lowest ask price (YES price) |
| `bestBid` | Highest bid price |
| `liquidityNum` | Total market liquidity in USD |
| `volume24hr` | 24-hour trading volume |
| `oneDayPriceChange` | Price change (decimal, e.g., 0.05 = 5%) |
| `endDate` | Market resolution date |

**Filtering:**
- Minimum liquidity: $5,000
- Active markets only (`active=true`, `closed=false`)

### 2.3 Portfolio Manager (`Portfolio`)

Tracks all positions and calculates P&L.

**State Structure (`portfolio_sim.json`):**
```json
{
  "balance": 493.95,
  "initial_balance": 1000.0,
  "positions": {
    "0x...conditionId": {
      "condition_id": "0x...",
      "question": "Will X happen?",
      "side": "YES" | "NO",
      "entry_price": 0.37,
      "shares": 200.12,
      "cost_basis": 74.04,
      "entry_time": "2026-02-09T10:39:41Z",
      "reason": "Mid-range momentum UP",
      "strategy": "MID_RANGE"
    }
  },
  "trade_history": [],
  "metrics": {
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "total_pnl": 0.0,
    "max_drawdown": 0.0,
    "peak_balance": 1000.0
  },
  "strategy_metrics": {
    "NEAR_CERTAIN": {"trades": 0, "wins": 0, "pnl": 0.0},
    "NEAR_ZERO": {"trades": 0, "wins": 0, "pnl": 0.0},
    "DIP_BUY": {"trades": 0, "wins": 0, "pnl": 0.0},
    "VOLUME_SURGE": {"trades": 0, "wins": 0, "pnl": 0.0},
    "MID_RANGE": {"trades": 0, "wins": 0, "pnl": 0.0}
  }
}
```

### 2.4 News Analyzer (`NewsAnalyzer` + `ClaudeAnalyzer`)

AI-powered news sentiment analysis.

**Components:**
1. **NewsAPI Integration** - Fetches relevant news articles
2. **Claude 3.5 Haiku** - Analyzes sentiment for market impact

**API Usage:**
- Model: `claude-3-haiku-20240307`
- Max tokens: 150 per request
- Daily limit: 50 requests (budget protection)
- Cost: ~$0.0001 per analysis

**Response Format:**
```json
{
  "is_relevant": true,
  "direction": "BULLISH",
  "confidence": 0.85,
  "reasoning": "Poll shows strong lead",
  "action": "BUY_YES"
}
```

### 2.5 Async Executor (`AsyncExecutor`)

Non-blocking order execution with retry logic.

**Features:**
- Exponential backoff (1s, 2s, 4s)
- Max 3 retries
- Thread pool for sync CLOB client
- Dry-run mode for simulation

**CLOB Client Configuration:**
```python
ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,  # Polygon
    key=POLYMARKET_PRIVATE_KEY,
    creds=ApiCreds(api_key, api_secret, api_passphrase)
)
```

---

## 3. Trading Strategies

### 3.1 Strategy Overview

| Strategy | Risk Level | Market Type | Exit Method | Expected Return | Turnover |
|----------|------------|-------------|-------------|-----------------|----------|
| MARKET_MAKER | Low | 15-85%, High Vol | Fill/Timeout | 1% per trip | Hours |
| DUAL_SIDE_ARB | Very Low | YES+NO < $0.98 | Resolution | 2-5% (guaranteed) | Days |
| NEAR_CERTAIN | Very Low | YES >= 95% | Resolution | 2-5% | Weeks |
| NEAR_ZERO | Very Low | YES <= 5% | Resolution | 2-5% | Weeks |
| MID_RANGE | Medium | 20-80% | TP/SL | 3-10% | Days |
| DIP_BUY | Medium | -5% drop | TP/SL | 3-15% | Days |
| VOLUME_SURGE | Medium | 2x volume | TP/SL | 3-10% | Days |

### 3.2 DUAL_SIDE_ARB Strategy (Account88888's $645K Strategy)

**Logic:** Buy BOTH YES and NO when combined cost < $0.98 (guaranteed profit)

**Entry Criteria:**
- `YES_price + NO_price < 0.98` (2%+ minimum profit)
- Liquidity >= $10,000 (each side)
- Must be able to buy BOTH sides

**P&L Calculation:**
```python
yes_price = bestAsk
no_price = 1 - bestBid  # NO cost = 1 - YES bid
total_cost = yes_price + no_price

if total_cost < 0.98:
    profit_per_share = 1.00 - total_cost  # Guaranteed $1 payout
    profit_pct = profit_per_share / total_cost
```

**Exit:** Wait for resolution - ONE side ALWAYS pays $1.00

**Why This Strategy:**
- Account88888 made $645K profit with 96% win rate
- Zero risk if both sides can be purchased
- Works best during high volatility when spreads widen
- Rare opportunity (markets are usually efficient)

**Example:**
```
Market: "Will X happen?"
YES Ask: $0.51
NO Bid: $0.52 → NO price = 1 - 0.52 = $0.48
Total cost: $0.51 + $0.48 = $0.99 (NO ARB - too tight)

BETTER EXAMPLE:
YES Ask: $0.55
NO Bid: $0.50 → NO price = 1 - 0.50 = $0.50
Total cost: $0.55 + $0.50 = $1.05 (NO ARB - OVERPRICED!)

ARB EXISTS:
YES Ask: $0.47
NO Bid: $0.55 → NO price = 1 - 0.55 = $0.45
Total cost: $0.47 + $0.45 = $0.92 (ARB! 8.7% guaranteed)
```

---

### 3.4 NEAR_CERTAIN Strategy

**Logic:** Buy YES when price >= 95%

**Entry Criteria:**
- `bestAsk >= 0.95`
- Liquidity >= $5,000

**Exit:** Wait for market resolution to $1.00

**Risk:** Market flips (rare at 95%+)

**Example:**
```
Market: "Will Super Bowl happen in 2025?"
Price: $0.99 (99% YES)
Buy: 100 shares @ $0.99 = $99
Payout: 100 shares × $1.00 = $100
Profit: $1.00 (1.01%)
```

### 3.5 NEAR_ZERO Strategy

**Logic:** Buy NO when YES price <= 5% (NO price >= 95%)

**Entry Criteria:**
- `bestAsk <= 0.05` (YES price)
- NO price = `1 - bestBid` < 0.98
- Liquidity >= $5,000

**Exit:** Wait for market resolution

**P&L Calculation for NO positions:**
```python
# CRITICAL: NO positions have inverted pricing
current_price = 1.0 - yes_price  # e.g., YES=0.04 → NO=0.96
pnl_pct = (current_price - entry_price) / entry_price
```

**Example:**
```
Market: "Will GTA VI release before June 2026?"
YES Price: $0.04 (4%)
NO Price: $0.96 (96%)
Buy: 85 NO shares @ $0.958 = $82.27
Payout if NO wins: 85 × $1.00 = $85.88
Profit: $3.61 (4.4%)
```

### 3.6 MID_RANGE Strategy (Active Trading)

**Logic:** Trade with momentum in 20-80% range

**Entry Criteria:**
- `0.20 <= bestAsk <= 0.80`
- Volume 24h >= $10,000
- Price change > 0.5% (momentum)

**Direction:**
- Buy YES if `oneDayPriceChange > 0.005`
- Buy NO if `oneDayPriceChange < -0.005`

**Exit:** Take Profit (+5%) or Stop Loss (-15%)

**Why This Strategy:**
- Near-certain strategies lock capital until resolution (weeks/months)
- MID_RANGE allows active trading with TP/SL exits
- Covers 73% of market price range (vs 0.6% for near-certain only)

### 3.7 DIP_BUY Strategy

**Logic:** Buy oversold markets expecting rebound

**Entry Criteria:**
- `oneDayPriceChange < -0.05` (5%+ drop)
- Volume 24h > $30,000 (high activity)
- Claude AI sentiment: BULLISH or NEUTRAL

**Exit:** Take Profit (+5%) or Stop Loss (-15%)

**Risk:** Fundamental shift (price continues down)

### 3.8 VOLUME_SURGE Strategy

**Logic:** Follow smart money accumulation

**Entry Criteria:**
- Current hour volume > 2x hourly average
- Price change < 5% (accumulation, not breakout)
- Liquidity >= $5,000

**Direction:**
- Buy YES if price change >= 0
- Buy NO if price change < 0

**Exit:** Take Profit (+5%) or Stop Loss (-15%)

---

## 4. Financial Model

### 4.1 Position Sizing

```python
CONFIG = {
    "max_position_pct": 0.10,    # Max 10% of balance per trade
    "max_positions": 10,         # Max 10 open positions
    "min_liquidity": 5000,       # Min market liquidity
}

# Additional constraint: Max 1% of market liquidity
max_amount = min(
    balance * 0.10,              # 10% of balance
    liquidity * 0.01,            # 1% of market liquidity
    100                          # Hard cap $100/trade
)
```

### 4.2 Risk Management

**Exit Rules:**
| Condition | Action |
|-----------|--------|
| P&L >= +5% | Take Profit |
| P&L <= -15% | Stop Loss |
| Market resolved | Claim payout |

**Drawdown Tracking:**
```python
if balance > peak_balance:
    peak_balance = balance
drawdown = (peak_balance - balance) / peak_balance
```

### 4.3 Fee Structure

**Polymarket Fees:**
- Trading fee: ~1% (built into spread)
- No withdrawal fees
- Gas: POL on Polygon (minimal)

**Cost Basis Calculation:**
```python
cost_basis = shares * entry_price
# Does NOT include fees (fees are in the price)
```

### 4.4 P&L Calculations

**YES Positions:**
```python
current_value = shares * current_yes_price
pnl = current_value - cost_basis
pnl_pct = pnl / cost_basis
```

**NO Positions:**
```python
current_no_price = 1.0 - current_yes_price
current_value = shares * current_no_price
pnl = current_value - cost_basis
pnl_pct = pnl / cost_basis
```

**Resolution Payout:**
```python
if winning_side:
    payout = shares * 1.00  # Winning side pays $1/share
else:
    payout = 0.00  # Losing side pays $0
```

---

## 5. Current Portfolio State

### 5.1 Summary (as of 2026-02-09)

| Metric | Value |
|--------|-------|
| Cash Balance | $444.56 |
| Invested | $555.44 |
| Total Value | ~$1,000 |
| ROI | ~0% (unrealized) |
| Open Positions | 8 |
| Closed Trades | 0 |

### 5.2 Open Positions

| Market | Strategy | Side | Entry | Cost Basis | Days to Resolve |
|--------|----------|------|-------|------------|-----------------|
| Rob Jetten PM | NEAR_CERTAIN | YES | $0.987 | $100.00 | 324d |
| U.S. Revenue $100b | NEAR_ZERO | NO | $0.959 | $77.28 | 18d |
| GTA VI June 2026 | NEAR_ZERO | NO | $0.958 | $82.27 | 110d |
| Thunder NBA | MID_RANGE | YES | $0.370 | $74.04 | 141d |
| Panthers Stanley | NEAR_ZERO | NO | $0.962 | $66.64 | 140d |
| Trump deportations | NEAR_ZERO | NO | $0.968 | $50.92 | PENDING |
| Elon budget 5% | NEAR_ZERO | NO | $0.979 | $54.88 | 18d |
| Dallas Stars | NEAR_ZERO | NO | $0.960 | $49.40 | 140d |

### 5.3 Strategy Distribution

| Strategy | Positions | Capital Allocated | % of Portfolio |
|----------|-----------|-------------------|----------------|
| NEAR_CERTAIN | 1 | $100.00 | 18% |
| NEAR_ZERO | 6 | $381.40 | 69% |
| MID_RANGE | 1 | $74.04 | 13% |
| DIP_BUY | 0 | $0.00 | 0% |
| VOLUME_SURGE | 0 | $0.00 | 0% |

### 5.4 Critical Observations

1. **Strategy Imbalance:** 75% of positions are NEAR_ZERO (6 of 8)
2. **No Active Trading Exits:** All positions wait for resolution, no TP/SL triggered
3. **Capital Efficiency Issue:** Only $132 (24%) resolves within 60 days
4. **Missing Strategies:** DIP_BUY and VOLUME_SURGE have never triggered

---

## 6. External Integrations

### 6.1 Polymarket Gamma API

**Base URL:** `https://gamma-api.polymarket.com`

**Endpoints Used:**
| Endpoint | Purpose |
|----------|---------|
| `/markets` | List active markets |
| `/markets?conditionId=X` | Single market (buggy - fetches all) |

**Rate Limits:** Unknown (conservative: 100 req/min)

### 6.2 Polymarket CLOB API

**Base URL:** `https://clob.polymarket.com`

**Authentication:**
```python
ApiCreds(
    api_key=CLOB_API_KEY,
    api_secret=CLOB_SECRET,
    api_passphrase=CLOB_PASSPHRASE
)
```

**Order Execution:**
```python
OrderArgs(
    price=0.37,
    size=200.12,
    side="BUY",
    token_id="0x..."
)
client.create_and_post_order(order_args)
```

### 6.3 Binance API

**Endpoints:**
- Spot: `https://api.binance.com/api/v3/ticker/price`
- Futures: `https://fapi.binance.com/fapi/v1/ticker/price`

**Symbols Tracked:** BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, BNBUSDT

**Use Case:** Cross-exchange arbitrage for crypto price prediction markets

### 6.4 Anthropic Claude API

**Endpoint:** `https://api.anthropic.com/v1/messages`

**Model:** `claude-3-haiku-20240307`

**Headers:**
```
x-api-key: CLAUDE_API_KEY
anthropic-version: 2023-06-01
content-type: application/json
```

### 6.5 NewsAPI

**Endpoint:** `https://newsapi.org/v2/everything`

**Parameters:**
```python
{
    "q": search_query,
    "sortBy": "publishedAt",
    "language": "en",
    "pageSize": 3,
    "apiKey": NEWS_API_KEY
}
```

---

## 7. Configuration Reference

### 7.1 Trading Configuration

```python
CONFIG = {
    # Capital Management
    "initial_balance": 1000.00,
    "max_position_pct": 0.10,      # 10% per trade
    "max_positions": 10,

    # Exit Rules (UPDATED 2026-02-09)
    "take_profit_pct": 0.03,       # +3% (was 5% - faster exits!)
    "stop_loss_pct": -0.10,        # -10% (was -15% - tighter risk)

    # Market Filters
    "min_liquidity": 5000,
    "min_confidence": 0.55,
    "scan_interval": 60,           # seconds

    # Strategy Thresholds
    "near_certain_min": 0.95,      # 95%+ for NEAR_CERTAIN
    "near_zero_max": 0.05,         # 5%- for NEAR_ZERO
    "dip_threshold": -0.05,        # 5% drop for DIP_BUY
    "volume_surge_mult": 2.0,      # 2x volume
    "mid_range_min": 0.20,
    "mid_range_max": 0.80,
    "min_24h_volume": 10000,

    # Capital Efficiency (IMPLEMENTED 2026-02-09)
    "max_days_to_resolve": 90,     # Don't lock capital >90 days
    "min_annualized_return": 0.15, # Require 15%+ APY

    # Dual-Side Arbitrage (IMPLEMENTED 2026-02-09)
    "dual_side_min_profit": 0.02,  # 2% minimum profit for arb
    "dual_side_min_liquidity": 10000,  # $10k minimum per side
}
```

### 7.2 Environment Variables

```bash
# Polymarket CLOB
CLOB_API_KEY=...
CLOB_SECRET=...
CLOB_PASSPHRASE=...
POLYMARKET_PRIVATE_KEY=0x...

# AI
CLAUDE_API_KEY=sk-ant-...

# News
NEWS_API_KEY=...
```

---

## 8. Agent Architecture (Legacy)

The original multi-agent architecture (still available but not used by `run_simulation.py`):

### 8.1 Agent Roles

| Agent | Role | File |
|-------|------|------|
| ALPHA SCOUT | Find anomalies | `agents/alpha_scout.py` |
| BETA ANALYST | Vet opportunities | `agents/beta_analyst.py` |
| GAMMA SNIPER | Execute trades | `agents/gamma_sniper.py` |
| OMEGA GUARDIAN | Risk management | `agents/omega_guardian.py` |

### 8.2 Blackboard Pattern

Agents communicate via shared state (`blackboard.json`):

```
ALPHA → Opportunities → Blackboard
BETA  → Vetted Trades → Blackboard
GAMMA → Positions     → Blackboard
OMEGA → Risk State    → Blackboard
```

### 8.3 State Management (`RedisState`)

- In-memory fallback when Redis unavailable
- JSON persistence for crash recovery
- Atomic writes (temp file → rename)
- TTL-based expiration for opportunities

---

## 9. Specialized Scanners

### 9.1 Binance Arbitrage Scanner (`agents/binance_arb.py`)

**Purpose:** Find mispricings between Binance spot prices and Polymarket crypto predictions.

**Logic:**
1. Get current Binance prices (BTC, ETH, etc.)
2. Find Polymarket markets about crypto prices
3. Calculate implied probability from Binance
4. Compare to Polymarket price
5. Signal if gap >= 5%

**Probability Model:**
```python
def calculate_implied_probability(current, target, direction, days=30):
    daily_vol = 0.03  # 60% annual volatility
    expected_move = daily_vol * sqrt(days)

    if direction == "ABOVE":
        if current >= target:
            return 0.85 + (current - target) / target * 0.1
        else:
            return max(0.05, 0.5 - distance / expected_move * 0.5)
```

### 9.2 Volatility Arbitrage Scanner (`agents/volatility_arb.py`)

**Purpose:** Find dual-side arbitrage when YES + NO < $1.00

**Logic:**
```python
yes_price = bestAsk
no_price = 1 - bestBid
total_cost = yes_price + no_price

if total_cost < 0.98:  # 2% minimum profit
    # BUY BOTH SIDES
    # One MUST pay $1.00, guaranteed profit
    profit = 1.00 - total_cost
```

**Reference:** Account88888 made $645K with 96% win rate using this strategy.

---

## 10. Known Issues, Bugs & Problems

### 10.1 CRITICAL BUGS (Fixed)

#### Bug #1: NO Position P&L Calculation Error

**Symptom:** NO positions showed fake -95% losses even when profitable.

**Root Cause:** `check_exits()` used YES price (`bestAsk`) directly for all positions. For NO positions, this compared $0.04 (YES price) to $0.96 (NO entry price), showing massive fake loss.

**Fix Applied:**
```python
# BEFORE (BROKEN):
current_price = yes_price  # Wrong for NO positions!

# AFTER (FIXED):
if position["side"] == "NO":
    current_price = 1.0 - yes_price  # NO value = 1 - YES price
else:
    current_price = yes_price
```

**Impact:** Without this fix, take-profit/stop-loss would trigger incorrectly.

---

#### Bug #2: Gamma API conditionId Filter Broken

**Symptom:** `get_market_price()` returned wrong prices, showing +170% fake profit on Thunder position.

**Root Cause:** API parameter `?conditionId=X` does NOT filter - it returns 20 random markets. The first market had `bestAsk=1.00` (old resolved market), which was used as current price.

**Fix Applied:**
```python
# BEFORE (BROKEN):
params = {"conditionId": condition_id}  # Returns random markets!
async with session.get(API, params=params) as resp:
    market = (await resp.json())[0]  # WRONG MARKET!
    return market.get("bestAsk")

# AFTER (FIXED):
params = {"limit": 200, "active": "true", "closed": "false"}
async with session.get(API, params=params) as resp:
    markets = await resp.json()
    for m in markets:
        if m.get("conditionId") == condition_id:
            return float(m.get("bestAsk") or 0)
```

**Impact:** Without this fix, P&L calculations were completely unreliable.

---

#### Bug #3: MID_RANGE Strategy Never Selected

**Symptom:** All positions were NEAR_ZERO, none were MID_RANGE despite opportunities existing.

**Root Cause:** Opportunities were sorted by confidence. NEAR_ZERO (0.95) always beat MID_RANGE (0.55), so MID_RANGE never made it to the top 5 executed.

**Fix Applied:**
```python
# BEFORE (BROKEN):
opportunities.sort(key=lambda x: x["confidence"], reverse=True)
return opportunities[:10]  # MID_RANGE never makes it

# AFTER (FIXED):
# Ensure strategy diversity: pick best from each strategy
by_strategy = {}
for opp in opportunities:
    strat = opp["strategy"]
    if strat not in by_strategy:
        by_strategy[strat] = []
    by_strategy[strat].append(opp)

# Pick top 2 from each strategy first
diverse_opps = []
for strat in ["NEAR_CERTAIN", "NEAR_ZERO", "MID_RANGE", "DIP_BUY", "VOLUME_SURGE"]:
    if strat in by_strategy:
        diverse_opps.extend(by_strategy[strat][:2])
```

**Impact:** Now we have strategy diversity for proper A/B testing.

---

### 10.2 FIXED PROBLEMS (Resolved 2026-02-09)

#### Problem #1: Capital Locked for Months ✅ FIXED

**Symptom:** Only 3 of 8 positions resolve within 60 days. The rest lock capital for 4-11 months.

**Fix Applied:** Implemented annualized return calculation with capital efficiency filter:
```python
def calculate_annualized_return(raw_return: float, days: int) -> float:
    """Convert raw return to annualized return."""
    if days <= 0:
        return 0.0
    return ((1 + raw_return) ** (365 / days)) - 1

# In find_opportunities():
days_to_resolve = (parse(end_date) - now).days
if days_to_resolve > 90:
    continue  # Skip markets resolving >90 days

annualized = calculate_annualized_return(raw_return, days_to_resolve)
if annualized < 0.15:  # Require 15%+ APY
    continue
```

**Result:** Future trades will only enter markets with 15%+ annualized return and <90 day resolution.

**Example Filtering:**
| Position | Days | Raw Return | Annualized | Passes Filter? |
|----------|------|------------|------------|----------------|
| U.S. Revenue | 18 | 4.3% | 119% APY | ✅ YES |
| Elon budget | 18 | 2.1% | 49% APY | ✅ YES |
| Rob Jetten | 324 | 1.3% | 1.5% APY | ❌ NO |
| Thunder NBA | 141 | ~5% | 15% APY | ✅ MARGINAL |

**Note:** Existing positions (8 total) were entered before this filter was implemented. They remain in portfolio and will be monitored until resolution. New entries will respect the filter.

---

### 10.3 ACTIVE PROBLEMS (Unfixed)

#### Problem #1: DIP_BUY and VOLUME_SURGE Never Trigger

**Symptom:** 8 positions total, 0 are DIP_BUY or VOLUME_SURGE.

**Root Cause:** Thresholds may be too strict for current market conditions:
- DIP_BUY requires -5% drop AND volume > $30k
- VOLUME_SURGE requires 2x hourly average AND price change < 5%

**Analysis Needed:** Log all markets that ALMOST qualify to tune thresholds.

---

#### Problem #2: Market Resolution Timing Unreliable

**Symptom:** Trump deportations market has `endDate: 2025-12-31` (41 days ago) but still active.

**Impact:** Cannot reliably predict when positions will resolve.

**Possible Causes:**
1. Polymarket delays resolution after end date
2. End date in API is incorrect
3. Resolution depends on external data source availability

---

#### Problem #3: Strategy A/B Test Has No Completed Trades

**Symptom:** All strategy_metrics show 0 trades, 0 wins, $0 P&L.

**Root Cause:** No positions have exited yet:
- NEAR_CERTAIN/NEAR_ZERO: Wait for resolution (weeks/months)
- MID_RANGE: Only 1 position, hasn't hit TP/SL yet

**Result:** Cannot determine which strategy is best.

---

#### Problem #4: Wallet Not Funded for Live Trading

**Current State:**
- Simulation: $1,000 virtual
- Live wallet: ~$2 USDC.e (insufficient)
- Minimum needed: $50+ for meaningful trades

**Blockers:**
- Need to fund wallet with USDC.e on Polygon
- Need POL for gas fees
- Need to verify CLOB API credentials

---

### 10.4 ARCHITECTURAL ISSUES

#### Issue #1: Single-Threaded Scanning

**Problem:** Scanning 200 markets sequentially is slow.

**Impact:** Opportunities may disappear before execution.

**Solution Needed:** Parallel market fetching, websocket for real-time updates.

---

#### Issue #2: No Position Monitoring Dashboard

**Problem:** Must run `python report.py` manually to check status.

**Solution Needed:** Web dashboard or Discord bot for real-time monitoring.

---

#### Issue #3: Binance Arb Not Integrated

**Problem:** `binance_arb.py` runs standalone, not in main loop.

**Impact:** Missing potential cross-exchange arbitrage opportunities.

**Note:** Volatility/Dual-Side Arb is now integrated as `DUAL_SIDE_ARB` strategy.

---

### 10.5 NOT YET IMPLEMENTED

| Feature | Status | Priority | Notes |
|---------|--------|----------|-------|
| `max_days_to_resolve` filter | ✅ DONE | - | Capital efficiency implemented |
| Dual-side arb integration | ✅ DONE | - | DUAL_SIDE_ARB strategy |
| Binance arb integration | Standalone | MEDIUM | Cross-exchange alpha |
| Position exit on resolution | Not handled | HIGH | Auto-claim winnings |
| Discord/Telegram alerts | Not built | LOW | Phase 3 |
| Web dashboard | Not built | LOW | Phase 3 |
| Live trading | Dry run only | BLOCKED | Needs wallet funding |
| Historical backtest | Not built | MEDIUM | Validate strategies |

---

### 10.6 RISK ASSESSMENT

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| API returns stale data | Medium | High | Validate prices before trade |
| Market resolves wrong way | Low | High | Diversify positions |
| Wallet drained by bug | Low | Critical | Paper trade first, low limits |
| Claude API over budget | Medium | Low | Daily limit + fallback |
| Polymarket goes down | Low | Medium | Graceful degradation |

---

## 11. Run Commands

```bash
# Simulation mode (paper trading)
python sovereign_hive/run_simulation.py

# Live trading (real money - requires funding)
python sovereign_hive/run_simulation.py --live

# Reset portfolio to $1,000
python sovereign_hive/run_simulation.py --reset

# Quick portfolio report
python sovereign_hive/report.py

# Full detailed report
python sovereign_hive/report.py --full

# Background autonomous mode
nohup python -u sovereign_hive/run_simulation.py > sovereign_hive/sim.log 2>&1 &

# Check logs
tail -50 sovereign_hive/sim.log

# Run Binance arbitrage scanner
python sovereign_hive/agents/binance_arb.py

# Run volatility arbitrage scanner
python sovereign_hive/agents/volatility_arb.py

# Legacy multi-agent system
python sovereign_hive/run_hive.py --scan
python sovereign_hive/run_hive.py --status
```

---

## 12. File Structure

```
sovereign_hive/
├── run_simulation.py      # Main trading engine (USE THIS)
├── run_hive.py            # Legacy multi-agent orchestrator
├── run_async_hive.py      # Async version of legacy system
├── report.py              # Portfolio reporting tool
├── GOALS.md               # Project goals and roadmap
├── ARCHITECTURE.md        # This document
│
├── data/
│   ├── portfolio_sim.json # Simulation portfolio state
│   └── portfolio_live.json # Live portfolio state
│
├── agents/
│   ├── alpha_scout.py     # Market scanner agent
│   ├── beta_analyst.py    # Opportunity vetter
│   ├── gamma_sniper.py    # Trade executor
│   ├── omega_guardian.py  # Risk manager
│   ├── binance_arb.py     # Binance arbitrage scanner
│   ├── volatility_arb.py  # Dual-side arb scanner
│   ├── async_*.py         # Async versions
│   └── ...
│
├── core/
│   ├── claude_analyzer.py # Claude AI integration
│   ├── async_executor.py  # Order execution
│   ├── redis_state.py     # State management
│   ├── simulation.py      # Simulation logic
│   └── ...
│
└── blackboard.json        # Shared agent state (legacy)
```

---

## 13. Security Considerations

### 13.1 Secrets Management

**Required in `.env`:**
- `POLYMARKET_PRIVATE_KEY` - Wallet private key (NEVER commit)
- `CLOB_API_KEY`, `CLOB_SECRET`, `CLOB_PASSPHRASE` - API credentials
- `CLAUDE_API_KEY` - Anthropic API key
- `NEWS_API_KEY` - NewsAPI key

### 13.2 Risk Controls

- Max 10% per position
- Max 10 positions
- 15% stop loss
- Claude API daily limit (50 calls)
- Dry run by default
- Live mode requires explicit `--live` flag and confirmation

---

## 14. Glossary

| Term | Definition |
|------|------------|
| **bestAsk** | Lowest price to buy YES |
| **bestBid** | Highest price to sell YES (or buy NO) |
| **conditionId** | Unique market identifier (0x...) |
| **CLOB** | Central Limit Order Book |
| **Gamma API** | Polymarket's REST API for market data |
| **NO position** | Bet that event will NOT happen |
| **Resolution** | When market outcome is determined |
| **Shares** | Units of YES or NO tokens |
| **YES position** | Bet that event WILL happen |

---

## 15. Contact & Support

**Repository Issues:** Report bugs and feature requests
**Strategy Questions:** Document your findings in `lessons.md`
**Architecture Changes:** Update this document

---

*Document generated for agent review. Last updated: 2026-02-09*
