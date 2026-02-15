#!/usr/bin/env python3
"""
COMPARE STRATEGIES TESTS
=========================
Tests for the strategy comparison dashboard.
"""

import pytest
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.ab_test.compare_strategies import (
    load_portfolio, calculate_metrics, STRATEGIES
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def mock_portfolio_data():
    """Sample portfolio data for testing."""
    return {
        "balance": 1050.0,
        "initial_balance": 1000.0,
        "positions": {
            "0xpos1": {
                "condition_id": "0xpos1",
                "question": "Test position 1",
                "side": "YES",
                "entry_price": 0.50,
                "shares": 100,
                "cost_basis": 50,
            }
        },
        "trade_history": [
            {"condition_id": "0x1", "question": "Trade 1", "pnl": 10.0, "exit_reason": "TAKE_PROFIT"},
            {"condition_id": "0x2", "question": "Trade 2", "pnl": -5.0, "exit_reason": "STOP_LOSS"},
            {"condition_id": "0x3", "question": "Trade 3", "pnl": 15.0, "exit_reason": "TAKE_PROFIT"},
        ],
        "metrics": {
            "total_trades": 3,
            "winning_trades": 2,
            "losing_trades": 1,
            "total_pnl": 20.0,
            "max_drawdown": 0.01,
            "peak_balance": 1050.0
        },
        "strategy_metrics": {
            "MARKET_MAKER": {"trades": 2, "wins": 1, "pnl": 15.0},
            "NEAR_ZERO": {"trades": 1, "wins": 1, "pnl": 5.0},
        },
        "last_updated": datetime.now(timezone.utc).isoformat()
    }


@pytest.fixture
def data_dir(tmp_path):
    """Create a temporary data directory."""
    ab_test_dir = tmp_path / "ab_test"
    ab_test_dir.mkdir(parents=True)
    return ab_test_dir


# ============================================================
# LOAD PORTFOLIO TESTS
# ============================================================

class TestLoadPortfolio:
    """Tests for load_portfolio function."""

    def test_load_existing_portfolio(self, data_dir, mock_portfolio_data, monkeypatch):
        """Test loading an existing portfolio file."""
        # Create portfolio file
        portfolio_file = data_dir / "portfolio_market_maker.json"
        with open(portfolio_file, "w") as f:
            json.dump(mock_portfolio_data, f)

        # Monkeypatch DATA_DIR
        import sovereign_hive.ab_test.compare_strategies as cs
        monkeypatch.setattr(cs, 'DATA_DIR', data_dir)

        result = load_portfolio("MARKET_MAKER")

        assert result is not None
        assert result["balance"] == 1050.0
        assert result["initial_balance"] == 1000.0

    def test_load_nonexistent_portfolio(self, data_dir, monkeypatch):
        """Test loading a portfolio that doesn't exist."""
        import sovereign_hive.ab_test.compare_strategies as cs
        monkeypatch.setattr(cs, 'DATA_DIR', data_dir)

        result = load_portfolio("NONEXISTENT")

        assert result is None

    def test_load_corrupted_portfolio(self, data_dir, monkeypatch):
        """Test loading a corrupted portfolio file."""
        # Create corrupted file
        portfolio_file = data_dir / "portfolio_binance_arb.json"
        with open(portfolio_file, "w") as f:
            f.write("not valid json {{{")

        import sovereign_hive.ab_test.compare_strategies as cs
        monkeypatch.setattr(cs, 'DATA_DIR', data_dir)

        result = load_portfolio("BINANCE_ARB")

        assert result is None


# ============================================================
# CALCULATE METRICS TESTS
# ============================================================

class TestCalculateMetrics:
    """Tests for calculate_metrics function."""

    def test_calculate_metrics_complete(self, mock_portfolio_data):
        """Test calculating metrics from complete portfolio data."""
        metrics = calculate_metrics(mock_portfolio_data)

        assert metrics is not None
        assert metrics["balance"] == 1050.0
        assert metrics["initial_balance"] == 1000.0
        assert metrics["total_value"] == 1100.0  # 1050 + 50 position
        assert metrics["total_pnl"] == 100.0  # 1100 - 1000
        assert metrics["roi_pct"] == 10.0
        assert metrics["open_positions"] == 1
        assert metrics["total_trades"] == 3
        assert metrics["wins"] == 2
        assert metrics["win_rate"] == pytest.approx(66.67, rel=0.1)
        assert metrics["avg_profit"] == pytest.approx(6.67, rel=0.1)

    def test_calculate_metrics_none_portfolio(self):
        """Test calculating metrics for None portfolio."""
        metrics = calculate_metrics(None)
        assert metrics is None

    def test_calculate_metrics_empty_portfolio(self):
        """Test calculating metrics for empty portfolio."""
        empty_portfolio = {
            "balance": 1000.0,
            "initial_balance": 1000.0,
            "positions": {},
            "trade_history": [],
            "strategy_metrics": {}
        }

        metrics = calculate_metrics(empty_portfolio)

        assert metrics is not None
        assert metrics["total_pnl"] == 0
        assert metrics["roi_pct"] == 0
        assert metrics["total_trades"] == 0
        assert metrics["win_rate"] == 0
        assert metrics["avg_profit"] == 0

    def test_calculate_metrics_all_losses(self):
        """Test calculating metrics when all trades are losses."""
        losing_portfolio = {
            "balance": 900.0,
            "initial_balance": 1000.0,
            "positions": {},
            "trade_history": [
                {"pnl": -30.0},
                {"pnl": -40.0},
                {"pnl": -30.0},
            ],
            "strategy_metrics": {}
        }

        metrics = calculate_metrics(losing_portfolio)

        assert metrics["total_pnl"] == -100.0
        assert metrics["roi_pct"] == -10.0
        assert metrics["win_rate"] == 0
        assert metrics["wins"] == 0

    def test_calculate_metrics_with_positions(self, mock_portfolio_data):
        """Test that open positions are included in total value."""
        metrics = calculate_metrics(mock_portfolio_data)

        # Position has cost_basis of 50
        assert metrics["total_value"] == 1100.0  # 1050 balance + 50 position

    def test_calculate_metrics_invalid_last_updated(self):
        """Test handling of invalid last_updated timestamp."""
        portfolio = {
            "balance": 1000.0,
            "initial_balance": 1000.0,
            "positions": {},
            "trade_history": [],
            "strategy_metrics": {},
            "last_updated": "invalid-date"
        }

        metrics = calculate_metrics(portfolio)

        assert metrics["hours_running"] == 0


# ============================================================
# STRATEGIES LIST TESTS
# ============================================================

class TestStrategiesList:
    """Tests for the strategies list."""

    def test_all_strategies_present(self):
        """Test that all expected strategies are in the list."""
        expected = [
            "MARKET_MAKER",
            "BINANCE_ARB",
            "NEAR_ZERO",
            "NEAR_CERTAIN",
            "DUAL_SIDE_ARB",
            "MID_RANGE",
            "DIP_BUY",
            "VOLUME_SURGE",
        ]

        assert set(STRATEGIES) == set(expected)
        assert len(STRATEGIES) == 8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
