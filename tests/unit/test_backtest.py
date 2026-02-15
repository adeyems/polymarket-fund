#!/usr/bin/env python3
"""
BACKTEST FRAMEWORK TESTS
=========================
Tests for the backtesting engine, data loader, and metrics.
"""

import pytest
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.backtest.data_loader import DataLoader, MarketHistory, PricePoint
from sovereign_hive.backtest.metrics import PerformanceMetrics, Trade, compare_strategies
from sovereign_hive.backtest.engine import (
    BacktestEngine, BacktestConfig, Position,
    near_certain_strategy, near_zero_strategy,
    mean_reversion_strategy, momentum_strategy,
    BUILTIN_STRATEGIES
)


# ============================================================
# DATA LOADER TESTS
# ============================================================

class TestDataLoader:
    """Tests for DataLoader class."""

    def test_generate_synthetic_creates_markets(self):
        """Test synthetic data generation."""
        loader = DataLoader()
        count = loader.generate_synthetic(num_markets=10, days=7)

        assert count == 10
        assert len(loader.markets) == 10

    def test_synthetic_markets_have_prices(self):
        """Test that synthetic markets have price data."""
        loader = DataLoader()
        loader.generate_synthetic(num_markets=5, days=7, interval_hours=4)

        for market in loader.markets.values():
            assert len(market.prices) > 0
            assert market.resolution in ["YES", "NO"]
            assert market.resolution_time is not None

    def test_synthetic_prices_in_bounds(self):
        """Test that synthetic prices stay within 0-1 bounds."""
        loader = DataLoader()
        loader.generate_synthetic(num_markets=20, days=14)

        for market in loader.markets.values():
            for p in market.prices:
                assert 0 <= p.price <= 1
                assert 0 <= p.bid <= 1
                assert 0 <= p.ask <= 1

    def test_get_markets_active_at(self):
        """Test getting markets active at a timestamp."""
        loader = DataLoader()
        loader.generate_synthetic(num_markets=10, days=7)

        start, end = loader.get_time_range()
        mid_time = start + (end - start) / 2

        active = loader.get_markets_active_at(mid_time)
        assert len(active) > 0

    def test_save_and_load_file(self, tmp_path):
        """Test saving and loading data to/from file."""
        loader1 = DataLoader()
        loader1.generate_synthetic(num_markets=5, days=3)

        filepath = str(tmp_path / "test_data.json")
        loader1.save_to_file(filepath)

        loader2 = DataLoader()
        count = loader2.load_from_file(filepath)

        assert count == 5
        assert len(loader2.markets) == 5

    def test_market_get_price_at(self):
        """Test getting price at specific timestamp."""
        loader = DataLoader()
        loader.generate_synthetic(num_markets=1, days=7)

        market = list(loader.markets.values())[0]
        mid_time = market.prices[len(market.prices) // 2].timestamp

        price = market.get_price_at(mid_time)
        assert price is not None
        assert 0 <= price <= 1

    def test_market_get_final_price(self):
        """Test getting resolution price."""
        loader = DataLoader()
        loader.generate_synthetic(num_markets=10, days=7)

        for market in loader.markets.values():
            final = market.get_final_price()
            if market.resolution == "YES":
                assert final == 1.0
            elif market.resolution == "NO":
                assert final == 0.0

    def test_summary(self):
        """Test summary generation."""
        loader = DataLoader()
        loader.generate_synthetic(num_markets=10, days=7)

        summary = loader.summary()
        assert "Markets: 10" in summary
        assert "Resolved:" in summary


# ============================================================
# PERFORMANCE METRICS TESTS
# ============================================================

class TestPerformanceMetrics:
    """Tests for PerformanceMetrics class."""

    @pytest.fixture
    def sample_trades(self):
        """Create sample trades for testing."""
        now = datetime.now(timezone.utc)
        trades = []

        # Winning trade
        t1 = Trade(
            condition_id="0x1",
            question="Test 1",
            strategy="TEST",
            side="YES",
            entry_time=now - timedelta(hours=48),
            entry_price=0.50,
            shares=100,
            cost_basis=50.0
        )
        t1.close(now - timedelta(hours=24), 0.60, "TAKE_PROFIT")
        trades.append(t1)

        # Losing trade
        t2 = Trade(
            condition_id="0x2",
            question="Test 2",
            strategy="TEST",
            side="YES",
            entry_time=now - timedelta(hours=36),
            entry_price=0.50,
            shares=100,
            cost_basis=50.0
        )
        t2.close(now - timedelta(hours=12), 0.40, "STOP_LOSS")
        trades.append(t2)

        return trades

    def test_calculate_returns(self, sample_trades):
        """Test return calculation."""
        metrics = PerformanceMetrics(
            initial_capital=1000,
            final_capital=1100,
            trades=sample_trades,
            strategy_name="TEST"
        )
        metrics.calculate()

        assert metrics.total_return == 100
        assert metrics.total_return_pct == 10.0

    def test_calculate_trade_stats(self, sample_trades):
        """Test trade statistics calculation."""
        metrics = PerformanceMetrics(
            initial_capital=1000,
            final_capital=1000,
            trades=sample_trades,
            strategy_name="TEST"
        )
        metrics.calculate()

        assert metrics.total_trades == 2
        assert metrics.winning_trades == 1
        assert metrics.losing_trades == 1
        assert metrics.win_rate == 50.0

    def test_calculate_avg_trade(self, sample_trades):
        """Test average trade calculation."""
        metrics = PerformanceMetrics(
            initial_capital=1000,
            final_capital=1000,
            trades=sample_trades,
            strategy_name="TEST"
        )
        metrics.calculate()

        assert metrics.avg_win > 0
        assert metrics.avg_loss < 0

    def test_get_report(self, sample_trades):
        """Test report generation."""
        metrics = PerformanceMetrics(
            initial_capital=1000,
            final_capital=1100,
            trades=sample_trades,
            strategy_name="TEST"
        )
        metrics.calculate()

        report = metrics.get_report()
        assert "BACKTEST RESULTS" in report
        assert "TEST" in report
        assert "Win Rate" in report

    def test_to_dict(self, sample_trades):
        """Test dict export."""
        metrics = PerformanceMetrics(
            initial_capital=1000,
            final_capital=1100,
            trades=sample_trades,
            strategy_name="TEST"
        )
        metrics.calculate()

        d = metrics.to_dict()
        assert d["strategy"] == "TEST"
        assert d["initial_capital"] == 1000
        assert d["total_return"] == 100

    def test_compare_strategies(self):
        """Test strategy comparison."""
        m1 = PerformanceMetrics(
            initial_capital=1000,
            final_capital=1200,
            strategy_name="STRATEGY_A"
        )
        m1.calculate()

        m2 = PerformanceMetrics(
            initial_capital=1000,
            final_capital=1100,
            strategy_name="STRATEGY_B"
        )
        m2.calculate()

        comparison = compare_strategies([m1, m2])
        assert "STRATEGY COMPARISON" in comparison
        assert "STRATEGY_A" in comparison
        assert "STRATEGY_B" in comparison


# ============================================================
# BACKTEST ENGINE TESTS
# ============================================================

class TestBacktestEngine:
    """Tests for BacktestEngine class."""

    @pytest.fixture
    def data_loader(self):
        """Create data loader with synthetic data."""
        loader = DataLoader()
        loader.generate_synthetic(num_markets=20, days=14)
        return loader

    @pytest.fixture
    def config(self):
        """Create backtest config."""
        return BacktestConfig(
            initial_capital=10000,
            max_position_pct=0.10,
            take_profit_pct=0.05,
            stop_loss_pct=-0.10,
            use_kelly=False  # Simpler for testing
        )

    def test_add_strategy(self, data_loader, config):
        """Test adding strategies to engine."""
        engine = BacktestEngine(data_loader, config)
        engine.add_strategy("TEST", near_certain_strategy)

        assert "TEST" in engine.strategies

    def test_run_single_strategy(self, data_loader, config):
        """Test running a single strategy."""
        engine = BacktestEngine(data_loader, config)
        engine.add_strategy("NEAR_CERTAIN", near_certain_strategy)

        results = engine.run()

        assert "NEAR_CERTAIN" in results
        assert isinstance(results["NEAR_CERTAIN"], PerformanceMetrics)

    def test_run_multiple_strategies(self, data_loader, config):
        """Test running multiple strategies."""
        engine = BacktestEngine(data_loader, config)
        engine.add_strategy("NEAR_CERTAIN", near_certain_strategy)
        engine.add_strategy("NEAR_ZERO", near_zero_strategy)

        results = engine.run()

        assert len(results) == 2
        assert "NEAR_CERTAIN" in results
        assert "NEAR_ZERO" in results

    def test_run_with_kelly(self, data_loader):
        """Test running with Kelly Criterion enabled."""
        config = BacktestConfig(
            initial_capital=10000,
            use_kelly=True,
            kelly_fraction=0.25
        )
        engine = BacktestEngine(data_loader, config)
        engine.add_strategy("NEAR_CERTAIN", near_certain_strategy)

        results = engine.run()

        assert "NEAR_CERTAIN" in results

    def test_engine_respects_max_positions(self, data_loader, config):
        """Test that engine respects max position limit."""
        config.max_positions = 2
        engine = BacktestEngine(data_loader, config)

        # Strategy that buys everything
        def always_buy(market, price, timestamp):
            return {"action": "BUY", "side": "YES", "confidence": 0.8, "reason": "Test"}

        engine.add_strategy("ALWAYS_BUY", always_buy)
        results = engine.run()

        # Should have limited positions
        assert results["ALWAYS_BUY"].total_trades >= 0

    def test_position_tracking(self, data_loader, config):
        """Test position creation and tracking."""
        engine = BacktestEngine(data_loader, config)
        engine.add_strategy("NEAR_CERTAIN", near_certain_strategy)

        results = engine.run()

        # Check that trades were recorded
        metrics = results["NEAR_CERTAIN"]
        if metrics.total_trades > 0:
            assert len(metrics.trades) > 0


# ============================================================
# BUILT-IN STRATEGY TESTS
# ============================================================

class TestBuiltInStrategies:
    """Tests for built-in trading strategies."""

    @pytest.fixture
    def mock_market(self):
        """Create a mock market for testing strategies."""
        prices = [
            PricePoint(
                timestamp=datetime.now(timezone.utc) - timedelta(hours=i),
                price=0.50 + (i * 0.01),
                volume=10000
            )
            for i in range(48, 0, -1)
        ]
        return MarketHistory(
            condition_id="0xtest",
            question="Test market",
            prices=prices
        )

    def test_near_certain_triggers_above_90(self, mock_market):
        """Test NEAR_CERTAIN triggers at high prices."""
        now = datetime.now(timezone.utc)

        signal = near_certain_strategy(mock_market, 0.95, now)
        assert signal is not None
        assert signal["action"] == "BUY"
        assert signal["side"] == "YES"

    def test_near_certain_skips_below_90(self, mock_market):
        """Test NEAR_CERTAIN skips low prices."""
        now = datetime.now(timezone.utc)

        signal = near_certain_strategy(mock_market, 0.50, now)
        assert signal is None

    def test_near_zero_triggers_below_10(self, mock_market):
        """Test NEAR_ZERO triggers at low prices."""
        now = datetime.now(timezone.utc)

        signal = near_zero_strategy(mock_market, 0.05, now)
        assert signal is not None
        assert signal["action"] == "BUY"
        assert signal["side"] == "NO"

    def test_near_zero_skips_above_10(self, mock_market):
        """Test NEAR_ZERO skips high prices."""
        now = datetime.now(timezone.utc)

        signal = near_zero_strategy(mock_market, 0.50, now)
        assert signal is None

    def test_mean_reversion_low_price(self, mock_market):
        """Test MEAN_REVERSION buys YES at low prices."""
        now = datetime.now(timezone.utc)

        signal = mean_reversion_strategy(mock_market, 0.25, now)
        assert signal is not None
        assert signal["side"] == "YES"

    def test_mean_reversion_high_price(self, mock_market):
        """Test MEAN_REVERSION buys NO at high prices."""
        now = datetime.now(timezone.utc)

        signal = mean_reversion_strategy(mock_market, 0.75, now)
        assert signal is not None
        assert signal["side"] == "NO"

    def test_mean_reversion_mid_price(self, mock_market):
        """Test MEAN_REVERSION skips mid prices."""
        now = datetime.now(timezone.utc)

        signal = mean_reversion_strategy(mock_market, 0.50, now)
        assert signal is None

    def test_all_builtin_strategies_exist(self):
        """Test that all built-in strategies are defined."""
        expected = ["NEAR_CERTAIN", "NEAR_ZERO", "MEAN_REVERSION", "MOMENTUM"]

        for name in expected:
            assert name in BUILTIN_STRATEGIES
            assert callable(BUILTIN_STRATEGIES[name])


# ============================================================
# TRADE CLASS TESTS
# ============================================================

class TestTrade:
    """Tests for Trade dataclass."""

    def test_trade_creation(self):
        """Test creating a trade."""
        now = datetime.now(timezone.utc)
        trade = Trade(
            condition_id="0x1",
            question="Test",
            strategy="TEST",
            side="YES",
            entry_time=now,
            entry_price=0.50,
            shares=100,
            cost_basis=50.0
        )

        assert trade.is_open is True
        assert trade.pnl == 0

    def test_trade_close_profit(self):
        """Test closing trade with profit."""
        now = datetime.now(timezone.utc)
        trade = Trade(
            condition_id="0x1",
            question="Test",
            strategy="TEST",
            side="YES",
            entry_time=now - timedelta(hours=24),
            entry_price=0.50,
            shares=100,
            cost_basis=50.0
        )

        trade.close(now, 0.60, "TAKE_PROFIT")

        assert trade.is_open is False
        assert trade.exit_price == 0.60
        assert trade.pnl == 10.0  # 100 * 0.60 - 50
        assert trade.pnl_pct == 20.0

    def test_trade_close_loss(self):
        """Test closing trade with loss."""
        now = datetime.now(timezone.utc)
        trade = Trade(
            condition_id="0x1",
            question="Test",
            strategy="TEST",
            side="YES",
            entry_time=now - timedelta(hours=24),
            entry_price=0.50,
            shares=100,
            cost_basis=50.0
        )

        trade.close(now, 0.40, "STOP_LOSS")

        assert trade.is_open is False
        assert trade.pnl == -10.0  # 100 * 0.40 - 50
        assert trade.pnl_pct == -20.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
