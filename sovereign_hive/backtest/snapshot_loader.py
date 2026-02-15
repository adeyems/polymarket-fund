#!/usr/bin/env python3
"""
SNAPSHOT LOADER
================
Loads collected market snapshots (real bid/ask/volume data) from NDJSON files
written by the production scanner's _log_snapshot() method.

Data location: sovereign_hive/data/snapshots/YYYY-MM-DD.ndjson

Each line is a JSON object:
{
  "ts": "2026-02-14T12:00:00+00:00",
  "binance": {"BTCUSDT": 67000, ...},
  "markets": [
    {"id": "0x...", "q": "...", "bid": 0.45, "ask": 0.47, "vol24h": 50000, ...}
  ]
}

This module converts these snapshots into MarketHistory objects with REAL
bid/ask/volume data, suitable for backtesting spread-dependent strategies
(MARKET_MAKER, DUAL_SIDE_ARB, etc.)
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .data_loader import DataLoader, MarketHistory, PricePoint, MarketSnapshot


SNAPSHOT_DIR = Path(__file__).parent.parent / "data" / "snapshots"


def get_snapshot_files() -> List[Path]:
    """Get available snapshot files sorted by date."""
    if not SNAPSHOT_DIR.exists():
        return []
    files = sorted(SNAPSHOT_DIR.glob("*.ndjson"))
    return files


def count_snapshot_days() -> int:
    """How many days of snapshot data do we have?"""
    return len(get_snapshot_files())


def load_snapshots(
    min_days: int = 1,
    max_markets: int = None,
) -> Optional[DataLoader]:
    """
    Load collected snapshots into a DataLoader.

    Returns None if insufficient data (<min_days).
    """
    files = get_snapshot_files()
    if len(files) < min_days:
        return None

    loader = DataLoader()
    market_points: Dict[str, dict] = {}  # condition_id -> {question, prices}

    for filepath in files:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    snapshot = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts_str = snapshot.get("ts", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    continue

                for m in snapshot.get("markets", []):
                    cid = m.get("id", "")
                    if not cid:
                        continue

                    bid = float(m.get("bid", 0))
                    ask = float(m.get("ask", 0))
                    if bid <= 0 and ask <= 0:
                        continue

                    price = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)

                    if cid not in market_points:
                        market_points[cid] = {
                            "question": m.get("q", f"Market {cid[:16]}..."),
                            "end_date": m.get("end", ""),
                            "prices": [],
                        }

                    market_points[cid]["prices"].append(PricePoint(
                        timestamp=ts,
                        price=price,
                        volume=float(m.get("vol24h", 0)),
                        bid=bid,
                        ask=ask,
                    ))

    # Convert to MarketHistory objects
    count = 0
    for cid, data in market_points.items():
        if max_markets and count >= max_markets:
            break

        prices = data["prices"]
        if len(prices) < 2:
            continue

        # Sort and deduplicate by timestamp
        prices.sort(key=lambda p: p.timestamp)
        seen = set()
        unique = []
        for p in prices:
            key = p.timestamp.isoformat()
            if key not in seen:
                seen.add(key)
                unique.append(p)

        # Determine resolution from end date
        resolution = None
        resolution_time = None
        end_str = data.get("end_date", "")
        if end_str:
            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                if unique[-1].timestamp >= end_dt:
                    final = unique[-1].price
                    if final >= 0.95:
                        resolution = "YES"
                    elif final <= 0.05:
                        resolution = "NO"
                    resolution_time = end_dt
            except (ValueError, TypeError):
                pass

        history = MarketHistory(
            condition_id=cid,
            question=data["question"],
            prices=unique,
            resolution=resolution,
            resolution_time=resolution_time,
        )
        history._timestamps = [p.timestamp for p in unique]
        loader.markets[cid] = history
        count += 1

    if count == 0:
        return None

    return loader


def snapshot_summary() -> str:
    """Get summary of available snapshot data."""
    files = get_snapshot_files()
    if not files:
        return "No snapshot data collected yet. Start the simulation to begin collecting."

    days = len(files)
    first = files[0].stem
    last = files[-1].stem

    # Count total snapshots and markets
    total_lines = 0
    market_ids = set()
    for f in files:
        with open(f, "r") as fh:
            for line in fh:
                if line.strip():
                    total_lines += 1
                    try:
                        snap = json.loads(line)
                        for m in snap.get("markets", []):
                            if m.get("id"):
                                market_ids.add(m["id"])
                    except json.JSONDecodeError:
                        pass

    return (
        f"Snapshot data: {days} days ({first} to {last})\n"
        f"Total snapshots: {total_lines:,}\n"
        f"Unique markets: {len(market_ids):,}\n"
        f"Data points: ~{total_lines * len(market_ids) // max(1, total_lines):,} per snapshot\n"
        f"Has real bid/ask: YES"
    )
