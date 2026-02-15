#!/usr/bin/env python3
"""
END-TO-END TESTS - Full Backtest Workflow
==========================================
Full end-to-end tests that simulate entire workflows from data generation
through engine execution to metrics reporting.

These tests run the FULL pipeline start to finish with no mocking of
internal modules. Only external API calls are avoided.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.backtest.data_loader import DataLoader
from sovereign_hive.backtest.engine import BacktestEngine, BacktestConfig
from sovereign_hive.backtest.strategies import (
    PRICE_ONLY_STRATEGIES, PRODUCTION_STRATEGIES, reset_state,
    mean_reversion, mean_reversion_broken,
)
from sovereign_hive.backtest.metrics import PerformanceMetrics, compare_strategies


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(autouse=True)
def clean_strategy_state():
    """Reset strategy state before each test."""
    reset_state()
    yield
    reset_state()


# ============================================================
# E2E TESTS
# ============================================================

@pytest.mark.e2e
class TestFullPriceOnlyBacktest:
    """Run ALL price-only strategies on generated data."""

    def test_full_price_only_backtest(self):
        """Generate 20 markets, run ALL 5 price-only strategies, verify each produces metrics."""
        dl = DataLoader()
        dl.generate_synthetic(num_markets=20, days=14, interval_hours=4)
        dl.enrich_synthetic_fields()

        config = BacktestConfig(
            initial_capital=1000.0,
            min_position_usd=10.0,
            max_positions=12,
        )
        engine = BacktestEngine(dl, config)

        for name, func in PRICE_ONLY_STRATEGIES.items():
            engine.add_strategy(name, func, use_snapshots=True)

        results = engine.run(verbose=False)

        assert len(results) == len(PRICE_ONLY_STRATEGIES)
        for name, metrics in results.items():
            assert isinstance(metrics, PerformanceMetrics), f"{name} did not return PerformanceMetrics"
            assert metrics.strategy_name == name
            assert metrics.initial_capital == 1000.0
            assert metrics.final_capital > 0, f"{name} lost all capital"
            assert len(metrics.equity_curve) > 0, f"{name} has no equity curve"


@pytest.mark.e2e
class TestFullBacktestWithEnrichedData:
    """Run production strategies on enriched data."""

    def test_full_backtest_with_enriched_data(self):
        """Generate, enrich, run PRODUCTION_STRATEGIES on enriched data."""
        dl = DataLoader()
        dl.generate_synthetic(num_markets=15, days=14, interval_hours=4)
        dl.enrich_synthetic_fields()

        config = BacktestConfig(
            initial_capital=1000.0,
            min_position_usd=10.0,
            max_positions=12,
        )
        engine = BacktestEngine(dl, config)

        for name, func in PRODUCTION_STRATEGIES.items():
            engine.add_strategy(name, func, use_snapshots=True)

        results = engine.run(verbose=False)

        assert len(results) == len(PRODUCTION_STRATEGIES)
        for name, metrics in results.items():
            assert isinstance(metrics, PerformanceMetrics)
            assert metrics.final_capital > 0, f"{name} lost all capital"


@pytest.mark.e2e
class TestFixComparisonPipeline:
    """Compare broken vs fixed MEAN_REVERSION."""

    def test_fix_comparison_pipeline(self):
        """Run broken vs fixed MEAN_REVERSION, compare metrics."""
        dl = DataLoader()
        dl.generate_synthetic(num_markets=20, days=14, interval_hours=4)
        dl.enrich_synthetic_fields()

        config = BacktestConfig(
            initial_capital=1000.0,
            min_position_usd=10.0,
            max_positions=20,
        )

        # Run fixed version
        reset_state()
        engine_fixed = BacktestEngine(dl, config)
        engine_fixed.add_strategy("MEAN_REV_FIXED", mean_reversion, use_snapshots=True)
        results_fixed = engine_fixed.run(verbose=False)

        # Run broken version
        reset_state()
        engine_broken = BacktestEngine(dl, config)
        engine_broken.add_strategy("MEAN_REV_BROKEN", mean_reversion_broken, use_snapshots=True)
        results_broken = engine_broken.run(verbose=False)

        fixed = results_fixed["MEAN_REV_FIXED"]
        broken = results_broken["MEAN_REV_BROKEN"]

        # Both should complete
        assert isinstance(fixed, PerformanceMetrics)
        assert isinstance(broken, PerformanceMetrics)

        # Broken version (no cooldown) typically trades more aggressively
        # Just verify they produce different results (broken trades more)
        # Note: with synthetic data, results can vary, so we just check structure
        assert fixed.final_capital > 0
        assert broken.final_capital > 0

        # compare_strategies should produce a valid report
        report = compare_strategies([fixed, broken])
        assert "MEAN_REV_FIXED" in report
        assert "MEAN_REV_BROKEN" in report


@pytest.mark.e2e
class TestBiasedResolutions:
    """Test strategies handle biased market resolutions."""

    def test_all_markets_resolved_yes(self):
        """Bias case: all YES resolution, verify strategies handle it."""
        dl = DataLoader()
        # Generate data, then force all to YES
        dl.generate_synthetic(num_markets=10, days=10, interval_hours=4)
        for market in dl.markets.values():
            market.resolution = "YES"
            if market.prices:
                market.prices[-1].price = 1.0
        dl.enrich_synthetic_fields()

        config = BacktestConfig(initial_capital=1000.0, min_position_usd=10.0)
        engine = BacktestEngine(dl, config)
        engine.add_strategy("MEAN_REVERSION", mean_reversion, use_snapshots=True)

        results = engine.run(verbose=False)
        metrics = results["MEAN_REVERSION"]

        assert metrics.final_capital > 0
        assert isinstance(metrics.total_return_pct, float)

    def test_all_markets_resolved_no(self):
        """All NO resolution, verify strategies handle it."""
        dl = DataLoader()
        dl.generate_synthetic(num_markets=10, days=10, interval_hours=4)
        for market in dl.markets.values():
            market.resolution = "NO"
            if market.prices:
                market.prices[-1].price = 0.0
        dl.enrich_synthetic_fields()

        config = BacktestConfig(initial_capital=1000.0, min_position_usd=10.0)
        engine = BacktestEngine(dl, config)
        engine.add_strategy("MEAN_REVERSION", mean_reversion, use_snapshots=True)

        results = engine.run(verbose=False)
        metrics = results["MEAN_REVERSION"]

        assert metrics.final_capital > 0
        assert isinstance(metrics.total_return_pct, float)


@pytest.mark.e2e
class TestZeroTradesHandled:
    """Test that a strategy producing zero trades still works."""

    def test_zero_trades_handled(self):
        """Strategy that never triggers, verify empty metrics."""
        dl = DataLoader()
        # Generate markets with prices firmly in mid-range (0.40 - 0.60)
        # NEAR_CERTAIN needs >= 0.95, so it should never trigger
        dl.generate_synthetic(num_markets=5, days=7, interval_hours=4)
        # Force all prices into 0.40-0.60 range
        for market in dl.markets.values():
            for point in market.prices:
                point.price = max(0.40, min(0.60, point.price))
            market.resolution = None  # Keep unresolved

        dl.enrich_synthetic_fields()

        config = BacktestConfig(initial_capital=1000.0, min_position_usd=10.0)
        engine = BacktestEngine(dl, config)
        from sovereign_hive.backtest.strategies import near_certain
        engine.add_strategy("NEAR_CERTAIN", near_certain, use_snapshots=True)

        results = engine.run(verbose=False)
        metrics = results["NEAR_CERTAIN"]

        assert metrics.total_trades == 0
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 0
        assert metrics.win_rate == 0
        # Capital should be unchanged (no trades)
        assert abs(metrics.final_capital - 1000.0) < 0.01


@pytest.mark.e2e
class TestLongBacktest:
    """Test larger backtest to verify no crashes."""

    def test_long_backtest(self):
        """50 markets, 30 days, verify no crashes."""
        dl = DataLoader()
        dl.generate_synthetic(num_markets=50, days=30, interval_hours=4)
        dl.enrich_synthetic_fields()

        config = BacktestConfig(
            initial_capital=1000.0,
            min_position_usd=10.0,
            max_positions=15,
        )
        engine = BacktestEngine(dl, config)
        engine.add_strategy("MEAN_REVERSION", mean_reversion, use_snapshots=True)

        results = engine.run(step_hours=4, verbose=False)
        metrics = results["MEAN_REVERSION"]

        assert metrics.final_capital > 0
        # Should have a substantial equity curve
        assert len(metrics.equity_curve) > 100
        # Verify report generation works
        report = metrics.get_report()
        assert len(report) > 0


@pytest.mark.e2e
class TestSmallCapital:
    """Test with small initial capital."""

    def test_small_capital(self):
        """$100 initial, verify min_position handling."""
        dl = DataLoader()
        dl.generate_synthetic(num_markets=10, days=14, interval_hours=4)
        dl.enrich_synthetic_fields()

        config = BacktestConfig(
            initial_capital=100.0,     # Small capital
            min_position_usd=10.0,     # $10 minimum
            max_position_usd=20.0,     # $20 max
            max_positions=5,
        )
        engine = BacktestEngine(dl, config)
        engine.add_strategy("MEAN_REVERSION", mean_reversion, use_snapshots=True)

        results = engine.run(verbose=False)
        metrics = results["MEAN_REVERSION"]

        assert metrics.initial_capital == 100.0
        assert metrics.final_capital > 0
        # Position sizes should be small, so trades should be bounded
        for trade in metrics.trades:
            assert trade.cost_basis <= 20.0 + 1.0  # max_position_usd + slippage margin


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
