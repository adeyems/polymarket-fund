#!/usr/bin/env python3
"""
BACKTEST RUNNER
================
CLI tool to run backtests and compare strategies.

Usage:
    python run_backtest.py                    # Quick test with synthetic data
    python run_backtest.py --days 30          # 30-day backtest
    python run_backtest.py --data file.json   # Use historical data file
    python run_backtest.py --api 50           # Fetch 50 markets from Polymarket API
    python run_backtest.py --kaggle data.zip  # Use Kaggle dataset
    python run_backtest.py --compare          # Compare all strategies
    python run_backtest.py --visualize        # Show equity curve charts
    python run_backtest.py --optimize MEAN_REVERSION  # Optimize strategy parameters
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.data_loader import DataLoader
from backtest.engine import BacktestEngine, BacktestConfig, BUILTIN_STRATEGIES
from backtest.metrics import PerformanceMetrics, compare_strategies
from backtest.visualize import (
    equity_curve_ascii,
    drawdown_chart_ascii,
    trade_distribution_ascii,
    generate_full_report,
    optimize_strategy_parameters,
    optimization_report,
    export_equity_curve_csv
)
from backtest.monte_carlo import (
    run_monte_carlo_from_metrics,
    monte_carlo_report,
    monte_carlo_histogram,
    compare_strategies_monte_carlo
)


def main():
    parser = argparse.ArgumentParser(description="Run backtests on trading strategies")
    parser.add_argument("--days", type=int, default=30, help="Days of synthetic data to simulate")
    parser.add_argument("--markets", type=int, default=50, help="Number of markets")
    parser.add_argument("--capital", type=float, default=10000, help="Initial capital")
    parser.add_argument("--data", type=str, help="Path to historical data JSON file")
    parser.add_argument("--api", action="store_true", help="Fetch real data from Polymarket API")
    parser.add_argument("--kaggle", type=str, help="Path to Kaggle dataset ZIP file")
    parser.add_argument("--strategy", type=str, help="Run single strategy (default: all)")
    parser.add_argument("--compare", action="store_true", help="Compare all strategies")
    parser.add_argument("--output", type=str, help="Output results to JSON file")
    parser.add_argument("--kelly", action="store_true", default=True, help="Use Kelly Criterion")
    parser.add_argument("--no-kelly", action="store_false", dest="kelly", help="Disable Kelly")
    parser.add_argument("--visualize", action="store_true", help="Show equity curve charts")
    parser.add_argument("--optimize", type=str, help="Optimize parameters for a strategy")
    parser.add_argument("--report", type=str, help="Generate full report to file")
    parser.add_argument("--monte-carlo", type=int, metavar="N", help="Run N Monte Carlo simulations")

    args = parser.parse_args()

    print("=" * 60)
    print("  POLYMARKET STRATEGY BACKTESTER")
    print("=" * 60)

    # Load data
    loader = DataLoader()
    data_source = "synthetic"

    if args.data:
        print(f"\nLoading data from: {args.data}")
        count = loader.load_from_file(args.data)
        print(f"Loaded {count} markets")
        data_source = "file"

    elif args.api:
        print(f"\nFetching {args.markets} markets from Polymarket API...")
        count = asyncio.run(loader.build_dataset_from_api(num_markets=args.markets))
        print(f"Fetched {count} markets")
        data_source = "api"

    elif args.kaggle:
        print(f"\nLoading Kaggle dataset: {args.kaggle}")
        count = loader.load_kaggle_dataset(args.kaggle, max_markets=args.markets)
        print(f"Loaded {count} markets")
        data_source = "kaggle"

    else:
        print(f"\nGenerating synthetic data: {args.markets} markets, {args.days} days")
        loader.generate_synthetic(
            num_markets=args.markets,
            days=args.days,
            interval_hours=1
        )
        data_source = "synthetic"

    print(f"\n{loader.summary()}")

    # Configure backtest
    config = BacktestConfig(
        initial_capital=args.capital,
        use_kelly=args.kelly,
        kelly_fraction=0.25,
        max_position_pct=0.10,
        take_profit_pct=0.05,
        stop_loss_pct=-0.10
    )

    print(f"\nConfig:")
    print(f"  Initial Capital: ${config.initial_capital:,.2f}")
    print(f"  Kelly Criterion: {'Enabled' if config.use_kelly else 'Disabled'}")
    print(f"  Max Position:    {config.max_position_pct * 100:.0f}%")
    print(f"  Take Profit:     {config.take_profit_pct * 100:.0f}%")
    print(f"  Stop Loss:       {config.stop_loss_pct * 100:.0f}%")

    # Handle parameter optimization
    if args.optimize:
        if args.optimize not in BUILTIN_STRATEGIES:
            print(f"Unknown strategy: {args.optimize}")
            print(f"Available: {', '.join(BUILTIN_STRATEGIES.keys())}")
            return

        print(f"\n" + "-" * 60)
        print(f"  OPTIMIZING: {args.optimize}")
        print("-" * 60)

        # Parameter grid for optimization
        param_grid = {
            "initial_capital": [args.capital],
            "max_position_pct": [0.05, 0.10, 0.15],
            "take_profit_pct": [0.03, 0.05, 0.08, 0.10],
            "stop_loss_pct": [-0.05, -0.10, -0.15],
            "use_kelly": [True, False],
            "kelly_fraction": [0.15, 0.25, 0.35],
        }

        opt_results = optimize_strategy_parameters(
            engine_class=BacktestEngine,
            data_loader=loader,
            strategy_func=BUILTIN_STRATEGIES[args.optimize],
            strategy_name=args.optimize,
            param_grid=param_grid
        )

        print("\n")
        print(optimization_report(opt_results, top_n=10))

        if opt_results:
            best = opt_results[0]
            print("\n" + "=" * 60)
            print(f"  BEST {args.optimize} BACKTEST")
            print("=" * 60)
            print(best.metrics.get_report())
            if args.visualize:
                print()
                print(equity_curve_ascii(best.metrics))

        return

    # Create engine
    engine = BacktestEngine(loader, config)

    # Add strategies
    if args.strategy:
        if args.strategy in BUILTIN_STRATEGIES:
            engine.add_strategy(args.strategy, BUILTIN_STRATEGIES[args.strategy])
        else:
            print(f"Unknown strategy: {args.strategy}")
            print(f"Available: {', '.join(BUILTIN_STRATEGIES.keys())}")
            return
    else:
        # Add all built-in strategies
        for name, func in BUILTIN_STRATEGIES.items():
            engine.add_strategy(name, func)

    # Run backtest
    print("\n" + "-" * 60)
    print("  RUNNING BACKTEST")
    print("-" * 60)

    results = engine.run()

    # Print results
    print("\n")
    for name, metrics in results.items():
        print(metrics.get_report())
        if args.visualize:
            print()
            print(equity_curve_ascii(metrics))
            print()
            print(drawdown_chart_ascii(metrics))
            print()
            print(trade_distribution_ascii(metrics))
        print()

    # Compare if multiple strategies
    if len(results) > 1:
        print(compare_strategies(list(results.values())))

    # Generate full report if requested
    if args.report:
        generate_full_report(results, args.report)

    # Run Monte Carlo simulation if requested
    if args.monte_carlo:
        print("\n" + "=" * 60)
        print(f"  MONTE CARLO SIMULATION ({args.monte_carlo:,} paths)")
        print("=" * 60)

        for name, metrics in results.items():
            try:
                mc_result = run_monte_carlo_from_metrics(metrics, args.monte_carlo, seed=42)
                print(f"\n{monte_carlo_report(mc_result, name)}")
                print(f"\n{monte_carlo_histogram(mc_result)}")
            except ValueError as e:
                print(f"\n{name}: Skipped Monte Carlo - {e}")

        # Comparison if multiple strategies
        if len(results) > 1:
            print(f"\n{compare_strategies_monte_carlo(results, args.monte_carlo, seed=42)}")

    # Save results
    if args.output:
        output_data = {
            "config": {
                "initial_capital": config.initial_capital,
                "use_kelly": config.use_kelly,
                "max_position_pct": config.max_position_pct,
                "take_profit_pct": config.take_profit_pct,
                "stop_loss_pct": config.stop_loss_pct,
            },
            "strategies": {
                name: metrics.to_dict()
                for name, metrics in results.items()
            },
            "run_time": datetime.now(timezone.utc).isoformat()
        }

        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)

        print(f"\nResults saved to: {args.output}")

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)

    best = max(results.values(), key=lambda x: x.total_return_pct)
    print(f"\nBest Strategy: {best.strategy_name}")
    print(f"  Return: {best.total_return_pct:+.2f}%")
    print(f"  Sharpe: {best.sharpe_ratio:.2f}")
    print(f"  Win Rate: {best.win_rate:.1f}%")
    print(f"  Max Drawdown: {best.max_drawdown_pct:.1f}%")


if __name__ == "__main__":
    main()
