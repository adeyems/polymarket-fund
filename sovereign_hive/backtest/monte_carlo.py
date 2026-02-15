#!/usr/bin/env python3
"""
MONTE CARLO SIMULATION
=======================
Estimate strategy risk through randomized simulations.

Features:
- Bootstrap resampling of historical trades
- Confidence intervals for returns
- Probability of ruin estimation
- Value at Risk (VaR) calculation
"""

import math
import random
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from datetime import datetime

from .metrics import PerformanceMetrics, Trade


@dataclass
class MonteCarloResult:
    """Results from Monte Carlo simulation."""
    num_simulations: int
    num_trades_per_sim: int

    # Return distribution
    mean_return_pct: float = 0.0
    median_return_pct: float = 0.0
    std_return_pct: float = 0.0
    min_return_pct: float = 0.0
    max_return_pct: float = 0.0

    # Confidence intervals
    ci_95_lower: float = 0.0
    ci_95_upper: float = 0.0
    ci_99_lower: float = 0.0
    ci_99_upper: float = 0.0

    # Risk metrics
    prob_positive_return: float = 0.0
    prob_loss_50pct: float = 0.0
    prob_loss_100pct: float = 0.0  # Probability of ruin

    # Value at Risk
    var_95: float = 0.0  # 5% worst case
    var_99: float = 0.0  # 1% worst case
    cvar_95: float = 0.0  # Expected loss in worst 5%

    # Drawdown distribution
    mean_max_drawdown: float = 0.0
    worst_max_drawdown: float = 0.0

    # All simulated returns (for plotting)
    all_returns: List[float] = field(default_factory=list)
    all_drawdowns: List[float] = field(default_factory=list)


def run_monte_carlo(
    trades: List[Trade],
    initial_capital: float = 10000.0,
    num_simulations: int = 1000,
    num_trades: int = None,
    seed: int = None
) -> MonteCarloResult:
    """
    Run Monte Carlo simulation using bootstrap resampling of trades.

    Args:
        trades: List of historical trades to sample from
        initial_capital: Starting capital for each simulation
        num_simulations: Number of random paths to simulate
        num_trades: Trades per simulation (default: same as input)
        seed: Random seed for reproducibility

    Returns:
        MonteCarloResult with distribution statistics
    """
    if seed is not None:
        random.seed(seed)

    # Filter to closed trades only
    closed_trades = [t for t in trades if not t.is_open and t.pnl != 0]

    if len(closed_trades) < 10:
        raise ValueError(f"Need at least 10 closed trades, got {len(closed_trades)}")

    if num_trades is None:
        num_trades = len(closed_trades)

    # Extract P&L values relative to trade size
    pnl_pcts = []
    for t in closed_trades:
        if t.cost_basis > 0:
            pnl_pcts.append(t.pnl / t.cost_basis)

    # Run simulations
    all_returns = []
    all_drawdowns = []

    for _ in range(num_simulations):
        # Bootstrap: sample trades with replacement
        sampled_pnls = random.choices(pnl_pcts, k=num_trades)

        # Simulate equity curve
        equity = initial_capital
        peak = equity
        max_dd = 0

        for pnl_pct in sampled_pnls:
            # Apply trade result (assume fixed position size)
            position_size = equity * 0.10  # 10% position
            trade_pnl = position_size * pnl_pct
            equity += trade_pnl

            # Track drawdown
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

            # Check for ruin
            if equity <= 0:
                equity = 0
                break

        final_return = (equity - initial_capital) / initial_capital * 100
        all_returns.append(final_return)
        all_drawdowns.append(max_dd * 100)

    # Calculate statistics
    all_returns.sort()
    all_drawdowns.sort()

    result = MonteCarloResult(
        num_simulations=num_simulations,
        num_trades_per_sim=num_trades,
        all_returns=all_returns,
        all_drawdowns=all_drawdowns
    )

    # Return distribution
    result.mean_return_pct = sum(all_returns) / len(all_returns)
    result.median_return_pct = all_returns[len(all_returns) // 2]
    result.std_return_pct = math.sqrt(
        sum((r - result.mean_return_pct) ** 2 for r in all_returns) / len(all_returns)
    )
    result.min_return_pct = all_returns[0]
    result.max_return_pct = all_returns[-1]

    # Confidence intervals
    idx_2_5 = int(0.025 * num_simulations)
    idx_97_5 = int(0.975 * num_simulations)
    idx_0_5 = int(0.005 * num_simulations)
    idx_99_5 = int(0.995 * num_simulations)

    result.ci_95_lower = all_returns[idx_2_5]
    result.ci_95_upper = all_returns[idx_97_5]
    result.ci_99_lower = all_returns[idx_0_5]
    result.ci_99_upper = all_returns[idx_99_5]

    # Probability calculations
    result.prob_positive_return = sum(1 for r in all_returns if r > 0) / num_simulations
    result.prob_loss_50pct = sum(1 for r in all_returns if r <= -50) / num_simulations
    result.prob_loss_100pct = sum(1 for r in all_returns if r <= -99) / num_simulations

    # Value at Risk
    idx_5 = int(0.05 * num_simulations)
    idx_1 = int(0.01 * num_simulations)
    result.var_95 = -all_returns[idx_5]  # Positive number = loss
    result.var_99 = -all_returns[idx_1]

    # Conditional VaR (Expected Shortfall)
    worst_5pct = all_returns[:idx_5]
    result.cvar_95 = -sum(worst_5pct) / len(worst_5pct) if worst_5pct else 0

    # Drawdown distribution
    result.mean_max_drawdown = sum(all_drawdowns) / len(all_drawdowns)
    result.worst_max_drawdown = all_drawdowns[-1]

    return result


def monte_carlo_report(result: MonteCarloResult, strategy_name: str = "Strategy") -> str:
    """Generate formatted Monte Carlo report."""
    lines = [
        "=" * 70,
        f"  MONTE CARLO SIMULATION: {strategy_name}",
        "=" * 70,
        f"  Simulations: {result.num_simulations:,}",
        f"  Trades per sim: {result.num_trades_per_sim}",
        "",
        "RETURN DISTRIBUTION:",
        f"  Mean Return:     {result.mean_return_pct:+.2f}%",
        f"  Median Return:   {result.median_return_pct:+.2f}%",
        f"  Std Deviation:   {result.std_return_pct:.2f}%",
        f"  Min Return:      {result.min_return_pct:+.2f}%",
        f"  Max Return:      {result.max_return_pct:+.2f}%",
        "",
        "CONFIDENCE INTERVALS:",
        f"  95% CI:          [{result.ci_95_lower:+.2f}%, {result.ci_95_upper:+.2f}%]",
        f"  99% CI:          [{result.ci_99_lower:+.2f}%, {result.ci_99_upper:+.2f}%]",
        "",
        "RISK METRICS:",
        f"  Prob(Return > 0):    {result.prob_positive_return:.1%}",
        f"  Prob(Loss > 50%):    {result.prob_loss_50pct:.1%}",
        f"  Prob(Ruin):          {result.prob_loss_100pct:.1%}",
        "",
        "VALUE AT RISK (VaR):",
        f"  VaR 95%:         {result.var_95:+.2f}% (5% worst case)",
        f"  VaR 99%:         {result.var_99:+.2f}% (1% worst case)",
        f"  CVaR 95%:        {result.cvar_95:+.2f}% (expected loss in worst 5%)",
        "",
        "DRAWDOWN DISTRIBUTION:",
        f"  Mean Max DD:     {result.mean_max_drawdown:.2f}%",
        f"  Worst Max DD:    {result.worst_max_drawdown:.2f}%",
        "",
        "=" * 70,
    ]

    return "\n".join(lines)


def monte_carlo_histogram(result: MonteCarloResult, bins: int = 20, width: int = 50) -> str:
    """Generate ASCII histogram of return distribution."""
    returns = result.all_returns

    min_val = min(returns)
    max_val = max(returns)
    range_val = max_val - min_val

    if range_val == 0:
        return "All returns identical"

    # Create bins
    bin_counts = [0] * bins
    bin_width = range_val / bins

    for r in returns:
        bin_idx = int((r - min_val) / bin_width)
        bin_idx = max(0, min(bins - 1, bin_idx))
        bin_counts[bin_idx] += 1

    max_count = max(bin_counts)

    lines = [
        "RETURN DISTRIBUTION HISTOGRAM",
        "-" * 60
    ]

    for i, count in enumerate(bin_counts):
        bin_start = min_val + i * bin_width
        bin_end = bin_start + bin_width
        bar_len = int((count / max_count) * width) if max_count > 0 else 0

        # Color-code positive/negative
        if bin_end <= 0:
            bar = "░" * bar_len
        elif bin_start >= 0:
            bar = "█" * bar_len
        else:
            bar = "▒" * bar_len

        lines.append(f"  {bin_start:>7.1f}% |{bar} ({count})")

    lines.append("")
    lines.append("  █ = Positive  ░ = Negative  ▒ = Spans zero")
    lines.append(f"  Mean: {result.mean_return_pct:+.2f}%  Median: {result.median_return_pct:+.2f}%")

    return "\n".join(lines)


def run_monte_carlo_from_metrics(
    metrics: PerformanceMetrics,
    num_simulations: int = 1000,
    seed: int = None
) -> MonteCarloResult:
    """
    Convenience function to run Monte Carlo from PerformanceMetrics.

    Args:
        metrics: Performance metrics from a backtest
        num_simulations: Number of simulations to run
        seed: Random seed for reproducibility

    Returns:
        MonteCarloResult
    """
    return run_monte_carlo(
        trades=metrics.trades,
        initial_capital=metrics.initial_capital,
        num_simulations=num_simulations,
        seed=seed
    )


def compare_strategies_monte_carlo(
    results_dict: dict,  # {strategy_name: PerformanceMetrics}
    num_simulations: int = 1000,
    seed: int = 42
) -> str:
    """
    Compare multiple strategies using Monte Carlo simulation.

    Args:
        results_dict: Dict of strategy name -> PerformanceMetrics
        num_simulations: Simulations per strategy
        seed: Random seed

    Returns:
        Formatted comparison report
    """
    mc_results = {}

    for name, metrics in results_dict.items():
        try:
            mc_results[name] = run_monte_carlo_from_metrics(
                metrics, num_simulations, seed
            )
        except ValueError as e:
            mc_results[name] = None
            print(f"  {name}: Skipped ({e})")

    # Build comparison table
    lines = [
        "=" * 90,
        "  MONTE CARLO STRATEGY COMPARISON",
        f"  ({num_simulations:,} simulations per strategy)",
        "=" * 90,
        "",
        f"{'Strategy':<18} {'Mean':>8} {'Median':>8} {'95% CI':>20} {'Prob+':>8} {'VaR95':>8}",
        "-" * 90,
    ]

    # Sort by mean return
    sorted_names = sorted(
        mc_results.keys(),
        key=lambda x: mc_results[x].mean_return_pct if mc_results[x] else -999,
        reverse=True
    )

    for name in sorted_names:
        mc = mc_results[name]
        if mc is None:
            lines.append(f"{name:<18} {'--':>8} {'--':>8} {'--':>20} {'--':>8} {'--':>8}")
        else:
            ci = f"[{mc.ci_95_lower:+.1f}%, {mc.ci_95_upper:+.1f}%]"
            lines.append(
                f"{name:<18} {mc.mean_return_pct:>+7.1f}% {mc.median_return_pct:>+7.1f}% "
                f"{ci:>20} {mc.prob_positive_return:>7.0%} {mc.var_95:>+7.1f}%"
            )

    lines.append("-" * 90)

    # Find best
    valid_results = {k: v for k, v in mc_results.items() if v is not None}
    if valid_results:
        best_mean = max(valid_results.items(), key=lambda x: x[1].mean_return_pct)
        best_sharpe = max(valid_results.items(),
                         key=lambda x: x[1].mean_return_pct / x[1].std_return_pct if x[1].std_return_pct > 0 else 0)
        safest = min(valid_results.items(), key=lambda x: x[1].var_95)

        lines.extend([
            "",
            f"Best Mean Return:  {best_mean[0]} ({best_mean[1].mean_return_pct:+.1f}%)",
            f"Best Risk-Adj:     {best_sharpe[0]} (Mean/Std: {best_sharpe[1].mean_return_pct / best_sharpe[1].std_return_pct:.2f})" if best_sharpe[1].std_return_pct > 0 else "",
            f"Lowest VaR:        {safest[0]} ({safest[1].var_95:+.1f}%)",
            "",
            "=" * 90,
        ])

    return "\n".join(lines)
