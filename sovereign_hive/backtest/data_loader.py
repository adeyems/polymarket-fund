#!/usr/bin/env python3
"""
DATA LOADER - Historical Market Data
=====================================
Loads and manages historical market data for backtesting.

Data sources:
1. Polymarket CLOB API (official historical data)
2. Kaggle dataset (3,385 markets with price history)
3. Synthetic data generation (for testing)
4. CSV/JSON file imports
"""

import asyncio
import aiohttp
import bisect
import json
import random
import zipfile
import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
import math


@dataclass
class PricePoint:
    """Single price observation."""
    timestamp: datetime
    price: float
    volume: float = 0.0
    bid: float = 0.0
    ask: float = 0.0


@dataclass
class MarketSnapshot:
    """Full market state at a point in time."""
    condition_id: str
    question: str
    price: float
    bid: float
    ask: float
    volume_24h: float
    price_change_24h: float
    volatility: float
    days_to_resolve: float
    resolution: Optional[str] = None


@dataclass
class MarketHistory:
    """Historical data for a single market."""
    condition_id: str
    question: str
    prices: List[PricePoint] = field(default_factory=list)
    resolution: Optional[str] = None  # "YES", "NO", or None if unresolved
    resolution_time: Optional[datetime] = None
    _timestamps: List[datetime] = field(default_factory=list, repr=False)

    def get_price_at(self, timestamp: datetime) -> Optional[float]:
        """Get price at or before a timestamp using binary search."""
        if not self.prices:
            return None
        if not self._timestamps:
            self._timestamps = [p.timestamp for p in self.prices]
        idx = bisect.bisect_right(self._timestamps, timestamp) - 1
        if idx < 0:
            return self.prices[0].price
        return self.prices[idx].price

    def get_point_at(self, timestamp: datetime) -> Optional['PricePoint']:
        """Get full PricePoint at or before a timestamp using binary search."""
        if not self.prices:
            return None
        if not self._timestamps:
            self._timestamps = [p.timestamp for p in self.prices]
        idx = bisect.bisect_right(self._timestamps, timestamp) - 1
        if idx < 0:
            return self.prices[0]
        return self.prices[idx]

    def get_price_change(self, timestamp: datetime, lookback_hours: int = 24) -> Optional[float]:
        """Get percentage price change over lookback period."""
        current = self.get_price_at(timestamp)
        past = self.get_price_at(timestamp - timedelta(hours=lookback_hours))
        if current is None or past is None or past <= 0:
            return None
        return (current - past) / past

    def get_volatility(self, timestamp: datetime, lookback_hours: int = 24) -> float:
        """Get price volatility over lookback period."""
        if not self.prices or not self._timestamps:
            if not self._timestamps and self.prices:
                self._timestamps = [p.timestamp for p in self.prices]
            else:
                return 0.0
        start = timestamp - timedelta(hours=lookback_hours)
        start_idx = max(0, bisect.bisect_left(self._timestamps, start))
        end_idx = bisect.bisect_right(self._timestamps, timestamp)
        window = self.prices[start_idx:end_idx]
        if len(window) < 2:
            return 0.0
        returns = []
        for i in range(1, len(window)):
            if window[i-1].price > 0:
                returns.append((window[i].price - window[i-1].price) / window[i-1].price)
        if not returns:
            return 0.0
        mean_r = sum(returns) / len(returns)
        var = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        return math.sqrt(var)

    def get_final_price(self) -> float:
        """Get resolution price (1.0 for YES, 0.0 for NO)."""
        if self.resolution == "YES":
            return 1.0
        elif self.resolution == "NO":
            return 0.0
        return self.prices[-1].price if self.prices else 0.5


class DataLoader:
    """
    Loads and manages historical market data.

    Supports multiple data sources:
    - JSON files from data collection
    - Synthetic data generation for testing
    - Live API snapshots
    """

    DATA_DIR = Path(__file__).parent.parent / "data" / "backtest"

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.markets: Dict[str, MarketHistory] = {}

    def load_from_file(self, filepath: str) -> int:
        """
        Load historical data from JSON file.

        Returns number of markets loaded.
        """
        path = Path(filepath)
        if not path.exists():
            return 0

        with open(path, "r") as f:
            data = json.load(f)

        count = 0
        for market_data in data.get("markets", []):
            history = self._parse_market_data(market_data)
            if history and history.prices:
                self.markets[history.condition_id] = history
                count += 1

        return count

    def _parse_market_data(self, data: dict) -> Optional[MarketHistory]:
        """Parse market data from JSON format."""
        condition_id = data.get("condition_id") or data.get("conditionId")
        if not condition_id:
            return None

        history = MarketHistory(
            condition_id=condition_id,
            question=data.get("question", "Unknown"),
            resolution=data.get("resolution"),
        )

        # Parse price history
        for p in data.get("prices", []):
            try:
                ts = datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
                history.prices.append(PricePoint(
                    timestamp=ts,
                    price=float(p["price"]),
                    volume=float(p.get("volume", 0)),
                    bid=float(p.get("bid", p["price"])),
                    ask=float(p.get("ask", p["price"])),
                ))
            except (KeyError, ValueError):
                continue

        if data.get("resolution_time"):
            try:
                history.resolution_time = datetime.fromisoformat(
                    data["resolution_time"].replace("Z", "+00:00")
                )
            except ValueError:
                pass

        return history

    def generate_synthetic(
        self,
        num_markets: int = 50,
        days: int = 30,
        interval_hours: int = 1
    ) -> int:
        """
        Generate synthetic market data for testing.

        Creates realistic price movements with:
        - Mean reversion
        - Volatility clustering
        - Resolution drift (prices move toward final outcome)

        Returns number of markets generated.
        """
        start_time = datetime.now(timezone.utc) - timedelta(days=days)
        num_points = (days * 24) // interval_hours

        for i in range(num_markets):
            condition_id = f"0xsynthetic_{i:04d}"

            # Random initial price between 0.10 and 0.90
            initial_price = random.uniform(0.20, 0.80)

            # Random resolution (weighted toward initial price direction)
            resolution = "YES" if random.random() < initial_price else "NO"
            final_price = 1.0 if resolution == "YES" else 0.0

            # Generate price path
            prices = self._generate_price_path(
                initial_price=initial_price,
                final_price=final_price,
                num_points=num_points,
                start_time=start_time,
                interval_hours=interval_hours
            )

            history = MarketHistory(
                condition_id=condition_id,
                question=f"Synthetic Market {i+1}: Will event occur?",
                prices=prices,
                resolution=resolution,
                resolution_time=prices[-1].timestamp if prices else None
            )

            self.markets[condition_id] = history

        return num_markets

    def _generate_price_path(
        self,
        initial_price: float,
        final_price: float,
        num_points: int,
        start_time: datetime,
        interval_hours: int
    ) -> List[PricePoint]:
        """Generate a realistic price path using geometric Brownian motion."""
        prices = []
        price = initial_price

        # Parameters
        volatility = random.uniform(0.02, 0.08)  # Daily volatility
        mean_reversion = 0.1  # Pull toward final price

        for i in range(num_points):
            timestamp = start_time + timedelta(hours=i * interval_hours)

            # Progress toward resolution (0 to 1)
            progress = i / max(num_points - 1, 1)

            # Target price drifts toward final price
            target = initial_price + (final_price - initial_price) * progress

            # Random walk with mean reversion
            drift = mean_reversion * (target - price)
            noise = random.gauss(0, volatility) * math.sqrt(interval_hours / 24)

            price = price + drift + noise
            price = max(0.01, min(0.99, price))  # Keep in bounds

            # Final point snaps to resolution
            if i == num_points - 1:
                price = final_price

            # Generate bid/ask spread
            spread = random.uniform(0.01, 0.03)
            bid = max(0.01, price - spread / 2)
            ask = min(0.99, price + spread / 2)

            prices.append(PricePoint(
                timestamp=timestamp,
                price=price,
                volume=random.uniform(1000, 50000),
                bid=bid,
                ask=ask
            ))

        return prices

    def get_market(self, condition_id: str) -> Optional[MarketHistory]:
        """Get market history by condition ID."""
        return self.markets.get(condition_id)

    def get_all_markets(self) -> List[MarketHistory]:
        """Get all loaded markets."""
        return list(self.markets.values())

    def get_markets_active_at(self, timestamp: datetime) -> List[MarketHistory]:
        """Get markets that were active (unresolved) at a given time."""
        active = []
        for market in self.markets.values():
            if market.prices:
                start = market.prices[0].timestamp
                end = market.resolution_time or market.prices[-1].timestamp
                if start <= timestamp <= end:
                    active.append(market)
        return active

    def save_to_file(self, filepath: str):
        """Save loaded data to JSON file."""
        data = {"markets": []}

        for market in self.markets.values():
            market_data = {
                "condition_id": market.condition_id,
                "question": market.question,
                "resolution": market.resolution,
                "resolution_time": market.resolution_time.isoformat() if market.resolution_time else None,
                "prices": [
                    {
                        "timestamp": p.timestamp.isoformat(),
                        "price": p.price,
                        "volume": p.volume,
                        "bid": p.bid,
                        "ask": p.ask
                    }
                    for p in market.prices
                ]
            }
            data["markets"].append(market_data)

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    def get_time_range(self) -> tuple:
        """Get the overall time range of loaded data."""
        if not self.markets:
            return None, None

        min_time = None
        max_time = None

        for market in self.markets.values():
            if market.prices:
                start = market.prices[0].timestamp
                end = market.prices[-1].timestamp
                if min_time is None or start < min_time:
                    min_time = start
                if max_time is None or end > max_time:
                    max_time = end

        return min_time, max_time

    def summary(self) -> str:
        """Get summary of loaded data."""
        if not self.markets:
            return "No data loaded"

        min_time, max_time = self.get_time_range()
        resolved = sum(1 for m in self.markets.values() if m.resolution)
        yes_wins = sum(1 for m in self.markets.values() if m.resolution == "YES")

        return (
            f"Markets: {len(self.markets)}\n"
            f"Resolved: {resolved} ({yes_wins} YES, {resolved - yes_wins} NO)\n"
            f"Time range: {min_time.strftime('%Y-%m-%d')} to {max_time.strftime('%Y-%m-%d')}\n"
            f"Duration: {(max_time - min_time).days} days"
        )

    def enrich_synthetic_fields(self):
        """Add synthetic bid/ask/volume to all markets missing them."""
        for market in self.markets.values():
            for i, p in enumerate(market.prices):
                if p.bid == 0 and p.ask == 0:
                    # Spread varies: tighter near 0.50, wider at extremes
                    distance_from_mid = abs(p.price - 0.50)
                    base_spread = 0.01 + distance_from_mid * 0.04  # 1-3% spread
                    spread = base_spread * random.uniform(0.8, 1.2)
                    p.bid = max(0.001, p.price - spread / 2)
                    p.ask = min(0.999, p.price + spread / 2)

                if p.volume == 0 and i > 0:
                    # Volume from price velocity
                    prev = market.prices[i - 1]
                    velocity = abs(p.price - prev.price) if prev else 0
                    base_vol = 5000 + velocity * 500000  # More movement = more volume
                    p.volume = base_vol * random.uniform(0.5, 2.0)
                elif p.volume == 0:
                    p.volume = random.uniform(2000, 10000)

            # Rebuild timestamp index
            market._timestamps = [p.timestamp for p in market.prices]

    def get_snapshot(self, market: MarketHistory, timestamp: datetime) -> Optional[MarketSnapshot]:
        """Get a full market snapshot at a point in time."""
        point = market.get_point_at(timestamp)
        if point is None:
            return None

        price_change = market.get_price_change(timestamp, 24) or 0.0
        vol = market.get_volatility(timestamp, 24)

        # Estimate days to resolve
        days_to_resolve = 365.0
        if market.resolution_time:
            remaining = (market.resolution_time - timestamp).total_seconds() / 86400
            days_to_resolve = max(1.0, remaining)

        # Estimate 24h volume from nearby points
        if not market._timestamps:
            market._timestamps = [p.timestamp for p in market.prices]
        start_24h = timestamp - timedelta(hours=24)
        s_idx = max(0, bisect.bisect_left(market._timestamps, start_24h))
        e_idx = bisect.bisect_right(market._timestamps, timestamp)
        vol_24h = sum(market.prices[i].volume for i in range(s_idx, e_idx))

        return MarketSnapshot(
            condition_id=market.condition_id,
            question=market.question,
            price=point.price,
            bid=point.bid if point.bid > 0 else max(0.001, point.price - 0.01),
            ask=point.ask if point.ask > 0 else min(0.999, point.price + 0.01),
            volume_24h=vol_24h,
            price_change_24h=price_change,
            volatility=vol,
            days_to_resolve=days_to_resolve,
            resolution=market.resolution,
        )

    def preprocess_kaggle_to_cache(
        self,
        zip_path: str = None,
        cache_path: str = None,
        min_price_points: int = 100,
        max_markets: int = None,
    ) -> int:
        """
        Convert Kaggle ZIP to fast JSON cache with enrichment.

        Filters to markets with sufficient history and adds synthetic fields.
        Returns number of cached markets.
        """
        zip_path = zip_path or str(self.DATA_DIR / "full-market-data-from-polymarket.zip")
        cache_path = cache_path or str(self.DATA_DIR / "kaggle_cache.json")

        cache_file = Path(cache_path)
        if cache_file.exists():
            print(f"Cache exists: {cache_path}")
            return self._load_cache(cache_path)

        print(f"Building cache from {zip_path}...")
        count = self.load_kaggle_dataset(zip_path, max_markets=max_markets)

        # Filter by minimum price points
        before = len(self.markets)
        to_remove = [
            cid for cid, m in self.markets.items()
            if len(m.prices) < min_price_points
        ]
        for cid in to_remove:
            del self.markets[cid]
        print(f"Filtered: {before} → {len(self.markets)} markets (>={min_price_points} points)")

        # Enrich with synthetic fields
        self.enrich_synthetic_fields()

        # Save cache
        self.save_to_file(cache_path)
        print(f"Cache saved: {cache_path} ({len(self.markets)} markets)")
        return len(self.markets)

    def _load_cache(self, cache_path: str) -> int:
        """Load from preprocessed cache file."""
        print(f"Loading cache: {cache_path}...")
        count = self.load_from_file(cache_path)
        # Rebuild timestamp indices
        for market in self.markets.values():
            market._timestamps = [p.timestamp for p in market.prices]
        print(f"Loaded {count} markets from cache")
        return count

    def get_resolved_markets(self) -> List[MarketHistory]:
        """Get markets with known resolution."""
        return [m for m in self.markets.values() if m.resolution is not None]

    def get_markets_by_duration(self, min_days: int = 7, max_days: int = 90) -> List[MarketHistory]:
        """Get markets within a duration range."""
        result = []
        for m in self.markets.values():
            if len(m.prices) >= 2:
                duration = (m.prices[-1].timestamp - m.prices[0].timestamp).days
                if min_days <= duration <= max_days:
                    result.append(m)
        return result

    # ================================================================
    # POLYMARKET API INTEGRATION
    # ================================================================

    CLOB_API = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"

    async def fetch_from_api(
        self,
        token_ids: List[str],
        interval: str = "max",
        fidelity: int = 60
    ) -> int:
        """
        Fetch historical price data from Polymarket CLOB API.

        Args:
            token_ids: List of CLOB token IDs to fetch
            interval: Time interval - "1m", "1h", "6h", "1d", "1w", "max"
            fidelity: Data resolution in minutes

        Returns:
            Number of markets fetched successfully
        """
        count = 0
        async with aiohttp.ClientSession() as session:
            for token_id in token_ids:
                try:
                    history = await self._fetch_price_history(
                        session, token_id, interval, fidelity
                    )
                    if history and history.prices:
                        self.markets[history.condition_id] = history
                        count += 1
                        print(f"  Fetched: {token_id[:16]}... ({len(history.prices)} points)")
                except Exception as e:
                    print(f"  Error fetching {token_id[:16]}...: {e}")

        return count

    async def _fetch_price_history(
        self,
        session: aiohttp.ClientSession,
        token_id: str,
        interval: str,
        fidelity: int
    ) -> Optional[MarketHistory]:
        """Fetch price history for a single token."""
        url = f"{self.CLOB_API}/prices-history"
        params = {
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity
        }

        async with session.get(url, params=params, timeout=30) as resp:
            if resp.status != 200:
                return None

            data = await resp.json()
            history_data = data.get("history", [])

            if not history_data:
                return None

            prices = []
            for point in history_data:
                ts = datetime.fromtimestamp(point["t"], tz=timezone.utc)
                price = float(point["p"])
                prices.append(PricePoint(timestamp=ts, price=price))

            # Sort by timestamp
            prices.sort(key=lambda x: x.timestamp)

            return MarketHistory(
                condition_id=token_id,
                question=f"Market {token_id[:16]}...",
                prices=prices
            )

    async def fetch_active_markets(self, limit: int = 50) -> List[dict]:
        """
        Fetch list of active markets from Gamma API, sorted by volume.

        Returns list of market dicts with conditionId, question, clobTokenIds
        """
        async with aiohttp.ClientSession() as session:
            url = f"{self.GAMMA_API}/markets"
            params = {
                "limit": limit,
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false"
            }

            async with session.get(url, params=params, timeout=30) as resp:
                if resp.status != 200:
                    return []
                return await resp.json()

    async def fetch_resolved_markets(self, limit: int = 100) -> List[dict]:
        """Fetch recently resolved markets for backtesting."""
        async with aiohttp.ClientSession() as session:
            url = f"{self.GAMMA_API}/markets"
            params = {
                "limit": limit,
                "closed": "true",
                "order": "volume",
                "ascending": "false"
            }

            async with session.get(url, params=params, timeout=30) as resp:
                if resp.status != 200:
                    return []
                return await resp.json()

    async def build_dataset_from_api(
        self,
        num_markets: int = 50,
        include_resolved: bool = False
    ) -> int:
        """
        Build a dataset by fetching from Polymarket API.

        Args:
            num_markets: Number of markets to fetch
            include_resolved: Use resolved markets (may have less price history)

        Returns:
            Number of markets loaded
        """
        print(f"Fetching market list from Polymarket API...")

        # Get active markets by default (they have price history available)
        if include_resolved:
            markets = await self.fetch_resolved_markets(limit=num_markets * 2)
        else:
            markets = await self.fetch_active_markets(limit=num_markets * 2)

        if not markets:
            print("No markets found")
            return 0

        print(f"Found {len(markets)} markets, fetching price history...")

        # Extract token IDs and fetch history
        count = 0
        for market in markets[:num_markets]:
            token_ids_raw = market.get("clobTokenIds", [])
            question = market.get("question", "Unknown")
            outcome = market.get("outcome", None)

            # Parse token IDs - API returns JSON string like '["123", "456"]'
            if isinstance(token_ids_raw, str):
                try:
                    token_ids = json.loads(token_ids_raw)
                except json.JSONDecodeError:
                    token_ids = []
            else:
                token_ids = token_ids_raw or []

            if not token_ids:
                continue

            # Fetch YES token (first token)
            token_id = token_ids[0]

            try:
                async with aiohttp.ClientSession() as session:
                    history = await self._fetch_price_history(
                        session, token_id, "max", 60
                    )

                    if history and history.prices:
                        history.question = question[:80]
                        history.condition_id = market.get("conditionId", token_id)

                        # Set resolution if market is closed
                        if outcome:
                            history.resolution = "YES" if outcome == "Yes" else "NO"
                            history.resolution_time = history.prices[-1].timestamp

                        self.markets[history.condition_id] = history
                        count += 1
                        print(f"  [{count}/{num_markets}] {question[:40]}...")

            except Exception as e:
                print(f"  Error: {e}")

            # Rate limiting
            await asyncio.sleep(0.2)

        return count

    # ================================================================
    # KAGGLE DATASET INTEGRATION
    # ================================================================

    def load_kaggle_dataset(self, zip_path: str, max_markets: int = None) -> int:
        """
        Load data from the Kaggle Polymarket dataset.

        Dataset: https://www.kaggle.com/datasets/sandeepkumarfromin/full-market-data-from-polymarket

        The dataset structure is:
        Polymarket_dataset/Polymarket_dataset/market=<condition_id>/price/token=<token_id>.ndjson

        Each .ndjson file contains space-separated JSON objects with price data.

        Args:
            zip_path: Path to downloaded Kaggle ZIP file
            max_markets: Maximum number of markets to load (None = all)

        Returns:
            Number of markets loaded
        """
        zip_path = Path(zip_path)
        if not zip_path.exists():
            print(f"Kaggle dataset not found: {zip_path}")
            return 0

        count = 0
        print(f"Loading Kaggle dataset from {zip_path}...")

        # Group price files by condition_id (market)
        market_files: Dict[str, List[str]] = {}

        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Find all .ndjson price files
            all_files = zf.namelist()
            price_files = [f for f in all_files if f.endswith('.ndjson') and '/price/' in f]

            # Also try legacy price.json format
            if not price_files:
                price_files = [f for f in all_files if f.endswith('price.json')]

            print(f"Found {len(price_files)} price files...")

            # Group by condition_id (market)
            for filepath in price_files:
                condition_id = self._extract_condition_id_from_path(filepath)
                if condition_id:
                    if condition_id not in market_files:
                        market_files[condition_id] = []
                    market_files[condition_id].append(filepath)

            total_markets = len(market_files)
            print(f"Found {total_markets} unique markets...")

            # Limit if requested
            market_ids = list(market_files.keys())
            if max_markets:
                market_ids = market_ids[:max_markets]

            # Process each market
            for condition_id in market_ids:
                try:
                    all_prices = []

                    # Load all price files for this market (YES and NO tokens)
                    for filepath in market_files[condition_id]:
                        with zf.open(filepath) as f:
                            content = f.read().decode('utf-8')
                            prices = self._parse_ndjson_prices(content, condition_id)
                            all_prices.extend(prices)

                    if all_prices:
                        # Sort by timestamp and remove duplicates
                        all_prices.sort(key=lambda x: x.timestamp)

                        # Keep only YES token prices (outcome_index=0 or first seen)
                        seen_times = set()
                        unique_prices = []
                        for p in all_prices:
                            ts_key = p.timestamp.isoformat()
                            if ts_key not in seen_times:
                                seen_times.add(ts_key)
                                unique_prices.append(p)

                        if unique_prices:
                            # Determine resolution from final price
                            final_price = unique_prices[-1].price
                            resolution = None
                            if final_price >= 0.95:
                                resolution = "YES"
                            elif final_price <= 0.05:
                                resolution = "NO"

                            history = MarketHistory(
                                condition_id=condition_id,
                                question=f"Market {condition_id[:16]}...",
                                prices=unique_prices,
                                resolution=resolution,
                                resolution_time=unique_prices[-1].timestamp if resolution else None
                            )
                            self.markets[condition_id] = history
                            count += 1

                            if count % 100 == 0:
                                print(f"  Loaded {count} markets...")

                except Exception as e:
                    continue  # Skip problematic markets

        print(f"Loaded {count} markets from Kaggle dataset")
        return count

    def _extract_condition_id_from_path(self, filepath: str) -> Optional[str]:
        """Extract condition_id from Kaggle dataset path."""
        # Pattern: .../market=<condition_id>/price/...
        import re
        match = re.search(r'market=([^/]+)', filepath)
        if match:
            return match.group(1)

        # Fallback: try extracting from directory structure
        parts = filepath.split('/')
        for i, part in enumerate(parts):
            if part.startswith('market='):
                return part.replace('market=', '')
            # Legacy format: condition_id/price.json
            if i < len(parts) - 1 and parts[i + 1] == 'price.json':
                return part

        return None

    def _parse_ndjson_prices(
        self,
        content: str,
        condition_id: str,
        yes_token_only: bool = True
    ) -> List[PricePoint]:
        """
        Parse space-separated JSON objects from NDJSON content.

        Format: {"token_id": "...", "outcome_index": 0, "t": 1234567890, "p": 0.56} {...}

        Args:
            content: Raw NDJSON content
            condition_id: Market condition ID
            yes_token_only: If True, only include YES token prices (outcome_index=0)
        """
        prices = []

        # Handle space-separated JSON objects
        # Split by "} {" and reassemble
        content = content.strip()
        if not content:
            return prices

        # Try splitting by "} {" (space-separated format)
        if '} {' in content:
            parts = content.split('} {')
            json_strings = []
            for i, part in enumerate(parts):
                if i == 0:
                    json_strings.append(part + '}')
                elif i == len(parts) - 1:
                    json_strings.append('{' + part)
                else:
                    json_strings.append('{' + part + '}')
        else:
            # Try newline-separated
            json_strings = [line.strip() for line in content.split('\n') if line.strip()]

        for json_str in json_strings:
            try:
                point = json.loads(json_str)

                # Filter by outcome_index if specified
                # outcome_index 0 = YES token, 1 = NO token
                if yes_token_only:
                    outcome_index = point.get('outcome_index')
                    if outcome_index is not None and outcome_index != 0:
                        continue  # Skip NO token prices

                # Extract timestamp and price
                ts_val = point.get('t')
                price_val = point.get('p')

                if ts_val is None or price_val is None:
                    continue

                # Parse timestamp (Unix timestamp)
                if isinstance(ts_val, (int, float)):
                    ts = datetime.fromtimestamp(ts_val, tz=timezone.utc)
                else:
                    continue

                # Only include prices in valid range
                price = float(price_val)
                if 0 <= price <= 1:
                    prices.append(PricePoint(
                        timestamp=ts,
                        price=price
                    ))

            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        return prices

    def _parse_kaggle_price_data(
        self,
        condition_id: str,
        price_data: list
    ) -> Optional[MarketHistory]:
        """Parse Kaggle price data format."""
        if not price_data:
            return None

        prices = []
        for point in price_data:
            try:
                # Kaggle format: {"timestamp": "...", "price": 0.xx}
                ts_str = point.get("timestamp") or point.get("t")
                price_val = point.get("price") or point.get("p")

                if ts_str is None or price_val is None:
                    continue

                # Parse timestamp
                if isinstance(ts_str, (int, float)):
                    ts = datetime.fromtimestamp(ts_str, tz=timezone.utc)
                else:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

                prices.append(PricePoint(
                    timestamp=ts,
                    price=float(price_val)
                ))

            except (ValueError, TypeError):
                continue

        if not prices:
            return None

        # Sort by timestamp
        prices.sort(key=lambda x: x.timestamp)

        # Determine resolution from final price
        final_price = prices[-1].price
        resolution = None
        if final_price >= 0.95:
            resolution = "YES"
        elif final_price <= 0.05:
            resolution = "NO"

        return MarketHistory(
            condition_id=condition_id,
            question=f"Market {condition_id[:16]}...",
            prices=prices,
            resolution=resolution,
            resolution_time=prices[-1].timestamp if resolution else None
        )

    def load_kaggle_csv(self, csv_path: str) -> int:
        """
        Load data from a Kaggle CSV export.

        Expected columns: condition_id, timestamp, price, [volume]
        """
        csv_path = Path(csv_path)
        if not csv_path.exists():
            print(f"CSV file not found: {csv_path}")
            return 0

        # Group by condition_id
        market_data: Dict[str, List[dict]] = {}

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                cid = row.get("condition_id") or row.get("market_id")
                if cid:
                    if cid not in market_data:
                        market_data[cid] = []
                    market_data[cid].append(row)

        count = 0
        for cid, rows in market_data.items():
            prices = []
            for row in rows:
                try:
                    ts_str = row.get("timestamp") or row.get("time")
                    price_val = row.get("price")

                    if isinstance(ts_str, (int, float)):
                        ts = datetime.fromtimestamp(float(ts_str), tz=timezone.utc)
                    else:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

                    prices.append(PricePoint(
                        timestamp=ts,
                        price=float(price_val),
                        volume=float(row.get("volume", 0))
                    ))
                except (ValueError, TypeError):
                    continue

            if prices:
                prices.sort(key=lambda x: x.timestamp)
                final_price = prices[-1].price
                resolution = "YES" if final_price >= 0.95 else ("NO" if final_price <= 0.05 else None)

                self.markets[cid] = MarketHistory(
                    condition_id=cid,
                    question=row.get("question", f"Market {cid[:16]}..."),
                    prices=prices,
                    resolution=resolution,
                    resolution_time=prices[-1].timestamp if resolution else None
                )
                count += 1

        print(f"Loaded {count} markets from CSV")
        return count
