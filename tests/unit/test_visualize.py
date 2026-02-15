#!/usr/bin/env python3
"""
BACKTEST VISUALIZATION TESTS
==============================
Comprehensive tests for sovereign_hive/backtest/visualize.py

Covers:
- equity_curve_ascii() - ASCII equity curve rendering
- drawdown_chart_ascii() - ASCII drawdown chart rendering
- trade_distribution_ascii() - trade P&L histogram
- generate_full_report() - multi-strategy report generation
- export_equity_curve_csv() - CSV export
- OptimizationResult dataclass
- optimize_strategy_parameters() - grid search optimization
- optimization_report() - optimization results report
"""

import pytest
import random
import sys
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.backtest.visualize import (
    equity_curve_ascii,
    drawdown_chart_ascii,
    trade_distribution_ascii,
    generate_full_report,
    export_equity_curve_csv,
    OptimizationResult,
    optimize_strategy_parameters,
    optimization_report,
)
from sovereign_hive.backtest.metrics import PerformanceMetrics, Trade, EquityPoint


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def sample_trades():
    """Create 20 closed trades with mixed P&L."""
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
def sample_equity_curve():
    """Create a realistic equity curve with ups and downs."""
    now = datetime.now(timezone.utc)
    points = []
    equity = 1000.0
    random.seed(42)
    for i in range(50):
        equity += random.uniform(-20, 25)
        equity = max(equity, 100)  # Don't go to zero
        points.append(
            EquityPoint(
                timestamp=now - timedelta(hours=200 - i * 4),
                equity=equity,
                cash=equity * 0.6,
                positions_value=equity * 0.4,
            )
        )
    return points


@pytest.fixture
def sample_metrics(sample_trades, sample_equity_curve):
    """PerformanceMetrics with equity curve and trades."""
    now = datetime.now(timezone.utc)
    m = PerformanceMetrics(
        initial_capital=1000,
        final_capital=sample_equity_curve[-1].equity,
        trades=sample_trades,
        equity_curve=sample_equity_curve,
        strategy_name="TEST",
        start_time=now - timedelta(days=30),
        end_time=now,
    )
    m.calculate()
    return m


@pytest.fixture
def flat_equity_curve():
    """Equity curve where equity never changes (flat line)."""
    now = datetime.now(timezone.utc)
    return [
        EquityPoint(
            timestamp=now - timedelta(hours=100 - i * 4),
            equity=1000.0,
            cash=500.0,
            positions_value=500.0,
        )
        for i in range(25)
    ]


@pytest.fixture
def flat_metrics(flat_equity_curve):
    """Metrics with a flat equity curve (no gains, no losses)."""
    now = datetime.now(timezone.utc)
    m = PerformanceMetrics(
        initial_capital=1000,
        final_capital=1000,
        trades=[],
        equity_curve=flat_equity_curve,
        strategy_name="FLAT",
        start_time=now - timedelta(days=30),
        end_time=now,
    )
    m.calculate()
    return m


@pytest.fixture
def empty_metrics():
    """Metrics with no equity curve and no trades."""
    now = datetime.now(timezone.utc)
    m = PerformanceMetrics(
        initial_capital=1000,
        final_capital=1000,
        trades=[],
        equity_curve=[],
        strategy_name="EMPTY",
        start_time=now - timedelta(days=30),
        end_time=now,
    )
    m.calculate()
    return m


@pytest.fixture
def single_point_metrics():
    """Metrics with only one equity curve point."""
    now = datetime.now(timezone.utc)
    m = PerformanceMetrics(
        initial_capital=1000,
        final_capital=1000,
        trades=[],
        equity_curve=[
            EquityPoint(timestamp=now, equity=1000.0, cash=500.0, positions_value=500.0)
        ],
        strategy_name="SINGLE",
        start_time=now,
        end_time=now,
    )
    m.calculate()
    return m


@pytest.fixture
def same_pnl_trades():
    """All closed trades have the same P&L."""
    now = datetime.now(timezone.utc)
    trades = []
    for i in range(10):
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
        t.close(now - timedelta(hours=46 - i * 4), 0.55, "EXIT")
        trades.append(t)
    return trades


# ============================================================
# equity_curve_ascii() TESTS
# ============================================================

class TestEquityCurveAscii:
    """Tests for equity_curve_ascii function."""

    def test_renders_basic_chart(self, sample_metrics):
        """Test that a basic equity curve chart is produced."""
        chart = equity_curve_ascii(sample_metrics)
        assert isinstance(chart, str)
        assert "EQUITY CURVE" in chart
        assert "TEST" in chart

    def test_empty_equity_curve(self, empty_metrics):
        """Test handling of empty equity curve."""
        chart = equity_curve_ascii(empty_metrics)
        assert "No equity curve data available" in chart

    def test_single_point_equity_curve(self, single_point_metrics):
        """Test handling of single data point."""
        chart = equity_curve_ascii(single_point_metrics)
        assert "Insufficient data for chart" in chart

    def test_flat_equity_curve(self, flat_metrics):
        """Test handling of flat equity (range = 0, guard against div-by-zero)."""
        chart = equity_curve_ascii(flat_metrics)
        assert isinstance(chart, str)
        # Should still render something meaningful with the eq_range=1 guard
        assert "EQUITY CURVE" in chart

    def test_chart_contains_legend(self, sample_metrics):
        """Test that chart contains the legend line."""
        chart = equity_curve_ascii(sample_metrics)
        assert "Above initial" in chart
        assert "Below initial" in chart
        assert "Initial capital" in chart

    def test_chart_contains_summary(self, sample_metrics):
        """Test that chart contains final capital and drawdown info."""
        chart = equity_curve_ascii(sample_metrics)
        assert "Final:" in chart
        assert "Max Drawdown:" in chart
        assert "Sharpe:" in chart

    def test_chart_custom_dimensions(self, sample_metrics):
        """Test chart with custom width and height."""
        chart = equity_curve_ascii(sample_metrics, width=40, height=10)
        assert isinstance(chart, str)
        assert "EQUITY CURVE" in chart


# ============================================================
# drawdown_chart_ascii() TESTS
# ============================================================

class TestDrawdownChartAscii:
    """Tests for drawdown_chart_ascii function."""

    def test_renders_basic_drawdown(self, sample_metrics):
        """Test basic drawdown chart rendering."""
        chart = drawdown_chart_ascii(sample_metrics)
        assert isinstance(chart, str)
        assert "DRAWDOWN CHART" in chart

    def test_empty_equity_curve(self, empty_metrics):
        """Test drawdown chart with no equity data."""
        chart = drawdown_chart_ascii(empty_metrics)
        assert "No equity curve data available" in chart

    def test_no_drawdown_case(self, flat_metrics):
        """Test drawdown chart when there is no drawdown (flat equity)."""
        chart = drawdown_chart_ascii(flat_metrics)
        assert isinstance(chart, str)
        assert "DRAWDOWN CHART" in chart

    def test_drawdown_contains_max_indicator(self, sample_metrics):
        """Test that the chart notes the max drawdown."""
        chart = drawdown_chart_ascii(sample_metrics)
        assert "Max drawdown" in chart


# ============================================================
# trade_distribution_ascii() TESTS
# ============================================================

class TestTradeDistributionAscii:
    """Tests for trade_distribution_ascii function."""

    def test_renders_distribution(self, sample_metrics):
        """Test basic trade distribution rendering."""
        chart = trade_distribution_ascii(sample_metrics)
        assert isinstance(chart, str)
        assert "P&L DISTRIBUTION" in chart
        assert "trades)" in chart

    def test_no_trades(self, empty_metrics):
        """Test distribution with no closed trades."""
        chart = trade_distribution_ascii(empty_metrics)
        assert "No closed trades" in chart

    def test_all_same_pnl(self, same_pnl_trades):
        """Test distribution when all trades have the same PnL."""
        now = datetime.now(timezone.utc)
        m = PerformanceMetrics(
            initial_capital=1000,
            final_capital=1050,
            trades=same_pnl_trades,
            strategy_name="SAME",
            start_time=now - timedelta(days=30),
            end_time=now,
        )
        m.calculate()
        chart = trade_distribution_ascii(m)
        assert isinstance(chart, str)
        assert "P&L DISTRIBUTION" in chart

    def test_distribution_legend(self, sample_metrics):
        """Test that distribution has profit/loss legend."""
        chart = trade_distribution_ascii(sample_metrics)
        assert "Profit bins" in chart
        assert "Loss bins" in chart

    def test_distribution_shows_avg_win_loss(self, sample_metrics):
        """Test that distribution shows average win and loss."""
        chart = trade_distribution_ascii(sample_metrics)
        assert "Avg Win:" in chart
        assert "Avg Loss:" in chart


# ============================================================
# generate_full_report() TESTS
# ============================================================

class TestGenerateFullReport:
    """Tests for generate_full_report function."""

    def test_full_report_generation(self, sample_metrics):
        """Test generating full report with one strategy."""
        results = {"TEST": sample_metrics}
        report = generate_full_report(results)
        assert isinstance(report, str)
        assert "POLYMARKET STRATEGY BACKTEST REPORT" in report
        assert "STRATEGY COMPARISON" in report
        assert "TEST" in report

    def test_full_report_multiple_strategies(self, sample_metrics, flat_metrics):
        """Test report with multiple strategies."""
        results = {"TEST": sample_metrics, "FLAT": flat_metrics}
        report = generate_full_report(results)
        assert "TEST" in report
        assert "FLAT" in report

    def test_full_report_saves_to_file(self, sample_metrics, tmp_path):
        """Test that report saves to file when path is given."""
        output_file = str(tmp_path / "test_report.txt")
        results = {"TEST": sample_metrics}
        report = generate_full_report(results, output_path=output_file)

        assert Path(output_file).exists()
        saved_content = Path(output_file).read_text()
        assert saved_content == report

    def test_full_report_contains_charts(self, sample_metrics):
        """Test that full report includes equity and drawdown charts."""
        results = {"TEST": sample_metrics}
        report = generate_full_report(results)
        assert "EQUITY CURVE" in report
        assert "DRAWDOWN CHART" in report
        assert "P&L DISTRIBUTION" in report


# ============================================================
# export_equity_curve_csv() TESTS
# ============================================================

class TestExportEquityCurveCsv:
    """Tests for export_equity_curve_csv function."""

    def test_csv_creates_file(self, sample_metrics, tmp_path):
        """Test that CSV export creates a file."""
        output_file = str(tmp_path / "equity.csv")
        export_equity_curve_csv(sample_metrics, output_file)
        assert Path(output_file).exists()

    def test_csv_has_correct_header(self, sample_metrics, tmp_path):
        """Test that CSV has the expected column headers."""
        output_file = str(tmp_path / "equity.csv")
        export_equity_curve_csv(sample_metrics, output_file)

        content = Path(output_file).read_text()
        first_line = content.split("\n")[0]
        assert first_line == "timestamp,equity,cash,positions_value"

    def test_csv_row_count_matches(self, sample_metrics, tmp_path):
        """Test that CSV has one row per equity curve point plus header."""
        output_file = str(tmp_path / "equity.csv")
        export_equity_curve_csv(sample_metrics, output_file)

        content = Path(output_file).read_text().strip()
        lines = content.split("\n")
        # Header + one line per equity point
        assert len(lines) == 1 + len(sample_metrics.equity_curve)

    def test_csv_values_parseable(self, sample_metrics, tmp_path):
        """Test that CSV values can be parsed as numbers."""
        output_file = str(tmp_path / "equity.csv")
        export_equity_curve_csv(sample_metrics, output_file)

        content = Path(output_file).read_text().strip()
        lines = content.split("\n")
        for line in lines[1:]:  # Skip header
            parts = line.split(",")
            assert len(parts) == 4
            # timestamp is an ISO string, rest should be floats
            float(parts[1])
            float(parts[2])
            float(parts[3])


# ============================================================
# OptimizationResult & optimization_report() TESTS
# ============================================================

class TestOptimizationResult:
    """Tests for OptimizationResult dataclass."""

    def test_creation(self, sample_metrics):
        """Test creating an OptimizationResult."""
        r = OptimizationResult(
            parameters={"spread": 0.02, "timeout": 4},
            metrics=sample_metrics,
            score=1.5,
        )
        assert r.parameters == {"spread": 0.02, "timeout": 4}
        assert r.score == 1.5


class TestOptimizationReport:
    """Tests for optimization_report function."""

    def test_empty_results(self):
        """Test report with no results."""
        report = optimization_report([])
        assert "PARAMETER OPTIMIZATION RESULTS" in report
        assert "No valid results" in report

    def test_report_with_results(self, sample_metrics):
        """Test report with multiple optimization results."""
        results = [
            OptimizationResult(parameters={"p": 1}, metrics=sample_metrics, score=2.5),
            OptimizationResult(parameters={"p": 2}, metrics=sample_metrics, score=1.8),
            OptimizationResult(parameters={"p": 3}, metrics=sample_metrics, score=0.5),
        ]
        report = optimization_report(results, top_n=2)
        assert "PARAMETER OPTIMIZATION RESULTS" in report
        assert "BEST CONFIGURATION" in report
        assert "#1" in report
        assert "#2" in report
        # top_n=2, so #3 should not appear
        assert "#3" not in report

    def test_report_shows_best_parameters(self, sample_metrics):
        """Test that the best configuration section shows parameters."""
        results = [
            OptimizationResult(
                parameters={"spread": 0.02, "hold_hours": 4},
                metrics=sample_metrics,
                score=3.0,
            ),
        ]
        report = optimization_report(results)
        assert "spread" in report
        assert "hold_hours" in report


# ============================================================
# optimize_strategy_parameters() TESTS
# ============================================================

class TestOptimizeStrategyParameters:
    """Tests for optimize_strategy_parameters function."""

    def test_optimization_runs_and_returns_sorted(self):
        """Test that grid search runs all combinations and returns sorted."""
        # Mock engine and data loader
        mock_metrics = MagicMock(spec=PerformanceMetrics)
        mock_metrics.sharpe_ratio = 1.5
        mock_metrics.total_return_pct = 10.0
        mock_metrics.max_drawdown_pct = 5.0
        mock_metrics.win_rate = 60.0

        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = {"TEST_STRAT": mock_metrics}

        mock_engine_class = MagicMock(return_value=mock_engine_instance)
        mock_data_loader = MagicMock()
        mock_strategy_func = MagicMock()

        param_grid = {"param_a": [1, 2], "param_b": [10, 20]}

        # BacktestConfig is imported lazily inside optimize_strategy_parameters,
        # so patch it at the engine module where it is defined.
        with patch("sovereign_hive.backtest.engine.BacktestConfig"):
            results = optimize_strategy_parameters(
                engine_class=mock_engine_class,
                data_loader=mock_data_loader,
                strategy_func=mock_strategy_func,
                strategy_name="TEST_STRAT",
                param_grid=param_grid,
            )

        # 2 x 2 = 4 combinations
        assert len(results) == 4
        # Should be sorted by score descending
        for i in range(1, len(results)):
            assert results[i - 1].score >= results[i].score

    def test_optimization_handles_failures(self):
        """Test that failed combinations are skipped gracefully."""
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.side_effect = RuntimeError("Backtest failed")

        mock_engine_class = MagicMock(return_value=mock_engine_instance)
        mock_data_loader = MagicMock()
        mock_strategy_func = MagicMock()

        param_grid = {"param_a": [1, 2]}

        with patch("sovereign_hive.backtest.engine.BacktestConfig"):
            results = optimize_strategy_parameters(
                engine_class=mock_engine_class,
                data_loader=mock_data_loader,
                strategy_func=mock_strategy_func,
                strategy_name="TEST",
                param_grid=param_grid,
            )

        assert len(results) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
