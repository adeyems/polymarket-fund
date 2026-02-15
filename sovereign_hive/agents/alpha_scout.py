#!/usr/bin/env python3
"""
AGENT ALPHA - THE SCOUT
=======================
Mathematical Discovery Engine. Keyword-blind anomaly detection.

Anomaly Types:
- ARBITRAGE: Price > $0.98 (near-certain outcome, potential free money)
- DIP_BUY: High volume + significant price drop (whale exit, retail panic)
- VOLUME_SPIKE: 2x normal volume (institutional interest)
- MISPRICING: Spread > 5% on liquid market (inefficiency)
"""

import json
import requests
import time
from datetime import datetime
from pathlib import Path

BLACKBOARD_PATH = Path(__file__).parent.parent / "blackboard.json"
GAMMA_API = "https://gamma-api.polymarket.com/markets"

# Anomaly Thresholds
ARBITRAGE_THRESHOLD = 0.98      # Price above this = near-certain
DIP_THRESHOLD = -0.10           # 10% drop triggers DIP_BUY
VOLUME_MIN = 100_000            # Minimum 24h volume to consider
SPREAD_MAX = 0.05               # 5% spread = mispricing opportunity
VOLUME_SPIKE_MULTIPLIER = 2.0   # 2x average = spike


def fetch_markets(limit: int = 100) -> list:
    """Fetch top markets by 24h volume from Gamma API."""
    try:
        params = {
            "limit": str(limit),
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false"
        }
        resp = requests.get(GAMMA_API, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[ALPHA] API Error: {e}")
        return []


def detect_anomalies(markets: list) -> list:
    """Pure mathematical anomaly detection. No keywords."""
    opportunities = []

    for m in markets:
        try:
            question = m.get("question", "Unknown")
            condition_id = m.get("conditionId", "")

            # Extract numerical data
            best_bid = float(m.get("bestBid") or 0)
            best_ask = float(m.get("bestAsk") or 0)
            last_price = float(m.get("lastTradePrice") or 0)
            volume_24h = float(m.get("volume24hr") or 0)
            volume_1w = float(m.get("volume1wk") or 0)
            liquidity = float(m.get("liquidityNum") or 0)

            # Price changes
            price_change_1d = float(m.get("oneDayPriceChange") or 0)
            price_change_1w = float(m.get("oneWeekPriceChange") or 0)

            # Skip illiquid markets
            if volume_24h < VOLUME_MIN:
                continue

            # Calculate spread
            spread = (best_ask - best_bid) / best_ask if best_ask > 0 else 1.0
            midpoint = (best_bid + best_ask) / 2 if best_ask > 0 else 0

            anomaly = None
            score = 0

            # === ANOMALY 1: ARBITRAGE (The Vulture) ===
            # Near-certain outcomes priced below $1.00
            if best_ask >= ARBITRAGE_THRESHOLD and best_ask < 0.999:
                potential_profit = (1.0 - best_ask) / best_ask * 100
                if spread < 0.02:  # Tight spread = real opportunity
                    anomaly = "ARBITRAGE"
                    score = potential_profit

            # === ANOMALY 2: DIP_BUY (The Crash) ===
            # High volume market with significant price drop
            elif price_change_1d <= DIP_THRESHOLD and volume_24h > 500_000:
                anomaly = "DIP_BUY"
                score = abs(price_change_1d) * 100  # Bigger dip = higher score

            # === ANOMALY 3: VOLUME_SPIKE (The Whale) ===
            # Unusual volume activity
            elif volume_1w > 0:
                daily_avg = volume_1w / 7
                if volume_24h > daily_avg * VOLUME_SPIKE_MULTIPLIER:
                    # Volume spike with price movement
                    if abs(price_change_1d) > 0.05:
                        anomaly = "VOLUME_SPIKE"
                        score = (volume_24h / daily_avg) * 10

            # === ANOMALY 4: MISPRICING (The Inefficiency) ===
            # Wide spread on liquid market = market maker opportunity
            elif spread > SPREAD_MAX and liquidity > 50_000:
                anomaly = "MISPRICING"
                score = spread * 100

            if anomaly:
                opportunities.append({
                    "condition_id": condition_id,
                    "question": question[:80],
                    "anomaly_type": anomaly,
                    "score": round(score, 2),
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread_pct": round(spread * 100, 2),
                    "volume_24h": int(volume_24h),
                    "price_change_1d": round(price_change_1d * 100, 2),
                    "liquidity": int(liquidity),
                    "discovered_at": datetime.utcnow().isoformat(),
                    "status": "PENDING"
                })

        except Exception as e:
            continue

    # Sort by score (highest first)
    opportunities.sort(key=lambda x: x["score"], reverse=True)
    return opportunities


def update_blackboard(opportunities: list):
    """Write discoveries to the shared blackboard."""
    try:
        with open(BLACKBOARD_PATH, "r") as f:
            blackboard = json.load(f)
    except:
        blackboard = {"opportunities": [], "vetted_trades": [], "active_positions": [], "risk_state": "HEALTHY"}

    # Dedupe by condition_id
    existing_ids = {o["condition_id"] for o in blackboard["opportunities"]}
    new_opps = [o for o in opportunities if o["condition_id"] not in existing_ids]

    # Add new opportunities
    blackboard["opportunities"].extend(new_opps)

    # Keep only last 50 opportunities
    blackboard["opportunities"] = blackboard["opportunities"][-50:]

    # Update metadata
    blackboard["last_scan"] = datetime.utcnow().isoformat()
    blackboard["scan_count"] = blackboard.get("scan_count", 0) + 1

    with open(BLACKBOARD_PATH, "w") as f:
        json.dump(blackboard, f, indent=2)

    return new_opps


def run_scan():
    """Execute one scan cycle."""
    print(f"\n{'='*60}")
    print(f"[ALPHA SCOUT] Scan initiated at {datetime.utcnow().isoformat()}")
    print(f"{'='*60}")

    # Fetch markets
    markets = fetch_markets(limit=100)
    print(f"[ALPHA] Fetched {len(markets)} markets from Gamma API")

    if not markets:
        print("[ALPHA] No markets fetched. Aborting scan.")
        return []

    # Detect anomalies
    opportunities = detect_anomalies(markets)
    print(f"[ALPHA] Detected {len(opportunities)} anomalies")

    # Update blackboard
    new_opps = update_blackboard(opportunities)

    # Report findings
    print(f"\n[ALPHA] === TOP DISCOVERIES ===")
    for i, opp in enumerate(opportunities[:5], 1):
        print(f"\n  #{i} [{opp['anomaly_type']}] Score: {opp['score']}")
        print(f"      Market: {opp['question']}")
        print(f"      Bid: ${opp['best_bid']:.3f} | Ask: ${opp['best_ask']:.3f} | Spread: {opp['spread_pct']:.1f}%")
        print(f"      24h Vol: ${opp['volume_24h']:,} | 1d Change: {opp['price_change_1d']:+.1f}%")

    return opportunities


def main():
    """Continuous scan loop."""
    print("[ALPHA SCOUT] Initializing Sovereign Hive - Agent Alpha")
    print("[ALPHA] Mode: MATHEMATICAL ANOMALY DETECTION")
    print("[ALPHA] Keywords: DISABLED (Pure Math)")

    while True:
        try:
            opportunities = run_scan()

            # Sleep between scans (5 minutes)
            print(f"\n[ALPHA] Sleeping 300s until next scan...")
            time.sleep(300)

        except KeyboardInterrupt:
            print("\n[ALPHA] Scout terminated by user.")
            break
        except Exception as e:
            print(f"[ALPHA] Error in scan loop: {e}")
            time.sleep(60)


if __name__ == "__main__":
    # Single scan for testing
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_scan()
    else:
        main()
