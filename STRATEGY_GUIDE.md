# QuesQuant Strategy Guide

A meticulous explanation of every trading strategy in the Sovereign Hive simulation engine.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Strategy 1: NEAR_CERTAIN](#strategy-1-near_certain)
3. [Strategy 2: NEAR_ZERO](#strategy-2-near_zero)
4. [Strategy 3: DIP_BUY](#strategy-3-dip_buy)
5. [Strategy 4: VOLUME_SURGE](#strategy-4-volume_surge)
6. [Strategy 5: MID_RANGE](#strategy-5-mid_range)
7. [Strategy 6: MEAN_REVERSION](#strategy-6-mean_reversion)
8. [Strategy 7: DUAL_SIDE_ARB](#strategy-7-dual_side_arb)
9. [Strategy 8: MARKET_MAKER](#strategy-8-market_maker)
10. [Strategy 9: BINANCE_ARB](#strategy-9-binance_arb)
11. [Position Sizing: Kelly Criterion](#position-sizing-kelly-criterion)
12. [Exit Logic](#exit-logic)
13. [Opportunity Pipeline](#opportunity-pipeline)
14. [Known Issues & Proposed Fixes](#known-issues--proposed-fixes)

---

## System Architecture

### How a Trading Cycle Works

Every 60 seconds, the engine runs `run_cycle()`:

1. **Check Exits** — Loops through all open positions. For each one, checks if take-profit, stop-loss, or strategy-specific exit conditions are met. If so, sells.
2. **Scan Markets** — Fetches all active Polymarket markets via their API. Also fetches Binance spot prices for crypto arbitrage.
3. **Find Opportunities** — Passes every market through all 9 strategy scanners. Each scanner independently checks if that market qualifies as an opportunity for its strategy.
4. **Deduplicate & Rank** — Groups opportunities by strategy, sorts each group by annualized return, picks the top N from each strategy (2 per strategy, 4 for MARKET_MAKER and BINANCE_ARB).
5. **Evaluate** — For the top 5 opportunities overall, checks: (a) not already holding this market, (b) not at max positions (12), (c) confidence >= 0.55, (d) for DIP_BUY/VOLUME_SURGE, requires bullish news from Claude AI.
6. **Execute** — If evaluation passes, sizes the position and records the trade.

### Global Configuration

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `initial_balance` | $1,000 | Starting virtual capital |
| `max_position_pct` | 15% | Max % of balance per trade |
| `max_positions` | 12 | Max simultaneous open positions |
| `take_profit_pct` | +10% | Default take-profit trigger |
| `stop_loss_pct` | -5% | Default stop-loss trigger |
| `min_confidence` | 0.55 | Minimum confidence to execute any trade |
| `min_liquidity` | $5,000 | Minimum market liquidity |
| `max_days_to_resolve` | 90 | Skip markets resolving beyond 90 days |
| `min_annualized_return` | 15% | Minimum APY for resolution strategies |
| `scan_interval` | 60s | Seconds between scan cycles |

### Position Size Cap

All trades are capped at the **minimum** of:
- `max_position_pct` * balance (15% of bankroll = $150 at $1000)
- 1% of market liquidity (to prevent unrealistic fills)
- $100 hard cap per trade

Minimum position size: **$50** (anything below is rejected as too small to matter).

---

## Strategy 1: NEAR_CERTAIN

**Category:** Resolution Arbitrage (Passive)
**Turnover:** Slow (weeks to months)
**Side:** Always buys YES

### Concept

Buy YES shares in markets where the outcome is nearly guaranteed (YES price >= 95%). When the market resolves, each YES share pays $1.00. The profit is the small gap between the purchase price and $1.00.

**Example:** "Will the sun rise tomorrow?" is trading at YES = $0.97. Buy at $0.97, receive $1.00 on resolution. Profit = $0.03/share (3.1%).

### Entry Logic (Scanner)

```
IF best_ask >= 0.95
AND days_to_resolve <= 90
AND annualized_return >= 15%
THEN → NEAR_CERTAIN opportunity
```

Step by step:
1. Check if YES price (best_ask) is at or above 95 cents
2. Parse the market's end date, calculate days until resolution
3. Skip if resolution is more than 90 days away (capital efficiency filter)
4. Calculate raw return: `(1.00 - price) / price`
5. Annualize it: `((1 + raw_return) ^ (365 / days)) - 1`
6. Only proceed if annualized return >= 15%

**Annualization Examples:**
| Buy Price | Raw Return | Days to Resolve | Annualized |
|-----------|------------|-----------------|------------|
| $0.98 | 2.04% | 7 days | 181% APY |
| $0.98 | 2.04% | 30 days | 27.5% APY |
| $0.98 | 2.04% | 180 days | 4.2% APY (REJECTED) |
| $0.95 | 5.26% | 14 days | 265% APY |

### Entry Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `near_certain_min` | 0.95 | Minimum YES price to qualify |
| `max_days_to_resolve` | 90 | Maximum days until resolution |
| `min_annualized_return` | 0.15 | Minimum 15% annualized return |

### Opportunity Output

```python
{
    "strategy": "NEAR_CERTAIN",
    "side": "YES",
    "price": 0.98,               # best_ask
    "expected_return": 0.0204,    # raw return
    "annualized_return": 1.81,    # APY
    "days_to_resolve": 7,
    "confidence": 0.95,           # Fixed high confidence
    "reason": "Near-certain 98%, 7d, 181% APY"
}
```

### Exit Logic

Standard take-profit (+10%) / stop-loss (-5%). In practice, these rarely trigger because the position is held until market resolution at $1.00.

### Position Sizing

Uses **Kelly Criterion** (see dedicated section below). With confidence=0.95 and a small edge (2-5%), Kelly typically sizes this at $50-80.

### Risk Profile

- **Win rate:** Very high (~95%) when markets are correctly identified
- **Loss scenario:** Market resolves NO (the "certain" outcome doesn't happen). Loss = entire position.
- **Capital lock:** Main risk. Capital is frozen until resolution — could be weeks/months.
- **Liquidity risk:** Can't exit early without finding a buyer.

---

## Strategy 2: NEAR_ZERO

**Category:** Resolution Arbitrage (Passive)
**Turnover:** Slow (weeks to months)
**Side:** Always buys NO

### Concept

The mirror of NEAR_CERTAIN. When YES is trading below 5%, it means NO is near-certain. Buy NO shares cheap, wait for the market to resolve NO, collect $1.00 per share.

**Example:** "Will aliens land on Earth by March?" YES = $0.02, so NO = $0.98. Buy NO at $0.98, receive $1.00 on resolution. Profit = $0.02/share.

### Entry Logic (Scanner)

```
IF best_ask > 0 AND best_ask <= 0.05
AND days_to_resolve <= 90
AND annualized_return >= 15%
AND no_price < 0.98  (safety: don't buy NO at near $1.00)
THEN → NEAR_ZERO opportunity
```

Step by step:
1. YES price (best_ask) must be at or below 5 cents
2. Calculate NO price: `1.0 - best_bid` (if bid exists) or `1.0 - best_ask`
3. Skip if NO price is already >= $0.98 (no room for profit)
4. Apply same capital efficiency filters: <=90 days, >=15% APY
5. Calculate return based on NO price: `(1.00 - no_price) / no_price`

### Entry Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `near_zero_max` | 0.05 | Maximum YES price (means NO >= 95%) |
| `max_days_to_resolve` | 90 | Maximum days until resolution |
| `min_annualized_return` | 0.15 | Minimum 15% annualized return |

### Exit Logic

Standard take-profit (+10%) / stop-loss (-5%). For NO positions, the current value is calculated as `1.0 - yes_price`, so if YES drops further, the NO position gains value.

### Position Sizing

Uses **Kelly Criterion**. The edge calculation inverts the prices for NO bets: `estimated_prob = 1 - estimated_prob` and `market_price = 1 - market_price` inside the Kelly calculator.

### Risk Profile

Same as NEAR_CERTAIN but in reverse. Risk = the "impossible" event actually happens.

---

## Strategy 3: DIP_BUY

**Category:** Momentum / News-driven (Active)
**Turnover:** Fast (7-day target)
**Side:** Always buys YES

### Concept

When a market drops >5% in 24 hours, buy the dip — assuming the drop is an overreaction and the price will recover. This strategy requires **bullish news confirmation** from Claude AI before executing.

**Example:** "Will Trump win the election?" drops from $0.60 to $0.55 (-8.3% in 24h). If Claude AI finds bullish news, buy YES expecting recovery.

### Entry Logic (Scanner)

```
IF price_change_24h < -5%
AND volume_24h > $30,000
THEN → DIP_BUY opportunity (pending news check)
```

Step by step:
1. Check if 24h price change is below -5% (the dip)
2. Require $30k+ 24h volume (avoids illiquid markets where dips are noise)
3. Expected return = magnitude of the drop (e.g., -8% drop → expect 8% recovery)
4. Annualized based on 7-day expected hold

### News Gate (Evaluation Phase)

**This is unique to DIP_BUY.** After the scanner flags an opportunity, the evaluator runs:

```python
news = await self.news.analyze_market(question)
if news.get("direction") != "BULLISH" or news.get("confidence", 0) < 0.6:
    return False  # Skip — news doesn't support a recovery
```

This calls the NewsAPI to fetch recent articles, then sends the headline to Claude AI for sentiment analysis. Only executes if Claude says the news is bullish with 60%+ confidence.

### Entry Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `dip_threshold` | -0.05 | Minimum 5% drop to qualify |
| Volume floor | $30,000 | Hardcoded minimum 24h volume |
| Expected hold | 7 days | Used for APY calculation |

### Exit Logic

Standard take-profit (+10%) / stop-loss (-5%).

### Position Sizing

Uses **Kelly Criterion** with `confidence: 0.65` (moderate — dip buys are speculative).

### Risk Profile

- **Win rate:** Moderate. Dips can be real crashes, not just overreactions.
- **Dependency:** Relies on Claude AI news analysis and NewsAPI key being set.
- **Capital efficiency:** 7-day target is good for turnover.

---

## Strategy 4: VOLUME_SURGE

**Category:** Smart Money Signal (Active)
**Turnover:** Fast (7-day target)
**Side:** Follows momentum (YES if price going up, NO if going down)

### Concept

When 1-hour volume is 2x+ the hourly average, it signals "smart money" entering the market. Follow the momentum direction.

**Example:** A market normally trades $10k/day ($416/hour). Suddenly, $1,200 trades in one hour (2.9x normal). If the price is rising, buy YES. If falling, buy NO.

### Entry Logic (Scanner)

```
hourly_avg = volume_24h / 24
IF volume_1h > hourly_avg * 2.0
AND abs(price_change_24h) < 5%  (not already a dip/spike — avoid overlap)
THEN → VOLUME_SURGE opportunity
```

Step by step:
1. Calculate average hourly volume: `volume_24h / 24`
2. Compare 1-hour volume to the average
3. Require 2x surge (i.e., this hour has double the normal volume)
4. Filter OUT markets that already moved >5% (those are DIP_BUY candidates, not volume surge)
5. Direction follows price momentum: positive change → YES, negative → NO

### Entry Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `volume_surge_mult` | 2.0 | 2x hourly average required |
| Price change filter | <5% | Avoids overlap with DIP_BUY |
| Expected return | 10% fixed | Assumed recovery target |
| Expected hold | 7 days | Used for APY calculation |

### News Gate

Like DIP_BUY, VOLUME_SURGE also goes through the Claude AI news check during evaluation. However, it doesn't strictly require bullish news — it just logs the sentiment.

### Exit Logic

Standard take-profit (+10%) / stop-loss (-5%).

### Position Sizing

Uses **Kelly Criterion** with `confidence: 0.60` (lowest of all strategies — pure volume signal is noisy).

### Risk Profile

- **Win rate:** Uncertain. Volume surges can be noise, bot activity, or genuine smart money.
- **Rare trigger:** A genuine 2x volume surge with <5% price change is uncommon.
- **Dependency:** Requires accurate `volume1hr` data from Polymarket API.

---

## Strategy 5: MID_RANGE

**Category:** Momentum Trading (Active)
**Turnover:** Fast (5-day target)
**Side:** Follows momentum (YES if uptrend, NO if downtrend)

### Concept

Trade markets in the 20-80% probability range where there's room for the price to move in either direction. Follow the short-term momentum: if the price is trending up, buy YES. If trending down, buy NO.

**Example:** A market at 45% is rising (+1.2% today). Buy YES expecting continued upward momentum. Take profit at +10% or stop-loss at -5%.

### Entry Logic (Scanner)

```
IF 0.20 <= best_ask <= 0.80
AND volume_24h >= $10,000
AND price_change_24h > +0.5% → BUY YES (upward momentum)
   OR price_change_24h < -0.5% → BUY NO (downward momentum)
THEN → MID_RANGE opportunity
```

Step by step:
1. Price must be between 20% and 80% (the "mid range" — enough room to move)
2. Minimum $10k 24h volume
3. Check momentum direction:
   - If 24h change > +0.5%: buy YES (follow the uptrend)
   - If 24h change < -0.5%: buy NO (follow the downtrend)
   - If change is between -0.5% and +0.5%: skip (no clear momentum)
4. For NO trades, price = `1.0 - best_bid`
5. Expected return = take_profit_pct (10%), annualized over 5-day target

### Entry Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `mid_range_min` | 0.20 | Min price (20%) |
| `mid_range_max` | 0.80 | Max price (80%) |
| `min_24h_volume` | $10,000 | Volume floor |
| Momentum threshold | 0.5% | Min 24h change to confirm direction |
| Expected hold | 5 days | Used for APY calculation |

### Exit Logic

Standard take-profit (+10%) / stop-loss (-5%).

### Position Sizing

Uses **Kelly Criterion** with `confidence: 0.55` (just above minimum). This is the problem — with low confidence and moderate edge, Kelly sizes positions below the $50 minimum, so trades never execute.

### Risk Profile

- **Win rate:** Moderate. Momentum can reverse.
- **Known issue:** Kelly sizing kills this strategy. Position sizes come out ~$14-30, below the $50 minimum.
- **Fix needed:** Disable Kelly for MID_RANGE (use fixed 15% of balance instead).

---

## Strategy 6: MEAN_REVERSION

**Category:** Contrarian / Statistical (Active)
**Turnover:** Medium (7-day target)
**Side:** Depends on price level (YES if too low, NO if too high)

### Concept

When a market's price deviates far from the 50% midpoint, bet that it will revert back toward the center. Buy YES when price is below 30%. Buy NO when price is above 70%.

**Backtested result:** +52% return, 1.05 Sharpe ratio, 18.6% max drawdown.

**Example:** A market at 22% (YES = $0.22). Historical mean is ~50%. Buy YES expecting price to climb back toward 50%. Take profit at +10%.

### Entry Logic (Scanner)

```
IF volume_24h >= $10,000
AND NOT on cooldown (48h per market)
AND entry_count < 2 (max 2 entries per market)
THEN:
  IF best_ask < 0.30 AND best_ask > 0.05 → BUY YES (price too low)
  IF best_ask > 0.70 AND best_ask < 0.95 → BUY NO (price too high)
→ MEAN_REVERSION opportunity
```

Step by step:
1. Minimum $10k 24h volume
2. **Cooldown check:** Each market has a 48-hour cooldown (`MR_COOLDOWN_HOURS`) after the last exit. This prevents re-entering a market that just stopped us out.
3. **Entry count check:** Maximum 2 entries per market ever (`MR_MAX_ENTRIES`). After 2 attempts, the strategy gives up on that market.
4. If price < 30% and > 5%: buy YES (reversion upward expected)
5. If price > 70% and < 95%: buy NO (reversion downward expected)
6. The 5% and 95% guards prevent overlap with NEAR_ZERO and NEAR_CERTAIN

### Anti-Re-Entry System

Mean reversion has a built-in protection against chasing losing positions:

```python
# Per-market state
self.mr_cooldowns = {}      # {condition_id: last_exit_time}
self.mr_entry_counts = {}   # {condition_id: number_of_entries}
MR_COOLDOWN_HOURS = 48      # Wait 48h after exit before re-entering
MR_MAX_ENTRIES = 2           # Max 2 entries per market, ever
```

When a MEAN_REVERSION trade exits (either TP or SL), the scanner records the exit time. For the next 48 hours, it won't re-enter that market. After 2 total entries in a market, it's permanently blacklisted for mean reversion.

### Entry Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `mean_reversion_low` | 0.30 | Buy YES below this |
| `mean_reversion_high` | 0.70 | Buy NO above this |
| `mean_reversion_tp` | 0.10 | 10% take profit |
| `mean_reversion_sl` | -0.05 | 5% stop loss |
| Cooldown | 48 hours | Per-market cooldown after exit |
| Max entries | 2 | Max entries per market |
| Floor/ceiling | 5% / 95% | Avoids overlap with NEAR strategies |

### Exit Logic

Standard take-profit (+10%) / stop-loss (-5%). On exit, the cooldown timer starts for that market.

### Position Sizing

**Kelly is DISABLED** for MEAN_REVERSION. Uses fixed `max_position_pct` (15%) instead. This was a critical fix — Kelly was too conservative for the moderate edges in mean reversion, resulting in positions below the $50 minimum.

```python
# In execute_trade():
if CONFIG.get("use_kelly", False) and opp["strategy"] not in ["DUAL_SIDE_ARB", "MARKET_MAKER", "MEAN_REVERSION"]:
    # Kelly sizing
else:
    # Fixed 15% of balance
```

### Risk Profile

- **Win rate:** ~60-65% in backtests
- **Key risk:** Prices can stay "extreme" for a long time (a 20% market can go to 10% before reverting)
- **Capital efficiency:** 7-day target with tight SL means fast turnover
- **Best performer in backtest** of all 9 strategies

---

## Strategy 7: DUAL_SIDE_ARB

**Category:** Pure Arbitrage (Risk-Free)
**Turnover:** Slow (waits for resolution, up to 30 days)
**Side:** BOTH (buys YES and NO simultaneously)

### Concept

On Polymarket, every market has YES and NO shares. When the market resolves, exactly one side pays $1.00. If you can buy YES + NO for less than $1.00 total, you lock in a guaranteed profit.

**Example:** YES = $0.45 (best_ask), NO = $0.53 (calculated as 1.0 - best_bid at $0.47). Total = $0.98. Buy both for $0.98, receive $1.00 on resolution. Guaranteed $0.02/share profit (2.04%).

### Entry Logic (Scanner)

```
IF best_ask > 0 AND best_bid > 0
AND liquidity >= $10,000
AND yes_price + no_price < (1.00 - 0.02)  [total < $0.98]
THEN → DUAL_SIDE_ARB opportunity
```

Step by step:
1. Both bid and ask must exist (market is active)
2. Minimum $10k liquidity per side
3. Calculate YES cost: `best_ask` (what you pay to buy YES)
4. Calculate NO cost: `1.0 - best_bid` (what you pay to buy NO)
5. Total cost must be less than $0.98 (at least 2% guaranteed profit)
6. Profit per share = `1.00 - total_cost`

### Entry Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `dual_side_min_profit` | 0.02 | Minimum 2% guaranteed profit |
| `dual_side_min_liquidity` | $10,000 | Min liquidity per side |

### Execution (Special)

Dual-side arb has a completely separate execution function `_execute_dual_side_arb()`:

1. Split the total amount proportionally: `yes_amount = total * (yes_price / total_cost)`
2. Record as a single position with `side="BOTH"`
3. The locked profit is calculated immediately: `payout - cost`

### Exit Logic (Special)

DUAL_SIDE_ARB positions bypass the normal TP/SL logic entirely:

```python
if position["side"] == "BOTH":
    # No TP/SL — profit is locked, just wait for resolution
    # Only exit on 30-day timeout
    if hold_hours >= 30 * 24:
        sell at entry_price (break even, exit timeout)
    continue  # Skip all other exit checks
```

- No take-profit (profit is locked at entry)
- No stop-loss (position can't lose value — profit is guaranteed)
- Only exits on 30-day timeout (exits at cost basis to free capital)

### Position Sizing

Kelly is DISABLED for DUAL_SIDE_ARB (uses fixed 15% sizing). Makes sense because this is arbitrage, not a directional bet.

### Risk Profile

- **Win rate:** 100% in theory (guaranteed profit)
- **Reality:** These opportunities are extremely rare. Market makers keep YES + NO very close to $1.00. A 2% gap almost never exists on liquid markets.
- **Capital lock:** Must wait for market resolution to collect. Could be months.
- **Execution risk:** In live trading, you might only fill one side, leaving you with a directional bet.

---

## Strategy 8: MARKET_MAKER

**Category:** Spread Capture (Active)
**Turnover:** Very fast (4-hour target)
**Side:** MM (special — enters at bid, exits at ask)

### Concept

Market makers provide liquidity by posting bid and ask orders. Buy at a lower price (bid), sell at a higher price (ask), profit from the spread. This doesn't bet on direction — it profits from the bid-ask gap.

**Example:** Market mid-price is $0.50. Post bid at $0.49 (mid - 2%) and ask at $0.51 (mid + 2%). If both fill, profit = $0.02/share (4% round trip).

### Entry Logic (Scanner)

```
IF NOT meme_market
AND 0.15 <= best_ask <= 0.85
AND best_bid > 0
AND volume_24h >= $15,000
AND liquidity >= $30,000
AND 2% <= spread_pct <= 10%
THEN → MARKET_MAKER opportunity
```

Step by step:
1. **Meme filter:** Skip markets about Jesus, aliens, flat earth, etc.
2. Price range: 15-85% (penny markets have absurd spreads, near-certain markets have none)
3. Volume: at least $15k/24h (need activity for fills)
4. Liquidity: at least $30k depth
5. Calculate spread: `(best_ask - best_bid) / midpoint`
6. Spread must be 2-10% (below 2% = no profit after fees, above 10% = too wide, won't fill)
7. Calculate our bid/ask: `bid = mid * 0.98`, `ask = mid * 1.02` (2% from mid each side)
8. If the market topic is preferred (crypto, politics, finance), confidence = 0.80; otherwise 0.65

### Meme Market Exclusion

```python
excluded_topics = [
    "jesus", "christ", "god return", "rapture", "second coming",
    "alien contact", "extraterrestrial", "supernatural",
    "flat earth", "illuminati"
]
```

Sports, entertainment, and politics markets are NOT excluded — those are legitimate for MM.

### Preferred Topics (Confidence Boost)

```python
preferred_topics = [
    "bitcoin", "btc", "ethereum", "eth", "crypto", "price",
    "trump", "biden", "election", "president", "congress",
    "fed", "interest rate", "inflation", "tariff", "economy"
]
```

If the market matches these topics, confidence is boosted from 0.65 to 0.80. This makes them more likely to pass the 0.55 minimum confidence check and get prioritized in ranking.

### Entry Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `mm_min_spread` | 0.02 | Minimum 2% spread |
| `mm_max_spread` | 0.10 | Maximum 10% spread |
| `mm_min_volume_24h` | $15,000 | Min 24h volume |
| `mm_min_liquidity` | $30,000 | Min liquidity depth |
| `mm_target_profit` | 0.01 | 1% target per round trip |
| `mm_max_hold_hours` | 4 | Exit if not filled in 4h |
| `mm_price_range` | (0.15, 0.85) | Valid price range |

### Execution (Special)

Market maker has a dedicated execution function `_execute_market_maker()`:

1. Entry price = our bid (`mid * 0.98`)
2. Records position with `side="MM"`
3. Stores MM-specific metadata: `mm_bid`, `mm_ask`, `mm_entry_time`, `mm_target_profit`

### Exit Logic (Special — 3 Conditions)

MM positions bypass normal TP/SL and use `_check_mm_exit()`:

**Condition 1: FILLED (Profit)**
```
IF current_price >= mm_ask → Sell at mm_ask
```
Price reached our ask level. Our ask order is "filled." Profit = ask - bid spread.

**Condition 2: STOP LOSS (Cut losses)**
```
IF (current_price - entry_price) / entry_price <= -3% → Sell at market
```
Price dropped 3% below our entry. Cut the loss. MM uses a tighter stop (-3%) than standard strategies (-5%) because we're trading frequently.

**Condition 3: TIMEOUT (Didn't fill)**
```
IF hold_hours >= 4 → Sell at market
```
We've held for 4 hours without price reaching our ask. Exit at current market price. This could be a small profit, small loss, or breakeven.

### Position Sizing

Kelly is DISABLED for MARKET_MAKER (uses fixed 15% sizing). This makes sense — MM profit comes from spread capture, not edge estimation.

### Risk Profile

- **Win rate:** ~70-80% (realistic, with 60% fill probability and 0.2% slippage)
- **Loss scenario:** Price moves against our bid before our ask fills
- **Capital efficiency:** Excellent — 4-hour cycle means capital rotates quickly
- **Best performing in simulation** (+$25.85, 8 trades, 100% win rate — though this may be partly due to favorable market conditions)

---

## Strategy 9: BINANCE_ARB

**Category:** Cross-Exchange Arbitrage (Active)
**Turnover:** Medium (7-day target)
**Side:** Depends on edge direction (YES if Polymarket underprices, NO if overprices)

### Concept

Polymarket has crypto price prediction markets ("Will Bitcoin hit $100k?"). Binance has real-time spot prices. When Polymarket's implied probability lags behind what Binance prices suggest, there's an arbitrage opportunity.

**Example:** Binance shows BTC at $95,000. Polymarket "Will BTC hit $100k?" is at YES = $0.30. Binance-implied probability for BTC hitting $100k is ~45%. Edge = 45% - 30% = +15%. Buy YES.

### Entry Logic (Scanner)

```
IF market question mentions bitcoin/ethereum/solana
AND market is about a price target ("price", "above", "below", "hit", "$")
AND liquidity >= $10,000
AND |edge| >= 5%
THEN → BINANCE_ARB opportunity
```

Step by step:
1. **Crypto detection:** Parse market question for "bitcoin", "btc", "ethereum", "eth", "solana", "sol"
2. **Price target extraction:** Use regex to find dollar amounts (`$100,000`, `$100k`, `$1m`)
3. **Direction detection:** Check for "above"/"below"/"under" keywords
4. **Binance price fetch:** Get current spot price from Binance API
5. **Implied probability calculation:** Model-based estimate of whether crypto will reach the target
6. **Edge calculation:** `edge = binance_implied_prob - polymarket_prob`
7. If |edge| >= 5%, it's an opportunity

### Implied Probability Model

The engine uses a **distance-based volatility model** to estimate probability:

```python
daily_vol = 0.03  # ~3% daily volatility for crypto
expected_move = daily_vol * sqrt(days_to_expiry)  # ~30-day window

if direction == "ABOVE":
    if current_price >= target:
        prob = 0.85 + bonus  # Already above target
    else:
        distance = (target - current_price) / current_price
        prob = max(0.05, 0.5 - distance / expected_move * 0.5)
```

This isn't a Black-Scholes model — it's a simplified heuristic. For BTC at $70k targeting $1M, the distance is so large that the probability is near-zero regardless of volatility.

### Entry Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `binance_min_edge` | 0.05 | Minimum 5% edge |
| `binance_min_liquidity` | $10,000 | Min market liquidity |
| `binance_symbols` | BTC, ETH, SOL | Cryptos tracked |
| Daily volatility | 3% | Assumed crypto daily vol |

### Exit Logic

Standard take-profit (+10%) / stop-loss (-5%). For NO positions, value = `1 - yes_price`.

### Position Sizing

Uses **Kelly Criterion**. Confidence = `min(0.95, 0.70 + |edge|)`. So a 15% edge gives 0.85 confidence.

### Risk Profile

- **Win rate:** Depends on model accuracy. The volatility model is simplistic.
- **Known issue:** Often finds the SAME market every cycle (e.g., "Will BTC hit $1M?") because the edge is persistent. Once holding that market, all future opportunities are rejected as duplicates.
- **Concentration risk:** Only 3 crypto assets tracked. Limited opportunity universe.
- **Model risk:** 3% daily vol assumption may not hold during low-volatility periods.

---

## Position Sizing: Kelly Criterion

### Formula

For prediction markets, the Kelly formula simplifies to:

```
f* = (estimated_prob - market_price) / (1 - market_price)
```

Where:
- `f*` = optimal fraction of bankroll to bet
- `estimated_prob` = what we think the true probability is
- `market_price` = what Polymarket is pricing the outcome at

### Fractional Kelly

Full Kelly is too aggressive (leads to ruin in practice). We use **15% fractional Kelly**:

```
adjusted_f = f* × 0.15 × confidence
```

Then cap at 15% of bankroll max (`kelly_max_position`).

### Configuration

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `use_kelly` | True | Enable Kelly sizing globally |
| `kelly_fraction` | 0.15 | 15% of full Kelly |
| `kelly_min_edge` | 0.03 | Minimum 3% edge to bet |
| `kelly_max_position` | 0.15 | Max 15% of bankroll |

### Which Strategies Use Kelly

| Strategy | Kelly? | Why |
|----------|--------|-----|
| NEAR_CERTAIN | Yes | Edge-based (price vs $1.00) |
| NEAR_ZERO | Yes | Edge-based (price vs $1.00) |
| DIP_BUY | Yes | Confidence-based sizing |
| VOLUME_SURGE | Yes | Confidence-based sizing |
| MID_RANGE | Yes | **BUG: should be disabled** |
| MEAN_REVERSION | **No** | Fixed 15% (Kelly was too conservative) |
| DUAL_SIDE_ARB | **No** | Fixed 15% (arbitrage, no edge estimation) |
| MARKET_MAKER | **No** | Fixed 15% (spread capture, no direction) |
| BINANCE_ARB | Yes | Edge from price discrepancy |

### Probability Estimation

Kelly requires an `estimated_prob` — what we think the TRUE probability is. Each strategy estimates this differently:

| Strategy | Estimation Method |
|----------|-------------------|
| NEAR_CERTAIN | `price + (1-price) * confidence * 0.5` |
| NEAR_ZERO | `price - price * confidence * 0.5` |
| BINANCE_ARB | Directly from Binance implied probability |
| DUAL_SIDE_ARB | 0.99 (guaranteed) |
| MARKET_MAKER | `price + spread/2` (slight edge from spread) |
| Default (MID_RANGE, etc.) | `price + confidence * 0.1` (slight edge) |

---

## Exit Logic

### Standard Exits (YES/NO positions)

Every cycle, the engine checks all open positions:

```python
current_price = yes_price if side == "YES" else (1.0 - yes_price)
pnl_pct = (current_price - entry_price) / entry_price

if pnl_pct >= +10%: SELL (TAKE_PROFIT)
if pnl_pct <= -5%:  SELL (STOP_LOSS)
```

### Market Maker Exits (MM positions)

Three conditions checked in order:
1. `current_price >= mm_ask` → SELL at ask (MM_FILLED, profit)
2. `pnl_pct <= -3%` → SELL at market (MM_STOP, cut loss)
3. `hold_hours >= 4` → SELL at market (MM_TIMEOUT)

### Dual-Side Arb Exits (BOTH positions)

Only one condition:
- `hold_hours >= 30 days` → SELL at entry price (TIMEOUT, break even)
- Otherwise: hold until market resolution

### Mean Reversion Cooldown Recording

When a MEAN_REVERSION position exits (either TP or SL), the exit time is recorded:

```python
if position.get("strategy") == "MEAN_REVERSION":
    self.scanner.mr_cooldowns[condition_id] = datetime.now(timezone.utc)
```

This prevents re-entering the same market for 48 hours.

---

## Opportunity Pipeline

### Step 1: Scanner (9 strategies in parallel)

Each market is tested against all 9 strategies simultaneously. A single market can generate multiple opportunities (e.g., a crypto market could trigger both MARKET_MAKER and BINANCE_ARB).

### Step 2: Strategy Diversity Filter

Group opportunities by strategy, sort each group by annualized return, then pick:

| Strategy | Max Opportunities Taken |
|----------|------------------------|
| DUAL_SIDE_ARB | 2 |
| BINANCE_ARB | 4 |
| MARKET_MAKER | 4 |
| MEAN_REVERSION | 2 |
| NEAR_CERTAIN | 2 |
| NEAR_ZERO | 2 |
| MID_RANGE | 2 |
| VOLUME_SURGE | 2 |
| DIP_BUY | Excluded (backtest showed -7.89% return) |

**Priority order:** DUAL_SIDE_ARB > BINANCE_ARB > MARKET_MAKER > MEAN_REVERSION > NEAR_CERTAIN > NEAR_ZERO > MID_RANGE > VOLUME_SURGE

### Step 3: Deduplication

Remove duplicate condition_ids (same market can't appear twice). Keep the first occurrence (which comes from the higher-priority strategy).

### Step 4: Final Sort + Cap

Sort all remaining opportunities by annualized return (descending). Return top 10 max.

### Step 5: Evaluation (top 5 only)

The engine evaluates only the top 5 opportunities:
1. Not already holding this market
2. Not at max positions (12)
3. Confidence >= 0.55
4. DIP_BUY/VOLUME_SURGE: bullish news confirmation from Claude AI

### Step 6: Execution

For each opportunity that passes evaluation:
1. Calculate position size (Kelly or fixed 15%)
2. Apply liquidity cap (1% of market liquidity)
3. Apply hard cap ($100)
4. Skip if below $50 minimum
5. Route to strategy-specific execution function (MM, DUAL_SIDE_ARB, BINANCE_ARB have special handlers; everything else uses standard buy)

---

## Strategy Status & Honest Assessment (2026-02-20)

### What's Running

5 parallel simulations, each with fresh $1000 capital:

| Sim | Strategy | PID | Log File | Status |
|-----|----------|-----|----------|--------|
| v8 (main) | MARKET_MAKER | 93915 | `simulation.log` | +$19.03, 9 trades, 78% WR |
| Isolated | NEAR_CERTAIN | 19908 | `near_certain.log` | 3 positions opened, waiting |
| Isolated | NEAR_ZERO | 20448 | `near_zero.log` | 4 positions opened, waiting |
| Isolated | DIP_BUY | 31553 | `dip_buy.log` | 2 positions opened |
| Isolated | VOLUME_SURGE | 36743 | `volume_surge.log` | Just started (bug fixed) |

### Strategy-by-Strategy Honest Assessment

#### 1. MARKET_MAKER — KEEP (Best Strategy)
**Verdict: The only consistently profitable strategy. Data-driven and validated.**

This is the workhorse. 78% win rate, +$19.03 in ~16 hours. Updated with data-driven parameters from 88.5M on-chain trades:
- Two-zone pricing: sweet spot (0.50-0.70, Kelly +29-48%) + fallback (0.80-0.95, Kelly +4-20%)
- Death zone blocked (0.35-0.45), trap zone blocked (0.70-0.75)
- Crypto penalized (-0.10 confidence), politics/economics preferred
- Min 2-day, max 30-day resolution window
- AI screening (Gemini) with empirical intelligence in prompt

Refinements to consider: NegRisk-focused MM (12x more mispricing), time-horizon-adaptive spreads.

#### 2. NEAR_CERTAIN — TESTING (Promising, Capital-Locked)
**Verdict: Mathematically sound. The edge is real but capital is frozen until resolution.**

Buys YES at 93%+ and waits for resolution to $1.00. The math works — it's collecting small guaranteed returns. In isolated testing it immediately deployed $481 across 3 markets. Main risk: capital lock. A $0.98 position earning 2% over 25 days is 27.5% APY — good, but you can't touch the money until resolution. Works best as a complement to faster strategies, not as a primary.

#### 3. NEAR_ZERO — TESTING (Same Profile as NEAR_CERTAIN)
**Verdict: Mirror of NEAR_CERTAIN for the NO side. Same strengths and weaknesses.**

Buys NO when YES is <7%. Deployed $569 across 4 positions immediately. Abundant opportunities (13/cycle). Same capital lock issue. The 88.5M trade analysis shows markets at extreme prices (>0.95 or <0.05) have positive but small Kelly — these strategies capture that edge.

#### 4. DIP_BUY — TESTING (Speculative)
**Verdict: High risk, unproven. Depends on news sentiment accuracy.**

Buys dips >3% assuming overreaction. Two gates: volume floor ($30k) and bullish news from Claude AI. Kelly sizing was broken (positions $26-28, below $50 min) — fixed by switching to fixed 20% sizing. Now deploying $160-200 positions. The fundamental question: is a 3% drop an overreaction or the beginning of a crash? The news gate helps but isn't reliable. Monitor closely.

#### 5. VOLUME_SURGE — TESTING (Just Fixed)
**Verdict: Experimental. Was dead code for its entire lifetime until today.**

The strategy was broken from day 1 — it read `volume1hr` from the API, but that field doesn't exist. Now uses `oneHourPriceChange` > 2% as a proxy for volume surges. The logic is sound (big price moves require big volume) but completely unproven. No historical performance data. Treat as experimental.

#### 6. MID_RANGE — NOT RUNNING (Mediocre)
**Verdict: Weak edge, losing money. Not worth isolating.**

Momentum trading in the 20-80% range. Only needs 0.5% price movement to trigger — very low bar. In the main sim it went -$6.32 on 2 trades (0% win rate). The 88.5M trade analysis doesn't support momentum trading on Polymarket — prediction markets don't trend like equities. The edge, if it exists, is too thin to overcome the -5% stop loss. Not running it separately.

#### 7. MEAN_REVERSION — NOT RUNNING (Backtested Well, Live Underperforms)
**Verdict: +52% in backtest, -$6.11 live. The gap is suspicious.**

Buys when price deviates from 50% midpoint. Best performer in historical backtest but losing money live. This is a classic overfitting signal. Prediction market prices are not like stock prices — a market at 20% might stay at 20% because that's the correct probability, not because it's "due for reversion." Has built-in safeguards (48h cooldown, max 2 entries) which is good. Not prioritizing for isolated testing.

### TRASHED Strategies

#### 8. DUAL_SIDE_ARB — TRASHED (Mathematically Impossible)
**Verdict: Cannot work. Delete the code.**

The math: `YES_cost + NO_cost = best_ask + (1 - best_bid) = 1 + spread`. Since spread >= 0 always, the total is always >= $1.00. You can NEVER buy both sides for under $1.00 on a single binary market. This isn't "rare" — it's impossible. The code references "Account88888's $645K strategy" but that trader was doing multi-outcome NegRisk arbitrage, not single-market dual-side arb.

**Replacement:** NegRisk Multi-Outcome Arbitrage (see Strategy 10 below).

#### 9. BINANCE_ARB — TRASHED (Killed by Fees)
**Verdict: Deliberately disabled. Polymarket's 3.15% dynamic crypto fees exceed the typical 3-5% edge.**

Was removed from `all_strategies` list in code but still generates phantom opportunities each cycle (wasting CPU). The strategy code should be cleaned up. Even if fees were removed, the implied probability model is a simplified heuristic (not Black-Scholes) and would need significant work.

### NEW Strategy

#### 10. NEGRISK_ARB — BUILDING (Highest Priority New Strategy)
**Verdict: Mathematically guaranteed profit. Real opportunities exist right now.**

Multi-outcome NegRisk markets (e.g., "Who will Trump nominate as Fed Chair?" with 39 outcomes) have independent CLOBs per outcome. The sum of all YES prices should equal $1.00 but frequently deviates. Research shows:
- 42% of multi-outcome markets have sum != $1.00
- Median mispricing: $0.08/dollar
- Top arbitrageur extracted $2M+ across 4,049 trades
- Live data: Fed Chair market bid_sum = $1.014 (1.4% guaranteed profit sitting there now)
- API fully supports it: `PartialCreateOrderOptions(neg_risk=True)`

Primary risk: leg risk (need ALL outcomes to fill). Building scanner now.

---

### Key Metrics Summary (2026-02-20)

| Metric | Value |
|--------|-------|
| **Total strategies** | 10 (5 running, 2 not running, 2 trashed, 1 building) |
| **Running (isolated sims)** | MARKET_MAKER, NEAR_CERTAIN, NEAR_ZERO, DIP_BUY, VOLUME_SURGE |
| **Not running** | MID_RANGE (weak), MEAN_REVERSION (overfitting suspected) |
| **Trashed** | DUAL_SIDE_ARB (impossible math), BINANCE_ARB (killed by fees) |
| **Building** | NEGRISK_ARB (multi-outcome arbitrage) |
| **Best performer** | MARKET_MAKER (+$19.03, 9 trades, 78% WR, data-driven) |
| **Tests** | 702 passing, 86% coverage |

### Data-Driven Updates Applied (2026-02-19)

| Change | Strategy | Detail |
|--------|----------|--------|
| Two-zone pricing | MARKET_MAKER | Sweet spot (0.50-0.70) + fallback (0.80-0.95) from 88.5M trades |
| Resolution window | MARKET_MAKER | Min 2 days (0-1d negative edge), max 30 days |
| Category confidence | MARKET_MAKER | Politics/economics +boost, crypto -0.10 penalty |
| Gemini prompt | MARKET_MAKER | Empirical intelligence section (Kelly data, death zones) |
| API bug fix | VOLUME_SURGE | `volume1hr` doesn't exist → now uses `oneHourPriceChange` proxy |
| Kelly exclusion | DIP_BUY | Fixed: was sizing $26-28 (under $50 min), now uses fixed 20% |

### Fixes History

| Date | Fix | Strategy |
|------|-----|----------|
| 2026-02-16 | Kelly exclusion for MID_RANGE | MID_RANGE |
| 2026-02-16 | Lower thresholds (93%, 7%, -3%, 1.5x) | NEAR_CERTAIN, NEAR_ZERO, DIP_BUY, VOLUME_SURGE |
| 2026-02-16 | Raise kelly_fraction 0.15 → 0.40 | All Kelly strategies |
| 2026-02-16 | Disable BINANCE_ARB | BINANCE_ARB |
| 2026-02-19 | Data-driven CONFIG from 88.5M trades | MARKET_MAKER |
| 2026-02-19 | Gemini prompt empirical intelligence | MARKET_MAKER |
| 2026-02-20 | VOLUME_SURGE API bug fix (volume1hr → oneHourPriceChange) | VOLUME_SURGE |
| 2026-02-20 | DIP_BUY Kelly exclusion | DIP_BUY |
| 2026-02-20 | DUAL_SIDE_ARB identified as impossible, trashed | DUAL_SIDE_ARB |
