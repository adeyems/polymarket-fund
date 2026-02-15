"""
Unit tests for CLI runner modules
===================================
Covers helper functions (not main()) from:
  - sovereign_hive/backtest/fix_tester.py
  - sovereign_hive/backtest/quick_backtest.py
  - sovereign_hive/backtest/fetch_data.py
  - sovereign_hive/backtest/run_backtest.py
  - sovereign_hive/run_strategy_tests.py
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock


# ============================================================
# Helpers
# ============================================================

def _make_perf_metrics(**overrides):
    """Create a mock PerformanceMetrics with sensible defaults."""
    defaults = dict(
        total_return_pct=15.0,
        total_trades=50,
        win_rate=62.0,
        sharpe_ratio=1.5,
        max_drawdown_pct=8.0,
        avg_trade=3.0,
        profit_factor=1.8,
        final_capital=1150.0,
        avg_win=6.0,
        avg_loss=-3.0,
        initial_capital=1000.0,
        strategy_name="TEST",
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    m.get_report = MagicMock(return_value="[REPORT]")
    m.to_dict = MagicMock(return_value=defaults)
    return m


# ============================================================
# fix_tester.py tests
# ============================================================

class TestFixTesterLoadData:

    @patch("sovereign_hive.backtest.fix_tester.DataLoader")
    def test_load_data_success(self, MockLoader):
        """load_data returns a DataLoader when data is present."""
        from sovereign_hive.backtest.fix_tester import load_data

        instance = MockLoader.return_value
        instance.DATA_DIR = Path("/fake/data")
        instance.preprocess_kaggle_to_cache.return_value = 100

        result = load_data(max_markets=50)
        assert result is instance
        instance.preprocess_kaggle_to_cache.assert_called_once()

    @patch("sovereign_hive.backtest.fix_tester.DataLoader")
    def test_load_data_exits_on_zero(self, MockLoader):
        """load_data calls sys.exit(1) when no data loaded."""
        from sovereign_hive.backtest.fix_tester import load_data

        instance = MockLoader.return_value
        instance.DATA_DIR = Path("/fake/data")
        instance.preprocess_kaggle_to_cache.return_value = 0

        with pytest.raises(SystemExit) as exc:
            load_data(max_markets=50)
        assert exc.value.code == 1


class TestFixTesterRunVersion:

    @patch("sovereign_hive.backtest.fix_tester.BacktestEngine")
    @patch("sovereign_hive.backtest.fix_tester.reset_state")
    def test_run_version_returns_strategy_result(self, mock_reset, MockEngine):
        """run_version returns the result for the named strategy."""
        from sovereign_hive.backtest.fix_tester import run_version

        fake_metrics = _make_perf_metrics()
        engine_inst = MockEngine.return_value
        engine_inst.run.return_value = {"MY_STRAT": fake_metrics}

        loader = MagicMock()
        result = run_version(loader, "MY_STRAT", lambda s: None, 1000.0, "LABEL")

        assert result is fake_metrics
        mock_reset.assert_called_once()
        engine_inst.add_strategy.assert_called_once()
        engine_inst.run.assert_called_once_with(verbose=False)


class TestFixTesterTestFix:

    @patch("sovereign_hive.backtest.fix_tester.run_version")
    @patch("sovereign_hive.backtest.fix_tester.PRODUCTION_STRATEGIES", {"MEAN_REVERSION": lambda s: None})
    @patch("sovereign_hive.backtest.fix_tester.BROKEN_STRATEGIES", {"MEAN_REVERSION": lambda s: None})
    def test_test_fix_returns_dict(self, mock_run):
        """test_fix returns dict with broken/fixed results."""
        from sovereign_hive.backtest.fix_tester import test_fix

        broken_m = _make_perf_metrics(total_return_pct=-5.0)
        fixed_m = _make_perf_metrics(total_return_pct=15.0)
        mock_run.side_effect = [broken_m, fixed_m]

        loader = MagicMock()
        result = test_fix(loader, "MEAN_REVERSION", capital=1000.0)

        assert result is not None
        assert result["strategy"] == "MEAN_REVERSION"
        assert result["broken"] is broken_m
        assert result["fixed"] is fixed_m

    @patch("sovereign_hive.backtest.fix_tester.PRODUCTION_STRATEGIES", {"MEAN_REVERSION": lambda s: None})
    @patch("sovereign_hive.backtest.fix_tester.BROKEN_STRATEGIES", {})
    def test_test_fix_returns_none_when_no_broken_version(self):
        """test_fix returns None when the strategy has no broken version."""
        from sovereign_hive.backtest.fix_tester import test_fix

        result = test_fix(MagicMock(), "MEAN_REVERSION")
        assert result is None

    @patch("sovereign_hive.backtest.fix_tester.PRODUCTION_STRATEGIES", {})
    @patch("sovereign_hive.backtest.fix_tester.BROKEN_STRATEGIES", {"MEAN_REVERSION": lambda s: None})
    def test_test_fix_returns_none_when_no_production_version(self):
        """test_fix returns None when the strategy has no production version."""
        from sovereign_hive.backtest.fix_tester import test_fix

        result = test_fix(MagicMock(), "MEAN_REVERSION")
        assert result is None


class TestFixTesterPrintComparison:

    def test_print_comparison_fix_validated(self, capsys):
        """print_comparison prints metrics table and returns verdict for validated fix."""
        from sovereign_hive.backtest.fix_tester import print_comparison

        broken = _make_perf_metrics(
            total_return_pct=-5.0, win_rate=40.0, sharpe_ratio=0.5,
            max_drawdown_pct=20.0, final_capital=950.0, profit_factor=0.8,
            avg_win=5.0, avg_loss=-6.0, total_trades=30,
        )
        fixed = _make_perf_metrics(
            total_return_pct=15.0, win_rate=62.0, sharpe_ratio=1.5,
            max_drawdown_pct=8.0, final_capital=1150.0, profit_factor=1.8,
            avg_win=6.0, avg_loss=-3.0, total_trades=50,
        )

        result_dict = {"strategy": "TEST_STRAT", "broken": broken, "fixed": fixed}
        verdict = print_comparison(result_dict)

        captured = capsys.readouterr()
        assert "TEST_STRAT" in captured.out
        assert "BROKEN" in captured.out
        assert "FIXED" in captured.out
        assert verdict == "FIX VALIDATED"

    def test_print_comparison_fix_rejected(self, capsys):
        """print_comparison returns FIX REJECTED when fixed is worse."""
        from sovereign_hive.backtest.fix_tester import print_comparison

        # fixed is worse on all metrics
        broken = _make_perf_metrics(
            total_return_pct=15.0, win_rate=62.0, sharpe_ratio=1.5,
            max_drawdown_pct=8.0, final_capital=1150.0, profit_factor=1.8,
            avg_win=6.0, avg_loss=-3.0, total_trades=50,
        )
        fixed = _make_perf_metrics(
            total_return_pct=-5.0, win_rate=40.0, sharpe_ratio=0.5,
            max_drawdown_pct=20.0, final_capital=950.0, profit_factor=0.8,
            avg_win=5.0, avg_loss=-6.0, total_trades=30,
        )

        result_dict = {"strategy": "BAD_FIX", "broken": broken, "fixed": fixed}
        verdict = print_comparison(result_dict)
        assert verdict == "FIX REJECTED"


class TestFixTesterSaveReport:

    def test_save_report_writes_markdown(self, tmp_path):
        """save_report creates a markdown file with proper table structure."""
        from sovereign_hive.backtest.fix_tester import save_report

        broken = _make_perf_metrics(total_return_pct=-5.0, win_rate=40.0)
        fixed = _make_perf_metrics(total_return_pct=15.0, win_rate=62.0)

        results = [
            {
                "strategy": "MEAN_REVERSION",
                "result": {"broken": broken, "fixed": fixed},
                "verdict": "FIX VALIDATED",
            }
        ]

        filepath = str(tmp_path / "fix_results.md")
        save_report(results, filepath=filepath)

        content = Path(filepath).read_text()
        assert "# Fix Test Results" in content
        assert "MEAN_REVERSION" in content
        assert "FIX VALIDATED" in content
        assert "|" in content  # Table rows


# ============================================================
# quick_backtest.py tests
# ============================================================

class TestQuickBacktestLoadKaggleData:

    @patch("sovereign_hive.backtest.quick_backtest.DataLoader")
    def test_load_kaggle_data_success(self, MockLoader):
        """load_kaggle_data returns a DataLoader on success."""
        from sovereign_hive.backtest.quick_backtest import load_kaggle_data

        instance = MockLoader.return_value
        instance.DATA_DIR = Path("/fake/data")
        instance.preprocess_kaggle_to_cache.return_value = 200

        result = load_kaggle_data(max_markets=100, min_points=50)
        assert result is instance

    @patch("sovereign_hive.backtest.quick_backtest.DataLoader")
    def test_load_kaggle_data_exits_on_zero(self, MockLoader):
        """load_kaggle_data sys.exit(1) when nothing loaded."""
        from sovereign_hive.backtest.quick_backtest import load_kaggle_data

        instance = MockLoader.return_value
        instance.DATA_DIR = Path("/fake/data")
        instance.preprocess_kaggle_to_cache.return_value = 0

        with pytest.raises(SystemExit) as exc:
            load_kaggle_data()
        assert exc.value.code == 1


class TestQuickBacktestPrintDataQuality:

    def test_print_data_quality_output(self, capsys):
        """print_data_quality prints a formatted quality report."""
        from sovereign_hive.backtest.quick_backtest import print_data_quality

        market1 = MagicMock()
        market1.resolution = "YES"
        market2 = MagicMock()
        market2.resolution = "NO"
        market3 = MagicMock()
        market3.resolution = None

        loader = MagicMock()
        loader.markets = {"m1": market1, "m2": market2, "m3": market3}
        loader.get_time_range.return_value = (
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 6, 1, tzinfo=timezone.utc),
        )

        print_data_quality(loader)
        captured = capsys.readouterr()

        assert "DATA QUALITY REPORT" in captured.out
        assert "Markets:     3" in captured.out
        assert "Resolved:    2" in captured.out
        assert "1 YES" in captured.out
        assert "1 NO" in captured.out
        assert "Kaggle" in captured.out

    def test_print_data_quality_bias_warning(self, capsys):
        """print_data_quality shows bias warning when resolution is >70% one-sided."""
        from sovereign_hive.backtest.quick_backtest import print_data_quality

        # Create 8 YES resolved and 2 NO resolved -> 80% YES bias
        markets = {}
        for i in range(8):
            m = MagicMock()
            m.resolution = "YES"
            markets[f"yes_{i}"] = m
        for i in range(2):
            m = MagicMock()
            m.resolution = "NO"
            markets[f"no_{i}"] = m

        loader = MagicMock()
        loader.markets = markets
        loader.get_time_range.return_value = (
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 6, 1, tzinfo=timezone.utc),
        )

        print_data_quality(loader)
        captured = capsys.readouterr()

        assert "WARNING" in captured.out
        assert "bias" in captured.out.lower()
        assert "YES" in captured.out


class TestQuickBacktestRunStrategies:

    @patch("sovereign_hive.backtest.quick_backtest.BacktestEngine")
    @patch("sovereign_hive.backtest.quick_backtest.reset_state")
    def test_run_strategies_returns_results(self, mock_reset, MockEngine):
        """run_strategies runs each strategy and collects results."""
        from sovereign_hive.backtest.quick_backtest import run_strategies

        fake_metrics = _make_perf_metrics(total_return_pct=10.0)
        engine_inst = MockEngine.return_value
        engine_inst.run.return_value = {"STRAT_A": fake_metrics}

        loader = MagicMock()
        strategies = {"STRAT_A": lambda s: None}

        result = run_strategies(loader, strategies, capital=1000.0, verbose=False)
        assert "STRAT_A" in result
        assert result["STRAT_A"] is fake_metrics

    @patch("sovereign_hive.backtest.quick_backtest.BacktestEngine")
    @patch("sovereign_hive.backtest.quick_backtest.reset_state")
    def test_run_strategies_skips_missing(self, mock_reset, MockEngine):
        """run_strategies skips strategies not returned by engine."""
        from sovereign_hive.backtest.quick_backtest import run_strategies

        engine_inst = MockEngine.return_value
        engine_inst.run.return_value = {}  # Strategy name not in results

        loader = MagicMock()
        strategies = {"STRAT_X": lambda s: None}

        result = run_strategies(loader, strategies)
        assert result == {}


class TestQuickBacktestPrintResultsTable:

    @patch("sovereign_hive.backtest.quick_backtest.count_snapshot_days", return_value=3)
    def test_print_results_table_with_results_and_skipped(self, mock_days, capsys):
        """print_results_table prints a formatted table and lists skipped strategies."""
        from sovereign_hive.backtest.quick_backtest import print_results_table

        results = {
            "NEAR_CERTAIN": _make_perf_metrics(total_return_pct=20.0, total_trades=40,
                                                win_rate=65.0, sharpe_ratio=1.8,
                                                max_drawdown_pct=5.0, avg_trade=5.0,
                                                profit_factor=2.0),
            "MID_RANGE": _make_perf_metrics(total_return_pct=-12.0, total_trades=30,
                                             win_rate=35.0, sharpe_ratio=0.3,
                                             max_drawdown_pct=18.0, avg_trade=-4.0,
                                             profit_factor=0.6),
        }
        skipped = ["MARKET_MAKER", "DUAL_SIDE_ARB"]

        print_results_table(results, skipped)
        captured = capsys.readouterr()

        assert "BACKTEST RESULTS" in captured.out
        assert "NEAR_CERTAIN" in captured.out
        assert "MID_RANGE" in captured.out
        assert "MARKET_MAKER" in captured.out
        assert "NEEDS REAL DATA" in captured.out
        assert "STRONG" in captured.out  # NEAR_CERTAIN is STRONG
        assert "LOSING" in captured.out  # MID_RANGE is LOSING

    def test_print_results_table_no_skipped(self, capsys):
        """print_results_table works without skipped strategies."""
        from sovereign_hive.backtest.quick_backtest import print_results_table

        results = {
            "NEAR_CERTAIN": _make_perf_metrics(total_return_pct=5.0, total_trades=10,
                                                win_rate=55.0, sharpe_ratio=1.0,
                                                max_drawdown_pct=3.0, avg_trade=5.0,
                                                profit_factor=1.2),
        }
        print_results_table(results)
        captured = capsys.readouterr()
        assert "BACKTEST RESULTS" in captured.out
        assert "NEAR_CERTAIN" in captured.out

    def test_print_results_table_no_trades_verdict(self, capsys):
        """print_results_table shows NO TRADES when total_trades is 0."""
        from sovereign_hive.backtest.quick_backtest import print_results_table

        results = {
            "DEAD_STRAT": _make_perf_metrics(total_return_pct=0.0, total_trades=0,
                                              win_rate=0.0, sharpe_ratio=0.0,
                                              max_drawdown_pct=0.0, avg_trade=0.0,
                                              profit_factor=0.0),
        }
        print_results_table(results)
        captured = capsys.readouterr()
        assert "NO TRADES" in captured.out

    def test_print_results_table_positive_verdict(self, capsys):
        """print_results_table shows POSITIVE for return > 0 but not STRONG."""
        from sovereign_hive.backtest.quick_backtest import print_results_table

        results = {
            "OK_STRAT": _make_perf_metrics(total_return_pct=5.0, total_trades=20,
                                            win_rate=50.0, sharpe_ratio=0.8,
                                            max_drawdown_pct=4.0, avg_trade=2.5,
                                            profit_factor=1.1),
        }
        print_results_table(results)
        captured = capsys.readouterr()
        assert "POSITIVE" in captured.out

    def test_print_results_table_marginal_verdict(self, capsys):
        """print_results_table shows MARGINAL for -10 < return <= 0."""
        from sovereign_hive.backtest.quick_backtest import print_results_table

        results = {
            "MEH_STRAT": _make_perf_metrics(total_return_pct=-5.0, total_trades=15,
                                             win_rate=45.0, sharpe_ratio=0.2,
                                             max_drawdown_pct=12.0, avg_trade=-3.0,
                                             profit_factor=0.9),
        }
        print_results_table(results)
        captured = capsys.readouterr()
        assert "MARGINAL" in captured.out

    def test_print_results_table_inf_profit_factor(self, capsys):
        """print_results_table shows INF when profit_factor >= 999."""
        from sovereign_hive.backtest.quick_backtest import print_results_table

        results = {
            "PERFECT": _make_perf_metrics(total_return_pct=25.0, total_trades=10,
                                           win_rate=100.0, sharpe_ratio=3.0,
                                           max_drawdown_pct=1.0, avg_trade=25.0,
                                           profit_factor=float('inf')),
        }
        print_results_table(results)
        captured = capsys.readouterr()
        assert "INF" in captured.out


class TestQuickBacktestSaveResults:

    def test_save_results_writes_markdown(self, tmp_path):
        """save_results creates a markdown report at the given filepath."""
        from sovereign_hive.backtest.quick_backtest import save_results

        results = {
            "NEAR_CERTAIN": _make_perf_metrics(total_return_pct=12.0, total_trades=40,
                                                win_rate=60.0, sharpe_ratio=1.5,
                                                max_drawdown_pct=7.0),
        }
        skipped = ["MARKET_MAKER"]
        filepath = str(tmp_path / "results.md")

        save_results(results, skipped, filepath=filepath)

        content = Path(filepath).read_text()
        assert "# Backtest Results" in content
        assert "NEAR_CERTAIN" in content
        assert "MARKET_MAKER" in content
        assert "NEEDS REAL DATA" in content


class TestQuickBacktestRunFixTest:

    @patch("sovereign_hive.backtest.quick_backtest.BacktestEngine")
    @patch("sovereign_hive.backtest.quick_backtest.reset_state")
    @patch("sovereign_hive.backtest.quick_backtest.PRODUCTION_STRATEGIES", {"MEAN_REVERSION": lambda s: None})
    @patch("sovereign_hive.backtest.quick_backtest.BROKEN_STRATEGIES", {"MEAN_REVERSION": lambda s: None})
    def test_run_fix_test_prints_comparison(self, mock_reset, MockEngine, capsys):
        """run_fix_test prints comparison table and verdict."""
        from sovereign_hive.backtest.quick_backtest import run_fix_test

        broken_m = _make_perf_metrics(total_return_pct=-5.0, win_rate=40.0,
                                       sharpe_ratio=0.5, max_drawdown_pct=20.0,
                                       final_capital=950.0, total_trades=30)
        fixed_m = _make_perf_metrics(total_return_pct=15.0, win_rate=62.0,
                                      sharpe_ratio=1.5, max_drawdown_pct=8.0,
                                      final_capital=1150.0, total_trades=50)

        engine_inst = MockEngine.return_value
        # First call returns broken, second returns fixed
        engine_inst.run.side_effect = [
            {"MEAN_REVERSION": broken_m},
            {"MEAN_REVERSION": fixed_m},
        ]

        loader = MagicMock()
        run_fix_test(loader, "MEAN_REVERSION", capital=1000.0)

        captured = capsys.readouterr()
        assert "FIX TEST" in captured.out
        assert "MEAN_REVERSION" in captured.out
        assert "VERDICT" in captured.out

    @patch("sovereign_hive.backtest.quick_backtest.BROKEN_STRATEGIES", {})
    def test_run_fix_test_exits_when_no_broken(self):
        """run_fix_test calls sys.exit(1) when no broken version exists."""
        from sovereign_hive.backtest.quick_backtest import run_fix_test

        with pytest.raises(SystemExit) as exc:
            run_fix_test(MagicMock(), "NONEXISTENT")
        assert exc.value.code == 1

    @patch("sovereign_hive.backtest.quick_backtest.BacktestEngine")
    @patch("sovereign_hive.backtest.quick_backtest.reset_state")
    @patch("sovereign_hive.backtest.quick_backtest.PRODUCTION_STRATEGIES", {"TEST": lambda s: None})
    @patch("sovereign_hive.backtest.quick_backtest.BROKEN_STRATEGIES", {"TEST": lambda s: None})
    def test_run_fix_test_handles_no_results(self, mock_reset, MockEngine, capsys):
        """run_fix_test prints error when engine returns no results."""
        from sovereign_hive.backtest.quick_backtest import run_fix_test

        engine_inst = MockEngine.return_value
        engine_inst.run.return_value = {}  # Empty results for both

        loader = MagicMock()
        run_fix_test(loader, "TEST", capital=1000.0)

        captured = capsys.readouterr()
        assert "ERROR" in captured.out


# ============================================================
# fetch_data.py tests
# ============================================================

class TestFetchData:

    @patch("sovereign_hive.backtest.fetch_data.DataLoader")
    def test_fetch_from_api(self, MockLoader):
        """fetch_from_api calls build_dataset_from_api and returns count."""
        from sovereign_hive.backtest.fetch_data import fetch_from_api
        import asyncio

        instance = MockLoader.return_value
        instance.build_dataset_from_api = AsyncMock(return_value=42)

        count = asyncio.run(fetch_from_api(instance, num_markets=50))
        assert count == 42
        instance.build_dataset_from_api.assert_awaited_once_with(
            num_markets=50, include_resolved=True
        )

    @patch("sovereign_hive.backtest.fetch_data.DataLoader")
    def test_load_from_kaggle(self, MockLoader):
        """load_from_kaggle calls load_kaggle_dataset and returns count."""
        from sovereign_hive.backtest.fetch_data import load_from_kaggle

        instance = MockLoader.return_value
        instance.load_kaggle_dataset.return_value = 100

        count = load_from_kaggle(instance, "/fake/data.zip", max_markets=50)
        assert count == 100
        instance.load_kaggle_dataset.assert_called_once_with(
            "/fake/data.zip", max_markets=50
        )


# ============================================================
# run_backtest.py tests
# ============================================================

class TestRunBacktest:

    def test_module_imports(self):
        """run_backtest.py exports a main() function."""
        from sovereign_hive.backtest import run_backtest
        assert hasattr(run_backtest, "main")
        assert callable(run_backtest.main)

    @patch("sovereign_hive.backtest.run_backtest.BacktestEngine")
    @patch("sovereign_hive.backtest.run_backtest.DataLoader")
    def test_builtin_strategies_dict_exists(self, MockLoader, MockEngine):
        """run_backtest module exposes BUILTIN_STRATEGIES dict."""
        from sovereign_hive.backtest.run_backtest import BUILTIN_STRATEGIES
        assert isinstance(BUILTIN_STRATEGIES, dict)
        assert len(BUILTIN_STRATEGIES) > 0


# ============================================================
# run_strategy_tests.py tests
# ============================================================

class TestRunStrategyTests:

    def test_strategies_constant(self):
        """STRATEGIES list contains all 9 strategy names."""
        from sovereign_hive.run_strategy_tests import STRATEGIES
        assert len(STRATEGIES) == 9
        assert "MARKET_MAKER" in STRATEGIES
        assert "MEAN_REVERSION" in STRATEGIES
        assert "DIP_BUY" in STRATEGIES

    def test_log_dir_constant(self):
        """LOG_DIR points to the strategies log directory."""
        from sovereign_hive.run_strategy_tests import LOG_DIR
        assert "strategies" in LOG_DIR

    def test_create_strategy_config(self, tmp_path):
        """create_strategy_config writes a valid JSON config file."""
        import sovereign_hive.run_strategy_tests as rst
        # Temporarily redirect LOG_DIR
        original = rst.LOG_DIR
        rst.LOG_DIR = str(tmp_path)
        try:
            config_file = rst.create_strategy_config("MARKET_MAKER")
            assert Path(config_file).exists()

            with open(config_file) as f:
                config = json.load(f)

            assert config["initial_balance"] == 1000
            assert config["enabled_strategies"] == ["MARKET_MAKER"]
            assert config["strategy_name"] == "MARKET_MAKER"
            # MM-specific settings
            assert "mm_min_spread" in config
        finally:
            rst.LOG_DIR = original

    def test_create_strategy_config_generic(self, tmp_path):
        """create_strategy_config for a non-MM strategy has basic fields only."""
        import sovereign_hive.run_strategy_tests as rst
        original = rst.LOG_DIR
        rst.LOG_DIR = str(tmp_path)
        try:
            config_file = rst.create_strategy_config("DIP_BUY")
            with open(config_file) as f:
                config = json.load(f)

            assert config["strategy_name"] == "DIP_BUY"
            assert "mm_min_spread" not in config
        finally:
            rst.LOG_DIR = original

    def test_project_root_constant(self):
        """PROJECT_ROOT points to the polymarket-fund directory."""
        from sovereign_hive.run_strategy_tests import PROJECT_ROOT
        assert "polymarket-fund" in PROJECT_ROOT

    @patch("sovereign_hive.run_strategy_tests.subprocess.run")
    def test_launch_strategy_test_calls_subprocess(self, mock_run, tmp_path, capsys):
        """launch_strategy_test invokes subprocess.run with the strategy command."""
        import sovereign_hive.run_strategy_tests as rst

        mock_run.return_value = MagicMock(returncode=0, stderr="")

        original = rst.LOG_DIR
        rst.LOG_DIR = str(tmp_path)
        try:
            # Create the log file that launch_strategy_test expects to clear
            log_file = tmp_path / "MEAN_REVERSION.log"
            log_file.write_text("old content")

            result = rst.launch_strategy_test("MEAN_REVERSION", 2)
            assert result == str(log_file)
            mock_run.assert_called_once()
            # Verify the command contains the strategy name
            call_args = mock_run.call_args
            assert "MEAN_REVERSION" in call_args[0][0]
        finally:
            rst.LOG_DIR = original

    @patch("sovereign_hive.run_strategy_tests.subprocess.run")
    def test_launch_strategy_test_reports_error(self, mock_run, tmp_path, capsys):
        """launch_strategy_test prints error when subprocess fails."""
        import sovereign_hive.run_strategy_tests as rst

        mock_run.return_value = MagicMock(returncode=1, stderr="some error")

        original = rst.LOG_DIR
        rst.LOG_DIR = str(tmp_path)
        try:
            log_file = tmp_path / "BAD_STRAT.log"
            log_file.write_text("")

            rst.launch_strategy_test("BAD_STRAT", 1)
            captured = capsys.readouterr()
            assert "Error" in captured.out or "BAD_STRAT" in captured.out
        finally:
            rst.LOG_DIR = original
