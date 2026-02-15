#!/usr/bin/env python3
"""
WEBSOCKET LISTENER - Real-Time Market Data
==========================================
Event-driven price updates. Kills polling latency.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Callable, Optional, List

try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    websockets = None

from .redis_state import get_state


class MarketWebSocket:
    """
    Real-time market listener using Polymarket WebSocket.
    Reacts to price changes instantly instead of polling.
    """

    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self, on_price_change: Callable = None):
        self.callback = on_price_change
        self.ws = None
        self.connected = False
        self.last_heartbeat = None
        self.subscribed_tokens = set()
        self.state = get_state()
        self._reconnect_attempts = 0
        self._max_reconnects = 5

    async def connect(self):
        """Establish WebSocket connection."""
        if not WS_AVAILABLE:
            print("[WS] websockets package not installed. Use GammaAPIPoller instead.")
            self.connected = False
            return False

        try:
            self.ws = await websockets.connect(
                self.WS_URL,
                ping_interval=30,
                ping_timeout=10
            )
            self.connected = True
            self._reconnect_attempts = 0
            self.last_heartbeat = datetime.now(timezone.utc)
            print(f"[WS] Connected to {self.WS_URL}")
            return True
        except Exception as e:
            print(f"[WS] Connection failed: {e}")
            self.connected = False
            return False

    async def subscribe(self, token_ids: List[str]):
        """Subscribe to market updates for specific tokens."""
        if not self.connected or not self.ws:
            print("[WS] Not connected. Call connect() first.")
            return False

        for token_id in token_ids:
            if token_id not in self.subscribed_tokens:
                msg = {
                    "type": "subscribe",
                    "channel": "market",
                    "assets_ids": [token_id]
                }
                await self.ws.send(json.dumps(msg))
                self.subscribed_tokens.add(token_id)
                print(f"[WS] Subscribed to {token_id[:16]}...")

        return True

    async def listen(self):
        """Main listening loop - processes incoming messages."""
        if not self.connected:
            await self.connect()

        try:
            async for message in self.ws:
                self.last_heartbeat = datetime.now(timezone.utc)

                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    continue

        except websockets.ConnectionClosed:
            print("[WS] Connection closed. Reconnecting...")
            self.connected = False
            await self._reconnect()

        except Exception as e:
            print(f"[WS] Error: {e}")
            self.connected = False

    async def _handle_message(self, data: dict):
        """Process incoming WebSocket message."""
        event_type = data.get("event_type") or data.get("type")

        if event_type == "price_change":
            # Price update
            token_id = data.get("asset_id")
            new_price = data.get("price")
            print(f"[WS] Price: {token_id[:16]}... -> ${new_price}")

            # Update state
            self.state.incr_metric("ws_price_updates")

            # Trigger callback
            if self.callback:
                await self.callback(data)

        elif event_type == "book_update":
            # Order book change
            self.state.incr_metric("ws_book_updates")

        elif event_type == "trade":
            # Trade executed
            self.state.incr_metric("ws_trades")
            if self.callback:
                await self.callback(data)

    async def _reconnect(self):
        """Attempt to reconnect with exponential backoff."""
        while self._reconnect_attempts < self._max_reconnects:
            self._reconnect_attempts += 1
            wait_time = 2 ** self._reconnect_attempts

            print(f"[WS] Reconnect attempt {self._reconnect_attempts}/{self._max_reconnects} in {wait_time}s...")
            await asyncio.sleep(wait_time)

            if await self.connect():
                # Resubscribe to all tokens
                if self.subscribed_tokens:
                    await self.subscribe(list(self.subscribed_tokens))
                return True

        print("[WS] Max reconnection attempts reached. Giving up.")
        self.state.set_risk_state("HALTED")
        return False

    async def health_check(self) -> bool:
        """Check if connection is alive."""
        if not self.connected:
            return False
        if self.last_heartbeat:
            elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()
            return elapsed < 30  # Consider dead if no message in 30s
        return False

    async def close(self):
        """Close connection gracefully."""
        if self.ws:
            await self.ws.close()
        self.connected = False
        print("[WS] Connection closed")


class GammaAPIPoller:
    """
    Fallback: REST polling for when WebSocket is unavailable.
    Used for market discovery (Alpha Scout).
    """

    API_URL = "https://gamma-api.polymarket.com/markets"

    def __init__(self, interval: float = 5.0):
        self.interval = interval
        self.state = get_state()
        self.running = False

    async def poll_markets(self, params: dict = None) -> List[dict]:
        """Fetch markets from Gamma API."""
        import aiohttp

        default_params = {
            "limit": "100",
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false"
        }
        if params:
            default_params.update(params)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.API_URL, params=default_params, timeout=10) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            print(f"[POLL] Error: {e}")
        return []

    async def run(self, callback: Callable):
        """Continuous polling loop."""
        self.running = True
        while self.running:
            markets = await self.poll_markets()
            if markets:
                self.state.incr_metric("poll_requests")
                await callback(markets)
            await asyncio.sleep(self.interval)

    def stop(self):
        self.running = False
