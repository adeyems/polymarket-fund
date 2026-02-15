#!/usr/bin/env python3
"""
DUAL-SIDE VOLATILITY ARBITRAGE SCANNER
========================================
The Account88888 strategy: Buy BOTH sides when mispriced.

When UP + DOWN < $1.00, buy both. One MUST pay $1.00.
Guaranteed profit = $1.00 - (UP + DOWN)

This scanner finds these opportunities on BTC/crypto volatility markets.
"""

import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import List, Dict, Optional
import re


GAMMA_API = "https://gamma-api.polymarket.com/markets"

# Minimum profit to signal (after fees ~1%)
MIN_PROFIT_PCT = 0.02  # 2% minimum edge


class VolatilityArbScanner:
    """
    Scans for dual-side arbitrage opportunities.

    Target markets:
    - "Will BTC be above/below $X?"
    - "BTC price on [date]: Up or Down?"
    - Any market with complementary YES/NO that sum < $1
    """

    def __init__(self):
        self.opportunities = []

    async def get_volatility_markets(self) -> List[dict]:
        """Find BTC/crypto price volatility markets."""
        try:
            async with aiohttp.ClientSession() as session:
                params = {"limit": 200, "active": "true", "closed": "false"}
                async with session.get(GAMMA_API, params=params, timeout=15) as resp:
                    if resp.status != 200:
                        return []

                    markets = await resp.json()

                    # Filter for crypto volatility markets
                    volatility_markets = []
                    for m in markets:
                        q = m.get("question", "").lower()
                        # Look for price prediction markets
                        if any(kw in q for kw in ["btc", "bitcoin", "eth", "ethereum", "crypto"]):
                            if any(kw in q for kw in ["above", "below", "up", "down", "price", "reach"]):
                                volatility_markets.append(m)

                    return volatility_markets
        except Exception as e:
            print(f"[VOL_ARB] Error fetching markets: {e}")
            return []

    async def find_paired_markets(self) -> List[dict]:
        """
        Find markets that are logical opposites (UP/DOWN pairs).
        These are where dual-side arb is possible.
        """
        markets = await self.get_volatility_markets()
        print(f"[VOL_ARB] Found {len(markets)} volatility markets")

        opportunities = []

        for m in markets:
            condition_id = m.get("conditionId", "")
            question = m.get("question", "")
            best_ask = float(m.get("bestAsk") or 0)  # Price to buy YES
            best_bid = float(m.get("bestBid") or 0)  # Price to sell YES (or buy NO)
            liquidity = float(m.get("liquidityNum") or 0)

            if liquidity < 5000:
                continue

            # For a single market: YES + NO should = $1.00
            # best_ask = price to buy YES
            # (1 - best_bid) = approximate price to buy NO
            # If best_ask + (1 - best_bid) < 1, there's arb

            no_price = 1 - best_bid if best_bid > 0 else 1 - best_ask
            total_cost = best_ask + no_price

            if total_cost < (1.0 - MIN_PROFIT_PCT):
                profit_pct = (1.0 - total_cost) / total_cost * 100

                opportunities.append({
                    "condition_id": condition_id,
                    "question": question[:80],
                    "strategy": "DUAL_SIDE_ARB",
                    "yes_price": round(best_ask, 3),
                    "no_price": round(no_price, 3),
                    "total_cost": round(total_cost, 3),
                    "profit_per_dollar": round(1.0 - total_cost, 3),
                    "profit_pct": round(profit_pct, 2),
                    "liquidity": int(liquidity),
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "action": "BUY_BOTH"
                })

                print(f"[VOL_ARB] OPPORTUNITY FOUND!")
                print(f"    {question[:50]}...")
                print(f"    YES: ${best_ask:.3f} + NO: ${no_price:.3f} = ${total_cost:.3f}")
                print(f"    Profit: {profit_pct:.1f}%")

        return opportunities

    async def scan_all_markets_for_arb(self) -> List[dict]:
        """
        Scan ALL markets for any where YES + NO < $1.00.
        Not just crypto - any mispriced market.
        """
        opportunities = []

        try:
            async with aiohttp.ClientSession() as session:
                params = {"limit": 200, "active": "true", "closed": "false"}
                async with session.get(GAMMA_API, params=params, timeout=15) as resp:
                    if resp.status != 200:
                        return []

                    markets = await resp.json()

                    for m in markets:
                        condition_id = m.get("conditionId", "")
                        question = m.get("question", "")
                        best_ask = float(m.get("bestAsk") or 0)
                        best_bid = float(m.get("bestBid") or 0)
                        liquidity = float(m.get("liquidityNum") or 0)

                        if liquidity < 5000 or best_ask <= 0 or best_bid <= 0:
                            continue

                        # Calculate NO price from the spread
                        # In a perfect market: YES_ask + NO_ask = 1.00
                        # NO price ≈ 1 - YES_bid (what you'd pay to buy NO)
                        no_price = 1 - best_bid
                        total_cost = best_ask + no_price

                        # Check for arbitrage
                        if total_cost < (1.0 - MIN_PROFIT_PCT):
                            profit_pct = (1.0 - total_cost) / total_cost * 100

                            opportunities.append({
                                "condition_id": condition_id,
                                "question": question[:80],
                                "strategy": "DUAL_SIDE_ARB",
                                "yes_price": round(best_ask, 3),
                                "no_price": round(no_price, 3),
                                "total_cost": round(total_cost, 3),
                                "profit_per_dollar": round(1.0 - total_cost, 3),
                                "profit_pct": round(profit_pct, 2),
                                "liquidity": int(liquidity),
                                "discovered_at": datetime.now(timezone.utc).isoformat()
                            })

                    print(f"[VOL_ARB] Scanned {len(markets)} markets, found {len(opportunities)} arb opportunities")

        except Exception as e:
            print(f"[VOL_ARB] Error: {e}")

        return opportunities


async def main():
    print("=" * 60)
    print("  DUAL-SIDE VOLATILITY ARBITRAGE SCANNER")
    print("  (Account88888's $645K Strategy)")
    print("=" * 60)
    print()

    scanner = VolatilityArbScanner()

    # Scan all markets
    print("[1] Scanning ALL markets for YES+NO < $1.00...")
    all_opps = await scanner.scan_all_markets_for_arb()

    if all_opps:
        print(f"\nFOUND {len(all_opps)} ARBITRAGE OPPORTUNITIES:")
        for opp in all_opps:
            print(f"\n  {opp['question']}")
            print(f"  YES: ${opp['yes_price']} + NO: ${opp['no_price']} = ${opp['total_cost']}")
            print(f"  PROFIT: {opp['profit_pct']:.1f}% per trade")
            print(f"  Liquidity: ${opp['liquidity']:,}")
    else:
        print("\nNo arbitrage opportunities found right now.")
        print("This means markets are efficiently priced.")
        print("Opportunities appear during high volatility/panic.")

    # Also check crypto-specific
    print("\n[2] Scanning crypto volatility markets...")
    crypto_opps = await scanner.find_paired_markets()

    if crypto_opps:
        print(f"\nFOUND {len(crypto_opps)} CRYPTO ARB OPPORTUNITIES")
    else:
        print("No crypto-specific arb found.")

    print("\n" + "=" * 60)
    print("  TIP: Run this during BTC pumps/dumps for best results")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
