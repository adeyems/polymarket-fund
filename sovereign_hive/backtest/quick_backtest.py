#!/usr/bin/env python3
"""
QUICK BACKTEST - Honest strategy validation
=============================================
Two modes based on what data is available:

  --price-only  (default) Test price-based strategies on Kaggle data
                          Skips MARKET_MAKER, DUAL_SIDE_ARB, BINANCE_ARB, VOLUME_SURGE
                          Available NOW

  --full                  Test ALL strategies on real collected bid/ask data
                          Requires 7+ days of snapshot collection
                          Available after running simulation with snapshot logger

Usage:
    python quick_backtest.py                              # Price-only, all testable strategies
    python quick_backtest.py --strategy MEAN_REVERSION    # Single strategy
    python quick_backtest.py --fix-test MEAN_REVERSION    # Before/after fix comparison
    python quick_backtest.py --full                       # All 9 (needs collected data)
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
    PRICE_ONLY_STRATEGIES, SPREAD_STRATEGIES, PRODUCTION_STRATEGIES,
    BROKEN_STRATEGIES, reset_state,
)
from sovereign_hive.backtest.snapshot_loader import (
    load_snapshots, count_snapshot_days, snapshot_summary,
)


def load_kaggle_data(max_markets: int = None, min_points: int = 100) -> DataLoader:
    """Load Kaggle data with caching."""
    loader = DataLoader()
    zip_path = str(loader.DATA_DIR / "full-market-data-from-polymarket.zip")
    cache_path = str(loader.DATA_DIR / "kaggle_cache.json")

    # Delete stale cache if it exists (force rebuild with all markets)
    cache_file = Path(cache_path)
    if cache_file.exists() and max_markets is None:
        # Only rebuild if not explicitly limiting markets
        pass

    count = loader.preprocess_kaggle_to_cache(
        zip_path=zip_path,
        cache_path=cache_path,
        min_price_points=min_points,
        max_markets=max_markets,
    )

    if count == 0:
        print("\nERROR: No data loaded!")
        print(f"  Expected Kaggle ZIP at: {zip_path}")
        print("  Download: https://www.kaggle.com/datasets/sandeepkumarfromin/full-market-data-from-polymarket")
        sys.exit(1)

    return loader


def print_data_quality(loader: DataLoader):
    """Print honest data quality report."""
    markets = list(loader.markets.values())
    total = len(markets)
    resolved = [m for m in markets if m.resolution]
    yes_count = sum(1 for m in resolved if m.resolution == "YES")
    no_count = sum(1 for m in resolved if m.resolution == "NO")
    unresolved = total - len(resolved)

    min_t, max_t = loader.get_time_range()
    days = (max_t - min_t).days if min_t and max_t else 0

    print(f"\n  DATA QUALITY REPORT")
    print(f"  {'='*50}")
    print(f"  Markets:     {total}")
    print(f"  Resolved:    {len(resolved)} ({yes_count} YES, {no_count} NO)")
    print(f"  Unresolved:  {unresolved}")
    print(f"  Time range:  {min_t.strftime('%Y-%m-%d') if min_t else '?'} to {max_t.strftime('%Y-%m-%d') if max_t else '?'} ({days}d)")

    # Bias warning
    if len(resolved) > 0:
        bias = max(yes_count, no_count) / len(resolved) * 100
        if bias > 70:
            dominant = "NO" if no_count > yes_count else "YES"
            print(f"  WARNING:     Resolution bias {bias:.0f}% toward {dominant}")
            print(f"               Strategies betting on {dominant} may appear")
            print(f"               artificially profitable")

    # Data source warning
    print(f"  Data source: Kaggle (mid-price only, NO real bid/ask)")
    print(f"  {'='*50}")


def run_strategies(loader, strategy_dict, capital=1000.0, verbose=True):
    """Run a set of strategies and return results."""
    all_results = {}
    for name, func in strategy_dict.items():
        reset_state()
        config = BacktestConfig(initial_capital=capital)
        engine = BacktestEngine(loader, config)
        engine.add_strategy(name, func, use_snapshots=True)
        results = engine.run(verbose=verbose)
        if name in results:
            all_results[name] = results[name]
    return all_results


def print_results_table(results: dict, skipped: list = None):
    """Print formatted results with skipped strategies marked N/A."""
    print(f"\n{'='*105}")
    print(f"  BACKTEST RESULTS")
    print(f"{'='*105}\n")

    print(f"  {'#':<3} {'Strategy':<18} {'Return':>10} {'Trades':>8} {'Win%':>8} "
          f"{'Sharpe':>8} {'MaxDD':>8} {'AvgTrade':>10} {'PF':>8} {'Status':>14}")
    print(f"  {'-'*105}")

    # Sort tested strategies by return
    sorted_results = sorted(results.items(), key=lambda x: x[1].total_return_pct, reverse=True)
    i = 0

    for name, m in sorted_results:
        i += 1
        if m.total_trades == 0:
            verdict = "NO TRADES"
        elif m.total_return_pct > 10 and m.win_rate > 60:
            verdict = "STRONG"
        elif m.total_return_pct > 0:
            verdict = "POSITIVE"
        elif m.total_return_pct > -10:
            verdict = "MARGINAL"
        else:
            verdict = "LOSING"

        pf = f"{m.profit_factor:.2f}" if m.profit_factor < 999 else "INF"
        print(f"  {i:<3} {name:<18} {m.total_return_pct:>+9.1f}% "
              f"{m.total_trades:>8} {m.win_rate:>7.1f}% "
              f"{m.sharpe_ratio:>8.2f} {m.max_drawdown_pct:>7.1f}% "
              f"${m.avg_trade:>+9.2f} {pf:>8} {verdict:>14}")

    # Show skipped strategies
    if skipped:
        for name in skipped:
            i += 1
            print(f"  {i:<3} {name:<18} {'N/A':>10} {'N/A':>8} {'N/A':>8} "
                  f"{'N/A':>8} {'N/A':>8} {'N/A':>10} {'N/A':>8} {'NEEDS REAL DATA':>14}")

    print(f"  {'-'*105}")

    # Recommendations
    profitable = [(n, m) for n, m in sorted_results if m.total_return_pct > 0 and m.total_trades > 0]
    if profitable:
        print(f"\n  Testable strategies with positive return:")
        for name, m in profitable[:3]:
            print(f"    - {name}: {m.total_return_pct:+.1f}%, {m.win_rate:.1f}% win rate, {m.sharpe_ratio:.2f} Sharpe")

    losing = [(n, m) for n, m in sorted_results if m.total_return_pct < -10]
    if losing:
        print(f"\n  Needs fixing (losing >10%):")
        for name, m in losing:
            print(f"    - {name}: {m.total_return_pct:+.1f}%, {m.win_rate:.1f}% win rate")

    if skipped:
        print(f"\n  Cannot test without real data ({len(skipped)} strategies):")
        print(f"    {', '.join(skipped)}")
        days = count_snapshot_days()
        if days == 0:
            print(f"    Start collecting: restart simulation (snapshot logger is built in)")
        else:
            print(f"    Collecting: {days} days so far (need 7+ for --full mode)")

    print(f"\n{'='*105}\n")


def run_fix_test(loader, strategy_name, capital=1000.0):
    """A/B test: broken vs fixed version."""
    if strategy_name not in BROKEN_STRATEGIES:
        print(f"No broken version for: {strategy_name}")
        print(f"Available: {', '.join(BROKEN_STRATEGIES.keys())}")
        sys.exit(1)

    print(f"\n{'='*70}")
    print(f"  FIX TEST: {strategy_name} (BROKEN vs FIXED)")
    print(f"{'='*70}")

    # Broken
    reset_state()
    config = BacktestConfig(initial_capital=capital)
    engine = BacktestEngine(loader, config)
    engine.add_strategy(strategy_name, BROKEN_STRATEGIES[strategy_name], use_snapshots=True)
    b = engine.run(verbose=False).get(strategy_name)

    # Fixed
    reset_state()
    config = BacktestConfig(initial_capital=capital)
    engine = BacktestEngine(loader, config)
    engine.add_strategy(strategy_name, PRODUCTION_STRATEGIES[strategy_name], use_snapshots=True)
    f = engine.run(verbose=False).get(strategy_name)

    if not b or not f:
        print("  ERROR: Could not run comparison")
        return

    print(f"\n  {'Metric':<22} {'BROKEN':>14} {'FIXED':>14} {'Change':>14}")
    print(f"  {'-'*64}")
    rows = [
        ("Return", f"{b.total_return_pct:+.1f}%", f"{f.total_return_pct:+.1f}%", f"{f.total_return_pct - b.total_return_pct:+.1f}%"),
        ("Final Capital", f"${b.final_capital:.2f}", f"${f.final_capital:.2f}", f"${f.final_capital - b.final_capital:+.2f}"),
        ("Trades", f"{b.total_trades}", f"{f.total_trades}", f"{f.total_trades - b.total_trades:+d}"),
        ("Win Rate", f"{b.win_rate:.1f}%", f"{f.win_rate:.1f}%", f"{f.win_rate - b.win_rate:+.1f}%"),
        ("Sharpe", f"{b.sharpe_ratio:.2f}", f"{f.sharpe_ratio:.2f}", f"{f.sharpe_ratio - b.sharpe_ratio:+.2f}"),
        ("Max Drawdown", f"{b.max_drawdown_pct:.1f}%", f"{f.max_drawdown_pct:.1f}%", f"{f.max_drawdown_pct - b.max_drawdown_pct:+.1f}%"),
    ]
    for label, bv, fv, delta in rows:
        print(f"  {label:<22} {bv:>14} {fv:>14} {delta:>14}")

    checks = [
        f.total_return_pct > b.total_return_pct,
        f.win_rate > b.win_rate,
        f.sharpe_ratio > b.sharpe_ratio,
        f.max_drawdown_pct <= b.max_drawdown_pct,
    ]
    score = sum(checks)
    verdict = "FIX VALIDATED" if score >= 3 else ("FIX MARGINAL" if checks[0] else "FIX REJECTED")
    print(f"\n  VERDICT: {verdict} ({score}/4 metrics improved)")
    print(f"{'='*70}\n")


def save_results(results: dict, skipped: list, filepath: str = None):
    """Save results to markdown."""
    if filepath is None:
        filepath = str(Path(__file__).parent.parent / "logs" / "backtest_results.md")
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    sorted_r = sorted(results.items(), key=lambda x: x[1].total_return_pct, reverse=True)
    lines = [
        f"# Backtest Results (Price-Only Mode)",
        f"",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Data:** Kaggle (mid-price only, NO real bid/ask)",
        f"",
        f"| # | Strategy | Return | Trades | Win% | Sharpe | MaxDD | Status |",
        f"|---|----------|--------|--------|------|--------|-------|--------|",
    ]
    for i, (name, m) in enumerate(sorted_r, 1):
        lines.append(f"| {i} | {name} | {m.total_return_pct:+.1f}% | {m.total_trades} | "
                     f"{m.win_rate:.1f}% | {m.sharpe_ratio:.2f} | {m.max_drawdown_pct:.1f}% | Tested |")
    for name in skipped:
        lines.append(f"| - | {name} | N/A | N/A | N/A | N/A | N/A | NEEDS REAL DATA |")

    with open(filepath, "w") as f:
        f.write("\n".join(lines))
    print(f"Results saved to: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Quick Backtest Runner")
    parser.add_argument("--strategy", "-s", help="Run single strategy")
    parser.add_argument("--fix-test", "-f", help="A/B test broken vs fixed strategy")
    parser.add_argument("--full", action="store_true", help="Test ALL strategies (needs collected data)")
    parser.add_argument("--price-only", action="store_true", help="Test price-only strategies (default)")
    parser.add_argument("--markets", "-m", type=int, default=None, help="Max markets to load")
    parser.add_argument("--capital", "-c", type=float, default=1000.0, help="Starting capital")
    parser.add_argument("--save", action="store_true", help="Save results to file")
    parser.add_argument("--output", "-o", help="Output file path")
    args = parser.parse_args()

    # Determine mode
    if args.full:
        days = count_snapshot_days()
        if days < 7:
            print(f"\nERROR: --full mode requires 7+ days of collected snapshot data.")
            print(f"  Current: {days} days collected")
            if days == 0:
                print(f"  To start collecting: restart the simulation (snapshot logger is built in)")
            else:
                print(f"  Need {7 - days} more days. Keep simulation running.")
            print(f"\n  Use default mode (--price-only) to test price-based strategies now.\n")
            sys.exit(1)

    mode = "FULL" if args.full else "PRICE-ONLY"

    print(f"\n{'='*60}")
    print(f"  QUICK BACKTEST ({mode})")
    print(f"  Capital: ${args.capital:,.0f}")
    print(f"{'='*60}")

    start = time.time()

    # Load data
    if args.full:
        loader = load_snapshots(min_days=7, max_markets=args.markets)
        if loader is None:
            print("ERROR: Failed to load snapshot data")
            sys.exit(1)
        print(f"\n{snapshot_summary()}")
        strat_dict = PRODUCTION_STRATEGIES
        skipped = []
    else:
        loader = load_kaggle_data(max_markets=args.markets)
        print_data_quality(loader)
        strat_dict = PRICE_ONLY_STRATEGIES
        skipped = list(SPREAD_STRATEGIES.keys())

    # Run
    if args.fix_test:
        run_fix_test(loader, args.fix_test, capital=args.capital)
    elif args.strategy:
        if args.strategy not in strat_dict:
            if args.strategy in SPREAD_STRATEGIES and not args.full:
                print(f"\n  {args.strategy} requires real bid/ask data.")
                print(f"  Use --full mode after collecting 7+ days of snapshots.\n")
                sys.exit(1)
            print(f"Unknown strategy: {args.strategy}")
            sys.exit(1)
        results = run_strategies(loader, {args.strategy: strat_dict[args.strategy]}, args.capital)
        for name, m in results.items():
            print(m.get_report())
    else:
        results = run_strategies(loader, strat_dict, args.capital)
        print_results_table(results, skipped)

        if args.save or args.output:
            save_results(results, skipped, args.output)

    elapsed = time.time() - start
    print(f"Completed in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
