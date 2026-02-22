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
        self._screen_cache: Dict[str, tuple] = {}  # {condition_id: (result, timestamp)}

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

    def _get_cached(self, condition_id: str) -> Optional[dict]:
        """Return cached screen result if still valid (1-hour TTL)."""
        if condition_id in self._screen_cache:
            result, ts = self._screen_cache[condition_id]
            if (datetime.now(timezone.utc) - ts).total_seconds() < 3600:
                cached = dict(result)
                cached["cached"] = True
                return cached
            del self._screen_cache[condition_id]
        return None

    def _set_cache(self, condition_id: str, result: dict):
        """Cache a screen result with current timestamp."""
        self._screen_cache[condition_id] = (result, datetime.now(timezone.utc))

    async def screen_market(self, question: str, price: float, end_date: str, volume_24h: float) -> dict:
        """Basic AI screen (legacy). Use deep_screen_market() for the full pipeline."""
        return await self.deep_screen_market(
            question=question, price=price, end_date=end_date,
            volume_24h=volume_24h, spread_pct=0.0, liquidity=0.0,
            best_bid=0.0, best_ask=0.0, news_headlines=[], days_to_resolve=0,
        )

    async def deep_screen_market(
        self,
        question: str,
        price: float,
        end_date: str,
        volume_24h: float,
        spread_pct: float,
        liquidity: float,
        best_bid: float,
        best_ask: float,
        news_headlines: List[str],
        days_to_resolve: int,
        condition_id: str = "",
    ) -> dict:
        """
        Deep AI screen with market context, news, and spread recommendation.

        Returns:
            {
                "approved": bool,
                "quality_score": 1-10,
                "reason": str,
                "recommended_spread_pct": float,
                "catalyst_expected": bool,
                "sector": str,
                "cached": bool,
            }
        """
        # Check cache first
        if condition_id:
            cached = self._get_cached(condition_id)
            if cached is not None:
                return cached

        default_result = {
            "approved": True, "quality_score": 5, "reason": "No API key - skipping screen",
            "recommended_spread_pct": 0.02, "catalyst_expected": False,
            "sector": "other", "cached": False,
        }

        if not self.api_key:
            return default_result

        news_section = "No recent news found."
        if news_headlines:
            bullets = "\n".join(f"- {h}" for h in news_headlines[:3])
            news_section = bullets

        prompt = f"""You are a prediction market analyst screening markets for spread trading.

MARKET: {question}
CURRENT PRICE: ${price:.2f} | BID: ${best_bid:.2f} | ASK: ${best_ask:.2f}
SPREAD: {spread_pct:.1%} | LIQUIDITY: ${liquidity:,.0f}
24H VOLUME: ${volume_24h:,.0f} | RESOLVES IN: {days_to_resolve} days
END DATE: {end_date or 'Unknown'}

RECENT NEWS:
{news_section}

EMPIRICAL INTELLIGENCE (from 88.5M historical Polymarket trades, $12B volume):
- Tokens priced 0.55-0.65 are systematically UNDERPRICED by 13-17pp (Kelly +29-48%)
- Tokens priced 0.35-0.45 are OVERPRICED by 10-14pp (Kelly -17 to -22%) — AVOID
- Price 0.70 is a TRAP: looks close to sweet spot but has -19% Kelly
- Economics and politics markets have strongest edge (+4-5% Kelly)
- Crypto markets have NEGATIVE edge (-1.53% Kelly)
- Optimal resolution: 15-30 days (Kelly +5.51%). 0-1 day is negative (insider-dominated)
- NegRisk (multi-outcome) markets have 12x more mispricing than simple binary markets

EVALUATE:
1. Is this market liquid and actively traded? (dead markets = stuck positions)
2. Is the outcome reasonable and near-term? (absurd outcomes = no fills)
3. Is the current price justified by fundamentals? (a 92% YES on a near-certain outcome is CORRECT, not mispriced)
4. Will news catalysts drive price movement? (no movement = no opportunity)
5. What spread should I target? (tighter = faster fill, wider = more profit)
6. Does the price fall in the empirical sweet spot (0.55-0.65)?

Respond ONLY with valid JSON (no markdown):
{{"approved":true/false,"quality_score":1,"reason":"one sentence","recommended_spread_pct":0.02,"catalyst_expected":true/false,"sector":"crypto"}}

sector must be one of: crypto, politics, sports, entertainment, science, economics, other

REJECT (1-4): price 0.35-0.45 (death zone), crypto sector, absurd outcome, no liquidity, >30d, <2d, no catalysts
MARGINAL (5-6): tradeable but low confidence, price outside sweet spot
GOOD (7-8): active market, upcoming catalyst, politics/economics, price 0.50-0.70
EXCELLENT (9-10): price 0.55-0.65, politics/economics, 15-30d resolution, clear catalyst"""

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GEMINI_API_URL}?key={self.api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200}
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
                        # Ensure all fields present with defaults
                        result.setdefault("approved", True)
                        result.setdefault("quality_score", 5)
                        result.setdefault("reason", "")
                        result.setdefault("recommended_spread_pct", 0.02)
                        result.setdefault("catalyst_expected", False)
                        result.setdefault("sector", "other")
                        result["cached"] = False
                        # Clamp spread recommendation
                        result["recommended_spread_pct"] = max(0.01, min(0.10, result["recommended_spread_pct"]))
                        # Cache the result
                        if condition_id:
                            self._set_cache(condition_id, result)
                        return result
                    elif resp.status == 429:
                        print("[GEMINI] Rate limited - using default")
                        return default_result
                    else:
                        error = await resp.text()
                        print(f"[GEMINI] Error {resp.status}: {error[:100]}")
                        return default_result

        except json.JSONDecodeError as e:
            print(f"[GEMINI] JSON parse error: {e}")
            return default_result
        except Exception as e:
            print(f"[GEMINI] Screen error: {e}")
            return default_result

    async def evaluate_reentry(
        self,
        question: str,
        current_price: float,
        stop_count: int,
        volume_24h: float,
    ) -> dict:
        """
        Ask AI whether re-entering a previously stopped market is wise.

        Called when a market has 1+ recent stops but hasn't hit the circuit breaker yet.
        Returns {"reenter": bool, "reason": str}.
        """
        default = {"reenter": False, "reason": "No API key"}
        if not self.api_key:
            return default

        prompt = f"""You are a risk manager for a prediction market trading bot.

This market was STOPPED OUT {stop_count} time(s) in the last 24 hours (price dropped >3% after entry).

MARKET: {question}
CURRENT PRICE: ${current_price:.2f}
24H VOLUME: ${volume_24h:,.0f}
STOP COUNT (24h): {stop_count}

Should the bot RE-ENTER this market? Consider:
1. Was the stop likely a temporary dip or a fundamental price collapse?
2. Is re-entering likely to result in another stop loss?
3. Is there enough volume for the market to recover?

Respond ONLY with valid JSON (no markdown):
{{"reenter":true/false,"reason":"one sentence"}}

Be CONSERVATIVE. If in doubt, say false. Repeated stops usually mean the market is moving against us."""

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
                        result.setdefault("reenter", False)
                        result.setdefault("reason", "")
                        return result
                    else:
                        return default
        except Exception as e:
            print(f"[GEMINI] Reentry eval error: {e}")
            return default

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
