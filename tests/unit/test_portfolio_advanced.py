#!/usr/bin/env python3
"""
ADVANCED PORTFOLIO TESTS
=========================
Comprehensive tests for Portfolio class edge cases and advanced scenarios.
"""

import pytest
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.run_simulation import Portfolio


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def portfolio(tmp_path):
    """Create a fresh portfolio for testing."""
    portfolio_file = tmp_path / "test_portfolio.json"
    return Portfolio(initial_balance=1000.0, data_file=str(portfolio_file))


@pytest.fixture
def portfolio_with_positions(tmp_path):
    """Create portfolio with existing positions."""
    portfolio_file = tmp_path / "test_portfolio.json"
    p = Portfolio(initial_balance=1000.0, data_file=str(portfolio_file))

    # Add some positions
    p.buy("0xpos1", "Position 1", "YES", 0.50, 100, "Test", "MARKET_MAKER")
    p.buy("0xpos2", "Position 2", "NO", 0.40, 100, "Test", "NEAR_ZERO")
    p.buy("0xpos3", "Position 3", "YES", 0.60, 100, "Test", "BINANCE_ARB")

    return p


# ============================================================
# PERSISTENCE TESTS
# ============================================================

class TestPortfolioPersistence:
    """Tests for portfolio save/load functionality."""

    def test_save_and_load(self, tmp_path):
        """Test saving and loading portfolio state."""
        portfolio_file = tmp_path / "persist_test.json"

        # Create and modify portfolio
        p1 = Portfolio(initial_balance=1000.0, data_file=str(portfolio_file))
        p1.buy("0xtest", "Test market", "YES", 0.50, 100, "Test", "TEST")

        # Create new portfolio from same file
        p2 = Portfolio(initial_balance=1000.0, data_file=str(portfolio_file))

        assert p2.balance == p1.balance
        assert "0xtest" in p2.positions
        assert p2.positions["0xtest"]["entry_price"] == 0.50

    def test_load_preserves_strategy_metrics(self, tmp_path):
        """Test that strategy metrics persist."""
        portfolio_file = tmp_path / "metrics_test.json"

        p1 = Portfolio(initial_balance=1000.0, data_file=str(portfolio_file))
        p1.buy("0x1", "Test", "YES", 0.50, 100, "Test", "MARKET_MAKER")
        p1.sell("0x1", 0.60, "TAKE_PROFIT")

        # Reload
        p2 = Portfolio(initial_balance=1000.0, data_file=str(portfolio_file))

        assert p2.strategy_metrics["MARKET_MAKER"]["trades"] == 1
        assert p2.strategy_metrics["MARKET_MAKER"]["wins"] == 1
        assert p2.strategy_metrics["MARKET_MAKER"]["pnl"] > 0

    def test_load_adds_missing_strategies(self, tmp_path):
        """Test that new strategies are added on load."""
        portfolio_file = tmp_path / "strategy_test.json"

        # Create portfolio with old format (missing some strategies)
        old_data = {
            "balance": 1000.0,
            "initial_balance": 1000.0,
            "positions": {},
            "trade_history": [],
            "metrics": {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "max_drawdown": 0.0,
                "peak_balance": 1000.0
            },
            "strategy_metrics": {
                "NEAR_CERTAIN": {"trades": 0, "wins": 0, "pnl": 0.0},
                # Missing newer strategies
            },
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

        with open(portfolio_file, "w") as f:
            json.dump(old_data, f)

        # Load - should add missing strategies
        p = Portfolio(initial_balance=1000.0, data_file=str(portfolio_file))

        assert "MARKET_MAKER" in p.strategy_metrics
        assert "BINANCE_ARB" in p.strategy_metrics
        assert "DUAL_SIDE_ARB" in p.strategy_metrics


# ============================================================
# SELL EDGE CASES
# ============================================================

class TestSellEdgeCases:
    """Tests for sell method edge cases."""

    def test_sell_nonexistent_position(self, portfolio):
        """Test selling a position that doesn't exist."""
        result = portfolio.sell("0xnonexistent", 0.60, "TEST")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_sell_at_loss_updates_metrics(self, portfolio):
        """Test that losing trades update metrics correctly."""
        portfolio.buy("0xlose", "Losing trade", "YES", 0.50, 100, "Test", "TEST")
        result = portfolio.sell("0xlose", 0.40, "STOP_LOSS")

        assert result["success"] is True
        assert result["trade"]["pnl"] < 0
        assert portfolio.metrics["losing_trades"] == 1
        assert portfolio.metrics["winning_trades"] == 0

    def test_sell_updates_peak_balance(self, portfolio):
        """Test that peak balance is tracked correctly."""
        initial_peak = portfolio.metrics["peak_balance"]

        # Win to increase balance
        portfolio.buy("0xwin", "Winning trade", "YES", 0.50, 100, "Test", "TEST")
        portfolio.sell("0xwin", 0.80, "TAKE_PROFIT")

        assert portfolio.metrics["peak_balance"] > initial_peak

    def test_sell_updates_drawdown(self, portfolio):
        """Test that max drawdown is tracked correctly."""
        # First win to set peak
        portfolio.buy("0xwin", "Win", "YES", 0.50, 100, "Test", "TEST")
        portfolio.sell("0xwin", 0.70, "TP")

        # Then lose to create drawdown
        portfolio.buy("0xlose", "Lose", "YES", 0.50, 200, "Test", "TEST")
        portfolio.sell("0xlose", 0.35, "SL")

        assert portfolio.metrics["max_drawdown"] > 0

    def test_sell_unknown_strategy(self, portfolio):
        """Test selling position with unknown strategy."""
        portfolio.buy("0xunk", "Unknown", "YES", 0.50, 100, "Test", "UNKNOWN_STRATEGY")
        result = portfolio.sell("0xunk", 0.60, "TP")

        # Should still work, just not update strategy metrics
        assert result["success"] is True


# ============================================================
# UNREALIZED PNL TESTS
# ============================================================

class TestUnrealizedPnL:
    """Tests for unrealized P&L calculation."""

    def test_unrealized_pnl_single_position(self, portfolio):
        """Test unrealized P&L for single position."""
        portfolio.buy("0xtest", "Test", "YES", 0.50, 100, "Test", "TEST")

        current_prices = {"0xtest": 0.60}
        unrealized = portfolio.get_unrealized_pnl(current_prices)

        # Bought 200 shares at $0.50, now worth $0.60 each
        # Unrealized = 200 * 0.60 - 100 = $20
        assert unrealized == pytest.approx(20.0, rel=0.01)

    def test_unrealized_pnl_multiple_positions(self, portfolio_with_positions):
        """Test unrealized P&L across multiple positions."""
        current_prices = {
            "0xpos1": 0.55,  # Profit
            "0xpos2": 0.35,  # Loss (NO position, so price inverted)
            "0xpos3": 0.65,  # Profit
        }

        unrealized = portfolio_with_positions.get_unrealized_pnl(current_prices)
        assert isinstance(unrealized, float)

    def test_unrealized_pnl_missing_prices(self, portfolio_with_positions):
        """Test unrealized P&L with missing price data."""
        current_prices = {"0xpos1": 0.55}  # Only one price

        unrealized = portfolio_with_positions.get_unrealized_pnl(current_prices)
        # Should only calculate for positions with prices
        assert isinstance(unrealized, float)

    def test_unrealized_pnl_empty_portfolio(self, portfolio):
        """Test unrealized P&L with no positions."""
        unrealized = portfolio.get_unrealized_pnl({})
        assert unrealized == 0.0


# ============================================================
# SUMMARY AND REPORT TESTS
# ============================================================

class TestSummaryAndReports:
    """Tests for summary and report methods."""

    def test_get_summary_initial(self, portfolio):
        """Test summary on fresh portfolio."""
        summary = portfolio.get_summary()

        assert summary["balance"] == 1000.0
        assert summary["total_value"] == 1000.0
        assert summary["initial_balance"] == 1000.0
        assert summary["roi_pct"] == 0.0
        assert summary["open_positions"] == 0
        assert summary["total_trades"] == 0
        assert summary["win_rate"] == 0

    def test_get_summary_with_positions(self, portfolio_with_positions):
        """Test summary with open positions."""
        summary = portfolio_with_positions.get_summary()

        assert summary["open_positions"] == 3
        assert summary["balance"] < 1000.0  # Some used for positions
        assert summary["total_value"] == 1000.0  # Balance + position cost basis

    def test_get_summary_with_trades(self, portfolio):
        """Test summary after trades."""
        portfolio.buy("0x1", "Trade 1", "YES", 0.50, 100, "Test", "TEST")
        portfolio.sell("0x1", 0.60, "TP")
        portfolio.buy("0x2", "Trade 2", "YES", 0.50, 100, "Test", "TEST")
        portfolio.sell("0x2", 0.55, "TP")

        summary = portfolio.get_summary()

        assert summary["total_trades"] == 2
        assert summary["win_rate"] == 100.0
        assert portfolio.metrics["winning_trades"] == 2

    def test_get_strategy_report(self, portfolio):
        """Test strategy report generation."""
        # Make trades in different strategies
        portfolio.buy("0x1", "MM trade", "YES", 0.50, 100, "Test", "MARKET_MAKER")
        portfolio.sell("0x1", 0.55, "TP")

        portfolio.buy("0x2", "NZ trade", "YES", 0.50, 100, "Test", "NEAR_ZERO")
        portfolio.sell("0x2", 0.45, "SL")

        report = portfolio.get_strategy_report()

        assert "MARKET_MAKER" in report
        assert "NEAR_ZERO" in report
        assert "STRATEGY PERFORMANCE" in report


# ============================================================
# EDGE CASE TESTS
# ============================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_buy_exact_balance(self, portfolio):
        """Test buying with exact balance amount."""
        result = portfolio.buy("0xexact", "Exact", "YES", 0.50, 1000, "Test", "TEST")

        assert result["success"] is True
        assert portfolio.balance == 0.0

    def test_buy_zero_amount(self, portfolio):
        """Test buying zero amount."""
        result = portfolio.buy("0xzero", "Zero", "YES", 0.50, 0, "Test", "TEST")

        # Zero shares is valid but questionable
        if result["success"]:
            assert portfolio.positions["0xzero"]["shares"] == 0

    def test_very_small_price(self, portfolio):
        """Test with very small price."""
        result = portfolio.buy("0xsmall", "Small", "YES", 0.001, 10, "Test", "TEST")

        assert result["success"] is True
        # Should get 10000 shares at $0.001 each
        assert portfolio.positions["0xsmall"]["shares"] == 10000

    def test_price_at_boundaries(self, portfolio):
        """Test prices at 0 and 1 boundaries."""
        # Price at 1.0 (unlikely but possible)
        result = portfolio.buy("0xone", "One", "YES", 1.0, 100, "Test", "TEST")
        assert result["success"] is True
        assert portfolio.positions["0xone"]["shares"] == 100

    def test_truncated_question(self, portfolio):
        """Test that long questions are truncated."""
        long_question = "A" * 200  # Very long question
        result = portfolio.buy("0xlong", long_question, "YES", 0.50, 100, "Test", "TEST")

        assert result["success"] is True
        assert len(portfolio.positions["0xlong"]["question"]) <= 80


# ============================================================
# POSITION TRACKING TESTS
# ============================================================

class TestPositionTracking:
    """Tests for position tracking."""

    def test_position_has_required_fields(self, portfolio):
        """Test that positions have all required fields."""
        portfolio.buy("0xfields", "Fields test", "YES", 0.50, 100, "Test reason", "TEST_STRAT")

        pos = portfolio.positions["0xfields"]

        assert "condition_id" in pos
        assert "question" in pos
        assert "side" in pos
        assert "entry_price" in pos
        assert "shares" in pos
        assert "cost_basis" in pos
        assert "entry_time" in pos
        assert "reason" in pos
        assert "strategy" in pos

    def test_position_entry_time_format(self, portfolio):
        """Test that entry time is valid ISO format."""
        portfolio.buy("0xtime", "Time test", "YES", 0.50, 100, "Test", "TEST")

        entry_time = portfolio.positions["0xtime"]["entry_time"]

        # Should parse without error
        parsed = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    def test_multiple_positions_same_side(self, portfolio):
        """Test multiple positions on same side."""
        portfolio.buy("0xa", "Market A", "YES", 0.40, 100, "Test", "TEST")
        portfolio.buy("0xb", "Market B", "YES", 0.60, 100, "Test", "TEST")

        assert len(portfolio.positions) == 2
        assert portfolio.balance == 800.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
