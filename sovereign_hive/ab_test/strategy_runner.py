#!/usr/bin/env python3
"""
ISOLATED STRATEGY RUNNER
=========================
Runs a single strategy in isolation for A/B testing.

Usage:
    python strategy_runner.py --strategy MARKET_MAKER
    python strategy_runner.py --strategy BINANCE_ARB
    python strategy_runner.py --strategy NEAR_ZERO

Each strategy gets its own portfolio file and runs independently.
"""

import asyncio
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from run_simulation import (
    Portfolio, MarketScanner, TradingEngine, CONFIG,
    NewsAnalyzer
)

# Valid strategies for A/B testing
VALID_STRATEGIES: Set[str] = {
    "MARKET_MAKER",
    "BINANCE_ARB",
    "NEAR_ZERO",
    "NEAR_CERTAIN",
    "DUAL_SIDE_ARB",
    "MID_RANGE",
    "DIP_BUY",
    "VOLUME_SURGE",
}


class IsolatedStrategyRunner:
    """
    Runs a single strategy in isolation for proper A/B testing.

    Each strategy gets:
    - Its own $1000 starting balance
    - Its own portfolio file
    - Only trades using that one strategy
    """

    def __init__(self, strategy: str, initial_balance: float = 1000.0):
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"Invalid strategy: {strategy}. Must be one of {VALID_STRATEGIES}")

        self.strategy = strategy
        self.initial_balance = initial_balance

        # Each strategy gets its own portfolio file
        data_dir = Path(__file__).parent.parent / "data" / "ab_test"
        data_dir.mkdir(parents=True, exist_ok=True)

        self.portfolio_file = f"portfolio_{strategy.lower()}.json"
        self.log_file = data_dir / f"log_{strategy.lower()}.txt"

        # Initialize components
        self.portfolio = Portfolio(
            initial_balance=initial_balance,
            data_file=str(data_dir / self.portfolio_file)
        )
        self.scanner = MarketScanner()
        self.news = NewsAnalyzer()
        self.running = False

    def filter_opportunities(self, opportunities: List[dict]) -> List[dict]:
        """Filter opportunities to only include our target strategy."""
        return [opp for opp in opportunities if opp.get("strategy") == self.strategy]

    async def check_exits(self):
        """Check all positions for exit conditions."""
        for condition_id, position in list(self.portfolio.positions.items()):
            # Handle different position types
            side = position.get("side", "YES")

            # DUAL_SIDE_ARB: Wait for resolution
            if side == "BOTH":
                continue

            # MARKET_MAKER: Check MM-specific exits
            if side == "MM":
                await self._check_mm_exit(condition_id, position)
                continue

            # Standard positions: Check TP/SL
            yes_price = await self.scanner.get_market_price(condition_id)
            if yes_price is None:
                continue

            current_price = (1.0 - yes_price) if side == "NO" else yes_price
            pnl_pct = self.portfolio.get_position_pnl(condition_id, current_price)

            if pnl_pct is None:
                continue

            # Take profit
            if pnl_pct >= CONFIG["take_profit_pct"]:
                result = self.portfolio.sell(condition_id, current_price, "TAKE_PROFIT")
                if result["success"]:
                    self._log(f"TAKE_PROFIT: +${result['trade']['pnl']:.2f}")

            # Stop loss
            elif pnl_pct <= CONFIG["stop_loss_pct"]:
                result = self.portfolio.sell(condition_id, current_price, "STOP_LOSS")
                if result["success"]:
                    self._log(f"STOP_LOSS: ${result['trade']['pnl']:.2f}")

    async def _check_mm_exit(self, condition_id: str, position: dict):
        """Check MM position exit conditions."""
        mm_ask = position.get("mm_ask", position["entry_price"] * 1.01)
        entry_time_str = position.get("mm_entry_time", position.get("entry_time", ""))

        yes_price = await self.scanner.get_market_price(condition_id)
        if yes_price is None:
            return

        current_price = yes_price

        # Calculate hold time
        try:
            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
            hold_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
        except:
            hold_hours = 0

        # Exit conditions
        if current_price >= mm_ask:
            result = self.portfolio.sell(condition_id, mm_ask, "MM_FILLED")
            if result["success"]:
                self._log(f"MM_FILLED: +${result['trade']['pnl']:.2f} in {hold_hours:.1f}h")
            return

        mm_stop_loss = -0.03
        pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]
        if pnl_pct <= mm_stop_loss:
            result = self.portfolio.sell(condition_id, current_price, "MM_STOP")
            if result["success"]:
                self._log(f"MM_STOP: ${result['trade']['pnl']:.2f}")
            return

        if hold_hours >= CONFIG["mm_max_hold_hours"]:
            result = self.portfolio.sell(condition_id, current_price, "MM_TIMEOUT")
            if result["success"]:
                self._log(f"MM_TIMEOUT: ${result['trade']['pnl']:.2f}")

    async def execute_trade(self, opp: dict):
        """Execute a trade for the strategy."""
        max_amount = self.portfolio.balance * CONFIG["max_position_pct"]
        liquidity = opp.get("liquidity", 10000)
        max_liquidity_amount = liquidity * 0.01
        amount = min(max_amount, max_liquidity_amount, 150)  # $150 max per trade

        if amount < 10:
            return

        # Skip if already in this position
        if opp["condition_id"] in self.portfolio.positions:
            return

        # Skip if at max positions
        if len(self.portfolio.positions) >= 8:  # 8 max for focused testing
            return

        # Execute based on strategy type
        if self.strategy == "MARKET_MAKER":
            await self._execute_mm(opp, amount)
        elif self.strategy == "DUAL_SIDE_ARB":
            await self._execute_dual_side(opp, amount)
        else:
            await self._execute_standard(opp, amount)

    async def _execute_standard(self, opp: dict, amount: float):
        """Execute standard buy order."""
        result = self.portfolio.buy(
            condition_id=opp["condition_id"],
            question=opp["question"],
            side=opp["side"],
            price=opp["price"],
            amount=amount,
            reason=opp["reason"],
            strategy=self.strategy
        )
        if result["success"]:
            self._log(f"BUY {opp['side']} @ ${opp['price']:.3f} | ${amount:.2f}")

    async def _execute_mm(self, opp: dict, amount: float):
        """Execute market maker position."""
        mid_price = opp.get("price", 0)
        mm_bid = opp.get("mm_bid", mid_price - max(mid_price * 0.005, 0.005))
        mm_ask = opp.get("mm_ask", mid_price + max(mid_price * 0.005, 0.005))

        result = self.portfolio.buy(
            condition_id=opp["condition_id"],
            question=opp["question"],
            side="MM",
            price=mm_bid,
            amount=amount,
            reason=opp["reason"],
            strategy="MARKET_MAKER"
        )

        if result["success"]:
            pos = self.portfolio.positions[opp["condition_id"]]
            pos["mm_bid"] = mm_bid
            pos["mm_ask"] = mm_ask
            pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
            self.portfolio._save()
            self._log(f"MM OPEN @ ${mm_bid:.3f} → ${mm_ask:.3f} | ${amount:.2f}")

    async def _execute_dual_side(self, opp: dict, amount: float):
        """Execute dual-side arbitrage."""
        yes_price = opp.get("yes_price", 0)
        no_price = opp.get("no_price", 0)

        if yes_price + no_price >= 1.0:
            return

        half_amount = amount / 2

        result = self.portfolio.buy(
            condition_id=opp["condition_id"],
            question=opp["question"],
            side="BOTH",
            price=(yes_price + no_price) / 2,
            amount=amount,
            reason=opp["reason"],
            strategy="DUAL_SIDE_ARB"
        )

        if result["success"]:
            profit = 1.0 - (yes_price + no_price)
            self._log(f"DUAL_SIDE: YES@${yes_price:.3f} + NO@${no_price:.3f} | Profit: {profit:.1%}")

    def _log(self, message: str):
        """Log message with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{self.strategy}] {message}"
        print(log_line)

        with open(self.log_file, "a") as f:
            f.write(log_line + "\n")

    async def run_cycle(self):
        """Run one trading cycle."""
        self._log(f"Cycle start | Balance: ${self.portfolio.balance:.2f} | Positions: {len(self.portfolio.positions)}")

        # Check exits
        if self.portfolio.positions:
            await self.check_exits()

        # Scan for opportunities
        markets = await self.scanner.get_active_markets()

        # Get Binance prices for BINANCE_ARB
        binance_prices = {}
        if self.strategy == "BINANCE_ARB":
            binance_prices = await self.scanner.get_binance_prices()

        opportunities = self.scanner.find_opportunities(markets, binance_prices)

        # Filter to our strategy only
        strategy_opps = self.filter_opportunities(opportunities)

        self._log(f"Found {len(strategy_opps)} {self.strategy} opportunities")

        # Execute trades
        for opp in strategy_opps[:3]:  # Max 3 trades per cycle
            await self.execute_trade(opp)
            await asyncio.sleep(0.5)

        # Log summary
        summary = self.portfolio.get_summary()
        self._log(f"Cycle end | P&L: ${summary['total_pnl']:+.2f} | Win: {summary['win_rate']:.0f}%")

    async def run(self, interval: int = 60):
        """Main run loop."""
        self._log(f"Starting isolated {self.strategy} runner")
        self._log(f"Initial balance: ${self.initial_balance:.2f}")
        self._log(f"Portfolio file: {self.portfolio_file}")

        self.running = True

        while self.running:
            try:
                await self.run_cycle()
            except Exception as e:
                self._log(f"Error: {e}")

            await asyncio.sleep(interval)

    def stop(self):
        """Stop the runner."""
        self.running = False

    def get_performance(self) -> dict:
        """Get current performance metrics."""
        summary = self.portfolio.get_summary()
        strategy_metrics = self.portfolio.strategy_metrics.get(self.strategy, {})

        return {
            "strategy": self.strategy,
            "balance": self.portfolio.balance,
            "initial_balance": self.initial_balance,
            "total_pnl": summary["total_pnl"],
            "roi_pct": summary["roi_pct"],
            "open_positions": summary["open_positions"],
            "total_trades": strategy_metrics.get("trades", 0),
            "wins": strategy_metrics.get("wins", 0),
            "win_rate": summary["win_rate"],
            "strategy_pnl": strategy_metrics.get("pnl", 0),
        }


def main():
    parser = argparse.ArgumentParser(description="Run isolated strategy for A/B testing")
    parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        choices=list(VALID_STRATEGIES),
        help="Strategy to run"
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=1000.0,
        help="Initial balance (default: $1000)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Scan interval in seconds (default: 60)"
    )

    args = parser.parse_args()

    runner = IsolatedStrategyRunner(
        strategy=args.strategy,
        initial_balance=args.balance
    )

    try:
        asyncio.run(runner.run(interval=args.interval))
    except KeyboardInterrupt:
        runner.stop()
        print(f"\nStopped. Final performance:")
        print(json.dumps(runner.get_performance(), indent=2))


if __name__ == "__main__":
    main()
