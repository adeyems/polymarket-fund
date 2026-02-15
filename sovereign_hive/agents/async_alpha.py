#!/usr/bin/env python3
"""
ASYNC ALPHA SCOUT - Event-Driven Anomaly Detection
==================================================
Reacts to market changes in real-time via WebSocket.
Falls back to polling if WebSocket unavailable.
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional
import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from core.redis_state import get_state
from core.ws_listener import GammaAPIPoller


# Anomaly Thresholds
ARBITRAGE_THRESHOLD = 0.98
DIP_THRESHOLD = -0.10
VOLUME_MIN = 100_000
SPREAD_MAX = 0.05


class AsyncAlphaScout:
    """
    Event-driven mathematical anomaly detection.
    """

    def __init__(self):
        self.state = get_state()
        self.poller = GammaAPIPoller(interval=10.0)
        self.running = False

    def detect_anomalies(self, markets: List[dict]) -> List[dict]:
        """Pure mathematical anomaly detection."""
        opportunities = []

        for m in markets:
            try:
                question = m.get("question", "Unknown")
                condition_id = m.get("conditionId", "")

                if not condition_id:
                    continue

                best_bid = float(m.get("bestBid") or 0)
                best_ask = float(m.get("bestAsk") or 0)
                volume_24h = float(m.get("volume24hr") or 0)
                volume_1w = float(m.get("volume1wk") or 0)
                liquidity = float(m.get("liquidityNum") or 0)
                price_change = float(m.get("oneDayPriceChange") or 0)

                if volume_24h < VOLUME_MIN:
                    continue

                spread = (best_ask - best_bid) / best_ask if best_ask > 0 else 1.0
                anomaly = None
                score = 0

                # ARBITRAGE
                if best_ask >= ARBITRAGE_THRESHOLD and best_ask < 0.999:
                    profit = (1.0 - best_ask) / best_ask * 100
                    if spread < 0.02:
                        anomaly = "ARBITRAGE"
                        score = profit

                # DIP_BUY
                elif price_change <= DIP_THRESHOLD and volume_24h > 500_000:
                    anomaly = "DIP_BUY"
                    score = abs(price_change) * 100

                # VOLUME_SPIKE
                elif volume_1w > 0:
                    daily_avg = volume_1w / 7
                    if volume_24h > daily_avg * 2:
                        if abs(price_change) > 0.05:
                            anomaly = "VOLUME_SPIKE"
                            score = (volume_24h / daily_avg) * 10

                # MISPRICING
                elif spread > SPREAD_MAX and liquidity > 50_000:
                    anomaly = "MISPRICING"
                    score = spread * 100

                if anomaly:
                    # Get token IDs
                    token_ids = m.get("clobTokenIds", "[]")
                    if isinstance(token_ids, str):
                        import json
                        token_ids = json.loads(token_ids)

                    opportunities.append({
                        "condition_id": condition_id,
                        "question": question[:80],
                        "anomaly_type": anomaly,
                        "score": round(score, 2),
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "spread_pct": round(spread * 100, 2),
                        "volume_24h": int(volume_24h),
                        "price_change_1d": round(price_change * 100, 2),
                        "liquidity": int(liquidity),
                        "token_id": token_ids[0] if token_ids else "",
                        "discovered_at": datetime.now(timezone.utc).isoformat(),
                        "status": "PENDING"
                    })

            except Exception as e:
                continue

        opportunities.sort(key=lambda x: x["score"], reverse=True)
        return opportunities

    async def on_markets_update(self, markets: List[dict]):
        """Callback when new market data arrives."""
        start = datetime.now(timezone.utc)

        anomalies = self.detect_anomalies(markets)

        for opp in anomalies[:10]:  # Top 10
            self.state.add_opportunity(opp)
            print(f"[ALPHA] {opp['anomaly_type']}: {opp['question'][:40]}... @ ${opp['best_ask']:.3f}")

        # Publish event for other agents
        if anomalies:
            self.state.publish("hive:events", {
                "type": "new_opportunities",
                "count": len(anomalies),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

        elapsed = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        self.state.incr_metric("alpha_scans")
        print(f"[ALPHA] Scan complete: {len(anomalies)} anomalies in {elapsed:.0f}ms")

    async def run(self):
        """Main run loop."""
        self.running = True
        print("[ALPHA] Scout started (polling mode)")

        await self.poller.run(self.on_markets_update)

    def stop(self):
        self.running = False
        self.poller.stop()


async def main():
    scout = AsyncAlphaScout()
    try:
        await scout.run()
    except KeyboardInterrupt:
        scout.stop()


if __name__ == "__main__":
    asyncio.run(main())
