#!/usr/bin/env python3
"""
GEMINI ANALYZER - AI-Powered News Sentiment Analysis
=====================================================
Uses Google's Gemini 1.5 Flash for fast, cheap sentiment analysis.

Free tier: 15 RPM, 1M tokens/day
Paid: $0.075/1M input tokens (10x cheaper than alternatives)
"""

import asyncio
import aiohttp
import os
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()


# Use gemini-2.0-flash-lite for lower quota usage
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent"


class GeminiAnalyzer:
    """
    Fast, cheap AI sentiment analysis using Gemini 1.5 Flash.
    """

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self._request_count = 0
        self._last_reset = datetime.now(timezone.utc)

    async def analyze_news(self, headline: str, description: str, market_question: str) -> dict:
        """
        Analyze if news is relevant to a market and determine direction.

        Returns:
        {
            "is_relevant": bool,
            "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
            "confidence": 0.0-1.0,
            "reasoning": str,
            "action": "BUY_YES" | "BUY_NO" | "HOLD"
        }
        """
        if not self.api_key:
            return self._fallback_analysis(headline, description)

        prompt = f"""You are a prediction market analyst. Analyze this news for trading.

MARKET QUESTION: {market_question}

NEWS HEADLINE: {headline}

NEWS DESCRIPTION: {description}

Respond ONLY with valid JSON (no markdown, no explanation):
{{
    "is_relevant": true/false,
    "direction": "BULLISH" or "BEARISH" or "NEUTRAL",
    "confidence": 0.0 to 1.0,
    "reasoning": "one sentence explanation",
    "action": "BUY_YES" or "BUY_NO" or "HOLD"
}}

Rules:
- is_relevant: Does this news DIRECTLY affect the market question?
- direction: BULLISH = increases YES probability, BEARISH = increases NO probability
- confidence: How certain are you? (0.5 = uncertain, 0.9 = very confident)
- action: What should a trader do? HOLD if uncertain or irrelevant."""

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GEMINI_API_URL}?key={self.api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1,  # Low temperature for consistent output
                        "maxOutputTokens": 200
                    }
                }

                async with session.post(url, json=payload, timeout=10) as resp:
                    self._request_count += 1

                    if resp.status == 200:
                        data = await resp.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"]

                        # Parse JSON from response
                        # Clean up potential markdown formatting
                        text = text.strip()
                        if text.startswith("```"):
                            text = text.split("```")[1]
                            if text.startswith("json"):
                                text = text[4:]

                        result = json.loads(text.strip())
                        result["model"] = "gemini-1.5-flash"
                        result["analyzed_at"] = datetime.now(timezone.utc).isoformat()
                        return result

                    elif resp.status == 429:
                        print("[GEMINI] Rate limited - using fallback")
                        return self._fallback_analysis(headline, description)
                    else:
                        error = await resp.text()
                        print(f"[GEMINI] Error {resp.status}: {error[:100]}")
                        return self._fallback_analysis(headline, description)

        except json.JSONDecodeError as e:
            print(f"[GEMINI] JSON parse error: {e}")
            return self._fallback_analysis(headline, description)
        except Exception as e:
            print(f"[GEMINI] Error: {e}")
            return self._fallback_analysis(headline, description)

    def _fallback_analysis(self, headline: str, description: str) -> dict:
        """Simple keyword-based fallback when Gemini unavailable."""
        text = f"{headline} {description}".lower()

        bullish = ["wins", "leads", "ahead", "surges", "confirms", "approved", "victory"]
        bearish = ["loses", "behind", "crashes", "denied", "rejected", "fails", "defeat"]

        bull_count = sum(1 for w in bullish if w in text)
        bear_count = sum(1 for w in bearish if w in text)

        if bull_count > bear_count:
            direction = "BULLISH"
            action = "BUY_YES"
        elif bear_count > bull_count:
            direction = "BEARISH"
            action = "BUY_NO"
        else:
            direction = "NEUTRAL"
            action = "HOLD"

        return {
            "is_relevant": True,  # Assume relevant in fallback
            "direction": direction,
            "confidence": 0.5,
            "reasoning": "Fallback keyword analysis (Gemini unavailable)",
            "action": action,
            "model": "fallback"
        }

    async def batch_analyze(self, articles: List[dict], market_question: str) -> List[dict]:
        """Analyze multiple articles for a single market."""
        results = []

        for article in articles[:5]:  # Limit to 5 per market
            result = await self.analyze_news(
                headline=article.get("title", ""),
                description=article.get("description", ""),
                market_question=market_question
            )
            result["headline"] = article.get("title", "")[:80]
            results.append(result)

            # Respect rate limits (15 RPM = 1 every 4 seconds)
            await asyncio.sleep(0.5)

        return results

    def get_consensus(self, analyses: List[dict]) -> dict:
        """Get consensus direction from multiple article analyses."""
        if not analyses:
            return {
                "direction": "NEUTRAL",
                "confidence": 0.0,
                "action": "HOLD",
                "article_count": 0
            }

        # Only count relevant articles
        relevant = [a for a in analyses if a.get("is_relevant", False)]

        if not relevant:
            return {
                "direction": "NEUTRAL",
                "confidence": 0.0,
                "action": "HOLD",
                "article_count": len(analyses),
                "relevant_count": 0
            }

        # Count directions
        bullish = sum(1 for a in relevant if a["direction"] == "BULLISH")
        bearish = sum(1 for a in relevant if a["direction"] == "BEARISH")
        neutral = sum(1 for a in relevant if a["direction"] == "NEUTRAL")

        # Weighted by confidence
        bull_weight = sum(a["confidence"] for a in relevant if a["direction"] == "BULLISH")
        bear_weight = sum(a["confidence"] for a in relevant if a["direction"] == "BEARISH")

        if bull_weight > bear_weight + 0.3:
            direction = "BULLISH"
            action = "BUY_YES"
            confidence = bull_weight / len(relevant)
        elif bear_weight > bull_weight + 0.3:
            direction = "BEARISH"
            action = "BUY_NO"
            confidence = bear_weight / len(relevant)
        else:
            direction = "NEUTRAL"
            action = "HOLD"
            confidence = 0.5

        return {
            "direction": direction,
            "confidence": round(confidence, 2),
            "action": action,
            "article_count": len(analyses),
            "relevant_count": len(relevant),
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral
        }

    async def screen_market(self, question: str, price: float, end_date: str, volume_24h: float) -> dict:
        """
        AI screen: Is this market worth trading on?

        Returns:
            {"approved": bool, "reason": str, "quality_score": 0-10}
        """
        if not self.api_key:
            return {"approved": True, "reason": "No API key - skipping screen", "quality_score": 5}

        prompt = f"""You are a prediction market trader screening markets for short-term spread trading (market making).
You need liquid, active markets where prices move frequently so limit orders get filled quickly.

MARKET: {question}
CURRENT YES PRICE: ${price:.2f}
END DATE: {end_date or 'Unknown'}
24H VOLUME: ${volume_24h:,.0f}

Score this market 1-10 for SHORT-TERM market making (buying low, selling high within hours).

REJECT (score 1-3) if ANY of these apply:
- The outcome is near-impossible or absurd (e.g., BTC hitting $1M, alien contact)
- The market won't see meaningful price movement before resolution
- The market is about a very long-term or speculative event with no near-term catalyst
- The price is stuck and unlikely to move (dead market despite volume)

APPROVE (score 7-10) if:
- High-frequency price movement expected (news-driven, political, sports, earnings)
- Resolution within days or weeks (faster capital turnover)
- Active trading with real price discovery happening

Respond ONLY with valid JSON:
{{"approved":true/false,"reason":"one sentence","quality_score":1-10}}"""

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GEMINI_API_URL}?key={self.api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 100}
                }

                async with session.post(url, json=payload, timeout=10) as resp:
                    self._request_count += 1
                    if resp.status == 200:
                        data = await resp.json()
                        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if text.startswith("```"):
                            text = text.split("```")[1]
                            if text.startswith("json"):
                                text = text[4:]
                        result = json.loads(text.strip())
                        return result
                    else:
                        return {"approved": True, "reason": "API error - allowing by default", "quality_score": 5}

        except Exception as e:
            print(f"[GEMINI] Screen error: {e}")
            return {"approved": True, "reason": f"Screen error: {e}", "quality_score": 5}

    def get_usage_stats(self) -> dict:
        """Get API usage stats."""
        return {
            "requests_today": self._request_count,
            "last_reset": self._last_reset.isoformat()
        }


async def test_gemini():
    """Test Gemini analyzer with sample data."""
    print("=" * 60)
    print("  GEMINI ANALYZER TEST")
    print("=" * 60)
    print()

    analyzer = GeminiAnalyzer()

    if not analyzer.api_key:
        print("ERROR: GEMINI_API_KEY not set in .env")
        return

    # Test cases
    tests = [
        {
            "market": "Will Trump win the 2024 election?",
            "headline": "Trump leads Biden by 5 points in new national poll",
            "description": "A new Reuters poll shows Trump ahead with 48% to Biden's 43%"
        },
        {
            "market": "Will the Seahawks win Super Bowl 2026?",
            "headline": "Seahawks quarterback suffers season-ending injury",
            "description": "Starting QB out for remainder of season after ACL tear"
        },
        {
            "market": "Will Bitcoin hit $100k by 2025?",
            "headline": "Taylor Swift announces new album tour dates",
            "description": "Pop star reveals 50-city world tour starting in March"
        }
    ]

    for test in tests:
        print(f"Market: {test['market']}")
        print(f"News: {test['headline'][:50]}...")

        result = await analyzer.analyze_news(
            headline=test["headline"],
            description=test["description"],
            market_question=test["market"]
        )

        print(f"  Relevant: {result['is_relevant']}")
        print(f"  Direction: {result['direction']}")
        print(f"  Confidence: {result['confidence']:.0%}")
        print(f"  Action: {result['action']}")
        print(f"  Reasoning: {result['reasoning']}")
        print(f"  Model: {result.get('model', 'unknown')}")
        print()

        await asyncio.sleep(1)

    print("=" * 60)
    print(f"Usage: {analyzer.get_usage_stats()}")


if __name__ == "__main__":
    asyncio.run(test_gemini())
