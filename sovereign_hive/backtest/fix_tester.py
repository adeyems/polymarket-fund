#!/usr/bin/env python3
"""
FIX TESTER - A/B Test Framework for Strategy Fixes
=====================================================
Validates proposed strategy fixes against historical data.

Runs "before" (broken) and "after" (fixed) versions side by side,
comparing metrics to declare FIX VALIDATED or FIX REJECTED.

Usage:
    python fix_tester.py                    # Test all available fixes
    python fix_tester.py MEAN_REVERSION     # Test single fix
    python fix_tester.py --markets 500      # More markets for confidence
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from sovereign_hive.backtest.data_loader import DataLoader
from sovereign_hive.backtest.engine import BacktestEngine, BacktestConfig
from sovereign_hive.backtest.strategies import (
    PRODUCTION_STRATEGIES, BROKEN_STRATEGIES, reset_state,
)


def load_data(max_markets: int = 200) -> DataLoader:
    loader = DataLoader()
    zip_path = str(loader.DATA_DIR / "full-market-data-from-polymarket.zip")
    count = loader.preprocess_kaggle_to_cache(
        zip_path=zip_path,
        min_price_points=100,
        max_markets=max_markets,
    )
    if count == 0:
        print("ERROR: No data loaded. Ensure Kaggle ZIP is at:")
        print(f"  {zip_path}")
        sys.exit(1)
    return loader


def run_version(loader, strategy_name, strategy_func, capital, label):
    """Run one version of a strategy."""
    reset_state()
    config = BacktestConfig(initial_capital=capital)
    engine = BacktestEngine(loader, config)
    engine.add_strategy(strategy_name, strategy_func, use_snapshots=True)
    results = engine.run(verbose=False)
    return results.get(strategy_name)


def test_fix(loader, strategy_name, capital=1000.0):
    """Run A/B test for a single strategy fix."""
    if strategy_name not in BROKEN_STRATEGIES:
        return None
    if strategy_name not in PRODUCTION_STRATEGIES:
        return None

    broken = run_version(loader, strategy_name, BROKEN_STRATEGIES[strategy_name], capital, "BROKEN")
    fixed = run_version(loader, strategy_name, PRODUCTION_STRATEGIES[strategy_name], capital, "FIXED")

    if not broken or not fixed:
        return None

    return {
        "strategy": strategy_name,
        "broken": broken,
        "fixed": fixed,
    }


def print_comparison(result: dict):
    """Print detailed comparison for one fix test."""
    name = result["strategy"]
    b = result["broken"]
    f = result["fixed"]

    print(f"\n{'='*70}")
    print(f"  {name}: BROKEN vs FIXED")
    print(f"{'='*70}")
    print(f"")
    print(f"  {'Metric':<22} {'BROKEN':>14} {'FIXED':>14} {'Change':>14}")
    print(f"  {'-'*64}")

    metrics = [
        ("Return", f"{b.total_return_pct:+.1f}%", f"{f.total_return_pct:+.1f}%",
         f"{f.total_return_pct - b.total_return_pct:+.1f}%"),
        ("Final Capital", f"${b.final_capital:.2f}", f"${f.final_capital:.2f}",
         f"${f.final_capital - b.final_capital:+.2f}"),
        ("Trades", f"{b.total_trades}", f"{f.total_trades}",
         f"{f.total_trades - b.total_trades:+d}"),
        ("Win Rate", f"{b.win_rate:.1f}%", f"{f.win_rate:.1f}%",
         f"{f.win_rate - b.win_rate:+.1f}%"),
        ("Sharpe", f"{b.sharpe_ratio:.2f}", f"{f.sharpe_ratio:.2f}",
         f"{f.sharpe_ratio - b.sharpe_ratio:+.2f}"),
        ("Max Drawdown", f"{b.max_drawdown_pct:.1f}%", f"{f.max_drawdown_pct:.1f}%",
         f"{f.max_drawdown_pct - b.max_drawdown_pct:+.1f}%"),
        ("Profit Factor", f"{b.profit_factor:.2f}", f"{f.profit_factor:.2f}",
         f"{f.profit_factor - b.profit_factor:+.2f}"),
        ("Avg Win", f"${b.avg_win:.2f}", f"${f.avg_win:.2f}",
         f"${f.avg_win - b.avg_win:+.2f}"),
        ("Avg Loss", f"${b.avg_loss:.2f}", f"${f.avg_loss:.2f}",
         f"${f.avg_loss - b.avg_loss:+.2f}"),
    ]

    for label, bv, fv, delta in metrics:
        print(f"  {label:<22} {bv:>14} {fv:>14} {delta:>14}")

    # Determine verdict
    return_improved = f.total_return_pct > b.total_return_pct
    winrate_improved = f.win_rate > b.win_rate
    sharpe_improved = f.sharpe_ratio > b.sharpe_ratio
    drawdown_improved = f.max_drawdown_pct <= b.max_drawdown_pct

    score = sum([return_improved, winrate_improved, sharpe_improved, drawdown_improved])

    print(f"")
    print(f"  Improvement checklist:")
    print(f"    {'[x]' if return_improved else '[ ]'} Return improved")
    print(f"    {'[x]' if winrate_improved else '[ ]'} Win rate improved")
    print(f"    {'[x]' if sharpe_improved else '[ ]'} Sharpe ratio improved")
    print(f"    {'[x]' if drawdown_improved else '[ ]'} Drawdown reduced or same")
    print(f"")

    if score >= 3:
        verdict = "FIX VALIDATED"
    elif score >= 2 and return_improved:
        verdict = "FIX ACCEPTABLE"
    elif return_improved:
        verdict = "FIX MARGINAL"
    else:
        verdict = "FIX REJECTED"

    print(f"  VERDICT: {verdict} ({score}/4 metrics improved)")
    print(f"{'='*70}")

    return verdict


def save_report(results: list, filepath: str = None):
    """Save all fix test results to markdown."""
    if filepath is None:
        filepath = str(Path(__file__).parent.parent / "logs" / "fix_test_results.md")
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Fix Test Results",
        f"",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"| Strategy | Broken Return | Fixed Return | Broken Win% | Fixed Win% | Verdict |",
        f"|----------|---------------|--------------|-------------|------------|---------|",
    ]

    for r in results:
        b = r["result"]["broken"]
        f = r["result"]["fixed"]
        lines.append(
            f"| {r['strategy']} | {b.total_return_pct:+.1f}% | {f.total_return_pct:+.1f}% | "
            f"{b.win_rate:.1f}% | {f.win_rate:.1f}% | {r['verdict']} |"
        )

    with open(filepath, "w") as fh:
        fh.write("\n".join(lines))
    print(f"\nReport saved to: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Fix Tester - A/B Test Strategy Fixes")
    parser.add_argument("strategy", nargs="?", help="Strategy to test (default: all)")
    parser.add_argument("--markets", "-m", type=int, default=200, help="Max markets")
    parser.add_argument("--capital", "-c", type=float, default=1000.0, help="Starting capital")
    parser.add_argument("--save", action="store_true", help="Save results to file")
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f"  FIX TESTER - A/B Test Framework")
    print(f"  Capital: ${args.capital:,.0f} | Markets: {args.markets}")
    print(f"{'='*70}")

    start = time.time()
    loader = load_data(max_markets=args.markets)

    strategies_to_test = [args.strategy] if args.strategy else list(BROKEN_STRATEGIES.keys())
    all_results = []

    for name in strategies_to_test:
        print(f"\nTesting fix for: {name}...")
        result = test_fix(loader, name, capital=args.capital)
        if result:
            verdict = print_comparison(result)
            all_results.append({"strategy": name, "result": result, "verdict": verdict})
        else:
            print(f"  No broken version available for {name}")

    # Summary
    if len(all_results) > 1:
        print(f"\n{'='*70}")
        print(f"  SUMMARY")
        print(f"{'='*70}")
        for r in all_results:
            b = r["result"]["broken"]
            f = r["result"]["fixed"]
            print(f"  {r['strategy']:<20} {b.total_return_pct:>+8.1f}% -> {f.total_return_pct:>+8.1f}%  {r['verdict']}")
        print(f"{'='*70}")

    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f}s")

    if args.save:
        save_report(all_results)


if __name__ == "__main__":
    main()
