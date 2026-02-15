#!/usr/bin/env python3
"""
BACKTEST STRATEGIES UNIT TESTS
================================
Comprehensive tests for sovereign_hive/backtest/strategies.py
Targets 90%+ coverage across all strategy functions and helper classes.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.backtest.data_loader import MarketHistory, MarketSnapshot, PricePoint
from sovereign_hive.backtest.strategies import (
    _annualized_return,
    StrategyState,
    reset_state,
    get_state,
    PROD_CONFIG,
    near_certain,
    near_zero,
    dip_buy,
    mid_range,
    mean_reversion,
    mean_reversion_broken,
    market_maker,
    market_maker_broken,
    dual_side_arb,
    volume_surge,
    binance_arb,
    PRICE_ONLY_STRATEGIES,
    SPREAD_STRATEGIES,
    PRODUCTION_STRATEGIES,
    BROKEN_STRATEGIES,
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def make_market():
    """Factory fixture to create MarketHistory with configurable parameters."""
    def _make(condition_id="0xtest", question="Test market?",
              num_points=48, base_price=0.5, resolution=None,
              resolution_time=None):
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(
                timestamp=now - timedelta(hours=num_points - i),
                price=base_price,
                volume=20000,
                bid=max(0.01, base_price - 0.01),
                ask=min(0.99, base_price + 0.01),
            )
            for i in range(num_points)
        ]
        m = MarketHistory(
            condition_id=condition_id,
            question=question,
            prices=prices,
            resolution=resolution,
            resolution_time=resolution_time,
        )
        m._timestamps = [p.timestamp for p in prices]
        return m
    return _make


@pytest.fixture
def make_snapshot():
    """Factory fixture to create MarketSnapshot with configurable parameters."""
    def _make(**kwargs):
        defaults = dict(
            condition_id="0xtest",
            question="Test?",
            price=0.50,
            bid=0.49,
            ask=0.51,
            volume_24h=30000,
            price_change_24h=0.0,
            volatility=0.05,
            days_to_resolve=30.0,
        )
        defaults.update(kwargs)
        return MarketSnapshot(**defaults)
    return _make


@pytest.fixture(autouse=True)
def clean_state():
    """Reset global StrategyState before and after every test."""
    reset_state()
    yield
    reset_state()


# ============================================================
# 1. _annualized_return()
# ============================================================

class TestAnnualizedReturn:
    """Tests for the _annualized_return helper function."""

    def test_positive_return(self):
        """Positive simple return over 30 days yields positive annualized."""
        result = _annualized_return(0.05, 30.0)
        assert result > 0.05  # annualizing a 30-day return amplifies it

    def test_negative_return(self):
        """Negative simple return yields negative annualized."""
        result = _annualized_return(-0.05, 30.0)
        assert result < 0

    def test_zero_days_returns_zero(self):
        """Zero holding period returns 0.0 (division guard)."""
        assert _annualized_return(0.10, 0.0) == 0.0

    def test_negative_days_returns_zero(self):
        """Negative days returns 0.0."""
        assert _annualized_return(0.10, -5.0) == 0.0

    def test_total_loss_returns_zero(self):
        """Return of exactly -1 (total loss) returns 0.0."""
        assert _annualized_return(-1.0, 30.0) == 0.0

    def test_overflow_capping(self):
        """Extreme values that would overflow are capped at 10.0."""
        result = _annualized_return(100.0, 1.0)
        assert result == 10.0

    def test_moderate_return_one_year(self):
        """10% over 365 days should return ~10%."""
        result = _annualized_return(0.10, 365.0)
        assert abs(result - 0.10) < 0.001

    def test_zero_return(self):
        """Zero simple return annualizes to zero."""
        assert _annualized_return(0.0, 30.0) == 0.0


# ============================================================
# 2. StrategyState class
# ============================================================

class TestStrategyState:
    """Tests for StrategyState bookkeeping class."""

    def test_fresh_state(self):
        state = StrategyState()
        assert state.mr_last_exit == {}
        assert state.mr_entry_count == {}
        assert state.mm_entries == {}
        assert state.mr_cooldown_hours == 48.0
        assert state.mr_max_entries == 2

    def test_record_mr_exit(self):
        state = StrategyState()
        ts = datetime.now(timezone.utc)
        state.record_mr_exit("0x1", ts)
        assert state.mr_last_exit["0x1"] == ts

    def test_can_enter_mr_before_cooldown(self):
        """Within 48h of exit, should block re-entry."""
        state = StrategyState()
        exit_ts = datetime.now(timezone.utc) - timedelta(hours=10)
        state.record_mr_exit("0x1", exit_ts)
        check_ts = datetime.now(timezone.utc)
        assert state.can_enter_mr("0x1", check_ts) is False

    def test_can_enter_mr_after_cooldown(self):
        """After 48h cooldown, entry should be allowed."""
        state = StrategyState()
        exit_ts = datetime.now(timezone.utc) - timedelta(hours=50)
        state.record_mr_exit("0x1", exit_ts)
        check_ts = datetime.now(timezone.utc)
        assert state.can_enter_mr("0x1", check_ts) is True

    def test_can_enter_mr_max_entries(self):
        """After reaching max_entries (2), should block."""
        state = StrategyState()
        state.record_mr_entry("0x1")
        state.record_mr_entry("0x1")
        ts = datetime.now(timezone.utc)
        assert state.can_enter_mr("0x1", ts) is False

    def test_can_enter_mr_no_history(self):
        """With no prior activity, entry is always allowed."""
        state = StrategyState()
        ts = datetime.now(timezone.utc)
        assert state.can_enter_mr("0xnew", ts) is True

    def test_record_mr_entry_increments(self):
        state = StrategyState()
        state.record_mr_entry("0x1")
        assert state.mr_entry_count["0x1"] == 1
        state.record_mr_entry("0x1")
        assert state.mr_entry_count["0x1"] == 2

    def test_record_mm_entry(self):
        state = StrategyState()
        ts = datetime.now(timezone.utc)
        state.record_mm_entry("0x1", ts, 0.48, 0.52)
        entry = state.get_mm_entry("0x1")
        assert entry is not None
        assert entry["mm_bid"] == 0.48
        assert entry["mm_ask"] == 0.52
        assert entry["entry_time"] == ts

    def test_get_mm_entry_missing(self):
        state = StrategyState()
        assert state.get_mm_entry("0xnone") is None

    def test_clear_mm_entry(self):
        state = StrategyState()
        ts = datetime.now(timezone.utc)
        state.record_mm_entry("0x1", ts, 0.48, 0.52)
        state.clear_mm_entry("0x1")
        assert state.get_mm_entry("0x1") is None

    def test_clear_mm_entry_nonexistent(self):
        """Clearing a nonexistent entry should not raise."""
        state = StrategyState()
        state.clear_mm_entry("0xnone")  # should not raise


# ============================================================
# 3. reset_state() / get_state()
# ============================================================

class TestGlobalState:
    """Tests for module-level state management."""

    def test_get_state_returns_strategy_state(self):
        state = get_state()
        assert isinstance(state, StrategyState)

    def test_reset_state_creates_fresh(self):
        state1 = get_state()
        state1.record_mr_entry("0x1")
        reset_state()
        state2 = get_state()
        assert state2.mr_entry_count == {}
        assert state1 is not state2


# ============================================================
# 4. near_certain()
# ============================================================

class TestNearCertain:
    """Tests for near_certain strategy."""

    def test_triggers_at_96pct(self, make_market, make_snapshot):
        """Price >= 0.95 with good APY should trigger."""
        market = make_market()
        snap = make_snapshot(price=0.96, days_to_resolve=10.0)
        ts = datetime.now(timezone.utc)
        result = near_certain(market, snap, ts)
        assert result is not None
        assert result["strategy"] == "NEAR_CERTAIN"
        assert result["side"] == "YES"
        assert result["action"] == "BUY"

    def test_rejects_below_95pct(self, make_market, make_snapshot):
        """Price < 0.95 should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.90)
        ts = datetime.now(timezone.utc)
        assert near_certain(market, snap, ts) is None

    def test_rejects_over_90_days(self, make_market, make_snapshot):
        """Days to resolve > 90 should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.96, days_to_resolve=100.0)
        ts = datetime.now(timezone.utc)
        assert near_certain(market, snap, ts) is None

    def test_rejects_low_apy(self, make_market, make_snapshot):
        """High price with very long time (low APY) should be rejected."""
        market = make_market()
        # 0.99 price = only 1% return; over 89 days that annualizes to ~4.2% < 15%
        snap = make_snapshot(price=0.99, days_to_resolve=89.0)
        ts = datetime.now(timezone.utc)
        assert near_certain(market, snap, ts) is None

    def test_price_exactly_95(self, make_market, make_snapshot):
        """Price of exactly 0.95 with short resolve should trigger."""
        market = make_market()
        # 0.95 price = 5.26% return; over 5 days annualizes to huge number
        snap = make_snapshot(price=0.95, days_to_resolve=5.0)
        ts = datetime.now(timezone.utc)
        result = near_certain(market, snap, ts)
        assert result is not None


# ============================================================
# 5. near_zero()
# ============================================================

class TestNearZero:
    """Tests for near_zero strategy."""

    def test_triggers_at_3pct(self, make_market, make_snapshot):
        """Price <= 0.05 (YES side) should trigger NO buy."""
        market = make_market()
        snap = make_snapshot(price=0.03, days_to_resolve=10.0)
        ts = datetime.now(timezone.utc)
        result = near_zero(market, snap, ts)
        assert result is not None
        assert result["strategy"] == "NEAR_ZERO"
        assert result["side"] == "NO"
        assert result["action"] == "BUY"

    def test_rejects_above_5pct(self, make_market, make_snapshot):
        """Price > 0.05 should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.10)
        ts = datetime.now(timezone.utc)
        assert near_zero(market, snap, ts) is None

    def test_rejects_price_zero(self, make_market, make_snapshot):
        """Price == 0 should be rejected (snap.price <= 0 guard)."""
        market = make_market()
        snap = make_snapshot(price=0.0)
        ts = datetime.now(timezone.utc)
        assert near_zero(market, snap, ts) is None

    def test_rejects_no_price_at_98(self, make_market, make_snapshot):
        """When no_price >= 0.98 (YES price <= 0.02), should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.02, days_to_resolve=10.0)
        ts = datetime.now(timezone.utc)
        assert near_zero(market, snap, ts) is None

    def test_rejects_over_90_days(self, make_market, make_snapshot):
        """Days to resolve > 90 should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.04, days_to_resolve=100.0)
        ts = datetime.now(timezone.utc)
        assert near_zero(market, snap, ts) is None

    def test_rejects_low_apy(self, make_market, make_snapshot):
        """Near-zero with very long resolve time should have low APY and be rejected."""
        market = make_market()
        # price=0.04, no_price=0.96, expected_return=(1-0.96)/0.96=0.0417
        # Over 89 days: annualized = (1.0417)^(365/89) - 1 = ~18%, which passes
        # Over 89 days with price=0.049: no_price=0.951, return=(1-0.951)/0.951=0.0515
        # We need a case where annualized < 15%
        # price=0.049, no_price=0.951, return=0.0515, over 89 days annualized=(1.0515)^4.1 ~= 22%
        # price=0.04, no_price=0.96, return=0.0417, over 89d = (1.0417)^4.1 ~= 18%
        # Try larger days_to_resolve but under 90
        # price=0.048, no_price=0.952, return=0.0504, over 89d = ~21%
        # Need return*(365/days) < 15% approximately
        # return=0.03, days=89: (1.03)^4.1 = ~12.7% -- this works!
        # no_price = 1/(1+0.03) = 0.9709, price = 0.0291
        snap = make_snapshot(price=0.03, days_to_resolve=89.0)
        ts = datetime.now(timezone.utc)
        result = near_zero(market, snap, ts)
        # no_price = 0.97, expected_return = 0.03/0.97 = 0.0309
        # annualized = (1.0309)^(365/89) - 1 = ~13.1% < 15%
        assert result is None


# ============================================================
# 6. dip_buy()
# ============================================================

class TestDipBuy:
    """Tests for dip_buy strategy."""

    def test_triggers_on_6pct_dip(self, make_market, make_snapshot):
        """Price change of -6% should trigger."""
        market = make_market()
        snap = make_snapshot(price_change_24h=-0.06)
        ts = datetime.now(timezone.utc)
        result = dip_buy(market, snap, ts)
        assert result is not None
        assert result["strategy"] == "DIP_BUY"
        assert result["side"] == "YES"

    def test_rejects_minus_2pct(self, make_market, make_snapshot):
        """Price change of -2% is above threshold, should be rejected."""
        market = make_market()
        snap = make_snapshot(price_change_24h=-0.02)
        ts = datetime.now(timezone.utc)
        assert dip_buy(market, snap, ts) is None

    def test_rejects_positive_change(self, make_market, make_snapshot):
        """Positive price change should be rejected."""
        market = make_market()
        snap = make_snapshot(price_change_24h=0.05)
        ts = datetime.now(timezone.utc)
        assert dip_buy(market, snap, ts) is None

    def test_exactly_at_threshold(self, make_market, make_snapshot):
        """Exactly at -5% threshold should be rejected (>= check)."""
        market = make_market()
        snap = make_snapshot(price_change_24h=-0.05)
        ts = datetime.now(timezone.utc)
        assert dip_buy(market, snap, ts) is None


# ============================================================
# 7. mid_range()
# ============================================================

class TestMidRange:
    """Tests for mid_range strategy."""

    def test_up_momentum(self, make_market, make_snapshot):
        """Positive price change > 0.5% should signal BUY YES."""
        market = make_market()
        snap = make_snapshot(price=0.50, price_change_24h=0.01)
        ts = datetime.now(timezone.utc)
        result = mid_range(market, snap, ts)
        assert result is not None
        assert result["side"] == "YES"
        assert "UP" in result["reason"]

    def test_down_momentum(self, make_market, make_snapshot):
        """Negative price change < -0.5% should signal BUY NO."""
        market = make_market()
        snap = make_snapshot(price=0.50, price_change_24h=-0.01)
        ts = datetime.now(timezone.utc)
        result = mid_range(market, snap, ts)
        assert result is not None
        assert result["side"] == "NO"
        assert "DOWN" in result["reason"]

    def test_flat_no_signal(self, make_market, make_snapshot):
        """Flat price change within [-0.5%, +0.5%] should return None."""
        market = make_market()
        snap = make_snapshot(price=0.50, price_change_24h=0.001)
        ts = datetime.now(timezone.utc)
        assert mid_range(market, snap, ts) is None

    def test_outside_range_low(self, make_market, make_snapshot):
        """Price < 0.20 should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.15, price_change_24h=0.02)
        ts = datetime.now(timezone.utc)
        assert mid_range(market, snap, ts) is None

    def test_outside_range_high(self, make_market, make_snapshot):
        """Price > 0.80 should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.85, price_change_24h=0.02)
        ts = datetime.now(timezone.utc)
        assert mid_range(market, snap, ts) is None


# ============================================================
# 8. mean_reversion()
# ============================================================

class TestMeanReversion:
    """Tests for mean_reversion strategy (with cooldown/trend filter)."""

    def test_buy_yes_below_30(self, make_market, make_snapshot):
        """Price < 0.30 and > 0.05 should trigger BUY YES."""
        market = make_market(base_price=0.20)
        snap = make_snapshot(price=0.20)
        ts = datetime.now(timezone.utc)
        result = mean_reversion(market, snap, ts)
        assert result is not None
        assert result["side"] == "YES"
        assert result["strategy"] == "MEAN_REVERSION"

    def test_buy_no_above_70(self, make_market, make_snapshot):
        """Price > 0.70 and < 0.95 should trigger BUY NO."""
        market = make_market(base_price=0.80)
        snap = make_snapshot(price=0.80)
        ts = datetime.now(timezone.utc)
        result = mean_reversion(market, snap, ts)
        assert result is not None
        assert result["side"] == "NO"
        assert result["strategy"] == "MEAN_REVERSION"

    def test_mid_range_rejected(self, make_market, make_snapshot):
        """Price in 30-70% range should be rejected."""
        market = make_market(base_price=0.50)
        snap = make_snapshot(price=0.50)
        ts = datetime.now(timezone.utc)
        assert mean_reversion(market, snap, ts) is None

    def test_extreme_low_rejected(self, make_market, make_snapshot):
        """Price <= 0.05 should be rejected (too extreme)."""
        market = make_market(base_price=0.04)
        snap = make_snapshot(price=0.04)
        ts = datetime.now(timezone.utc)
        assert mean_reversion(market, snap, ts) is None

    def test_extreme_high_rejected(self, make_market, make_snapshot):
        """Price >= 0.95 should be rejected (too extreme)."""
        market = make_market(base_price=0.96)
        snap = make_snapshot(price=0.96)
        ts = datetime.now(timezone.utc)
        assert mean_reversion(market, snap, ts) is None

    def test_cooldown_blocks_entry(self, make_market, make_snapshot):
        """Recent MR exit should block new entry within 48h."""
        market = make_market(base_price=0.20)
        snap = make_snapshot(price=0.20)
        ts = datetime.now(timezone.utc)
        state = get_state()
        state.record_mr_exit(market.condition_id, ts - timedelta(hours=10))
        assert mean_reversion(market, snap, ts) is None

    def test_trend_filter_blocks_yes(self, make_snapshot):
        """Strong 7d downtrend (< -10%) should block YES buy."""
        now = datetime.now(timezone.utc)
        # Create a market with declining prices over 7+ days (168 hours)
        num_points = 200
        prices = []
        start_price = 0.40
        for i in range(num_points):
            # Price declines from 0.40 to ~0.20 over 200 hours
            t = now - timedelta(hours=num_points - i)
            p = start_price - (0.20 * i / num_points)
            prices.append(PricePoint(
                timestamp=t, price=p, volume=20000,
                bid=max(0.01, p - 0.01), ask=min(0.99, p + 0.01),
            ))
        market = MarketHistory(
            condition_id="0xtrend", question="Trend test?",
            prices=prices, resolution=None, resolution_time=None,
        )
        market._timestamps = [pp.timestamp for pp in prices]
        snap = make_snapshot(price=0.20, condition_id="0xtrend")
        result = mean_reversion(market, snap, now)
        assert result is None

    def test_trend_filter_blocks_no(self, make_snapshot):
        """Strong 7d uptrend (> +10%) should block NO buy."""
        now = datetime.now(timezone.utc)
        num_points = 200
        prices = []
        start_price = 0.60
        for i in range(num_points):
            t = now - timedelta(hours=num_points - i)
            p = start_price + (0.20 * i / num_points)
            prices.append(PricePoint(
                timestamp=t, price=p, volume=20000,
                bid=max(0.01, p - 0.01), ask=min(0.99, p + 0.01),
            ))
        market = MarketHistory(
            condition_id="0xtrend_up", question="Trend test?",
            prices=prices, resolution=None, resolution_time=None,
        )
        market._timestamps = [pp.timestamp for pp in prices]
        snap = make_snapshot(price=0.80, condition_id="0xtrend_up")
        result = mean_reversion(market, snap, now)
        assert result is None

    def test_entry_count_recorded(self, make_market, make_snapshot):
        """Successful entry should increment entry count."""
        market = make_market(base_price=0.20)
        snap = make_snapshot(price=0.20)
        ts = datetime.now(timezone.utc)
        result = mean_reversion(market, snap, ts)
        assert result is not None
        state = get_state()
        assert state.mr_entry_count[market.condition_id] == 1


# ============================================================
# 9. mean_reversion_broken()
# ============================================================

class TestMeanReversionBroken:
    """Tests for mean_reversion_broken (no cooldown/trend filter)."""

    def test_fires_yes_without_cooldown(self, make_market, make_snapshot):
        """Should fire even if cooldown would block the normal version."""
        market = make_market(base_price=0.20)
        snap = make_snapshot(price=0.20)
        ts = datetime.now(timezone.utc)
        state = get_state()
        state.record_mr_exit(market.condition_id, ts - timedelta(hours=10))
        result = mean_reversion_broken(market, snap, ts)
        assert result is not None
        assert result["side"] == "YES"

    def test_fires_no_without_trend_filter(self, make_market, make_snapshot):
        """Should fire regardless of 7d trend."""
        market = make_market(base_price=0.80)
        snap = make_snapshot(price=0.80)
        ts = datetime.now(timezone.utc)
        result = mean_reversion_broken(market, snap, ts)
        assert result is not None
        assert result["side"] == "NO"

    def test_mid_range_still_rejected(self, make_market, make_snapshot):
        """Mid-range prices are still rejected in broken version."""
        market = make_market(base_price=0.50)
        snap = make_snapshot(price=0.50)
        ts = datetime.now(timezone.utc)
        assert mean_reversion_broken(market, snap, ts) is None

    def test_extreme_low_still_rejected(self, make_market, make_snapshot):
        """Price <= 0.05 still rejected in broken version."""
        market = make_market(base_price=0.04)
        snap = make_snapshot(price=0.04)
        ts = datetime.now(timezone.utc)
        assert mean_reversion_broken(market, snap, ts) is None

    def test_extreme_high_still_rejected(self, make_market, make_snapshot):
        """Price >= 0.95 still rejected in broken version."""
        market = make_market(base_price=0.96)
        snap = make_snapshot(price=0.96)
        ts = datetime.now(timezone.utc)
        assert mean_reversion_broken(market, snap, ts) is None


# ============================================================
# 10. market_maker()
# ============================================================

class TestMarketMaker:
    """Tests for market_maker strategy."""

    def test_valid_spread_and_volume(self, make_market, make_snapshot):
        """Valid spread (2-10%) and volume should trigger MM signal."""
        market = make_market()
        # bid=0.48, ask=0.52 => spread = 0.04/0.50 = 8%
        snap = make_snapshot(price=0.50, bid=0.48, ask=0.52, volume_24h=20000)
        ts = datetime.now(timezone.utc)
        result = market_maker(market, snap, ts)
        assert result is not None
        assert result["strategy"] == "MARKET_MAKER"
        assert result["side"] == "MM"
        assert "mm_bid" in result
        assert "mm_ask" in result

    def test_rejects_no_bid(self, make_market, make_snapshot):
        """Bid <= 0 should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.50, bid=0.0, ask=0.52, volume_24h=20000)
        ts = datetime.now(timezone.utc)
        assert market_maker(market, snap, ts) is None

    def test_rejects_low_volume(self, make_market, make_snapshot):
        """Volume < 15000 should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.50, bid=0.48, ask=0.52, volume_24h=5000)
        ts = datetime.now(timezone.utc)
        assert market_maker(market, snap, ts) is None

    def test_rejects_spread_too_narrow(self, make_market, make_snapshot):
        """Spread < 2% should be rejected."""
        market = make_market()
        # bid=0.499, ask=0.501 => spread = 0.002/0.500 = 0.4%
        snap = make_snapshot(price=0.50, bid=0.499, ask=0.501, volume_24h=20000)
        ts = datetime.now(timezone.utc)
        assert market_maker(market, snap, ts) is None

    def test_rejects_spread_too_wide(self, make_market, make_snapshot):
        """Spread > 10% should be rejected."""
        market = make_market()
        # bid=0.40, ask=0.52 => spread = 0.12/0.46 = ~26%
        snap = make_snapshot(price=0.46, bid=0.40, ask=0.52, volume_24h=20000)
        ts = datetime.now(timezone.utc)
        assert market_maker(market, snap, ts) is None

    def test_rejects_price_too_low(self, make_market, make_snapshot):
        """Price < 0.03 should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.02, bid=0.01, ask=0.03, volume_24h=20000)
        ts = datetime.now(timezone.utc)
        assert market_maker(market, snap, ts) is None

    def test_rejects_price_too_high(self, make_market, make_snapshot):
        """Price > 0.97 should be rejected."""
        market = make_market()
        snap = make_snapshot(price=0.98, bid=0.96, ask=0.99, volume_24h=20000)
        ts = datetime.now(timezone.utc)
        assert market_maker(market, snap, ts) is None

    def test_records_mm_state(self, make_market, make_snapshot):
        """Successful MM entry should be recorded in state."""
        market = make_market()
        snap = make_snapshot(price=0.50, bid=0.48, ask=0.52, volume_24h=20000)
        ts = datetime.now(timezone.utc)
        market_maker(market, snap, ts)
        state = get_state()
        entry = state.get_mm_entry(market.condition_id)
        assert entry is not None


# ============================================================
# 10b. market_maker_broken()
# ============================================================

class TestMarketMakerBroken:
    """Tests for market_maker_broken (delegates to market_maker)."""

    def test_delegates_to_market_maker(self, make_market, make_snapshot):
        """Broken version should produce same result as normal MM."""
        market = make_market()
        snap = make_snapshot(price=0.50, bid=0.48, ask=0.52, volume_24h=20000)
        ts = datetime.now(timezone.utc)
        result = market_maker_broken(market, snap, ts)
        assert result is not None
        assert result["strategy"] == "MARKET_MAKER"


# ============================================================
# 11. dual_side_arb()
# ============================================================

class TestDualSideArb:
    """Tests for dual_side_arb strategy."""

    def test_triggers_on_profitable_total(self, make_market, make_snapshot):
        """Total cost < 0.98 (= 1.0 - 0.02) should trigger."""
        market = make_market()
        # yes_price = ask = 0.45, no_price = 1 - bid = 1 - 0.50 = 0.50
        # total = 0.95 < 0.98
        snap = make_snapshot(price=0.50, bid=0.50, ask=0.45, volume_24h=30000)
        ts = datetime.now(timezone.utc)
        result = dual_side_arb(market, snap, ts)
        assert result is not None
        assert result["strategy"] == "DUAL_SIDE_ARB"
        assert result["side"] == "BOTH"
        assert result["confidence"] == 0.99

    def test_rejects_no_profit(self, make_market, make_snapshot):
        """Total cost >= 0.98 should be rejected."""
        market = make_market()
        # yes_price = ask = 0.51, no_price = 1 - bid = 1 - 0.49 = 0.51
        # total = 1.02 >= 0.98
        snap = make_snapshot(price=0.50, bid=0.49, ask=0.51, volume_24h=30000)
        ts = datetime.now(timezone.utc)
        assert dual_side_arb(market, snap, ts) is None

    def test_fallback_no_bid(self, make_market, make_snapshot):
        """When bid = 0, no_price should use 1 - snap.price."""
        market = make_market()
        # bid=0 => no_price = 1 - price = 1 - 0.50 = 0.50
        # yes_price = ask = 0.40; total = 0.90 < 0.98
        snap = make_snapshot(price=0.50, bid=0.0, ask=0.40, volume_24h=30000)
        ts = datetime.now(timezone.utc)
        result = dual_side_arb(market, snap, ts)
        assert result is not None


# ============================================================
# 12. volume_surge()
# ============================================================

class TestVolumeSurge:
    """Tests for volume_surge strategy."""

    def test_triggers_on_high_volatility(self, make_market, make_snapshot):
        """High volatility (>= 0.04), modest price change should trigger."""
        market = make_market()
        snap = make_snapshot(
            volume_24h=50000, price_change_24h=0.01, volatility=0.06,
        )
        ts = datetime.now(timezone.utc)
        result = volume_surge(market, snap, ts)
        assert result is not None
        assert result["strategy"] == "VOLUME_SURGE"
        assert result["side"] == "YES"  # positive price change

    def test_negative_change_buys_no(self, make_market, make_snapshot):
        """Negative price change should signal BUY NO."""
        market = make_market()
        snap = make_snapshot(
            volume_24h=50000, price_change_24h=-0.01, volatility=0.06,
        )
        ts = datetime.now(timezone.utc)
        result = volume_surge(market, snap, ts)
        assert result is not None
        assert result["side"] == "NO"

    def test_rejects_zero_volume(self, make_market, make_snapshot):
        """Volume <= 0 should be rejected."""
        market = make_market()
        snap = make_snapshot(volume_24h=0, price_change_24h=0.01, volatility=0.06)
        ts = datetime.now(timezone.utc)
        assert volume_surge(market, snap, ts) is None

    def test_rejects_large_price_change(self, make_market, make_snapshot):
        """Price change >= 5% should be rejected."""
        market = make_market()
        snap = make_snapshot(
            volume_24h=50000, price_change_24h=0.06, volatility=0.06,
        )
        ts = datetime.now(timezone.utc)
        assert volume_surge(market, snap, ts) is None

    def test_rejects_low_volatility(self, make_market, make_snapshot):
        """Volatility < 0.04 should be rejected."""
        market = make_market()
        snap = make_snapshot(
            volume_24h=50000, price_change_24h=0.01, volatility=0.02,
        )
        ts = datetime.now(timezone.utc)
        assert volume_surge(market, snap, ts) is None


# ============================================================
# 13. binance_arb()
# ============================================================

class TestBinanceArb:
    """Tests for binance_arb strategy."""

    def _make_crypto_market(self, keyword="bitcoin", base_price=0.50, num_points=200):
        """Helper to build a crypto market with 7+ days of history."""
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(
                timestamp=now - timedelta(hours=num_points - i),
                price=base_price,
                volume=20000,
                bid=max(0.01, base_price - 0.01),
                ask=min(0.99, base_price + 0.01),
            )
            for i in range(num_points)
        ]
        m = MarketHistory(
            condition_id="0xcrypto",
            question=f"Will {keyword} reach $100k?",
            prices=prices,
        )
        m._timestamps = [p.timestamp for p in prices]
        return m

    def test_crypto_market_detected(self, make_snapshot):
        """Market with 'bitcoin' in question should pass crypto check."""
        market = self._make_crypto_market("bitcoin")
        snap = make_snapshot(price=0.50, price_change_24h=-0.10, condition_id="0xcrypto")
        ts = datetime.now(timezone.utc)
        # price_7d = 0 (flat), edge = 0 - (-0.10) = 0.10 >= 0.05
        result = binance_arb(market, snap, ts)
        assert result is not None
        assert result["strategy"] == "BINANCE_ARB"

    def test_non_crypto_rejected(self, make_snapshot):
        """Market without crypto keyword should be rejected."""
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(timestamp=now - timedelta(hours=200 - i), price=0.50,
                       volume=20000, bid=0.49, ask=0.51)
            for i in range(200)
        ]
        market = MarketHistory(
            condition_id="0xpolitics",
            question="Will candidate win election?",
            prices=prices,
        )
        market._timestamps = [p.timestamp for p in prices]
        snap = make_snapshot(price=0.50, price_change_24h=-0.10, condition_id="0xpolitics")
        ts = now
        assert binance_arb(market, snap, ts) is None

    def test_edge_too_small(self, make_snapshot):
        """Edge < 5% should be rejected."""
        market = self._make_crypto_market("btc")
        # price_7d = 0 (flat), price_change_24h = 0 => edge = 0 < 0.05
        snap = make_snapshot(price=0.50, price_change_24h=0.0, condition_id="0xcrypto")
        ts = datetime.now(timezone.utc)
        assert binance_arb(market, snap, ts) is None

    def test_no_7d_data_empty_market(self, make_snapshot):
        """Market with no price data at all should return None (price_7d is None)."""
        market = MarketHistory(
            condition_id="0xempty",
            question="Will bitcoin reach $100k?",
            prices=[],
        )
        market._timestamps = []
        snap = make_snapshot(price=0.50, price_change_24h=-0.10, condition_id="0xempty")
        ts = datetime.now(timezone.utc)
        assert binance_arb(market, snap, ts) is None

    def test_various_crypto_keywords(self, make_snapshot):
        """All crypto keywords should be detected."""
        keywords = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto"]
        ts = datetime.now(timezone.utc)
        for kw in keywords:
            market = self._make_crypto_market(kw)
            snap = make_snapshot(price=0.50, price_change_24h=-0.10, condition_id="0xcrypto")
            result = binance_arb(market, snap, ts)
            assert result is not None, f"Keyword '{kw}' should trigger crypto detection"

    def test_positive_edge_buys_yes(self, make_snapshot):
        """Positive edge should signal BUY YES."""
        market = self._make_crypto_market("bitcoin")
        # price_7d = 0, price_change_24h = -0.10 => edge = 0.10 > 0
        snap = make_snapshot(price=0.50, price_change_24h=-0.10, condition_id="0xcrypto")
        ts = datetime.now(timezone.utc)
        result = binance_arb(market, snap, ts)
        assert result is not None
        assert result["side"] == "YES"

    def test_negative_edge_buys_no(self, make_snapshot):
        """Negative edge should signal BUY NO."""
        market = self._make_crypto_market("bitcoin")
        # price_7d = 0, price_change_24h = 0.10 => edge = -0.10 < 0
        snap = make_snapshot(price=0.50, price_change_24h=0.10, condition_id="0xcrypto")
        ts = datetime.now(timezone.utc)
        result = binance_arb(market, snap, ts)
        assert result is not None
        assert result["side"] == "NO"


# ============================================================
# 14. Strategy Registries
# ============================================================

class TestStrategyRegistries:
    """Tests for strategy registry dictionaries."""

    def test_price_only_has_5_strategies(self):
        assert len(PRICE_ONLY_STRATEGIES) == 5

    def test_price_only_contents(self):
        expected = {"NEAR_CERTAIN", "NEAR_ZERO", "DIP_BUY", "MID_RANGE", "MEAN_REVERSION"}
        assert set(PRICE_ONLY_STRATEGIES.keys()) == expected

    def test_spread_has_4_strategies(self):
        assert len(SPREAD_STRATEGIES) == 4

    def test_spread_contents(self):
        expected = {"MARKET_MAKER", "DUAL_SIDE_ARB", "VOLUME_SURGE", "BINANCE_ARB"}
        assert set(SPREAD_STRATEGIES.keys()) == expected

    def test_production_has_9_strategies(self):
        assert len(PRODUCTION_STRATEGIES) == 9

    def test_production_is_union(self):
        """PRODUCTION_STRATEGIES should be the union of PRICE_ONLY and SPREAD."""
        combined = {**PRICE_ONLY_STRATEGIES, **SPREAD_STRATEGIES}
        assert set(PRODUCTION_STRATEGIES.keys()) == set(combined.keys())

    def test_broken_has_2_strategies(self):
        assert len(BROKEN_STRATEGIES) == 2

    def test_broken_contents(self):
        expected = {"MEAN_REVERSION", "MARKET_MAKER"}
        assert set(BROKEN_STRATEGIES.keys()) == expected

    def test_all_strategies_callable(self):
        """Every registered strategy should be callable."""
        for name, fn in PRODUCTION_STRATEGIES.items():
            assert callable(fn), f"{name} is not callable"
        for name, fn in BROKEN_STRATEGIES.items():
            assert callable(fn), f"BROKEN {name} is not callable"

    def test_broken_mean_reversion_is_different_function(self):
        """Broken MR should be a different function than production MR."""
        assert BROKEN_STRATEGIES["MEAN_REVERSION"] is not PRODUCTION_STRATEGIES["MEAN_REVERSION"]

    def test_broken_market_maker_is_different_function(self):
        """Broken MM should be a different function than production MM."""
        assert BROKEN_STRATEGIES["MARKET_MAKER"] is not PRODUCTION_STRATEGIES["MARKET_MAKER"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
