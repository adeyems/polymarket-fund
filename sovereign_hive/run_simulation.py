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
import random
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.claude_analyzer import ClaudeAnalyzer
from core.kelly_criterion import KellyCriterion, monte_carlo_validate, empirical_probability, polymarket_taker_fee, taker_slippage
from core.news_intelligence import NewsIntelligence
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
    "max_positions": 10,             # More positions for active trading
    "take_profit_pct": 0.10,         # +10% take profit (optimized: larger wins)
    "stop_loss_pct": -0.05,          # -5% stop loss (optimized: tighter = better)
    # DUAL-SIDE ARB CONFIG
    "dual_side_min_profit": 0.02,    # Minimum 2% profit for dual-side arb
    "dual_side_min_liquidity": 10000, # $10k minimum liquidity per side
    "min_liquidity": 5000,           # Min market liquidity (lowered from 10k)
    "min_confidence": 0.55,          # Min AI confidence to trade (lowered from 0.60)
    "scan_interval": 120,            # Scan every 2 min (was 10 min — too slow)
    "exit_check_interval": 30,       # Check exits every 30s for faster turnover
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

    # MARKET MAKER CONFIG (DATA-DRIVEN from 88.5M on-chain trade analysis)
    # Source: becker-dataset analysis of $12B across 30,649 resolved markets
    "mm_min_spread": 0.01,           # 1% min spread
    "mm_max_spread": 0.15,           # 15% max spread
    "mm_min_volume_24h": 5000,       # $5k+ volume
    "mm_min_liquidity": 10000,       # $10k+ liquidity
    "mm_target_profit": 0.015,       # 1.5% default (AI overrides per-market)
    "mm_max_hold_hours": 4,          # Exit after 4h (was 2h, too short for maker sells)
    "mm_timeout_min_profit_pct": 0.03,  # 3% min profit before timeout exit (covers taker fees + slippage)
    "mm_price_range": (0.50, 0.70),  # SWEET SPOT: Kelly +29-48%, ROI +23-26% (was 0.05-0.95)
    "mm_fallback_range": (0.80, 0.95),  # SECONDARY: Kelly +4-20%, smaller edge
    "mm_max_days_to_resolve": 30,    # 15-30d optimal, 30d cap works
    "mm_min_days_to_resolve": 2,     # 0-1d is NEGATIVE edge (insider-dominated)
    "mm_ai_screen": True,            # Use Gemini AI to screen market quality
    "mm_fill_probability": 0.60,     # 60% chance of fill when price touches ask (sim only)
    "mm_slippage_bps": 20,           # 20 bps (0.2%) slippage on entry/exit prices (sim only)

    # LIVE TRADING LIMITS (only used when --live flag is set)
    "live_max_order": 10,            # Max $10 per order (conservative for small accounts)
    "live_min_position": 5,          # Min $5 position (Polymarket allows ~$1 but gas makes <$5 wasteful)
    "live_max_position_pct": 0.50,   # Allow 50% of balance per trade for small accounts (capped by live_max_order)

    # NEG_RISK ARBITRAGE CONFIG (multi-outcome event arbitrage)
    # Source: 42% of NegRisk events have probability sums != 1.0
    # Top arbitrageur extracted $2M+ across 4,049 trades
    "negrisk_min_edge": 0.005,       # 0.5% minimum guaranteed profit
    "negrisk_min_outcomes": 3,       # Need 3+ outcomes for meaningful arb
    "negrisk_min_liquidity": 5000,   # $5k min liquidity per outcome
    "negrisk_max_outcomes": 50,      # Skip events with 50+ outcomes (execution risk)
    "negrisk_max_edge": 0.10,        # 10% max edge — higher means NOT mutually exclusive

    # BINANCE ARBITRAGE CONFIG (Strategy 8 - Model-based, NOT latency arb)
    # Polymarket added 3.15% dynamic fees on 15-min crypto markets, killing latency arb
    # Now: compare Binance spot to Polymarket for LONGER-DURATION crypto markets only
    "binance_min_edge": 0.03,        # 3% minimum edge (was 5% - too restrictive)
    "binance_min_liquidity": 10000,  # $10k minimum liquidity
    "binance_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],  # Cryptos to track

    # KELLY CRITERION CONFIG - Monte Carlo Cap 3 Half Kelly (institutional standard)
    # Source: Article analysis + 88.5M trade Becker dataset empirical edges
    # Half Kelly = f*/2: 75% of growth, 25% of volatility
    # Cap 3 = 30% max position per trade (hard ceiling)
    # Monte Carlo = 10,000 simulated paths validate fraction at startup
    "use_kelly": True,               # Enable Kelly Criterion position sizing
    "kelly_fraction": 0.50,          # Half Kelly (was 0.40 — now institutional standard)
    "kelly_min_edge": 0.02,          # 2% edge minimum
    "kelly_max_position": 0.30,      # Cap 3: 30% of bankroll per trade (was 20%)

    # MEAN REVERSION CONFIG (OPTIMIZED from backtest: +52% return, 1.05 Sharpe)
    # Backtest date: 2026-02-11, 50 markets, 30-day period
    "mean_reversion_low": 0.30,      # Buy YES when price < 30%
    "mean_reversion_high": 0.70,     # Buy NO when price > 70%
    "mean_reversion_tp": 0.10,       # 10% take profit (optimized)
    "mean_reversion_sl": -0.05,      # 5% stop loss (tighter = better)

    # WEBSOCKET CONFIG — real-time price feed (replaces REST polling for exits)
    "use_websocket": False,          # Opt-in: True for live, False for sim (saves connections)
    "ws_stale_seconds": 30,          # Consider WS price stale after 30s, fall back to REST
}

# Maker strategies pay ZERO fees (post-only limit orders)
MAKER_STRATEGIES = {"MARKET_MAKER"}

# Exit reasons that are fee-free (on-chain settlement, not CLOB trades)
FEE_FREE_EXITS = {"RESOLVED", "MM_RESOLVED", "MM_DELISTED", "MM_FILLED"}

# ============================================================
# PORTFOLIO STATE
# ============================================================

class Portfolio:
    """Tracks simulated portfolio state."""

    def __init__(self, initial_balance: float = 1000.0, data_file: str = "portfolio.json"):
        self.data_file = Path(__file__).parent / "data" / data_file
        self.data_file.parent.mkdir(exist_ok=True)

        # Load or initialize (with corruption recovery)
        if self.data_file.exists():
            try:
                self._load()
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                # Corrupted JSON — try .tmp backup, else start fresh
                tmp_file = self.data_file.with_suffix(".json.tmp")
                if tmp_file.exists():
                    try:
                        print(f"[PORTFOLIO] WARNING: {self.data_file.name} corrupted ({e}), recovering from .tmp backup")
                        import shutil
                        shutil.copy2(tmp_file, self.data_file)
                        self._load()
                    except Exception:
                        print(f"[PORTFOLIO] WARNING: Backup also corrupted, starting fresh")
                        self._init_fresh(initial_balance)
                        return
                else:
                    print(f"[PORTFOLIO] WARNING: {self.data_file.name} corrupted ({e}), starting fresh")
                    self._init_fresh(initial_balance)
                    return
        else:
            self._init_fresh(initial_balance)

    def _init_fresh(self, initial_balance: float = 1000.0):
        """Initialize a fresh portfolio (used on first run or corruption recovery)."""
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
        self.strategy_metrics = {
            "NEAR_CERTAIN": {"trades": 0, "wins": 0, "pnl": 0.0},
            "NEAR_ZERO": {"trades": 0, "wins": 0, "pnl": 0.0},
            "DIP_BUY": {"trades": 0, "wins": 0, "pnl": 0.0},
            "VOLUME_SURGE": {"trades": 0, "wins": 0, "pnl": 0.0},
            "MID_RANGE": {"trades": 0, "wins": 0, "pnl": 0.0},
            "DUAL_SIDE_ARB": {"trades": 0, "wins": 0, "pnl": 0.0},
            "MARKET_MAKER": {"trades": 0, "wins": 0, "pnl": 0.0},
            "BINANCE_ARB": {"trades": 0, "wins": 0, "pnl": 0.0},
        }
        self._save()

    def _load(self):
        with open(self.data_file, "r") as f:
            data = json.load(f)
        self.balance = data["balance"]
        self.initial_balance = data["initial_balance"]
        self.positions = data["positions"]
        self.trade_history = data["trade_history"]
        # Merge loaded metrics with defaults to handle missing keys
        # Start with saved data, fill in any missing keys with defaults
        default_metrics = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "peak_balance": data.get("initial_balance", 1000.0),
        }
        saved_metrics = data.get("metrics", {})
        self.metrics = {**default_metrics, **saved_metrics}
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
        try:
            # Atomic write: write to .tmp then rename (prevents corruption on crash/kill)
            tmp_file = self.data_file.with_suffix(".json.tmp")
            with open(tmp_file, "w") as f:
                json.dump(data, f, indent=2)
            tmp_file.replace(self.data_file)  # Atomic on POSIX
        except Exception as e:
            print(f"[PORTFOLIO] WARNING: Save failed ({e}), trading continues with in-memory state")

    def buy(self, condition_id: str, question: str, side: str, price: float, amount: float, reason: str, strategy: str = "UNKNOWN", fee_pct: float = 0.0) -> dict:
        """Execute a simulated buy order.

        Args:
            fee_pct: Taker fee as decimal (e.g. 0.0144 for 1.44%). Makers pass 0.
                     Fee is deducted from the amount, reducing shares received.
        """
        if amount > self.balance:
            return {"success": False, "error": "Insufficient balance"}

        fee = amount * fee_pct
        effective_amount = amount - fee
        shares = effective_amount / price

        position = {
            "condition_id": condition_id,
            "question": question[:80],
            "side": side,
            "entry_price": price,
            "shares": shares,
            "cost_basis": amount,  # Full amount paid (includes fee)
            "entry_fee": round(fee, 4),
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "strategy": strategy,
        }

        self.positions[condition_id] = position
        self.balance -= amount

        # Track cumulative fees per strategy
        if strategy in self.strategy_metrics:
            self.strategy_metrics[strategy].setdefault("fees", 0.0)
            self.strategy_metrics[strategy]["fees"] += fee

        self._save()

        return {"success": True, "position": position}

    def sell(self, condition_id: str, current_price: float, reason: str, fee_pct: float = 0.0) -> dict:
        """Execute a simulated sell order.

        Args:
            fee_pct: Taker fee as decimal. Makers pass 0. Fee deducted from proceeds.
        """
        if condition_id not in self.positions:
            return {"success": False, "error": "Position not found"}

        position = self.positions[condition_id]
        gross_proceeds = position["shares"] * current_price
        exit_fee = gross_proceeds * fee_pct
        proceeds = gross_proceeds - exit_fee
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
            "entry_fee": position.get("entry_fee", 0),
            "exit_fee": round(exit_fee, 4),
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
            self.strategy_metrics[strategy].setdefault("fees", 0.0)
            self.strategy_metrics[strategy]["fees"] += exit_fee
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
            "max_drawdown_pct": round(self.metrics.get("max_drawdown", 0) * 100, 2),
            "strategy_metrics": self.strategy_metrics,
        }

    def get_strategy_report(self) -> str:
        """Get A/B test report for all strategies."""
        # Count open positions per strategy
        open_by_strategy = {}
        for pos in self.positions.values():
            s = pos.get("strategy", "UNKNOWN")
            open_by_strategy[s] = open_by_strategy.get(s, 0) + 1

        lines = ["STRATEGY PERFORMANCE (A/B Test):"]
        lines.append("-" * 65)
        for strategy, metrics in self.strategy_metrics.items():
            trades = metrics["trades"]
            wins = metrics["wins"]
            pnl = metrics["pnl"]
            fees = metrics.get("fees", 0.0)
            win_rate = (wins / trades * 100) if trades > 0 else 0
            fee_str = f" | Fees: ${fees:.2f}" if fees > 0 else ""
            open_count = open_by_strategy.get(strategy, 0)
            open_str = f" | Open: {open_count}" if open_count > 0 else ""
            lines.append(f"  {strategy:15} | Trades: {trades:3} | Win: {win_rate:5.1f}% | P&L: ${pnl:+.2f}{fee_str}{open_str}")
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
        self._retry_max = 3
        self._retry_base_delay = 1.0  # seconds
        # MEAN_REVERSION cooldown tracking — prevents death loop on same market
        self.mr_cooldowns = {}  # {condition_id: last_exit_timestamp}
        self.mr_entry_counts = {}  # {condition_id: number_of_entries}
        self.MR_COOLDOWN_HOURS = 48
        self.MR_MAX_ENTRIES = 2

    async def _fetch_with_retry(self, url: str, params: dict = None, timeout: int = 15) -> Optional[dict]:
        """Fetch URL with 3-retry exponential backoff. Returns parsed JSON or None."""
        for attempt in range(self._retry_max):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=timeout) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        elif resp.status in (429, 502, 503):
                            delay = self._retry_base_delay * (2 ** attempt)
                            print(f"[SCANNER] HTTP {resp.status} from {url.split('/')[-1]}, retry {attempt+1}/{self._retry_max} in {delay:.0f}s")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            return None  # Non-retryable HTTP error
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                delay = self._retry_base_delay * (2 ** attempt)
                if attempt < self._retry_max - 1:
                    print(f"[SCANNER] {type(e).__name__} on {url.split('/')[-1]}, retry {attempt+1}/{self._retry_max} in {delay:.0f}s")
                    await asyncio.sleep(delay)
                else:
                    print(f"[SCANNER] {type(e).__name__} on {url.split('/')[-1]}, all {self._retry_max} attempts failed")
            except Exception as e:
                print(f"[SCANNER] Unexpected error: {e}")
                return None
        return None

    async def get_active_markets(self) -> List[dict]:
        """Fetch active markets with good liquidity (with retry)."""
        params = {"limit": 500, "active": "true", "closed": "false", "order": "volume24hr", "ascending": "false"}
        markets = await self._fetch_with_retry(self.GAMMA_API, params=params, timeout=15)
        if not markets:
            return []
        result = []
        for m in markets:
            if float(m.get("liquidityNum") or 0) >= CONFIG["min_liquidity"]:
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

    async def get_market_price(self, condition_id: str) -> Optional[float]:
        """Get current YES price for a market (with retry).

        Sorts by volume24hr to ensure high-volume (actively held) positions
        are reliably found. Returns None (not 0) when market not found,
        to avoid false stop-loss triggers.
        """
        params = {
            "limit": 500,
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false",
        }
        markets = await self._fetch_with_retry(self.GAMMA_API, params=params, timeout=20)
        if not markets:
            return None
        for m in markets:
            if m.get("conditionId") == condition_id:
                best_ask = m.get("bestAsk")
                if best_ask is not None:
                    return float(best_ask)
                return None  # Market found but no ask price
        return None

    async def get_resolution_price(self, condition_id: str) -> Optional[float]:
        """
        Get the YES resolution price for a closed/resolved market (with retry).

        Returns:
          1.0  if YES won
          0.0  if NO won (YES worthless)
          None if market not found in closed markets (still active or API error)

        Uses outcomePrices field: ["1","0"] = YES won, ["0","1"] = NO won.
        """
        params = {"conditionId": condition_id, "closed": "true", "limit": 5}
        markets = await self._fetch_with_retry(self.GAMMA_API, params=params, timeout=15)
        if not markets:
            return None
        for m in markets:
            if m.get("conditionId") != condition_id:
                continue
            outcome_prices = m.get("outcomePrices")
            if not outcome_prices:
                continue
            if isinstance(outcome_prices, str):
                import json as _json
                outcome_prices = _json.loads(outcome_prices)
            yes_resolved = float(outcome_prices[0])
            return yes_resolved  # 1.0 = YES won, 0.0 = NO won
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
        """Fetch current Binance spot prices for major cryptos (with retry)."""
        symbols = CONFIG.get("binance_symbols", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        prices = {}

        data = await self._fetch_with_retry(self.BINANCE_API, timeout=10)
        if data:
            for item in data:
                if item["symbol"] in symbols:
                    prices[item["symbol"]] = float(item["price"])

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
            # PRICE FILTER: Only buy dips in empirically profitable zones
            dip_in_edge_zone = (0.55 <= best_ask <= 0.65) or (0.80 <= best_ask <= 0.95)
            if price_change < CONFIG["dip_threshold"] and volume_24h > 30000 and dip_in_edge_zone:
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
            # Gamma API has no hourly volume field. Use oneHourPriceChange as
            # a proxy: large price moves require large volume to execute.
            # Combine with high absolute daily volume as a quality filter.
            # PRICE FILTER (from 88.5M Becker trades): Only trade in empirically
            # profitable zones. Death zone (0.35-0.45) and trap zone (0.70-0.75) blocked.
            price_change_1h = abs(float(m.get("oneHourPriceChange") or 0))
            min_hourly_change = 0.02  # 2% move signals unusual activity
            min_surge_volume = 30000  # $30k daily volume floor
            surge_price = best_ask if price_change >= 0 else (1.0 - best_bid if best_bid > 0 else 1.0 - best_ask)
            surge_in_edge_zone = (0.55 <= surge_price <= 0.65) or (0.80 <= surge_price <= 0.95)
            if (price_change_1h >= min_hourly_change
                    and volume_24h >= min_surge_volume
                    and abs(price_change) < 0.05
                    and surge_in_edge_zone):
                surge_ratio = price_change_1h / min_hourly_change  # how many multiples of 2%
                expected_return = 0.10
                annualized = self.calculate_annualized_return(expected_return, 7)  # 7-day target
                opportunities.append({
                    "condition_id": condition_id,
                    "question": question,
                    "strategy": "VOLUME_SURGE",
                    "side": "YES" if price_change >= 0 else "NO",
                    "price": best_ask if price_change >= 0 else (1.0 - best_bid if best_bid > 0 else 1.0 - best_ask),
                    "expected_return": expected_return,
                    "annualized_return": annualized,
                    "days_to_resolve": 7,  # Active trading target
                    "liquidity": liquidity,
                    "confidence": 0.60,
                    "reason": f"1h surge {price_change_1h:.1%} ({surge_ratio:.1f}x), {annualized:.0%} APY target"
                })

            # Strategy 5: Mid-range active trading
            # Fastest capital turnover - 5% TP in ~3-7 days
            # PRICE FILTER (from 88.5M Becker trades): Only trade in empirically
            # profitable zones. Death zone (0.35-0.45) and trap zone (0.70-0.75) blocked.
            if volume_24h >= CONFIG["min_24h_volume"]:
                expected_return = CONFIG["take_profit_pct"]  # 5% take profit
                annualized = self.calculate_annualized_return(expected_return, 5)  # 5-day target
                # Trade with momentum: buy YES if price going up, NO if going down
                if price_change > 0.005:  # 0.5%+ upward momentum
                    yes_in_edge_zone = (0.55 <= best_ask <= 0.65) or (0.80 <= best_ask <= 0.95)
                    if yes_in_edge_zone:
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
                    no_in_edge_zone = (0.55 <= no_price <= 0.65) or (0.80 <= no_price <= 0.95)
                    if no_in_edge_zone:
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

            # HARD FILTER: Resolution time (data-driven from 88.5M trade analysis)
            # 15-30d is optimal (Kelly +5.51%), 0-1d is NEGATIVE (insider-dominated)
            mm_max_days = CONFIG.get("mm_max_days_to_resolve", 30)
            mm_min_days = CONFIG.get("mm_min_days_to_resolve", 2)
            if days_to_resolve > mm_max_days or days_to_resolve < mm_min_days:
                pass  # Skip — outside optimal resolution window
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

                # PREFERRED TOPICS: Politics & Economics (data-driven: Kelly +4-5%)
                # Crypto REMOVED — negative Kelly (-1.53%) from 88.5M trade analysis
                preferred_topics = [
                    "trump", "biden", "election", "president", "congress",
                    "fed", "interest rate", "inflation", "tariff", "economy",
                    "gdp", "unemployment", "recession", "jobs",
                ]
                is_preferred = any(topic in q_lower for topic in preferred_topics)

                # NEGATIVE CATEGORIES: Crypto has negative edge
                negative_categories = ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana"]
                is_negative_category = any(kw in q_lower for kw in negative_categories)

                # SPORTS FILTER: Sports markets have higher variance, all 3 MM stops
                # came from sports. Tennis/LoL/soccer dips are real info, not mispricing.
                # Use word-boundary matching to avoid false positives (e.g. "inflation" matching "nfl")
                import re
                _q_words = set(re.findall(r'[a-z0-9]+', q_lower))
                sports_exact = {"tennis", "atp", "wta", "soccer", "football",
                                "nba", "nfl", "nhl", "mlb", "cricket", "ipl",
                                "mls", "esports", "csgo", "dota", "lol"}
                sports_phrases = [
                    "grand slam", "premier league", "champions league",
                    "la liga", "serie a", "bundesliga", "ligue 1",
                    "league of legends", " vs ",
                    "game 1", "game 2", "game 3",
                ]
                is_sports = bool(_q_words & sports_exact) or any(p in q_lower for p in sports_phrases)

                # TWO-ZONE PRICE FILTER (data-driven from 88.5M trades)
                # Sweet spot: 0.50-0.70 (Kelly +29-48%, ROI +23-26%)
                # Fallback: 0.80-0.95 (Kelly +4-20%, smaller edge)
                # Death zone: 0.35-0.45 (Kelly -17 to -22%) — EXCLUDED
                # Trap zone: 0.70-0.75 (Kelly -19%) — EXCLUDED
                mm_min, mm_max = CONFIG["mm_price_range"]
                fb_min, fb_max = CONFIG.get("mm_fallback_range", (0.80, 0.95))
                in_sweet_spot = mm_min <= best_ask <= mm_max
                in_fallback = fb_min <= best_ask <= fb_max
                mm_pass_price = in_sweet_spot or in_fallback

                mm_pass_bid = best_bid > 0
                mm_pass_vol = volume_24h >= CONFIG["mm_min_volume_24h"]
                mm_pass_liq = liquidity >= CONFIG["mm_min_liquidity"]
                if (not is_meme_market and not is_sports and mm_pass_price and mm_pass_bid and mm_pass_vol and mm_pass_liq):

                    spread = best_ask - best_bid
                    spread_pct = spread / ((best_ask + best_bid) / 2) if (best_ask + best_bid) > 0 else 0
                    mid_price = (best_ask + best_bid) / 2

                    if not (CONFIG["mm_min_spread"] <= spread_pct <= CONFIG["mm_max_spread"]):
                        print(f"[MM_DEBUG] Spread miss: {question[:45]}... bid={best_bid:.3f} ask={best_ask:.3f} spread={spread_pct:.1%} (need {CONFIG['mm_min_spread']:.0%}-{CONFIG['mm_max_spread']:.0%})")

                    if CONFIG["mm_min_spread"] <= spread_pct <= CONFIG["mm_max_spread"]:
                        expected_return = CONFIG["mm_target_profit"]
                        hours_to_fill = 4
                        days_to_fill = hours_to_fill / 24
                        annualized = min(self.calculate_annualized_return(expected_return, max(1, int(days_to_fill * 10))), 10.0)

                        # Data-driven confidence based on price zone + category
                        if in_sweet_spot and is_preferred:
                            confidence = 0.85
                        elif in_sweet_spot:
                            confidence = 0.75
                        elif in_fallback and is_preferred:
                            confidence = 0.65
                        else:
                            confidence = 0.55
                        # Reduce confidence for crypto (negative Kelly)
                        if is_negative_category:
                            confidence -= 0.10

                        zone = "sweet" if in_sweet_spot else "fallback"
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
                            "mm_bid": round(mid_price - max(mid_price * CONFIG["mm_target_profit"], 0.01), 3),
                            "mm_ask": round(mid_price + max(mid_price * CONFIG["mm_target_profit"], 0.01), 3),
                            "expected_return": expected_return,
                            "annualized_return": annualized,
                            "days_to_resolve": days_to_resolve,
                            "end_date": end_date_str,
                            "liquidity": liquidity,
                            "volume_24h": volume_24h,
                            "confidence": confidence,
                            "price_zone": zone,
                            "reason": f"MM[{zone}]: Spread {spread_pct:.1%}, Vol ${volume_24h/1000:.0f}k, {days_to_resolve}d, conf={confidence:.2f}"
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
        # MARKET_MAKER — spread capture (fast turnover, high hit rate)
        diverse_opps = []
        # Allow more slots for fast-turnover and high-hit-rate strategies
        fast_strats = {"MARKET_MAKER": 4, "NEAR_CERTAIN": 3, "NEAR_ZERO": 3, "NEG_RISK_ARB": 3}

        # DEBUG: Log opportunities by strategy
        strategy_summary = {}
        all_strategies = ["NEG_RISK_ARB", "DUAL_SIDE_ARB", "MARKET_MAKER", "MEAN_REVERSION",
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

    # --- NEG_RISK MULTI-OUTCOME ARBITRAGE ---

    GAMMA_EVENTS_API = "https://gamma-api.polymarket.com/events"

    async def fetch_negrisk_events(self) -> List[dict]:
        """Fetch active NegRisk events with multiple outcomes from Gamma API."""
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "active": "true",
                    "closed": "false",
                    "negRisk": "true",  # CRITICAL: only NegRisk events (mutually exclusive outcomes)
                    "limit": 50,
                }
                async with session.get(self.GAMMA_EVENTS_API, params=params, timeout=15) as resp:
                    if resp.status == 200:
                        events = await resp.json()
                        # Filter to multi-outcome events (3+ markets)
                        min_outcomes = CONFIG.get("negrisk_min_outcomes", 3)
                        multi = []
                        for event in events:
                            markets = event.get("markets", [])
                            if len(markets) >= min_outcomes:
                                multi.append(event)
                        return multi
        except Exception as e:
            print(f"[NEGRISK] Fetch error: {e}")
        return []

    def find_negrisk_opportunities(self, events: List[dict]) -> List[dict]:
        """Find arbitrage opportunities in multi-outcome NegRisk events.

        For mutually exclusive outcomes, the sum of all YES prices should equal $1.00.
        If bid_sum > 1.0 → sell all outcomes for guaranteed profit.
        If ask_sum < 1.0 → buy all outcomes for guaranteed profit.
        """
        min_edge = CONFIG.get("negrisk_min_edge", 0.005)
        max_edge = CONFIG.get("negrisk_max_edge", 0.10)
        min_liquidity = CONFIG.get("negrisk_min_liquidity", 5000)
        max_outcomes = CONFIG.get("negrisk_max_outcomes", 50)
        opportunities = []

        for event in events:
            markets = event.get("markets", [])
            num_outcomes = len(markets)

            # Skip if too many outcomes (execution risk)
            if num_outcomes > max_outcomes:
                continue

            # Collect prices and check liquidity
            bids = []
            asks = []
            liquidities = []
            outcome_prices = []
            skip = False

            for m in markets:
                bid = float(m.get("bestBid") or 0)
                ask = float(m.get("bestAsk") or 0)
                liq = float(m.get("liquidityNum") or 0)

                if liq < min_liquidity:
                    skip = True
                    break

                bids.append(bid)
                asks.append(ask)
                liquidities.append(liq)
                outcome_prices.append({"question": m.get("question", "?"), "bid": bid, "ask": ask})

            if skip:
                continue

            bid_sum = sum(bids)
            ask_sum = sum(asks)

            # Calculate days to resolve
            end_date = event.get("endDate") or ""
            days_to_resolve = 30  # default
            if end_date:
                try:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    days_to_resolve = max(1, (end_dt - datetime.now(timezone.utc)).days)
                except (ValueError, TypeError):
                    pass

            event_id = event.get("id", str(hash(event.get("title", ""))))
            event_title = event.get("title", "Unknown Event")

            # SELL ARB: bid_sum > 1.0 means we can sell YES on all outcomes
            # Revenue = bid_sum, Liability = 1.0 (one outcome resolves YES)
            if bid_sum > 1.0 + min_edge:
                edge = bid_sum - 1.0
                # Sanity check: edge > max_edge means outcomes are NOT mutually exclusive
                if edge > max_edge:
                    continue
                annualized = self.calculate_annualized_return(edge, days_to_resolve) if days_to_resolve > 0 else 0
                opportunities.append({
                    "condition_id": f"negrisk_sell_{event_id}",
                    "question": event_title,
                    "strategy": "NEG_RISK_ARB",
                    "side": "SELL_ALL",
                    "price": bid_sum,
                    "expected_return": edge,
                    "annualized_return": annualized,
                    "days_to_resolve": days_to_resolve,
                    "liquidity": min(liquidities),
                    "confidence": 0.95,
                    "num_outcomes": num_outcomes,
                    "outcome_prices": outcome_prices,
                    "reason": f"NegRisk SELL: {num_outcomes} outcomes, bid_sum={bid_sum:.3f}, edge={edge:.1%}"
                })

            # BUY ARB: ask_sum < 1.0 means we can buy YES on all outcomes
            # Cost = ask_sum, Payout = 1.0 (one outcome resolves YES)
            if ask_sum < 1.0 - min_edge:
                edge = 1.0 - ask_sum
                # Sanity check: edge > max_edge means outcomes are NOT mutually exclusive
                if edge > max_edge:
                    continue
                annualized = self.calculate_annualized_return(edge, days_to_resolve) if days_to_resolve > 0 else 0
                opportunities.append({
                    "condition_id": f"negrisk_buy_{event_id}",
                    "question": event_title,
                    "strategy": "NEG_RISK_ARB",
                    "side": "BUY_ALL",
                    "price": ask_sum,
                    "expected_return": edge,
                    "annualized_return": annualized,
                    "days_to_resolve": days_to_resolve,
                    "liquidity": min(liquidities),
                    "confidence": 0.95,
                    "num_outcomes": num_outcomes,
                    "outcome_prices": outcome_prices,
                    "reason": f"NegRisk BUY: {num_outcomes} outcomes, ask_sum={ask_sum:.3f}, edge={edge:.1%}"
                })

        return opportunities


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
        self.news_intel = NewsIntelligence()
        self.running = False
        self._last_scan_time = None  # Track when we last scanned for new opportunities
        self._last_sync_time = None  # Track when we last synced with on-chain balance

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

        # Circuit breaker — tracks stop losses per market to prevent re-entry death loops
        # {condition_id: [datetime, datetime, ...]}  — timestamps of recent stop exits
        self.stop_tracker: dict[str, list] = {}
        self.MAX_STOPS_PER_DAY = 2  # After 2 stops on same market in 24h, lock it out
        self._stop_tracker_file = Path(__file__).parent / "data" / "stop_tracker.json"
        self._load_stop_tracker()

        # Snapshot logger — saves real bid/ask/volume every cycle for future backtesting
        self.snapshot_dir = Path(__file__).parent / "data" / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        # WebSocket real-time price feed (opt-in)
        self.ws = None
        self.ws_prices = {}        # {asset_id: {"price": float, "ts": datetime}}
        self._ws_task = None       # Background listener task
        if CONFIG.get("use_websocket"):
            try:
                from core.ws_listener import MarketWebSocket
                self.ws = MarketWebSocket(on_price_change=self._on_ws_price)
                print("[WS] WebSocket listener initialized (will connect on run)")
            except Exception as e:
                print(f"[WS] Init failed ({e}), falling back to REST polling")
                self.ws = None

        # Monte Carlo Cap 3 Half Kelly validation at startup
        # Validates that Half Kelly fraction survives realistic variance
        if CONFIG.get("use_kelly"):
            try:
                # Compute actual bet fraction for representative sweet-spot trade
                avg_price = 0.60
                emp_prob = empirical_probability(avg_price, "politics")  # Conservative
                raw_kelly = (emp_prob - avg_price) / (1 - avg_price)
                bet_fraction = min(
                    raw_kelly * CONFIG["kelly_fraction"],  # Half Kelly applied
                    CONFIG["kelly_max_position"],          # Cap 3
                )
                mc = monte_carlo_validate(
                    bet_fraction=bet_fraction,
                    win_prob=emp_prob,
                    payout_ratio=(1 - avg_price) / avg_price,
                )
                if mc.validated_fraction < bet_fraction:
                    # Scale down the Half Kelly multiplier proportionally
                    scale = mc.validated_fraction / bet_fraction
                    CONFIG["kelly_fraction"] *= scale
                    print(f"[KELLY-MC] Reduced multiplier to {CONFIG['kelly_fraction']:.2%} "
                          f"(95th pctl DD: {mc.p95_drawdown:.1%})")
                else:
                    print(f"[KELLY-MC] Half Kelly validated "
                          f"(95th pctl DD: {mc.p95_drawdown:.1%}, "
                          f"ruin: {mc.ruin_probability:.2%})")
                self._mc_validated = True
            except Exception as e:
                print(f"[KELLY-MC] Validation failed ({e}), using default fraction")
                self._mc_validated = False
        else:
            self._mc_validated = False

    # ============================================================
    # WEBSOCKET PRICE FEED
    # ============================================================

    async def _on_ws_price(self, data: dict):
        """Callback for WebSocket price updates. Updates local cache."""
        asset_id = data.get("asset_id")
        price = data.get("price")
        if asset_id and price is not None:
            self.ws_prices[asset_id] = {
                "price": float(price),
                "ts": datetime.now(timezone.utc),
            }

    async def _get_market_price(self, condition_id: str, position: dict = None) -> Optional[float]:
        """
        Get current YES price, preferring WebSocket over REST.

        Checks WS cache first (by token_id from position). If stale or
        unavailable, falls back to REST via scanner.get_market_price().
        """
        # Try WebSocket cache first
        if self.ws and position:
            token_id = position.get("token_id")
            if token_id and token_id in self.ws_prices:
                entry = self.ws_prices[token_id]
                age = (datetime.now(timezone.utc) - entry["ts"]).total_seconds()
                stale_limit = CONFIG.get("ws_stale_seconds", 30)
                if age < stale_limit:
                    return entry["price"]

        # Fallback to REST
        return await self.scanner.get_market_price(condition_id)

    async def _ws_subscribe_position(self, token_id: str):
        """Subscribe to WS updates for a new position's token."""
        if self.ws and self.ws.connected and token_id:
            await self.ws.subscribe([token_id])

    async def _ws_start(self):
        """Connect WS and subscribe to tokens of existing positions."""
        if not self.ws:
            return

        connected = await self.ws.connect()
        if not connected:
            print("[WS] Initial connection failed, will use REST polling")
            return

        # Subscribe to tokens of open positions
        token_ids = []
        for pos in self.portfolio.positions.values():
            tid = pos.get("token_id")
            if tid:
                token_ids.append(tid)
        if token_ids:
            await self.ws.subscribe(token_ids)
            print(f"[WS] Subscribed to {len(token_ids)} open position tokens")

        # Start listener as background task
        self._ws_task = asyncio.create_task(self.ws.listen())

    async def _ws_health_check(self):
        """Check WS health and reconnect if needed."""
        if not self.ws:
            return
        if not await self.ws.health_check():
            print("[WS] Connection unhealthy, attempting reconnect...")
            await self.ws._reconnect()

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

            yes_price = await self._get_market_price(condition_id, position)
            if yes_price is None:
                # Market not in active feed — check if it resolved
                res_yes_price = await self.scanner.get_resolution_price(condition_id)
                if res_yes_price is not None:
                    # We know the resolution outcome — price it correctly
                    if position["side"] == "NO":
                        exit_price = 1.0 - res_yes_price  # NO pays out if YES=0
                    else:
                        exit_price = res_yes_price  # YES pays out if YES=1
                    result = self.portfolio.sell(condition_id, exit_price, "RESOLVED")
                    if result["success"]:
                        trade = result["trade"]
                        outcome = "YES WON" if res_yes_price >= 0.5 else "NO WON"
                        print(f"[TRADE] RESOLVED ({outcome}): {trade['question'][:40]}...")
                        print(f"        Exit @ ${exit_price:.3f} | P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")
                else:
                    # Not in closed markets either — truly gone or API lag, skip for now
                    pass
                continue

            # IMPORTANT: For NO positions, current value = 1 - YES_price
            if position["side"] == "NO":
                current_price = 1.0 - yes_price
            else:
                current_price = yes_price

            pnl_pct = self.portfolio.get_position_pnl(condition_id, current_price)
            if pnl_pct is None:
                continue

            strategy = position.get("strategy", "")
            # Resolution strategies (NEAR_CERTAIN, NEAR_ZERO) hold until resolution —
            # stop losses make no sense since they pay out at $1 or $0, not intraday price.
            # Only apply TP/SL to strategies that actively trade intraday.
            no_stop_strategies = {"NEAR_CERTAIN", "NEAR_ZERO"}

            # Take profit — taker fee + slippage applies (selling on CLOB)
            if pnl_pct >= CONFIG["take_profit_pct"]:
                liq = position.get("liquidity", 50000)
                slip = taker_slippage(liq)
                exit_price = current_price * (1 - slip)  # Slippage works against seller
                exit_fee = polymarket_taker_fee(exit_price)
                result = self.portfolio.sell(condition_id, exit_price, "TAKE_PROFIT", fee_pct=exit_fee)
                if result["success"]:
                    trade = result["trade"]
                    print(f"[TRADE] TAKE PROFIT: {trade['question'][:40]}...")
                    print(f"        P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")
                    if strategy == "MEAN_REVERSION":
                        self.scanner.mr_cooldowns[condition_id] = datetime.now(timezone.utc)

            # Stop loss — skip for resolution strategies. Taker fee + slippage applies.
            elif pnl_pct <= CONFIG["stop_loss_pct"] and strategy not in no_stop_strategies:
                liq = position.get("liquidity", 50000)
                slip = taker_slippage(liq)
                exit_price = current_price * (1 - slip)  # Slippage works against seller
                exit_fee = polymarket_taker_fee(exit_price)
                result = self.portfolio.sell(condition_id, exit_price, "STOP_LOSS", fee_pct=exit_fee)
                if result["success"]:
                    trade = result["trade"]
                    print(f"[TRADE] STOP LOSS: {trade['question'][:40]}...")
                    print(f"        P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")
                    if strategy == "MEAN_REVERSION":
                        self.scanner.mr_cooldowns[condition_id] = datetime.now(timezone.utc)
                    # Record stop in circuit breaker for active trading strategies
                    if strategy in {"DIP_BUY", "VOLUME_SURGE", "MID_RANGE"}:
                        if condition_id not in self.stop_tracker:
                            self.stop_tracker[condition_id] = []
                        self.stop_tracker[condition_id].append(datetime.now(timezone.utc))
                        self._save_stop_tracker()
                        stop_count = len(self._get_recent_stops(condition_id))
                        if stop_count >= self.MAX_STOPS_PER_DAY:
                            print(f"        CIRCUIT BREAKER: {stop_count} stops in 24h — market locked out")

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

        # Calculate hold time first — needed for timeout even without a price
        try:
            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
            hold_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
        except:
            hold_hours = 0

        # Get current market price (prefer WS, fallback REST)
        yes_price = await self._get_market_price(condition_id, position)

        # If market has disappeared, look up the actual resolution outcome
        if yes_price is None:
            res_yes_price = await self.scanner.get_resolution_price(condition_id)
            if res_yes_price is not None:
                # MM positions are YES-side — use actual YES resolution price
                exit_price = res_yes_price  # 1.0 if YES won, 0.0 if NO won
                result = self.portfolio.sell(condition_id, exit_price, "MM_RESOLVED")
                if result["success"]:
                    trade = result["trade"]
                    outcome = "YES WON" if res_yes_price >= 0.5 else "NO WON"
                    print(f"[MM] RESOLVED ({outcome}): {trade['question'][:40]}...")
                    print(f"     Entry: ${trade['entry_price']:.3f} → Resolution: ${exit_price:.3f}")
                    print(f"     P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%) in {hold_hours:.1f}h")
            elif hold_hours >= 1.0:
                # Not in closed API either — use entry price as fallback after 1h
                exit_price = position["entry_price"]
                result = self.portfolio.sell(condition_id, exit_price, "MM_DELISTED")
                if result["success"]:
                    trade = result["trade"]
                    print(f"[MM] DELISTED: {trade['question'][:40]}... (market gone, P&L: ${trade['pnl']:+.2f})")
            return

        current_price = yes_price  # MM positions are always YES side

        # EXIT CONDITION 1: Price reached our ask (PROFIT!)
        # MM_FILLED = maker exit (our ask was taken by taker) = ZERO fee
        # Sim realism: only 60% of touches actually fill (partial fills, front-running)
        if current_price >= mm_ask:
            fill_prob = CONFIG.get("mm_fill_probability", 0.60)
            if random.random() > fill_prob:
                return  # Not filled this cycle — will re-check next cycle
            result = self.portfolio.sell(condition_id, mm_ask, "MM_FILLED", fee_pct=0.0)
            if result["success"]:
                trade = result["trade"]
                print(f"[MM] FILLED! {trade['question'][:40]}...")
                print(f"     Entry: ${trade['entry_price']:.3f} → Exit: ${mm_ask:.3f}")
                print(f"     P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%) in {hold_hours:.1f}h")
            return

        # EXIT CONDITION 2: Price dropped too much (STOP LOSS)
        # MM_STOP = taker exit (crossing spread to exit) = taker fee + slippage
        mm_stop_loss = -0.03
        pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]
        if pnl_pct <= mm_stop_loss:
            slippage = CONFIG.get("mm_slippage_bps", 20) / 10000
            exit_price = current_price * (1 - slippage)  # Slippage works against us
            stop_fee = polymarket_taker_fee(exit_price)
            result = self.portfolio.sell(condition_id, exit_price, "MM_STOP", fee_pct=stop_fee)
            if result["success"]:
                trade = result["trade"]
                # Record stop in circuit breaker tracker
                if condition_id not in self.stop_tracker:
                    self.stop_tracker[condition_id] = []
                self.stop_tracker[condition_id].append(datetime.now(timezone.utc))
                self._save_stop_tracker()
                stop_count = len(self._get_recent_stops(condition_id))
                print(f"[MM] STOP: {trade['question'][:40]}...")
                print(f"     Entry: ${trade['entry_price']:.3f} → Exit: ${exit_price:.3f} (slip {slippage:.2%})")
                print(f"     P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%) - Cut loss!")
                if stop_count >= self.MAX_STOPS_PER_DAY:
                    print(f"     CIRCUIT BREAKER: {stop_count} stops in 24h — market locked out")
            return

        # EXIT CONDITION 3: Timeout (didn't fill in time)
        # MM_TIMEOUT = taker exit (exiting at market) = taker fee + slippage
        # RULE: Don't dump for 0-1% — only timeout-exit if profit covers taker costs (>=3%)
        mm_timeout_min_profit = CONFIG.get("mm_timeout_min_profit_pct", 0.03)
        if hold_hours >= CONFIG["mm_max_hold_hours"]:
            if pnl_pct < mm_timeout_min_profit:
                # Not enough profit to cover taker fees + slippage. Hold position.
                # The sell at mm_ask is still posted — let it fill naturally.
                if hold_hours < CONFIG["mm_max_hold_hours"] + 1:
                    # Log once when we first skip the timeout
                    print(f"[MM] TIMEOUT HOLD: {position.get('question', '')[:40]}... "
                          f"P&L {pnl_pct:+.1%} < {mm_timeout_min_profit:.0%} min, keeping sell posted")
                return
            slippage = CONFIG.get("mm_slippage_bps", 20) / 10000
            exit_price = current_price * (1 - slippage)
            timeout_fee = polymarket_taker_fee(exit_price)
            result = self.portfolio.sell(condition_id, exit_price, "MM_TIMEOUT", fee_pct=timeout_fee)
            if result["success"]:
                trade = result["trade"]
                print(f"[MM] TIMEOUT: {trade['question'][:40]}...")
                print(f"     Held {hold_hours:.1f}h without fill, exiting at ${exit_price:.3f} (slip {slippage:.2%})")
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
                # Ghost position with no order ID — clean up
                self.portfolio.balance += position.get("cost_basis", 0)
                del self.portfolio.positions[condition_id]
                self.portfolio._save()
                print(f"[MM-LIVE] GHOST CLEANUP: no buy_order_id, returning ${position.get('cost_basis', 0):.2f}")
                return

            status = await self.executor.get_order_status(buy_order_id)

            # Order no longer exists on CLOB — clean up ghost position
            if status.get("status") in ("ERROR", "CANCELLED", "CANCELED"):
                self.portfolio.balance += position.get("cost_basis", 0)
                del self.portfolio.positions[condition_id]
                self.portfolio._save()
                reason = status.get("status")
                print(f"[MM-LIVE] BUY {reason}: order gone, returned ${position.get('cost_basis', 0):.2f}")
                return

            matched = status.get("size_matched", 0)
            original = status.get("original_size", 0)

            if original > 0 and matched >= original * 0.95:
                # Buy order filled — get REAL fill price from CLOB trades
                fill_price = await self.executor.get_fill_price(buy_order_id)
                actual_fill = fill_price if fill_price else status.get("price", position["entry_price"])
                position["live_state"] = "BUY_FILLED"
                position["actual_fill_price"] = actual_fill
                # Update entry_price to match reality so P&L calculations are correct
                if fill_price and abs(fill_price - position["entry_price"]) > 0.001:
                    print(f"[MM-LIVE] BUY FILL PRICE: ${fill_price:.4f} (limit was ${position['entry_price']:.3f})")
                    position["entry_price"] = actual_fill
                    position["cost_basis"] = actual_fill * position["shares"]
                # Reset timer so sell timeout starts from fill, not buy post
                position["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
                self.portfolio._save()
                print(f"[MM-LIVE] BUY FILLED @ ${actual_fill:.4f}: {position['question'][:40]}...")
            elif hold_hours >= CONFIG["mm_max_hold_hours"]:
                # Timeout - cancel unfilled buy
                await self.executor.cancel_order(buy_order_id)
                self.portfolio.balance += position["cost_basis"]
                del self.portfolio.positions[condition_id]
                self.portfolio._save()
                print(f"[MM-LIVE] BUY TIMEOUT: Cancelled unfilled buy after {hold_hours:.1f}h")

        elif live_state == "BUY_FILLED":
            # Post sell order at mm_ask
            if not token_id:
                print(f"[MM-LIVE] ERROR: No token_id for sell order")
                return

            # Track sell retry attempts to avoid infinite loop
            sell_retries = position.get("sell_retries", 0)
            if sell_retries >= 5:
                # NegRisk balance/allowance bug — resync and retry first
                if self.live and hasattr(self.executor, '_resync_negrisk_balance'):
                    try:
                        await self.executor._resync_negrisk_balance(token_id)
                        position["sell_retries"] = 0
                        self.portfolio._save()
                        print(f"[MM-LIVE] SELL FAILED 5x — resynced NegRisk balance, will retry")
                        return
                    except Exception as e:
                        print(f"[MM-LIVE] NegRisk resync failed: {e}")
                # Resync didn't help — ask AI what to do and at what price
                ai_exit = await self._ai_exit_decision(position, "SELL_FAILED")
                if ai_exit["action"] == "SELL":
                    exit_price = ai_exit["sell_price"]
                    result = await self.executor.post_limit_order(
                        token_id=token_id, side="SELL", price=exit_price,
                        size=round(position["shares"], 2), post_only=False
                    )
                    exit_order_id = result.get("orderID", "")
                    if exit_order_id:
                        position["live_state"] = "EXIT_PENDING"
                        position["exit_order_id"] = exit_order_id
                        position["exit_reason"] = "MM_SELL_FAILED"
                        position["exit_limit_price"] = exit_price
                        position.pop("sell_retries", None)
                        self.portfolio._save()
                        print(f"[MM-LIVE] AI EXIT @ ${exit_price:.3f}: {ai_exit['reason']}")
                    else:
                        position["sell_retries"] = 0
                        self.portfolio._save()
                else:
                    position["sell_retries"] = 0
                    self.portfolio._save()
                    print(f"[MM-LIVE] AI HOLD: {ai_exit['reason']} (true_prob={ai_exit['true_probability']:.2f})")
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
                error_msg = str(result.get("error", ""))
                if "does not exist" in error_msg:
                    # Orderbook gone — market resolved or delisted. Position is dead.
                    # Close at entry price (we may have been redeemed externally).
                    print(f"[MM-LIVE] MARKET GONE: orderbook no longer exists, closing position")
                    sale = self.portfolio.sell(condition_id, position["entry_price"], "MM_MARKET_GONE", fee_pct=0.0)
                    if sale["success"]:
                        print(f"[MM-LIVE] CLOSED (market gone): ${sale['trade']['pnl']:+.2f}")
                    return
                # Post-only rejected (would cross spread) - retry next cycle
                position["sell_retries"] = sell_retries + 1
                self.portfolio._save()
                print(f"[MM-LIVE] SELL REJECTED (attempt {sell_retries + 1}/5): {error_msg}")

        elif live_state == "SELL_PENDING":
            sell_order_id = position.get("sell_order_id", "")
            if not sell_order_id:
                # No sell order ID — go back to BUY_FILLED to repost
                position["live_state"] = "BUY_FILLED"
                self.portfolio._save()
                return

            status = await self.executor.get_order_status(sell_order_id)

            # Sell order no longer exists on CLOB — go back to BUY_FILLED to repost
            if status.get("status") == "ERROR":
                position["live_state"] = "BUY_FILLED"
                position["sell_order_id"] = ""
                self.portfolio._save()
                print(f"[MM-LIVE] SELL ORDER GONE (CLOB error), will repost next cycle")
                return

            matched = status.get("size_matched", 0)
            original = status.get("original_size", 0)

            if original > 0 and matched >= original * 0.95:
                # Sell order filled — get actual fill price from CLOB, not our limit price
                fill_price = await self.executor.get_fill_price(sell_order_id)
                actual_exit = fill_price if fill_price else mm_ask
                if fill_price and abs(fill_price - mm_ask) > 0.001:
                    print(f"[MM-LIVE] FILL PRICE: ${fill_price:.4f} (limit was ${mm_ask:.3f})")
                result = self.portfolio.sell(condition_id, actual_exit, "MM_FILLED", fee_pct=0.0)
                if result["success"]:
                    trade = result["trade"]
                    self.safety.record_trade_pnl(trade["pnl"])
                    print(f"[MM-LIVE] FILLED! P&L: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")
                return

            # Check stop-loss and timeout while waiting for sell fill
            current_price = await self._get_market_price(condition_id, position)
            if current_price is None:
                return

            pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]

            if pnl_pct <= -0.03:
                # STOP LOSS: Ask AI whether to exit and at what price
                ai_exit = await self._ai_exit_decision(position, "STOP_LOSS")
                if ai_exit["action"] == "SELL":
                    await self.executor.cancel_order(sell_order_id)
                    exit_price = ai_exit["sell_price"]
                    result = await self.executor.post_limit_order(
                        token_id=token_id, side="SELL",
                        price=exit_price, size=round(position["shares"], 2),
                        post_only=False  # Allow taker to exit fast
                    )
                    exit_order_id = result.get("orderID", "")
                    if exit_order_id:
                        position["live_state"] = "EXIT_PENDING"
                        position["exit_order_id"] = exit_order_id
                        position["exit_reason"] = "MM_STOP"
                        position["exit_limit_price"] = exit_price
                        self.portfolio._save()
                        print(f"[MM-LIVE] AI STOP EXIT @ ${exit_price:.3f}: {ai_exit['reason']}")
                else:
                    # AI says HOLD — price drop is temporary, true prob still supports our position
                    # Reset timer to avoid re-triggering immediately
                    position["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
                    self.portfolio._save()
                    print(f"[MM-LIVE] AI STOP HOLD: {ai_exit['reason']} (true_prob={ai_exit['true_probability']:.2f})")

            elif hold_hours >= CONFIG["mm_max_hold_hours"]:
                # TIMEOUT: Sell didn't fill in time. Ask AI whether to exit and at what price.
                ai_exit = await self._ai_exit_decision(position, "TIMEOUT")
                if ai_exit["action"] == "SELL":
                    await self.executor.cancel_order(sell_order_id)
                    exit_price = ai_exit["sell_price"]
                    result = await self.executor.post_limit_order(
                        token_id=token_id, side="SELL",
                        price=exit_price, size=round(position["shares"], 2),
                        post_only=False
                    )
                    exit_order_id = result.get("orderID", "")
                    if exit_order_id:
                        position["live_state"] = "EXIT_PENDING"
                        position["exit_order_id"] = exit_order_id
                        position["exit_reason"] = "MM_TIMEOUT"
                        position["exit_limit_price"] = exit_price
                        self.portfolio._save()
                        print(f"[MM-LIVE] AI TIMEOUT EXIT @ ${exit_price:.3f}: {ai_exit['reason']}")
                else:
                    # AI says HOLD — the position still has edge, keep sell order posted
                    position["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
                    self.portfolio._save()
                    print(f"[MM-LIVE] AI TIMEOUT HOLD: {ai_exit['reason']} (true_prob={ai_exit['true_probability']:.2f})")

            elif status.get("status") in ("CANCELLED", "CANCELED"):
                # Sell order cancelled externally - re-enter BUY_FILLED to repost
                position["live_state"] = "BUY_FILLED"
                position["sell_order_id"] = ""
                self.portfolio._save()
                print(f"[MM-LIVE] SELL CANCELLED externally, will repost next cycle")

        elif live_state == "EXIT_PENDING":
            # Waiting for CLOB to confirm exit order fill — then record with REAL price
            exit_order_id = position.get("exit_order_id", "")
            exit_reason = position.get("exit_reason", "MM_EXIT")
            exit_limit_price = position.get("exit_limit_price", 0)

            if not exit_order_id:
                # No exit order — shouldn't happen, recover by going back to BUY_FILLED
                position["live_state"] = "BUY_FILLED"
                self.portfolio._save()
                return

            status = await self.executor.get_order_status(exit_order_id)
            matched = status.get("size_matched", 0)
            original = status.get("original_size", 0)

            if original > 0 and matched >= original * 0.95:
                # Exit order FILLED — get the REAL execution price from CLOB
                fill_price = await self.executor.get_fill_price(exit_order_id)
                actual_exit = fill_price if fill_price else exit_limit_price

                if fill_price:
                    print(f"[MM-LIVE] EXIT CONFIRMED: CLOB fill @ ${fill_price:.4f} (limit was ${exit_limit_price:.3f})")
                else:
                    print(f"[MM-LIVE] EXIT CONFIRMED: using limit price ${exit_limit_price:.3f} (CLOB trade data unavailable)")

                # Now record the trade with the real price
                fee_pct = polymarket_taker_fee(actual_exit) if exit_reason != "MM_FILLED" else 0.0
                result = self.portfolio.sell(condition_id, actual_exit, exit_reason, fee_pct=fee_pct)
                if result["success"]:
                    trade = result["trade"]
                    self.safety.record_trade_pnl(trade["pnl"])
                    if exit_reason == "MM_STOP":
                        if condition_id not in self.stop_tracker:
                            self.stop_tracker[condition_id] = []
                        self.stop_tracker[condition_id].append(datetime.now(timezone.utc))
                        self._save_stop_tracker()
                    print(f"[MM-LIVE] {exit_reason} @ ${actual_exit:.3f}: ${trade['pnl']:+.2f} ({trade['pnl_pct']:+.1f}%)")

            elif status.get("status") in ("CANCELLED", "CANCELED", "ERROR"):
                # Exit order gone — go back to BUY_FILLED to retry
                position["live_state"] = "BUY_FILLED"
                position.pop("exit_order_id", None)
                position.pop("exit_reason", None)
                position.pop("exit_limit_price", None)
                self.portfolio._save()
                print(f"[MM-LIVE] EXIT {status.get('status')}, will retry next cycle")

    def _load_stop_tracker(self):
        """Load stop tracker from disk (survives process restarts)."""
        try:
            if self._stop_tracker_file.exists():
                with open(self._stop_tracker_file, "r") as f:
                    raw = json.load(f)
                self.stop_tracker = {}
                for cid, timestamps in raw.items():
                    self.stop_tracker[cid] = [
                        datetime.fromisoformat(ts) for ts in timestamps
                    ]
                print(f"[INIT] Loaded stop tracker: {len(self.stop_tracker)} markets tracked")
        except Exception as e:
            print(f"[INIT] Could not load stop tracker: {e}")
            self.stop_tracker = {}

    def _save_stop_tracker(self):
        """Save stop tracker to disk (atomic write)."""
        try:
            raw = {}
            for cid, timestamps in self.stop_tracker.items():
                raw[cid] = [ts.isoformat() for ts in timestamps]
            tmp_file = self._stop_tracker_file.with_suffix(".json.tmp")
            with open(tmp_file, "w") as f:
                json.dump(raw, f, indent=2)
            tmp_file.replace(self._stop_tracker_file)
        except Exception as e:
            print(f"[WARN] Could not save stop tracker: {e}")

    def _get_recent_stops(self, condition_id: str, hours: int = 24) -> list:
        """Get stop timestamps for a market within the last N hours."""
        if condition_id not in self.stop_tracker:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = [ts for ts in self.stop_tracker[condition_id] if ts > cutoff]
        # Clean up old entries
        self.stop_tracker[condition_id] = recent
        return recent

    async def _ai_reentry_check(self, opp: dict, stop_count: int) -> bool:
        """Ask Gemini whether re-entering a previously stopped market makes sense."""
        if not self.gemini:
            return False  # No AI available — don't re-enter stopped markets blindly

        question = opp.get("question", "")
        price = opp.get("price", 0)
        try:
            result = await self.gemini.evaluate_reentry(
                question=question,
                current_price=price,
                stop_count=stop_count,
                volume_24h=opp.get("volume_24h", 0),
            )
            approved = result.get("reenter", False)
            reason = result.get("reason", "no reason")
            print(f"[AI-REENTRY] {question[:40]}... → {'APPROVED' if approved else 'REJECTED'}: {reason}")
            return approved
        except Exception as e:
            print(f"[AI-REENTRY] Error: {e} — blocking re-entry")
            return False

    async def _ai_exit_decision(self, position: dict, exit_trigger: str) -> dict:
        """
        Ask Gemini AI whether to HOLD or SELL, and at what price.

        Args:
            position: The position dict with entry_price, question, token_id, etc.
            exit_trigger: "TIMEOUT" | "STOP_LOSS" | "SELL_FAILED"

        Returns:
            {"action": "HOLD"|"SELL", "true_probability": float, "sell_price": float, "reason": str}
        """
        default = {
            "action": "HOLD",
            "true_probability": position.get("entry_price", 0.5),
            "sell_price": position.get("entry_price", 0.5),
            "reason": "No AI available — holding by default",
        }
        if not self.gemini:
            return default

        # Gather context for AI
        entry_price = position["entry_price"]
        question = position.get("question", "Unknown market")
        token_id = position.get("token_id", "")
        current_price = await self._get_market_price(
            position.get("condition_id", ""), position
        )
        if current_price is None:
            current_price = entry_price

        entry_time = position.get("mm_entry_time", position.get("entry_time", ""))
        hold_hours = 0
        if entry_time:
            try:
                entered = datetime.fromisoformat(entry_time)
                hold_hours = (datetime.now(timezone.utc) - entered).total_seconds() / 3600
            except Exception:
                pass

        # Get order book for best bid/ask
        best_bid, best_ask = 0.0, 1.0
        if self.live and self.executor and token_id:
            try:
                book = await self.executor.get_order_book(token_id)
                bids = book.get("bids", [])
                asks = book.get("asks", [])
                best_bid = bids[0][0] if bids else 0.0
                best_ask = asks[0][0] if asks else 1.0
            except Exception:
                pass

        try:
            result = await self.gemini.evaluate_exit(
                question=question,
                entry_price=entry_price,
                current_price=current_price,
                hold_hours=hold_hours,
                exit_trigger=exit_trigger,
                best_bid=best_bid,
                best_ask=best_ask,
            )
            action = result.get("action", "HOLD")
            true_prob = result.get("true_probability", current_price)
            sell_price = result.get("sell_price", entry_price)
            reason = result.get("reason", "")
            print(f"[AI-EXIT] {question[:40]}... trigger={exit_trigger} → {action} (true_prob={true_prob:.2f}, sell=${sell_price:.3f}): {reason}")
            return result
        except Exception as e:
            print(f"[AI-EXIT] Error: {e} — holding by default")
            return default

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

        # CIRCUIT BREAKER: Block re-entry after too many stops on same market
        # Applies to all active trading strategies (not arb, not resolution, not MEAN_REVERSION which has own cooldown)
        CIRCUIT_BREAKER_STRATEGIES = {"MARKET_MAKER", "DIP_BUY", "VOLUME_SURGE", "MID_RANGE"}
        if opp["strategy"] in CIRCUIT_BREAKER_STRATEGIES:
            recent_stops = self._get_recent_stops(condition_id)
            if len(recent_stops) >= self.MAX_STOPS_PER_DAY:
                print(f"[CIRCUIT BREAKER] {opp['question'][:40]}... BLOCKED ({len(recent_stops)} stops in 24h)")
                return False
            # If 1 stop exists, require AI approval before re-entering
            if len(recent_stops) >= 1:
                approved = await self._ai_reentry_check(opp, len(recent_stops))
                if not approved:
                    return False

        # Check news sentiment (uses Claude API sparingly)
        if opp["strategy"] in ["DIP_BUY", "VOLUME_SURGE"]:
            news = await self.news.analyze_market(opp["question"])
            if news:
                print(f"[NEWS] {opp['question'][:40]}...")
                print(f"       {news.get('direction', 'NEUTRAL')} ({news.get('confidence', 0):.0%})")

                # Block dip buys only when bearish news confirms the dip is justified
                if opp["strategy"] == "DIP_BUY":
                    if news.get("direction") == "BEARISH" and news.get("confidence", 0) >= 0.6:
                        print(f"       Skipping: Bearish news confirms dip ({news.get('confidence', 0):.0%})")
                        return False
                # Require news direction to match surge direction
                elif opp["strategy"] == "VOLUME_SURGE":
                    surge_side = opp.get("side", "YES")
                    expected_direction = "BULLISH" if surge_side == "YES" else "BEARISH"
                    news_direction = news.get("direction", "NEUTRAL")
                    if news_direction != expected_direction or news.get("confidence", 0) < 0.5:
                        print(f"       Skipping: News {news_direction} doesn't support {surge_side} surge")
                        return False

        confidence_ok = opp["confidence"] >= CONFIG["min_confidence"]
        if not confidence_ok:
            print(f"[EVAL] {opp['strategy']}: REJECTED (confidence {opp['confidence']:.2f} < {CONFIG['min_confidence']:.2f})")
        return confidence_ok

    async def execute_trade(self, opp: dict):
        """Execute a trade for an opportunity using REAL market prices."""
        # CAPITAL RESERVATION: Hold-and-wait strategies capped at 50% of capital
        # so MARKET_MAKER always has capital for active trading
        hold_strategies = {"NEAR_CERTAIN", "NEAR_ZERO", "MID_RANGE", "MEAN_REVERSION", "NEG_RISK_ARB"}
        if opp["strategy"] in hold_strategies:
            hold_capital = sum(
                p["cost_basis"] for p in self.portfolio.positions.values()
                if p.get("strategy") in hold_strategies
            )
            if hold_capital >= self.portfolio.initial_balance * 0.50:
                print(f"[TRADE] Skipping {opp['strategy']}: Hold strategies at cap (${hold_capital:.0f}/{self.portfolio.initial_balance * 0.50:.0f})")
                return

        # Optional: AI Validator pre-trade check (fail-open if unreachable)
        if os.getenv("ENABLE_VALIDATOR"):
            try:
                validation = await self._call_validator(opp)
                if validation and not validation.get("approved", True):
                    print(f"[VALIDATOR] REJECTED: {validation.get('reason', 'unknown')}")
                    return
                elif validation and validation.get("risk_flags"):
                    flags = validation["risk_flags"]
                    print(f"[VALIDATOR] APPROVED with {len(flags)} warning(s): {flags[0]}")
            except Exception as e:
                print(f"[VALIDATOR] Unreachable ({e}), proceeding with trade")

        # Calculate position size using Monte Carlo Cap 3 Half Kelly
        # Arb strategies (guaranteed profit) and MM (spread capture, high turnover) use fixed %
        if CONFIG.get("use_kelly", False) and opp["strategy"] not in ["DUAL_SIDE_ARB", "NEG_RISK_ARB", "MARKET_MAKER"]:
            pos_pct = CONFIG.get("live_max_position_pct", 0.50) if self.live else CONFIG.get("kelly_max_position", 0.30)
            kelly = KellyCriterion(
                kelly_fraction=CONFIG.get("kelly_fraction", 0.50),
                max_position_pct=pos_pct,
                min_edge=CONFIG.get("kelly_min_edge", 0.02),
                mc_validated=getattr(self, '_mc_validated', False),
            )
            kelly_result = kelly.calculate_from_opportunity(opp, self.portfolio.balance)

            if kelly_result:
                max_amount = kelly_result.position_size
                emp_tag = "EMP" if kelly_result.empirical_edge_used else "HEU"
                print(f"[KELLY] Edge: {kelly_result.edge:.1%} | Raw: {kelly_result.kelly_fraction:.1%} | "
                      f"Half: {kelly_result.adjusted_fraction:.1%} | ${kelly_result.position_size:.0f} | "
                      f"Risk: {kelly_result.risk_level} | {emp_tag}")
            else:
                # Fall back to fixed percentage if Kelly returns None (no edge)
                fallback_pct = CONFIG.get("live_max_position_pct", 0.50) if self.live else CONFIG["max_position_pct"]
                max_amount = self.portfolio.balance * fallback_pct
        else:
            # Fixed percentage for special strategies or when Kelly disabled
            fallback_pct = CONFIG.get("live_max_position_pct", 0.50) if self.live else CONFIG["max_position_pct"]
            max_amount = self.portfolio.balance * fallback_pct

        # REALISTIC CONSTRAINT: Can't buy more than 1% of market liquidity
        # This prevents unrealistic fills that wouldn't happen in real trading
        liquidity = opp.get("liquidity", 10000)
        max_liquidity_amount = liquidity * 0.01  # Max 1% of liquidity

        per_trade_cap = CONFIG.get("live_max_order", 10) if self.live else 200
        amount = min(max_amount, max_liquidity_amount, per_trade_cap)

        # Minimum position size (lower for live small accounts)
        min_position = CONFIG.get("live_min_position", 5) if self.live else 50
        if amount < min_position:
            print(f"[TRADE] Skipping: Position too small (${amount:.2f} < ${min_position} minimum)")
            return

        # NEG_RISK_ARB: Multi-outcome arbitrage — buy/sell all outcomes
        if opp["strategy"] == "NEG_RISK_ARB":
            await self._execute_negrisk_arb(opp, amount)
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
            # SIMULATION: Record virtual trade with realistic fees + slippage
            is_maker = opp["strategy"] in MAKER_STRATEGIES
            entry_fee = 0.0 if is_maker else polymarket_taker_fee(opp["price"])
            # Taker slippage: worse fill on thin markets (makers have own slippage in Phase 2)
            if is_maker:
                fill_price = opp["price"]
            else:
                slip = taker_slippage(opp.get("liquidity", 50000))
                fill_price = opp["price"] * (1 + slip)  # Slippage works against buyer
            result = self.portfolio.buy(
                condition_id=opp["condition_id"],
                question=opp["question"],
                side=opp["side"],
                price=fill_price,
                amount=amount,
                reason=opp["reason"],
                strategy=opp["strategy"],
                fee_pct=entry_fee,
            )

            if result["success"]:
                # Store token_id for WS price feed
                token_id = opp.get("token_id_yes")
                if token_id:
                    pos = self.portfolio.positions[opp["condition_id"]]
                    pos["token_id"] = token_id
                    self.portfolio._save()
                    await self._ws_subscribe_position(token_id)

                annualized = opp.get("annualized_return", 0)
                days = opp.get("days_to_resolve", "?")
                print(f"[TRADE] BUY ${amount:.2f} {opp['side']} @ {opp['price']:.3f}")
                print(f"        Market: {opp['question'][:50]}...")
                print(f"        Strategy: {opp['strategy']} | {days}d to resolve | {annualized:.0%} APY")

    async def _call_validator(self, opp: dict) -> Optional[dict]:
        """Call the AI Validator service for pre-trade approval."""
        validator_url = os.getenv("VALIDATOR_URL", "http://validator:8100/validate")
        payload = {
            "condition_id": opp.get("condition_id", ""),
            "question": opp.get("question", ""),
            "strategy": opp.get("strategy", ""),
            "side": opp.get("side"),
            "price": opp.get("price"),
            "amount": self.portfolio.balance * CONFIG["max_position_pct"],
            "confidence": opp.get("confidence"),
            "ai_score": opp.get("ai_score"),
            "portfolio_summary": self.portfolio.get_summary(),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(validator_url, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return await resp.json()
        return None

    async def _execute_negrisk_arb(self, opp: dict, total_amount: float):
        """
        Execute NEG_RISK ARBITRAGE: Buy or sell YES on all outcomes of a multi-outcome event.

        SELL_ALL: If bid_sum > 1.0, sell YES on all outcomes.
          Revenue = bid_sum per share, Liability = 1.0 (one resolves YES).
        BUY_ALL: If ask_sum < 1.0, buy YES on all outcomes.
          Cost = ask_sum per share, Payout = 1.0 (one resolves YES).

        Paper trading: record as a single position, lock in profit immediately.
        """
        side = opp.get("side", "BUY_ALL")
        price_sum = opp.get("price", 1.0)  # bid_sum or ask_sum
        num_outcomes = opp.get("num_outcomes", 0)

        if side == "SELL_ALL":
            edge = price_sum - 1.0
        else:  # BUY_ALL
            edge = 1.0 - price_sum

        if edge <= 0:
            print(f"[NEGRISK] Skipping: No edge ({side}, sum={price_sum:.3f})")
            return

        locked_profit = total_amount * edge

        if self.live:
            print(f"[NEGRISK] LIVE MODE: Would {side} {num_outcomes} outcomes, edge={edge:.1%}")
            print(f"           Locked profit: ${locked_profit:.2f}")
            return

        # SIMULATION: Record as single position with guaranteed profit
        # Arb entries are taker (buying from orderbook)
        arb_fee = polymarket_taker_fee(price_sum if side == "BUY_ALL" else 1.0)
        result = self.portfolio.buy(
            condition_id=opp["condition_id"],
            question=opp["question"],
            side="BOTH",
            price=price_sum if side == "BUY_ALL" else 1.0,
            amount=total_amount,
            reason=opp["reason"],
            strategy="NEG_RISK_ARB",
            fee_pct=arb_fee,
        )

        if result["success"]:
            print(f"[NEGRISK] {side} ${total_amount:.2f} across {num_outcomes} outcomes")
            print(f"           Sum: {price_sum:.3f} | Edge: {edge:.1%}")
            print(f"           LOCKED PROFIT: ${locked_profit:.2f}")
            print(f"           Event: {opp['question'][:60]}...")

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
        # Arb entries are taker (buying from orderbook)
        arb_fee = polymarket_taker_fee(total_cost)
        result = self.portfolio.buy(
            condition_id=opp["condition_id"],
            question=opp["question"],
            side="BOTH",
            price=total_cost,
            amount=total_amount,
            reason=opp["reason"],
            strategy="DUAL_SIDE_ARB",
            fee_pct=arb_fee,
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

        if mid_price <= 0:
            print(f"[MM] Skipping: Invalid price ${mid_price}")
            return

        # Use AI-recommended spread if available (from Phase 2 deep screen), else default 2%
        ai_spread = opp.get("ai_spread", CONFIG["mm_target_profit"])
        mm_bid = round(mid_price - max(mid_price * ai_spread, 0.01), 3)
        mm_ask = round(mid_price + max(mid_price * ai_spread, 0.01), 3)
        spread_pct = opp.get("spread_pct", 0.02)

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
                pos["mm_target_profit"] = ai_spread
                pos["buy_order_id"] = order_id
                pos["sell_order_id"] = ""
                pos["token_id"] = token_id
                pos["live_state"] = "BUY_PENDING"
                pos["sector"] = opp.get("sector", "other")
                pos["ai_score"] = opp.get("ai_score", 0)
                self.portfolio._save()
            return

        # SIMULATION: Record as MM position with special tracking
        # Entry at bid + slippage (realistic: we don't always get best bid)
        # MM entry is maker (post-only limit) = ZERO fee
        slippage = CONFIG.get("mm_slippage_bps", 20) / 10000
        entry_price = mm_bid * (1 + slippage)  # Slippage works against us on buy
        result = self.portfolio.buy(
            condition_id=opp["condition_id"],
            question=opp["question"],
            side="MM",
            price=entry_price,
            amount=buy_amount,
            reason=opp["reason"],
            strategy="MARKET_MAKER",
            fee_pct=0.0,
        )

        if result["success"]:
            # Store MM-specific data for exit simulation
            pos = self.portfolio.positions[opp["condition_id"]]
            pos["mm_bid"] = mm_bid
            pos["mm_ask"] = mm_ask
            pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
            pos["mm_target_profit"] = ai_spread
            pos["sector"] = opp.get("sector", "other")
            pos["ai_score"] = opp.get("ai_score", 0)
            # Store token_id for WS price feed
            token_id = opp.get("token_id_yes")
            if token_id:
                pos["token_id"] = token_id
                await self._ws_subscribe_position(token_id)
            self.portfolio._save()

            expected_profit = buy_amount * ai_spread
            print(f"[MM] POSITION OPENED @ ${mm_bid:.3f}")
            print(f"     Market: {opp['question'][:50]}...")
            print(f"     Target Exit: ${mm_ask:.3f} (+{ai_spread:.1%})")
            print(f"     Expected Profit: ${expected_profit:.2f}")
            print(f"     Sector: {opp.get('sector', 'other')} | AI: {opp.get('ai_score', 'N/A')}/10")
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

        # SIMULATION: Execute the trade (taker entry)
        entry_fee = polymarket_taker_fee(price)
        result = self.portfolio.buy(
            condition_id=opp["condition_id"],
            question=opp["question"],
            side=side,
            price=price,
            amount=amount,
            reason=opp["reason"],
            strategy="BINANCE_ARB",
            fee_pct=entry_fee,
        )

        if result["success"]:
            print(f"[BINANCE_ARB] BUY {side} @ ${price:.3f}")
            print(f"     Market: {opp['question'][:50]}...")
            print(f"     Edge: {edge:+.1f}% | Binance: ${binance_price:,.0f} → Target: ${target_price:,.0f}")
            print(f"     Amount: ${amount:.2f} | Confidence: {opp.get('confidence', 0):.0%}")

    async def _ai_deep_screen(self, opp: dict) -> Optional[dict]:
        """Phase 2: AI deep screen with news context for MM and MR candidates."""
        if not self.gemini:
            return None

        # Fetch recent news headlines for context
        headlines = []
        try:
            articles = await self.news_intel.fetch_headlines(opp["question"], max_results=3)
            headlines = [a["title"] for a in articles if a.get("title")]
        except Exception as e:
            print(f"[AI] News fetch error: {e}")

        # Deep screen with full market context
        try:
            result = await self.gemini.deep_screen_market(
                question=opp["question"],
                price=opp.get("price", 0),
                end_date=opp.get("end_date", ""),
                volume_24h=opp.get("volume_24h", 0),
                spread_pct=opp.get("spread_pct", 0),
                liquidity=opp.get("liquidity", 0),
                best_bid=opp.get("best_bid", 0),
                best_ask=opp.get("best_ask", 0),
                news_headlines=headlines,
                days_to_resolve=opp.get("days_to_resolve", 0),
                condition_id=opp.get("condition_id", ""),
            )
            cached_tag = " (cached)" if result.get("cached") else ""
            score = result.get("quality_score", 0)
            sector = result.get("sector", "other")
            spread = result.get("recommended_spread_pct", 0.02)
            print(f"[AI] {opp['question'][:50]}... → {score}/10 [{sector}] spread={spread:.1%}{cached_tag}")
            return result
        except Exception as e:
            print(f"[AI] Screen error: {e}")
            return None

    def _check_portfolio_concentration(self, sector: str, condition_id: str) -> bool:
        """Phase 3: Check if adding this position would over-concentrate the portfolio."""
        # Rule 1: No duplicate markets
        if condition_id in self.portfolio.positions:
            return False

        # Rule 2: Max 2 positions in same sector
        sector_count = 0
        sector_value = 0.0
        total_value = self.portfolio.balance
        for pos in self.portfolio.positions.values():
            total_value += pos.get("cost_basis", 0)
            if pos.get("sector", "other") == sector:
                sector_count += 1
                sector_value += pos.get("cost_basis", 0)

        if sector_count >= 2:
            print(f"[DIVERSIFY] Skipping: already {sector_count} positions in '{sector}'")
            return False

        # Rule 3: Max 40% of portfolio in any one sector
        if total_value > 0 and sector_value / total_value > 0.40:
            print(f"[DIVERSIFY] Skipping: '{sector}' already {sector_value/total_value:.0%} of portfolio")
            return False

        return True

    def _portfolio_select(self, screened: list) -> list:
        """Phase 3: Portfolio-aware selection — diversify and rank by AI score."""
        selected = []
        for opp in screened:
            if opp["strategy"] == "MARKET_MAKER":
                sector = opp.get("sector", "other")
                if not self._check_portfolio_concentration(sector, opp["condition_id"]):
                    continue
            selected.append(opp)

        # Sort MM opportunities by AI score (higher = better), others keep their order
        selected.sort(
            key=lambda x: x.get("ai_score", x.get("annualized_return", x.get("confidence", 0))),
            reverse=True
        )
        return selected

    async def _startup_reconcile(self):
        """
        On live startup, validate all positions against the CLOB and on-chain balance.

        Ghost positions (orders that no longer exist) are cleaned up immediately.
        Balance is synced to on-chain wallet after ghost cleanup.
        This runs ONCE at startup before the trading loop begins.
        """
        if not self.live or not self.executor:
            return

        positions = list(self.portfolio.positions.items())
        if not positions:
            # No positions — just sync balance
            try:
                on_chain = await self.executor.get_balance_usdc()
                if on_chain is not None and abs(on_chain - self.portfolio.balance) > 0.50:
                    old = self.portfolio.balance
                    self.portfolio.balance = on_chain
                    self.portfolio._save()
                    print(f"[RECONCILE] Balance synced: ${old:.2f} → ${on_chain:.2f}")
                else:
                    print(f"[RECONCILE] Balance OK: ${self.portfolio.balance:.2f}")
            except Exception as e:
                print(f"[RECONCILE] Balance check failed: {e}")
            return

        print(f"[RECONCILE] Validating {len(positions)} positions against CLOB...")
        ghosts_cleaned = 0

        for condition_id, pos in positions:
            live_state = pos.get("live_state", "")
            order_id = ""

            if live_state == "BUY_PENDING":
                order_id = pos.get("buy_order_id", "")
            elif live_state == "SELL_PENDING":
                order_id = pos.get("sell_order_id", "")
            elif live_state == "EXIT_PENDING":
                order_id = pos.get("exit_order_id", "")
            elif live_state == "BUY_FILLED":
                # Has shares but no pending order — valid state, skip
                print(f"[RECONCILE] {pos.get('question', '')[:40]}... BUY_FILLED (has shares, needs sell)")
                continue
            else:
                # Unknown state — skip
                continue

            if not order_id:
                # No order ID — ghost, clean up
                if live_state == "BUY_PENDING":
                    self.portfolio.balance += pos.get("cost_basis", 0)
                del self.portfolio.positions[condition_id]
                ghosts_cleaned += 1
                print(f"[RECONCILE] GHOST (no order_id): {pos.get('question', '')[:40]}... → removed")
                continue

            # Check if order still exists on CLOB
            status = await self.executor.get_order_status(order_id)
            clob_status = status.get("status", "UNKNOWN")

            if clob_status in ("ERROR", "UNKNOWN"):
                # Order doesn't exist on CLOB anymore
                if live_state == "BUY_PENDING":
                    self.portfolio.balance += pos.get("cost_basis", 0)
                    del self.portfolio.positions[condition_id]
                    ghosts_cleaned += 1
                    print(f"[RECONCILE] GHOST (order gone): {pos.get('question', '')[:40]}... → returned ${pos.get('cost_basis', 0):.2f}")
                elif live_state in ("SELL_PENDING", "EXIT_PENDING"):
                    # Sell/exit order gone — revert to BUY_FILLED to repost
                    pos["live_state"] = "BUY_FILLED"
                    pos.pop("sell_order_id", None)
                    pos.pop("exit_order_id", None)
                    pos.pop("exit_reason", None)
                    pos.pop("exit_limit_price", None)
                    print(f"[RECONCILE] STALE SELL: {pos.get('question', '')[:40]}... → reverted to BUY_FILLED")
            elif clob_status in ("CANCELLED", "CANCELED"):
                if live_state == "BUY_PENDING":
                    self.portfolio.balance += pos.get("cost_basis", 0)
                    del self.portfolio.positions[condition_id]
                    ghosts_cleaned += 1
                    print(f"[RECONCILE] CANCELLED: {pos.get('question', '')[:40]}... → returned ${pos.get('cost_basis', 0):.2f}")
                elif live_state in ("SELL_PENDING", "EXIT_PENDING"):
                    pos["live_state"] = "BUY_FILLED"
                    pos.pop("sell_order_id", None)
                    pos.pop("exit_order_id", None)
                    print(f"[RECONCILE] CANCELLED SELL: {pos.get('question', '')[:40]}... → reverted to BUY_FILLED")
            else:
                print(f"[RECONCILE] VALID: {pos.get('question', '')[:40]}... state={live_state} clob={clob_status}")

        if ghosts_cleaned > 0:
            self.portfolio._save()
            print(f"[RECONCILE] Cleaned {ghosts_cleaned} ghost positions")

        # ALWAYS sync balance to on-chain (CLOB buys are off-chain, don't move USDC)
        try:
            on_chain = await self.executor.get_balance_usdc()
            if on_chain is not None:
                pending_cost = sum(
                    p.get("cost_basis", 0)
                    for p in self.portfolio.positions.values()
                    if p.get("live_state") == "BUY_PENDING"
                )
                correct_balance = round(on_chain - pending_cost, 2)
                if abs(correct_balance - self.portfolio.balance) > 0.50:
                    old = self.portfolio.balance
                    self.portfolio.balance = correct_balance
                    self.portfolio._save()
                    print(f"[RECONCILE] Balance synced: ${old:.2f} → ${correct_balance:.2f} (on-chain=${on_chain:.2f}, pending=${pending_cost:.2f})")
                else:
                    print(f"[RECONCILE] Balance: ${self.portfolio.balance:.2f} (on-chain: ${on_chain:.2f})")
        except Exception as e:
            print(f"[RECONCILE] Balance check failed: {e}")

    async def _log_on_chain_balance(self):
        """Sync on-chain balance with internal state.

        ALWAYS sync: on-chain USDC is the source of truth. CLOB buy orders
        are off-chain intents — they do NOT move USDC from the wallet.
        Internal balance = on_chain - sum(cost_basis of BUY_PENDING positions).
        """
        try:
            on_chain = await self.executor.get_balance_usdc()
            if on_chain is None:
                return

            # Internal balance should be: on-chain minus cost of pending buys
            pending_cost = sum(
                pos.get("cost_basis", 0)
                for pos in self.portfolio.positions.values()
                if pos.get("live_state") == "BUY_PENDING"
            )
            correct_balance = round(on_chain - pending_cost, 2)
            drift = abs(correct_balance - self.portfolio.balance)

            if drift > 0.50:
                old_balance = self.portfolio.balance
                self.portfolio.balance = correct_balance
                self.portfolio._save()
                reason = ""
                if correct_balance > old_balance + 5:
                    reason = " (deposit detected!)"
                print(f"[CHAIN] SYNCED: ${old_balance:.2f} → ${correct_balance:.2f} "
                      f"(on-chain=${on_chain:.2f}, pending_buys=${pending_cost:.2f}){reason}")
            else:
                print(f"[CHAIN] OK: wallet=${on_chain:.2f}, internal=${self.portfolio.balance:.2f}, pending=${pending_cost:.2f}")
        except Exception as e:
            print(f"[CHAIN] Error: {e}")

    async def run_cycle(self):
        """Run one trading cycle."""
        print(f"\n{'='*60}")
        print(f"  CYCLE @ {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}")

        # 0. On-chain balance sync — auto-corrects when no orders are in flight.
        # Ghost positions are cleaned at startup (_startup_reconcile), so
        # has_pending_orders should be accurate during normal operation.
        if self.live:
            now_utc = datetime.now(timezone.utc)
            sync_interval = 300  # 5 minutes
            if not hasattr(self, '_last_sync_time') or self._last_sync_time is None \
               or (now_utc - self._last_sync_time).total_seconds() >= sync_interval:
                self._last_sync_time = now_utc
                await self._log_on_chain_balance()

        # 1. Check exits on existing positions (EVERY cycle — 60s)
        if self.portfolio.positions:
            print(f"\n[POSITIONS] Checking {len(self.portfolio.positions)} open positions...")
            await self.check_exits()

        # 2. Scan for new opportunities (only every scan_interval — 10 min)
        now = datetime.now(timezone.utc)
        scan_interval = CONFIG.get("scan_interval", 600)
        should_scan = (
            self._last_scan_time is None
            or (now - self._last_scan_time).total_seconds() >= scan_interval
        )

        if should_scan:
            self._last_scan_time = now
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

            # === PHASE 1: DISCOVERY (heuristic filter, no AI) ===
            opportunities = self.scanner.find_opportunities(markets, binance_prices)

            # NEG_RISK_ARB: Fetch multi-outcome events and find arbitrage
            negrisk_events = await self.scanner.fetch_negrisk_events()
            negrisk_opps = self.scanner.find_negrisk_opportunities(negrisk_events)
            if negrisk_opps:
                print(f"[NEGRISK] Scanned {len(negrisk_events)} events → {len(negrisk_opps)} arb opportunities")
                opportunities.extend(negrisk_opps)

            print(f"[SCANNER] Identified {len(opportunities)} opportunities")

            # Log market snapshot for future backtesting
            self._log_snapshot(markets, binance_prices)

            # === PHASE 2: AI DEEP SCREEN (Gemini + news, cached 1hr) ===
            ai_screened_strategies = {"MARKET_MAKER", "MEAN_REVERSION"}
            screened = []
            for opp in opportunities:
                if opp["strategy"] in ai_screened_strategies and CONFIG.get("mm_ai_screen"):
                    screen = await self._ai_deep_screen(opp)
                    if screen and screen.get("approved") and screen.get("quality_score", 0) >= 6:
                        opp["ai_score"] = screen["quality_score"]
                        opp["ai_spread"] = screen.get("recommended_spread_pct", 0.02)
                        opp["sector"] = screen.get("sector", "other")
                        opp["catalyst_expected"] = screen.get("catalyst_expected", False)
                        screened.append(opp)
                    elif screen:
                        score = screen.get("quality_score", 0)
                        print(f"[AI] REJECTED ({score}/10): {opp['question'][:50]}... → {screen.get('reason', '')}")
                else:
                    screened.append(opp)  # Other strategies pass through

            # === PHASE 3: PORTFOLIO-AWARE SELECTION ===
            selected = self._portfolio_select(screened)
            mm_count = sum(1 for o in selected if o["strategy"] == "MARKET_MAKER")
            print(f"[PIPELINE] Phase 1→{len(opportunities)} → Phase 2→{len(screened)} → Phase 3→{len(selected)} (MM: {mm_count})")

            # === PHASE 4: EXECUTE (with AI-recommended spread) ===
            # Prioritize active strategies (MM) over hold-and-wait strategies
            # Cap at 3 new entries per cycle — preserves capital for better opportunities
            active_strats = [o for o in selected if o["strategy"] in ("MARKET_MAKER", "NEG_RISK_ARB")]
            hold_strats = [o for o in selected if o["strategy"] not in ("MARKET_MAKER", "NEG_RISK_ARB")]
            ordered = active_strats + hold_strats
            executed = 0
            for opp in ordered:
                if executed >= 3:  # Max 3 new entries per cycle — pace capital deployment
                    break
                if await self.evaluate_opportunity(opp):
                    await self.execute_trade(opp)
                    executed += 1
                    await asyncio.sleep(1)  # Rate limit
        else:
            print(f"\n[SCANNER] Exit-check only (next scan in {scan_interval - (now - self._last_scan_time).total_seconds():.0f}s)")

        # Print summary
        summary = self.portfolio.get_summary()
        print(f"\n[PORTFOLIO]")
        print(f"  Balance: ${summary['balance']:.2f}")
        print(f"  Open Positions: {summary['open_positions']}")
        print(f"  Total P&L: ${summary['total_pnl']:+.2f}")
        print(f"  Win Rate: {summary['win_rate']:.1f}%")
        print(f"  ROI: {summary['roi_pct']:+.1f}%")

        # Strategy A/B report
        print(f"\n{self.portfolio.get_strategy_report()}")

        # Write heartbeat for external monitoring (watchdog, alerter)
        try:
            heartbeat = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "positions": len(self.portfolio.positions),
                "balance": round(self.portfolio.balance, 2),
                "pnl": round(self.portfolio.metrics.get("total_pnl", 0), 2),
                "trades": self.portfolio.metrics.get("total_trades", 0),
                "win_rate": round(summary.get("win_rate", 0), 1),
            }
            heartbeat_path = Path(__file__).parent / "data" / ".heartbeat.json"
            with open(heartbeat_path, "w") as f:
                json.dump(heartbeat, f)
        except Exception:
            pass  # Never let monitoring break trading

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
                        "chg1h": float(m.get("oneHourPriceChange") or 0),
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

        # Live startup: reconcile portfolio with on-chain reality
        if self.live:
            await self._startup_reconcile()

        self.running = True

        # Start WebSocket listener if configured
        await self._ws_start()

        try:
            while self.running:
                # Check kill switch in live mode
                if self.live and self.safety.check_kill_switch():
                    print("[SHUTDOWN] Kill switch detected!")
                    break
                # WS health check — reconnect if stale
                await self._ws_health_check()
                await self.run_cycle()
                interval = CONFIG.get("exit_check_interval", 60)
                print(f"\n[SLEEP] Next check in {interval}s...")
                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Stopping gracefully...")
        finally:
            self.running = False

            # Close WebSocket
            if self.ws:
                await self.ws.close()
            if self._ws_task and not self._ws_task.done():
                self._ws_task.cancel()

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
