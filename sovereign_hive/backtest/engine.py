#!/usr/bin/env python3
"""
BACKTEST ENGINE
================
Core engine for replaying historical data through trading strategies.

Features:
- Time-series simulation with realistic execution
- Multiple strategy support with production-matching logic
- Position tracking and P&L calculation
- MM-specific exit model (fill probability, timeout, slippage)
- MEAN_REVERSION cooldown tracking
- Kelly Criterion integration
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Callable
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from .data_loader import DataLoader, MarketHistory, PricePoint, MarketSnapshot
from .metrics import PerformanceMetrics, Trade, EquityPoint

# Import Kelly if available
try:
    from core.kelly_criterion import KellyCriterion
except ImportError:
    KellyCriterion = None


@dataclass
class Position:
    """Open position in a market."""
    condition_id: str
    question: str
    strategy: str
    side: str
    entry_time: datetime
    entry_price: float
    shares: float
    cost_basis: float
    # MM-specific fields
    mm_bid: float = 0.0
    mm_ask: float = 0.0


@dataclass
class StrategyOverrides:
    """Per-strategy exit parameters."""
    take_profit_pct: float = 0.10
    stop_loss_pct: float = -0.05
    max_hold_hours: float = 0  # 0 = no timeout
    fill_probability: float = 1.0  # 1.0 = always fills
    exit_slippage_pct: float = 0.0
    use_kelly: bool = True
    fixed_position_pct: float = 0.0  # >0 = override Kelly with fixed %


# Production-matching overrides for each strategy
DEFAULT_STRATEGY_OVERRIDES = {
    "NEAR_CERTAIN": StrategyOverrides(
        take_profit_pct=0.10, stop_loss_pct=-0.05,
    ),
    "NEAR_ZERO": StrategyOverrides(
        take_profit_pct=0.10, stop_loss_pct=-0.05,
    ),
    "DIP_BUY": StrategyOverrides(
        take_profit_pct=0.10, stop_loss_pct=-0.05,
    ),
    "VOLUME_SURGE": StrategyOverrides(
        take_profit_pct=0.10, stop_loss_pct=-0.05,
    ),
    "MID_RANGE": StrategyOverrides(
        take_profit_pct=0.10, stop_loss_pct=-0.05,
        use_kelly=False, fixed_position_pct=0.10,
    ),
    "MEAN_REVERSION": StrategyOverrides(
        take_profit_pct=0.10, stop_loss_pct=-0.05,
        use_kelly=False, fixed_position_pct=0.10,
    ),
    "DUAL_SIDE_ARB": StrategyOverrides(
        take_profit_pct=1.0, stop_loss_pct=-0.50,  # Hold until resolution
        use_kelly=False, fixed_position_pct=0.10,
    ),
    "MARKET_MAKER": StrategyOverrides(
        take_profit_pct=0.05, stop_loss_pct=-0.03,
        max_hold_hours=4.0,
        fill_probability=0.60,
        exit_slippage_pct=0.002,
        use_kelly=False, fixed_position_pct=0.10,
    ),
    "BINANCE_ARB": StrategyOverrides(
        take_profit_pct=0.10, stop_loss_pct=-0.05,
    ),
}


@dataclass
class BacktestConfig:
    """Configuration for backtest run."""
    initial_capital: float = 1000.0
    max_position_pct: float = 0.15  # Max 15% per position (matches production)
    max_positions: int = 8
    take_profit_pct: float = 0.10  # 10% take profit (matches production)
    stop_loss_pct: float = -0.05   # 5% stop loss (matches production)
    use_kelly: bool = True
    kelly_fraction: float = 0.15   # Matches production
    commission_pct: float = 0.001  # 0.1% commission
    min_position_usd: float = 50.0  # $50 minimum (matches production)
    max_position_usd: float = 100.0  # $100 cap (matches production)
    slippage_pct: float = 0.002    # 0.2% slippage
    strategy_overrides: Dict[str, StrategyOverrides] = field(default_factory=dict)

    def get_overrides(self, strategy: str) -> StrategyOverrides:
        if strategy in self.strategy_overrides:
            return self.strategy_overrides[strategy]
        return DEFAULT_STRATEGY_OVERRIDES.get(strategy, StrategyOverrides())


class BacktestEngine:
    """
    Backtest engine for testing trading strategies.

    Supports two strategy interfaces:
    1. Legacy: strategy(market, price, timestamp) -> signal
    2. Production: strategy(market, snapshot, timestamp) -> signal

    Usage:
        engine = BacktestEngine(data_loader, config)
        engine.add_strategy("NEAR_CERTAIN", near_certain)
        results = engine.run()
    """

    def __init__(
        self,
        data_loader: DataLoader,
        config: Optional[BacktestConfig] = None
    ):
        self.data = data_loader
        self.config = config or BacktestConfig()

        # Strategy callbacks
        self.strategies: Dict[str, Callable] = {}
        self._use_snapshots: Dict[str, bool] = {}

        # State during backtest
        self.cash: float = 0.0
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[EquityPoint] = []
        self.current_time: datetime = datetime.now(timezone.utc)

        # Kelly calculator
        self.kelly = KellyCriterion(
            kelly_fraction=self.config.kelly_fraction,
            max_position_pct=self.config.max_position_pct
        ) if KellyCriterion and self.config.use_kelly else None

    def add_strategy(self, name: str, strategy_func: Callable, use_snapshots: bool = False):
        """
        Add a strategy to the backtest.

        If use_snapshots=True, strategy receives (market, snapshot, timestamp).
        Otherwise legacy interface: (market, price, timestamp).
        """
        self.strategies[name] = strategy_func
        self._use_snapshots[name] = use_snapshots

    def run(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        step_hours: int = 1,
        verbose: bool = True,
    ) -> Dict[str, PerformanceMetrics]:
        """Run backtest for all strategies. Returns metrics per strategy."""
        data_start, data_end = self.data.get_time_range()
        if data_start is None:
            raise ValueError("No data loaded")

        start_time = start_time or data_start
        end_time = end_time or data_end

        results = {}
        for strategy_name in self.strategies:
            if verbose:
                print(f"\nRunning backtest: {strategy_name}")
            metrics = self._run_single_strategy(
                strategy_name, start_time, end_time, step_hours, verbose
            )
            results[strategy_name] = metrics
            if verbose:
                print(f"  Completed: {metrics.total_trades} trades, "
                      f"{metrics.total_return_pct:+.2f}% return")

        return results

    def _run_single_strategy(
        self,
        strategy_name: str,
        start_time: datetime,
        end_time: datetime,
        step_hours: int,
        verbose: bool = True,
    ) -> PerformanceMetrics:
        """Run backtest for a single strategy."""
        # Reset state
        self.cash = self.config.initial_capital
        self.positions = {}
        self.trades = []
        self.equity_curve = []

        # Reset strategy state (cooldowns, etc.)
        try:
            from .strategies import reset_state
            reset_state()
        except ImportError:
            pass

        strategy_func = self.strategies[strategy_name]
        use_snap = self._use_snapshots.get(strategy_name, False)
        step = timedelta(hours=step_hours)
        current = start_time

        while current <= end_time:
            self.current_time = current

            # 1. Check exits for open positions
            self._check_exits(current, strategy_name)

            # 2. Look for new opportunities
            if len(self.positions) < self.config.max_positions:
                active_markets = self.data.get_markets_active_at(current)

                for market in active_markets:
                    if market.condition_id in self.positions:
                        continue

                    if len(self.positions) >= self.config.max_positions:
                        break

                    signal = None
                    if use_snap:
                        snap = self.data.get_snapshot(market, current)
                        if snap is None:
                            continue
                        signal = strategy_func(market, snap, current)
                    else:
                        price = market.get_price_at(current)
                        if price is None:
                            continue
                        signal = strategy_func(market, price, current)

                    if signal and signal.get("action") == "BUY":
                        self._execute_entry(
                            market=market,
                            signal=signal,
                            strategy=strategy_name,
                        )

            # 3. Record equity
            equity = self._calculate_equity(current)
            self.equity_curve.append(EquityPoint(
                timestamp=current,
                equity=equity,
                cash=self.cash,
                positions_value=equity - self.cash
            ))

            current += step

        # Close remaining positions at final prices
        self._close_all_positions(end_time, strategy_name)

        metrics = PerformanceMetrics(
            initial_capital=self.config.initial_capital,
            final_capital=self.cash,
            trades=self.trades.copy(),
            equity_curve=self.equity_curve.copy(),
            strategy_name=strategy_name,
            start_time=start_time,
            end_time=end_time
        )
        metrics.calculate()
        return metrics

    def _execute_entry(
        self,
        market: MarketHistory,
        signal: dict,
        strategy: str,
    ):
        """Execute a buy order from a strategy signal."""
        side = signal.get("side", "YES")
        confidence = signal.get("confidence", 0.5)
        price_from_signal = signal.get("price")

        # Get YES price from market
        yes_price = market.get_price_at(self.current_time)
        if yes_price is None:
            return

        # Determine entry price
        if side == "MM":
            side_price = price_from_signal or yes_price
        elif side == "BOTH":
            side_price = price_from_signal or yes_price  # Total cost
        elif price_from_signal and 0 < price_from_signal < 1:
            side_price = price_from_signal
        else:
            side_price = yes_price if side == "YES" else (1 - yes_price)

        if side_price <= 0.001 or side_price >= 0.999:
            return

        # Apply slippage on entry
        side_price *= (1 + self.config.slippage_pct)
        side_price = min(0.999, side_price)

        # Position sizing
        overrides = self.config.get_overrides(strategy)
        if overrides.fixed_position_pct > 0:
            amount = self.config.initial_capital * overrides.fixed_position_pct
        elif self.kelly and overrides.use_kelly and self.config.use_kelly:
            estimated_prob = self._estimate_probability(yes_price, confidence, side, strategy)
            kelly_result = self.kelly.calculate(
                estimated_prob=estimated_prob,
                market_price=side_price,
                bankroll=self.cash,
                confidence=confidence,
                side=side if side not in ("MM", "BOTH") else "YES"
            )
            if kelly_result:
                amount = kelly_result.position_size
            else:
                amount = self.config.initial_capital * self.config.max_position_pct * 0.5
        else:
            amount = self.config.initial_capital * self.config.max_position_pct

        # Cap amount
        amount = min(amount, self.config.max_position_usd, self.cash * 0.95)

        # Minimum position check
        if amount < self.config.min_position_usd:
            return

        # Commission
        amount_after_commission = amount * (1 - self.config.commission_pct)
        if amount_after_commission < 1:
            return

        shares = amount_after_commission / side_price

        # Create position
        position = Position(
            condition_id=market.condition_id,
            question=market.question[:60],
            strategy=strategy,
            side=side,
            entry_time=self.current_time,
            entry_price=side_price,
            shares=shares,
            cost_basis=amount,
            mm_bid=signal.get("mm_bid", 0.0),
            mm_ask=signal.get("mm_ask", 0.0),
        )

        self.positions[market.condition_id] = position
        self.cash -= amount

        trade = Trade(
            condition_id=market.condition_id,
            question=market.question[:60],
            strategy=strategy,
            side=side,
            entry_time=self.current_time,
            entry_price=side_price,
            shares=shares,
            cost_basis=amount,
            is_open=True
        )
        self.trades.append(trade)

    def _estimate_probability(
        self, price: float, confidence: float, side: str, strategy: str
    ) -> float:
        if strategy == "NEAR_CERTAIN":
            return min(0.99, price + (1 - price) * confidence * 0.5)
        elif strategy == "NEAR_ZERO":
            return max(0.01, price - price * confidence * 0.5)
        elif strategy == "BINANCE_ARB":
            return 0.95 if side == "YES" else 0.05
        else:
            if side == "YES":
                return min(0.95, price + confidence * 0.1)
            else:
                return max(0.05, price - confidence * 0.1)

    def _check_exits(self, current_time: datetime, strategy_name: str):
        """Check and execute exits for open positions with strategy-specific logic."""
        to_close = []

        for cid, pos in self.positions.items():
            market = self.data.get_market(cid)
            if not market:
                continue

            yes_price = market.get_price_at(current_time)
            if yes_price is None:
                continue

            overrides = self.config.get_overrides(pos.strategy)
            hold_hours = (current_time - pos.entry_time).total_seconds() / 3600

            # Check market resolution
            if market.resolution and market.resolution_time and current_time >= market.resolution_time:
                yes_final = market.get_final_price()
                if pos.side == "BOTH":
                    side_final = 1.0  # One side always pays $1
                elif pos.side == "MM":
                    side_final = yes_final
                else:
                    side_final = yes_final if pos.side == "YES" else (1 - yes_final)
                to_close.append((cid, side_final, "RESOLUTION"))
                continue

            # Current price based on position side
            if pos.side == "MM":
                current_side_price = yes_price
            elif pos.side == "BOTH":
                # DUAL_SIDE_ARB waits for resolution, but with a max hold timeout
                # to prevent capital being locked indefinitely
                if hold_hours >= 30 * 24:  # 30-day max hold
                    to_close.append((cid, pos.entry_price, "TIMEOUT"))
                continue  # Otherwise wait for resolution
            else:
                current_side_price = yes_price if pos.side == "YES" else (1 - yes_price)

            # MM-specific exit logic
            if pos.side == "MM":
                exit_info = self._check_mm_exit(pos, yes_price, hold_hours, overrides)
                if exit_info:
                    to_close.append((cid, exit_info[0], exit_info[1]))
                continue

            # Standard TP/SL
            current_value = pos.shares * current_side_price
            pnl_pct = (current_value - pos.cost_basis) / pos.cost_basis if pos.cost_basis > 0 else 0

            if pnl_pct >= overrides.take_profit_pct:
                to_close.append((cid, current_side_price, "TAKE_PROFIT"))
                continue
            if pnl_pct <= overrides.stop_loss_pct:
                to_close.append((cid, current_side_price, "STOP_LOSS"))
                continue

            # General timeout
            if overrides.max_hold_hours > 0 and hold_hours >= overrides.max_hold_hours:
                to_close.append((cid, current_side_price, "TIMEOUT"))
                continue

        for cid, price, reason in to_close:
            self._execute_exit(cid, price, reason, strategy_name)

    def _check_mm_exit(
        self,
        pos: Position,
        current_price: float,
        hold_hours: float,
        overrides: StrategyOverrides,
    ) -> Optional[tuple]:
        """
        MM-specific exit logic matching production _check_mm_exit:
        1. Price reaches ask → fill with 60% probability + slippage
        2. Price drops >3% → stop loss
        3. Hold > 4h → timeout at bid (forced seller)
        """
        mm_ask = pos.mm_ask if pos.mm_ask > 0 else pos.entry_price * 1.01

        # 1. Fill at ask
        if current_price >= mm_ask:
            if random.random() < overrides.fill_probability:
                exit_price = mm_ask * (1 - overrides.exit_slippage_pct)
                return (exit_price, "MM_FILLED")
            return None  # Didn't fill, retry next cycle

        # 2. Stop loss at -3%
        pnl_pct = (current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0
        if pnl_pct <= overrides.stop_loss_pct:
            return (current_price, "MM_STOP")

        # 3. Timeout: exit at BID (forced seller gets worse price)
        if hold_hours >= overrides.max_hold_hours and overrides.max_hold_hours > 0:
            # Exit at bid = current price - half spread (forced seller penalty)
            timeout_price = current_price * (1 - 0.01)  # ~1% penalty for forced exit
            return (timeout_price, "MM_TIMEOUT")

        return None

    def _execute_exit(self, condition_id: str, price: float, reason: str, strategy_name: str = ""):
        """Execute a sell order."""
        if condition_id not in self.positions:
            return

        pos = self.positions[condition_id]
        proceeds = pos.shares * price * (1 - self.config.commission_pct)

        self.cash += proceeds
        del self.positions[condition_id]

        # Record MEAN_REVERSION exit for cooldown tracking (all exit reasons)
        if pos.strategy == "MEAN_REVERSION":
            try:
                from .strategies import get_state
                get_state().record_mr_exit(condition_id, self.current_time)
            except ImportError:
                pass

        # Clear MM entry state
        if pos.strategy == "MARKET_MAKER":
            try:
                from .strategies import get_state
                get_state().clear_mm_entry(condition_id)
            except ImportError:
                pass

        # Update trade record
        for trade in self.trades:
            if trade.condition_id == condition_id and trade.is_open:
                trade.close(self.current_time, price, reason)
                break

    def _close_all_positions(self, end_time: datetime, strategy_name: str = ""):
        """Close all positions at final prices."""
        self.current_time = end_time

        for cid in list(self.positions.keys()):
            pos = self.positions[cid]
            market = self.data.get_market(cid)
            if market:
                yes_final = market.get_final_price()
                if pos.side == "BOTH":
                    side_final = 1.0
                elif pos.side == "MM":
                    side_final = yes_final
                else:
                    side_final = yes_final if pos.side == "YES" else (1 - yes_final)
                self._execute_exit(cid, side_final, "END_OF_BACKTEST", strategy_name)

    def _calculate_equity(self, timestamp: datetime) -> float:
        """Calculate total equity (cash + positions value)."""
        equity = self.cash

        for cid, pos in self.positions.items():
            market = self.data.get_market(cid)
            if market:
                yes_price = market.get_price_at(timestamp)
                if yes_price is not None:
                    if pos.side == "BOTH":
                        equity += pos.cost_basis  # Held at cost (profit locked)
                    elif pos.side == "MM":
                        equity += pos.shares * yes_price
                    else:
                        side_price = yes_price if pos.side == "YES" else (1 - yes_price)
                        equity += pos.shares * side_price
                else:
                    equity += pos.cost_basis
        return equity


# ============================================================
# BUILT-IN STRATEGIES (legacy, kept for backward compatibility)
# ============================================================

def near_certain_strategy(market: MarketHistory, price: float, timestamp: datetime) -> Optional[dict]:
    if price >= 0.90:
        return {"action": "BUY", "side": "YES", "confidence": min(price, 0.95),
                "reason": f"Near certain YES at {price:.2f}"}
    return None

def near_zero_strategy(market: MarketHistory, price: float, timestamp: datetime) -> Optional[dict]:
    if price <= 0.10:
        return {"action": "BUY", "side": "NO", "confidence": min(1 - price, 0.95),
                "reason": f"Near zero YES at {price:.2f}"}
    return None

def mean_reversion_strategy(market: MarketHistory, price: float, timestamp: datetime) -> Optional[dict]:
    if price < 0.30:
        return {"action": "BUY", "side": "YES", "confidence": 0.6,
                "reason": f"Mean reversion: price {price:.2f} below 0.30"}
    elif price > 0.70:
        return {"action": "BUY", "side": "NO", "confidence": 0.6,
                "reason": f"Mean reversion: price {price:.2f} above 0.70"}
    return None

def momentum_strategy(market: MarketHistory, price: float, timestamp: datetime) -> Optional[dict]:
    lookback_time = timestamp - timedelta(hours=24)
    prev_price = market.get_price_at(lookback_time)
    if prev_price is None:
        return None
    price_change = price - prev_price
    if price_change > 0.05 and price < 0.85:
        return {"action": "BUY", "side": "YES", "confidence": min(0.5 + abs(price_change), 0.8),
                "reason": f"Momentum: +{price_change:.2f} over 24h"}
    elif price_change < -0.05 and price > 0.15:
        return {"action": "BUY", "side": "NO", "confidence": min(0.5 + abs(price_change), 0.8),
                "reason": f"Momentum: {price_change:.2f} over 24h"}
    return None

def dip_buy_strategy(market: MarketHistory, price: float, timestamp: datetime) -> Optional[dict]:
    lookback_time = timestamp - timedelta(hours=24)
    prev_price = market.get_price_at(lookback_time)
    if prev_price is None or prev_price <= 0:
        return None
    price_change = (price - prev_price) / prev_price
    if price_change < -0.05 and price > 0.10 and price < 0.90:
        return {"action": "BUY", "side": "YES", "confidence": min(0.65 + abs(price_change), 0.85),
                "reason": f"Dip buy: {price_change:.1%} drop"}
    return None

def mid_range_strategy(market: MarketHistory, price: float, timestamp: datetime) -> Optional[dict]:
    if price < 0.20 or price > 0.80:
        return None
    lookback_time = timestamp - timedelta(hours=6)
    prev_price = market.get_price_at(lookback_time)
    if prev_price is None:
        return None
    price_change = price - prev_price
    if price_change > 0.01:
        return {"action": "BUY", "side": "YES", "confidence": 0.60,
                "reason": f"Mid-range up: {price_change:+.2%}"}
    elif price_change < -0.01:
        return {"action": "BUY", "side": "NO", "confidence": 0.60,
                "reason": f"Mid-range down: {price_change:+.2%}"}
    return None

def volume_surge_strategy(market: MarketHistory, price: float, timestamp: datetime) -> Optional[dict]:
    lookback_time = timestamp - timedelta(hours=6)
    prev_price = market.get_price_at(lookback_time)
    if prev_price is None:
        return None
    price_change = abs(price - prev_price)
    if 0.02 < price_change < 0.08 and 0.25 < price < 0.75:
        direction = "YES" if price > prev_price else "NO"
        return {"action": "BUY", "side": direction, "confidence": 0.60,
                "reason": f"Accumulation pattern: {price_change:.2%} move"}
    return None


BUILTIN_STRATEGIES = {
    "NEAR_CERTAIN": near_certain_strategy,
    "NEAR_ZERO": near_zero_strategy,
    "MEAN_REVERSION": mean_reversion_strategy,
    "MOMENTUM": momentum_strategy,
    "DIP_BUY": dip_buy_strategy,
    "MID_RANGE": mid_range_strategy,
    "VOLUME_SURGE": volume_surge_strategy,
}
