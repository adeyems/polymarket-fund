#!/usr/bin/env python3
"""
TWITTER SCOUT - Real-Time News Detection
==========================================
Monitors Twitter/X for breaking news that affects Polymarket prices.

The edge: Be first to react to news before price moves.

Without Twitter API ($100/mo), we use alternatives:
1. Nitter (free Twitter scraper) - often blocked
2. RSS feeds from journalists
3. Polymarket's own activity feed (volume spikes = someone knows something)

IMPORTANT: Twitter API Basic is $100/month minimum.
For production, you need this. For testing, we use volume detection.
"""

import asyncio
import aiohttp
import os
from datetime import datetime, timezone
from typing import List, Dict, Optional
import re
import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from core.redis_state import get_state


# Key Twitter accounts to monitor (if we had API access)
KEY_ACCOUNTS = [
    # Politics
    "realDonaldTrump", "JoeBiden", "POTUS", "WhiteHouse",
    "elikibaer", "Nate_Cohn", "NateSilver538",

    # Crypto
    "elonmusk", "saboruschka", "CryptoHayes", "zaboruschka",

    # Breaking News
    "Breaking911", "BNONews", "disclosetv", "unusual_whales",

    # Sports
    "wojespn", "ShamsCharania", "AdamSchefter",
]

# Keywords that signal market-moving news
SIGNAL_KEYWORDS = [
    # Political
    "breaking", "just in", "developing", "confirmed", "announces",
    "resigns", "drops out", "wins", "loses", "indicted", "arrested",

    # Crypto
    "btc", "bitcoin", "ethereum", "sec", "etf approved", "hack",

    # Sports
    "trade", "injury", "out for", "signs with", "released",
]


class TwitterScout:
    """
    Real-time news detection for trading signals.

    Strategy:
    1. Monitor volume spikes on Polymarket (someone knows something)
    2. Cross-reference with news sources
    3. If news confirms the move direction → follow the smart money
    4. If no news found → potential manipulation, skip
    """

    def __init__(self):
        self.state = get_state()
        self.twitter_bearer = os.getenv("TWITTER_BEARER_TOKEN", "")
        self.running = False
        self._last_volumes = {}  # condition_id -> volume

    async def detect_volume_anomaly(self) -> List[dict]:
        """
        Detect sudden volume spikes that suggest news is breaking.
        This works WITHOUT Twitter API.
        """
        signals = []

        try:
            async with aiohttp.ClientSession() as session:
                url = "https://gamma-api.polymarket.com/markets"
                params = {"limit": 100, "active": "true"}

                async with session.get(url, params=params, timeout=15) as resp:
                    if resp.status != 200:
                        return signals

                    markets = await resp.json()

                    for m in markets:
                        condition_id = m.get("conditionId", "")
                        question = m.get("question", "")
                        volume_24h = float(m.get("volume24hr") or 0)
                        volume_1h = float(m.get("volume1hr") or 0) if m.get("volume1hr") else volume_24h / 24
                        price_change = float(m.get("oneDayPriceChange") or 0)
                        best_ask = float(m.get("bestAsk") or 0)
                        liquidity = float(m.get("liquidityNum") or 0)

                        # Skip low liquidity
                        if liquidity < 10000:
                            continue

                        # Check for volume spike
                        prev_volume = self._last_volumes.get(condition_id, 0)

                        # Calculate hourly rate
                        hourly_avg = volume_24h / 24

                        # SIGNAL: Volume spike > 5x normal hourly rate
                        if volume_1h > hourly_avg * 5 and volume_1h > 10000:
                            # Something is happening
                            direction = "BULLISH" if price_change > 0 else "BEARISH"

                            signals.append({
                                "condition_id": condition_id,
                                "question": question[:80],
                                "anomaly_type": "VOLUME_SURGE",
                                "volume_1h": int(volume_1h),
                                "volume_avg_hourly": int(hourly_avg),
                                "volume_multiplier": round(volume_1h / hourly_avg, 1) if hourly_avg > 0 else 0,
                                "price_change_1d": round(price_change * 100, 2),
                                "direction": direction,
                                "best_ask": best_ask,
                                "liquidity": int(liquidity),
                                "signal": f"5x+ volume surge ({direction})",
                                "discovered_at": datetime.now(timezone.utc).isoformat(),
                                "status": "PENDING"
                            })

                            print(f"[TWITTER] 🚨 VOLUME SURGE: {question[:40]}...")
                            print(f"    Volume: ${volume_1h:,.0f}/hr (normal: ${hourly_avg:,.0f}/hr)")
                            print(f"    Direction: {direction} ({price_change*100:+.1f}%)")

                        # Update cache
                        self._last_volumes[condition_id] = volume_24h

        except Exception as e:
            print(f"[TWITTER] Error: {e}")

        return signals

    async def search_news_for_market(self, question: str) -> Optional[dict]:
        """
        Search for news related to a market question.
        Uses NewsAPI as fallback (slow but works).
        """
        api_key = os.getenv("NEWS_API_KEY", "")
        if not api_key:
            return None

        # Extract search terms
        words = question.lower().replace("?", "").split()
        stopwords = {"will", "the", "be", "a", "an", "in", "on", "by", "to", "of"}
        keywords = [w for w in words if w not in stopwords and len(w) > 2][:4]
        query = " ".join(keywords)

        try:
            async with aiohttp.ClientSession() as session:
                url = "https://newsapi.org/v2/everything"
                params = {
                    "q": query,
                    "sortBy": "publishedAt",
                    "language": "en",
                    "pageSize": "5",
                    "apiKey": api_key
                }

                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        articles = data.get("articles", [])

                        if articles:
                            latest = articles[0]
                            return {
                                "title": latest.get("title", ""),
                                "source": latest.get("source", {}).get("name", ""),
                                "published": latest.get("publishedAt", ""),
                                "url": latest.get("url", "")
                            }
        except Exception as e:
            print(f"[TWITTER] News search error: {e}")

        return None

    async def analyze_signal(self, signal: dict) -> dict:
        """
        Analyze a volume signal to determine if we should trade.
        """
        question = signal.get("question", "")

        # Search for confirming news
        news = await self.search_news_for_market(question)

        if news:
            signal["news_found"] = True
            signal["news_title"] = news["title"][:80]
            signal["news_source"] = news["source"]
            signal["confidence"] = 0.75  # News confirms the move
            signal["recommendation"] = f"FOLLOW_{signal['direction']}"
            print(f"[TWITTER] 📰 News found: {news['title'][:50]}...")
        else:
            signal["news_found"] = False
            signal["confidence"] = 0.5  # Volume only, no confirmation
            signal["recommendation"] = "MONITOR"
            print(f"[TWITTER] ⚠️  No news found - could be manipulation")

        return signal

    async def run(self, interval: float = 30.0):
        """Main monitoring loop."""
        self.running = True
        print("[TWITTER] Scout started (volume-based detection)")
        print("[TWITTER] Monitoring for 5x+ volume surges...")

        if not self.twitter_bearer:
            print("[TWITTER] ⚠️  No Twitter API - using volume detection only")

        while self.running:
            try:
                # Detect volume anomalies
                signals = await self.detect_volume_anomaly()

                # Analyze each signal
                for signal in signals:
                    analyzed = await self.analyze_signal(signal)

                    if analyzed.get("news_found") or analyzed.get("volume_multiplier", 0) > 10:
                        # High confidence - add to opportunities
                        self.state.add_opportunity(analyzed)
                        print(f"[TWITTER] ✅ Signal added: {analyzed['recommendation']}")

            except Exception as e:
                print(f"[TWITTER] Error: {e}")

            await asyncio.sleep(interval)

    def stop(self):
        self.running = False


async def main():
    print("=" * 60)
    print("  TWITTER SCOUT - NEWS DETECTION")
    print("=" * 60)
    print()
    print("Strategy: Detect volume surges → Search for news → Trade")
    print()

    scout = TwitterScout()

    # Run single scan
    signals = await scout.detect_volume_anomaly()

    if signals:
        print(f"\nFound {len(signals)} volume surges:")
        for s in signals:
            print(f"\n  {s['question']}")
            print(f"  Volume: {s['volume_multiplier']}x normal")
            print(f"  Direction: {s['direction']}")

            # Analyze
            analyzed = await scout.analyze_signal(s)
            print(f"  Recommendation: {analyzed['recommendation']}")
    else:
        print("\nNo significant volume surges detected.")
        print("Markets are quiet - no breaking news likely.")


if __name__ == "__main__":
    asyncio.run(main())
