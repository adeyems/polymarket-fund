# Sovereign Hive V4 - Project Goals

## Vision
Build a fully autonomous multi-agent trading system for Polymarket prediction markets that generates consistent alpha through anomaly detection, intelligent vetting, and disciplined position management.

---

## Active Strategies (IMPLEMENTED)

### 1. NEAR-CERTAIN ARBITRAGE (Lowest Risk) ✅
**Status:** Running in simulation
**What:** Buy YES at $0.98+ when market is almost resolved
**Edge:** Collect 2% when market resolves to $1.00
**Risk:** Market flips (rare at 98%+)
**Capital:** Any amount
**Example:** "Will Super Bowl happen in 2025?" at $0.99

### 2. DIP BUYING (Medium Risk) ✅
**Status:** Running in simulation
**What:** Buy when price drops >10% in 24h on high volume
**Edge:** Overreaction to news, price rebounds
**Risk:** Fundamental shift, price continues down
**Trigger:** News sentiment must be neutral/bullish (Claude AI)
**Example:** Political market drops on false rumor

### 3. VOLUME DIVERGENCE (Information Edge) ✅
**Status:** Running in simulation
**What:** High volume without price movement = informed traders accumulating
**Edge:** Follow the smart money before price moves
**Risk:** Volume was exit, not entry
**Trigger:** 3x+ normal volume + stable price

### 4. BINANCE-POLYMARKET ARBITRAGE ✅
**Status:** Built, not integrated into main loop
**File:** `agents/binance_arb.py`
**What:** Compare Binance crypto prices to Polymarket price prediction markets
**Edge:** Polymarket often lags behind real-time Binance prices
**Risk:** Volatility model assumptions, timing
**Example:** BTC at $97K on Binance, Polymarket "BTC above $100K" priced at 30% but should be 45%

---

## Potential Strategies (TO BUILD)

### 5. DUAL-SIDE VOLATILITY ARBITRAGE (Low Risk, High Capital)
**Status:** Research phase
**What:** Buy BOTH sides (UP + DOWN) when mispriced during volatility
**Edge:** During panic, UP + DOWN < $1.00. Buy both, guaranteed profit.
**Risk:** Requires fast execution, high capital ($40K+ positions)
**Example:** BTC UP at $0.48 + BTC DOWN at $0.46 = $0.94. Payout = $1.00. Profit = 6%
**Proof:** Account88888 made $645K with 96% win rate using this exact strategy
**Reference:** https://polymarket.com/@Account88888

### 6. SPORTS BOOK ARBITRAGE (Cross-Platform)
**Status:** Not implemented
**What:** Compare Polymarket odds vs DraftKings/FanDuel/Pinnacle
**Edge:** Polymarket often lags behind sharp sports books
**Risk:** Line movement, different rules
**Example:** Polymarket has Team A at 45%, Vegas at 52%

### 7. NEWS FRONTRUNNING (Speed Edge)
**Status:** Partially implemented (NewsAPI + Claude)
**What:** React to breaking news before market prices it in
**Edge:** Minutes matter - be first to trade
**Risk:** Fake news, wrong interpretation
**Requires:** Twitter API ($100/mo) for maximum speed

### 8. RESOLUTION TIMING (Calendar Edge)
**Status:** Not implemented
**What:** Markets about to resolve have compressed timeframes
**Edge:** Less time = less risk of reversal
**Risk:** Resolution delayed
**Example:** "Will X happen by Feb 10?" on Feb 9th

---

## Phase 1: Foundation (COMPLETE)

### Core Infrastructure
- [x] Multi-agent blackboard architecture (ALPHA/BETA/GAMMA/OMEGA)
- [x] Async execution with non-blocking I/O
- [x] State persistence across restarts (blackboard.json)
- [x] Simulation mode for risk-free testing
- [x] Trade history with performance metrics

### Position Lifecycle
- [x] BUY: Execute vetted opportunities
- [x] MONITOR: Track unrealized P&L
- [x] SELL: Take profit (+5%) / Stop loss (-15%)
- [x] RESOLVE: Claim winnings on market resolution

### Risk Management
- [x] Position sizing based on available balance
- [x] Maximum exposure limits
- [x] Order retry with exponential backoff
- [x] Emergency halt capability

---

## Phase 2: Intelligence (NEXT)

### Alpha Generation
- [ ] Volume spike detection with 3-sigma threshold
- [ ] Arbitrage scanner (YES + NO > $1.00 spread)
- [ ] Dip buy opportunities (sudden price drops)
- [ ] News sentiment integration via NewsAPI/Twitter

### Market Selection
- [ ] Liquidity filtering (min $10k volume)
- [ ] Time-to-resolution scoring
- [ ] Volatility-adjusted sizing
- [ ] Avoid illiquid/manipulated markets

### Strategy Optimization
- [ ] Dynamic TP/SL based on volatility
- [ ] Strategy performance tracking by type
- [ ] Kill underperforming strategies automatically
- [ ] A/B testing framework for new signals

---

## Phase 3: Production (FUTURE)

### Operational Excellence
- [ ] 24/7 uptime with health monitoring
- [ ] Discord/Telegram alerts on trades
- [ ] Daily P&L reports
- [ ] Automatic gas refueling

### Dashboard
- [ ] Real-time position viewer
- [ ] Trade history with filtering
- [ ] Performance charts (cumulative P&L, drawdown)
- [ ] Risk state indicator

### Scale
- [ ] Multi-wallet support
- [ ] Parallel market monitoring (100+ markets)
- [ ] Sub-100ms execution latency
- [ ] Cloud deployment (AWS/GCP)

---

## Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Win Rate | > 55% | 66.7% (sim) |
| Sharpe Ratio | > 1.0 | 0.26 (sim) |
| Max Drawdown | < 20% | $6.00 (sim) |
| Avg Trade P&L | > $1.00 | $1.29 (sim) |
| Daily Volume | > $500 | $0 (unfunded) |

---

## Immediate Blockers

1. **Wallet Funding**: $2 balance - need $50+ minimum for live trading
2. **API Keys**: Verify CLOB credentials are valid
3. **Gas**: Ensure POL balance for transaction fees

---

## Philosophy

> "The bot that only buys is a money incinerator."

Every position must have a planned exit. Take profits when the market gives them. Cut losses before they compound. Measure everything.

---

## Run Commands

```bash
# Simulation (real data, virtual $1000)
python sovereign_hive/run_simulation.py

# Live trading (requires funding)
python sovereign_hive/run_simulation.py --live

# Reset portfolio to $1000
python sovereign_hive/run_simulation.py --reset

# Run in background (autonomous)
nohup python -u sovereign_hive/run_simulation.py > sovereign_hive/sim.log 2>&1 &

# Check simulation log
tail -50 sovereign_hive/sim.log

# View portfolio state
cat sovereign_hive/data/portfolio_sim.json
```

---

*Last Updated: 2026-02-08*
