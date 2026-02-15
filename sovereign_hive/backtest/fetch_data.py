#!/usr/bin/env python3
"""
FETCH HISTORICAL DATA
======================
Download and prepare historical data for backtesting.

Sources:
1. Polymarket CLOB API (official)
2. Kaggle dataset (download manually first)

Usage:
    # Fetch from Polymarket API
    python fetch_data.py --api --markets 50

    # Load from Kaggle dataset
    python fetch_data.py --kaggle /path/to/polymarket-data.zip

    # Save fetched data for later use
    python fetch_data.py --api --markets 100 --save data/historical.json
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.data_loader import DataLoader


async def fetch_from_api(loader: DataLoader, num_markets: int) -> int:
    """Fetch data from Polymarket API."""
    print("\n" + "=" * 60)
    print("  FETCHING FROM POLYMARKET API")
    print("=" * 60)

    count = await loader.build_dataset_from_api(
        num_markets=num_markets,
        include_resolved=True
    )

    return count


def load_from_kaggle(loader: DataLoader, path: str, max_markets: int = None) -> int:
    """Load data from Kaggle dataset."""
    print("\n" + "=" * 60)
    print("  LOADING KAGGLE DATASET")
    print("=" * 60)

    return loader.load_kaggle_dataset(path, max_markets=max_markets)


def main():
    parser = argparse.ArgumentParser(description="Fetch historical data for backtesting")
    parser.add_argument("--api", action="store_true", help="Fetch from Polymarket API")
    parser.add_argument("--kaggle", type=str, help="Path to Kaggle ZIP file")
    parser.add_argument("--csv", type=str, help="Path to CSV file with price data")
    parser.add_argument("--markets", type=int, default=50, help="Number of markets to fetch")
    parser.add_argument("--save", type=str, help="Save data to JSON file")
    parser.add_argument("--info", action="store_true", help="Show data summary only")

    args = parser.parse_args()

    loader = DataLoader()

    # Check if we have saved data
    default_data = loader.DATA_DIR / "historical_data.json"
    if default_data.exists() and args.info:
        loader.load_from_file(str(default_data))
        print("\n" + loader.summary())
        return

    # Fetch from specified source
    count = 0

    if args.api:
        count = asyncio.run(fetch_from_api(loader, args.markets))

    elif args.kaggle:
        count = load_from_kaggle(loader, args.kaggle, max_markets=args.markets)

    elif args.csv:
        count = loader.load_kaggle_csv(args.csv)

    else:
        print("Specify a data source: --api, --kaggle <path>, or --csv <path>")
        print("\nTo download Kaggle dataset:")
        print("  1. Visit: https://www.kaggle.com/datasets/sandeepkumarfromin/full-market-data-from-polymarket")
        print("  2. Download the ZIP file")
        print("  3. Run: python fetch_data.py --kaggle /path/to/archive.zip")
        return

    if count == 0:
        print("\nNo data loaded")
        return

    # Print summary
    print("\n" + "=" * 60)
    print("  DATA SUMMARY")
    print("=" * 60)
    print(loader.summary())

    # Save if requested
    if args.save:
        loader.save_to_file(args.save)
        print(f"\nSaved to: {args.save}")
    else:
        # Save to default location
        default_save = loader.DATA_DIR / "historical_data.json"
        loader.save_to_file(str(default_save))
        print(f"\nSaved to: {default_save}")

    print("\nTo run backtest with this data:")
    print(f"  python run_backtest.py --data {default_save}")


if __name__ == "__main__":
    main()
