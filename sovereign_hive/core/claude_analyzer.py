#!/usr/bin/env python3
"""
CLAUDE ANALYZER - AI-Powered News Sentiment Analysis
=====================================================
Uses Claude 3.5 Haiku for fast, cheap sentiment analysis.

Pricing: $0.25/1M input, $1.25/1M output
Estimated cost: ~$0.0001 per news article (~500 tokens)

IMPORTANT: Be conservative with API calls to stay under budget!
"""

import asyncio
import aiohttp
import os
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"


class ClaudeAnalyzer:
    """
    Fast, cheap AI sentiment analysis using Claude 3.5 Haiku.
    """

    def __init__(self):
        self.api_key = os.getenv("CLAUDE_API_KEY", "")
        self._request_count = 0
        self._last_reset = datetime.now(timezone.utc)
        self._daily_limit = 50  # Conservative limit to save budget

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

        # Check daily limit to save budget
        if self._request_count >= self._daily_limit:
            print(f"[CLAUDE] Daily limit reached ({self._daily_limit}) - using fallback")
            return self._fallback_analysis(headline, description)

        prompt = f"""Analyze this news for a prediction market trade.

MARKET: {market_question}
HEADLINE: {headline}
DESCRIPTION: {description[:200]}

Respond with ONLY valid JSON:
{{"is_relevant":true/false,"direction":"BULLISH"/"BEARISH"/"NEUTRAL","confidence":0.0-1.0,"reasoning":"one sentence","action":"BUY_YES"/"BUY_NO"/"HOLD"}}"""

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                payload = {
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 150,  # Keep response short to save tokens
                    "messages": [{"role": "user", "content": prompt}]
                }

                async with session.post(CLAUDE_API_URL, headers=headers, json=payload, timeout=15) as resp:
                    self._request_count += 1

                    if resp.status == 200:
                        data = await resp.json()
                        text = data["content"][0]["text"].strip()

                        # Parse JSON from response
                        if text.startswith("```"):
                            text = text.split("```")[1]
                            if text.startswith("json"):
                                text = text[4:]

                        result = json.loads(text.strip())
                        result["model"] = "claude-3.5-haiku"
                        result["analyzed_at"] = datetime.now(timezone.utc).isoformat()
                        return result

                    elif resp.status == 429:
                        print("[CLAUDE] Rate limited - using fallback")
                        return self._fallback_analysis(headline, description)
                    else:
                        error = await resp.text()
                        print(f"[CLAUDE] Error {resp.status}: {error[:100]}")
                        return self._fallback_analysis(headline, description)

        except json.JSONDecodeError as e:
            print(f"[CLAUDE] JSON parse error: {e}")
            return self._fallback_analysis(headline, description)
        except Exception as e:
            print(f"[CLAUDE] Error: {e}")
            return self._fallback_analysis(headline, description)

    def _fallback_analysis(self, headline: str, description: str) -> dict:
        """Simple keyword-based fallback when Claude unavailable."""
        text = f"{headline} {description}".lower()

        bullish = ["wins", "leads", "ahead", "surges", "confirms", "approved", "victory", "gains"]
        bearish = ["loses", "behind", "crashes", "denied", "rejected", "fails", "defeat", "injured"]

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
            "is_relevant": True,
            "direction": direction,
            "confidence": 0.5,
            "reasoning": "Fallback keyword analysis (Claude unavailable)",
            "action": action,
            "model": "fallback"
        }

    async def batch_analyze(self, articles: List[dict], market_question: str) -> List[dict]:
        """Analyze multiple articles for a single market."""
        results = []

        for article in articles[:3]:  # Limit to 3 per market to save budget
            result = await self.analyze_news(
                headline=article.get("title", ""),
                description=article.get("description", ""),
                market_question=market_question
            )
            result["headline"] = article.get("title", "")[:80]
            results.append(result)

            # Small delay between requests
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

        relevant = [a for a in analyses if a.get("is_relevant", False)]

        if not relevant:
            return {
                "direction": "NEUTRAL",
                "confidence": 0.0,
                "action": "HOLD",
                "article_count": len(analyses),
                "relevant_count": 0
            }

        bullish = sum(1 for a in relevant if a["direction"] == "BULLISH")
        bearish = sum(1 for a in relevant if a["direction"] == "BEARISH")

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
            "bearish_count": bearish
        }

    def get_usage_stats(self) -> dict:
        """Get API usage stats."""
        return {
            "requests_today": self._request_count,
            "daily_limit": self._daily_limit,
            "remaining": self._daily_limit - self._request_count,
            "last_reset": self._last_reset.isoformat()
        }


async def test_claude():
    """Test Claude analyzer with ONE sample (to save budget)."""
    print("=" * 60)
    print("  CLAUDE ANALYZER TEST (1 call only)")
    print("=" * 60)
    print()

    analyzer = ClaudeAnalyzer()

    if not analyzer.api_key:
        print("ERROR: CLAUDE_API_KEY not set in .env")
        return

    # Single test to save budget
    test = {
        "market": "Will Trump win the 2024 election?",
        "headline": "Trump leads Biden by 5 points in new national poll",
        "description": "A new Reuters poll shows Trump ahead with 48% to Biden's 43%"
    }

    print(f"Market: {test['market']}")
    print(f"News: {test['headline']}")

    result = await analyzer.analyze_news(
        headline=test["headline"],
        description=test["description"],
        market_question=test["market"]
    )

    print(f"\nResult:")
    print(f"  Relevant: {result['is_relevant']}")
    print(f"  Direction: {result['direction']}")
    print(f"  Confidence: {result['confidence']:.0%}")
    print(f"  Action: {result['action']}")
    print(f"  Reasoning: {result['reasoning']}")
    print(f"  Model: {result.get('model', 'unknown')}")

    print()
    print("=" * 60)
    print(f"Usage: {analyzer.get_usage_stats()}")
    print("Cost estimate: ~$0.0001 (500 tokens)")


if __name__ == "__main__":
    asyncio.run(test_claude())
