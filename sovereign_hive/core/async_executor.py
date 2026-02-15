#!/usr/bin/env python3
"""
ASYNC EXECUTOR - Non-Blocking Order Execution
=============================================
Fire orders without blocking the main loop.
Includes retry logic with exponential backoff.
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
    Non-blocking order execution for Gamma Sniper.
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
                creds=creds
            )
            self._initialized = True
            print("[EXEC] CLOB client initialized")
        except Exception as e:
            print(f"[EXEC] Init error: {e}")

    def _is_retryable(self, error: str) -> bool:
        """Check if error is retryable."""
        error_lower = error.lower()
        return any(err in error_lower for err in RETRYABLE_ERRORS)

    async def execute_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        dry_run: bool = True
    ) -> dict:
        """Execute order asynchronously with retry logic."""

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

        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                from py_clob_client.clob_types import OrderArgs

                o_args = OrderArgs(
                    price=price,
                    size=size,
                    side=side,
                    token_id=token_id
                )

                # Execute in thread pool (CLOB client is sync)
                resp = await asyncio.to_thread(
                    self.client.create_and_post_order, o_args
                )

                print(f"[EXEC] Order placed: {resp}")
                return {
                    "success": resp.get("success", False),
                    "dry_run": False,
                    "order_id": resp.get("orderID", ""),
                    "status": resp.get("status", "UNKNOWN"),
                    "response": resp,
                    "attempts": attempt + 1
                }

            except Exception as e:
                last_error = str(e)
                print(f"[EXEC] Error (attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}")

                # Check if retryable
                if attempt < MAX_RETRIES and self._is_retryable(last_error):
                    delay = RETRY_DELAY_BASE * (2 ** attempt)  # Exponential backoff
                    print(f"[EXEC] Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    break

        return {"success": False, "error": last_error, "attempts": MAX_RETRIES + 1}

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
        """Cancel an order."""
        if not self._initialized:
            await self.init()

        try:
            resp = await asyncio.to_thread(
                self.client.cancel, order_id
            )
            return resp.get("success", False)
        except:
            return False


# Singleton
_executor = None

def get_executor() -> AsyncExecutor:
    global _executor
    if _executor is None:
        _executor = AsyncExecutor()
    return _executor
