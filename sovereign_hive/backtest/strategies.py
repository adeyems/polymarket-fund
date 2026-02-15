#!/usr/bin/env python3
"""
BACKTEST STRATEGY ADAPTERS
============================
Production strategy logic adapted for backtesting.

IMPORTANT: Strategies are split into two groups based on data requirements:

PRICE_ONLY_STRATEGIES — Can be backtested on Kaggle data (mid-price only):
  NEAR_CERTAIN, NEAR_ZERO, MEAN_REVERSION, DIP_BUY, MID_RANGE

SPREAD_STRATEGIES — Require real bid/ask data (collected snapshots):
  MARKET_MAKER, DUAL_SIDE_ARB, BINANCE_ARB, VOLUME_SURGE
"""

from datetime import datetime, timedelta
from typing import Optional, Dict

from .data_loader import MarketHistory, MarketSnapshot


# ============================================================
# Shared state for strategies that need memory across calls
# ============================================================

class StrategyState:
    """Tracks per-strategy state across backtest timesteps."""

    def __init__(self):
        self.mr_last_exit: Dict[str, datetime] = {}
        self.mr_entry_count: Dict[str, int] = {}
        self.mr_cooldown_hours: float = 48.0
        self.mr_max_entries: int = 2
        self.mm_entries: Dict[str, dict] = {}

    def record_mr_exit(self, condition_id: str, timestamp: datetime):
        self.mr_last_exit[condition_id] = timestamp

    def can_enter_mr(self, condition_id: str, timestamp: datetime) -> bool:
        if condition_id in self.mr_last_exit:
            elapsed = (timestamp - self.mr_last_exit[condition_id]).total_seconds() / 3600
            if elapsed < self.mr_cooldown_hours:
                return False
        if self.mr_entry_count.get(condition_id, 0) >= self.mr_max_entries:
            return False
        return True

    def record_mr_entry(self, condition_id: str):
        self.mr_entry_count[condition_id] = self.mr_entry_count.get(condition_id, 0) + 1

    def record_mm_entry(self, condition_id: str, timestamp: datetime, mm_bid: float, mm_ask: float):
        self.mm_entries[condition_id] = {"entry_time": timestamp, "mm_bid": mm_bid, "mm_ask": mm_ask}

    def get_mm_entry(self, condition_id: str) -> Optional[dict]:
        return self.mm_entries.get(condition_id)

    def clear_mm_entry(self, condition_id: str):
        self.mm_entries.pop(condition_id, None)


_state = StrategyState()

def reset_state():
    global _state
    _state = StrategyState()

def get_state() -> StrategyState:
    return _state


# ============================================================
# CONFIG matching production run_simulation.py
# ============================================================

PROD_CONFIG = {
    "near_certain_min": 0.95,
    "near_zero_max": 0.05,
    "dip_threshold": -0.05,
    "volume_surge_mult": 2.0,
    "mid_range_min": 0.20,
    "mid_range_max": 0.80,
    "min_24h_volume": 10000,
    "mean_reversion_low": 0.30,
    "mean_reversion_high": 0.70,
    "mm_min_spread": 0.02,
    "mm_max_spread": 0.10,
    "mm_min_volume_24h": 15000,
    "mm_price_range": (0.03, 0.97),
    "dual_side_min_profit": 0.02,
    "binance_min_edge": 0.05,
    "max_days_to_resolve": 90,
    "min_annualized_return": 0.15,
}


def _annualized_return(simple_return: float, days: float) -> float:
    if days <= 0 or simple_return <= -1:
        return 0.0
    try:
        return (pow(1 + simple_return, 365.0 / days) - 1)
    except (OverflowError, ValueError):
        return 10.0


# ============================================================
# PRICE-ONLY STRATEGIES (testable on Kaggle data)
# These use snap.price only — no bid/ask/volume dependency
# ============================================================

def near_certain(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """Buy YES when price >= 95%. Uses PRICE only."""
    if snap.price < PROD_CONFIG["near_certain_min"]:
        return None
    if snap.days_to_resolve > PROD_CONFIG["max_days_to_resolve"]:
        return None

    expected_return = (1.0 - snap.price) / snap.price if snap.price > 0 else 0
    annualized = _annualized_return(expected_return, snap.days_to_resolve)
    if annualized < PROD_CONFIG["min_annualized_return"]:
        return None

    return {
        "action": "BUY", "side": "YES", "price": snap.price,
        "confidence": 0.95, "strategy": "NEAR_CERTAIN",
        "reason": f"Near-certain {snap.price:.0%}, {snap.days_to_resolve:.0f}d, {annualized:.0%} APY",
    }


def near_zero(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """Buy NO when YES price <= 5%. Uses PRICE only."""
    if snap.price > PROD_CONFIG["near_zero_max"] or snap.price <= 0:
        return None
    if snap.days_to_resolve > PROD_CONFIG["max_days_to_resolve"]:
        return None

    no_price = 1.0 - snap.price
    if no_price >= 0.98:
        return None

    expected_return = (1.0 - no_price) / no_price if no_price > 0 else 0
    annualized = _annualized_return(expected_return, snap.days_to_resolve)
    if annualized < PROD_CONFIG["min_annualized_return"]:
        return None

    return {
        "action": "BUY", "side": "NO", "price": no_price,
        "confidence": 0.95, "strategy": "NEAR_ZERO",
        "reason": f"Near-zero YES {snap.price:.0%}, {snap.days_to_resolve:.0f}d, {annualized:.0%} APY",
    }


def dip_buy(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """Buy when price dropped >5% in 24h. Uses PRICE + price_change only."""
    if snap.price_change_24h >= PROD_CONFIG["dip_threshold"]:
        return None
    # In price-only mode, we can't check volume — skip that filter
    # (production requires volume > 30000 but we don't have real volume)

    return {
        "action": "BUY", "side": "YES", "price": snap.price,
        "confidence": 0.65, "strategy": "DIP_BUY",
        "reason": f"Dip {snap.price_change_24h:.0%}",
    }


def mid_range(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """Trade with momentum in 20-80% range. Uses PRICE + price_change only."""
    if snap.price < PROD_CONFIG["mid_range_min"] or snap.price > PROD_CONFIG["mid_range_max"]:
        return None
    # Skip volume filter in price-only mode (no real volume data)

    if snap.price_change_24h > 0.005:
        return {
            "action": "BUY", "side": "YES", "price": snap.price,
            "confidence": 0.55, "strategy": "MID_RANGE",
            "reason": f"MID UP {snap.price_change_24h:+.1%}",
        }
    elif snap.price_change_24h < -0.005:
        return {
            "action": "BUY", "side": "NO", "price": 1.0 - snap.price,
            "confidence": 0.55, "strategy": "MID_RANGE",
            "reason": f"MID DOWN {snap.price_change_24h:+.1%}",
        }
    return None


def mean_reversion(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """
    Buy YES when price < 30%, buy NO when price > 70%.
    Uses PRICE only. Includes fixes: cooldown, trend filter, entry limit.
    """
    # Skip volume filter in price-only mode
    state = get_state()
    low = PROD_CONFIG["mean_reversion_low"]
    high = PROD_CONFIG["mean_reversion_high"]

    side = None
    if snap.price < low and snap.price > 0.05:
        side = "YES"
    elif snap.price > high and snap.price < 0.95:
        side = "NO"
    else:
        return None

    if not state.can_enter_mr(market.condition_id, timestamp):
        return None

    # Trend filter: don't fight strong 7-day momentum
    price_7d = market.get_price_change(timestamp, lookback_hours=168)
    if price_7d is not None:
        if side == "YES" and price_7d < -0.10:
            return None
        if side == "NO" and price_7d > 0.10:
            return None

    state.record_mr_entry(market.condition_id)

    entry_price = snap.price if side == "YES" else (1.0 - snap.price)

    return {
        "action": "BUY", "side": side, "price": entry_price,
        "confidence": 0.60, "strategy": "MEAN_REVERSION",
        "reason": f"MEAN_REV: Price {snap.price:.0%} {'< 30%' if side == 'YES' else '> 70%'}",
    }


def mean_reversion_broken(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """BROKEN version: no cooldown, no trend filter, no entry limit."""
    low = PROD_CONFIG["mean_reversion_low"]
    high = PROD_CONFIG["mean_reversion_high"]

    if snap.price < low and snap.price > 0.05:
        return {
            "action": "BUY", "side": "YES", "price": snap.price,
            "confidence": 0.60, "strategy": "MEAN_REVERSION",
            "reason": f"MEAN_REV: Price {snap.price:.0%} < 30%",
        }
    elif snap.price > high and snap.price < 0.95:
        return {
            "action": "BUY", "side": "NO", "price": 1.0 - snap.price,
            "confidence": 0.60, "strategy": "MEAN_REVERSION",
            "reason": f"MEAN_REV: Price {snap.price:.0%} > 70%",
        }
    return None


# ============================================================
# SPREAD-DEPENDENT STRATEGIES (require real bid/ask data)
# These CANNOT be backtested on Kaggle/synthetic data
# ============================================================

def market_maker(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """REQUIRES REAL BID/ASK DATA. Do not run on Kaggle/synthetic data."""
    mm_min, mm_max = PROD_CONFIG["mm_price_range"]
    if snap.price < mm_min or snap.price > mm_max:
        return None
    if snap.bid <= 0:
        return None
    if snap.volume_24h < PROD_CONFIG["mm_min_volume_24h"]:
        return None

    spread_pct = (snap.ask - snap.bid) / ((snap.ask + snap.bid) / 2) if (snap.ask + snap.bid) > 0 else 0
    if spread_pct < PROD_CONFIG["mm_min_spread"] or spread_pct > PROD_CONFIG["mm_max_spread"]:
        return None

    mid_price = (snap.ask + snap.bid) / 2
    mm_bid = round(mid_price - max(mid_price * 0.02, 0.01), 3)
    mm_ask = round(mid_price + max(mid_price * 0.02, 0.01), 3)

    state = get_state()
    state.record_mm_entry(market.condition_id, timestamp, mm_bid, mm_ask)

    return {
        "action": "BUY", "side": "MM", "price": mm_bid,
        "mm_bid": mm_bid, "mm_ask": mm_ask,
        "confidence": 0.65, "strategy": "MARKET_MAKER",
        "reason": f"MM: Spread {spread_pct:.1%}, Vol ${snap.volume_24h/1000:.0f}k",
    }


def market_maker_broken(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """BROKEN version for A/B testing. Same entry, different exit model."""
    return market_maker(market, snap, timestamp)


def dual_side_arb(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """REQUIRES REAL BID/ASK DATA."""
    yes_price = snap.ask
    no_price = 1.0 - snap.bid if snap.bid > 0 else 1.0 - snap.price
    total_cost = yes_price + no_price

    if total_cost >= (1.0 - PROD_CONFIG["dual_side_min_profit"]):
        return None

    profit_pct = (1.0 - total_cost) / total_cost
    return {
        "action": "BUY", "side": "BOTH", "price": total_cost,
        "yes_price": yes_price, "no_price": no_price,
        "confidence": 0.99, "strategy": "DUAL_SIDE_ARB",
        "reason": f"DUAL ARB: ${total_cost:.3f} ({profit_pct:.1%})",
    }


def volume_surge(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """REQUIRES REAL VOLUME DATA."""
    if snap.volume_24h <= 0 or abs(snap.price_change_24h) >= 0.05:
        return None
    if snap.volatility < 0.04:
        return None

    side = "YES" if snap.price_change_24h >= 0 else "NO"
    price = snap.price if side == "YES" else (1.0 - snap.price)
    return {
        "action": "BUY", "side": side, "price": price,
        "confidence": 0.60, "strategy": "VOLUME_SURGE",
        "reason": f"Volume surge, vol={snap.volatility:.3f}",
    }


def binance_arb(
    market: MarketHistory, snap: MarketSnapshot, timestamp: datetime,
) -> Optional[dict]:
    """REQUIRES REAL BINANCE + POLYMARKET CROSS-EXCHANGE DATA."""
    q = market.question.lower()
    is_crypto = any(kw in q for kw in ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto"])
    if not is_crypto:
        return None

    price_7d = market.get_price_change(timestamp, lookback_hours=168)
    if price_7d is None:
        return None

    edge = price_7d - snap.price_change_24h
    if abs(edge) < PROD_CONFIG["binance_min_edge"]:
        return None

    side = "YES" if edge > 0 else "NO"
    entry_price = snap.price if side == "YES" else (1.0 - snap.price)
    return {
        "action": "BUY", "side": side, "price": entry_price,
        "confidence": min(0.95, 0.70 + abs(edge)),
        "strategy": "BINANCE_ARB",
        "reason": f"BINANCE_ARB: Edge {edge*100:+.1f}%",
    }


# ============================================================
# STRATEGY REGISTRIES
# ============================================================

# Strategies that work on price-only data (Kaggle)
PRICE_ONLY_STRATEGIES = {
    "NEAR_CERTAIN": near_certain,
    "NEAR_ZERO": near_zero,
    "DIP_BUY": dip_buy,
    "MID_RANGE": mid_range,
    "MEAN_REVERSION": mean_reversion,
}

# Strategies that REQUIRE real bid/ask/volume data
SPREAD_STRATEGIES = {
    "MARKET_MAKER": market_maker,
    "DUAL_SIDE_ARB": dual_side_arb,
    "VOLUME_SURGE": volume_surge,
    "BINANCE_ARB": binance_arb,
}

# All strategies combined
PRODUCTION_STRATEGIES = {**PRICE_ONLY_STRATEGIES, **SPREAD_STRATEGIES}

# Broken versions for A/B testing
BROKEN_STRATEGIES = {
    "MEAN_REVERSION": mean_reversion_broken,
    "MARKET_MAKER": market_maker_broken,
}
