#!/usr/bin/env python3
"""
BINANCE-POLYMARKET ARBITRAGE SCANNER
=====================================
Compares crypto price predictions between Polymarket and Binance.
Finds mispricings where prediction markets lag behind derivatives markets.

Strategy:
1. Find Polymarket markets about crypto prices (BTC, ETH, SOL, etc.)
2. Get Binance futures/spot prices
3. Calculate implied probability from price distance
4. Compare to Polymarket price
5. If gap > threshold → ARBITRAGE SIGNAL
"""

import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import List, Dict, Optional
import re
import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from core.redis_state import get_state


# Binance API endpoints
BINANCE_SPOT_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_FUTURES_URL = "https://fapi.binance.com/fapi/v1/ticker/price"

# Polymarket Gamma API
GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"

# Arbitrage thresholds
MIN_EDGE_PERCENT = 5.0  # Minimum 5% edge to signal
MIN_LIQUIDITY = 10_000  # Minimum $10k liquidity


class BinanceArbScanner:
    """
    Cross-exchange arbitrage scanner.
    Compares Polymarket predictions to Binance-implied probabilities.
    """

    def __init__(self):
        self.state = get_state()
        self.running = False
        self._price_cache = {}  # symbol -> price

    async def get_binance_prices(self) -> Dict[str, float]:
        """Fetch current Binance spot prices for major cryptos."""
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT"]
        prices = {}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(BINANCE_SPOT_URL, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data:
                            if item["symbol"] in symbols:
                                prices[item["symbol"]] = float(item["price"])
        except Exception as e:
            print(f"[BINANCE_ARB] Price fetch error: {e}")

        self._price_cache = prices
        return prices

    async def get_crypto_markets(self) -> List[dict]:
        """Find Polymarket markets about crypto prices."""
        crypto_markets = []

        try:
            async with aiohttp.ClientSession() as session:
                # Search for crypto-related markets
                params = {"limit": 100, "active": "true"}
                async with session.get(GAMMA_API_URL, params=params, timeout=15) as resp:
                    if resp.status == 200:
                        markets = await resp.json()

                        for m in markets:
                            question = m.get("question", "").lower()
                            # Filter for crypto price markets
                            if any(kw in question for kw in ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto"]):
                                if any(kw in question for kw in ["price", "above", "below", "reach", "hit", "$"]):
                                    crypto_markets.append(m)

        except Exception as e:
            print(f"[BINANCE_ARB] Market fetch error: {e}")

        return crypto_markets

    def extract_price_target(self, question: str) -> Optional[Dict]:
        """
        Extract crypto symbol and price target from market question.

        Examples:
        - "Will Bitcoin be above $100,000 on March 1?" -> {symbol: BTC, target: 100000, direction: ABOVE}
        - "Will ETH reach $5,000 by end of 2024?" -> {symbol: ETH, target: 5000, direction: ABOVE}
        """
        question_lower = question.lower()

        # Identify crypto
        symbol = None
        if "bitcoin" in question_lower or "btc" in question_lower:
            symbol = "BTCUSDT"
        elif "ethereum" in question_lower or "eth" in question_lower:
            symbol = "ETHUSDT"
        elif "solana" in question_lower or "sol" in question_lower:
            symbol = "SOLUSDT"

        if not symbol:
            return None

        # Extract price target
        # Match patterns like $100,000 or $100k or 100000
        price_patterns = [
            r'\$([0-9,]+(?:\.[0-9]+)?)[k]?',  # $100,000 or $100k
            r'([0-9,]+(?:\.[0-9]+)?)\s*(?:dollars|usd)',  # 100000 dollars
        ]

        target = None
        for pattern in price_patterns:
            match = re.search(pattern, question_lower.replace(',', ''))
            if match:
                price_str = match.group(1).replace(',', '')
                if 'k' in question_lower[match.end():match.end()+1]:
                    target = float(price_str) * 1000
                else:
                    target = float(price_str)
                break

        if not target:
            return None

        # Determine direction
        direction = "ABOVE"  # Default
        if "below" in question_lower or "under" in question_lower:
            direction = "BELOW"

        return {
            "symbol": symbol,
            "target": target,
            "direction": direction
        }

    def calculate_implied_probability(self, current_price: float, target: float,
                                       direction: str, days_to_expiry: int = 30) -> float:
        """
        Calculate implied probability that price will reach target.

        Uses simple distance-based model:
        - If target is 10% away, probability decreases
        - Volatility assumption: ~3% daily for BTC

        More sophisticated: Use Black-Scholes or historical data
        """
        if current_price <= 0 or target <= 0:
            return 0.5

        # Distance to target (as percentage)
        if direction == "ABOVE":
            distance = (target - current_price) / current_price
        else:
            distance = (current_price - target) / current_price

        # Simplified probability model
        # Assumes ~60% annual volatility for crypto (~3% daily)
        daily_vol = 0.03
        expected_move = daily_vol * (days_to_expiry ** 0.5)  # sqrt(time) scaling

        if direction == "ABOVE":
            if current_price >= target:
                # Already above target
                prob = 0.85 + (current_price - target) / target * 0.1
            else:
                # Need price to go up
                prob = max(0.05, 0.5 - distance / expected_move * 0.5)
        else:
            if current_price <= target:
                prob = 0.85 + (target - current_price) / current_price * 0.1
            else:
                prob = max(0.05, 0.5 - distance / expected_move * 0.5)

        return min(0.95, max(0.05, prob))

    async def scan_for_arbitrage(self) -> List[dict]:
        """
        Main scan: Compare Polymarket prices to Binance-implied probabilities.
        """
        opportunities = []

        # Get current Binance prices
        binance_prices = await self.get_binance_prices()
        if not binance_prices:
            print("[BINANCE_ARB] No Binance prices available")
            return opportunities

        print(f"[BINANCE_ARB] BTC: ${binance_prices.get('BTCUSDT', 0):,.0f} | ETH: ${binance_prices.get('ETHUSDT', 0):,.0f}")

        # Get crypto markets from Polymarket
        markets = await self.get_crypto_markets()
        print(f"[BINANCE_ARB] Found {len(markets)} crypto-related markets")

        for market in markets:
            question = market.get("question", "")
            condition_id = market.get("conditionId", "")
            best_ask = float(market.get("bestAsk") or 0)
            best_bid = float(market.get("bestBid") or 0)
            liquidity = float(market.get("liquidityNum") or 0)

            if liquidity < MIN_LIQUIDITY:
                continue

            # Extract target from question
            target_info = self.extract_price_target(question)
            if not target_info:
                continue

            symbol = target_info["symbol"]
            target_price = target_info["target"]
            direction = target_info["direction"]

            current_price = binance_prices.get(symbol, 0)
            if current_price <= 0:
                continue

            # Calculate Binance-implied probability
            binance_prob = self.calculate_implied_probability(
                current_price, target_price, direction
            )

            # Polymarket probability = best_ask (price to buy YES)
            poly_prob = best_ask

            # Calculate edge
            edge = binance_prob - poly_prob

            if abs(edge) >= MIN_EDGE_PERCENT / 100:
                signal = {
                    "condition_id": condition_id,
                    "question": question[:80],
                    "anomaly_type": "BINANCE_ARB",
                    "symbol": symbol,
                    "current_price": current_price,
                    "target_price": target_price,
                    "direction": direction,
                    "polymarket_prob": round(poly_prob, 3),
                    "binance_implied_prob": round(binance_prob, 3),
                    "edge": round(edge * 100, 2),  # As percentage
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "liquidity": int(liquidity),
                    "recommendation": "BUY_YES" if edge > 0 else "BUY_NO",
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "status": "PENDING"
                }

                opportunities.append(signal)
                print(f"[BINANCE_ARB] 🎯 EDGE FOUND: {edge*100:+.1f}%")
                print(f"    {question[:50]}...")
                print(f"    {symbol}: ${current_price:,.0f} → Target: ${target_price:,.0f}")
                print(f"    Polymarket: {poly_prob:.1%} | Binance implied: {binance_prob:.1%}")

        return opportunities

    async def run(self, interval: float = 60.0):
        """Main scan loop."""
        self.running = True
        print("[BINANCE_ARB] Scanner started")
        print(f"[BINANCE_ARB] Min edge threshold: {MIN_EDGE_PERCENT}%")

        while self.running:
            try:
                opps = await self.scan_for_arbitrage()

                for opp in opps:
                    self.state.add_opportunity(opp)

                if opps:
                    print(f"[BINANCE_ARB] Cycle complete: {len(opps)} opportunities")
                else:
                    print(f"[BINANCE_ARB] No arbitrage opportunities found this cycle")

            except Exception as e:
                print(f"[BINANCE_ARB] Error: {e}")

            await asyncio.sleep(interval)

    def stop(self):
        self.running = False


async def main():
    scanner = BinanceArbScanner()

    print("=" * 60)
    print("  BINANCE-POLYMARKET ARBITRAGE SCANNER")
    print("=" * 60)
    print()

    # Run single scan for testing
    opps = await scanner.scan_for_arbitrage()

    if opps:
        print()
        print(f"Found {len(opps)} arbitrage opportunities:")
        for opp in opps:
            print(f"  • {opp['question'][:40]}...")
            print(f"    Edge: {opp['edge']:+.1f}% | Rec: {opp['recommendation']}")
    else:
        print()
        print("No arbitrage opportunities found.")
        print("This could mean:")
        print("  1. Markets are efficiently priced")
        print("  2. No crypto price prediction markets active")
        print("  3. Edge threshold too high (currently 5%)")


if __name__ == "__main__":
    asyncio.run(main())
