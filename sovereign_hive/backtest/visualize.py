#!/usr/bin/env python3
"""
BACKTEST VISUALIZATION
=======================
Generate equity curve visualizations and parameter optimization reports.

Features:
- ASCII equity curve for terminal display
- HTML report with interactive charts
- Parameter sweep analysis
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .metrics import PerformanceMetrics, EquityPoint


def equity_curve_ascii(metrics: PerformanceMetrics, width: int = 70, height: int = 20) -> str:
    """
    Generate ASCII art equity curve for terminal display.

    Args:
        metrics: Performance metrics with equity curve
        width: Chart width in characters
        height: Chart height in characters

    Returns:
        ASCII art string
    """
    if not metrics.equity_curve:
        return "No equity curve data available"

    # Extract equity values
    equities = [p.equity for p in metrics.equity_curve]
    timestamps = [p.timestamp for p in metrics.equity_curve]

    if len(equities) < 2:
        return "Insufficient data for chart"

    # Calculate bounds
    min_eq = min(equities)
    max_eq = max(equities)
    eq_range = max_eq - min_eq

    if eq_range == 0:
        eq_range = 1  # Prevent division by zero

    # Build chart grid
    chart = [[' ' for _ in range(width)] for _ in range(height)]

    # Map equity values to chart positions
    for i, eq in enumerate(equities):
        x = int((i / (len(equities) - 1)) * (width - 1)) if len(equities) > 1 else 0
        y = int(((eq - min_eq) / eq_range) * (height - 1))
        y = height - 1 - y  # Flip y axis (0 at bottom)

        if 0 <= x < width and 0 <= y < height:
            # Use different chars for gain/loss
            if eq >= metrics.initial_capital:
                chart[y][x] = '█'
            else:
                chart[y][x] = '▒'

    # Add initial capital line
    init_y = int(((metrics.initial_capital - min_eq) / eq_range) * (height - 1))
    init_y = height - 1 - init_y
    if 0 <= init_y < height:
        for x in range(width):
            if chart[init_y][x] == ' ':
                chart[init_y][x] = '·'

    # Build output
    lines = []
    lines.append(f"  EQUITY CURVE: {metrics.strategy_name}")
    lines.append(f"  {'─' * (width + 4)}")

    # Y-axis labels
    for i, row in enumerate(chart):
        y_val = max_eq - (i / (height - 1)) * eq_range
        prefix = f"${y_val:>8,.0f} │"
        lines.append(prefix + ''.join(row))

    # X-axis
    lines.append(f"{'':>10} └{'─' * width}")

    # Time labels
    start_str = timestamps[0].strftime("%m/%d")
    end_str = timestamps[-1].strftime("%m/%d")
    mid_idx = len(timestamps) // 2
    mid_str = timestamps[mid_idx].strftime("%m/%d") if mid_idx < len(timestamps) else ""

    # Format time axis
    time_axis = f"{'':>11}{start_str}{' ' * ((width - len(start_str) - len(end_str) - len(mid_str)) // 2)}{mid_str}{' ' * ((width - len(start_str) - len(end_str) - len(mid_str)) // 2)}{end_str}"
    lines.append(time_axis)

    # Legend
    lines.append("")
    lines.append(f"  █ = Above initial  ▒ = Below initial  · = Initial capital (${metrics.initial_capital:,.0f})")
    lines.append(f"  Final: ${metrics.final_capital:,.2f} ({metrics.total_return_pct:+.2f}%)")
    lines.append(f"  Max Drawdown: {metrics.max_drawdown_pct:.1f}%  Sharpe: {metrics.sharpe_ratio:.2f}")

    return '\n'.join(lines)


def drawdown_chart_ascii(metrics: PerformanceMetrics, width: int = 70, height: int = 10) -> str:
    """Generate ASCII drawdown chart."""
    if not metrics.equity_curve:
        return "No equity curve data available"

    equities = [p.equity for p in metrics.equity_curve]

    # Calculate drawdown series
    drawdowns = []
    peak = equities[0]
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        drawdowns.append(dd)

    max_dd = max(drawdowns) if drawdowns else 0
    if max_dd == 0:
        max_dd = 1

    # Build chart
    chart = [[' ' for _ in range(width)] for _ in range(height)]

    for i, dd in enumerate(drawdowns):
        x = int((i / (len(drawdowns) - 1)) * (width - 1)) if len(drawdowns) > 1 else 0
        y = int((dd / max_dd) * (height - 1))

        if 0 <= x < width and 0 <= y < height:
            chart[y][x] = '▼' if dd == max(drawdowns) else '░'

    lines = []
    lines.append(f"  DRAWDOWN CHART")
    lines.append(f"  {'─' * (width + 4)}")

    for i, row in enumerate(chart):
        dd_val = (i / (height - 1)) * max_dd
        prefix = f"{dd_val:>6.1f}% │"
        lines.append(prefix + ''.join(row))

    lines.append(f"{'':>8} └{'─' * width}")
    lines.append(f"  ▼ = Max drawdown ({max_dd:.1f}%)")

    return '\n'.join(lines)


def trade_distribution_ascii(metrics: PerformanceMetrics, bins: int = 10) -> str:
    """Generate ASCII histogram of trade P&L distribution."""
    closed_trades = [t for t in metrics.trades if not t.is_open]

    if not closed_trades:
        return "No closed trades"

    pnls = [t.pnl for t in closed_trades]

    min_pnl = min(pnls)
    max_pnl = max(pnls)
    pnl_range = max_pnl - min_pnl

    if pnl_range == 0:
        pnl_range = 1

    # Create bins
    bin_counts = [0] * bins
    for pnl in pnls:
        bin_idx = int(((pnl - min_pnl) / pnl_range) * (bins - 1))
        bin_idx = max(0, min(bins - 1, bin_idx))
        bin_counts[bin_idx] += 1

    max_count = max(bin_counts) if bin_counts else 1
    bar_width = 40

    lines = []
    lines.append(f"  P&L DISTRIBUTION ({len(closed_trades)} trades)")
    lines.append(f"  {'─' * 60}")

    for i, count in enumerate(bin_counts):
        bin_start = min_pnl + (i / bins) * pnl_range
        bin_end = min_pnl + ((i + 1) / bins) * pnl_range
        bar_len = int((count / max_count) * bar_width) if max_count > 0 else 0

        # Color positive/negative differently
        if bin_start >= 0:
            bar = '█' * bar_len
        else:
            bar = '░' * bar_len

        lines.append(f"  ${bin_start:>7.0f}-{bin_end:>7.0f} │{bar} ({count})")

    lines.append("")
    lines.append(f"  █ = Profit bins  ░ = Loss bins")
    lines.append(f"  Avg Win: ${metrics.avg_win:+.2f}  Avg Loss: ${metrics.avg_loss:.2f}")

    return '\n'.join(lines)


def generate_full_report(
    results: Dict[str, PerformanceMetrics],
    output_path: Optional[str] = None
) -> str:
    """
    Generate a comprehensive text report for all strategies.

    Args:
        results: Dict of strategy name -> performance metrics
        output_path: Optional file path to save report

    Returns:
        Full report as string
    """
    lines = []

    # Header
    lines.append("=" * 80)
    lines.append("  POLYMARKET STRATEGY BACKTEST REPORT")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 80)
    lines.append("")

    # Sort by return
    sorted_results = sorted(results.items(), key=lambda x: x[1].total_return_pct, reverse=True)

    # Summary table
    lines.append("  STRATEGY COMPARISON")
    lines.append("  " + "-" * 76)
    lines.append(f"  {'Strategy':<18} {'Return':>10} {'Sharpe':>8} {'MaxDD':>8} {'Trades':>8} {'Win%':>8} {'PF':>8}")
    lines.append("  " + "-" * 76)

    for name, m in sorted_results:
        lines.append(
            f"  {name:<18} {m.total_return_pct:>+9.1f}% {m.sharpe_ratio:>8.2f} "
            f"{m.max_drawdown_pct:>7.1f}% {m.total_trades:>8} {m.win_rate:>7.1f}% "
            f"{m.profit_factor:>8.2f}"
        )

    lines.append("  " + "-" * 76)
    lines.append("")

    # Individual strategy reports with charts
    for name, metrics in sorted_results:
        lines.append("")
        lines.append("=" * 80)
        lines.append(metrics.get_report())
        lines.append("")
        lines.append(equity_curve_ascii(metrics))
        lines.append("")
        lines.append(drawdown_chart_ascii(metrics))
        lines.append("")
        lines.append(trade_distribution_ascii(metrics))

    report = '\n'.join(lines)

    # Save if path provided
    if output_path:
        Path(output_path).write_text(report)
        print(f"Report saved to: {output_path}")

    return report


def export_equity_curve_csv(metrics: PerformanceMetrics, output_path: str):
    """Export equity curve to CSV for external plotting."""
    lines = ["timestamp,equity,cash,positions_value"]
    for point in metrics.equity_curve:
        lines.append(f"{point.timestamp.isoformat()},{point.equity:.2f},{point.cash:.2f},{point.positions_value:.2f}")

    Path(output_path).write_text('\n'.join(lines))
    print(f"Equity curve exported to: {output_path}")


@dataclass
class OptimizationResult:
    """Result from parameter optimization."""
    parameters: Dict
    metrics: PerformanceMetrics
    score: float


def optimize_strategy_parameters(
    engine_class,
    data_loader,
    strategy_func,
    strategy_name: str,
    param_grid: Dict[str, List],
    score_func = None
) -> List[OptimizationResult]:
    """
    Perform parameter optimization via grid search.

    Args:
        engine_class: BacktestEngine class
        data_loader: DataLoader with historical data
        strategy_func: Strategy function to optimize
        strategy_name: Name of the strategy
        param_grid: Dict of parameter name -> list of values to try
        score_func: Optional custom scoring function (default: Sharpe ratio)

    Returns:
        List of OptimizationResult sorted by score
    """
    from .engine import BacktestConfig

    if score_func is None:
        score_func = lambda m: m.sharpe_ratio

    results = []

    # Generate all parameter combinations
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())

    def generate_combinations(values, idx=0, current=None):
        if current is None:
            current = {}
        if idx == len(values):
            return [current.copy()]

        combos = []
        for v in values[idx]:
            current[param_names[idx]] = v
            combos.extend(generate_combinations(values, idx + 1, current))
        return combos

    combinations = generate_combinations(param_values)
    total = len(combinations)

    print(f"Optimizing {strategy_name}: {total} parameter combinations")

    for i, params in enumerate(combinations):
        # Create config with these parameters
        config = BacktestConfig(**params)

        # Run backtest
        engine = engine_class(data_loader, config)
        engine.add_strategy(strategy_name, strategy_func)

        try:
            run_results = engine.run()
            metrics = run_results[strategy_name]
            score = score_func(metrics)

            results.append(OptimizationResult(
                parameters=params.copy(),
                metrics=metrics,
                score=score
            ))
        except Exception as e:
            print(f"  Combination {i+1}/{total} failed: {e}")
            continue

        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/{total}")

    # Sort by score descending
    results.sort(key=lambda x: x.score, reverse=True)

    return results


def optimization_report(results: List[OptimizationResult], top_n: int = 10) -> str:
    """Generate report from optimization results."""
    lines = []
    lines.append("=" * 80)
    lines.append("  PARAMETER OPTIMIZATION RESULTS")
    lines.append("=" * 80)
    lines.append("")

    if not results:
        lines.append("No valid results")
        return '\n'.join(lines)

    lines.append(f"  Top {min(top_n, len(results))} configurations:")
    lines.append("  " + "-" * 76)

    for i, r in enumerate(results[:top_n]):
        lines.append(f"\n  #{i+1} Score: {r.score:.4f}")
        lines.append(f"      Return: {r.metrics.total_return_pct:+.2f}%")
        lines.append(f"      Sharpe: {r.metrics.sharpe_ratio:.2f}")
        lines.append(f"      MaxDD: {r.metrics.max_drawdown_pct:.1f}%")
        lines.append(f"      Win Rate: {r.metrics.win_rate:.1f}%")
        lines.append(f"      Parameters: {r.parameters}")

    # Best configuration
    best = results[0]
    lines.append("")
    lines.append("=" * 80)
    lines.append("  BEST CONFIGURATION")
    lines.append("=" * 80)
    for k, v in best.parameters.items():
        lines.append(f"    {k}: {v}")

    return '\n'.join(lines)
