#!/usr/bin/env python3
"""
SENTIMENT STREAMER - Background Pre-Caching
============================================
Continuously pre-digests news so lookups are instant.
"""

import asyncio
import aiohttp
import os
from datetime import datetime, timezone
from typing import List, Optional
import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from core.redis_state import get_state


class SentimentStreamer:
    """
    Background process that pre-caches sentiment analysis.

    HOW IT WORKS:
    1. Scans active Polymarket markets
    2. Extracts entities (Trump, Seahawks, Bitcoin, etc.)
    3. Monitors news for those entities
    4. When news hits → signals trading opportunity
    """

    NEWS_API_URL = "https://newsapi.org/v2/everything"
    GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"

    def __init__(self):
        self.state = get_state()
        self.api_key = os.getenv("NEWS_API_KEY", "")
        self.hot_topics = set()
        self.market_entities = {}  # entity -> [market_ids]
        self.running = False

    async def discover_market_entities(self) -> dict:
        """
        Scan Polymarket for active markets and extract entities to monitor.
        Returns: {entity: [condition_ids that care about this entity]}
        """
        entities = {}

        try:
            async with aiohttp.ClientSession() as session:
                params = {"limit": 100, "active": "true", "closed": "false"}
                async with session.get(self.GAMMA_API_URL, params=params, timeout=15) as resp:
                    if resp.status != 200:
                        return entities

                    markets = await resp.json()

                    # Filter to markets with liquidity
                    active = [m for m in markets if float(m.get("liquidityNum") or 0) > 5000]

                    for m in active:
                        question = m.get("question", "")
                        condition_id = m.get("conditionId", "")

                        # Extract named entities (capitalized words)
                        words = question.replace("?", "").replace("$", "").split()
                        stopwords = {"Will", "The", "What", "How", "Who", "When", "Before", "After"}

                        for word in words:
                            clean = word.strip(".,!?()[]")
                            if len(clean) > 2 and clean[0].isupper() and clean not in stopwords:
                                if clean not in entities:
                                    entities[clean] = []
                                if condition_id not in entities[clean]:
                                    entities[clean].append(condition_id)

                    print(f"[SENTIMENT] Discovered {len(entities)} entities from {len(active)} markets")

        except Exception as e:
            print(f"[SENTIMENT] Discovery error: {e}")

        self.market_entities = entities
        return entities

    async def fetch_news(self, query: str, hours_back: int = 12) -> List[dict]:
        """Fetch recent news articles for a topic."""
        if not self.api_key:
            # Fallback: no API key, skip news
            return []

        from datetime import timedelta
        from_date = (datetime.utcnow() - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%S")

        params = {
            "q": query,
            "from": from_date,
            "sortBy": "relevancy",
            "language": "en",
            "pageSize": "5",
            "apiKey": self.api_key
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.NEWS_API_URL, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        articles = data.get("articles", [])
                        return [
                            {
                                "title": a.get("title", ""),
                                "source": a.get("source", {}).get("name", ""),
                                "published": a.get("publishedAt", ""),
                                "description": a.get("description", "")[:200] if a.get("description") else ""
                            }
                            for a in articles[:5]
                        ]
        except Exception as e:
            print(f"[SENTIMENT] News fetch error: {e}")
        return []

    def analyze_sentiment(self, topic: str, articles: List[dict]) -> dict:
        """
        Quick sentiment analysis without LLM.
        Upgrade to Claude API for production.
        """
        if not articles:
            return {
                "topic": topic,
                "direction": "NEUTRAL",
                "confidence": 0.3,
                "sources": 0,
                "cached_at": datetime.now(timezone.utc).isoformat()
            }

        # Simple keyword-based sentiment (fast)
        positive_words = ['win', 'success', 'gain', 'rise', 'up', 'victory', 'ahead', 'leads', 'confirm']
        negative_words = ['lose', 'fail', 'drop', 'down', 'defeat', 'behind', 'crash', 'reject', 'deny']

        text = ' '.join([
            f"{a['title']} {a['description']}"
            for a in articles
        ]).lower()

        pos_count = sum(1 for w in positive_words if w in text)
        neg_count = sum(1 for w in negative_words if w in text)

        if pos_count > neg_count + 2:
            direction = "BULLISH"
            confidence = min(0.9, 0.5 + (pos_count - neg_count) * 0.1)
        elif neg_count > pos_count + 2:
            direction = "BEARISH"
            confidence = min(0.9, 0.5 + (neg_count - pos_count) * 0.1)
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return {
            "topic": topic,
            "direction": direction,
            "confidence": confidence,
            "sources": len(articles),
            "headlines": [a["title"][:80] for a in articles[:3]],
            "cached_at": datetime.now(timezone.utc).isoformat()
        }

    def extract_topics(self, question: str) -> List[str]:
        """Extract key topics from market question."""
        # Remove common words
        stopwords = {
            'will', 'the', 'be', 'a', 'an', 'in', 'on', 'by', 'to', 'of',
            'as', 'is', 'for', 'at', 'from', 'with', 'that', 'this', 'or',
            'and', 'if', 'than', 'result', 'after', 'before', 'during'
        }

        words = question.lower().replace('?', '').replace("'", '').split()
        key_words = [w for w in words if w not in stopwords and len(w) > 2]

        topics = []

        # Full topic
        if len(key_words) >= 2:
            topics.append(' '.join(key_words[:4]))

        # Entity extraction (capitalized words from original)
        entities = [w for w in question.split() if w[0].isupper() and len(w) > 2]
        if entities:
            topics.append(' '.join(entities[:3]))

        return topics[:2]  # Max 2 topics per question

    async def stream(self, interval: float = 30.0):
        """Main streaming loop - continuously pre-cache sentiment."""
        self.running = True
        print("[SENTIMENT] Streamer started")
        print("[SENTIMENT] Strategy: Discover markets → Extract entities → Monitor news")

        cycle = 0
        while self.running:
            try:
                cycle += 1

                # Every 10 cycles, rediscover market entities
                if cycle % 10 == 1:
                    await self.discover_market_entities()
                    # Add discovered entities to hot topics
                    self.hot_topics.update(self.market_entities.keys())

                # Also add topics from detected opportunities
                opps = self.state.get_opportunities()
                for opp in opps:
                    question = opp.get("question", "")
                    topics = self.extract_topics(question)
                    self.hot_topics.update(topics)

                # Pre-cache sentiment for hot topics
                processed = 0
                for topic in list(self.hot_topics)[:20]:
                    # Skip if already cached (10 min TTL)
                    cached = self.state.get_sentiment(topic)
                    if cached:
                        continue

                    # Fetch and analyze
                    articles = await self.fetch_news(topic)
                    sentiment = self.analyze_sentiment(topic, articles)

                    # Check if this is BREAKING news (< 1 hour old)
                    if articles:
                        sentiment["is_breaking"] = self._is_breaking_news(articles)

                    self.state.set_sentiment(topic, sentiment, ttl=600)

                    processed += 1
                    breaking = "🚨 BREAKING" if sentiment.get("is_breaking") else ""
                    print(f"[SENTIMENT] {breaking} '{topic}' -> {sentiment['direction']} ({sentiment['sources']} sources)")

                    # If breaking news found, check which markets it affects
                    if sentiment.get("is_breaking") and topic in self.market_entities:
                        affected_markets = self.market_entities[topic]
                        print(f"[SENTIMENT] ⚡ Affects {len(affected_markets)} markets!")

                    # Rate limit NewsAPI
                    await asyncio.sleep(1)

                if processed > 0:
                    self.state.incr_metric("sentiment_cached", processed)

            except Exception as e:
                print(f"[SENTIMENT] Error: {e}")

            await asyncio.sleep(interval)

    def _is_breaking_news(self, articles: List[dict]) -> bool:
        """Check if any article is less than 1 hour old."""
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)

        for article in articles:
            published_str = article.get("published", "")
            if published_str:
                try:
                    # Parse ISO format
                    published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                    if published > one_hour_ago:
                        return True
                except:
                    pass
        return False

    def stop(self):
        self.running = False

    async def get_instant_sentiment(self, question: str) -> Optional[dict]:
        """
        Instant sentiment lookup (no API call).
        Returns cached sentiment if available.
        """
        topics = self.extract_topics(question)
        for topic in topics:
            cached = self.state.get_sentiment(topic)
            if cached:
                return cached
        return None


async def main():
    streamer = SentimentStreamer()
    try:
        await streamer.stream()
    except KeyboardInterrupt:
        streamer.stop()
        print("[SENTIMENT] Streamer stopped")


if __name__ == "__main__":
    asyncio.run(main())
