#!/usr/bin/env python3
"""
ASYNC EXECUTOR - Non-Blocking Order Execution
=============================================
Fire orders without blocking the main loop.
Includes retry logic with exponential backoff.
Supports live trading via CLOB API with post-only orders.
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1.0  # seconds
RETRYABLE_ERRORS = [
    "timeout",
    "connection",
    "rate limit",
    "503",
    "502",
    "temporarily unavailable"
]


class AsyncExecutor:
    """
    Non-blocking order execution via Polymarket CLOB API.
    Includes retry logic for transient failures.
    """

    def __init__(self):
        self.client = None
        self._initialized = False
        self._retry_count = 0

    async def init(self):
        """Lazy initialization of CLOB client."""
        if self._initialized:
            return

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            creds = ApiCreds(
                api_key=os.getenv("CLOB_API_KEY"),
                api_secret=os.getenv("CLOB_SECRET"),
                api_passphrase=os.getenv("CLOB_PASSPHRASE")
            )

            self.client = ClobClient(
                host="https://clob.polymarket.com",
                chain_id=137,
                key=os.getenv("POLYMARKET_PRIVATE_KEY"),
                creds=creds,
                signature_type=0,  # EOA (Externally Owned Account)
            )
            self._initialized = True
            print("[EXEC] CLOB client initialized (signature_type=EOA)")
        except Exception as e:
            print(f"[EXEC] Init error: {e}")

    def _is_retryable(self, error: str) -> bool:
        """Check if error is retryable."""
        error_lower = error.lower()
        return any(err in error_lower for err in RETRYABLE_ERRORS)

    async def _retry_operation(self, operation, operation_name: str) -> dict:
        """Generic retry wrapper for async operations."""
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await operation()
            except Exception as e:
                last_error = str(e)
                print(f"[EXEC] {operation_name} error (attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}")
                if attempt < MAX_RETRIES and self._is_retryable(last_error):
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    print(f"[EXEC] Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    break
        return {"success": False, "error": last_error, "attempts": MAX_RETRIES + 1}

    async def get_fee_rate_bps(self, token_id: str) -> int:
        """
        Query the current fee rate for a token.

        Returns fee in basis points (e.g., 150 = 1.50%).
        Maker (post-only) orders always have 0 fee, but the field must still
        match what the CLOB expects in the signed payload.
        Falls back to 0 on error (safe for maker/post-only orders).
        """
        if not self._initialized:
            await self.init()

        if not self.client:
            return 0

        try:
            fee_bps = await asyncio.to_thread(
                self.client.get_fee_rate_bps, token_id
            )
            return int(fee_bps)
        except Exception as e:
            print(f"[EXEC] get_fee_rate_bps error: {e} — defaulting to 0")
            return 0

    async def execute_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        dry_run: bool = True
    ) -> dict:
        """Execute order asynchronously with retry logic (legacy method)."""

        if dry_run:
            print(f"[EXEC] DRY RUN: {side} {size:.2f} @ ${price:.3f}")
            return {
                "success": True,
                "dry_run": True,
                "order_id": f"DRY_{token_id[:16]}",
                "status": "SIMULATED"
            }

        if not self._initialized:
            await self.init()

        if not self.client:
            return {"success": False, "error": "Client not initialized"}

        # Query fee rate for this token (required in signed payload)
        fee_bps = await self.get_fee_rate_bps(token_id)

        async def _do():
            from py_clob_client.clob_types import OrderArgs
            o_args = OrderArgs(
                price=price,
                size=size,
                side=side,
                token_id=token_id,
                fee_rate_bps=fee_bps,
            )
            resp = await asyncio.to_thread(
                self.client.create_and_post_order, o_args
            )
            print(f"[EXEC] Order placed (fee={fee_bps}bps): {resp}")
            return {
                "success": resp.get("success", False),
                "dry_run": False,
                "order_id": resp.get("orderID", ""),
                "status": resp.get("status", "UNKNOWN"),
                "response": resp,
            }

        return await self._retry_operation(_do, "execute_order")

    async def post_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        post_only: bool = True
    ) -> dict:
        """
        Post a GTC limit order via the CLOB API.

        Args:
            token_id: The CLOB token ID (from clobTokenIds)
            side: "BUY" or "SELL"
            price: Limit price (0.001 to 0.999)
            size: Number of shares
            post_only: If True, guarantees maker status (zero fees).
                       Order is rejected if it would cross the spread.

        Returns:
            dict with orderID, success, status
        """
        if not self._initialized:
            await self.init()

        if not self.client:
            return {"success": False, "error": "Client not initialized"}

        # Query fee rate (0 for post-only/maker, but must match CLOB expectation)
        fee_bps = await self.get_fee_rate_bps(token_id)

        async def _do():
            from py_clob_client.clob_types import OrderArgs, OrderType

            o_args = OrderArgs(
                price=price,
                size=round(size, 2),
                side=side,
                token_id=token_id,
                fee_rate_bps=fee_bps,
            )

            # Two-step: create (sign) then post with post_only flag
            signed_order = await asyncio.to_thread(
                self.client.create_order, o_args
            )
            resp = await asyncio.to_thread(
                self.client.post_order, signed_order, OrderType.GTC, post_only
            )

            order_id = resp.get("orderID", "")
            success = bool(order_id)
            print(f"[EXEC] {'POST-ONLY ' if post_only else ''}LIMIT {side} {size:.2f} @ ${price:.3f} (fee={fee_bps}bps) -> {order_id[:16] if order_id else 'FAILED'}")
            return {
                "success": success,
                "orderID": order_id,
                "status": resp.get("status", "LIVE" if success else "FAILED"),
                "response": resp,
            }

        return await self._retry_operation(_do, f"post_limit_{side}")

    async def get_order_status(self, order_id: str) -> dict:
        """
        Get the current status of an order.

        Returns:
            dict with status, size_matched, original_size, price
            status is one of: LIVE, MATCHED, CANCELLED, EXPIRED
        """
        if not self._initialized:
            await self.init()

        if not self.client:
            return {"status": "UNKNOWN", "size_matched": 0, "original_size": 0}

        try:
            resp = await asyncio.to_thread(
                self.client.get_order, order_id
            )
            return {
                "status": resp.get("status", "UNKNOWN"),
                "size_matched": float(resp.get("size_matched", 0)),
                "original_size": float(resp.get("original_size", resp.get("size", 0))),
                "price": float(resp.get("price", 0)),
                "side": resp.get("side", ""),
                "response": resp,
            }
        except Exception as e:
            print(f"[EXEC] get_order_status error: {e}")
            return {"status": "ERROR", "size_matched": 0, "original_size": 0, "error": str(e)}

    async def cancel_all_orders(self) -> bool:
        """Cancel all open orders. Used for emergency shutdown."""
        if not self._initialized:
            await self.init()

        if not self.client:
            return False

        try:
            resp = await asyncio.to_thread(
                self.client.cancel_all
            )
            print(f"[EXEC] Cancel all orders: {resp}")
            return True
        except Exception as e:
            print(f"[EXEC] cancel_all error: {e}")
            return False

    async def get_order_book(self, token_id: str) -> dict:
        """Fetch order book asynchronously."""
        if not self._initialized:
            await self.init()

        if not self.client:
            return {}

        try:
            book = await asyncio.to_thread(
                self.client.get_order_book, token_id
            )
            return {
                "bids": [(float(b.price), float(b.size)) for b in book.bids[:5]],
                "asks": [(float(a.price), float(a.size)) for a in book.asks[:5]]
            }
        except Exception as e:
            print(f"[EXEC] Book error: {e}")
            return {}

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order by ID."""
        if not self._initialized:
            await self.init()

        try:
            resp = await asyncio.to_thread(
                self.client.cancel, order_id
            )
            cancelled = resp.get("canceled", [])
            success = order_id in cancelled if isinstance(cancelled, list) else bool(cancelled)
            print(f"[EXEC] Cancel {order_id[:16]}... -> {'OK' if success else 'FAILED'}")
            return success
        except Exception as e:
            print(f"[EXEC] Cancel error: {e}")
            return False


# Singleton
_executor = None

def get_executor() -> AsyncExecutor:
    global _executor
    if _executor is None:
        _executor = AsyncExecutor()
    return _executor
