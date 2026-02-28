#!/usr/bin/env python3
"""
GEMINI ANALYZER - AI-Powered News Sentiment Analysis
=====================================================
Uses Google's Gemini 1.5 Flash for fast, cheap sentiment analysis.

Free tier: 15 RPM, 1M tokens/day
Paid: $0.075/1M input tokens (10x cheaper than alternatives)
"""

import aiohttp
import os
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List
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

    async def evaluate_exit(
        self,
        question: str,
        entry_price: float,
        current_price: float,
        hold_hours: float,
        exit_trigger: str,
        best_bid: float,
        best_ask: float,
    ) -> dict:
        """
        AI-driven exit decision. Called before ANY exit to determine if we should
        hold, sell at market, or sell at a specific price.

        exit_trigger: "TIMEOUT" | "STOP_LOSS" | "SELL_FAILED"

        Returns:
            {
                "action": "HOLD" | "SELL",
                "true_probability": 0.0-1.0,
                "sell_price": float (only if action=SELL),
                "reason": str,
            }
        """
        default = {"action": "HOLD", "true_probability": current_price, "reason": "No API key — holding by default"}
        if not self.api_key:
            return default

        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        prompt = f"""You are a prediction market risk manager. The bot is considering exiting a position.

MARKET: {question}
ENTRY PRICE: ${entry_price:.3f} (our cost basis)
CURRENT PRICE: ${current_price:.3f} (market mid)
BEST BID: ${best_bid:.3f} | BEST ASK: ${best_ask:.3f}
UNREALIZED P&L: {pnl_pct:+.1f}%
HOLD TIME: {hold_hours:.1f} hours
EXIT TRIGGER: {exit_trigger}

KEY QUESTION: What is the TRUE probability of this event occurring?
- If true probability > current price → the market is UNDERPRICING this → HOLD (we have edge)
- If true probability < current price → the market is OVERPRICING this → SELL (cut loss)
- If true probability ≈ current price → no edge → SELL at break-even if possible

CONTEXT:
- We bought this as a market maker at ${entry_price:.3f}
- TIMEOUT means our sell order didn't fill in time — NOT an emergency
- STOP_LOSS means price dropped 3%+ — could be temporary dip or real move
- SELL_FAILED means CLOB rejected our sell orders — technical issue, not market issue

CRITICAL SPREAD RULE:
- Bid-ask spread = {((best_ask - best_bid) / max(best_ask, 0.01)) * 100:.0f}%
- If spread > 20%, the orderbook is DEAD — there is no liquidity to exit at a fair price.
  ALWAYS recommend SELL at best_bid when spread > 20%. Holding a position in a dead orderbook
  is pointless — you will be stuck until market resolution. Exit NOW at best_bid.
- Never recommend HOLD when spread > 20%.

Respond ONLY with valid JSON (no markdown):
{{"action":"HOLD","true_probability":0.85,"sell_price":0.83,"reason":"one sentence"}}

action: "HOLD" to keep position, "SELL" to exit
true_probability: your estimate of true probability (0.0-1.0)
sell_price: if SELL, what price to target (use best_bid if urgent, entry_price for break-even)
reason: brief explanation

Be data-driven. If the event is very likely (>80% true prob), holding is usually correct even if the sell didn't fill."""

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GEMINI_API_URL}?key={self.api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 150}
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
                        result.setdefault("action", "HOLD")
                        result.setdefault("true_probability", current_price)
                        result.setdefault("sell_price", entry_price)
                        result.setdefault("reason", "")
                        # Safety: never sell below 90% of entry regardless of AI
                        if result["action"] == "SELL":
                            min_price = entry_price * 0.90
                            if result["sell_price"] < min_price:
                                result["sell_price"] = min_price
                        return result
                    else:
                        return default
        except Exception as e:
            print(f"[GEMINI] Exit eval error: {e}")
            return default

    async def evaluate_exit_with_context(
        self,
        question: str,
        entry_price: float,
        current_price: float,
        hold_hours: float,
        best_bid: float,
        best_ask: float,
        external_context: str = "",
        position_size_usd: float = 0.0,
    ) -> dict:
        """
        Enhanced exit evaluation with external intelligence from the monitor agent.

        Called by ai_position_review.py when the monitor provides WebSearch context
        (polling data, match results, news) that Gemini doesn't have natively.

        Returns:
            {
                "action": "HOLD" | "SELL",
                "true_probability": 0.0-1.0,
                "sell_price": float,
                "reason": str,
                "confidence": 0.0-1.0,
            }
        """
        default = {
            "action": "HOLD", "true_probability": current_price,
            "reason": "No API key — holding by default", "confidence": 0.5,
        }
        if not self.api_key:
            return default

        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        context_section = ""
        if external_context:
            context_section = f"""
EXTERNAL INTELLIGENCE (from real-time web research by monitor agent):
{external_context}

IMPORTANT: The above intelligence is CURRENT and comes from live web searches.
Weight it heavily — it may contain information not yet reflected in the market price."""

        size_section = ""
        if position_size_usd > 0:
            size_section = f"\nPOSITION SIZE: ${position_size_usd:.2f} at risk"

        prompt = f"""You are a prediction market risk manager reviewing a position for the autonomous monitor.

MARKET: {question}
ENTRY PRICE: ${entry_price:.3f} (our cost basis)
CURRENT PRICE: ${current_price:.3f} (market mid)
BEST BID: ${best_bid:.3f} | BEST ASK: ${best_ask:.3f}
UNREALIZED P&L: {pnl_pct:+.1f}%
HOLD TIME: {hold_hours:.1f} hours{size_section}
{context_section}

KEY QUESTION: Given ALL available information (market data + external intelligence),
what is the TRUE probability of this event occurring?

- If true probability > current price → HOLD (we have edge, market hasn't caught up)
- If true probability < current price → SELL (market is overpricing, or we have negative info)
- If true probability ≈ current price → SELL at break-even if possible

Respond ONLY with valid JSON (no markdown):
{{"action":"HOLD","true_probability":0.85,"sell_price":0.83,"reason":"one sentence","confidence":0.8}}

action: "HOLD" to keep position, "SELL" to exit
true_probability: your estimate (0.0-1.0) — factor in the external intelligence
sell_price: if SELL, target price (use best_bid for urgency, entry_price for break-even)
reason: brief explanation referencing the evidence
confidence: how confident you are in your assessment (0.0-1.0)

Be data-driven. External intelligence (polls, results, news) should OVERRIDE generic priors."""

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
                        result.setdefault("action", "HOLD")
                        result.setdefault("true_probability", current_price)
                        result.setdefault("sell_price", entry_price)
                        result.setdefault("reason", "")
                        result.setdefault("confidence", 0.5)
                        # Safety: never sell below 90% of entry
                        if result["action"] == "SELL":
                            min_price = entry_price * 0.90
                            if result["sell_price"] < min_price:
                                result["sell_price"] = min_price
                        return result
                    else:
                        return default
        except Exception as e:
            print(f"[GEMINI] Exit-with-context eval error: {e}")
            return default

    def get_usage_stats(self) -> dict:
        """Get API usage stats."""
        return {
            "requests_today": self._request_count,
            "last_reset": self._last_reset.isoformat()
        }


