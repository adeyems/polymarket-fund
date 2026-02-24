#!/usr/bin/env python3
"""
ASYNC EXECUTOR TESTS
=====================
Tests for AsyncExecutor methods: get_fill_price, get_balance_usdc,
get_open_orders, cancel_order, get_order_status.

These test the CLOB interaction layer that maps submitted orders to
actual on-chain reality.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.core.async_executor import AsyncExecutor


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def executor():
    """Create an AsyncExecutor with mocked CLOB client."""
    ex = AsyncExecutor()
    ex.client = MagicMock()
    ex._initialized = True
    return ex


@pytest.fixture
def mock_trades_taker():
    """Trades where our order was the taker."""
    return [
        {
            "taker_order_id": "order-abc-123",
            "size": "10.0",
            "price": "0.800",
            "side": "SELL",
            "maker_orders": [],
        },
        {
            "taker_order_id": "order-abc-123",
            "size": "5.0",
            "price": "0.820",
            "side": "SELL",
            "maker_orders": [],
        },
    ]


@pytest.fixture
def mock_trades_maker():
    """Trades where our order was the maker."""
    return [
        {
            "taker_order_id": "someone-else",
            "size": "10.0",
            "price": "0.500",
            "side": "BUY",
            "maker_orders": [
                {"order_id": "our-maker-order", "matched_amount": "8.0", "price": "0.750"},
            ],
        },
        {
            "taker_order_id": "another-taker",
            "size": "5.0",
            "price": "0.500",
            "side": "BUY",
            "maker_orders": [
                {"order_id": "our-maker-order", "matched_amount": "4.0", "price": "0.760"},
            ],
        },
    ]


# ============================================================
# GET FILL PRICE TESTS
# ============================================================

class TestGetFillPrice:
    """Tests for get_fill_price — the actual CLOB execution price."""

    @pytest.mark.asyncio
    async def test_fill_price_taker_single_fill(self, executor):
        """Single fill as taker returns the trade price."""
        executor.client.get_trades = MagicMock(return_value=[
            {"taker_order_id": "order-abc", "size": "10.0", "price": "0.800", "maker_orders": []},
        ])
        price = await executor.get_fill_price("order-abc")
        assert price == pytest.approx(0.800, abs=0.001)

    @pytest.mark.asyncio
    async def test_fill_price_taker_multiple_fills_averages(self, executor, mock_trades_taker):
        """Multiple partial fills return volume-weighted average price."""
        executor.client.get_trades = MagicMock(return_value=mock_trades_taker)
        price = await executor.get_fill_price("order-abc-123")
        # VWAP: (10*0.80 + 5*0.82) / 15 = (8.0+4.1)/15 = 12.1/15 ≈ 0.8067
        expected = (10.0 * 0.800 + 5.0 * 0.820) / 15.0
        assert price == pytest.approx(expected, abs=0.001)

    @pytest.mark.asyncio
    async def test_fill_price_maker_fills(self, executor, mock_trades_maker):
        """Fills where we were the maker return correct VWAP."""
        executor.client.get_trades = MagicMock(return_value=mock_trades_maker)
        price = await executor.get_fill_price("our-maker-order")
        # VWAP: (8*0.75 + 4*0.76) / 12 = (6.0+3.04)/12 = 9.04/12 ≈ 0.7533
        expected = (8.0 * 0.750 + 4.0 * 0.760) / 12.0
        assert price == pytest.approx(expected, abs=0.001)

    @pytest.mark.asyncio
    async def test_fill_price_no_matching_trades(self, executor):
        """Returns None when no trades match the order ID."""
        executor.client.get_trades = MagicMock(return_value=[
            {"taker_order_id": "different-order", "size": "10.0", "price": "0.500", "maker_orders": []},
        ])
        price = await executor.get_fill_price("order-abc")
        assert price is None

    @pytest.mark.asyncio
    async def test_fill_price_empty_trades(self, executor):
        """Returns None when trade history is empty."""
        executor.client.get_trades = MagicMock(return_value=[])
        price = await executor.get_fill_price("order-abc")
        assert price is None

    @pytest.mark.asyncio
    async def test_fill_price_client_error(self, executor):
        """Returns None on CLOB API error (no crash)."""
        executor.client.get_trades = MagicMock(side_effect=Exception("Connection timeout"))
        price = await executor.get_fill_price("order-abc")
        assert price is None

    @pytest.mark.asyncio
    async def test_fill_price_not_initialized(self):
        """Returns None if client not initialized."""
        ex = AsyncExecutor()
        price = await ex.get_fill_price("order-abc")
        assert price is None

    @pytest.mark.asyncio
    async def test_fill_price_price_improvement(self, executor):
        """Verifies that price improvement is captured correctly.

        This is the critical bug that caused the phantom $9.87 loss:
        sell limit at $0.01 actually filled at $0.80 on the CLOB.
        """
        # Submitted sell at $0.01, CLOB matched at $0.80
        executor.client.get_trades = MagicMock(return_value=[
            {"taker_order_id": "fire-sale-order", "size": "12.0", "price": "0.800", "maker_orders": []},
        ])
        price = await executor.get_fill_price("fire-sale-order")
        assert price == pytest.approx(0.800, abs=0.001)
        # The limit price ($0.01) is irrelevant — only the actual fill matters


# ============================================================
# GET BALANCE USDC TESTS
# ============================================================

class TestGetBalanceUsdc:
    """Tests for get_balance_usdc — on-chain USDC.e balance check."""

    @pytest.mark.asyncio
    async def test_balance_success(self, executor):
        """Returns correct balance from ERC20 balanceOf."""
        mock_contract = MagicMock()
        mock_balance_fn = MagicMock()
        mock_balance_fn.call = MagicMock(return_value=10_470_000)  # 10.47 USDC (6 decimals)
        mock_contract.functions.balanceOf = MagicMock(return_value=mock_balance_fn)

        mock_decimals_fn = MagicMock()
        mock_decimals_fn.call = MagicMock(return_value=6)
        mock_contract.functions.decimals = MagicMock(return_value=mock_decimals_fn)

        with patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0x" + "ab" * 32}), \
             patch("web3.Web3") as MockWeb3:

            mock_w3 = MagicMock()
            mock_account = MagicMock()
            mock_account.address = "0x1234567890abcdef"
            mock_w3.eth.account.from_key.return_value = mock_account
            mock_w3.eth.contract.return_value = mock_contract
            MockWeb3.return_value = mock_w3
            MockWeb3.HTTPProvider = MagicMock()
            MockWeb3.to_checksum_address = lambda x: x

            balance = await executor.get_balance_usdc()
            assert balance == pytest.approx(10.47, abs=0.01)

    @pytest.mark.asyncio
    async def test_balance_rpc_failure_returns_none(self, executor):
        """Returns None on RPC failure — never corrupts internal state."""
        with patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0x" + "ab" * 32}), \
             patch("web3.Web3") as MockWeb3:

            MockWeb3.side_effect = Exception("RPC connection refused")
            MockWeb3.HTTPProvider = MagicMock()

            balance = await executor.get_balance_usdc()
            assert balance is None

    @pytest.mark.asyncio
    async def test_balance_not_initialized(self):
        """Returns None if client not initialized (and init fails)."""
        ex = AsyncExecutor()
        # Patch init to do nothing (simulating failed init)
        with patch.object(ex, 'init', new_callable=AsyncMock):
            balance = await ex.get_balance_usdc()
            assert balance is None

    @pytest.mark.asyncio
    async def test_balance_no_private_key(self, executor):
        """Returns None when POLYMARKET_PRIVATE_KEY is not set."""
        with patch.dict("os.environ", {}, clear=True), \
             patch("web3.Web3") as MockWeb3:

            mock_w3 = MagicMock()
            MockWeb3.return_value = mock_w3
            MockWeb3.HTTPProvider = MagicMock()

            balance = await executor.get_balance_usdc()
            assert balance is None


# ============================================================
# GET OPEN ORDERS TESTS
# ============================================================

class TestGetOpenOrders:
    """Tests for get_open_orders — current CLOB orders."""

    @pytest.mark.asyncio
    async def test_open_orders_success(self, executor):
        """Returns list of open orders."""
        mock_orders = [
            {"orderID": "ord-1", "side": "BUY", "price": "0.80", "original_size": "10"},
            {"orderID": "ord-2", "side": "SELL", "price": "0.85", "original_size": "10"},
        ]
        executor.client.get_orders = MagicMock(return_value=mock_orders)
        orders = await executor.get_open_orders()
        assert len(orders) == 2

    @pytest.mark.asyncio
    async def test_open_orders_empty(self, executor):
        """Returns empty list when no orders."""
        executor.client.get_orders = MagicMock(return_value=[])
        orders = await executor.get_open_orders()
        assert orders == []

    @pytest.mark.asyncio
    async def test_open_orders_error_returns_empty(self, executor):
        """Returns empty list on API error (no crash)."""
        executor.client.get_orders = MagicMock(side_effect=Exception("500 Internal Server Error"))
        orders = await executor.get_open_orders()
        assert orders == []

    @pytest.mark.asyncio
    async def test_open_orders_not_initialized(self):
        """Returns empty list if client not initialized."""
        ex = AsyncExecutor()
        with patch.object(ex, 'init', new_callable=AsyncMock):
            orders = await ex.get_open_orders()
            assert orders == []


# ============================================================
# CANCEL ORDER TESTS
# ============================================================

class TestCancelOrder:
    """Tests for cancel_order — single order cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_success(self, executor):
        """Returns True when order is successfully cancelled."""
        executor.client.cancel = MagicMock(return_value={"canceled": ["ord-123"]})
        result = await executor.cancel_order("ord-123")
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, executor):
        """Returns False when order is not in cancelled list."""
        executor.client.cancel = MagicMock(return_value={"canceled": []})
        result = await executor.cancel_order("ord-123")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_error(self, executor):
        """Returns False on API error."""
        executor.client.cancel = MagicMock(side_effect=Exception("order not found"))
        result = await executor.cancel_order("ord-123")
        assert result is False


# ============================================================
# GET ORDER STATUS TESTS
# ============================================================

class TestGetOrderStatus:
    """Tests for get_order_status — CLOB order state polling."""

    @pytest.mark.asyncio
    async def test_status_live(self, executor):
        """Returns LIVE status with correct fields."""
        executor.client.get_order = MagicMock(return_value={
            "status": "LIVE",
            "size_matched": "5.0",
            "original_size": "10.0",
            "price": "0.80",
            "side": "BUY",
        })
        status = await executor.get_order_status("ord-123")
        assert status["status"] == "LIVE"
        assert status["size_matched"] == 5.0
        assert status["original_size"] == 10.0

    @pytest.mark.asyncio
    async def test_status_matched(self, executor):
        """Returns MATCHED when fully filled."""
        executor.client.get_order = MagicMock(return_value={
            "status": "MATCHED",
            "size_matched": "10.0",
            "original_size": "10.0",
            "price": "0.80",
            "side": "BUY",
        })
        status = await executor.get_order_status("ord-123")
        assert status["status"] == "MATCHED"
        assert status["size_matched"] == status["original_size"]

    @pytest.mark.asyncio
    async def test_status_canceled_american_spelling(self, executor):
        """CLOB uses 'CANCELED' (American spelling) — must handle it."""
        executor.client.get_order = MagicMock(return_value={
            "status": "CANCELED",
            "size_matched": "0",
            "original_size": "10.0",
            "price": "0.80",
            "side": "BUY",
        })
        status = await executor.get_order_status("ord-123")
        assert status["status"] == "CANCELED"

    @pytest.mark.asyncio
    async def test_status_error_returns_safe_defaults(self, executor):
        """Returns ERROR status with zeroed fields on API failure."""
        executor.client.get_order = MagicMock(side_effect=Exception("timeout"))
        status = await executor.get_order_status("ord-123")
        assert status["status"] == "ERROR"
        assert status["size_matched"] == 0
        assert status["original_size"] == 0


# ============================================================
# RETRY LOGIC TESTS
# ============================================================

class TestRetryLogic:
    """Tests for the retry wrapper."""

    def test_is_retryable_timeout(self, executor):
        assert executor._is_retryable("Connection timeout after 30s") is True

    def test_is_retryable_503(self, executor):
        assert executor._is_retryable("503 Service Unavailable") is True

    def test_is_retryable_rate_limit(self, executor):
        assert executor._is_retryable("Rate limit exceeded") is True

    def test_not_retryable_auth(self, executor):
        assert executor._is_retryable("401 Unauthorized") is False

    def test_not_retryable_invalid_order(self, executor):
        assert executor._is_retryable("Invalid order parameters") is False
