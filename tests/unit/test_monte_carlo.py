#!/usr/bin/env python3
"""
MONTE CARLO SIMULATION TESTS
==============================
Comprehensive tests for sovereign_hive/backtest/monte_carlo.py

Covers:
- MonteCarloResult dataclass
- run_monte_carlo() main simulation
- monte_carlo_report() text generation
- monte_carlo_histogram() ASCII rendering
- run_monte_carlo_from_metrics() convenience wrapper
- compare_strategies_monte_carlo() multi-strategy comparison
"""

import pytest
import random
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.backtest.monte_carlo import (
    MonteCarloResult,
    run_monte_carlo,
    monte_carlo_report,
    monte_carlo_histogram,
    run_monte_carlo_from_metrics,
    compare_strategies_monte_carlo,
)
from sovereign_hive.backtest.metrics import PerformanceMetrics, Trade, EquityPoint


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def sample_trades():
    """Create 20 closed trades with mixed P&L for Monte Carlo sampling."""
    now = datetime.now(timezone.utc)
    trades = []
    random.seed(42)
    for i in range(20):
        t = Trade(
            condition_id=f"0x{i:04x}",
            question=f"Trade {i}",
            strategy="TEST",
            side="YES",
            entry_time=now - timedelta(hours=100 - i * 4),
            entry_price=0.50,
            shares=100,
            cost_basis=50.0,
        )
        exit_price = 0.50 + random.uniform(-0.10, 0.15)
        t.close(now - timedelta(hours=96 - i * 4), exit_price, "TEST_EXIT")
        trades.append(t)
    return trades


@pytest.fixture
def sample_metrics(sample_trades):
    """Create PerformanceMetrics populated with sample trades."""
    now = datetime.now(timezone.utc)
    equity_curve = []
    equity = 1000.0
    for i, t in enumerate(sample_trades):
        equity += t.pnl
        equity_curve.append(
            EquityPoint(
                timestamp=now - timedelta(hours=100 - i * 4),
                equity=equity,
                cash=equity * 0.5,
                positions_value=equity * 0.5,
            )
        )
    m = PerformanceMetrics(
        initial_capital=1000,
        final_capital=equity,
        trades=sample_trades,
        equity_curve=equity_curve,
        strategy_name="TEST",
        start_time=now - timedelta(days=30),
        end_time=now,
    )
    m.calculate()
    return m


@pytest.fixture
def few_trades():
    """Create only 5 closed trades (below the minimum of 10)."""
    now = datetime.now(timezone.utc)
    trades = []
    random.seed(99)
    for i in range(5):
        t = Trade(
            condition_id=f"0x{i:04x}",
            question=f"Trade {i}",
            strategy="TEST",
            side="YES",
            entry_time=now - timedelta(hours=50 - i * 4),
            entry_price=0.50,
            shares=100,
            cost_basis=50.0,
        )
        exit_price = 0.50 + random.uniform(-0.05, 0.10)
        t.close(now - timedelta(hours=46 - i * 4), exit_price, "TEST_EXIT")
        trades.append(t)
    return trades


@pytest.fixture
def identical_trades():
    """Create trades that all have the same return."""
    now = datetime.now(timezone.utc)
    trades = []
    for i in range(15):
        t = Trade(
            condition_id=f"0x{i:04x}",
            question=f"Trade {i}",
            strategy="TEST",
            side="YES",
            entry_time=now - timedelta(hours=100 - i * 4),
            entry_price=0.50,
            shares=100,
            cost_basis=50.0,
        )
        t.close(now - timedelta(hours=96 - i * 4), 0.55, "TEST_EXIT")
        trades.append(t)
    return trades


# ============================================================
# MonteCarloResult DATACLASS TESTS
# ============================================================

class TestMonteCarloResult:
    """Tests for MonteCarloResult dataclass."""

    def test_default_values(self):
        """Test MonteCarloResult has correct defaults."""
        r = MonteCarloResult(num_simulations=100, num_trades_per_sim=20)
        assert r.num_simulations == 100
        assert r.num_trades_per_sim == 20
        assert r.mean_return_pct == 0.0
        assert r.prob_positive_return == 0.0
        assert r.all_returns == []
        assert r.all_drawdowns == []

    def test_mutable_defaults_independent(self):
        """Test that list defaults are independent across instances."""
        r1 = MonteCarloResult(num_simulations=10, num_trades_per_sim=5)
        r2 = MonteCarloResult(num_simulations=10, num_trades_per_sim=5)
        r1.all_returns.append(1.0)
        assert r2.all_returns == []


# ============================================================
# run_monte_carlo() TESTS
# ============================================================

class TestRunMonteCarlo:
    """Tests for the main run_monte_carlo function."""

    def test_basic_run_returns_valid_result(self, sample_trades):
        """Test that a basic run returns a MonteCarloResult with populated fields."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=100)
        assert isinstance(result, MonteCarloResult)
        assert result.num_simulations == 100
        assert len(result.all_returns) == 100
        assert len(result.all_drawdowns) == 100

    def test_requires_minimum_trades(self, few_trades):
        """Test that fewer than 10 closed trades raises ValueError."""
        with pytest.raises(ValueError, match="Need at least 10 closed trades"):
            run_monte_carlo(few_trades, seed=42)

    def test_seed_produces_reproducible_results(self, sample_trades):
        """Test that setting the same seed gives identical results."""
        r1 = run_monte_carlo(sample_trades, seed=42, num_simulations=200)
        r2 = run_monte_carlo(sample_trades, seed=42, num_simulations=200)
        assert r1.all_returns == r2.all_returns
        assert r1.mean_return_pct == r2.mean_return_pct

    def test_different_seeds_produce_different_results(self, sample_trades):
        """Test that different seeds produce different results."""
        r1 = run_monte_carlo(sample_trades, seed=42, num_simulations=200)
        r2 = run_monte_carlo(sample_trades, seed=99, num_simulations=200)
        assert r1.all_returns != r2.all_returns

    def test_num_simulations_matches_request(self, sample_trades):
        """Test that the number of simulated returns matches num_simulations."""
        for n in [50, 200, 500]:
            result = run_monte_carlo(sample_trades, seed=42, num_simulations=n)
            assert result.num_simulations == n
            assert len(result.all_returns) == n
            assert len(result.all_drawdowns) == n

    def test_confidence_intervals_ordered(self, sample_trades):
        """Test that CI values are logically ordered: 99_lower <= 95_lower <= 95_upper <= 99_upper."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=1000)
        assert result.ci_99_lower <= result.ci_95_lower
        assert result.ci_95_lower <= result.ci_95_upper
        assert result.ci_95_upper <= result.ci_99_upper

    def test_prob_positive_return_in_range(self, sample_trades):
        """Test that probability of positive return is between 0 and 1."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=500)
        assert 0.0 <= result.prob_positive_return <= 1.0

    def test_var_values_are_reasonable(self, sample_trades):
        """Test that VaR and CVaR are non-negative loss figures when positive."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=1000)
        # VaR 99 should be >= VaR 95 (worse percentile means bigger potential loss)
        assert result.var_99 >= result.var_95
        # CVaR should be >= VaR (conditional is always worse than the threshold)
        assert result.cvar_95 >= result.var_95

    def test_returns_sorted(self, sample_trades):
        """Test that all_returns list is sorted ascending."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=200)
        for i in range(1, len(result.all_returns)):
            assert result.all_returns[i] >= result.all_returns[i - 1]

    def test_min_max_return(self, sample_trades):
        """Test that min and max return match first/last of sorted list."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=200)
        assert result.min_return_pct == result.all_returns[0]
        assert result.max_return_pct == result.all_returns[-1]

    def test_custom_num_trades(self, sample_trades):
        """Test that num_trades parameter overrides default trade count."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=100, num_trades=10)
        assert result.num_trades_per_sim == 10

    def test_open_trades_are_filtered_out(self):
        """Test that open trades and zero-pnl trades are excluded."""
        now = datetime.now(timezone.utc)
        trades = []
        random.seed(42)
        # Create 12 closed non-zero-pnl trades
        for i in range(12):
            t = Trade(
                condition_id=f"0x{i:04x}",
                question=f"Trade {i}",
                strategy="TEST",
                side="YES",
                entry_time=now - timedelta(hours=100 - i * 4),
                entry_price=0.50,
                shares=100,
                cost_basis=50.0,
            )
            t.close(now - timedelta(hours=96 - i * 4), 0.55, "EXIT")
            trades.append(t)

        # Add 3 open trades
        for i in range(12, 15):
            t = Trade(
                condition_id=f"0x{i:04x}",
                question=f"Open Trade {i}",
                strategy="TEST",
                side="YES",
                entry_time=now - timedelta(hours=10),
                entry_price=0.50,
                shares=100,
                cost_basis=50.0,
            )
            trades.append(t)

        result = run_monte_carlo(trades, seed=42, num_simulations=50)
        assert isinstance(result, MonteCarloResult)
        # Default num_trades should be 12 (the closed ones)
        assert result.num_trades_per_sim == 12

    def test_identical_returns_simulation(self, identical_trades):
        """Test Monte Carlo with trades that all have the same return."""
        result = run_monte_carlo(identical_trades, seed=42, num_simulations=100)
        # All trades produce the same P&L so std deviation should be 0
        assert result.std_return_pct == pytest.approx(0.0, abs=1e-6)
        # All returns should be the same
        assert result.min_return_pct == pytest.approx(result.max_return_pct, abs=1e-6)

    def test_drawdown_metrics_populated(self, sample_trades):
        """Test that drawdown metrics are calculated."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=200)
        assert result.mean_max_drawdown >= 0
        assert result.worst_max_drawdown >= result.mean_max_drawdown


# ============================================================
# monte_carlo_report() TESTS
# ============================================================

class TestMonteCarloReport:
    """Tests for monte_carlo_report function."""

    def test_report_contains_expected_sections(self, sample_trades):
        """Test that the report contains all expected sections."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=200)
        report = monte_carlo_report(result, strategy_name="MY_STRAT")

        assert "MONTE CARLO SIMULATION" in report
        assert "MY_STRAT" in report
        assert "RETURN DISTRIBUTION" in report
        assert "CONFIDENCE INTERVALS" in report
        assert "RISK METRICS" in report
        assert "VALUE AT RISK" in report
        assert "DRAWDOWN DISTRIBUTION" in report

    def test_report_contains_numeric_values(self, sample_trades):
        """Test that the report contains numeric metric values."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=200)
        report = monte_carlo_report(result)

        # Check it contains formatted percentages and numbers
        assert "Mean Return:" in report
        assert "Median Return:" in report
        assert "Simulations:" in report
        assert "VaR 95%:" in report
        assert "CVaR 95%:" in report

    def test_report_default_strategy_name(self, sample_trades):
        """Test that default strategy name is 'Strategy'."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=50)
        report = monte_carlo_report(result)
        assert "Strategy" in report


# ============================================================
# monte_carlo_histogram() TESTS
# ============================================================

class TestMonteCarloHistogram:
    """Tests for monte_carlo_histogram function."""

    def test_histogram_renders_without_error(self, sample_trades):
        """Test basic histogram rendering."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=500)
        histogram = monte_carlo_histogram(result)
        assert isinstance(histogram, str)
        assert "RETURN DISTRIBUTION HISTOGRAM" in histogram

    def test_histogram_has_legend(self, sample_trades):
        """Test histogram includes legend markers."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=500)
        histogram = monte_carlo_histogram(result)
        assert "Positive" in histogram
        assert "Negative" in histogram
        assert "Mean:" in histogram
        assert "Median:" in histogram

    def test_histogram_identical_returns(self, identical_trades):
        """Test histogram when all returns are identical."""
        result = run_monte_carlo(identical_trades, seed=42, num_simulations=100)
        histogram = monte_carlo_histogram(result)
        assert "All returns identical" == histogram

    def test_histogram_custom_bins(self, sample_trades):
        """Test histogram with a custom number of bins."""
        result = run_monte_carlo(sample_trades, seed=42, num_simulations=200)
        hist_10 = monte_carlo_histogram(result, bins=10)
        hist_30 = monte_carlo_histogram(result, bins=30)
        # More bins means more lines
        assert len(hist_30.split("\n")) > len(hist_10.split("\n"))


# ============================================================
# run_monte_carlo_from_metrics() TESTS
# ============================================================

class TestRunMonteCarloFromMetrics:
    """Tests for run_monte_carlo_from_metrics convenience wrapper."""

    def test_from_metrics_works(self, sample_metrics):
        """Test that the convenience function runs successfully."""
        result = run_monte_carlo_from_metrics(sample_metrics, num_simulations=100, seed=42)
        assert isinstance(result, MonteCarloResult)
        assert result.num_simulations == 100

    def test_from_metrics_uses_initial_capital(self, sample_metrics):
        """Test that the function uses the metrics initial capital."""
        result = run_monte_carlo_from_metrics(sample_metrics, num_simulations=100, seed=42)
        assert result.num_trades_per_sim > 0


# ============================================================
# compare_strategies_monte_carlo() TESTS
# ============================================================

class TestCompareStrategiesMonteCarlo:
    """Tests for compare_strategies_monte_carlo function."""

    def test_compare_multiple_strategies(self, sample_metrics):
        """Test comparison across two differently-named strategies."""
        # Create a second metrics object with different name
        now = datetime.now(timezone.utc)
        trades2 = []
        random.seed(99)
        for i in range(15):
            t = Trade(
                condition_id=f"0xb{i:04x}",
                question=f"Trade B{i}",
                strategy="STRAT_B",
                side="YES",
                entry_time=now - timedelta(hours=100 - i * 4),
                entry_price=0.50,
                shares=100,
                cost_basis=50.0,
            )
            t.close(now - timedelta(hours=96 - i * 4), 0.50 + random.uniform(-0.08, 0.12), "EXIT")
            trades2.append(t)

        m2 = PerformanceMetrics(
            initial_capital=1000,
            final_capital=1050,
            trades=trades2,
            strategy_name="STRAT_B",
            start_time=now - timedelta(days=30),
            end_time=now,
        )
        m2.calculate()

        results_dict = {"STRAT_A": sample_metrics, "STRAT_B": m2}
        report = compare_strategies_monte_carlo(results_dict, num_simulations=200, seed=42)

        assert "MONTE CARLO STRATEGY COMPARISON" in report
        assert "STRAT_A" in report
        assert "STRAT_B" in report
        assert "Best Mean Return" in report

    def test_compare_skips_insufficient_trades(self, sample_metrics, few_trades, capsys):
        """Test that strategies with too few trades are skipped gracefully."""
        m_few = PerformanceMetrics(
            initial_capital=1000,
            final_capital=1010,
            trades=few_trades,
            strategy_name="FEW_TRADES",
        )
        m_few.calculate()

        results_dict = {"GOOD": sample_metrics, "FEW": m_few}
        report = compare_strategies_monte_carlo(results_dict, num_simulations=100, seed=42)

        assert "GOOD" in report
        assert "FEW" in report
        # FEW should show dashes since it was skipped
        assert "--" in report

    def test_compare_empty_dict(self):
        """Test comparison with empty results dict."""
        report = compare_strategies_monte_carlo({}, num_simulations=100, seed=42)
        assert "MONTE CARLO STRATEGY COMPARISON" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
