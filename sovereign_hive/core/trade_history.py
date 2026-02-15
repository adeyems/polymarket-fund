#!/usr/bin/env python3
"""
TRADE HISTORY - Audit Trail & Performance Metrics
==================================================
Logs every closed trade. Calculates win rate, P&L, Sharpe ratio.
You can't improve what you don't measure.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional
import math


# Default history file
DEFAULT_HISTORY_FILE = Path(__file__).parent.parent / "trade_history.json"


class TradeHistory:
    """
    Complete audit trail of all closed trades with performance analytics.
    """

    def __init__(self, history_file: Path = None):
        self._history_file = history_file or DEFAULT_HISTORY_FILE
        self._trades: List[dict] = []
        self._load()

    def _load(self):
        """Load trade history from disk."""
        if self._history_file.exists():
            try:
                with open(self._history_file) as f:
                    data = json.load(f)
                self._trades = data.get("trades", [])
                print(f"[HISTORY] Loaded {len(self._trades)} historical trades")
            except Exception as e:
                print(f"[HISTORY] Load error: {e}")
                self._trades = []

    def _save(self):
        """Save trade history to disk."""
        try:
            data = {
                "trades": self._trades,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "summary": self.get_summary()
            }
            with open(self._history_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[HISTORY] Save error: {e}")

    def log_trade(self, trade: dict):
        """
        Log a closed trade to history.

        Required fields:
        - condition_id: Market identifier
        - question: Market question
        - entry_price: Buy price
        - exit_price: Sell price
        - size: Number of shares
        - pnl: Profit/loss in dollars
        - exit_reason: TAKE_PROFIT, STOP_LOSS, RESOLVED_WIN, RESOLVED_LOSE
        """
        record = {
            "id": len(self._trades) + 1,
            "condition_id": trade.get("condition_id", ""),
            "question": trade.get("question", "")[:80],
            "entry_price": trade.get("entry_price", 0),
            "exit_price": trade.get("exit_price", 0),
            "size": trade.get("size", 0),
            "notional": trade.get("notional", 0),
            "pnl": trade.get("pnl", 0),
            "pnl_pct": trade.get("pnl_pct", 0),
            "exit_reason": trade.get("exit_reason", "UNKNOWN"),
            "strategy": trade.get("strategy", trade.get("anomaly_type", "UNKNOWN")),
            "entry_time": trade.get("executed_at", ""),
            "exit_time": trade.get("closed_at", datetime.now(timezone.utc).isoformat()),
            "simulated": trade.get("simulated", trade.get("dry_run", False)),
        }

        self._trades.append(record)
        self._save()

        # Print confirmation
        emoji = "🟢" if record["pnl"] >= 0 else "🔴"
        print(f"[HISTORY] {emoji} Trade #{record['id']} logged: ${record['pnl']:+.2f} ({record['exit_reason']})")

        return record

    def get_trades(self, limit: int = None, simulated: bool = None) -> List[dict]:
        """Get trade history with optional filters."""
        trades = self._trades

        if simulated is not None:
            trades = [t for t in trades if t.get("simulated") == simulated]

        if limit:
            trades = trades[-limit:]

        return trades

    def get_summary(self) -> dict:
        """Calculate performance summary."""
        if not self._trades:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "max_drawdown": 0,
                "sharpe_ratio": 0,
            }

        pnls = [t["pnl"] for t in self._trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total_pnl = sum(pnls)
        avg_pnl = total_pnl / len(pnls) if pnls else 0

        # Max Drawdown calculation
        cumulative = 0
        peak = 0
        max_drawdown = 0
        for pnl in pnls:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            drawdown = peak - cumulative
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        # Sharpe Ratio (simplified - assumes risk-free rate = 0)
        if len(pnls) > 1:
            mean_return = avg_pnl
            std_return = math.sqrt(sum((p - mean_return) ** 2 for p in pnls) / len(pnls))
            sharpe = (mean_return / std_return) if std_return > 0 else 0
        else:
            sharpe = 0

        return {
            "total_trades": len(self._trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 2),
            "best_trade": round(max(pnls), 2) if pnls else 0,
            "worst_trade": round(min(pnls), 2) if pnls else 0,
            "max_drawdown": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 2),
        }

    def get_by_strategy(self) -> dict:
        """Get performance breakdown by strategy."""
        strategies = {}

        for trade in self._trades:
            strategy = trade.get("strategy", "UNKNOWN")
            if strategy not in strategies:
                strategies[strategy] = {"trades": 0, "wins": 0, "pnl": 0}

            strategies[strategy]["trades"] += 1
            strategies[strategy]["pnl"] += trade["pnl"]
            if trade["pnl"] > 0:
                strategies[strategy]["wins"] += 1

        # Calculate win rates
        for s in strategies:
            strategies[s]["win_rate"] = round(
                strategies[s]["wins"] / strategies[s]["trades"] * 100, 1
            ) if strategies[s]["trades"] > 0 else 0
            strategies[s]["pnl"] = round(strategies[s]["pnl"], 2)

        return strategies

    def get_by_exit_reason(self) -> dict:
        """Get performance breakdown by exit reason."""
        reasons = {}

        for trade in self._trades:
            reason = trade.get("exit_reason", "UNKNOWN")
            if reason not in reasons:
                reasons[reason] = {"count": 0, "pnl": 0}

            reasons[reason]["count"] += 1
            reasons[reason]["pnl"] += trade["pnl"]

        for r in reasons:
            reasons[r]["pnl"] = round(reasons[r]["pnl"], 2)

        return reasons

    def report(self):
        """Print comprehensive performance report."""
        summary = self.get_summary()
        by_strategy = self.get_by_strategy()
        by_exit = self.get_by_exit_reason()

        print()
        print("=" * 60)
        print("  TRADE HISTORY - PERFORMANCE REPORT")
        print("=" * 60)
        print()
        print("  SUMMARY")
        print("  " + "-" * 40)
        print(f"  Total Trades:    {summary['total_trades']}")
        print(f"  Wins / Losses:   {summary['wins']} / {summary['losses']}")
        print(f"  Win Rate:        {summary['win_rate']}%")
        print()
        print(f"  Total P&L:       ${summary['total_pnl']:+.2f}")
        print(f"  Average P&L:     ${summary['avg_pnl']:+.2f}")
        print(f"  Best Trade:      ${summary['best_trade']:+.2f}")
        print(f"  Worst Trade:     ${summary['worst_trade']:+.2f}")
        print()
        print(f"  Max Drawdown:    ${summary['max_drawdown']:.2f}")
        print(f"  Sharpe Ratio:    {summary['sharpe_ratio']:.2f}")

        if by_strategy:
            print()
            print("  BY STRATEGY")
            print("  " + "-" * 40)
            for strategy, data in by_strategy.items():
                print(f"  {strategy}:")
                print(f"    Trades: {data['trades']} | Win: {data['win_rate']}% | P&L: ${data['pnl']:+.2f}")

        if by_exit:
            print()
            print("  BY EXIT REASON")
            print("  " + "-" * 40)
            for reason, data in by_exit.items():
                print(f"  {reason}: {data['count']} trades | ${data['pnl']:+.2f}")

        # Recent trades
        recent = self.get_trades(limit=5)
        if recent:
            print()
            print("  RECENT TRADES")
            print("  " + "-" * 40)
            for t in reversed(recent):
                emoji = "🟢" if t["pnl"] >= 0 else "🔴"
                print(f"  {emoji} #{t['id']}: {t['question'][:30]}...")
                print(f"     ${t['entry_price']:.3f} → ${t['exit_price']:.3f} | P&L: ${t['pnl']:+.2f}")

        print()
        print("=" * 60)
        print()

    def clear(self, confirm: bool = False):
        """Clear all trade history (use with caution)."""
        if confirm:
            self._trades = []
            self._save()
            print("[HISTORY] Trade history cleared")
        else:
            print("[HISTORY] Call clear(confirm=True) to clear history")


# Singleton
_history = None


def get_history() -> TradeHistory:
    global _history
    if _history is None:
        _history = TradeHistory()
    return _history
