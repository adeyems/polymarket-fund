#!/usr/bin/env python3
"""
Quick portfolio report - run anytime to check status.

Usage:
    python sovereign_hive/report.py           # Quick summary
    python sovereign_hive/report.py --full    # Detailed report
"""

import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

def load_portfolio():
    path = Path(__file__).parent / "data" / "portfolio_sim.json"
    if not path.exists():
        print("No portfolio found. Run simulation first.")
        return None
    with open(path) as f:
        return json.load(f)

def quick_report(data):
    """One-liner status."""
    balance = data["balance"]
    positions = len(data["positions"])
    invested = sum(p["cost_basis"] for p in data["positions"].values())
    total = balance + invested
    roi = (total - data["initial_balance"]) / data["initial_balance"] * 100
    trades = data["metrics"]["total_trades"]
    pnl = data["metrics"]["total_pnl"]

    print(f"Balance: ${balance:.2f} | Positions: {positions} | Invested: ${invested:.2f} | Total: ${total:.2f} | ROI: {roi:+.1f}% | Closed Trades: {trades} | P&L: ${pnl:+.2f}")

def full_report(data):
    """Detailed report."""
    print("=" * 70)
    print("  SOVEREIGN HIVE - PORTFOLIO REPORT")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Summary
    balance = data["balance"]
    positions = len(data["positions"])
    invested = sum(p["cost_basis"] for p in data["positions"].values())
    total = balance + invested
    roi = (total - data["initial_balance"]) / data["initial_balance"] * 100

    print(f"\n[SUMMARY]")
    print(f"  Cash Balance:    ${balance:,.2f}")
    print(f"  Invested:        ${invested:,.2f}")
    print(f"  Total Value:     ${total:,.2f}")
    print(f"  Initial:         ${data['initial_balance']:,.2f}")
    print(f"  ROI:             {roi:+.2f}%")

    # Positions
    print(f"\n[OPEN POSITIONS] ({positions} total)")
    print("-" * 70)
    for p in data["positions"].values():
        expected_value = p["shares"] * 1.0  # If wins, pays $1
        expected_profit = expected_value - p["cost_basis"]
        expected_roi = expected_profit / p["cost_basis"] * 100
        print(f"  {p['question'][:50]}...")
        print(f"    Strategy: {p.get('strategy', 'UNKNOWN'):12} | {p['side']} @ ${p['entry_price']:.3f}")
        print(f"    Cost: ${p['cost_basis']:.2f} | Expected if wins: ${expected_value:.2f} (+${expected_profit:.2f}, {expected_roi:+.1f}%)")
        print()

    # Metrics
    print(f"[METRICS]")
    m = data["metrics"]
    win_rate = (m["winning_trades"] / m["total_trades"] * 100) if m["total_trades"] > 0 else 0
    print(f"  Total Trades:    {m['total_trades']}")
    print(f"  Winning:         {m['winning_trades']}")
    print(f"  Losing:          {m['losing_trades']}")
    print(f"  Win Rate:        {win_rate:.1f}%")
    print(f"  Total P&L:       ${m['total_pnl']:+.2f}")
    print(f"  Max Drawdown:    {m['max_drawdown']*100:.2f}%")

    # Strategy A/B
    print(f"\n[STRATEGY A/B TEST]")
    print("-" * 70)
    for strat, metrics in data.get("strategy_metrics", {}).items():
        trades = metrics["trades"]
        wins = metrics["wins"]
        pnl = metrics["pnl"]
        wr = (wins / trades * 100) if trades > 0 else 0
        # Count open positions per strategy
        open_count = sum(1 for p in data["positions"].values() if p.get("strategy") == strat)
        print(f"  {strat:15} | Open: {open_count:2} | Closed: {trades:2} | Win: {wr:5.1f}% | P&L: ${pnl:+.2f}")

    # Trade History
    if data["trade_history"]:
        print(f"\n[RECENT TRADES] (last 5)")
        print("-" * 70)
        for t in data["trade_history"][-5:]:
            print(f"  {t['question'][:40]}...")
            print(f"    {t['side']} @ ${t['entry_price']:.3f} -> ${t['exit_price']:.3f} | P&L: ${t['pnl']:+.2f} ({t['pnl_pct']:+.1f}%) | {t['exit_reason']}")
    else:
        print(f"\n[TRADE HISTORY]")
        print("  No closed trades yet. Positions still open.")

    print("\n" + "=" * 70)
    print(f"  Last Updated: {data['last_updated']}")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Portfolio Report")
    parser.add_argument("--full", action="store_true", help="Show detailed report")
    args = parser.parse_args()

    data = load_portfolio()
    if not data:
        return

    if args.full:
        full_report(data)
    else:
        quick_report(data)

if __name__ == "__main__":
    main()
