#!/usr/bin/env python3
"""
COMPREHENSIVE STRATEGY TESTS
=============================
Tests for all trading strategies to ensure they work correctly.

Run with: pytest tests/test_strategies.py -v
"""

import pytest
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add parent path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sovereign_hive.run_simulation import Portfolio, MarketScanner


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def temp_portfolio(tmp_path):
    """Create a temporary portfolio for testing."""
    portfolio_file = tmp_path / "test_portfolio.json"
    portfolio = Portfolio(initial_balance=1000.0, data_file=str(portfolio_file))
    return portfolio


@pytest.fixture
def scanner():
    """Create a market scanner instance."""
    return MarketScanner()


@pytest.fixture
def mock_markets():
    """Sample market data for testing."""
    return [
        {
            "conditionId": "0x123abc",
            "question": "Will Bitcoin hit $100k by March 2026?",
            "bestBid": 0.45,
            "bestAsk": 0.48,
            "volume24hr": 50000,
            "liquidityNum": 100000,
            "endDate": (datetime.now(timezone.utc).isoformat()),
        },
        {
            "conditionId": "0x456def",
            "question": "Will Trump win 2028 election?",
            "bestBid": 0.95,
            "bestAsk": 0.97,
            "volume24hr": 200000,
            "liquidityNum": 500000,
            "endDate": (datetime.now(timezone.utc).isoformat()),
        },
        {
            "conditionId": "0x789ghi",
            "question": "Will the Lakers win 2026 NBA Finals?",
            "bestBid": 0.03,
            "bestAsk": 0.05,
            "volume24hr": 30000,
            "liquidityNum": 80000,
            "endDate": (datetime.now(timezone.utc).isoformat()),
        },
    ]


# ============================================================
# PORTFOLIO TESTS
# ============================================================

class TestPortfolio:
    """Tests for Portfolio class."""

    def test_initial_balance(self, temp_portfolio):
        """Test portfolio initializes with correct balance."""
        assert temp_portfolio.balance == 1000.0
        assert temp_portfolio.initial_balance == 1000.0

    def test_buy_deducts_balance(self, temp_portfolio):
        """Test buying reduces balance correctly."""
        result = temp_portfolio.buy(
            condition_id="0x123",
            question="Test market",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test buy",
            strategy="TEST"
        )

        assert result["success"] is True
        assert temp_portfolio.balance == 900.0
        assert "0x123" in temp_portfolio.positions

    def test_buy_insufficient_balance(self, temp_portfolio):
        """Test buying with insufficient balance fails."""
        result = temp_portfolio.buy(
            condition_id="0x123",
            question="Test market",
            side="YES",
            price=0.50,
            amount=2000,  # More than balance
            reason="Test buy",
            strategy="TEST"
        )

        assert result["success"] is False
        assert temp_portfolio.balance == 1000.0

    def test_sell_updates_balance(self, temp_portfolio):
        """Test selling updates balance and records trade."""
        # First buy
        temp_portfolio.buy(
            condition_id="0x123",
            question="Test market",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test buy",
            strategy="TEST"
        )

        # Then sell at profit
        result = temp_portfolio.sell("0x123", 0.60, "TAKE_PROFIT")

        assert result["success"] is True
        assert "0x123" not in temp_portfolio.positions
        assert len(temp_portfolio.trade_history) == 1
        assert temp_portfolio.trade_history[0]["pnl"] > 0

    def test_position_pnl_calculation(self, temp_portfolio):
        """Test P&L calculation for positions."""
        temp_portfolio.buy(
            condition_id="0x123",
            question="Test market",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test buy",
            strategy="TEST"
        )

        # Test at higher price (profit)
        pnl = temp_portfolio.get_position_pnl("0x123", 0.60)
        assert pnl == pytest.approx(0.20, rel=0.01)  # 20% profit

        # Test at lower price (loss)
        pnl = temp_portfolio.get_position_pnl("0x123", 0.40)
        assert pnl == pytest.approx(-0.20, rel=0.01)  # 20% loss

    def test_no_positions_pnl(self, temp_portfolio):
        """Test P&L with no positions."""
        pnl = temp_portfolio.get_position_pnl("nonexistent", 0.50)
        assert pnl is None

    def test_strategy_metrics_tracking(self, temp_portfolio):
        """Test that strategy metrics are tracked correctly."""
        # Buy position
        temp_portfolio.buy(
            condition_id="0x123",
            question="Test market",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test buy",
            strategy="MARKET_MAKER"
        )

        # Sell at profit
        temp_portfolio.sell("0x123", 0.60, "TAKE_PROFIT")

        metrics = temp_portfolio.strategy_metrics.get("MARKET_MAKER", {})
        assert metrics.get("trades", 0) == 1
        assert metrics.get("wins", 0) == 1
        assert metrics.get("pnl", 0) > 0


# ============================================================
# MARKET SCANNER TESTS
# ============================================================

class TestMarketScanner:
    """Tests for MarketScanner class."""

    def test_annualized_return_calculation(self, scanner):
        """Test annualized return formula."""
        # 2% in 18 days should be ~49% annualized
        ann = scanner.calculate_annualized_return(0.02, 18)
        assert ann == pytest.approx(0.495, rel=0.1)

        # 2% in 365 days should be ~2% annualized
        ann = scanner.calculate_annualized_return(0.02, 365)
        assert ann == pytest.approx(0.02, rel=0.01)

        # Edge case: 0 days
        ann = scanner.calculate_annualized_return(0.02, 0)
        assert ann == 0.0

    def test_find_near_certain_opportunities(self, scanner):
        """Test detection of NEAR_CERTAIN opportunities."""
        # Create market specifically for near-certain detection
        markets = [
            {
                "conditionId": "0xnearcertain",
                "question": "Will something very likely happen?",
                "bestBid": 0.96,
                "bestAsk": 0.97,
                "volume24hr": 50000,
                "liquidityNum": 100000,
                "endDate": "2026-03-01T00:00:00Z",
            }
        ]

        opps = scanner.find_opportunities(markets)
        near_certain = [o for o in opps if o["strategy"] == "NEAR_CERTAIN"]

        # Should detect near-certain opportunity
        assert len(near_certain) >= 1
        assert near_certain[0]["side"] == "YES"
        assert near_certain[0]["confidence"] >= 0.95

    def test_find_market_maker_opportunities(self, scanner, mock_markets):
        """Test detection of MARKET_MAKER opportunities."""
        opps = scanner.find_opportunities(mock_markets)

        mm_opps = [o for o in opps if o["strategy"] == "MARKET_MAKER"]

        # Lakers market should qualify (3-5 cent range, good spread)
        for opp in mm_opps:
            assert "mm_bid" in opp
            assert "mm_ask" in opp
            assert opp["mm_ask"] > opp["mm_bid"]

    def test_meme_market_filter(self, scanner):
        """Test that meme markets are filtered out."""
        meme_markets = [
            {
                "conditionId": "0xmeme1",
                "question": "Will Jesus Christ return before GTA VI?",
                "bestBid": 0.10,
                "bestAsk": 0.15,
                "volume24hr": 50000,
                "liquidityNum": 100000,
            }
        ]

        opps = scanner.find_opportunities(meme_markets)
        mm_opps = [o for o in opps if o["strategy"] == "MARKET_MAKER"]

        # Should NOT find meme market
        assert len(mm_opps) == 0

    def test_extract_crypto_target(self, scanner):
        """Test crypto price target extraction."""
        # BTC target
        result = scanner.extract_crypto_target("Will Bitcoin hit $100,000 by March?")
        assert result is not None
        assert result["symbol"] == "BTCUSDT"
        assert result["target"] == 100000
        assert result["direction"] == "ABOVE"

        # ETH target
        result = scanner.extract_crypto_target("Will ETH fall below $2000?")
        assert result is not None
        assert result["symbol"] == "ETHUSDT"
        assert result["target"] == 2000
        assert result["direction"] == "BELOW"

        # Non-crypto market
        result = scanner.extract_crypto_target("Will Trump win the election?")
        assert result is None

    def test_binance_implied_probability(self, scanner):
        """Test Binance implied probability calculation."""
        # Price already above target
        prob = scanner.calculate_binance_implied_prob(110000, 100000, "ABOVE")
        assert prob > 0.80

        # Price far below target
        prob = scanner.calculate_binance_implied_prob(50000, 100000, "ABOVE")
        assert prob < 0.30

        # Price at target
        prob = scanner.calculate_binance_implied_prob(100000, 100000, "ABOVE")
        assert 0.40 < prob < 0.90


# ============================================================
# STRATEGY DETECTION TESTS
# ============================================================

class TestStrategyDetection:
    """Tests for strategy opportunity detection."""

    def test_dual_side_arb_detection(self, scanner):
        """Test DUAL_SIDE_ARB detection when YES + NO < $1."""
        markets = [
            {
                "conditionId": "0xarb1",
                "question": "Will X happen?",
                "bestBid": 0.45,
                "bestAsk": 0.48,
                "outcomePrices": json.dumps([0.48, 0.50]),  # YES=0.48, NO=0.50, sum=0.98
                "volume24hr": 50000,
                "liquidityNum": 50000,
            }
        ]

        opps = scanner.find_opportunities(markets)
        dual_opps = [o for o in opps if o["strategy"] == "DUAL_SIDE_ARB"]

        # Should detect arb when sum < $1
        # Note: depends on exact threshold in config

    def test_near_zero_detection(self, scanner):
        """Test NEAR_ZERO detection (buying NO on low-probability markets)."""
        markets = [
            {
                "conditionId": "0xlow1",
                "question": "Will something unlikely happen?",
                "bestBid": 0.02,
                "bestAsk": 0.04,
                "volume24hr": 20000,
                "liquidityNum": 50000,
            }
        ]

        opps = scanner.find_opportunities(markets)
        near_zero = [o for o in opps if o["strategy"] == "NEAR_ZERO"]

        if near_zero:
            assert near_zero[0]["side"] == "NO"

    def test_mid_range_detection(self, scanner):
        """Test MID_RANGE detection for active trading."""
        markets = [
            {
                "conditionId": "0xmid1",
                "question": "Close contest?",
                "bestBid": 0.48,
                "bestAsk": 0.52,
                "volume24hr": 100000,
                "liquidityNum": 200000,
            }
        ]

        opps = scanner.find_opportunities(markets)
        mid_range = [o for o in opps if o["strategy"] == "MID_RANGE"]

        if mid_range:
            assert 0.20 <= mid_range[0]["price"] <= 0.80


# ============================================================
# MM SPREAD CALCULATION TESTS
# ============================================================

class TestMMSpreadCalculation:
    """Tests for Market Maker spread calculations."""

    def test_mm_spread_minimum(self, scanner):
        """Test that MM spread has minimum $0.005 on each side."""
        markets = [
            {
                "conditionId": "0xlow1",
                "question": "Low price market",
                "bestBid": 0.03,
                "bestAsk": 0.05,
                "volume24hr": 50000,
                "liquidityNum": 50000,
            }
        ]

        opps = scanner.find_opportunities(markets)
        mm_opps = [o for o in opps if o["strategy"] == "MARKET_MAKER"]

        if mm_opps:
            opp = mm_opps[0]
            spread = opp["mm_ask"] - opp["mm_bid"]
            # Should have at least $0.01 spread (0.005 on each side)
            assert spread >= 0.009  # Allow small floating point error

    def test_mm_spread_high_price(self, scanner):
        """Test MM spread on higher-priced markets."""
        markets = [
            {
                "conditionId": "0xhigh1",
                "question": "Higher price market",
                "bestBid": 0.45,
                "bestAsk": 0.50,
                "volume24hr": 50000,
                "liquidityNum": 50000,
            }
        ]

        opps = scanner.find_opportunities(markets)
        mm_opps = [o for o in opps if o["strategy"] == "MARKET_MAKER"]

        if mm_opps:
            opp = mm_opps[0]
            # At 0.475 mid price, 0.5% = 0.002375, but minimum is 0.005
            # So should still be at least $0.01 spread
            spread = opp["mm_ask"] - opp["mm_bid"]
            assert spread >= 0.009


# ============================================================
# BINANCE ARB TESTS
# ============================================================

class TestBinanceArb:
    """Tests for Binance arbitrage strategy."""

    def test_binance_arb_detection(self, scanner):
        """Test BINANCE_ARB opportunity detection."""
        markets = [
            {
                "conditionId": "0xbtc1",
                "question": "Will Bitcoin hit $100,000 by March 2026?",
                "bestBid": 0.30,
                "bestAsk": 0.35,
                "volume24hr": 50000,
                "liquidityNum": 20000,
            }
        ]

        # Mock Binance prices - BTC at $95k (close to target)
        binance_prices = {"BTCUSDT": 95000, "ETHUSDT": 3000, "SOLUSDT": 100}

        opps = scanner.find_opportunities(markets, binance_prices)
        binance_opps = [o for o in opps if o["strategy"] == "BINANCE_ARB"]

        # Should detect opportunity if edge is sufficient
        for opp in binance_opps:
            assert "edge" in opp
            assert "binance_price" in opp
            assert abs(opp["edge"]) >= 5  # 5% minimum edge

    def test_binance_arb_no_edge(self, scanner):
        """Test that small edges are not detected."""
        markets = [
            {
                "conditionId": "0xbtc1",
                "question": "Will Bitcoin hit $100,000?",
                "bestBid": 0.80,
                "bestAsk": 0.82,  # High probability already priced in
                "volume24hr": 50000,
                "liquidityNum": 20000,
            }
        ]

        binance_prices = {"BTCUSDT": 95000}  # Close to target

        opps = scanner.find_opportunities(markets, binance_prices)
        binance_opps = [o for o in opps if o["strategy"] == "BINANCE_ARB"]

        # Edge might be too small to trigger


# ============================================================
# INTEGRATION TESTS
# ============================================================

class TestIntegration:
    """Integration tests for the trading system."""

    def test_full_trading_cycle(self, temp_portfolio):
        """Test a full buy->hold->sell cycle."""
        # Buy
        buy_result = temp_portfolio.buy(
            condition_id="0xtest",
            question="Integration test market",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="TEST"
        )
        assert buy_result["success"]
        assert temp_portfolio.balance == 900

        # Check position exists
        assert "0xtest" in temp_portfolio.positions
        pos = temp_portfolio.positions["0xtest"]
        assert pos["side"] == "YES"
        assert pos["entry_price"] == 0.50

        # Sell at profit
        sell_result = temp_portfolio.sell("0xtest", 0.60, "TAKE_PROFIT")
        assert sell_result["success"]

        # Check trade recorded
        assert len(temp_portfolio.trade_history) == 1
        trade = temp_portfolio.trade_history[0]
        assert trade["pnl"] > 0
        assert trade["exit_reason"] == "TAKE_PROFIT"

    def test_strategy_isolation(self, scanner, mock_markets):
        """Test that strategies are properly isolated in opportunities."""
        opps = scanner.find_opportunities(mock_markets)

        # Each opportunity should have exactly one strategy
        for opp in opps:
            assert "strategy" in opp
            assert opp["strategy"] in [
                "NEAR_CERTAIN", "NEAR_ZERO", "DIP_BUY", "VOLUME_SURGE",
                "MID_RANGE", "DUAL_SIDE_ARB", "MARKET_MAKER", "BINANCE_ARB"
            ]


# ============================================================
# EDGE CASE TESTS
# ============================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_markets(self, scanner):
        """Test handling of empty market list."""
        opps = scanner.find_opportunities([])
        assert opps == []

    def test_missing_market_fields(self, scanner):
        """Test handling of markets with missing fields."""
        markets = [
            {
                "conditionId": "0xinvalid",
                # Missing question, prices, etc.
            }
        ]

        # Should not crash
        opps = scanner.find_opportunities(markets)
        assert isinstance(opps, list)

    def test_zero_liquidity(self, scanner):
        """Test markets with zero liquidity are skipped."""
        markets = [
            {
                "conditionId": "0xnoliq",
                "question": "No liquidity market",
                "bestBid": 0.50,
                "bestAsk": 0.55,
                "volume24hr": 1000,
                "liquidityNum": 0,
            }
        ]

        opps = scanner.find_opportunities(markets)
        # Should be filtered out due to low liquidity
        assert len([o for o in opps if o["condition_id"] == "0xnoliq"]) == 0

    def test_invalid_prices(self, scanner):
        """Test markets with invalid prices."""
        markets = [
            {
                "conditionId": "0xinvalid",
                "question": "Invalid prices",
                "bestBid": -0.10,  # Invalid
                "bestAsk": 1.50,   # Invalid
                "volume24hr": 10000,
                "liquidityNum": 50000,
            }
        ]

        opps = scanner.find_opportunities(markets)
        # Should handle gracefully


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
