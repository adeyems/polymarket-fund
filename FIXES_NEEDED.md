# Critical Fixes Before Paper Trading

## 1. MARKET_MAKER Spread - TOO TIGHT
**File**: `sovereign_hive/run_simulation.py`
**Current**: Entry = mid - 0.5%, Exit = mid + 0.5%
**Fix**: Entry = mid - 2%, Exit = mid + 2%
**Line**: ~1216-1218
```python
mm_bid = mid_price - max(mid_price * 0.005, 0.005)  # CHANGE 0.005 to 0.02
mm_ask = mid_price + max(mid_price * 0.005, 0.005)  # CHANGE 0.005 to 0.02
```

## 2. MARKET_MAKER Fill Rate - 100% UNREALISTIC
**File**: `sovereign_hive/run_simulation.py`
**Current**: Assumes price touching ask = guaranteed fill
**Fix**: Add 60% fill probability simulation
**Line**: ~1016-1023 (_check_mm_exit)
```python
# Current: if current_price >= mm_ask: FILL
# New: if current_price >= mm_ask and random() < 0.60: FILL
```

## 3. Kelly Criterion - TOO CONSERVATIVE
**File**: `sovereign_hive/run_simulation.py` OR `core/kelly_criterion.py`
**Current**: Adjusting 41.7% down to 3.7% (killing capital)
**Fix**: Use fixed position sizing for MEAN_REVERSION instead of Kelly
**Line**: ~1089-1106 (execute_trade)
```python
# For MEAN_REVERSION, ignore Kelly
if opp["strategy"] == "MEAN_REVERSION":
    max_amount = self.portfolio.balance * 0.10  # Fixed 10%
else:
    # Use Kelly for other strategies
```

## 4. Position Size - TOO SMALL
**File**: `sovereign_hive/run_simulation.py`
**Current**: min_position_pct = 0.15 (15%), but capped at $100 max
**Fix**: Increase to $100-150 minimum
**Line**: ~1113
```python
amount = min(max_amount, max_liquidity_amount, 150)  # was 100
# Add minimum: if amount < 50: skip
```

## 5. MM Max Hold Time - INFINITE
**File**: `sovereign_hive/run_simulation.py`
**Current**: mm_max_hold_hours: 24
**Fix**: Reduce to 4 hours (market maker shouldn't hold long)
**Line**: ~70
```python
"mm_max_hold_hours": 4,  # was 24
```

## 6. Add Slippage Model
**File**: `sovereign_hive/run_simulation.py`
**Current**: Assumes zero slippage
**Fix**: Add 0.2% slippage on exits
**Line**: ~1016 (_check_mm_exit)
```python
# When exit price is mm_ask, apply slippage
exit_price = mm_ask * 0.998  # 0.2% slippage
```

---

## Summary of Changes
| Issue | Current | Fix | Impact |
|-------|---------|-----|--------|
| MM Spread | 0.5% | 2% | More realistic |
| Fill Rate | 100% | 60% | Realistic execution |
| Kelly | Too harsh | Fixed 10% for MR | Stops capital bleed |
| Position Min | $5 | $50 | Meaningful trades |
| Hold Time | 24h | 4h | Real MM behavior |
| Slippage | 0% | 0.2% | Realistic pricing |

Expected new results with fixes:
- MARKET_MAKER: 99.3% → 70% win rate, +116% → +20-30% ROI
- MEAN_REVERSION: -89.7% → positive (needs testing)
- Others: Should improve with fixed Kelly

