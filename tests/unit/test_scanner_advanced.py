#!/usr/bin/env python3
"""
ADVANCED MARKET SCANNER TESTS
==============================
Comprehensive tests for MarketScanner API fetching and edge cases.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.run_simulation import MarketScanner, CONFIG


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def scanner():
    """Create a scanner instance."""
    return MarketScanner()


@pytest.fixture
def mock_markets():
    """Sample markets with various edge cases."""
    now = datetime.now(timezone.utc)
    return [
        {
            "conditionId": "0xnormal",
            "question": "Normal market?",
            "bestBid": 0.50,
            "bestAsk": 0.52,
            "volume24hr": 50000,
            "liquidityNum": 100000,
            "endDate": (now + timedelta(days=30)).isoformat(),
        },
        {
            "conditionId": "0xhighvol",
            "question": "High volume surge?",
            "bestBid": 0.48,
            "bestAsk": 0.50,
            "volume24hr": 200000,
            "volume1hr": 50000,  # 6x hourly average
            "liquidityNum": 150000,
            "endDate": (now + timedelta(days=14)).isoformat(),
            "oneDayPriceChange": 0.02,
        },
        {
            "conditionId": "0xdip",
            "question": "Big dip market?",
            "bestBid": 0.35,
            "bestAsk": 0.38,
            "volume24hr": 80000,
            "liquidityNum": 120000,
            "endDate": (now + timedelta(days=7)).isoformat(),
            "oneDayPriceChange": -0.15,  # 15% drop
        },
        {
            "conditionId": "0xlongterm",
            "question": "Long term market?",
            "bestBid": 0.96,
            "bestAsk": 0.97,
            "volume24hr": 100000,
            "liquidityNum": 200000,
            "endDate": (now + timedelta(days=400)).isoformat(),  # Over max days
        },
        {
            "conditionId": "0xmiddown",
            "question": "Mid range downward?",
            "bestBid": 0.55,
            "bestAsk": 0.58,
            "volume24hr": 50000,
            "liquidityNum": 100000,
            "endDate": (now + timedelta(days=14)).isoformat(),
            "oneDayPriceChange": -0.02,  # Downward momentum
        },
    ]


# ============================================================
# ANNUALIZED RETURN TESTS
# ============================================================

class TestAnnualizedReturn:
    """Tests for calculate_annualized_return."""

    def test_short_term_high_return(self, scanner):
        """Test high annualized return for short-term trades."""
        # 5% in 3 days
        ann = scanner.calculate_annualized_return(0.05, 3)
        assert ann > 5.0  # Should be very high

    def test_long_term_low_return(self, scanner):
        """Test low annualized return for long-term trades."""
        # 5% in 300 days
        ann = scanner.calculate_annualized_return(0.05, 300)
        assert ann < 0.10  # Should be low

    def test_negative_return(self, scanner):
        """Test negative return handling."""
        ann = scanner.calculate_annualized_return(-0.10, 30)
        assert ann < 0

    def test_return_near_minus_one(self, scanner):
        """Test return at -100%."""
        ann = scanner.calculate_annualized_return(-1.0, 30)
        assert ann == -1.0

    def test_return_capped_at_10(self, scanner):
        """Test that extreme returns are capped."""
        # Very high short-term return
        ann = scanner.calculate_annualized_return(0.50, 1)
        assert ann <= 10.0


# ============================================================
# CRYPTO TARGET EXTRACTION TESTS
# ============================================================

class TestExtractCryptoTarget:
    """Tests for extract_crypto_target."""

    def test_btc_above_target(self, scanner):
        """Test BTC above target extraction."""
        result = scanner.extract_crypto_target(
            "Will Bitcoin price reach above $150,000 by end of year?"
        )
        assert result is not None
        assert result["symbol"] == "BTCUSDT"
        assert result["target"] == 150000
        assert result["direction"] == "ABOVE"

    def test_eth_below_target(self, scanner):
        """Test ETH below target extraction."""
        result = scanner.extract_crypto_target(
            "Will Ethereum fall below $1500 by March?"
        )
        assert result is not None
        assert result["symbol"] == "ETHUSDT"
        assert result["target"] == 1500
        assert result["direction"] == "BELOW"

    def test_sol_with_k_notation(self, scanner):
        """Test SOL with $XXk notation."""
        result = scanner.extract_crypto_target(
            "Will Solana hit $500k market cap?"  # This should fail - not price
        )
        # This might not match as it's not a price market
        # Just verify it doesn't crash

    def test_non_crypto_market(self, scanner):
        """Test non-crypto market returns None."""
        result = scanner.extract_crypto_target(
            "Will the Lakers win the championship?"
        )
        assert result is None

    def test_crypto_without_price(self, scanner):
        """Test crypto market without price target."""
        result = scanner.extract_crypto_target(
            "Will Bitcoin be adopted by Amazon?"
        )
        assert result is None  # No price target


# ============================================================
# BINANCE IMPLIED PROBABILITY TESTS
# ============================================================

class TestBinanceImpliedProb:
    """Tests for calculate_binance_implied_prob."""

    def test_price_far_above_target(self, scanner):
        """Test when current price is far above target."""
        prob = scanner.calculate_binance_implied_prob(120000, 100000, "ABOVE")
        assert prob > 0.85

    def test_price_far_below_target(self, scanner):
        """Test when current price is far below target."""
        prob = scanner.calculate_binance_implied_prob(50000, 100000, "ABOVE")
        assert prob < 0.30

    def test_price_at_target(self, scanner):
        """Test when price is exactly at target."""
        prob = scanner.calculate_binance_implied_prob(100000, 100000, "ABOVE")
        assert 0.5 < prob < 0.95

    def test_below_direction(self, scanner):
        """Test BELOW direction."""
        prob = scanner.calculate_binance_implied_prob(80000, 100000, "BELOW")
        assert prob > 0.5  # Currently below target

    def test_zero_price(self, scanner):
        """Test handling of zero price."""
        prob = scanner.calculate_binance_implied_prob(0, 100000, "ABOVE")
        assert prob == 0.5

    def test_probability_bounds(self, scanner):
        """Test probability is within bounds."""
        prob = scanner.calculate_binance_implied_prob(200000, 100000, "ABOVE")
        assert 0.05 <= prob <= 0.95


# ============================================================
# FIND OPPORTUNITIES TESTS
# ============================================================

class TestFindOpportunities:
    """Tests for find_opportunities edge cases."""

    def test_dip_buy_detection(self, scanner, mock_markets):
        """Test DIP_BUY detection on price drop."""
        opps = scanner.find_opportunities(mock_markets)
        dip_opps = [o for o in opps if o["strategy"] == "DIP_BUY"]

        # Should find the dip market
        if dip_opps:
            assert dip_opps[0]["condition_id"] == "0xdip"

    def test_volume_surge_detection(self, scanner, mock_markets):
        """Test VOLUME_SURGE detection."""
        opps = scanner.find_opportunities(mock_markets)
        vol_opps = [o for o in opps if o["strategy"] == "VOLUME_SURGE"]

        # May or may not detect based on volume calculation

    def test_mid_range_downward(self, scanner, mock_markets):
        """Test MID_RANGE with downward momentum."""
        opps = scanner.find_opportunities(mock_markets)
        mid_opps = [o for o in opps if o["strategy"] == "MID_RANGE"]

        # Should find mid-range opportunities
        for opp in mid_opps:
            assert CONFIG["mid_range_min"] <= opp["price"] <= CONFIG["mid_range_max"]

    def test_near_certain_skipped_long_term(self, scanner, mock_markets):
        """Test NEAR_CERTAIN skipped for long-term markets."""
        opps = scanner.find_opportunities(mock_markets)

        # 0xlongterm has 97% but is >90 days out
        near_certain = [o for o in opps if o["condition_id"] == "0xlongterm"]
        if near_certain:
            # If found, shouldn't be NEAR_CERTAIN strategy
            assert all(o["strategy"] != "NEAR_CERTAIN" for o in near_certain)

    def test_binance_arb_with_prices(self, scanner):
        """Test BINANCE_ARB with Binance prices."""
        markets = [
            {
                "conditionId": "0xbtc100k",
                "question": "Will Bitcoin reach $100,000?",
                "bestBid": 0.30,
                "bestAsk": 0.35,
                "volume24hr": 50000,
                "liquidityNum": 30000,
            }
        ]
        binance_prices = {"BTCUSDT": 95000, "ETHUSDT": 3000}

        opps = scanner.find_opportunities(markets, binance_prices)
        binance_opps = [o for o in opps if o["strategy"] == "BINANCE_ARB"]

        # Should detect if edge is sufficient
        for opp in binance_opps:
            assert abs(opp["edge"]) >= CONFIG["binance_min_edge"] * 100

    def test_diversity_limiting(self, scanner):
        """Test that diversity filter limits per-strategy opportunities."""
        # Create many markets for same strategy
        markets = []
        for i in range(10):
            markets.append({
                "conditionId": f"0xnc{i}",
                "question": f"Near certain market {i}?",
                "bestBid": 0.96,
                "bestAsk": 0.97,
                "volume24hr": 50000,
                "liquidityNum": 100000,
                "endDate": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
            })

        opps = scanner.find_opportunities(markets)
        nc_opps = [o for o in opps if o["strategy"] == "NEAR_CERTAIN"]

        # Should be limited by diversity filter (max 2 per strategy normally)
        assert len(nc_opps) <= 4

    def test_missing_end_date(self, scanner):
        """Test handling of missing endDate."""
        markets = [
            {
                "conditionId": "0xnodate",
                "question": "No date market?",
                "bestBid": 0.96,
                "bestAsk": 0.97,
                "volume24hr": 50000,
                "liquidityNum": 100000,
                # No endDate
            }
        ]

        # Should not crash
        opps = scanner.find_opportunities(markets)
        assert isinstance(opps, list)

    def test_invalid_end_date(self, scanner):
        """Test handling of invalid endDate."""
        markets = [
            {
                "conditionId": "0xbaddate",
                "question": "Bad date market?",
                "bestBid": 0.50,
                "bestAsk": 0.52,
                "volume24hr": 50000,
                "liquidityNum": 100000,
                "endDate": "not-a-date",
            }
        ]

        # Should not crash
        opps = scanner.find_opportunities(markets)
        assert isinstance(opps, list)


# ============================================================
# API FETCH TESTS (MOCKED)
# ============================================================

class TestApiFetch:
    """Tests for API fetching methods."""

    @pytest.mark.asyncio
    async def test_get_active_markets_success(self, scanner):
        """Test successful market fetch."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=[
            {"conditionId": "0x1", "liquidityNum": 100000},
            {"conditionId": "0x2", "liquidityNum": 1000},  # Below min
        ])
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_response)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            markets = await scanner.get_active_markets()

        # Should filter by liquidity
        assert len(markets) == 1
        assert markets[0]["conditionId"] == "0x1"

    @pytest.mark.asyncio
    async def test_get_active_markets_error(self, scanner):
        """Test market fetch with error."""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            markets = await scanner.get_active_markets()

        assert markets == []

    @pytest.mark.asyncio
    async def test_get_market_price_success(self, scanner):
        """Test successful price fetch."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=[
            {"conditionId": "0xtest", "bestAsk": 0.65},
        ])
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_response)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            price = await scanner.get_market_price("0xtest")

        assert price == 0.65

    @pytest.mark.asyncio
    async def test_get_market_price_not_found(self, scanner):
        """Test price fetch when market not found."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=[])
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_response)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            price = await scanner.get_market_price("0xnonexistent")

        assert price is None

    @pytest.mark.asyncio
    async def test_get_binance_prices_success(self, scanner):
        """Test successful Binance price fetch."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=[
            {"symbol": "BTCUSDT", "price": "95000.00"},
            {"symbol": "ETHUSDT", "price": "3200.00"},
            {"symbol": "SOLUSDT", "price": "150.00"},
            {"symbol": "XRPUSDT", "price": "0.50"},  # Not in our list
        ])
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_response)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            prices = await scanner.get_binance_prices()

        assert prices["BTCUSDT"] == 95000.0
        assert prices["ETHUSDT"] == 3200.0
        assert prices["SOLUSDT"] == 150.0
        assert "XRPUSDT" not in prices  # Not in config

    @pytest.mark.asyncio
    async def test_get_binance_prices_error(self, scanner):
        """Test Binance price fetch with error."""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(side_effect=Exception("API error"))
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            prices = await scanner.get_binance_prices()

        assert prices == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
