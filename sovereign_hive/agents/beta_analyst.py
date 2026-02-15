#!/usr/bin/env python3
"""
AGENT BETA - THE ANALYST
========================
Semantic Validation Engine. Vets Alpha's discoveries with news/LLM.

Workflow:
1. Read PENDING opportunities from blackboard
2. For each, query news sources or LLM
3. Determine: VETTED (safe to trade) or REJECTED (trap/noise)
4. Move vetted trades to vetted_trades list
"""

import json
import os
import requests
from datetime import datetime, timezone
from pathlib import Path

BLACKBOARD_PATH = Path(__file__).parent.parent / "blackboard.json"

# Verdict types
VERDICT_VETTED = "VETTED"
VERDICT_REJECTED = "REJECTED"
VERDICT_PENDING = "PENDING"


def load_blackboard() -> dict:
    """Load the shared blackboard."""
    try:
        with open(BLACKBOARD_PATH, "r") as f:
            return json.load(f)
    except:
        return {"opportunities": [], "vetted_trades": [], "active_positions": [], "risk_state": "HEALTHY"}


def save_blackboard(blackboard: dict):
    """Save the blackboard."""
    with open(BLACKBOARD_PATH, "w") as f:
        json.dump(blackboard, f, indent=2)


def search_news(query: str) -> list:
    """
    Search for recent news about a topic.
    Uses free news APIs or can be upgraded to Tavily/NewsAPI.
    """
    # Placeholder - in production, use Tavily, NewsAPI, or web search
    # For now, return empty (manual vetting mode)
    return []


def analyze_with_llm(opportunity: dict, news_context: str = "") -> dict:
    """
    Use LLM to analyze if the opportunity is legitimate.
    Returns verdict and reasoning.

    In production: Call Claude/GPT API
    For now: Rule-based analysis
    """
    anomaly_type = opportunity.get("anomaly_type", "")
    price = opportunity.get("best_ask", 0)
    price_change = opportunity.get("price_change_1d", 0)
    spread = opportunity.get("spread_pct", 0)
    volume = opportunity.get("volume_24h", 0)

    verdict = VERDICT_PENDING
    reasoning = ""
    confidence = 0.0

    # === RULE-BASED ANALYSIS (Upgrade to LLM later) ===

    # ARBITRAGE: High price + tight spread = likely safe
    if anomaly_type == "ARBITRAGE":
        if price >= 0.995 and spread < 0.5:
            verdict = VERDICT_VETTED
            reasoning = f"Near-certain outcome at ${price:.3f} with tight {spread:.1f}% spread. Low risk arbitrage."
            confidence = 0.95
        elif price >= 0.98 and spread < 1.0:
            verdict = VERDICT_VETTED
            reasoning = f"High probability at ${price:.3f}. Acceptable spread."
            confidence = 0.85
        else:
            verdict = VERDICT_REJECTED
            reasoning = f"Spread too wide ({spread:.1f}%) for arbitrage play."
            confidence = 0.70

    # DIP_BUY: Need news validation (default to reject without context)
    elif anomaly_type == "DIP_BUY":
        if abs(price_change) > 50:
            verdict = VERDICT_REJECTED
            reasoning = f"Massive {price_change:.1f}% move suggests fundamental shift, not temporary dip. Needs manual review."
            confidence = 0.60
        elif abs(price_change) > 20 and volume > 500000:
            verdict = VERDICT_PENDING
            reasoning = f"Significant dip with high volume. Requires news validation."
            confidence = 0.50
        else:
            verdict = VERDICT_REJECTED
            reasoning = "Insufficient conviction for dip buy."
            confidence = 0.65

    # VOLUME_SPIKE: Check if it's live event noise
    elif anomaly_type == "VOLUME_SPIKE":
        if price > 0.99:
            verdict = VERDICT_VETTED
            reasoning = "Volume spike on near-settled market. Safe to collect dust."
            confidence = 0.90
        elif spread > 10:
            verdict = VERDICT_REJECTED
            reasoning = f"Wide spread ({spread:.1f}%) indicates illiquid/manipulated market."
            confidence = 0.80
        else:
            verdict = VERDICT_PENDING
            reasoning = "Volume spike needs context. Could be live event or whale activity."
            confidence = 0.50

    # MISPRICING: Usually safe if spread is wide on liquid market
    elif anomaly_type == "MISPRICING":
        if volume > 100000:
            verdict = VERDICT_VETTED
            reasoning = f"Inefficient spread on liquid market (${volume:,} vol). Market making opportunity."
            confidence = 0.75
        else:
            verdict = VERDICT_REJECTED
            reasoning = "Low volume mispricing - likely illiquid, not inefficient."
            confidence = 0.70

    return {
        "verdict": verdict,
        "reasoning": reasoning,
        "confidence": confidence,
        "analyzed_at": datetime.now(timezone.utc).isoformat()
    }


def vet_opportunities():
    """Main vetting loop - analyze all PENDING opportunities."""
    print(f"\n{'='*60}")
    print(f"[BETA ANALYST] Vetting initiated at {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}")

    blackboard = load_blackboard()
    opportunities = blackboard.get("opportunities", [])
    vetted_trades = blackboard.get("vetted_trades", [])

    pending = [o for o in opportunities if o.get("status") == "PENDING"]
    print(f"[BETA] Found {len(pending)} PENDING opportunities to analyze")

    vetted_count = 0
    rejected_count = 0

    for opp in pending:
        question = opp.get("question", "Unknown")[:60]
        print(f"\n[BETA] Analyzing: {question}...")

        # Get news context (placeholder)
        news = search_news(question)
        news_context = "\n".join(news) if news else ""

        # Analyze with LLM/rules
        analysis = analyze_with_llm(opp, news_context)

        # Update opportunity with analysis
        opp["analyst_verdict"] = analysis["verdict"]
        opp["analyst_reasoning"] = analysis["reasoning"]
        opp["analyst_confidence"] = analysis["confidence"]
        opp["analyzed_at"] = analysis["analyzed_at"]

        if analysis["verdict"] == VERDICT_VETTED:
            opp["status"] = "VETTED"
            vetted_trades.append(opp.copy())
            vetted_count += 1
            print(f"  ✅ VETTED (Confidence: {analysis['confidence']:.0%})")
            print(f"     Reason: {analysis['reasoning']}")
        elif analysis["verdict"] == VERDICT_REJECTED:
            opp["status"] = "REJECTED"
            rejected_count += 1
            print(f"  ❌ REJECTED (Confidence: {analysis['confidence']:.0%})")
            print(f"     Reason: {analysis['reasoning']}")
        else:
            print(f"  ⏸️  PENDING - Needs manual review")
            print(f"     Reason: {analysis['reasoning']}")

    # Save updated blackboard
    blackboard["vetted_trades"] = vetted_trades
    blackboard["last_analysis"] = datetime.now(timezone.utc).isoformat()
    save_blackboard(blackboard)

    print(f"\n[BETA] === SUMMARY ===")
    print(f"  Vetted: {vetted_count}")
    print(f"  Rejected: {rejected_count}")
    print(f"  Still Pending: {len(pending) - vetted_count - rejected_count}")

    return vetted_trades


def manual_vet(condition_id: str, verdict: str, reasoning: str = "Manual override"):
    """Manually vet a specific opportunity."""
    blackboard = load_blackboard()

    for opp in blackboard["opportunities"]:
        if opp["condition_id"] == condition_id:
            opp["status"] = verdict
            opp["analyst_verdict"] = verdict
            opp["analyst_reasoning"] = reasoning
            opp["analyst_confidence"] = 1.0
            opp["analyzed_at"] = datetime.now(timezone.utc).isoformat()

            if verdict == VERDICT_VETTED:
                blackboard["vetted_trades"].append(opp.copy())
                print(f"[BETA] Manually VETTED: {opp['question'][:50]}")
            else:
                print(f"[BETA] Manually REJECTED: {opp['question'][:50]}")

            save_blackboard(blackboard)
            return True

    print(f"[BETA] Condition ID not found: {condition_id}")
    return False


def main():
    """Run vetting once or in loop."""
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "--once":
            vet_opportunities()
        elif sys.argv[1] == "--manual" and len(sys.argv) >= 4:
            # Usage: --manual <condition_id> <VETTED|REJECTED> [reasoning]
            cid = sys.argv[2]
            verdict = sys.argv[3]
            reason = sys.argv[4] if len(sys.argv) > 4 else "Manual override"
            manual_vet(cid, verdict, reason)
    else:
        # Continuous mode
        import time
        while True:
            try:
                vet_opportunities()
                print(f"\n[BETA] Sleeping 300s until next analysis...")
                time.sleep(300)
            except KeyboardInterrupt:
                print("\n[BETA] Analyst terminated.")
                break


if __name__ == "__main__":
    main()
