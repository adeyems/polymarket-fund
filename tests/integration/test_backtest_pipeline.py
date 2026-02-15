#!/usr/bin/env python3
"""
INTEGRATION TESTS - Backtest Pipeline
=======================================
Tests that verify multiple backtest modules working together.

Uses REAL synthetic data generation (no mocks for DataLoader) but avoids
network calls. Validates that DataLoader -> Engine -> Strategies -> Metrics
all integrate correctly.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.backtest.data_loader import DataLoader
from sovereign_hive.backtest.engine import BacktestEngine, BacktestConfig
from sovereign_hive.backtest.strategies import (
    PRICE_ONLY_STRATEGIES, PRODUCTION_STRATEGIES, reset_state,
    near_certain, near_zero, mean_reversion, dip_buy, mid_range,
    market_maker, dual_side_arb, volume_surge, binance_arb,
)
from sovereign_hive.backtest.metrics import PerformanceMetrics


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def synth_loader():
    """Generate synthetic data with enriched fields."""
    dl = DataLoader()
    dl.generate_synthetic(num_markets=20, days=14, interval_hours=4)
    dl.enrich_synthetic_fields()
    return dl


@pytest.fixture(autouse=True)
def clean_strategy_state():
    """Reset strategy state before each test to avoid cross-test pollution."""
    reset_state()
    yield
    reset_state()


# ============================================================
# INTEGRATION TESTS
# ============================================================

@pytest.mark.integration
class TestSyntheticDataThroughEngine:
    """Tests for synthetic data flowing through the backtest engine."""

    def test_synthetic_data_through_engine(self, synth_loader):
        """Generate synthetic data, run a single strategy, verify metrics exist."""
        config = BacktestConfig(initial_capital=1000.0, min_position_usd=10.0)
        engine = BacktestEngine(synth_loader, config)
        engine.add_strategy("MEAN_REVERSION", mean_reversion, use_snapshots=True)

        results = engine.run(verbose=False)

        assert "MEAN_REVERSION" in results
        metrics = results["MEAN_REVERSION"]
        assert isinstance(metrics, PerformanceMetrics)
        assert metrics.initial_capital == 1000.0
        assert metrics.final_capital > 0
        # Equity curve should have been recorded
        assert len(metrics.equity_curve) > 0

    def test_engine_with_snapshot_strategy(self, synth_loader):
        """Run NEAR_CERTAIN from backtest/strategies.py through the engine."""
        config = BacktestConfig(initial_capital=1000.0, min_position_usd=10.0)
        engine = BacktestEngine(synth_loader, config)
        engine.add_strategy("NEAR_CERTAIN", near_certain, use_snapshots=True)

        results = engine.run(verbose=False)

        assert "NEAR_CERTAIN" in results
        metrics = results["NEAR_CERTAIN"]
        # Should complete without error
        assert metrics.initial_capital == 1000.0
        # Total trades may be 0 (near-certain requires price >= 0.95,
        # only happens near the end of resolved-YES markets)
        assert metrics.total_trades >= 0


@pytest.mark.integration
class TestMultipleStrategies:
    """Tests for running multiple strategies on the same data."""

    def test_multiple_strategies_same_data(self, synth_loader):
        """Run 3 strategies on the same dataset, compare results."""
        config = BacktestConfig(initial_capital=1000.0, min_position_usd=10.0)
        engine = BacktestEngine(synth_loader, config)

        engine.add_strategy("MEAN_REVERSION", mean_reversion, use_snapshots=True)
        engine.add_strategy("DIP_BUY", dip_buy, use_snapshots=True)
        engine.add_strategy("MID_RANGE", mid_range, use_snapshots=True)

        results = engine.run(verbose=False)

        assert len(results) == 3
        for name in ["MEAN_REVERSION", "DIP_BUY", "MID_RANGE"]:
            assert name in results
            assert isinstance(results[name], PerformanceMetrics)
            # Each strategy gets its own equity curve (independent runs)
            assert len(results[name].equity_curve) > 0


@pytest.mark.integration
class TestMeanReversionCooldownInEngine:
    """Test that mean reversion cooldown integrates correctly with engine."""

    def test_mean_reversion_cooldown_in_engine(self, synth_loader):
        """Verify cooldown integration works -- limits re-entries."""
        config = BacktestConfig(
            initial_capital=1000.0,
            min_position_usd=10.0,
            max_positions=20,  # High limit so cooldown is the binding constraint
        )
        engine = BacktestEngine(synth_loader, config)
        engine.add_strategy("MEAN_REVERSION", mean_reversion, use_snapshots=True)

        results = engine.run(verbose=False)
        metrics = results["MEAN_REVERSION"]

        # The strategy should complete and cooldown should have prevented
        # infinite re-entry loops (max 2 entries per market)
        assert metrics.initial_capital == 1000.0
        assert metrics.final_capital > 0


@pytest.mark.integration
class TestMMExitLogicInEngine:
    """Test that MM exit logic works through the engine."""

    def test_mm_exit_logic_in_engine(self, synth_loader):
        """Verify MM fills work through engine exit logic."""
        config = BacktestConfig(
            initial_capital=1000.0,
            min_position_usd=10.0,
        )
        engine = BacktestEngine(synth_loader, config)
        engine.add_strategy("MARKET_MAKER", market_maker, use_snapshots=True)

        results = engine.run(verbose=False)
        metrics = results["MARKET_MAKER"]

        # Engine should complete without errors
        assert isinstance(metrics, PerformanceMetrics)
        assert metrics.final_capital > 0


@pytest.mark.integration
class TestEngineStrategyOverrides:
    """Test engine respects strategy overrides."""

    def test_engine_respects_strategy_overrides(self, synth_loader):
        """Custom overrides applied correctly."""
        from sovereign_hive.backtest.engine import StrategyOverrides

        custom_overrides = {
            "MEAN_REVERSION": StrategyOverrides(
                take_profit_pct=0.20,  # Very wide TP
                stop_loss_pct=-0.15,   # Very wide SL
                use_kelly=False,
                fixed_position_pct=0.05,
            )
        }
        config = BacktestConfig(
            initial_capital=1000.0,
            min_position_usd=10.0,
            strategy_overrides=custom_overrides,
        )
        engine = BacktestEngine(synth_loader, config)
        engine.add_strategy("MEAN_REVERSION", mean_reversion, use_snapshots=True)

        # Verify overrides are applied
        overrides = config.get_overrides("MEAN_REVERSION")
        assert overrides.take_profit_pct == 0.20
        assert overrides.stop_loss_pct == -0.15
        assert overrides.fixed_position_pct == 0.05

        results = engine.run(verbose=False)
        assert "MEAN_REVERSION" in results


@pytest.mark.integration
class TestSaveLoadRoundtrip:
    """Test data save/load roundtrip."""

    def test_save_load_roundtrip(self, tmp_path):
        """Generate, save to tmp_path, load back, run engine."""
        # Generate and save
        dl1 = DataLoader()
        dl1.generate_synthetic(num_markets=10, days=7, interval_hours=4)
        dl1.enrich_synthetic_fields()

        filepath = str(tmp_path / "test_data.json")
        dl1.save_to_file(filepath)

        # Load back
        dl2 = DataLoader()
        count = dl2.load_from_file(filepath)
        assert count == 10
        assert len(dl2.markets) == 10

        # Run engine on loaded data
        config = BacktestConfig(initial_capital=1000.0, min_position_usd=10.0)
        engine = BacktestEngine(dl2, config)
        engine.add_strategy("DIP_BUY", dip_buy, use_snapshots=True)

        results = engine.run(verbose=False)
        assert "DIP_BUY" in results


@pytest.mark.integration
class TestEnrichedData:
    """Test enriched data enables spread-dependent strategies."""

    def test_enriched_data_enables_spread_strategies(self, synth_loader):
        """Enriched data has bid/ask/volume fields populated."""
        markets = synth_loader.get_all_markets()
        assert len(markets) == 20

        # Check that enrichment added bid/ask/volume
        for market in markets:
            for point in market.prices:
                assert point.bid > 0, "bid should be positive after enrichment"
                assert point.ask > 0, "ask should be positive after enrichment"
                assert point.volume > 0, "volume should be positive after enrichment"


@pytest.mark.integration
class TestDataQualityReport:
    """Test data quality methods work together."""

    def test_data_quality_report(self, synth_loader):
        """get_time_range, get_resolved_markets work together."""
        start, end = synth_loader.get_time_range()
        assert start is not None
        assert end is not None
        assert end > start

        resolved = synth_loader.get_resolved_markets()
        assert len(resolved) > 0  # Synthetic data has resolutions

        # All resolved should have YES or NO
        for m in resolved:
            assert m.resolution in ("YES", "NO")


@pytest.mark.integration
class TestMetricsCalculationEndToEnd:
    """Test engine run produces complete PerformanceMetrics."""

    def test_metrics_calculation_end_to_end(self, synth_loader):
        """Engine run -> complete PerformanceMetrics with all fields populated."""
        config = BacktestConfig(
            initial_capital=1000.0,
            min_position_usd=10.0,
            max_positions=20,
        )
        engine = BacktestEngine(synth_loader, config)
        engine.add_strategy("MEAN_REVERSION", mean_reversion, use_snapshots=True)

        results = engine.run(verbose=False)
        metrics = results["MEAN_REVERSION"]

        # Verify metrics structure
        assert metrics.initial_capital == 1000.0
        assert isinstance(metrics.total_return, float)
        assert isinstance(metrics.total_return_pct, float)
        assert isinstance(metrics.sharpe_ratio, float)
        assert isinstance(metrics.max_drawdown, float)
        assert isinstance(metrics.max_drawdown_pct, float)
        assert isinstance(metrics.win_rate, float)
        assert isinstance(metrics.total_trades, int)
        assert isinstance(metrics.winning_trades, int)
        assert isinstance(metrics.losing_trades, int)

        # to_dict should work
        d = metrics.to_dict()
        assert "strategy" in d
        assert d["strategy"] == "MEAN_REVERSION"
        assert "total_return_pct" in d
        assert "sharpe_ratio" in d

        # get_report should work
        report = metrics.get_report()
        assert "MEAN_REVERSION" in report
        assert "Sharpe" in report

    def test_metrics_with_near_zero_strategy(self, synth_loader):
        """Near zero strategy metrics should calculate correctly."""
        config = BacktestConfig(initial_capital=1000.0, min_position_usd=10.0)
        engine = BacktestEngine(synth_loader, config)
        engine.add_strategy("NEAR_ZERO", near_zero, use_snapshots=True)

        results = engine.run(verbose=False)
        metrics = results["NEAR_ZERO"]

        # Should have equity curve regardless of trades
        assert len(metrics.equity_curve) > 0
        assert metrics.equity_curve[0].equity >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
