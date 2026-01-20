import asyncio
import json
import websockets
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class BinanceWSManager:
    """
    Manages persistent WebSocket connections to Binance for real-time spot prices.
    Features automatic reconnection and thread-safe price caching.
    """
    def __init__(self, symbols: list):
        self.symbols = [s.lower() for s in symbols]
        self.prices: Dict[str, float] = {}
        self.url = "wss://stream.binance.com:9443/ws"
        self._is_running = False
        self._task: Optional[asyncio.Task] = None

    async def _handle_message(self, message: str):
        try:
            data = json.loads(message)
            if "s" in data and "p" in data:
                symbol = data["s"].upper()
                price = float(data["p"])
                self.prices[symbol] = price
        except Exception as e:
            logger.error(f"Error parsing Binance message: {e}")

    async def _listen(self):
        streams = "/".join([f"{s}@aggTrade" for s in self.symbols])
        full_url = f"{self.url}/{streams}"
        
        while self._is_running:
            try:
                print(f"[BINANCE-WS] Connecting to {full_url}...")
                async with websockets.connect(full_url) as ws:
                    print(f"[BINANCE-WS] Connected.")
                    while self._is_running:
                        message = await ws.recv()
                        await self._handle_message(message)
            except (websockets.ConnectionClosed, Exception) as e:
                print(f"[BINANCE-WS] Connection lost ({e}). Retrying in 5s...")
                await asyncio.sleep(5)

    def start(self):
        """Starts the WebSocket listener in the current event loop."""
        if not self._is_running:
            self._is_running = True
            self._task = asyncio.create_task(self._listen())
            print(f"[BINANCE-WS] Manager started for {self.symbols}")

    def stop(self):
        """Stops the WebSocket listener."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            print("[BINANCE-WS] Manager stopped.")

    def get_price(self, symbol: str) -> Optional[float]:
        """Returns the latest cached price for a symbol."""
        return self.prices.get(symbol.upper())

# Singleton-style access
_manager: Optional[BinanceWSManager] = None

def get_binance_manager(symbols: list = None) -> BinanceWSManager:
    global _manager
    if _manager is None:
        if symbols is None:
            symbols = ["btcusdt", "ethusdt", "solusdt"]
        _manager = BinanceWSManager(symbols)
    return _manager
