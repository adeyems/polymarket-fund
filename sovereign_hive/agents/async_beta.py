#!/usr/bin/env python3
"""
ASYNC BETA ANALYST - Instant Sentiment Vetting
==============================================
Uses pre-cached sentiment for instant decisions.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from core.redis_state import get_state
from agents.sentiment_streamer import SentimentStreamer


class AsyncBetaAnalyst:
    """
    Instant vetting using pre-cached sentiment.
    No blocking LLM calls in the hot path.
    """

    def __init__(self):
        self.state = get_state()
        self.sentiment = SentimentStreamer()
        self.running = False

    async def analyze(self, opp: dict) -> dict:
        """
        Analyze opportunity using cached sentiment.
        Returns verdict in < 100ms.
        """
        anomaly_type = opp.get("anomaly_type", "")
        price = opp.get("best_ask", 0)
        spread = opp.get("spread_pct", 0)
        price_change = opp.get("price_change_1d", 0)
        question = opp.get("question", "")

        verdict = "PENDING"
        reasoning = ""
        confidence = 0.5

        # === INSTANT SENTIMENT LOOKUP ===
        cached_sentiment = await self.sentiment.get_instant_sentiment(question)
        sentiment_boost = 0

        if cached_sentiment:
            if cached_sentiment["direction"] == "BULLISH":
                sentiment_boost = cached_sentiment["confidence"] * 0.2
            elif cached_sentiment["direction"] == "BEARISH":
                sentiment_boost = -cached_sentiment["confidence"] * 0.2

        # === RULE-BASED ANALYSIS ===

        if anomaly_type == "ARBITRAGE":
            if price >= 0.995 and spread < 0.5:
                verdict = "VETTED"
                confidence = 0.95 + sentiment_boost
                reasoning = f"Near-certain at ${price:.3f}, tight spread"
            elif price >= 0.98 and spread < 1.0:
                verdict = "VETTED"
                confidence = 0.85 + sentiment_boost
                reasoning = f"High prob at ${price:.3f}"
            else:
                verdict = "REJECTED"
                confidence = 0.7
                reasoning = f"Spread too wide ({spread:.1f}%)"

        elif anomaly_type == "DIP_BUY":
            if abs(price_change) > 50:
                verdict = "REJECTED"
                confidence = 0.6
                reasoning = f"Massive {price_change:.0f}% move - fundamental shift"
            elif cached_sentiment and cached_sentiment["direction"] == "BULLISH":
                verdict = "VETTED"
                confidence = 0.7 + sentiment_boost
                reasoning = f"Dip with bullish sentiment ({cached_sentiment['sources']} sources)"
            else:
                verdict = "PENDING"
                confidence = 0.5
                reasoning = "Dip needs news validation"

        elif anomaly_type == "VOLUME_SPIKE":
            if price > 0.99:
                verdict = "VETTED"
                confidence = 0.9
                reasoning = "Near-settled market, safe dust"
            elif spread > 10:
                verdict = "REJECTED"
                confidence = 0.8
                reasoning = f"Wide spread ({spread:.1f}%) - illiquid"
            else:
                verdict = "PENDING"
                confidence = 0.5 + sentiment_boost
                reasoning = "Volume spike needs context"

        elif anomaly_type == "MISPRICING":
            if opp.get("volume_24h", 0) > 100_000:
                verdict = "VETTED"
                confidence = 0.75
                reasoning = "Inefficient spread on liquid market"
            else:
                verdict = "REJECTED"
                confidence = 0.7
                reasoning = "Low volume mispricing"

        # Cap confidence
        confidence = max(0.1, min(0.99, confidence))

        return {
            "verdict": verdict,
            "reasoning": reasoning,
            "confidence": round(confidence, 2),
            "sentiment": cached_sentiment.get("direction") if cached_sentiment else None,
            "analyzed_at": datetime.now(timezone.utc).isoformat()
        }

    async def vet_pending(self):
        """Vet all pending opportunities."""
        opps = self.state.get_opportunities()
        pending = [o for o in opps if o.get("status") == "PENDING"]

        vetted_count = 0
        rejected_count = 0

        for opp in pending:
            analysis = await self.analyze(opp)

            # Update opportunity
            opp["analyst_verdict"] = analysis["verdict"]
            opp["analyst_reasoning"] = analysis["reasoning"]
            opp["analyst_confidence"] = analysis["confidence"]
            opp["analyzed_at"] = analysis["analyzed_at"]

            if analysis["verdict"] == "VETTED":
                opp["status"] = "VETTED"
                self.state.add_vetted(opp)
                vetted_count += 1
                print(f"[BETA] ✅ VETTED: {opp['question'][:40]}... ({analysis['confidence']:.0%})")

            elif analysis["verdict"] == "REJECTED":
                opp["status"] = "REJECTED"
                rejected_count += 1
                print(f"[BETA] ❌ REJECTED: {opp['question'][:40]}...")

            # Update in state
            self.state.add_opportunity(opp)

        self.state.incr_metric("beta_vetted", vetted_count)
        self.state.incr_metric("beta_rejected", rejected_count)

        return {"vetted": vetted_count, "rejected": rejected_count}

    async def run(self, interval: float = 5.0):
        """Main analysis loop."""
        self.running = True
        print("[BETA] Analyst started")

        while self.running:
            try:
                result = await self.vet_pending()
                if result["vetted"] > 0 or result["rejected"] > 0:
                    print(f"[BETA] Cycle: {result['vetted']} vetted, {result['rejected']} rejected")
            except Exception as e:
                print(f"[BETA] Error: {e}")

            await asyncio.sleep(interval)

    def stop(self):
        self.running = False


async def main():
    analyst = AsyncBetaAnalyst()
    try:
        await analyst.run()
    except KeyboardInterrupt:
        analyst.stop()


if __name__ == "__main__":
    asyncio.run(main())
