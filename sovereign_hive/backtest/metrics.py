#!/usr/bin/env python3
"""
PERFORMANCE METRICS
====================
Calculate trading performance metrics for backtesting.

Metrics include:
- Total return and ROI
- Sharpe ratio (risk-adjusted return)
- Maximum drawdown
- Win rate and profit factor
- Annualized returns
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timedelta


@dataclass
class Trade:
    """Record of a single trade."""
    condition_id: str
    question: str
    strategy: str
    side: str  # "YES" or "NO"
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    shares: float = 0.0
    cost_basis: float = 0.0
    proceeds: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    is_open: bool = True

    def close(self, exit_time: datetime, exit_price: float, reason: str):
        """Close the trade and calculate P&L."""
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_reason = reason
        self.is_open = False
        self.proceeds = self.shares * exit_price
        self.pnl = self.proceeds - self.cost_basis
        self.pnl_pct = (self.pnl / self.cost_basis * 100) if self.cost_basis > 0 else 0


@dataclass
class EquityPoint:
    """Point on the equity curve."""
    timestamp: datetime
    equity: float
    cash: float
    positions_value: float


@dataclass
class PerformanceMetrics:
    """
    Performance metrics for a backtest run.

    Calculates standard trading metrics:
    - Returns (total, annualized)
    - Risk metrics (Sharpe, Sortino, max drawdown)
    - Trade statistics (win rate, profit factor)
    """

    initial_capital: float
    final_capital: float
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[EquityPoint] = field(default_factory=list)
    strategy_name: str = "Unknown"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # Calculated metrics (populated by calculate())
    total_return: float = 0.0
    total_return_pct: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_trade: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_holding_period: float = 0.0  # In hours

    def calculate(self):
        """Calculate all performance metrics."""
        self._calculate_returns()
        self._calculate_trade_stats()
        self._calculate_risk_metrics()
        self._calculate_drawdown()

    def _calculate_returns(self):
        """Calculate return metrics."""
        self.total_return = self.final_capital - self.initial_capital
        self.total_return_pct = (self.total_return / self.initial_capital * 100) if self.initial_capital > 0 else 0

        # Annualized return
        if self.start_time and self.end_time:
            days = (self.end_time - self.start_time).days
            if days > 0 and self.initial_capital > 0:
                # Compound annual growth rate
                growth = self.final_capital / self.initial_capital
                if growth > 0:
                    try:
                        self.annualized_return = (math.pow(growth, 365 / days) - 1) * 100
                        # Cap extreme values
                        self.annualized_return = max(-999, min(9999, self.annualized_return))
                    except (OverflowError, ValueError):
                        # Handle extreme cases
                        self.annualized_return = -999 if growth < 1 else 9999
                else:
                    self.annualized_return = -999  # Total loss

    def _calculate_trade_stats(self):
        """Calculate trade statistics."""
        closed_trades = [t for t in self.trades if not t.is_open]
        self.total_trades = len(closed_trades)

        if self.total_trades == 0:
            return

        wins = [t for t in closed_trades if t.pnl > 0]
        losses = [t for t in closed_trades if t.pnl <= 0]

        self.winning_trades = len(wins)
        self.losing_trades = len(losses)
        self.win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0

        # Average trade metrics
        total_pnl = sum(t.pnl for t in closed_trades)
        self.avg_trade = total_pnl / self.total_trades

        if wins:
            self.avg_win = sum(t.pnl for t in wins) / len(wins)
        if losses:
            self.avg_loss = sum(t.pnl for t in losses) / len(losses)

        # Profit factor
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        self.profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

        # Average holding period
        holding_times = []
        for t in closed_trades:
            if t.entry_time and t.exit_time:
                hours = (t.exit_time - t.entry_time).total_seconds() / 3600
                holding_times.append(hours)
        if holding_times:
            self.avg_holding_period = sum(holding_times) / len(holding_times)

    def _calculate_risk_metrics(self):
        """Calculate Sharpe and Sortino ratios."""
        if len(self.equity_curve) < 2:
            return

        # Calculate daily returns
        returns = []
        for i in range(1, len(self.equity_curve)):
            prev = self.equity_curve[i - 1].equity
            curr = self.equity_curve[i].equity
            if prev > 0:
                returns.append((curr - prev) / prev)

        if not returns:
            return

        # Mean and std of returns
        mean_return = sum(returns) / len(returns)

        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance) if variance > 0 else 0

        # Sharpe ratio (assuming risk-free rate of 0)
        # Annualized: multiply by sqrt(252) for daily returns
        if std_return > 0:
            self.sharpe_ratio = (mean_return / std_return) * math.sqrt(252)

        # Sortino ratio (only downside deviation)
        downside_returns = [r for r in returns if r < 0]
        if downside_returns:
            downside_variance = sum(r ** 2 for r in downside_returns) / len(returns)
            downside_std = math.sqrt(downside_variance)
            if downside_std > 0:
                self.sortino_ratio = (mean_return / downside_std) * math.sqrt(252)

    def _calculate_drawdown(self):
        """Calculate maximum drawdown."""
        if not self.equity_curve:
            return

        peak = self.equity_curve[0].equity
        max_dd = 0
        max_dd_pct = 0

        for point in self.equity_curve:
            if point.equity > peak:
                peak = point.equity

            drawdown = peak - point.equity
            drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0

            if drawdown > max_dd:
                max_dd = drawdown
                max_dd_pct = drawdown_pct

        self.max_drawdown = max_dd
        self.max_drawdown_pct = max_dd_pct

    def get_report(self) -> str:
        """Generate a formatted performance report."""
        lines = [
            "=" * 60,
            f"  BACKTEST RESULTS: {self.strategy_name}",
            "=" * 60,
            "",
            "RETURNS:",
            f"  Initial Capital:    ${self.initial_capital:,.2f}",
            f"  Final Capital:      ${self.final_capital:,.2f}",
            f"  Total Return:       ${self.total_return:+,.2f} ({self.total_return_pct:+.2f}%)",
            f"  Annualized Return:  {self.annualized_return:+.2f}%",
            "",
            "RISK METRICS:",
            f"  Sharpe Ratio:       {self.sharpe_ratio:.2f}",
            f"  Sortino Ratio:      {self.sortino_ratio:.2f}",
            f"  Max Drawdown:       ${self.max_drawdown:,.2f} ({self.max_drawdown_pct:.2f}%)",
            "",
            "TRADE STATISTICS:",
            f"  Total Trades:       {self.total_trades}",
            f"  Winning Trades:     {self.winning_trades}",
            f"  Losing Trades:      {self.losing_trades}",
            f"  Win Rate:           {self.win_rate:.1f}%",
            f"  Profit Factor:      {self.profit_factor:.2f}",
            f"  Avg Win:            ${self.avg_win:+.2f}",
            f"  Avg Loss:           ${self.avg_loss:+.2f}",
            f"  Avg Trade:          ${self.avg_trade:+.2f}",
            f"  Avg Holding Period: {self.avg_holding_period:.1f} hours",
            "",
            "=" * 60,
        ]

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Export metrics as dictionary."""
        return {
            "strategy": self.strategy_name,
            "initial_capital": self.initial_capital,
            "final_capital": self.final_capital,
            "total_return": self.total_return,
            "total_return_pct": self.total_return_pct,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_pct": self.max_drawdown_pct,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "avg_trade": self.avg_trade,
            "avg_holding_period": self.avg_holding_period,
        }


def compare_strategies(results: List[PerformanceMetrics]) -> str:
    """Generate comparison table for multiple strategies."""
    if not results:
        return "No results to compare"

    # Sort by total return
    results = sorted(results, key=lambda x: x.total_return_pct, reverse=True)

    lines = [
        "=" * 100,
        "  STRATEGY COMPARISON",
        "=" * 100,
        "",
        f"{'Strategy':<20} {'Return':>10} {'Sharpe':>8} {'MaxDD':>10} {'Trades':>8} {'Win%':>8} {'PF':>8}",
        "-" * 100,
    ]

    for r in results:
        lines.append(
            f"{r.strategy_name:<20} "
            f"{r.total_return_pct:>+9.1f}% "
            f"{r.sharpe_ratio:>8.2f} "
            f"{r.max_drawdown_pct:>9.1f}% "
            f"{r.total_trades:>8} "
            f"{r.win_rate:>7.1f}% "
            f"{r.profit_factor:>8.2f}"
        )

    lines.append("-" * 100)

    # Best performers
    best_return = results[0]
    best_sharpe = max(results, key=lambda x: x.sharpe_ratio)
    best_winrate = max(results, key=lambda x: x.win_rate)

    lines.extend([
        "",
        f"Best Return:  {best_return.strategy_name} ({best_return.total_return_pct:+.1f}%)",
        f"Best Sharpe:  {best_sharpe.strategy_name} ({best_sharpe.sharpe_ratio:.2f})",
        f"Best WinRate: {best_winrate.strategy_name} ({best_winrate.win_rate:.1f}%)",
        "",
        "=" * 100,
    ])

    return "\n".join(lines)
