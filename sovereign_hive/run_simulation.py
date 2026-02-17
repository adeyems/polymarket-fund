#!/usr/bin/env python3
"""
SOVEREIGN HIVE - SIMULATION RUNNER
===================================
Uses REAL market data with SIMULATED order execution.

Usage:
    python run_simulation.py           # Simulation mode ($1000 virtual)
    python run_simulation.py --live    # Live trading (real money)
"""

import asyncio
import aiohttp
import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.claude_analyzer import ClaudeAnalyzer
from core.kelly_criterion import KellyCriterion
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# STRATEGY FILTERING (for isolated testing)
# ============================================================

STRATEGY_FILTER = os.getenv("STRATEGY_FILTER", "").strip()
if STRATEGY_FILTER:
    print(f"\n[CONFIG] Strategy filter enabled: {STRATEGY_FILTER}")
    print(f"[CONFIG] Only this strategy will execute\n")

# ============================================================
# CONFIGURATION
# ============================================================

CONFIG = {
    "initial_balance": 1000.00,      # Paper trading capital
    "max_position_pct": 0.20,        # Max 20% per trade
    "max_positions": 6,              # Diversified positions
    "take_profit_pct": 0.10,         # +10% take profit (optimized: larger wins)
    "stop_loss_pct": -0.05,          # -5% stop loss (optimized: tighter = better)
    # DUAL-SIDE ARB CONFIG
    "dual_side_min_profit": 0.02,    # Minimum 2% profit for dual-side arb
    "dual_side_min_liquidity": 10000, # $10k minimum liquidity per side
    "min_liquidity": 5000,           # Min market liquidity (lowered from 10k)
    "min_confidence": 0.55,          # Min AI confidence to trade (lowered from 0.60)
    "scan_interval": 60,             # Seconds between scans
    # Lowered thresholds for more opportunities (research-backed)
    "dip_threshold": -0.03,          # 3% drop (was 5% - too restrictive)
    "volume_surge_mult": 1.5,        # 1.5x volume (was 2x - too restrictive)
    "near_certain_min": 0.93,        # 93% YES (was 95% - research shows 93%+ profitable)
    "near_zero_max": 0.07,           # 7% YES (was 5% - capture more near-zero opps)
    # CAPITAL EFFICIENCY - The math that matters!
    "max_days_to_resolve": 90,       # Don't lock capital for >90 days
    "min_annualized_return": 0.15,   # Require 15%+ annualized return
    # Formula: annualized = (1 + return)^(365/days) - 1
    # Example: 2% in 18 days = 49% annualized (GOOD)
    # Example: 2% in 324 days = 2.3% annualized (BAD - skip!)
    # NEW: Mid-range markets for active trading
    "mid_range_min": 0.20,           # 20% - room to move up
    "mid_range_max": 0.80,           # 80% - room to move down
    "min_24h_volume": 10000,         # Volume threshold for mid-range (lowered)

    # MARKET MAKER CONFIG (NEW - Based on research: 10-200% APY proven)
    # Strategy: Post bid/ask on both sides, profit from spread when both fill
    # Source: Polymarket docs + on-chain analysis of profitable MM bots
    "mm_min_spread": 0.02,           # 2% minimum spread to profit after fees
    "mm_max_spread": 0.10,           # 10% max spread (relaxed for more opportunities)
    "mm_min_volume_24h": 15000,      # $15k+ volume (lowered - markets are quieter now)
    "mm_min_liquidity": 30000,       # $30k+ liquidity depth
    "mm_target_profit": 0.02,        # 2% target profit per round trip (was 1% - too thin)
    "mm_max_hold_hours": 4,          # Exit if not filled within 4 hours (was 24)
    "mm_price_range": (0.05, 0.95),  # 5-95% range (was 15-85 - missed liquid low-price markets)
    "mm_max_days_to_resolve": 30,    # Only MM markets resolving within 30 days (fast turnover)
    "mm_ai_screen": True,            # Use Gemini AI to screen market quality before trading

    # BINANCE ARBITRAGE CONFIG (Strategy 8 - Model-based, NOT latency arb)
    # Polymarket added 3.15% dynamic fees on 15-min crypto markets, killing latency arb
    # Now: compare Binance spot to Polymarket for LONGER-DURATION crypto markets only
    "binance_min_edge": 0.03,        # 3% minimum edge (was 5% - too restrictive)
    "binance_min_liquidity": 10000,  # $10k minimum liquidity
    "binance_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],  # Cryptos to track

    # KELLY CRITERION CONFIG - Optimal position sizing based on edge
    # Research: 15% Kelly designed for $10M+ funds. For $1k, need 40% to generate
    # positions above $50 minimum. Confidence used as GATE only, not multiplier.
    "use_kelly": True,               # Enable Kelly Criterion position sizing
    "kelly_fraction": 0.40,          # 40% Kelly (was 15% - too conservative for $1k bankroll)
    "kelly_min_edge": 0.02,          # 2% edge minimum (was 3%)
    "kelly_max_position": 0.20,      # 20% of bankroll per trade (was 15%)

    # MEAN REVERSION CONFIG (OPTIMIZED from backtest: +52% return, 1.05 Sharpe)
    # Backtest date: 2026-02-11, 50 markets, 30-day period
    "mean_reversion_low": 0.30,      # Buy YES when price < 30%
    "mean_reversion_high": 0.70,     # Buy NO when price > 70%
    "mean_reversion_tp": 0.10,       # 10% take profit (optimized)
    "mean_reversion_sl": -0.05,      # 5% stop loss (tighter = better)
}

# ============================================================
# PORTFOLIO STATE
# ============================================================

class Portfolio:
    """Tracks simulated portfolio state."""

    def __init__(self, initial_balance: float = 1000.0, data_file: str = "portfolio.json"):
        self.data_file = Path(__file__).parent / "data" / data_file
        self.data_file.parent.mkdir(exist_ok=True)

        # Load or initialize
        if self.data_file.exists():
            self._load()
        else:
            self.balance = initial_balance
            self.initial_balance = initial_balance
            self.positions: Dict[str, dict] = {}
            self.trade_history: List[dict] = []
            self.metrics = {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "max_drawdown": 0.0,
                "peak_balance": initial_balance,
            }
            # Strategy-level tracking for A/B testing
            self.strategy_metrics = {
                "NEAR_CERTAIN": {"trades": 0, "wins": 0, "pnl": 0.0},
                "NEAR_ZERO": {"trades": 0, "wins": 0, "pnl": 0.0},
                "DIP_BUY": {"trades": 0, "wins": 0, "pnl": 0.0},
                "VOLUME_SURGE": {"trades": 0, "wins": 0, "pnl": 0.0},
                "MID_RANGE": {"trades": 0, "wins": 0, "pnl": 0.0},
                "DUAL_SIDE_ARB": {"trades": 0, "wins": 0, "pnl": 0.0},  # Account88888 strategy
                "MARKET_MAKER": {"trades": 0, "wins": 0, "pnl": 0.0},  # Spread capture strategy
                "BINANCE_ARB": {"trades": 0, "wins": 0, "pnl": 0.0},   # Crypto price arbitrage
            }
            self._save()

    def _load(self):
        with open(self.data_file, "r") as f:
            data = json.load(f)
        self.balance = data["balance"]
        self.initial_balance = data["initial_balance"]
        self.positions = data["positions"]
        self.trade_history = data["trade_history"]
        self.metrics = data["metrics"]
        self.strategy_metrics = data.get("strategy_metrics", {
            "NEAR_CERTAIN": {"trades": 0, "wins": 0, "pnl": 0.0},
            "NEAR_ZERO": {"trades": 0, "wins": 0, "pnl": 0.0},
            "DIP_BUY": {"trades": 0, "wins": 0, "pnl": 0.0},
            "VOLUME_SURGE": {"trades": 0, "wins": 0, "pnl": 0.0},
            "MID_RANGE": {"trades": 0, "wins": 0, "pnl": 0.0},
            "DUAL_SIDE_ARB": {"trades": 0, "wins": 0, "pnl": 0.0},
            "MARKET_MAKER": {"trades": 0, "wins": 0, "pnl": 0.0},
            "BINANCE_ARB": {"trades": 0, "wins": 0, "pnl": 0.0},
        })
        # Ensure new strategies exist if loading old portfolio
        if "MID_RANGE" not in self.strategy_metrics:
            self.strategy_metrics["MID_RANGE"] = {"trades": 0, "wins": 0, "pnl": 0.0}
        if "DUAL_SIDE_ARB" not in self.strategy_metrics:
            self.strategy_metrics["DUAL_SIDE_ARB"] = {"trades": 0, "wins": 0, "pnl": 0.0}
        if "MARKET_MAKER" not in self.strategy_metrics:
            self.strategy_metrics["MARKET_MAKER"] = {"trades": 0, "wins": 0, "pnl": 0.0}
        if "BINANCE_ARB" not in self.strategy_metrics:
            self.strategy_metrics["BINANCE_ARB"] = {"trades": 0, "wins": 0, "pnl": 0.0}
        if "MEAN_REVERSION" not in self.strategy_metrics:
            self.strategy_metrics["MEAN_REVERSION"] = {"trades": 0, "wins": 0, "pnl": 0.0}

    def _save(self):
        data = {
            "balance": self.balance,
            "initial_balance": self.initial_balance,
            "positions": self.positions,
            "trade_history": self.trade_history,
            "metrics": self.metrics,
            "strategy_metrics": self.strategy_metrics,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        with open(self.data_file, "w") as f:
            json.dump(data, f, indent=2)

    def buy(self, condition_id: str, question: str, side: str, price: float, amount: float, reason: str, strategy: str = "UNKNOWN") -> dict:
        """Execute a simulated buy order."""
        if amount > self.balance:
            return {"success": False, "error": "Insufficient balance"}

        shares = amount / price

        position = {
            "condition_id": condition_id,
            "question": question[:80],
            "side": side,
            "entry_price": price,
            "shares": shares,
            "cost_basis": amount,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "strategy": strategy,  # Track which strategy opened this position
        }

        self.positions[condition_id] = position
        self.balance -= amount

        self._save()

        return {"success": True, "position": position}

    def sell(self, condition_id: str, current_price: float, reason: str) -> dict:
        """Execute a simulated sell order."""
        if condition_id not in self.positions:
            return {"success": False, "error": "Position not found"}

        position = self.positions[condition_id]
        proceeds = position["shares"] * current_price
        pnl = proceeds - position["cost_basis"]
        pnl_pct = pnl / position["cost_basis"] * 100
        strategy = position.get("strategy", "UNKNOWN")

        # Record trade with strategy info
        trade = {
            "condition_id": condition_id,
            "question": position["question"],
            "side": position["side"],
            "entry_price": position["entry_price"],
            "exit_price": current_price,
            "shares": position["shares"],
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "entry_time": position["entry_time"],
            "exit_time": datetime.now(timezone.utc).isoformat(),
            "exit_reason": reason,
            "strategy": strategy,
        }

        self.trade_history.append(trade)

        # Update strategy-level metrics for A/B testing
        if strategy in self.strategy_metrics:
            self.strategy_metrics[strategy]["trades"] += 1
            self.strategy_metrics[strategy]["pnl"] += pnl
            if pnl > 0:
                self.strategy_metrics[strategy]["wins"] += 1
        self.balance += proceeds

        # Update metrics
        self.metrics["total_trades"] += 1
        self.metrics["total_pnl"] += pnl
        if pnl > 0:
            self.metrics["winning_trades"] += 1
        else:
            self.metrics["losing_trades"] += 1

        # Track drawdown
        if self.balance > self.metrics["peak_balance"]:
            self.metrics["peak_balance"] = self.balance
        drawdown = (self.metrics["peak_balance"] - self.balance) / self.metrics["peak_balance"]
        if drawdown > self.metrics["max_drawdown"]:
            self.metrics["max_drawdown"] = drawdown

        del self.positions[condition_id]
        self._save()

        return {"success": True, "trade": trade}

    def get_unrealized_pnl(self, current_prices: Dict[str, float]) -> float:
        """Calculate unrealized P&L across all positions."""
        total = 0.0
        for cid, pos in self.positions.items():
            if cid in current_prices:
                current_value = pos["shares"] * current_prices[cid]
                total += current_value - pos["cost_basis"]
        return total

    def get_position_pnl(self, condition_id: str, current_price: float) -> Optional[float]:
        """Get P&L percentage for a position."""
        if condition_id not in self.positions:
            return None
        pos = self.positions[condition_id]
        current_value = pos["shares"] * current_price
        return (current_value - pos["cost_basis"]) / pos["cost_basis"]

    def get_summary(self) -> dict:
        """Get portfolio summary."""
        total_value = self.balance + sum(p["cost_basis"] for p in self.positions.values())
        roi = (total_value - self.initial_balance) / self.initial_balance * 100

        win_rate = 0
        if self.metrics["total_trades"] > 0:
            win_rate = self.metrics["winning_trades"] / self.metrics["total_trades"] * 100

        return {
            "balance": round(self.balance, 2),
            "total_value": round(total_value, 2),
            "initial_balance": self.initial_balance,
            "roi_pct": round(roi, 2),
            "open_positions": len(self.positions),
            "total_trades": self.metrics["total_trades"],
            "win_rate": round(win_rate, 1),
            "total_pnl": round(self.metrics["total_pnl"], 2),
            "max_drawdown_pct": round(self.metrics["max_drawdown"] * 100, 2),
            "strategy_metrics": self.strategy_metrics,
        }

    def get_strategy_report(self) -> str:
        """Get A/B test report for all strategies."""
        lines = ["STRATEGY PERFORMANCE (A/B Test):"]
        lines.append("-" * 50)
        for strategy, metrics in self.strategy_metrics.items():
            trades = metrics["trades"]
            wins = metrics["wins"]
            pnl = metrics["pnl"]
            win_rate = (wins / trades * 100) if trades > 0 else 0
            lines.append(f"  {strategy:15} | Trades: {trades:3} | Win: {win_rate:5.1f}% | P&L: ${pnl:+.2f}")
        return "\n".join(lines)


# ============================================================
# MARKET SCANNER
# ============================================================

class MarketScanner:
    """Scans Polymarket for trading opportunities."""

    GAMMA_API = "https://gamma-api.polymarket.com/markets"
    BINANCE_API = "https://api.binance.com/api/v3/ticker/price"

    def __init__(self):
        self._binance_cache = {}  # Cache for Binance prices
        # MEAN_REVERSION cooldown tracking — prevents death loop on same market
        self.mr_cooldowns = {}  # {condition_id: last_exit_timestamp}
        self.mr_entry_counts = {}  # {condition_id: number_of_entries}
        self.MR_COOLDOWN_HOURS = 48
        self.MR_MAX_ENTRIES = 2

    async def get_active_markets(self) -> List[dict]:
        """Fetch active markets with good liquidity."""
        try:
            async with aiohttp.ClientSession() as session:
                params = {"limit": 100, "active": "true", "closed": "false"}
                async with session.get(self.GAMMA_API, params=params, timeout=15) as resp:
                    if resp.status == 200:
                        markets = await resp.json()
                        # Filter for liquidity and parse token IDs
                        result = []
                        for m in markets:
                            if float(m.get("liquidityNum") or 0) >= CONFIG["min_liquidity"]:
                                # Parse clobTokenIds for live order placement
                                raw_ids = m.get("clobTokenIds", "[]")
                                if isinstance(raw_ids, str):
                                    try:
                                        token_ids = json.loads(raw_ids)
                                    except (json.JSONDecodeError, TypeError):
                                        token_ids = []
                                else:
                                    token_ids = raw_ids or []
                                m["_token_id_yes"] = token_ids[0] if len(token_ids) > 0 else None
                                m["_token_id_no"] = token_ids[1] if len(token_ids) > 1 else None
                                result.append(m)
                        return result
        except Exception as e:
            print(f"[SCANNER] Error: {e}")
        return []

    async def get_market_price(self, condition_id: str) -> Optional[float]:
        """Get current YES price for a market."""
        try:
            # Fetch all active markets and find the one with matching conditionId
            # (The API doesn't properly filter by conditionId parameter)
            async with aiohttp.ClientSession() as session:
                params = {"limit": 200, "active": "true", "closed": "false"}
                async with session.get(self.GAMMA_API, params=params, timeout=15) as resp:
                    if resp.status == 200:
                        markets = await resp.json()
                        for m in markets:
                            if m.get("conditionId") == condition_id:
                                return float(m.get("bestAsk") or 0)
        except Exception as e:
            print(f"[SCANNER] Price fetch error: {e}")
        return None

    def calculate_annualized_return(self, raw_return: float, days: int) -> float:
        """
        Calculate annualized return using compound interest formula.

        Formula: annualized = (1 + return)^(365/days) - 1

        Examples:
        - 2% in 18 days  = (1.02)^(365/18) - 1 = 49.5% annualized
        - 2% in 90 days  = (1.02)^(365/90) - 1 = 8.3% annualized
        - 2% in 324 days = (1.02)^(365/324) - 1 = 2.3% annualized

        This ensures we prioritize fast-resolving markets over slow ones.
        """
        if days <= 0:
            return 0.0
        if raw_return <= -1:
            return -1.0
        try:
            annualized = ((1 + raw_return) ** (365 / days)) - 1
            return min(annualized, 10.0)  # Cap at 1000% to avoid infinity
        except:
            return 0.0

    async def get_binance_prices(self) -> Dict[str, float]:
        """Fetch current Binance spot prices for major cryptos."""
        symbols = CONFIG.get("binance_symbols", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        prices = {}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.BINANCE_API, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data:
                            if item["symbol"] in symbols:
                                prices[item["symbol"]] = float(item["price"])
        except Exception as e:
            print(f"[BINANCE] Price fetch error: {e}")

        self._binance_cache = prices
        return prices

    def extract_crypto_target(self, question: str) -> Optional[Dict]:
        """
        Extract crypto symbol and price target from market question.
        Returns: {symbol: "BTCUSDT", target: 100000, direction: "ABOVE"}
        """
        import re
        q_lower = question.lower()

        # Identify crypto
        symbol = None
        if "bitcoin" in q_lower or "btc" in q_lower:
            symbol = "BTCUSDT"
        elif "ethereum" in q_lower or " eth " in q_lower or "eth " in q_lower:
            symbol = "ETHUSDT"
        elif "solana" in q_lower or "sol" in q_lower:
            symbol = "SOLUSDT"

        if not symbol:
            return None

        # Must be a price-related market
        if not any(kw in q_lower for kw in ["price", "above", "below", "reach", "hit", "$"]):
            return None

        # Extract price target (e.g., $100,000 or $100k)
        price_match = re.search(r'\$([0-9,]+(?:\.[0-9]+)?)\s*([km])?', q_lower.replace(',', ''))
        if not price_match:
            return None

        target = float(price_match.group(1))
        multiplier = price_match.group(2)
        if multiplier == 'k':
            target *= 1000
        elif multiplier == 'm':
            target *= 1000000

        # Determine direction
        direction = "ABOVE"
        if "below" in q_lower or "under" in q_lower:
            direction = "BELOW"

        return {"symbol": symbol, "target": target, "direction": direction}

    def calculate_binance_implied_prob(self, current_price: float, target: float,
                                        direction: str, days_to_expiry: int = 30) -> float:
        """
        Calculate implied probability that price will reach target.
        Uses distance-based model with ~60% annual volatility for crypto.
        """
        if current_price <= 0 or target <= 0:
            return 0.5

        daily_vol = 0.03  # ~3% daily volatility for crypto
        expected_move = daily_vol * (days_to_expiry ** 0.5)

        if direction == "ABOVE":
            if current_price >= target:
                prob = 0.85 + min(0.10, (current_price - target) / target * 0.1)
            else:
                distance = (target - current_price) / current_price
                prob = max(0.05, 0.5 - distance / expected_move * 0.5)
        else:  # BELOW
            if current_price <= target:
                prob = 0.85 + min(0.10, (target - current_price) / current_price * 0.1)
            else:
                distance = (current_price - target) / current_price
                prob = max(0.05, 0.5 - distance / expected_move * 0.5)

        return min(0.95, max(0.05, prob))

    def find_opportunities(self, markets: List[dict], binance_prices: Dict[str, float] = None) -> List[dict]:
        """Identify trading opportunities with capital efficiency scoring."""
        opportunities = []
        binance_prices = binance_prices or self._binance_cache or {}
        now = datetime.now(timezone.utc)

        # Build condition_id → token_id mapping for live order placement
        token_id_map = {}
        for m in markets:
            cid = m.get("conditionId", "")
            if cid:
                token_id_map[cid] = {
                    "token_id_yes": m.get("_token_id_yes"),
                    "token_id_no": m.get("_token_id_no"),
                }

        for m in markets:
            condition_id = m.get("conditionId", "")
            question = m.get("question", "")
            best_ask = float(m.get("bestAsk") or 0)
            best_bid = float(m.get("bestBid") or 0)
            liquidity = float(m.get("liquidityNum") or 0)
            volume_24h = float(m.get("volume24hr") or 0)
            price_change = float(m.get("oneDayPriceChange") or 0)

            # Parse resolution date for capital efficiency calculation
            end_date_str = m.get("endDate", "")
            days_to_resolve = 365  # Default to 1 year if unknown
            if end_date_str:
                try:
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    days_to_resolve = max(1, (end_date - now).days)
                except:
                    pass

            # CAPITAL EFFICIENCY FILTER: Skip long-term markets for resolution strategies
            skip_resolution_strategies = days_to_resolve > CONFIG["max_days_to_resolve"]

            # Strategy 1: Near-certain arbitrage (YES at 95%+)
            # ONLY for markets resolving within max_days_to_resolve
            if best_ask >= CONFIG["near_certain_min"] and not skip_resolution_strategies:
                expected_return = (1.0 - best_ask) / best_ask
                annualized = self.calculate_annualized_return(expected_return, days_to_resolve)

                # Only take if annualized return is good enough
                if annualized >= CONFIG["min_annualized_return"]:
                    opportunities.append({
                        "condition_id": condition_id,
                        "question": question,
                        "strategy": "NEAR_CERTAIN",
                        "side": "YES",
                        "price": best_ask,
                        "expected_return": expected_return,
                        "annualized_return": annualized,
                        "days_to_resolve": days_to_resolve,
                        "liquidity": liquidity,
                        "confidence": 0.95,
                        "reason": f"Near-certain {best_ask:.0%}, {days_to_resolve}d, {annualized:.0%} APY"
                    })

            # Strategy 2: Near-zero arbitrage (YES at 0-5% = NO at 95-100%)
            # ONLY for markets resolving within max_days_to_resolve
            if best_ask > 0 and best_ask <= CONFIG["near_zero_max"] and not skip_resolution_strategies:
                no_price = 1.0 - best_bid if best_bid > 0 else 1.0 - best_ask
                # Only trade if NO price is reasonable (below 98%)
                if no_price < 0.98:
                    expected_return = (1.0 - no_price) / no_price
                    annualized = self.calculate_annualized_return(expected_return, days_to_resolve)

                    # Only take if annualized return is good enough
                    if annualized >= CONFIG["min_annualized_return"]:
                        opportunities.append({
                            "condition_id": condition_id,
                            "question": question,
                            "strategy": "NEAR_ZERO",
                            "side": "NO",
                            "price": no_price,
                            "expected_return": expected_return,
                            "annualized_return": annualized,
                            "days_to_resolve": days_to_resolve,
                            "liquidity": liquidity,
                            "confidence": 0.95,
                            "reason": f"Near-zero YES {best_ask:.0%}, {days_to_resolve}d, {annualized:.0%} APY"
                        })

            # Strategy 3: Dip buying (price dropped >5%)
            # Active trading - assume 7-day hold for TP/SL
            if price_change < CONFIG["dip_threshold"] and volume_24h > 30000:
                expected_return = abs(price_change)
                annualized = self.calculate_annualized_return(expected_return, 7)  # 7-day target
                opportunities.append({
                    "condition_id": condition_id,
                    "question": question,
                    "strategy": "DIP_BUY",
                    "side": "YES",
                    "price": best_ask,
                    "expected_return": expected_return,
                    "annualized_return": annualized,
                    "days_to_resolve": 7,  # Active trading target
                    "liquidity": liquidity,
                    "confidence": 0.65,
                    "reason": f"Dip {price_change:.0%}, {annualized:.0%} APY target"
                })

            # Strategy 4: Volume surge (smart money)
            # Active trading - assume 7-day hold for TP/SL
            hourly_avg = volume_24h / 24 if volume_24h > 0 else 0
            volume_1h = float(m.get("volume1hr") or hourly_avg)
            if hourly_avg > 0 and volume_1h > hourly_avg * CONFIG["volume_surge_mult"] and abs(price_change) < 0.05:
                expected_return = 0.10
                annualized = self.calculate_annualized_return(expected_return, 7)  # 7-day target
                opportunities.append({
                    "condition_id": condition_id,
                    "question": question,
                    "strategy": "VOLUME_SURGE",
                    "side": "YES" if price_change >= 0 else "NO",
                    "price": best_ask if price_change >= 0 else best_bid,
                    "expected_return": expected_return,
                    "annualized_return": annualized,
                    "days_to_resolve": 7,  # Active trading target
                    "liquidity": liquidity,
                    "confidence": 0.60,
                    "reason": f"Volume {volume_1h/hourly_avg:.1f}x, {annualized:.0%} APY target"
                })

            # Strategy 5: Mid-range active trading
            # Fastest capital turnover - 5% TP in ~3-7 days
            if (CONFIG["mid_range_min"] <= best_ask <= CONFIG["mid_range_max"] and
                volume_24h >= CONFIG["min_24h_volume"]):
                expected_return = CONFIG["take_profit_pct"]  # 5% take profit
                annualized = self.calculate_annualized_return(expected_return, 5)  # 5-day target
                # Trade with momentum: buy YES if price going up, NO if going down
                if price_change > 0.005:  # 0.5%+ upward momentum
                    opportunities.append({
                        "condition_id": condition_id,
                        "question": question,
                        "strategy": "MID_RANGE",
                        "side": "YES",
                        "price": best_ask,
                        "expected_return": expected_return,
                        "annualized_return": annualized,
                        "days_to_resolve": 5,  # Fast active trading
                        "liquidity": liquidity,
                        "confidence": 0.55,
                        "reason": f"MID UP {price_change:+.1%}, {annualized:.0%} APY target"
                    })
                elif price_change < -0.005:  # 0.5%+ downward momentum
                    no_price = 1.0 - best_bid if best_bid > 0 else 1.0 - best_ask
                    opportunities.append({
                        "condition_id": condition_id,
                        "question": question,
                        "strategy": "MID_RANGE",
                        "side": "NO",
                        "price": no_price,
                        "expected_return": expected_return,
                        "annualized_return": annualized,
                        "days_to_resolve": 5,  # Fast active trading
                        "liquidity": liquidity,
                        "confidence": 0.55,
                        "reason": f"MID DOWN {price_change:+.1%}, {annualized:.0%} APY target"
                    })

            # Strategy 5.5: MEAN_REVERSION (OPTIMIZED - Best performing in backtest!)
            # Buys YES when price < 30% (expects reversion toward 50%)
            # Buys NO when price > 70% (expects reversion toward 50%)
            # Backtest results: +52% return, 1.05 Sharpe, 18.6% max drawdown
            # Optimized parameters: TP=10%, SL=-5%, Kelly=0.15
            if volume_24h >= CONFIG.get("min_24h_volume", 10000):
                mean_reversion_low = CONFIG.get("mean_reversion_low", 0.30)
                mean_reversion_high = CONFIG.get("mean_reversion_high", 0.70)

                # Cooldown check: skip if we recently exited this market or entered too many times
                mr_on_cooldown = False
                if condition_id in self.mr_cooldowns:
                    elapsed_h = (datetime.now(timezone.utc) - self.mr_cooldowns[condition_id]).total_seconds() / 3600
                    if elapsed_h < self.MR_COOLDOWN_HOURS:
                        mr_on_cooldown = True
                if self.mr_entry_counts.get(condition_id, 0) >= self.MR_MAX_ENTRIES:
                    mr_on_cooldown = True

                if not mr_on_cooldown and best_ask < mean_reversion_low and best_ask > 0.05:
                    # Price too low, expect reversion up
                    expected_return = 0.10  # 10% take profit target
                    annualized = self.calculate_annualized_return(expected_return, 7)
                    self.mr_entry_counts[condition_id] = self.mr_entry_counts.get(condition_id, 0) + 1
                    opportunities.append({
                        "condition_id": condition_id,
                        "question": question,
                        "strategy": "MEAN_REVERSION",
                        "side": "YES",
                        "price": best_ask,
                        "expected_return": expected_return,
                        "annualized_return": annualized,
                        "days_to_resolve": 7,
                        "liquidity": liquidity,
                        "confidence": 0.60,
                        "reason": f"MEAN_REV: Price {best_ask:.0%} < 30%, expect reversion"
                    })
                elif not mr_on_cooldown and best_ask > mean_reversion_high and best_ask < 0.95:
                    # Price too high, expect reversion down (buy NO)
                    no_price = 1.0 - best_bid if best_bid > 0 else 1.0 - best_ask
                    expected_return = 0.10
                    annualized = self.calculate_annualized_return(expected_return, 7)
                    self.mr_entry_counts[condition_id] = self.mr_entry_counts.get(condition_id, 0) + 1
                    opportunities.append({
                        "condition_id": condition_id,
                        "question": question,
                        "strategy": "MEAN_REVERSION",
                        "side": "NO",
                        "price": no_price,
                        "expected_return": expected_return,
                        "annualized_return": annualized,
                        "days_to_resolve": 7,
                        "liquidity": liquidity,
                        "confidence": 0.60,
                        "reason": f"MEAN_REV: Price {best_ask:.0%} > 70%, expect reversion"
                    })

            # Strategy 6: DUAL-SIDE ARBITRAGE (Account88888's $645K strategy!)
            # When YES + NO < $1.00, buy BOTH sides for GUARANTEED profit
            # One side MUST pay $1.00, so profit = $1.00 - (YES + NO)
            if best_ask > 0 and best_bid > 0 and liquidity >= CONFIG["dual_side_min_liquidity"]:
                yes_price = best_ask  # Cost to buy YES
                no_price = 1.0 - best_bid  # Cost to buy NO (inverse of YES bid)
                total_cost = yes_price + no_price

                # Check if there's arbitrage (total < $1.00 minus min profit threshold)
                if total_cost < (1.0 - CONFIG["dual_side_min_profit"]):
                    profit_per_dollar = 1.0 - total_cost
                    profit_pct = profit_per_dollar / total_cost
                    # This is INSTANT profit - no waiting for resolution needed
                    # Annualized is theoretically infinite, cap at 1000%
                    annualized = min(self.calculate_annualized_return(profit_pct, 1), 10.0)

                    opportunities.append({
                        "condition_id": condition_id,
                        "question": question,
                        "strategy": "DUAL_SIDE_ARB",
                        "side": "BOTH",  # Special: buy both YES and NO
                        "price": total_cost,  # Total cost for both sides
                        "yes_price": yes_price,
                        "no_price": no_price,
                        "expected_return": profit_pct,
                        "annualized_return": annualized,
                        "days_to_resolve": 1,  # Instant profit when market resolves
                        "liquidity": liquidity,
                        "confidence": 0.99,  # Near-guaranteed profit
                        "reason": f"DUAL ARB: YES ${yes_price:.3f} + NO ${no_price:.3f} = ${total_cost:.3f} (profit {profit_pct:.1%})"
                    })

            # Strategy 7: MARKET MAKER (Based on research: 10-200% APY)
            # Place limit orders on both sides, profit from spread when filled
            # Key: High volume markets for reliable fills, reasonable spread

            # HARD FILTER: Resolution time (MM needs fast capital turnover)
            mm_max_days = CONFIG.get("mm_max_days_to_resolve", 30)
            if days_to_resolve > mm_max_days:
                pass  # Skip this market for MM — too far out
            else:
                # QUALITY FILTER: Skip meme/absurd markets
                q_lower = question.lower()
                excluded_topics = [
                    "jesus", "christ", "god return", "rapture", "second coming",
                    "alien contact", "extraterrestrial", "supernatural",
                    "flat earth", "illuminati", "$1m", "$1,000,000",
                    "million dollars", "billion dollar"
                ]
                is_meme_market = any(topic in q_lower for topic in excluded_topics)

                # PREFERRED TOPICS: Finance, Politics, Crypto (boost confidence)
                preferred_topics = [
                    "bitcoin", "btc", "ethereum", "eth", "crypto", "price",
                    "trump", "biden", "election", "president", "congress",
                    "fed", "interest rate", "inflation", "tariff", "economy"
                ]
                is_preferred = any(topic in q_lower for topic in preferred_topics)

                mm_min, mm_max = CONFIG["mm_price_range"]
                if (not is_meme_market and  # Skip meme markets
                    mm_min <= best_ask <= mm_max and
                    best_bid > 0 and
                    volume_24h >= CONFIG["mm_min_volume_24h"] and
                    liquidity >= CONFIG["mm_min_liquidity"]):

                    spread = best_ask - best_bid
                    spread_pct = spread / ((best_ask + best_bid) / 2) if (best_ask + best_bid) > 0 else 0
                    mid_price = (best_ask + best_bid) / 2

                    # Only MM if spread is in our target range (2-8%)
                    if CONFIG["mm_min_spread"] <= spread_pct <= CONFIG["mm_max_spread"]:
                        expected_return = CONFIG["mm_target_profit"]
                        hours_to_fill = 4
                        days_to_fill = hours_to_fill / 24
                        annualized = min(self.calculate_annualized_return(expected_return, max(1, int(days_to_fill * 10))), 10.0)

                        opportunities.append({
                            "condition_id": condition_id,
                            "question": question,
                            "strategy": "MARKET_MAKER",
                            "side": "MM",
                            "price": mid_price,
                            "best_bid": best_bid,
                            "best_ask": best_ask,
                            "spread": spread,
                            "spread_pct": spread_pct,
                            "mm_bid": round(mid_price - max(mid_price * 0.02, 0.01), 3),
                            "mm_ask": round(mid_price + max(mid_price * 0.02, 0.01), 3),
                            "expected_return": expected_return,
                            "annualized_return": annualized,
                            "days_to_resolve": days_to_resolve,
                            "end_date": end_date_str,
                            "liquidity": liquidity,
                            "volume_24h": volume_24h,
                            "confidence": 0.80 if is_preferred else 0.65,
                            "reason": f"MM: Spread {spread_pct:.1%}, Vol ${volume_24h/1000:.0f}k, {days_to_resolve}d to resolve"
                        })

            # Strategy 8: BINANCE ARBITRAGE (Crypto price lag arbitrage)
            # Compare Polymarket crypto predictions to Binance spot prices
            # When Polymarket lags behind real price movement → buy the mispriced side
            if binance_prices:
                target_info = self.extract_crypto_target(question)
                if target_info and liquidity >= CONFIG["binance_min_liquidity"]:
                    symbol = target_info["symbol"]
                    target_price = target_info["target"]
                    direction = target_info["direction"]

                    current_price = binance_prices.get(symbol, 0)
                    if current_price > 0:
                        # Calculate what Binance implies the probability should be
                        binance_prob = self.calculate_binance_implied_prob(
                            current_price, target_price, direction
                        )

                        # Polymarket probability = best_ask (price to buy YES)
                        poly_prob = best_ask

                        # Edge = difference between Binance implied and Polymarket
                        edge = binance_prob - poly_prob

                        if abs(edge) >= CONFIG["binance_min_edge"]:
                            # Positive edge = Polymarket underpricing YES (buy YES)
                            # Negative edge = Polymarket overpricing YES (buy NO)
                            side = "YES" if edge > 0 else "NO"
                            entry_price = best_ask if side == "YES" else (1 - best_bid)

                            opportunities.append({
                                "condition_id": condition_id,
                                "question": question,
                                "strategy": "BINANCE_ARB",
                                "side": side,
                                "price": entry_price,
                                "best_bid": best_bid,
                                "best_ask": best_ask,
                                "binance_price": current_price,
                                "target_price": target_price,
                                "binance_prob": round(binance_prob, 3),
                                "poly_prob": round(poly_prob, 3),
                                "edge": round(edge * 100, 2),  # As percentage
                                "expected_return": abs(edge),
                                "annualized_return": min(abs(edge) * 12, 10.0),  # Fast turnover
                                "days_to_resolve": 7,  # Crypto markets resolve faster
                                "liquidity": liquidity,
                                "volume_24h": volume_24h,
                                "confidence": min(0.95, 0.70 + abs(edge)),  # Higher edge = higher confidence
                                "reason": f"BINANCE_ARB: {symbol} ${current_price:,.0f} → ${target_price:,.0f} | Edge: {edge*100:+.1f}%"
                            })

        # Ensure strategy diversity: pick best from each strategy
        by_strategy = {}
        for opp in opportunities:
            strat = opp["strategy"]
            if strat not in by_strategy:
                by_strategy[strat] = []
            by_strategy[strat].append(opp)

        # Sort each strategy's opportunities by ANNUALIZED RETURN (capital efficiency!)
        # For strategies without annualized_return, fall back to confidence
        for strat in by_strategy:
            by_strategy[strat].sort(
                key=lambda x: x.get("annualized_return", x.get("confidence", 0)),
                reverse=True
            )

        # Pick top N from each strategy (diversity)
        # DUAL_SIDE_ARB first - guaranteed profit
        # BINANCE_ARB second - fast crypto arbitrage
        # MARKET_MAKER third - spread capture
        diverse_opps = []
        # Allow more slots for fast-turnover and high-hit-rate strategies
        fast_strats = {"MARKET_MAKER": 4, "BINANCE_ARB": 3, "NEAR_CERTAIN": 3, "NEAR_ZERO": 3}

        # DEBUG: Log opportunities by strategy
        strategy_summary = {}
        all_strategies = ["DUAL_SIDE_ARB", "MARKET_MAKER", "MEAN_REVERSION",
                          "NEAR_CERTAIN", "NEAR_ZERO", "MID_RANGE", "VOLUME_SURGE", "DIP_BUY"]
        # BINANCE_ARB removed: Polymarket's 3.15% dynamic crypto fees killed the edge

        # FILTER: If STRATEGY_FILTER env var is set, only use that strategy
        if STRATEGY_FILTER:
            all_strategies = [STRATEGY_FILTER] if STRATEGY_FILTER in all_strategies else []

        for strat in all_strategies:
            count = len(by_strategy.get(strat, []))
            strategy_summary[strat] = count
            if strat in by_strategy:
                limit = fast_strats.get(strat, 2)
                diverse_opps.extend(by_strategy[strat][:limit])

        # Remove duplicates while preserving order
        seen = set()
        result = []
        for opp in diverse_opps:
            if opp["condition_id"] not in seen:
                seen.add(opp["condition_id"])
                result.append(opp)

        # Final sort by annualized return across all strategies
        result.sort(key=lambda x: x.get("annualized_return", x.get("confidence", 0)), reverse=True)

        # Inject CLOB token IDs for live order placement
        for opp in result:
            ids = token_id_map.get(opp["condition_id"], {})
            opp["token_id_yes"] = ids.get("token_id_yes")
            opp["token_id_no"] = ids.get("token_id_no")

        # Log strategy opportunity summary
        print("\n[OPPS] Strategy Opportunities Found:")
        for strat in all_strategies:
            count = strategy_summary.get(strat, 0)
            print(f"       {strat:15} : {count:2d} opportunities")
        if STRATEGY_FILTER:
            print(f"       [FILTERED to: {STRATEGY_FILTER}]")

        return result[:10]


# ============================================================
# NEWS ANALYZER
# ============================================================

class NewsAnalyzer:
    """Fetches and analyzes news with Claude AI."""

    NEWS_API = "https://newsapi.org/v2/everything"

    def __init__(self):
        self.claude = ClaudeAnalyzer()
        self.news_api_key = os.getenv("NEWS_API_KEY", "")

    async def analyze_market(self, question: str) -> Optional[dict]:
        """Analyze news sentiment for a market question."""
        if not self.news_api_key:
            return None

        # Extract search terms
        words = question.lower().replace("?", "").split()
        stopwords = {"will", "the", "be", "a", "an", "in", "on", "by", "to", "of", "what", "how"}
        keywords = [w for w in words if w not in stopwords and len(w) > 2][:3]
        query = " ".join(keywords)

        try:
            # Fetch news
            async with aiohttp.ClientSession() as session:
                params = {
                    "q": query,
                    "sortBy": "publishedAt",
                    "language": "en",
                    "pageSize": "3",
                    "apiKey": self.news_api_key
                }
                async with session.get(self.NEWS_API, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    articles = data.get("articles", [])

            if not articles:
                return None

            # Analyze with Claude (only first article to save budget)
            article = articles[0]
            result = await self.claude.analyze_news(
                headline=article.get("title", ""),
                description=article.get("description", "")[:200],
                market_question=question
            )

            result["headline"] = article.get("title", "")[:80]
            return result

        except Exception as e:
            print(f"[NEWS] Error: {e}")
            return None


# ============================================================
# TRADING ENGINE
# ============================================================

class TradingEngine:
    """Main trading engine orchestrating all components."""

    def __init__(self, live: bool = False):
        self.live = live

        # Use strategy-specific portfolio file if filtering
        if STRATEGY_FILTER:
            portfolio_file = f"portfolio_{STRATEGY_FILTER.lower()}.json"
        else:
            portfolio_file = "portfolio_live.json" if live else "portfolio_sim.json"

        self.portfolio = Portfolio(
            initial_balance=CONFIG["initial_balance"],
            data_file=portfolio_file
        )
        self.scanner = MarketScanner()
        self.news = NewsAnalyzer()
        self.running = False

        # AI market screening (Gemini - free tier)
        if CONFIG.get("mm_ai_screen"):
            try:
                from core.gemini_analyzer import GeminiAnalyzer
                self.gemini = GeminiAnalyzer()
            except Exception:
                self.gemini = None
        else:
            self.gemini = None

        # Live trading components
        if self.live:
            from core.async_executor import get_executor
            from core.live_safety import LiveSafety
            self.executor = get_executor()
            self.safety = LiveSafety()
        else:
            self.executor = None
            self.safety = None

        # Snapshot logger — saves real bid/ask/volume every cycle for future backtesting
        self.snapshot_dir = Path(__file__).parent / "data" / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    async def check_exits(self):
        """Check all positions for exit conditions."""
        for condition_id, position in list(self.portfolio.positions.items()):
            # DUAL_SIDE_ARB positions: No TP/SL - profit is locked, just wait for resolution
            if position["side"] == "BOTH":
                # For BOTH positions, payout is always $1.00 per share
                # Profit = shares * $1.00 - cost_basis (guaranteed)
                guaranteed_profit = position["shares"] * 1.0 - position["cost_basis"]
                # 30-day max hold to prevent capital being locked indefinitely
                entry_time_str = position.get("entry_time", "")
                try:
                    entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
                    hold_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
                    if hold_hours >= 30 * 24:  # 30 days
                        result = self.portfolio.sell(condition_id, position["entry_price"], "TIMEOUT")
                        if result["success"]:
                            trade = result["trade"]
                            print(f"[DUAL_ARB] TIMEOUT: {trade['question'][:40]}...")
                            print(f"           Held {hold_hours/24:.0f} days, exiting at cost basis")
                except Exception:
                    pass
                continue

            # MARKET_MAKER positions: Exit when price reaches our ask OR timeout
            if position["side"] == "MM":
                await self._check_mm_exit(condition_id, position)
                continue

            yes_price = await self.scanner.get_market_price(condition_id)
            if yes_price is None:
                continue

            # IMPORTANT: For NO positions, current value = 1 - YES_price
            if position["side"] == "NO":
                current_price = 1.0 - yes_price
            else:
                current_price = yes_price

            pnl_pct = self.portfolio.get_position_pnl(condition_id, current_price)
            if pnl_pct is None:
                continue

            # Take profit (3% now for faster exits)
            if pnl_pct >= CONFIG["take_profit_pct"]:
                result = self.portfolio.sell(condition_id, current_price, "TAKE_PROFIT")
                if result["success"]:
                    trade = result["trade"]
                    print(f"[TRADE] TAKE PROFIT: {trade['question'][:40]}...")
                    print(f"        P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")
                    # Record cooldown for MEAN_REVERSION
                    if position.get("strategy") == "MEAN_REVERSION":
                        self.scanner.mr_cooldowns[condition_id] = datetime.now(timezone.utc)

            # Stop loss (10% now for tighter risk)
            elif pnl_pct <= CONFIG["stop_loss_pct"]:
                result = self.portfolio.sell(condition_id, current_price, "STOP_LOSS")
                if result["success"]:
                    trade = result["trade"]
                    print(f"[TRADE] STOP LOSS: {trade['question'][:40]}...")
                    print(f"        P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")
                    # Record cooldown for MEAN_REVERSION
                    if position.get("strategy") == "MEAN_REVERSION":
                        self.scanner.mr_cooldowns[condition_id] = datetime.now(timezone.utc)

    async def _check_mm_exit(self, condition_id: str, position: dict):
        """
        Check exit conditions for MARKET_MAKER positions.

        Exit when:
        1. Price reaches our ask level (PROFIT - filled!)
        2. Price falls below entry - 3% (STOP LOSS - cut losses)
        3. Hold time exceeds max hours (TIMEOUT - exit at market)

        In live mode, uses order state machine (BUY_PENDING → SELL_PENDING → CLOSED).
        In simulation mode, uses price-based exit logic.
        """
        # LIVE MODE: Delegate to state machine
        if self.live:
            await self._check_mm_exit_live(condition_id, position)
            return

        mm_ask = position.get("mm_ask", position["entry_price"] * 1.01)
        mm_bid = position.get("mm_bid", position["entry_price"])
        entry_time_str = position.get("mm_entry_time", position.get("entry_time", ""))

        # Get current market price
        yes_price = await self.scanner.get_market_price(condition_id)
        if yes_price is None:
            return

        current_price = yes_price  # MM positions are always YES side

        # Calculate hold time
        try:
            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
            hold_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
        except:
            hold_hours = 0

        # EXIT CONDITION 1: Price reached our ask (PROFIT!)
        if current_price >= mm_ask:
            result = self.portfolio.sell(condition_id, mm_ask, "MM_FILLED")
            if result["success"]:
                trade = result["trade"]
                print(f"[MM] FILLED! {trade['question'][:40]}...")
                print(f"     Entry: ${trade['entry_price']:.3f} → Exit: ${mm_ask:.3f}")
                print(f"     P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%) in {hold_hours:.1f}h")
            return

        # EXIT CONDITION 2: Price dropped too much (STOP LOSS)
        # MM positions use tighter stop (3%) since we're trading frequently
        mm_stop_loss = -0.03
        pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]
        if pnl_pct <= mm_stop_loss:
            result = self.portfolio.sell(condition_id, current_price, "MM_STOP")
            if result["success"]:
                trade = result["trade"]
                print(f"[MM] STOP: {trade['question'][:40]}...")
                print(f"     Entry: ${trade['entry_price']:.3f} → Exit: ${current_price:.3f}")
                print(f"     P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%) - Cut loss!")
            return

        # EXIT CONDITION 3: Timeout (didn't fill in time)
        if hold_hours >= CONFIG["mm_max_hold_hours"]:
            result = self.portfolio.sell(condition_id, current_price, "MM_TIMEOUT")
            if result["success"]:
                trade = result["trade"]
                print(f"[MM] TIMEOUT: {trade['question'][:40]}...")
                print(f"     Held {hold_hours:.1f}h without fill, exiting at market")
                print(f"     P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")
            return

    async def _check_mm_exit_live(self, condition_id: str, position: dict):
        """
        Live MM order state machine.

        States:
          BUY_PENDING  → poll buy order → filled? → BUY_FILLED
          BUY_FILLED   → post sell at mm_ask      → SELL_PENDING
          SELL_PENDING → poll sell order → filled? → CLOSED (profit)
                       → price drops 3%?          → cancel sell, exit (stop loss)
                       → 4h timeout?              → cancel sell, exit (timeout)
          BUY_PENDING  → 4h timeout?              → cancel buy (no fill)
        """
        live_state = position.get("live_state", "")
        token_id = position.get("token_id", "")
        mm_ask = position.get("mm_ask", position["entry_price"] * 1.02)

        # Calculate hold time
        entry_time_str = position.get("mm_entry_time", position.get("entry_time", ""))
        try:
            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
            hold_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
        except Exception:
            hold_hours = 0

        if live_state == "BUY_PENDING":
            buy_order_id = position.get("buy_order_id", "")
            if not buy_order_id:
                return

            status = await self.executor.get_order_status(buy_order_id)
            matched = status.get("size_matched", 0)
            original = status.get("original_size", 0)

            if original > 0 and matched >= original * 0.95:
                # Buy order filled
                position["live_state"] = "BUY_FILLED"
                position["actual_fill_price"] = status.get("price", position["entry_price"])
                self.portfolio._save()
                print(f"[MM-LIVE] BUY FILLED: {position['question'][:40]}...")
            elif hold_hours >= CONFIG["mm_max_hold_hours"]:
                # Timeout - cancel unfilled buy
                await self.executor.cancel_order(buy_order_id)
                self.portfolio.balance += position["cost_basis"]
                del self.portfolio.positions[condition_id]
                self.portfolio._save()
                print(f"[MM-LIVE] BUY TIMEOUT: Cancelled unfilled buy after {hold_hours:.1f}h")
            else:
                # Still waiting for buy fill
                if status.get("status") in ("CANCELLED", "CANCELED"):
                    # Order was cancelled externally
                    self.portfolio.balance += position["cost_basis"]
                    del self.portfolio.positions[condition_id]
                    self.portfolio._save()
                    print(f"[MM-LIVE] BUY CANCELLED externally")

        elif live_state == "BUY_FILLED":
            # Post sell order at mm_ask
            if not token_id:
                print(f"[MM-LIVE] ERROR: No token_id for sell order")
                return

            # Track sell retry attempts to avoid infinite loop
            sell_retries = position.get("sell_retries", 0)
            if sell_retries >= 5:
                # Give up on post-only, exit at market to avoid being stuck
                current_price = await self.scanner.get_market_price(condition_id)
                if current_price and current_price > 0:
                    result = self.portfolio.sell(condition_id, current_price, "MM_SELL_FAILED")
                    if result["success"]:
                        trade = result["trade"]
                        if self.live:
                            self.safety.record_trade_pnl(trade["pnl"])
                        print(f"[MM-LIVE] SELL FAILED after 5 retries, exiting: ${trade['pnl']:+.2f}")
                return

            shares = position["shares"]
            result = await self.executor.post_limit_order(
                token_id=token_id, side="SELL", price=mm_ask,
                size=round(shares, 2), post_only=True
            )
            sell_order_id = result.get("orderID", "")
            if sell_order_id:
                position["sell_order_id"] = sell_order_id
                position["live_state"] = "SELL_PENDING"
                position.pop("sell_retries", None)
                self.portfolio._save()
                print(f"[MM-LIVE] SELL POSTED @ ${mm_ask:.3f}: {position['question'][:40]}...")
            else:
                # Post-only rejected (would cross spread) - retry next cycle
                position["sell_retries"] = sell_retries + 1
                self.portfolio._save()
                print(f"[MM-LIVE] SELL REJECTED (attempt {sell_retries + 1}/5): {result.get('error', 'unknown')}")

        elif live_state == "SELL_PENDING":
            sell_order_id = position.get("sell_order_id", "")
            if not sell_order_id:
                return

            status = await self.executor.get_order_status(sell_order_id)
            matched = status.get("size_matched", 0)
            original = status.get("original_size", 0)

            if original > 0 and matched >= original * 0.95:
                # Sell order filled - PROFIT!
                result = self.portfolio.sell(condition_id, mm_ask, "MM_FILLED")
                if result["success"]:
                    trade = result["trade"]
                    self.safety.record_trade_pnl(trade["pnl"])
                    print(f"[MM-LIVE] FILLED! P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")
                return

            # Check stop-loss and timeout while waiting for sell fill
            current_price = await self.scanner.get_market_price(condition_id)
            if current_price is None:
                return

            pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]

            if pnl_pct <= -0.03:
                # STOP LOSS: Cancel sell, exit at best bid
                await self.executor.cancel_order(sell_order_id)
                # Place aggressive sell at best bid
                book = await self.executor.get_order_book(token_id)
                bids = book.get("bids", [])
                exit_price = bids[0][0] if bids else current_price * 0.99
                await self.executor.post_limit_order(
                    token_id=token_id, side="SELL",
                    price=exit_price, size=round(position["shares"], 2),
                    post_only=False  # Allow taker to exit fast
                )
                result = self.portfolio.sell(condition_id, exit_price, "MM_STOP")
                if result["success"]:
                    trade = result["trade"]
                    self.safety.record_trade_pnl(trade["pnl"])
                    print(f"[MM-LIVE] STOP LOSS @ ${exit_price:.3f}: ${trade['pnl']:+.2f}")

            elif hold_hours >= CONFIG["mm_max_hold_hours"]:
                # TIMEOUT: Cancel sell, exit at best bid
                await self.executor.cancel_order(sell_order_id)
                book = await self.executor.get_order_book(token_id)
                bids = book.get("bids", [])
                exit_price = bids[0][0] if bids else current_price * 0.99
                await self.executor.post_limit_order(
                    token_id=token_id, side="SELL",
                    price=exit_price, size=round(position["shares"], 2),
                    post_only=False
                )
                result = self.portfolio.sell(condition_id, exit_price, "MM_TIMEOUT")
                if result["success"]:
                    trade = result["trade"]
                    self.safety.record_trade_pnl(trade["pnl"])
                    print(f"[MM-LIVE] TIMEOUT @ ${exit_price:.3f}: ${trade['pnl']:+.2f}")

            elif status.get("status") in ("CANCELLED", "CANCELED"):
                # Sell order cancelled externally - re-enter BUY_FILLED to repost
                position["live_state"] = "BUY_FILLED"
                position["sell_order_id"] = ""
                self.portfolio._save()
                print(f"[MM-LIVE] SELL CANCELLED externally, will repost next cycle")

    async def evaluate_opportunity(self, opp: dict) -> bool:
        """Evaluate if we should trade an opportunity."""
        condition_id = opp["condition_id"]

        # Skip if already in position
        if condition_id in self.portfolio.positions:
            return False

        # Skip if too many positions
        if len(self.portfolio.positions) >= CONFIG["max_positions"]:
            print(f"[EVAL] {opp['strategy']}: REJECTED (max positions {len(self.portfolio.positions)}/{CONFIG['max_positions']})")
            return False

        # Check news sentiment (uses Claude API sparingly)
        if opp["strategy"] in ["DIP_BUY", "VOLUME_SURGE"]:
            news = await self.news.analyze_market(opp["question"])
            if news:
                print(f"[NEWS] {opp['question'][:40]}...")
                print(f"       {news.get('direction', 'NEUTRAL')} ({news.get('confidence', 0):.0%})")

                # Require bullish news for dip buys
                if opp["strategy"] == "DIP_BUY":
                    if news.get("direction") != "BULLISH" or news.get("confidence", 0) < 0.6:
                        print(f"       Skipping: News not bullish enough")
                        return False

        confidence_ok = opp["confidence"] >= CONFIG["min_confidence"]
        if not confidence_ok:
            print(f"[EVAL] {opp['strategy']}: REJECTED (confidence {opp['confidence']:.2f} < {CONFIG['min_confidence']:.2f})")
        return confidence_ok

    async def execute_trade(self, opp: dict):
        """Execute a trade for an opportunity using REAL market prices."""
        # Calculate position size using Kelly Criterion if enabled
        # These strategies use fixed % sizing (Kelly undersizes them due to moderate edges)
        if CONFIG.get("use_kelly", False) and opp["strategy"] not in ["DUAL_SIDE_ARB", "MARKET_MAKER", "MEAN_REVERSION", "MID_RANGE"]:
            kelly = KellyCriterion(
                kelly_fraction=CONFIG.get("kelly_fraction", 0.25),
                max_position_pct=CONFIG.get("kelly_max_position", 0.15),
                min_edge=CONFIG.get("kelly_min_edge", 0.03)
            )
            kelly_result = kelly.calculate_from_opportunity(opp, self.portfolio.balance)

            if kelly_result:
                max_amount = kelly_result.position_size
                print(f"[KELLY] Edge: {kelly_result.edge:.1%} | Raw: {kelly_result.kelly_fraction:.1%} | "
                      f"Adj: {kelly_result.adjusted_fraction:.1%} | Risk: {kelly_result.risk_level}")
            else:
                # Fall back to fixed percentage if Kelly returns None (no edge)
                max_amount = self.portfolio.balance * CONFIG["max_position_pct"]
        else:
            # Fixed percentage for special strategies or when Kelly disabled
            max_amount = self.portfolio.balance * CONFIG["max_position_pct"]

        # REALISTIC CONSTRAINT: Can't buy more than 1% of market liquidity
        # This prevents unrealistic fills that wouldn't happen in real trading
        liquidity = opp.get("liquidity", 10000)
        max_liquidity_amount = liquidity * 0.01  # Max 1% of liquidity

        amount = min(max_amount, max_liquidity_amount, 200)  # Cap at $200 per trade

        # Minimum position size
        if amount < 50:
            print(f"[TRADE] Skipping: Position too small (${amount:.2f} < $50 minimum)")
            return

        # DUAL_SIDE_ARB: Special handling - buy BOTH sides for guaranteed profit
        if opp["strategy"] == "DUAL_SIDE_ARB":
            await self._execute_dual_side_arb(opp, amount)
            return

        # MARKET_MAKER: Post limit orders on both sides for spread capture
        if opp["strategy"] == "MARKET_MAKER":
            await self._execute_market_maker(opp, amount)
            return

        # BINANCE_ARB: Execute based on edge direction
        if opp["strategy"] == "BINANCE_ARB":
            await self._execute_binance_arb(opp, amount)
            return

        # Verify we're using real market price
        if opp["price"] <= 0 or opp["price"] > 1:
            print(f"[TRADE] Skipping: Invalid price ${opp['price']}")
            return

        if self.live:
            # LIVE: Place real CLOB order for non-MM strategies
            token_id = opp.get("token_id_yes") if opp["side"] == "YES" else opp.get("token_id_no")
            if not token_id:
                print(f"[TRADE-LIVE] SKIP: No token_id for {opp['strategy']}")
                return

            total_exposure = sum(p["cost_basis"] for p in self.portfolio.positions.values())
            safe, reason = self.safety.pre_order_check(
                order_amount=amount,
                portfolio_balance=self.portfolio.balance,
                total_exposure=total_exposure,
                portfolio_initial=self.portfolio.initial_balance,
            )
            if not safe:
                print(f"[TRADE-LIVE] SAFETY BLOCK: {reason}")
                return

            await self.executor.init()
            shares = amount / opp["price"]
            result = await self.executor.post_limit_order(
                token_id=token_id, side="BUY", price=opp["price"],
                size=round(shares, 2), post_only=True
            )
            order_id = result.get("orderID", "")
            if not order_id:
                print(f"[TRADE-LIVE] ORDER FAILED: {result.get('error', result)}")
                return

            # Record in portfolio
            port_result = self.portfolio.buy(
                condition_id=opp["condition_id"],
                question=opp["question"],
                side=opp["side"],
                price=opp["price"],
                amount=amount,
                reason=opp["reason"],
                strategy=opp["strategy"]
            )
            if port_result["success"]:
                pos = self.portfolio.positions[opp["condition_id"]]
                pos["buy_order_id"] = order_id
                pos["token_id"] = token_id
                pos["live_state"] = "BUY_PENDING"
                self.portfolio._save()
                print(f"[TRADE-LIVE] BUY ${amount:.2f} {opp['side']} @ {opp['price']:.3f}")
                print(f"             {opp['strategy']} | {opp['question'][:50]}...")
            return
        else:
            # SIMULATION: Record virtual trade
            result = self.portfolio.buy(
                condition_id=opp["condition_id"],
                question=opp["question"],
                side=opp["side"],
                price=opp["price"],
                amount=amount,
                reason=opp["reason"],
                strategy=opp["strategy"]  # Track strategy for A/B testing
            )

            if result["success"]:
                annualized = opp.get("annualized_return", 0)
                days = opp.get("days_to_resolve", "?")
                print(f"[TRADE] BUY ${amount:.2f} {opp['side']} @ {opp['price']:.3f}")
                print(f"        Market: {opp['question'][:50]}...")
                print(f"        Strategy: {opp['strategy']} | {days}d to resolve | {annualized:.0%} APY")

    async def _execute_dual_side_arb(self, opp: dict, total_amount: float):
        """
        Execute DUAL-SIDE ARBITRAGE: Buy BOTH YES and NO for guaranteed profit.

        When YES + NO < $1.00, buying both guarantees profit because
        one side MUST pay $1.00 when the market resolves.

        Profit = $1.00 - (YES_price + NO_price)
        """
        yes_price = opp.get("yes_price", 0)
        no_price = opp.get("no_price", 0)
        total_cost = yes_price + no_price

        if total_cost <= 0 or total_cost >= 1.0:
            print(f"[DUAL_ARB] Skipping: No arbitrage (total={total_cost:.3f})")
            return

        # Split amount proportionally between YES and NO
        yes_amount = total_amount * (yes_price / total_cost)
        no_amount = total_amount * (no_price / total_cost)

        # For dual-side arb, we record as a single "BOTH" position
        # The profit is locked in immediately - we just wait for resolution
        expected_payout = total_amount / total_cost  # What we get when one side wins
        locked_profit = expected_payout - total_amount

        if self.live:
            print(f"[DUAL_ARB] LIVE MODE: Would buy ${yes_amount:.2f} YES + ${no_amount:.2f} NO")
            print(f"           Locked profit: ${locked_profit:.2f}")
            return

        # SIMULATION: Record as special dual-side position
        # We use "BOTH" side and track the guaranteed profit
        result = self.portfolio.buy(
            condition_id=opp["condition_id"],
            question=opp["question"],
            side="BOTH",  # Special marker for dual-side arb
            price=total_cost,  # Total cost per share
            amount=total_amount,
            reason=opp["reason"],
            strategy="DUAL_SIDE_ARB"
        )

        if result["success"]:
            profit_pct = (1.0 - total_cost) / total_cost * 100
            print(f"[DUAL_ARB] BUY BOTH ${total_amount:.2f} @ ${total_cost:.3f}/share")
            print(f"           YES: ${yes_price:.3f} | NO: ${no_price:.3f}")
            print(f"           LOCKED PROFIT: ${locked_profit:.2f} ({profit_pct:.1f}%)")
            print(f"           Market: {opp['question'][:50]}...")

    async def _execute_market_maker(self, opp: dict, amount: float):
        """
        Execute MARKET MAKER: Post limit orders on both sides to capture spread.

        How it works:
        1. Post BID below mid price (waiting to buy cheap)
        2. Post ASK above mid price (waiting to sell high)
        3. When BOTH fill, profit = spread between our bid and ask
        4. Simulate fills based on price movement

        Based on research: 10-200% APY for active market makers
        """
        mid_price = opp.get("price", 0)
        # Use max of 2% or $0.01 minimum spread on each side (was 0.5%/$0.005)
        mm_bid = opp.get("mm_bid", mid_price - max(mid_price * 0.02, 0.01))
        mm_ask = opp.get("mm_ask", mid_price + max(mid_price * 0.02, 0.01))
        spread_pct = opp.get("spread_pct", 0.02)

        if mid_price <= 0:
            print(f"[MM] Skipping: Invalid price ${mid_price}")
            return

        # AI MARKET SCREEN: Ask Gemini if this market is worth trading
        if CONFIG.get("mm_ai_screen") and hasattr(self, 'gemini') and self.gemini:
            screen = await self.gemini.screen_market(
                question=opp["question"],
                price=mid_price,
                end_date=opp.get("end_date", ""),
                volume_24h=opp.get("volume_24h", 0),
            )
            score = screen.get("quality_score", 5)
            approved = screen.get("approved", True)
            if not approved or score < 5:
                print(f"[MM] AI REJECTED ({score}/10): {opp['question'][:50]}... → {screen.get('reason', '')}")
                return
            else:
                print(f"[MM] AI APPROVED ({score}/10): {opp['question'][:50]}...")

        # Split capital: half for bid (buying), half for ask (selling position)
        # But we need to BUY first to have something to sell
        # Strategy: Buy at our bid, then post ask to sell
        buy_amount = amount

        if self.live:
            # LIVE: Place real CLOB order
            token_id = opp.get("token_id_yes")
            if not token_id:
                print(f"[MM-LIVE] SKIP: No token_id for {opp['question'][:40]}")
                return

            # Safety checks
            total_exposure = sum(p["cost_basis"] for p in self.portfolio.positions.values())
            safe, reason = self.safety.pre_order_check(
                order_amount=buy_amount,
                portfolio_balance=self.portfolio.balance,
                total_exposure=total_exposure,
                portfolio_initial=self.portfolio.initial_balance,
            )
            if not safe:
                print(f"[MM-LIVE] SAFETY BLOCK: {reason}")
                return

            # Post BUY limit order at mm_bid (post-only = maker, zero fees)
            await self.executor.init()
            shares = buy_amount / mm_bid
            result = await self.executor.post_limit_order(
                token_id=token_id, side="BUY", price=mm_bid,
                size=round(shares, 2), post_only=True
            )

            order_id = result.get("orderID", "")
            if not order_id:
                print(f"[MM-LIVE] BUY ORDER FAILED: {result.get('error', result)}")
                return

            print(f"[MM-LIVE] BUY POSTED @ ${mm_bid:.3f} ({round(shares, 2)} shares)")
            print(f"          Market: {opp['question'][:50]}...")

            # Record in portfolio with order tracking
            port_result = self.portfolio.buy(
                condition_id=opp["condition_id"],
                question=opp["question"],
                side="MM",
                price=mm_bid,
                amount=buy_amount,
                reason=opp["reason"],
                strategy="MARKET_MAKER"
            )
            if port_result["success"]:
                pos = self.portfolio.positions[opp["condition_id"]]
                pos["mm_bid"] = mm_bid
                pos["mm_ask"] = mm_ask
                pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
                pos["mm_target_profit"] = CONFIG["mm_target_profit"]
                pos["buy_order_id"] = order_id
                pos["sell_order_id"] = ""
                pos["token_id"] = token_id
                pos["live_state"] = "BUY_PENDING"
                self.portfolio._save()
            return

        # SIMULATION: Record as MM position with special tracking
        # We record the entry at our bid price (optimistic fill)
        # The position will be monitored for exit at our ask price
        result = self.portfolio.buy(
            condition_id=opp["condition_id"],
            question=opp["question"],
            side="MM",  # Special marker for market maker
            price=mm_bid,  # Entry at our bid
            amount=buy_amount,
            reason=opp["reason"],
            strategy="MARKET_MAKER"
        )

        if result["success"]:
            # Store MM-specific data for exit simulation
            pos = self.portfolio.positions[opp["condition_id"]]
            pos["mm_bid"] = mm_bid
            pos["mm_ask"] = mm_ask
            pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
            pos["mm_target_profit"] = CONFIG["mm_target_profit"]
            self.portfolio._save()

            expected_profit = buy_amount * CONFIG["mm_target_profit"]
            print(f"[MM] POSITION OPENED @ ${mm_bid:.3f}")
            print(f"     Market: {opp['question'][:50]}...")
            print(f"     Target Exit: ${mm_ask:.3f} (+{CONFIG['mm_target_profit']:.1%})")
            print(f"     Expected Profit: ${expected_profit:.2f}")
            print(f"     Volume: ${opp.get('volume_24h', 0)/1000:.0f}k/24h")

    async def _execute_binance_arb(self, opp: dict, amount: float):
        """
        Execute BINANCE ARBITRAGE: Buy mispriced side based on Binance-implied probability.

        When Polymarket lags behind Binance price movement:
        - Positive edge → Buy YES (Polymarket underpricing)
        - Negative edge → Buy NO (Polymarket overpricing)
        """
        side = opp["side"]
        price = opp["price"]
        edge = opp.get("edge", 0)
        binance_price = opp.get("binance_price", 0)
        target_price = opp.get("target_price", 0)

        if self.live:
            print(f"[BINANCE_ARB] LIVE MODE: Would buy ${amount:.2f} of {side}")
            print(f"     Edge: {edge:+.1f}% | BTC: ${binance_price:,.0f}")
            return

        # SIMULATION: Execute the trade
        result = self.portfolio.buy(
            condition_id=opp["condition_id"],
            question=opp["question"],
            side=side,
            price=price,
            amount=amount,
            reason=opp["reason"],
            strategy="BINANCE_ARB"
        )

        if result["success"]:
            print(f"[BINANCE_ARB] BUY {side} @ ${price:.3f}")
            print(f"     Market: {opp['question'][:50]}...")
            print(f"     Edge: {edge:+.1f}% | Binance: ${binance_price:,.0f} → Target: ${target_price:,.0f}")
            print(f"     Amount: ${amount:.2f} | Confidence: {opp.get('confidence', 0):.0%}")

    async def run_cycle(self):
        """Run one trading cycle."""
        print(f"\n{'='*60}")
        print(f"  CYCLE @ {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}")

        # 1. Check exits on existing positions
        if self.portfolio.positions:
            print(f"\n[POSITIONS] Checking {len(self.portfolio.positions)} open positions...")
            await self.check_exits()

        # 2. Scan for new opportunities
        print(f"\n[SCANNER] Scanning markets...")
        markets = await self.scanner.get_active_markets()
        print(f"[SCANNER] Found {len(markets)} liquid markets")

        # Fetch Binance prices for crypto arbitrage
        binance_prices = await self.scanner.get_binance_prices()
        if binance_prices:
            btc = binance_prices.get("BTCUSDT", 0)
            eth = binance_prices.get("ETHUSDT", 0)
            if btc > 0:
                print(f"[BINANCE] BTC: ${btc:,.0f} | ETH: ${eth:,.0f}")

        opportunities = self.scanner.find_opportunities(markets, binance_prices)
        print(f"[SCANNER] Identified {len(opportunities)} opportunities")

        # 2.5. Log market snapshot (real bid/ask/volume for future backtesting)
        self._log_snapshot(markets, binance_prices)

        # 3. Evaluate and execute (try more strategies in parallel)
        for opp in opportunities[:5]:  # Evaluate top 5 to test more strategies
            if await self.evaluate_opportunity(opp):
                await self.execute_trade(opp)
                await asyncio.sleep(1)  # Rate limit

        # 4. Print summary
        summary = self.portfolio.get_summary()
        print(f"\n[PORTFOLIO]")
        print(f"  Balance: ${summary['balance']:.2f}")
        print(f"  Open Positions: {summary['open_positions']}")
        print(f"  Total P&L: ${summary['total_pnl']:+.2f}")
        print(f"  Win Rate: {summary['win_rate']:.1f}%")
        print(f"  ROI: {summary['roi_pct']:+.1f}%")

        # 5. Strategy A/B report (every cycle)
        print(f"\n{self.portfolio.get_strategy_report()}")

    def _log_snapshot(self, markets: list, binance_prices: dict):
        """Append market snapshot to daily NDJSON file for future backtesting."""
        try:
            now = datetime.now(timezone.utc)
            filename = self.snapshot_dir / f"{now.strftime('%Y-%m-%d')}.ndjson"
            snapshot = {
                "ts": now.isoformat(),
                "binance": binance_prices or {},
                "markets": [
                    {
                        "id": m.get("conditionId", ""),
                        "q": m.get("question", "")[:80],
                        "bid": float(m.get("bestBid") or 0),
                        "ask": float(m.get("bestAsk") or 0),
                        "vol24h": float(m.get("volume24hr") or 0),
                        "vol1h": float(m.get("volume1hr") or 0),
                        "liq": float(m.get("liquidityNum") or 0),
                        "chg24h": float(m.get("oneDayPriceChange") or 0),
                        "end": m.get("endDate", ""),
                    }
                    for m in markets
                ],
            }
            with open(filename, "a") as f:
                f.write(json.dumps(snapshot, separators=(",", ":")) + "\n")
        except Exception:
            pass  # Never let logging break trading

    async def run(self):
        """Main trading loop."""
        mode = "LIVE" if self.live else "SIMULATION"
        print(f"\n{'#'*60}")
        if STRATEGY_FILTER:
            print(f"#  SOVEREIGN HIVE V4 - STRATEGY TEST: {STRATEGY_FILTER}")
            print(f"#  Isolated capital: ${CONFIG['initial_balance']:.2f}")
        else:
            print(f"#  SOVEREIGN HIVE V4 - {mode} MODE")
            print(f"#  Initial Balance: ${CONFIG['initial_balance']:.2f}")
        print(f"#  Started: {datetime.now().isoformat()}")
        print(f"{'#'*60}")

        if self.live:
            print("\n*** LIVE TRADING - REAL MONEY AT RISK ***\n")
            # Initialize CLOB client at startup
            await self.executor.init()
            if not self.executor.client:
                print("[FATAL] Cannot initialize CLOB client. Aborting live mode.")
                return
            # Register signal handlers for graceful shutdown
            import signal
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, lambda: setattr(self, 'running', False))

        self.running = True

        try:
            while self.running:
                # Check kill switch in live mode
                if self.live and self.safety.check_kill_switch():
                    print("[SHUTDOWN] Kill switch detected!")
                    break
                await self.run_cycle()
                print(f"\n[SLEEP] Next scan in {CONFIG['scan_interval']} seconds...")
                await asyncio.sleep(CONFIG["scan_interval"])
        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Stopping gracefully...")
        finally:
            self.running = False

            # Cancel all open orders in live mode
            if self.live and self.executor and self.executor._initialized:
                print("[SHUTDOWN] Cancelling all open CLOB orders...")
                await self.executor.cancel_all_orders()

            summary = self.portfolio.get_summary()
            print(f"\n{'='*60}")
            print(f"  FINAL SUMMARY")
            print(f"{'='*60}")
            print(f"  Total Value: ${summary['total_value']:.2f}")
            print(f"  Total P&L: ${summary['total_pnl']:+.2f}")
            print(f"  ROI: {summary['roi_pct']:+.1f}%")
            print(f"  Trades: {summary['total_trades']}")
            print(f"  Win Rate: {summary['win_rate']:.1f}%")
            print(f"\n{self.portfolio.get_strategy_report()}")
            print(f"{'='*60}\n")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Sovereign Hive Trading Bot")
    parser.add_argument("--live", action="store_true", help="Enable live trading (real money)")
    parser.add_argument("--reset", action="store_true", help="Reset portfolio to initial state")
    args = parser.parse_args()

    if args.reset:
        data_file = "portfolio_live.json" if args.live else "portfolio_sim.json"
        path = Path(__file__).parent / "data" / data_file
        if path.exists():
            path.unlink()
            print(f"Portfolio reset: {data_file}")
        return

    engine = TradingEngine(live=args.live)
    asyncio.run(engine.run())


if __name__ == "__main__":
    main()
