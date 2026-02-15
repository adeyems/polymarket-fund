#!/usr/bin/env python3
"""
STRATEGY COMPARISON DASHBOARD
==============================
Compares performance of isolated strategy runners.

Usage:
    python compare_strategies.py           # One-time comparison
    python compare_strategies.py --watch   # Live monitoring
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Add parent paths
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

DATA_DIR = Path(__file__).parent.parent / "data" / "ab_test"

STRATEGIES = [
    "MARKET_MAKER",
    "BINANCE_ARB",
    "NEAR_ZERO",
    "NEAR_CERTAIN",
    "DUAL_SIDE_ARB",
    "MID_RANGE",
    "DIP_BUY",
    "VOLUME_SURGE",
]


def load_portfolio(strategy: str) -> dict:
    """Load portfolio data for a strategy."""
    portfolio_file = DATA_DIR / f"portfolio_{strategy.lower()}.json"

    if not portfolio_file.exists():
        return None

    try:
        with open(portfolio_file, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {strategy}: {e}")
        return None


def calculate_metrics(portfolio: dict) -> dict:
    """Calculate performance metrics from portfolio data."""
    if portfolio is None:
        return None

    balance = portfolio.get("balance", 0)
    initial = portfolio.get("initial_balance", 1000)
    positions = portfolio.get("positions", {})
    trades = portfolio.get("trade_history", [])
    strategy_metrics = portfolio.get("strategy_metrics", {})

    # Calculate total value (balance + open positions)
    position_value = sum(p.get("cost_basis", 0) for p in positions.values())
    total_value = balance + position_value

    # P&L
    total_pnl = total_value - initial
    roi_pct = (total_pnl / initial) * 100 if initial > 0 else 0

    # Win rate
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    total_trades = len(trades)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    # Average trade
    avg_profit = sum(t.get("pnl", 0) for t in trades) / total_trades if total_trades > 0 else 0

    # Time running
    last_updated = portfolio.get("last_updated", "")
    try:
        last_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
        hours_running = (datetime.now(last_dt.tzinfo) - last_dt).total_seconds() / 3600
    except:
        hours_running = 0

    return {
        "balance": balance,
        "initial_balance": initial,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "roi_pct": roi_pct,
        "open_positions": len(positions),
        "total_trades": total_trades,
        "wins": wins,
        "win_rate": win_rate,
        "avg_profit": avg_profit,
        "hours_running": hours_running,
        "strategy_metrics": strategy_metrics,
    }


def print_comparison():
    """Print comparison table of all strategies."""
    print("\n" + "=" * 90)
    print("  STRATEGY A/B TEST COMPARISON")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 90)

    results = []

    for strategy in STRATEGIES:
        portfolio = load_portfolio(strategy)
        metrics = calculate_metrics(portfolio)

        if metrics:
            results.append({
                "strategy": strategy,
                **metrics
            })

    if not results:
        print("\nNo strategy data found. Start runners first:")
        print("  python strategy_runner.py --strategy MARKET_MAKER")
        print("  python strategy_runner.py --strategy BINANCE_ARB")
        return

    # Sort by ROI
    results.sort(key=lambda x: x["roi_pct"], reverse=True)

    # Print header
    print(f"\n{'Strategy':<15} {'P&L':>10} {'ROI':>8} {'Trades':>8} {'Win%':>8} {'Avg':>8} {'Positions':>10}")
    print("-" * 90)

    # Print each strategy
    for r in results:
        pnl_str = f"${r['total_pnl']:+.2f}"
        roi_str = f"{r['roi_pct']:+.1f}%"
        avg_str = f"${r['avg_profit']:.2f}"

        # Color coding (using ANSI)
        if r['roi_pct'] > 0:
            color = "\033[92m"  # Green
        elif r['roi_pct'] < 0:
            color = "\033[91m"  # Red
        else:
            color = "\033[0m"   # Default

        print(f"{color}{r['strategy']:<15} {pnl_str:>10} {roi_str:>8} {r['total_trades']:>8} {r['win_rate']:>7.0f}% {avg_str:>8} {r['open_positions']:>10}\033[0m")

    # Summary
    print("-" * 90)

    total_pnl = sum(r["total_pnl"] for r in results)
    total_trades = sum(r["total_trades"] for r in results)
    avg_roi = sum(r["roi_pct"] for r in results) / len(results) if results else 0

    print(f"{'TOTAL':<15} ${total_pnl:>+9.2f} {avg_roi:>+7.1f}% {total_trades:>8}")

    # Best performer
    if results:
        best = results[0]
        print(f"\n{'='*90}")
        print(f"  BEST PERFORMER: {best['strategy']}")
        print(f"  ROI: {best['roi_pct']:+.2f}% | P&L: ${best['total_pnl']:+.2f} | Win Rate: {best['win_rate']:.0f}%")
        print(f"{'='*90}")

    return results


def print_detailed_report():
    """Print detailed report for each strategy."""
    print("\n" + "=" * 90)
    print("  DETAILED STRATEGY REPORTS")
    print("=" * 90)

    for strategy in STRATEGIES:
        portfolio = load_portfolio(strategy)
        if portfolio is None:
            continue

        metrics = calculate_metrics(portfolio)
        if metrics is None:
            continue

        print(f"\n{'─' * 40}")
        print(f"  {strategy}")
        print(f"{'─' * 40}")

        print(f"  Balance:        ${metrics['balance']:.2f}")
        print(f"  Total Value:    ${metrics['total_value']:.2f}")
        print(f"  P&L:            ${metrics['total_pnl']:+.2f} ({metrics['roi_pct']:+.1f}%)")
        print(f"  Trades:         {metrics['total_trades']} ({metrics['wins']} wins)")
        print(f"  Win Rate:       {metrics['win_rate']:.1f}%")
        print(f"  Avg Profit:     ${metrics['avg_profit']:.2f}")
        print(f"  Open Positions: {metrics['open_positions']}")

        # Show open positions
        positions = portfolio.get("positions", {})
        if positions:
            print(f"\n  Open Positions:")
            for cid, pos in list(positions.items())[:3]:
                q = pos.get("question", "")[:35]
                entry = pos.get("entry_price", 0)
                side = pos.get("side", "?")
                print(f"    - {side} @ ${entry:.3f} | {q}...")

        # Recent trades
        trades = portfolio.get("trade_history", [])[-5:]
        if trades:
            print(f"\n  Recent Trades:")
            for t in trades:
                reason = t.get("exit_reason", "BUY")
                pnl = t.get("pnl", 0)
                q = t.get("question", "")[:30]
                print(f"    - {reason}: ${pnl:+.2f} | {q}...")


def export_csv():
    """Export comparison data to CSV."""
    import csv

    csv_file = DATA_DIR / "comparison.csv"

    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Strategy", "Balance", "Total Value", "P&L", "ROI%",
            "Trades", "Wins", "Win Rate", "Avg Profit", "Open Positions"
        ])

        for strategy in STRATEGIES:
            portfolio = load_portfolio(strategy)
            metrics = calculate_metrics(portfolio)

            if metrics:
                writer.writerow([
                    strategy,
                    f"{metrics['balance']:.2f}",
                    f"{metrics['total_value']:.2f}",
                    f"{metrics['total_pnl']:.2f}",
                    f"{metrics['roi_pct']:.2f}",
                    metrics['total_trades'],
                    metrics['wins'],
                    f"{metrics['win_rate']:.1f}",
                    f"{metrics['avg_profit']:.2f}",
                    metrics['open_positions'],
                ])

    print(f"\nExported to {csv_file}")


def main():
    parser = argparse.ArgumentParser(description="Compare strategy performance")
    parser.add_argument("--watch", action="store_true", help="Continuous monitoring")
    parser.add_argument("--interval", type=int, default=60, help="Watch interval (seconds)")
    parser.add_argument("--detailed", action="store_true", help="Show detailed reports")
    parser.add_argument("--export", action="store_true", help="Export to CSV")

    args = parser.parse_args()

    if args.export:
        export_csv()
        return

    if args.watch:
        import time
        try:
            while True:
                os.system("clear" if os.name != "nt" else "cls")
                print_comparison()
                if args.detailed:
                    print_detailed_report()
                print(f"\nRefreshing in {args.interval}s... (Ctrl+C to stop)")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        print_comparison()
        if args.detailed:
            print_detailed_report()


if __name__ == "__main__":
    main()
