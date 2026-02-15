#!/usr/bin/env python3
"""
Deep unit tests for sovereign_hive/backtest/engine.py
Targets: 78% → 90%+ coverage

Covers: _execute_entry edge cases, _estimate_probability, _check_exits
(resolution, TP/SL, timeout, MM, BOTH), _execute_exit side effects,
_close_all_positions, _calculate_equity, legacy built-in strategies,
BacktestConfig.get_overrides.
"""

import random
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from sovereign_hive.backtest.engine import (
    BacktestEngine,
    BacktestConfig,
    Position,
    StrategyOverrides,
    DEFAULT_STRATEGY_OVERRIDES,
    BUILTIN_STRATEGIES,
    near_certain_strategy,
    near_zero_strategy,
    mean_reversion_strategy,
    momentum_strategy,
    dip_buy_strategy,
    mid_range_strategy,
    volume_surge_strategy,
)
from sovereign_hive.backtest.data_loader import DataLoader, MarketHistory, PricePoint


# ============================================================
# HELPERS
# ============================================================

def make_history(
    cid="0xtest",
    question="Test market?",
    prices=None,
    resolution=None,
    resolution_time=None,
):
    """Build a MarketHistory with controlled prices."""
    if prices is None:
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(timestamp=now - timedelta(hours=48), price=0.50, volume=10000, bid=0.49, ask=0.51),
            PricePoint(timestamp=now - timedelta(hours=24), price=0.55, volume=12000, bid=0.54, ask=0.56),
            PricePoint(timestamp=now, price=0.60, volume=15000, bid=0.59, ask=0.61),
        ]
    m = MarketHistory(
        condition_id=cid,
        question=question,
        prices=prices,
        resolution=resolution,
        resolution_time=resolution_time,
    )
    m._timestamps = [p.timestamp for p in prices]
    return m


def make_loader(*markets):
    """Build a DataLoader with given markets."""
    loader = DataLoader()
    for m in markets:
        loader.markets[m.condition_id] = m
    return loader


def make_engine(loader, **config_kw):
    """Build an engine with given loader and config overrides."""
    cfg = BacktestConfig(**config_kw)
    return BacktestEngine(loader, cfg)


# ============================================================
# BacktestConfig.get_overrides
# ============================================================

class TestBacktestConfigGetOverrides:

    def test_custom_override(self):
        custom = StrategyOverrides(take_profit_pct=0.50)
        cfg = BacktestConfig(strategy_overrides={"MY_STRAT": custom})
        assert cfg.get_overrides("MY_STRAT").take_profit_pct == 0.50

    def test_known_strategy_gets_default(self):
        cfg = BacktestConfig()
        mm_overrides = cfg.get_overrides("MARKET_MAKER")
        assert mm_overrides.fill_probability == 0.60
        assert mm_overrides.max_hold_hours == 4.0

    def test_unknown_strategy_gets_generic(self):
        cfg = BacktestConfig()
        ovr = cfg.get_overrides("UNKNOWN_STRATEGY")
        assert ovr.take_profit_pct == 0.10  # default StrategyOverrides values


# ============================================================
# _execute_entry edge cases
# ============================================================

class TestExecuteEntry:

    def test_entry_yes_side(self):
        """YES side uses correct price path."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50, volume=10000, bid=0.49, ask=0.51)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 1000.0
        engine.current_time = now

        signal = {"action": "BUY", "side": "YES", "confidence": 0.7, "strategy": "NEAR_CERTAIN"}
        engine._execute_entry(market, signal, "NEAR_CERTAIN")

        assert "0xtest" in engine.positions
        assert engine.positions["0xtest"].side == "YES"

    def test_entry_no_side_uses_inverted_price(self):
        """NO side price = 1 - yes_price when no signal price given."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.30, volume=10000, bid=0.29, ask=0.31)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 1000.0
        engine.current_time = now

        signal = {"action": "BUY", "side": "NO", "confidence": 0.7}
        engine._execute_entry(market, signal, "NEAR_ZERO")

        pos = engine.positions["0xtest"]
        assert pos.side == "NO"
        expected_base = 0.70  # 1 - 0.30
        assert abs(pos.entry_price - expected_base * 1.002) < 0.01  # with slippage

    def test_entry_mm_side(self):
        """MM side uses signal price."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50, volume=20000, bid=0.49, ask=0.51)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 1000.0
        engine.current_time = now

        signal = {"action": "BUY", "side": "MM", "price": 0.48, "mm_bid": 0.48, "mm_ask": 0.52, "confidence": 0.7}
        engine._execute_entry(market, signal, "MARKET_MAKER")

        pos = engine.positions["0xtest"]
        assert pos.side == "MM"
        assert pos.mm_bid == 0.48
        assert pos.mm_ask == 0.52

    def test_entry_both_side(self):
        """BOTH side uses signal price."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50, volume=10000, bid=0.49, ask=0.51)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 1000.0
        engine.current_time = now

        signal = {"action": "BUY", "side": "BOTH", "price": 0.96, "confidence": 0.99}
        engine._execute_entry(market, signal, "DUAL_SIDE_ARB")

        pos = engine.positions["0xtest"]
        assert pos.side == "BOTH"

    def test_entry_skip_price_too_low(self):
        """Skip when price <= 0.001."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.001, volume=10000, bid=0.0, ask=0.002)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 1000.0
        engine.current_time = now

        signal = {"action": "BUY", "side": "YES", "confidence": 0.7}
        engine._execute_entry(market, signal, "NEAR_ZERO")

        assert "0xtest" not in engine.positions

    def test_entry_skip_price_too_high(self):
        """Skip when price >= 0.999."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.999, volume=10000, bid=0.998, ask=1.0)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 1000.0
        engine.current_time = now

        signal = {"action": "BUY", "side": "YES", "confidence": 0.7}
        engine._execute_entry(market, signal, "NEAR_CERTAIN")

        assert "0xtest" not in engine.positions

    def test_entry_skip_insufficient_cash(self):
        """Skip when cash is too low for min position."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50, volume=10000, bid=0.49, ask=0.51)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, min_position_usd=50.0, use_kelly=False)
        engine.cash = 10.0  # Less than min
        engine.current_time = now

        signal = {"action": "BUY", "side": "YES", "confidence": 0.7}
        engine._execute_entry(market, signal, "NEAR_CERTAIN")

        assert "0xtest" not in engine.positions

    def test_entry_slippage_applied(self):
        """Slippage is applied to entry price."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50, volume=10000, bid=0.49, ask=0.51)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, slippage_pct=0.01, use_kelly=False)
        engine.cash = 1000.0
        engine.current_time = now

        signal = {"action": "BUY", "side": "YES", "price": 0.50, "confidence": 0.7}
        engine._execute_entry(market, signal, "NEAR_CERTAIN")

        pos = engine.positions["0xtest"]
        assert pos.entry_price == pytest.approx(0.505, abs=0.001)

    def test_entry_commission_deducted(self):
        """Commission is deducted from position amount."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50, volume=10000, bid=0.49, ask=0.51)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, commission_pct=0.01, use_kelly=False)
        engine.cash = 1000.0
        engine.current_time = now

        signal = {"action": "BUY", "side": "YES", "price": 0.50, "confidence": 0.7}
        engine._execute_entry(market, signal, "NEAR_CERTAIN")

        pos = engine.positions["0xtest"]
        # shares = amount * (1 - commission) / price
        # amount = min(100, 1000*0.15) = 100 (max_position_usd default)
        # amount_after_commission = 100 * 0.99 = 99
        assert pos.shares < 100 / 0.50  # Commission reduced shares

    def test_entry_fixed_position_pct(self):
        """Fixed position pct overrides default sizing."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50, volume=10000, bid=0.49, ask=0.51)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        custom_overrides = {"MY_STRAT": StrategyOverrides(fixed_position_pct=0.05)}
        engine = make_engine(loader, use_kelly=False, strategy_overrides=custom_overrides, max_position_usd=200.0)
        engine.cash = 1000.0
        engine.current_time = now

        signal = {"action": "BUY", "side": "YES", "price": 0.50, "confidence": 0.7}
        engine._execute_entry(market, signal, "MY_STRAT")

        pos = engine.positions["0xtest"]
        # fixed_position_pct = 0.05 * 1000 = $50
        assert pos.cost_basis == pytest.approx(50.0, abs=1.0)

    def test_entry_yes_price_none_skips(self):
        """Entry skips if market has no price at current time."""
        now = datetime.now(timezone.utc)
        # Market with prices far in the past -- get_price_at may return first/last but let's
        # use an empty prices list
        market = MarketHistory(
            condition_id="0xempty", question="Empty?",
            prices=[], resolution=None, resolution_time=None,
        )
        market._timestamps = []
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 1000.0
        engine.current_time = now

        signal = {"action": "BUY", "side": "YES", "confidence": 0.7}
        engine._execute_entry(market, signal, "NEAR_CERTAIN")

        assert "0xempty" not in engine.positions

    def test_entry_kelly_sizing(self):
        """Kelly sizing path is exercised when available."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50, volume=10000, bid=0.49, ask=0.51)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=True, max_position_usd=200.0)
        engine.cash = 1000.0
        engine.current_time = now

        # NEAR_CERTAIN uses Kelly
        signal = {"action": "BUY", "side": "YES", "price": 0.50, "confidence": 0.85}
        engine._execute_entry(market, signal, "NEAR_CERTAIN")

        assert "0xtest" in engine.positions


# ============================================================
# _estimate_probability
# ============================================================

class TestEstimateProbability:

    def setup_method(self):
        loader = make_loader()
        self.engine = make_engine(loader)

    def test_near_certain(self):
        result = self.engine._estimate_probability(0.96, 0.95, "YES", "NEAR_CERTAIN")
        assert result > 0.96
        assert result <= 0.99

    def test_near_zero(self):
        result = self.engine._estimate_probability(0.04, 0.95, "NO", "NEAR_ZERO")
        assert result < 0.04
        assert result >= 0.01

    def test_binance_arb_yes(self):
        result = self.engine._estimate_probability(0.50, 0.80, "YES", "BINANCE_ARB")
        assert result == 0.95

    def test_binance_arb_no(self):
        result = self.engine._estimate_probability(0.50, 0.80, "NO", "BINANCE_ARB")
        assert result == 0.05

    def test_generic_yes(self):
        result = self.engine._estimate_probability(0.50, 0.70, "YES", "DIP_BUY")
        assert result > 0.50
        assert result <= 0.95

    def test_generic_no(self):
        result = self.engine._estimate_probability(0.50, 0.70, "NO", "DIP_BUY")
        assert result < 0.50
        assert result >= 0.05


# ============================================================
# _check_exits: resolution, TP/SL, timeout, BOTH, MM
# ============================================================

class TestCheckExits:

    def _make_engine_with_position(self, side="YES", entry_price=0.50, strategy="NEAR_CERTAIN",
                                   resolution=None, resolution_time=None, mm_bid=0.0, mm_ask=0.0):
        """Helper to build engine with one open position."""
        now = datetime.now(timezone.utc)
        entry_time = now - timedelta(hours=2)
        prices = [
            PricePoint(timestamp=entry_time, price=0.50, volume=10000, bid=0.49, ask=0.51),
            PricePoint(timestamp=now, price=0.60, volume=12000, bid=0.59, ask=0.61),
        ]
        market = make_history(prices=prices, resolution=resolution, resolution_time=resolution_time)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0
        engine.current_time = now

        pos = Position(
            condition_id="0xtest",
            question="Test?",
            strategy=strategy,
            side=side,
            entry_time=entry_time,
            entry_price=entry_price,
            shares=100.0 / entry_price,
            cost_basis=100.0,
            mm_bid=mm_bid,
            mm_ask=mm_ask,
        )
        engine.positions["0xtest"] = pos

        # Also add a matching open trade
        from sovereign_hive.backtest.metrics import Trade
        trade = Trade(
            condition_id="0xtest", question="Test?", strategy=strategy,
            side=side, entry_time=entry_time, entry_price=entry_price,
            shares=100.0 / entry_price, cost_basis=100.0, is_open=True,
        )
        engine.trades.append(trade)

        return engine, now

    def test_resolution_yes_wins_yes_side(self):
        """YES resolution + YES position = side_final=1.0 → big profit."""
        now = datetime.now(timezone.utc)
        engine, current = self._make_engine_with_position(
            side="YES", entry_price=0.50,
            resolution="YES", resolution_time=now - timedelta(hours=1),
        )
        initial_cash = engine.cash
        engine._check_exits(current, "NEAR_CERTAIN")

        assert "0xtest" not in engine.positions
        assert engine.cash > initial_cash

    def test_resolution_no_wins_yes_side(self):
        """NO resolution + YES position = side_final=0.0 → total loss."""
        now = datetime.now(timezone.utc)
        engine, current = self._make_engine_with_position(
            side="YES", entry_price=0.50,
            resolution="NO", resolution_time=now - timedelta(hours=1),
        )
        initial_cash = engine.cash
        engine._check_exits(current, "NEAR_CERTAIN")

        assert "0xtest" not in engine.positions
        # Proceeds = shares * 0.0 * (1 - commission) ≈ 0
        assert engine.cash == pytest.approx(initial_cash, abs=0.1)

    def test_resolution_both_side(self):
        """BOTH side on resolution → side_final=1.0 (one side always pays)."""
        now = datetime.now(timezone.utc)
        engine, current = self._make_engine_with_position(
            side="BOTH", entry_price=0.96, strategy="DUAL_SIDE_ARB",
            resolution="YES", resolution_time=now - timedelta(hours=1),
        )
        initial_cash = engine.cash
        engine._check_exits(current, "DUAL_SIDE_ARB")

        assert "0xtest" not in engine.positions
        assert engine.cash > initial_cash  # Proceeds from $1.0 per share

    def test_resolution_mm_side(self):
        """MM side on resolution → side_final=yes_final."""
        now = datetime.now(timezone.utc)
        engine, current = self._make_engine_with_position(
            side="MM", entry_price=0.50, strategy="MARKET_MAKER",
            resolution="YES", resolution_time=now - timedelta(hours=1),
            mm_bid=0.48, mm_ask=0.52,
        )
        initial_cash = engine.cash
        engine._check_exits(current, "MARKET_MAKER")

        assert "0xtest" not in engine.positions
        assert engine.cash > initial_cash

    def test_take_profit(self):
        """Standard TP triggers when PnL > take_profit_pct."""
        now = datetime.now(timezone.utc)
        entry_time = now - timedelta(hours=2)
        # Price went from 0.50 to 0.80 → PnL = (200*0.80 - 100)/100 = 60% > 10% TP
        prices = [
            PricePoint(timestamp=entry_time, price=0.50, volume=10000, bid=0.49, ask=0.51),
            PricePoint(timestamp=now, price=0.80, volume=12000, bid=0.79, ask=0.81),
        ]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0
        engine.current_time = now

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="NEAR_CERTAIN",
            side="YES", entry_time=entry_time, entry_price=0.50,
            shares=200.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xtest", question="Test?", strategy="NEAR_CERTAIN",
            side="YES", entry_time=entry_time, entry_price=0.50,
            shares=200.0, cost_basis=100.0, is_open=True,
        ))

        engine._check_exits(now, "NEAR_CERTAIN")
        assert "0xtest" not in engine.positions

    def test_stop_loss(self):
        """Standard SL triggers when PnL < stop_loss_pct."""
        now = datetime.now(timezone.utc)
        entry_time = now - timedelta(hours=2)
        # Price went from 0.50 to 0.30 → PnL = (200*0.30 - 100)/100 = -40% < -5% SL
        prices = [
            PricePoint(timestamp=entry_time, price=0.50, volume=10000, bid=0.49, ask=0.51),
            PricePoint(timestamp=now, price=0.30, volume=12000, bid=0.29, ask=0.31),
        ]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0
        engine.current_time = now

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="NEAR_CERTAIN",
            side="YES", entry_time=entry_time, entry_price=0.50,
            shares=200.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xtest", question="Test?", strategy="NEAR_CERTAIN",
            side="YES", entry_time=entry_time, entry_price=0.50,
            shares=200.0, cost_basis=100.0, is_open=True,
        ))

        engine._check_exits(now, "NEAR_CERTAIN")
        assert "0xtest" not in engine.positions

    def test_timeout(self):
        """Timeout triggers when hold_hours >= max_hold_hours."""
        now = datetime.now(timezone.utc)
        entry_time = now - timedelta(hours=100)  # Way past any timeout
        prices = [
            PricePoint(timestamp=entry_time, price=0.50, volume=10000, bid=0.49, ask=0.51),
            PricePoint(timestamp=now, price=0.52, volume=12000, bid=0.51, ask=0.53),
        ]
        market = make_history(prices=prices)
        loader = make_loader(market)
        # Use overrides with a 24-hour timeout for this strategy
        custom = {"TIMEOUT_STRAT": StrategyOverrides(
            take_profit_pct=0.50, stop_loss_pct=-0.50,  # Very loose TP/SL
            max_hold_hours=24.0,
        )}
        engine = make_engine(loader, use_kelly=False, strategy_overrides=custom)
        engine.cash = 900.0
        engine.current_time = now

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="TIMEOUT_STRAT",
            side="YES", entry_time=entry_time, entry_price=0.50,
            shares=200.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xtest", question="Test?", strategy="TIMEOUT_STRAT",
            side="YES", entry_time=entry_time, entry_price=0.50,
            shares=200.0, cost_basis=100.0, is_open=True,
        ))

        engine._check_exits(now, "TIMEOUT_STRAT")
        assert "0xtest" not in engine.positions

    def test_both_side_continues_to_resolution(self):
        """BOTH side skips TP/SL and continues until resolution."""
        now = datetime.now(timezone.utc)
        entry_time = now - timedelta(hours=2)
        prices = [
            PricePoint(timestamp=entry_time, price=0.50, volume=10000, bid=0.49, ask=0.51),
            PricePoint(timestamp=now, price=0.80, volume=12000, bid=0.79, ask=0.81),
        ]
        market = make_history(prices=prices)  # No resolution
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0
        engine.current_time = now

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="DUAL_SIDE_ARB",
            side="BOTH", entry_time=entry_time, entry_price=0.96,
            shares=104.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos

        engine._check_exits(now, "DUAL_SIDE_ARB")
        assert "0xtest" in engine.positions  # Still open, waiting for resolution

    def test_market_not_found_skips(self):
        """Position with unknown market ID is skipped."""
        loader = make_loader()  # No markets
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0
        engine.current_time = datetime.now(timezone.utc)

        pos = Position(
            condition_id="0xunknown", question="Unknown?", strategy="TEST",
            side="YES", entry_time=engine.current_time - timedelta(hours=1),
            entry_price=0.50, shares=100.0, cost_basis=50.0,
        )
        engine.positions["0xunknown"] = pos

        engine._check_exits(engine.current_time, "TEST")
        assert "0xunknown" in engine.positions  # Not closed


# ============================================================
# _check_mm_exit
# ============================================================

class TestCheckMmExit:

    def _make_mm_pos(self, entry_price=0.50, mm_bid=0.48, mm_ask=0.52):
        now = datetime.now(timezone.utc)
        return Position(
            condition_id="0xmm", question="MM?", strategy="MARKET_MAKER",
            side="MM", entry_time=now - timedelta(hours=1),
            entry_price=entry_price, shares=200.0, cost_basis=100.0,
            mm_bid=mm_bid, mm_ask=mm_ask,
        )

    def test_fill_at_ask(self):
        """Price >= mm_ask and fill probability hits → MM_FILLED."""
        pos = self._make_mm_pos(mm_ask=0.52)
        overrides = StrategyOverrides(fill_probability=1.0, exit_slippage_pct=0.002, max_hold_hours=4.0)

        result = BacktestEngine.__new__(BacktestEngine)
        result = BacktestEngine._check_mm_exit(None, pos, 0.55, 1.0, overrides)

        assert result is not None
        assert result[1] == "MM_FILLED"
        assert result[0] < 0.52  # Slippage applied

    def test_fill_probability_fails(self):
        """Price >= mm_ask but random misses → None."""
        pos = self._make_mm_pos(mm_ask=0.52)
        overrides = StrategyOverrides(fill_probability=0.0, max_hold_hours=4.0)

        with patch("sovereign_hive.backtest.engine.random.random", return_value=0.99):
            result = BacktestEngine._check_mm_exit(None, pos, 0.55, 1.0, overrides)

        assert result is None

    def test_mm_stop_loss(self):
        """Price drops enough → MM_STOP."""
        pos = self._make_mm_pos(entry_price=0.50)
        overrides = StrategyOverrides(stop_loss_pct=-0.03, fill_probability=0.6, max_hold_hours=4.0)

        result = BacktestEngine._check_mm_exit(None, pos, 0.45, 1.0, overrides)

        assert result is not None
        assert result[1] == "MM_STOP"
        assert result[0] == 0.45

    def test_mm_timeout(self):
        """Hold > max_hold_hours → MM_TIMEOUT with penalty."""
        pos = self._make_mm_pos(entry_price=0.50)
        overrides = StrategyOverrides(stop_loss_pct=-0.10, fill_probability=0.6, max_hold_hours=4.0)

        result = BacktestEngine._check_mm_exit(None, pos, 0.51, 5.0, overrides)

        assert result is not None
        assert result[1] == "MM_TIMEOUT"
        assert result[0] < 0.51  # Penalty applied


# ============================================================
# _execute_exit side effects
# ============================================================

class TestExecuteExit:

    def test_updates_cash(self):
        """Exit adds proceeds to cash."""
        now = datetime.now(timezone.utc)
        loader = make_loader()
        engine = make_engine(loader, commission_pct=0.001)
        engine.cash = 900.0
        engine.current_time = now

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="NEAR_CERTAIN",
            side="YES", entry_time=now - timedelta(hours=1),
            entry_price=0.50, shares=200.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xtest", question="Test?", strategy="NEAR_CERTAIN",
            side="YES", entry_time=now - timedelta(hours=1), entry_price=0.50,
            shares=200.0, cost_basis=100.0, is_open=True,
        ))

        engine._execute_exit("0xtest", 0.60, "TAKE_PROFIT", "NEAR_CERTAIN")

        # proceeds = 200 * 0.60 * (1 - 0.001) ≈ 119.88
        assert engine.cash > 1000.0
        assert "0xtest" not in engine.positions

    def test_mr_cooldown_recorded(self):
        """MEAN_REVERSION exit records cooldown."""
        now = datetime.now(timezone.utc)
        loader = make_loader()
        engine = make_engine(loader)
        engine.cash = 900.0
        engine.current_time = now

        pos = Position(
            condition_id="0xmr", question="MR?", strategy="MEAN_REVERSION",
            side="YES", entry_time=now - timedelta(hours=1),
            entry_price=0.20, shares=500.0, cost_basis=100.0,
        )
        engine.positions["0xmr"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xmr", question="MR?", strategy="MEAN_REVERSION",
            side="YES", entry_time=now - timedelta(hours=1), entry_price=0.20,
            shares=500.0, cost_basis=100.0, is_open=True,
        ))

        from sovereign_hive.backtest.strategies import get_state, reset_state
        reset_state()

        engine._execute_exit("0xmr", 0.30, "TAKE_PROFIT", "MEAN_REVERSION")

        state = get_state()
        assert "0xmr" in state.mr_last_exit

    def test_mm_state_cleared(self):
        """MARKET_MAKER exit clears MM state."""
        now = datetime.now(timezone.utc)
        loader = make_loader()
        engine = make_engine(loader)
        engine.cash = 900.0
        engine.current_time = now

        pos = Position(
            condition_id="0xmm", question="MM?", strategy="MARKET_MAKER",
            side="MM", entry_time=now - timedelta(hours=1),
            entry_price=0.50, shares=200.0, cost_basis=100.0,
            mm_bid=0.48, mm_ask=0.52,
        )
        engine.positions["0xmm"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xmm", question="MM?", strategy="MARKET_MAKER",
            side="MM", entry_time=now - timedelta(hours=1), entry_price=0.50,
            shares=200.0, cost_basis=100.0, is_open=True,
        ))

        from sovereign_hive.backtest.strategies import get_state, reset_state
        reset_state()
        get_state().record_mm_entry("0xmm", now, 0.48, 0.52)

        engine._execute_exit("0xmm", 0.52, "MM_FILLED", "MARKET_MAKER")

        assert get_state().get_mm_entry("0xmm") is None

    def test_nonexistent_position(self):
        """Exit on nonexistent position is a no-op."""
        loader = make_loader()
        engine = make_engine(loader)
        engine.cash = 1000.0
        engine.current_time = datetime.now(timezone.utc)

        engine._execute_exit("0xnonexistent", 0.50, "TAKE_PROFIT", "TEST")
        assert engine.cash == 1000.0  # Unchanged


# ============================================================
# _close_all_positions
# ============================================================

class TestCloseAllPositions:

    def test_closes_yes_position(self):
        """YES position closed at final price."""
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(timestamp=now - timedelta(hours=2), price=0.50, volume=10000, bid=0.49, ask=0.51),
            PricePoint(timestamp=now, price=0.80, volume=12000, bid=0.79, ask=0.81),
        ]
        market = make_history(prices=prices, resolution="YES")
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="NEAR_CERTAIN",
            side="YES", entry_time=now - timedelta(hours=2),
            entry_price=0.50, shares=200.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xtest", question="Test?", strategy="NEAR_CERTAIN",
            side="YES", entry_time=now - timedelta(hours=2), entry_price=0.50,
            shares=200.0, cost_basis=100.0, is_open=True,
        ))

        engine._close_all_positions(now, "NEAR_CERTAIN")
        assert len(engine.positions) == 0
        assert engine.cash > 900.0

    def test_closes_both_position_at_1(self):
        """BOTH position closes at $1.00."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50, volume=10000, bid=0.49, ask=0.51)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="DUAL_SIDE_ARB",
            side="BOTH", entry_time=now - timedelta(hours=2),
            entry_price=0.96, shares=104.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xtest", question="Test?", strategy="DUAL_SIDE_ARB",
            side="BOTH", entry_time=now - timedelta(hours=2), entry_price=0.96,
            shares=104.0, cost_basis=100.0, is_open=True,
        ))

        engine._close_all_positions(now, "DUAL_SIDE_ARB")
        assert len(engine.positions) == 0
        # Proceeds = 104 * 1.0 * (1 - commission)
        assert engine.cash > 1000.0

    def test_closes_no_position(self):
        """NO position closed with (1 - final_price)."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.20, volume=10000, bid=0.19, ask=0.21)]
        market = make_history(prices=prices, resolution="NO")
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="NEAR_ZERO",
            side="NO", entry_time=now - timedelta(hours=2),
            entry_price=0.80, shares=125.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xtest", question="Test?", strategy="NEAR_ZERO",
            side="NO", entry_time=now - timedelta(hours=2), entry_price=0.80,
            shares=125.0, cost_basis=100.0, is_open=True,
        ))

        engine._close_all_positions(now, "NEAR_ZERO")
        assert len(engine.positions) == 0

    def test_closes_mm_position(self):
        """MM position closed at yes_final price."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.60, volume=10000, bid=0.59, ask=0.61)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="MARKET_MAKER",
            side="MM", entry_time=now - timedelta(hours=2),
            entry_price=0.50, shares=200.0, cost_basis=100.0,
            mm_bid=0.48, mm_ask=0.52,
        )
        engine.positions["0xtest"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xtest", question="Test?", strategy="MARKET_MAKER",
            side="MM", entry_time=now - timedelta(hours=2), entry_price=0.50,
            shares=200.0, cost_basis=100.0, is_open=True,
        ))

        engine._close_all_positions(now, "MARKET_MAKER")
        assert len(engine.positions) == 0


# ============================================================
# _calculate_equity
# ============================================================

class TestCalculateEquity:

    def test_cash_only(self):
        loader = make_loader()
        engine = make_engine(loader)
        engine.cash = 1000.0
        engine.positions = {}

        assert engine._calculate_equity(datetime.now(timezone.utc)) == 1000.0

    def test_with_yes_position(self):
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.60, volume=10000, bid=0.59, ask=0.61)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader)
        engine.cash = 900.0

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="NEAR_CERTAIN",
            side="YES", entry_time=now - timedelta(hours=1),
            entry_price=0.50, shares=200.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos

        equity = engine._calculate_equity(now)
        assert equity == pytest.approx(900.0 + 200 * 0.60, abs=0.01)

    def test_with_both_position(self):
        """BOTH position adds cost_basis to equity."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50, volume=10000, bid=0.49, ask=0.51)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader)
        engine.cash = 900.0

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="DUAL_SIDE_ARB",
            side="BOTH", entry_time=now - timedelta(hours=1),
            entry_price=0.96, shares=104.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos

        equity = engine._calculate_equity(now)
        assert equity == pytest.approx(1000.0, abs=0.01)

    def test_with_mm_position(self):
        """MM position valued at shares * yes_price."""
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.55, volume=10000, bid=0.54, ask=0.56)]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader)
        engine.cash = 900.0

        pos = Position(
            condition_id="0xtest", question="Test?", strategy="MARKET_MAKER",
            side="MM", entry_time=now - timedelta(hours=1),
            entry_price=0.50, shares=200.0, cost_basis=100.0,
            mm_bid=0.48, mm_ask=0.52,
        )
        engine.positions["0xtest"] = pos

        equity = engine._calculate_equity(now)
        assert equity == pytest.approx(900.0 + 200 * 0.55, abs=0.01)

    def test_fallback_to_cost_basis(self):
        """When price is unavailable, use cost_basis."""
        now = datetime.now(timezone.utc)
        # Market with no prices
        market = MarketHistory(
            condition_id="0xnoprice", question="No price?",
            prices=[], resolution=None, resolution_time=None,
        )
        market._timestamps = []
        loader = make_loader(market)
        engine = make_engine(loader)
        engine.cash = 900.0

        pos = Position(
            condition_id="0xnoprice", question="No price?", strategy="TEST",
            side="YES", entry_time=now - timedelta(hours=1),
            entry_price=0.50, shares=200.0, cost_basis=100.0,
        )
        engine.positions["0xnoprice"] = pos

        equity = engine._calculate_equity(now)
        assert equity == pytest.approx(1000.0, abs=0.01)  # 900 + 100 cost basis


# ============================================================
# LEGACY BUILT-IN STRATEGIES
# ============================================================

class TestBuiltinStrategies:

    @pytest.fixture
    def market_with_history(self):
        """Market with price history spanning multiple days."""
        now = datetime.now(timezone.utc)
        prices = []
        for i in range(100):
            t = now - timedelta(hours=100 - i)
            p = 0.40 + 0.003 * i  # Gradually rising from 0.40 to 0.70
            prices.append(PricePoint(timestamp=t, price=p, volume=10000, bid=p - 0.01, ask=p + 0.01))
        m = MarketHistory(
            condition_id="0xhistory", question="History test?",
            prices=prices, resolution=None, resolution_time=None,
        )
        m._timestamps = [pp.timestamp for pp in prices]
        return m, now

    def test_near_certain_triggers(self):
        result = near_certain_strategy(None, 0.92, datetime.now(timezone.utc))
        assert result is not None
        assert result["side"] == "YES"

    def test_near_certain_rejects(self):
        result = near_certain_strategy(None, 0.80, datetime.now(timezone.utc))
        assert result is None

    def test_near_zero_triggers(self):
        result = near_zero_strategy(None, 0.05, datetime.now(timezone.utc))
        assert result is not None
        assert result["side"] == "NO"

    def test_near_zero_rejects(self):
        result = near_zero_strategy(None, 0.20, datetime.now(timezone.utc))
        assert result is None

    def test_mean_reversion_yes(self):
        result = mean_reversion_strategy(None, 0.20, datetime.now(timezone.utc))
        assert result is not None
        assert result["side"] == "YES"

    def test_mean_reversion_no(self):
        result = mean_reversion_strategy(None, 0.80, datetime.now(timezone.utc))
        assert result is not None
        assert result["side"] == "NO"

    def test_mean_reversion_mid(self):
        result = mean_reversion_strategy(None, 0.50, datetime.now(timezone.utc))
        assert result is None

    def test_momentum_up(self, market_with_history):
        market, now = market_with_history
        # At now, price ~0.70. At now - 24h, price ~0.47. Change = +0.23 > 0.05
        result = momentum_strategy(market, 0.70, now)
        assert result is not None
        assert result["side"] == "YES"

    def test_momentum_down(self, market_with_history):
        """Falling price triggers NO momentum."""
        now = datetime.now(timezone.utc)
        prices = []
        for i in range(100):
            t = now - timedelta(hours=100 - i)
            p = 0.70 - 0.003 * i  # Falling from 0.70 to 0.40
            prices.append(PricePoint(timestamp=t, price=p, volume=10000, bid=p - 0.01, ask=p + 0.01))
        m = MarketHistory(
            condition_id="0xdown", question="Down?",
            prices=prices, resolution=None, resolution_time=None,
        )
        m._timestamps = [pp.timestamp for pp in prices]

        result = momentum_strategy(m, 0.40, now)
        assert result is not None
        assert result["side"] == "NO"

    def test_momentum_none_no_prev(self):
        """No previous price → None."""
        market = MarketHistory(
            condition_id="0xempty", question="Empty?",
            prices=[], resolution=None, resolution_time=None,
        )
        market._timestamps = []
        result = momentum_strategy(market, 0.50, datetime.now(timezone.utc))
        assert result is None

    def test_dip_buy_triggers(self, market_with_history):
        """Price drop > 5% triggers dip buy."""
        now = datetime.now(timezone.utc)
        prices = []
        for i in range(100):
            t = now - timedelta(hours=100 - i)
            p = 0.60 - 0.002 * i  # Falling from 0.60 to 0.40
            prices.append(PricePoint(timestamp=t, price=p, volume=10000, bid=p - 0.01, ask=p + 0.01))
        m = MarketHistory(
            condition_id="0xdip", question="Dip?",
            prices=prices, resolution=None, resolution_time=None,
        )
        m._timestamps = [pp.timestamp for pp in prices]

        # At now, price=0.40. 24h ago (~index 76), price=0.60 - 0.002*76=0.448
        # change = (0.40 - 0.448)/0.448 = -10.7% < -5%
        result = dip_buy_strategy(m, 0.40, now)
        assert result is not None
        assert result["side"] == "YES"

    def test_dip_buy_none_no_prev(self):
        market = MarketHistory(
            condition_id="0xempty", question="Empty?",
            prices=[], resolution=None, resolution_time=None,
        )
        market._timestamps = []
        result = dip_buy_strategy(market, 0.50, datetime.now(timezone.utc))
        assert result is None

    def test_mid_range_up(self, market_with_history):
        """Mid-range with upward 6h change → YES."""
        market, now = market_with_history
        # At now, price ~0.70 (out of 0.20-0.80 range but close to 0.70)
        # Let's test at 0.50 with price going up
        now2 = datetime.now(timezone.utc)
        prices = []
        for i in range(20):
            t = now2 - timedelta(hours=20 - i)
            p = 0.45 + 0.005 * i  # Rising from 0.45 to 0.54
            prices.append(PricePoint(timestamp=t, price=p, volume=10000, bid=p - 0.01, ask=p + 0.01))
        m = MarketHistory(
            condition_id="0xmid", question="Mid?",
            prices=prices, resolution=None, resolution_time=None,
        )
        m._timestamps = [pp.timestamp for pp in prices]

        # At now2, price=0.54. 6h ago (~index 14), price=0.45+0.005*14=0.52
        # change = 0.54 - 0.52 = +0.02 > 0.01
        result = mid_range_strategy(m, 0.54, now2)
        assert result is not None
        assert result["side"] == "YES"

    def test_mid_range_down(self):
        """Mid-range with downward 6h change → NO."""
        now = datetime.now(timezone.utc)
        prices = []
        for i in range(20):
            t = now - timedelta(hours=20 - i)
            p = 0.55 - 0.005 * i  # Falling from 0.55 to 0.46
            prices.append(PricePoint(timestamp=t, price=p, volume=10000, bid=p - 0.01, ask=p + 0.01))
        m = MarketHistory(
            condition_id="0xmid", question="Mid?",
            prices=prices, resolution=None, resolution_time=None,
        )
        m._timestamps = [pp.timestamp for pp in prices]

        result = mid_range_strategy(m, 0.46, now)
        assert result is not None
        assert result["side"] == "NO"

    def test_mid_range_none_no_prev(self):
        market = MarketHistory(
            condition_id="0xempty", question="Empty?",
            prices=[], resolution=None, resolution_time=None,
        )
        market._timestamps = []
        result = mid_range_strategy(market, 0.50, datetime.now(timezone.utc))
        assert result is None

    def test_mid_range_out_of_range(self):
        result = mid_range_strategy(None, 0.15, datetime.now(timezone.utc))
        assert result is None
        result = mid_range_strategy(None, 0.85, datetime.now(timezone.utc))
        assert result is None

    def test_volume_surge_triggers(self):
        """Volume surge triggers on moderate price change in mid-range."""
        now = datetime.now(timezone.utc)
        prices = []
        for i in range(20):
            t = now - timedelta(hours=20 - i)
            p = 0.45 + 0.003 * i  # Rising from 0.45 to 0.51
            prices.append(PricePoint(timestamp=t, price=p, volume=10000, bid=p - 0.01, ask=p + 0.01))
        m = MarketHistory(
            condition_id="0xvol", question="Volume?",
            prices=prices, resolution=None, resolution_time=None,
        )
        m._timestamps = [pp.timestamp for pp in prices]

        # At now, price=0.51. 6h ago (~index 14), price=0.45+0.003*14=0.492
        # change = |0.51 - 0.492| = 0.018, not in (0.02, 0.08) range
        # Let's increase the spread:
        now2 = datetime.now(timezone.utc)
        prices2 = []
        for i in range(20):
            t = now2 - timedelta(hours=20 - i)
            p = 0.40 + 0.01 * i  # Rising from 0.40 to 0.59
            prices2.append(PricePoint(timestamp=t, price=p, volume=10000, bid=p - 0.01, ask=p + 0.01))
        m2 = MarketHistory(
            condition_id="0xvol2", question="Volume2?",
            prices=prices2, resolution=None, resolution_time=None,
        )
        m2._timestamps = [pp.timestamp for pp in prices2]

        # At now2, price=0.59. 6h ago (~index 14), price=0.40+0.01*14=0.54
        # change = |0.59 - 0.54| = 0.05. In (0.02, 0.08) ✓, 0.25 < 0.59 < 0.75 ✓
        result = volume_surge_strategy(m2, 0.59, now2)
        assert result is not None
        assert result["side"] == "YES"

    def test_volume_surge_no_direction(self):
        """Volume surge with price drop → NO direction."""
        now = datetime.now(timezone.utc)
        prices = []
        for i in range(20):
            t = now - timedelta(hours=20 - i)
            p = 0.60 - 0.01 * i  # Falling from 0.60 to 0.41
            prices.append(PricePoint(timestamp=t, price=p, volume=10000, bid=p - 0.01, ask=p + 0.01))
        m = MarketHistory(
            condition_id="0xvol", question="Volume?",
            prices=prices, resolution=None, resolution_time=None,
        )
        m._timestamps = [pp.timestamp for pp in prices]

        # At now, price=0.41. 6h ago (index 14), price=0.60-0.01*14=0.46
        # change = |0.41 - 0.46| = 0.05 ✓, 0.25 < 0.41 < 0.75 ✓
        result = volume_surge_strategy(m, 0.41, now)
        assert result is not None
        assert result["side"] == "NO"

    def test_volume_surge_none_no_prev(self):
        market = MarketHistory(
            condition_id="0xempty", question="Empty?",
            prices=[], resolution=None, resolution_time=None,
        )
        market._timestamps = []
        result = volume_surge_strategy(market, 0.50, datetime.now(timezone.utc))
        assert result is None


# ============================================================
# BUILTIN_STRATEGIES registry
# ============================================================

class TestBuiltinRegistry:

    def test_contains_7_strategies(self):
        assert len(BUILTIN_STRATEGIES) == 7

    def test_all_callable(self):
        for name, fn in BUILTIN_STRATEGIES.items():
            assert callable(fn)

    def test_expected_names(self):
        expected = {"NEAR_CERTAIN", "NEAR_ZERO", "MEAN_REVERSION",
                    "MOMENTUM", "DIP_BUY", "MID_RANGE", "VOLUME_SURGE"}
        assert set(BUILTIN_STRATEGIES.keys()) == expected


# ============================================================
# run() method edge case
# ============================================================

class TestRunMethod:

    def test_run_no_data_raises(self):
        """run() with empty DataLoader raises ValueError."""
        loader = DataLoader()
        engine = BacktestEngine(loader)
        engine.add_strategy("TEST", lambda m, p, t: None)

        with pytest.raises(ValueError, match="No data"):
            engine.run()


# ============================================================
# Bug fix regression tests
# ============================================================

class TestBugFixes:
    """Regression tests for 3 bugs discovered during audit (2026-02-14)."""

    def test_mm_ask_fallback_uses_1_01(self):
        """Bug 1: MM ask fallback should use 1.01 (aligned with production), not 1.04."""
        pos = Position(
            condition_id="0xmm", question="MM?", strategy="MARKET_MAKER",
            side="MM", entry_time=datetime.now(timezone.utc) - timedelta(hours=1),
            entry_price=0.50, shares=200.0, cost_basis=100.0,
            mm_bid=0.49, mm_ask=0.0,  # mm_ask = 0 triggers fallback
        )
        overrides = StrategyOverrides(fill_probability=1.0, exit_slippage_pct=0.0, max_hold_hours=4.0)

        # Price at 0.505 = entry * 1.01 → should trigger fill with 1.01 fallback
        result = BacktestEngine._check_mm_exit(None, pos, 0.505, 1.0, overrides)
        assert result is not None
        assert result[1] == "MM_FILLED"

        # Price at 0.503 = below entry * 1.01 → should NOT fill
        result2 = BacktestEngine._check_mm_exit(None, pos, 0.503, 1.0, overrides)
        assert result2 is None

    def test_mr_cooldown_recorded_on_all_exit_reasons(self):
        """Bug 2: MR cooldown should be recorded on ALL exit reasons, not just TP/SL/TIMEOUT."""
        now = datetime.now(timezone.utc)
        loader = make_loader()
        from sovereign_hive.backtest.strategies import get_state, reset_state
        from sovereign_hive.backtest.metrics import Trade

        # Test with a non-standard exit reason like "RESOLUTION"
        for reason in ["STOP_LOSS", "TAKE_PROFIT", "TIMEOUT", "RESOLUTION", "MM_STOP"]:
            reset_state()
            engine = make_engine(loader)
            engine.cash = 900.0
            engine.current_time = now

            cid = f"0xmr_{reason}"
            pos = Position(
                condition_id=cid, question="MR?", strategy="MEAN_REVERSION",
                side="YES", entry_time=now - timedelta(hours=1),
                entry_price=0.20, shares=500.0, cost_basis=100.0,
            )
            engine.positions[cid] = pos
            engine.trades.append(Trade(
                condition_id=cid, question="MR?", strategy="MEAN_REVERSION",
                side="YES", entry_time=now - timedelta(hours=1), entry_price=0.20,
                shares=500.0, cost_basis=100.0, is_open=True,
            ))

            engine._execute_exit(cid, 0.30, reason, "MEAN_REVERSION")

            state = get_state()
            assert cid in state.mr_last_exit, f"MR cooldown not recorded for exit reason: {reason}"

    def test_both_position_timeout_after_30_days(self):
        """Bug 3: BOTH positions should timeout after 30 days instead of being held forever."""
        now = datetime.now(timezone.utc)
        entry_time = now - timedelta(days=31)  # 31 days ago
        prices = [
            PricePoint(timestamp=entry_time, price=0.50, volume=10000, bid=0.49, ask=0.51),
            PricePoint(timestamp=now, price=0.55, volume=12000, bid=0.54, ask=0.56),
        ]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0
        engine.current_time = now

        pos = Position(
            condition_id="0xtest", question="Both?", strategy="DUAL_SIDE_ARB",
            side="BOTH", entry_time=entry_time, entry_price=0.96,
            shares=104.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos
        from sovereign_hive.backtest.metrics import Trade
        engine.trades.append(Trade(
            condition_id="0xtest", question="Both?", strategy="DUAL_SIDE_ARB",
            side="BOTH", entry_time=entry_time, entry_price=0.96,
            shares=104.0, cost_basis=100.0, is_open=True,
        ))

        engine._check_exits(now, "DUAL_SIDE_ARB")

        # Position should have been closed due to 30-day timeout
        assert "0xtest" not in engine.positions

    def test_both_position_holds_before_30_days(self):
        """Bug 3 (counterpart): BOTH positions should still hold if < 30 days."""
        now = datetime.now(timezone.utc)
        entry_time = now - timedelta(days=15)  # Only 15 days
        prices = [
            PricePoint(timestamp=entry_time, price=0.50, volume=10000, bid=0.49, ask=0.51),
            PricePoint(timestamp=now, price=0.55, volume=12000, bid=0.54, ask=0.56),
        ]
        market = make_history(prices=prices)
        loader = make_loader(market)
        engine = make_engine(loader, use_kelly=False)
        engine.cash = 900.0
        engine.current_time = now

        pos = Position(
            condition_id="0xtest", question="Both?", strategy="DUAL_SIDE_ARB",
            side="BOTH", entry_time=entry_time, entry_price=0.96,
            shares=104.0, cost_basis=100.0,
        )
        engine.positions["0xtest"] = pos

        engine._check_exits(now, "DUAL_SIDE_ARB")

        # Position should still be open
        assert "0xtest" in engine.positions


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
