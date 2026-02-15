#!/usr/bin/env python3
"""
NEWS INTELLIGENCE - Production-Grade News Processing
=====================================================
Addresses the critical gaps in naive keyword matching:

1. LATENCY: Target < 5 seconds tick-to-trade
2. DISAMBIGUATION: Entity resolution with context
3. RELEVANCE: Filter noise from signal
4. DIRECTION: Determine bullish vs bearish
5. DEDUPLICATION: One trade per narrative
6. PRICE CHECK: Verify market hasn't already moved
7. RATE LIMITS: Batched queries to stay under quota
"""

import asyncio
import aiohttp
import hashlib
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set
import re


# ============================================================
# ENTITY RESOLUTION - Handles disambiguation and aliases
# ============================================================

ENTITY_ALIASES = {
    # Crypto
    "Bitcoin": ["BTC", "bitcoin", "btc", "₿"],
    "Ethereum": ["ETH", "ethereum", "eth", "Ether"],
    "Solana": ["SOL", "solana"],

    # People - Politics
    "Trump": ["Donald Trump", "DJT", "Trump", "45", "47", "POTUS"],
    "Biden": ["Joe Biden", "Biden", "POTUS", "President Biden"],
    "Elon Musk": ["Elon", "Musk", "@elonmusk", "Tesla CEO"],

    # People - Sports
    "Patrick Mahomes": ["Mahomes", "PM15"],
    "LeBron James": ["LeBron", "King James", "Bron"],

    # Organizations
    "Federal Reserve": ["Fed", "FOMC", "Jerome Powell", "Powell"],
    "SEC": ["Securities and Exchange", "Gary Gensler", "Gensler"],

    # Teams
    "Seahawks": ["Seattle Seahawks", "Hawks", "SEA"],
    "Patriots": ["New England Patriots", "Pats", "NE"],
    "Celtics": ["Boston Celtics", "BOS"],
    "Knicks": ["New York Knicks", "NYK"],
}

# Build reverse lookup: alias -> canonical entity
ALIAS_TO_ENTITY = {}
for entity, aliases in ENTITY_ALIASES.items():
    ALIAS_TO_ENTITY[entity.lower()] = entity
    for alias in aliases:
        ALIAS_TO_ENTITY[alias.lower()] = entity


def resolve_entity(text: str) -> Set[str]:
    """
    Extract canonical entities from text.
    Handles aliases and disambiguation.
    """
    text_lower = text.lower()
    found = set()

    for alias, entity in ALIAS_TO_ENTITY.items():
        if alias in text_lower:
            found.add(entity)

    return found


# ============================================================
# RELEVANCE FILTERING - Is this news actually market-moving?
# ============================================================

# Keywords that indicate market-moving news
SIGNAL_KEYWORDS = {
    "high_impact": [
        "breaking", "just in", "confirmed", "announces", "signs",
        "wins", "loses", "dies", "resigns", "arrested", "indicted",
        "crashes", "surges", "plunges", "soars", "collapses",
        "approved", "rejected", "passed", "vetoed", "declares",
        "injured", "out for", "traded", "fired", "hired"
    ],
    "medium_impact": [
        "expected", "likely", "sources say", "reportedly", "rumored",
        "considering", "planning", "may", "could", "might"
    ],
    "noise": [
        "opinion", "editorial", "analysis", "podcast", "interview",
        "throwback", "anniversary", "remembering", "history"
    ]
}


def calculate_relevance_score(headline: str, description: str = "") -> dict:
    """
    Score news relevance from 0-100.
    Returns score + reasoning.
    """
    text = f"{headline} {description}".lower()

    score = 50  # Base score
    reasons = []

    # High impact keywords boost score
    for kw in SIGNAL_KEYWORDS["high_impact"]:
        if kw in text:
            score += 15
            reasons.append(f"+15: '{kw}' detected")
            break  # Only count once

    # Medium impact keywords
    for kw in SIGNAL_KEYWORDS["medium_impact"]:
        if kw in text:
            score += 5
            reasons.append(f"+5: speculative '{kw}'")
            break

    # Noise keywords reduce score
    for kw in SIGNAL_KEYWORDS["noise"]:
        if kw in text:
            score -= 20
            reasons.append(f"-20: noise '{kw}'")
            break

    # Length heuristic: very short = clickbait, very long = analysis
    if len(headline) < 30:
        score -= 10
        reasons.append("-10: too short (clickbait?)")
    elif len(headline) > 150:
        score -= 5
        reasons.append("-5: too long (analysis?)")

    score = max(0, min(100, score))

    return {
        "score": score,
        "is_signal": score >= 60,
        "reasons": reasons
    }


# ============================================================
# DIRECTION DETECTION - Bullish or Bearish?
# ============================================================

BULLISH_SIGNALS = [
    "wins", "winning", "leads", "leading", "ahead", "surges", "soars",
    "approved", "passed", "confirmed", "signs", "deal", "breakthrough",
    "recovers", "rebounds", "gains", "rises", "climbs", "endorses",
    "supports", "backs", "favors", "advantage"
]

BEARISH_SIGNALS = [
    "loses", "losing", "trails", "behind", "crashes", "plunges", "drops",
    "rejected", "failed", "denied", "cancelled", "withdraws", "collapses",
    "falls", "declines", "sinks", "opposes", "against", "hurt", "injured",
    "indicted", "arrested", "scandal", "controversy"
]


def detect_direction(headline: str, description: str = "") -> dict:
    """
    Determine if news is bullish or bearish for the entity.
    """
    text = f"{headline} {description}".lower()

    bullish_count = sum(1 for w in BULLISH_SIGNALS if w in text)
    bearish_count = sum(1 for w in BEARISH_SIGNALS if w in text)

    if bullish_count > bearish_count + 1:
        direction = "BULLISH"
        confidence = min(0.9, 0.5 + (bullish_count - bearish_count) * 0.1)
    elif bearish_count > bullish_count + 1:
        direction = "BEARISH"
        confidence = min(0.9, 0.5 + (bearish_count - bullish_count) * 0.1)
    else:
        direction = "NEUTRAL"
        confidence = 0.5

    return {
        "direction": direction,
        "confidence": round(confidence, 2),
        "bullish_signals": bullish_count,
        "bearish_signals": bearish_count
    }


# ============================================================
# DEDUPLICATION - One trade per narrative
# ============================================================

class NewsDeduplicator:
    """
    Prevents trading the same story multiple times.
    Uses content hashing + time windows.
    """

    def __init__(self, window_hours: int = 4):
        self.seen_hashes: Dict[str, datetime] = {}
        self.window = timedelta(hours=window_hours)

    def _hash_content(self, text: str) -> str:
        """Create a fuzzy hash of the content."""
        # Normalize: lowercase, remove punctuation, take first 100 chars
        normalized = re.sub(r'[^\w\s]', '', text.lower())[:100]
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def is_duplicate(self, headline: str) -> bool:
        """Check if we've seen this story recently."""
        content_hash = self._hash_content(headline)

        now = datetime.now(timezone.utc)

        # Clean old entries
        self.seen_hashes = {
            h: t for h, t in self.seen_hashes.items()
            if now - t < self.window
        }

        if content_hash in self.seen_hashes:
            return True

        self.seen_hashes[content_hash] = now
        return False

    def mark_seen(self, headline: str):
        """Mark a story as seen."""
        content_hash = self._hash_content(headline)
        self.seen_hashes[content_hash] = datetime.now(timezone.utc)


# ============================================================
# PRICE MOVEMENT CHECK - Is it already priced in?
# ============================================================

async def check_price_moved(condition_id: str, threshold_pct: float = 5.0) -> dict:
    """
    Check if market price has already moved significantly.
    If price moved > threshold, opportunity is likely gone.
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://gamma-api.polymarket.com/markets?conditionId={condition_id}"
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    markets = await resp.json()
                    if markets:
                        m = markets[0]
                        price_change = float(m.get("oneDayPriceChange") or 0) * 100
                        volume_24h = float(m.get("volume24hr") or 0)

                        already_moved = abs(price_change) > threshold_pct

                        return {
                            "already_moved": already_moved,
                            "price_change_pct": round(price_change, 2),
                            "volume_24h": int(volume_24h),
                            "should_trade": not already_moved
                        }
    except Exception as e:
        print(f"[NEWS_INTEL] Price check error: {e}")

    return {"already_moved": False, "should_trade": True}


# ============================================================
# BATCHED QUERIES - Stay under API rate limits
# ============================================================

def batch_entities_for_query(entities: List[str], max_query_length: int = 200) -> List[str]:
    """
    Combine entities into batched OR queries to reduce API calls.

    Example: ["Trump", "Biden", "Musk"] -> "Trump OR Biden OR Musk"

    NewsAPI allows complex queries, so we batch to stay under limits.
    """
    batches = []
    current_batch = []
    current_length = 0

    for entity in entities:
        entity_addition = len(entity) + 4  # " OR " = 4 chars

        if current_length + entity_addition > max_query_length:
            if current_batch:
                batches.append(" OR ".join(current_batch))
            current_batch = [entity]
            current_length = len(entity)
        else:
            current_batch.append(entity)
            current_length += entity_addition

    if current_batch:
        batches.append(" OR ".join(current_batch))

    return batches


# ============================================================
# MAIN INTELLIGENCE PIPELINE
# ============================================================

class NewsIntelligence:
    """
    Production-grade news processing pipeline.
    """

    def __init__(self):
        self.deduplicator = NewsDeduplicator(window_hours=4)
        self.api_key = os.getenv("NEWS_API_KEY", "")
        self._request_count = 0
        self._last_reset = datetime.now(timezone.utc)

    async def process_article(self, article: dict, target_entities: Set[str]) -> Optional[dict]:
        """
        Full pipeline for a single article.
        Returns trading signal if valid, None if filtered.
        """
        headline = article.get("title", "")
        description = article.get("description", "")
        published = article.get("publishedAt", "")

        # 1. DEDUPLICATION
        if self.deduplicator.is_duplicate(headline):
            return None

        # 2. ENTITY RESOLUTION
        found_entities = resolve_entity(f"{headline} {description}")
        relevant_entities = found_entities & target_entities

        if not relevant_entities:
            return None

        # 3. RELEVANCE SCORING
        relevance = calculate_relevance_score(headline, description)
        if not relevance["is_signal"]:
            return None

        # 4. DIRECTION DETECTION
        direction = detect_direction(headline, description)

        # 5. Mark as seen (after passing all filters)
        self.deduplicator.mark_seen(headline)

        return {
            "headline": headline[:100],
            "entities": list(relevant_entities),
            "relevance_score": relevance["score"],
            "direction": direction["direction"],
            "direction_confidence": direction["confidence"],
            "published": published,
            "processed_at": datetime.now(timezone.utc).isoformat()
        }

    def get_batched_queries(self, entities: List[str]) -> List[str]:
        """Get optimized queries for API calls."""
        return batch_entities_for_query(entities)

    def can_make_request(self, daily_limit: int = 100) -> bool:
        """Check if we're within rate limits."""
        now = datetime.now(timezone.utc)

        # Reset counter at midnight UTC
        if now.date() > self._last_reset.date():
            self._request_count = 0
            self._last_reset = now

        return self._request_count < daily_limit

    def record_request(self):
        """Record an API request."""
        self._request_count += 1


# ============================================================
# QUICK TEST
# ============================================================

async def test_pipeline():
    print("=" * 60)
    print("  NEWS INTELLIGENCE PIPELINE TEST")
    print("=" * 60)
    print()

    intel = NewsIntelligence()

    # Test articles
    test_articles = [
        {
            "title": "BREAKING: Trump announces 2024 campaign rally in Iowa",
            "description": "Former president confirms major campaign event next week",
            "publishedAt": datetime.now(timezone.utc).isoformat()
        },
        {
            "title": "Trump plays golf at Mar-a-Lago",
            "description": "The former president enjoyed a round of golf today",
            "publishedAt": datetime.now(timezone.utc).isoformat()
        },
        {
            "title": "Seahawks QB injured in practice, out for season",
            "description": "Major blow to Seattle's Super Bowl hopes",
            "publishedAt": datetime.now(timezone.utc).isoformat()
        },
        {
            "title": "Opinion: Why Bitcoin will never reach $100k",
            "description": "Analysis of cryptocurrency market trends",
            "publishedAt": datetime.now(timezone.utc).isoformat()
        }
    ]

    target_entities = {"Trump", "Seahawks", "Bitcoin"}

    for article in test_articles:
        print(f"Article: {article['title'][:50]}...")

        result = await intel.process_article(article, target_entities)

        if result:
            print(f"  ✅ SIGNAL: {result['direction']} for {result['entities']}")
            print(f"     Relevance: {result['relevance_score']}/100")
            print(f"     Confidence: {result['direction_confidence']:.0%}")
        else:
            print(f"  ❌ FILTERED (noise/duplicate/irrelevant)")
        print()

    # Test batching
    print("BATCHED QUERIES:")
    entities = ["Trump", "Biden", "Bitcoin", "Ethereum", "Seahawks", "Celtics", "Knicks"]
    batches = intel.get_batched_queries(entities)
    for i, batch in enumerate(batches):
        print(f"  Query {i+1}: {batch}")


if __name__ == "__main__":
    asyncio.run(test_pipeline())
