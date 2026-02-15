"""
Shared Fixtures and Mocks for Testing
======================================

This file is automatically loaded by pytest and provides:
- Mock API responses (Polymarket, Binance)
- Temporary portfolio fixtures
- Sample market data
"""

import pytest
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Add parent path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================
# MOCK DATA
# ============================================================

MOCK_MARKETS = [
    {
        "conditionId": "0xmarket1",
        "question": "Will Bitcoin hit $100k by March 2026?",
        "bestBid": 0.45,
        "bestAsk": 0.48,
        "volume24hr": 50000,
        "liquidityNum": 100000,
        "endDate": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    },
    {
        "conditionId": "0xmarket2",
        "question": "Will Trump win 2028 election?",
        "bestBid": 0.95,
        "bestAsk": 0.97,
        "volume24hr": 200000,
        "liquidityNum": 500000,
        "endDate": (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
    },
    {
        "conditionId": "0xmarket3",
        "question": "Will the Lakers win 2026 NBA Finals?",
        "bestBid": 0.03,
        "bestAsk": 0.06,
        "volume24hr": 30000,
        "liquidityNum": 80000,
        "endDate": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
    },
    {
        "conditionId": "0xmarket4",
        "question": "Will something very unlikely happen?",
        "bestBid": 0.01,
        "bestAsk": 0.03,
        "volume24hr": 15000,
        "liquidityNum": 50000,
        "endDate": (datetime.now(timezone.utc) + timedelta(days=60)).isoformat(),
    },
    {
        "conditionId": "0xmarket5",
        "question": "Close race market",
        "bestBid": 0.48,
        "bestAsk": 0.52,
        "volume24hr": 100000,
        "liquidityNum": 200000,
        "endDate": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
    },
]

MOCK_BINANCE_PRICES = {
    "BTCUSDT": 67000.0,
    "ETHUSDT": 2100.0,
    "SOLUSDT": 85.0,
}

MOCK_PORTFOLIO_DATA = {
    "balance": 1000.0,
    "initial_balance": 1000.0,
    "positions": {},
    "trade_history": [],
    "metrics": {
        "total_pnl": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "peak_balance": 1000.0,
    },
    "strategy_metrics": {
        "NEAR_CERTAIN": {"trades": 0, "wins": 0, "pnl": 0.0},
        "NEAR_ZERO": {"trades": 0, "wins": 0, "pnl": 0.0},
        "DIP_BUY": {"trades": 0, "wins": 0, "pnl": 0.0},
        "VOLUME_SURGE": {"trades": 0, "wins": 0, "pnl": 0.0},
        "MID_RANGE": {"trades": 0, "wins": 0, "pnl": 0.0},
        "DUAL_SIDE_ARB": {"trades": 0, "wins": 0, "pnl": 0.0},
        "MARKET_MAKER": {"trades": 0, "wins": 0, "pnl": 0.0},
        "BINANCE_ARB": {"trades": 0, "wins": 0, "pnl": 0.0},
    },
    "last_updated": datetime.now(timezone.utc).isoformat(),
}


# ============================================================
# FIXTURES - Data
# ============================================================

@pytest.fixture
def mock_markets():
    """Sample market data for testing."""
    return MOCK_MARKETS.copy()


@pytest.fixture
def mock_binance_prices():
    """Sample Binance prices for testing."""
    return MOCK_BINANCE_PRICES.copy()


@pytest.fixture
def mock_portfolio_data():
    """Sample portfolio data for testing."""
    import copy
    return copy.deepcopy(MOCK_PORTFOLIO_DATA)


# ============================================================
# FIXTURES - Components
# ============================================================

@pytest.fixture
def temp_portfolio(tmp_path):
    """Create a temporary portfolio for testing."""
    from sovereign_hive.run_simulation import Portfolio

    portfolio_file = tmp_path / "test_portfolio.json"
    portfolio = Portfolio(initial_balance=1000.0, data_file=str(portfolio_file))
    return portfolio


@pytest.fixture
def scanner():
    """Create a market scanner instance."""
    from sovereign_hive.run_simulation import MarketScanner
    return MarketScanner()


@pytest.fixture
def trading_engine(tmp_path):
    """Create a trading engine with temporary portfolio."""
    from sovereign_hive.run_simulation import TradingEngine, Portfolio

    # Patch the portfolio to use temp directory
    portfolio_file = tmp_path / "test_portfolio.json"

    with patch('sovereign_hive.run_simulation.Portfolio') as MockPortfolio:
        MockPortfolio.return_value = Portfolio(
            initial_balance=1000.0,
            data_file=str(portfolio_file)
        )
        engine = TradingEngine(live=False)
        engine.portfolio = Portfolio(
            initial_balance=1000.0,
            data_file=str(portfolio_file)
        )
        return engine


# ============================================================
# FIXTURES - Mocked APIs
# ============================================================

@pytest.fixture
def mock_polymarket_api(mocker):
    """Mock Polymarket Gamma API responses."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=MOCK_MARKETS)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(return_value=mock_response)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    return mocker.patch('aiohttp.ClientSession', return_value=mock_session)


@pytest.fixture
def mock_binance_api(mocker):
    """Mock Binance price API."""
    async def mock_get_prices():
        return MOCK_BINANCE_PRICES

    return mocker.patch(
        'sovereign_hive.run_simulation.MarketScanner.get_binance_prices',
        side_effect=mock_get_prices
    )


# ============================================================
# FIXTURES - Utility
# ============================================================

@pytest.fixture
def sample_position():
    """Sample position data."""
    return {
        "condition_id": "0xtest123",
        "question": "Test market question",
        "side": "YES",
        "entry_price": 0.50,
        "shares": 200.0,
        "cost_basis": 100.0,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "strategy": "TEST",
        "reason": "Test position",
    }


@pytest.fixture
def sample_trade():
    """Sample completed trade data."""
    return {
        "condition_id": "0xtest123",
        "question": "Test market question",
        "side": "YES",
        "entry_price": 0.50,
        "exit_price": 0.60,
        "shares": 200.0,
        "cost_basis": 100.0,
        "proceeds": 120.0,
        "pnl": 20.0,
        "pnl_pct": 0.20,
        "entry_time": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "exit_time": datetime.now(timezone.utc).isoformat(),
        "exit_reason": "TAKE_PROFIT",
        "strategy": "TEST",
    }


# ============================================================
# MARKERS
# ============================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (skip with -m 'not slow')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "e2e: marks tests as end-to-end tests")
    config.addinivalue_line("markers", "live_api: marks tests that make real API calls")


# ============================================================
# HELPERS
# ============================================================

def assert_valid_opportunity(opp: dict):
    """Assert that an opportunity dict has required fields."""
    required_fields = [
        "condition_id",
        "question",
        "strategy",
        "side",
        "price",
        "confidence",
        "reason",
    ]
    for field in required_fields:
        assert field in opp, f"Missing required field: {field}"

    assert opp["strategy"] in [
        "NEAR_CERTAIN", "NEAR_ZERO", "DIP_BUY", "VOLUME_SURGE",
        "MID_RANGE", "DUAL_SIDE_ARB", "MARKET_MAKER", "BINANCE_ARB"
    ]
    assert opp["side"] in ["YES", "NO", "MM", "BOTH"]
    assert 0 <= opp["price"] <= 1 or opp["side"] == "MM"
    assert 0 <= opp["confidence"] <= 1


def assert_valid_trade(trade: dict):
    """Assert that a trade dict has required fields."""
    required_fields = [
        "condition_id",
        "question",
        "side",
        "entry_price",
        "exit_price",
        "pnl",
        "pnl_pct",
        "exit_reason",
    ]
    for field in required_fields:
        assert field in trade, f"Missing required field: {field}"
