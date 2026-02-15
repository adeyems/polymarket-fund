#!/usr/bin/env python3
"""
COMPREHENSIVE DATA LOADER TESTS
================================
Deep coverage tests for sovereign_hive/backtest/data_loader.py
Targets: 31% -> 90%+ coverage
"""

import pytest
import math
import json
import csv
import random
import io
import zipfile
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.backtest.data_loader import (
    DataLoader, MarketHistory, PricePoint, MarketSnapshot,
)


# ============================================================
# FIXTURES (all in-file, no conftest dependency)
# ============================================================

@pytest.fixture
def loader():
    """Fresh DataLoader instance."""
    return DataLoader()


@pytest.fixture
def sample_market():
    """MarketHistory with 48 hourly price points and sinusoidal pattern."""
    now = datetime.now(timezone.utc)
    prices = [
        PricePoint(
            timestamp=now - timedelta(hours=48 - i),
            price=0.50 + 0.01 * math.sin(i / 5),
            volume=random.uniform(5000, 20000),
            bid=0.49,
            ask=0.51,
        )
        for i in range(48)
    ]
    m = MarketHistory(
        condition_id="0xtest",
        question="Test?",
        prices=prices,
        resolution="YES",
        resolution_time=prices[-1].timestamp,
    )
    m._timestamps = [p.timestamp for p in prices]
    return m


@pytest.fixture
def loaded_loader():
    """DataLoader pre-loaded with 10 synthetic markets over 7 days."""
    dl = DataLoader()
    dl.generate_synthetic(num_markets=10, days=7)
    return dl


@pytest.fixture
def empty_market():
    """MarketHistory with zero prices."""
    return MarketHistory(condition_id="0xempty", question="Empty?", prices=[])


@pytest.fixture
def single_point_market():
    """MarketHistory with exactly one price point."""
    now = datetime.now(timezone.utc)
    p = PricePoint(timestamp=now, price=0.60, volume=1000, bid=0.59, ask=0.61)
    m = MarketHistory(
        condition_id="0xsingle",
        question="Single?",
        prices=[p],
        resolution=None,
    )
    m._timestamps = [p.timestamp]
    return m


@pytest.fixture
def no_bid_ask_market():
    """Market with bid=0, ask=0 on every point (needs enrichment)."""
    now = datetime.now(timezone.utc)
    prices = [
        PricePoint(
            timestamp=now - timedelta(hours=10 - i),
            price=0.40 + 0.02 * i,
            volume=0,
            bid=0,
            ask=0,
        )
        for i in range(10)
    ]
    m = MarketHistory(condition_id="0xbare", question="Bare?", prices=prices)
    m._timestamps = [p.timestamp for p in prices]
    return m


# ============================================================
# 1. MarketHistory.get_point_at()
# ============================================================

class TestGetPointAt:
    """Tests for MarketHistory.get_point_at()."""

    def test_returns_pricepoint_at_exact_time(self, sample_market):
        ts = sample_market.prices[10].timestamp
        pt = sample_market.get_point_at(ts)
        assert isinstance(pt, PricePoint)
        assert pt.timestamp == ts

    def test_returns_nearest_before(self, sample_market):
        ts = sample_market.prices[10].timestamp + timedelta(minutes=30)
        pt = sample_market.get_point_at(ts)
        assert pt.timestamp == sample_market.prices[10].timestamp

    def test_returns_none_when_empty(self, empty_market):
        now = datetime.now(timezone.utc)
        assert empty_market.get_point_at(now) is None

    def test_returns_first_point_before_first_timestamp(self, sample_market):
        early = sample_market.prices[0].timestamp - timedelta(days=30)
        pt = sample_market.get_point_at(early)
        assert pt == sample_market.prices[0]

    def test_returns_last_point_after_last_timestamp(self, sample_market):
        late = sample_market.prices[-1].timestamp + timedelta(days=30)
        pt = sample_market.get_point_at(late)
        assert pt == sample_market.prices[-1]

    def test_rebuilds_timestamps_if_missing(self):
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now - timedelta(hours=i), price=0.5)
                  for i in range(5, 0, -1)]
        m = MarketHistory(condition_id="0x", question="Q", prices=prices)
        m._timestamps = []  # force empty
        pt = m.get_point_at(now)
        assert pt is not None
        assert len(m._timestamps) == 5


# ============================================================
# 2. MarketHistory.get_price_change()
# ============================================================

class TestGetPriceChange:
    """Tests for MarketHistory.get_price_change()."""

    def test_positive_change(self, sample_market):
        ts = sample_market.prices[-1].timestamp
        change = sample_market.get_price_change(ts, lookback_hours=24)
        assert change is not None
        assert isinstance(change, float)

    def test_none_when_empty(self, empty_market):
        now = datetime.now(timezone.utc)
        assert empty_market.get_price_change(now) is None

    def test_returns_float_for_normal_data(self, sample_market):
        ts = sample_market.prices[30].timestamp
        change = sample_market.get_price_change(ts, lookback_hours=12)
        assert isinstance(change, float)

    def test_change_is_zero_for_flat_prices(self):
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(timestamp=now - timedelta(hours=48 - i), price=0.50)
            for i in range(48)
        ]
        m = MarketHistory(condition_id="0xflat", question="Flat?", prices=prices)
        m._timestamps = [p.timestamp for p in prices]
        change = m.get_price_change(prices[-1].timestamp, lookback_hours=24)
        assert change == 0.0

    def test_negative_change(self):
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(timestamp=now - timedelta(hours=2), price=0.80),
            PricePoint(timestamp=now, price=0.40),
        ]
        m = MarketHistory(condition_id="0xdrop", question="Drop?", prices=prices)
        m._timestamps = [p.timestamp for p in prices]
        change = m.get_price_change(now, lookback_hours=4)
        assert change is not None
        assert change < 0


# ============================================================
# 3. MarketHistory.get_volatility()
# ============================================================

class TestGetVolatility:
    """Tests for MarketHistory.get_volatility()."""

    def test_with_window(self, sample_market):
        ts = sample_market.prices[-1].timestamp
        vol = sample_market.get_volatility(ts, lookback_hours=24)
        assert vol >= 0.0

    def test_empty_returns_zero(self, empty_market):
        now = datetime.now(timezone.utc)
        assert empty_market.get_volatility(now) == 0.0

    def test_single_point_returns_zero(self, single_point_market):
        ts = single_point_market.prices[0].timestamp
        assert single_point_market.get_volatility(ts) == 0.0

    def test_rebuilds_timestamps_when_missing(self):
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(timestamp=now - timedelta(hours=10 - i), price=0.50 + 0.05 * i)
            for i in range(10)
        ]
        m = MarketHistory(condition_id="0x", question="Q", prices=prices)
        m._timestamps = []  # force empty
        vol = m.get_volatility(now, lookback_hours=24)
        assert vol >= 0.0
        assert len(m._timestamps) == 10

    def test_volatility_higher_for_volatile_data(self):
        now = datetime.now(timezone.utc)
        stable_prices = [
            PricePoint(timestamp=now - timedelta(hours=10 - i), price=0.50)
            for i in range(10)
        ]
        volatile_prices = [
            PricePoint(timestamp=now - timedelta(hours=10 - i),
                       price=0.50 + 0.10 * ((-1) ** i))
            for i in range(10)
        ]
        ms = MarketHistory(condition_id="0xs", question="S", prices=stable_prices)
        ms._timestamps = [p.timestamp for p in stable_prices]
        mv = MarketHistory(condition_id="0xv", question="V", prices=volatile_prices)
        mv._timestamps = [p.timestamp for p in volatile_prices]

        vol_s = ms.get_volatility(now, 24)
        vol_v = mv.get_volatility(now, 24)
        assert vol_v > vol_s

    def test_volatility_zero_with_zero_prices(self):
        """If prior prices are 0, returns in that range should be skipped."""
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(timestamp=now - timedelta(hours=2), price=0.0),
            PricePoint(timestamp=now - timedelta(hours=1), price=0.50),
            PricePoint(timestamp=now, price=0.60),
        ]
        m = MarketHistory(condition_id="0xz", question="Z", prices=prices)
        m._timestamps = [p.timestamp for p in prices]
        vol = m.get_volatility(now, 24)
        # Only one valid return (0.50->0.60), variance of single item is 0
        assert vol == 0.0


# ============================================================
# 4. MarketHistory.get_final_price()
# ============================================================

class TestGetFinalPrice:
    """Tests for MarketHistory.get_final_price()."""

    def test_yes_resolution(self):
        m = MarketHistory(condition_id="0x1", question="Q", resolution="YES",
                          prices=[PricePoint(datetime.now(timezone.utc), 0.95)])
        assert m.get_final_price() == 1.0

    def test_no_resolution(self):
        m = MarketHistory(condition_id="0x2", question="Q", resolution="NO",
                          prices=[PricePoint(datetime.now(timezone.utc), 0.05)])
        assert m.get_final_price() == 0.0

    def test_unresolved_returns_last_price(self):
        m = MarketHistory(
            condition_id="0x3", question="Q", resolution=None,
            prices=[PricePoint(datetime.now(timezone.utc), 0.42)])
        assert m.get_final_price() == 0.42

    def test_unresolved_no_prices_returns_half(self, empty_market):
        assert empty_market.get_final_price() == 0.5


# ============================================================
# 5. DataLoader.enrich_synthetic_fields()
# ============================================================

class TestEnrichSyntheticFields:
    """Tests for DataLoader.enrich_synthetic_fields()."""

    def test_adds_bid_ask_when_zero(self, loader, no_bid_ask_market):
        loader.markets["0xbare"] = no_bid_ask_market
        loader.enrich_synthetic_fields()
        for p in no_bid_ask_market.prices:
            assert p.bid > 0
            assert p.ask > 0
            assert p.bid < p.ask

    def test_adds_volume_from_velocity(self, loader, no_bid_ask_market):
        loader.markets["0xbare"] = no_bid_ask_market
        loader.enrich_synthetic_fields()
        for i, p in enumerate(no_bid_ask_market.prices):
            assert p.volume > 0

    def test_first_point_volume_gets_random(self, loader, no_bid_ask_market):
        loader.markets["0xbare"] = no_bid_ask_market
        loader.enrich_synthetic_fields()
        assert no_bid_ask_market.prices[0].volume > 0

    def test_rebuilds_timestamps(self, loader, no_bid_ask_market):
        no_bid_ask_market._timestamps = []
        loader.markets["0xbare"] = no_bid_ask_market
        loader.enrich_synthetic_fields()
        assert len(no_bid_ask_market._timestamps) == len(no_bid_ask_market.prices)

    def test_does_not_clobber_existing_bid_ask(self, loader, sample_market):
        loader.markets["0xtest"] = sample_market
        orig_bid = sample_market.prices[0].bid
        orig_ask = sample_market.prices[0].ask
        loader.enrich_synthetic_fields()
        assert sample_market.prices[0].bid == orig_bid
        assert sample_market.prices[0].ask == orig_ask


# ============================================================
# 6. DataLoader.get_snapshot()
# ============================================================

class TestGetSnapshot:
    """Tests for DataLoader.get_snapshot()."""

    def test_valid_snapshot(self, loader, sample_market):
        ts = sample_market.prices[24].timestamp
        snap = loader.get_snapshot(sample_market, ts)
        assert isinstance(snap, MarketSnapshot)
        assert snap.condition_id == "0xtest"
        assert snap.question == "Test?"
        assert snap.resolution == "YES"

    def test_none_when_empty(self, loader, empty_market):
        now = datetime.now(timezone.utc)
        assert loader.get_snapshot(empty_market, now) is None

    def test_volume_24h_calculation(self, loader, sample_market):
        ts = sample_market.prices[-1].timestamp
        snap = loader.get_snapshot(sample_market, ts)
        assert snap.volume_24h > 0

    def test_days_to_resolve_with_resolution_time(self, loader, sample_market):
        ts = sample_market.prices[0].timestamp
        snap = loader.get_snapshot(sample_market, ts)
        assert snap.days_to_resolve >= 1.0

    def test_days_to_resolve_default_without_resolution_time(self, loader):
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(timestamp=now - timedelta(hours=1), price=0.50, volume=100),
            PricePoint(timestamp=now, price=0.55, volume=200),
        ]
        m = MarketHistory(
            condition_id="0xnores", question="Q",
            prices=prices, resolution=None, resolution_time=None,
        )
        m._timestamps = [p.timestamp for p in prices]
        snap = loader.get_snapshot(m, now)
        assert snap.days_to_resolve == 365.0

    def test_snapshot_uses_fallback_bid_ask(self, loader):
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(timestamp=now, price=0.50, volume=100, bid=0, ask=0),
        ]
        m = MarketHistory(condition_id="0xnoba", question="Q", prices=prices)
        m._timestamps = [p.timestamp for p in prices]
        snap = loader.get_snapshot(m, now)
        assert snap.bid == pytest.approx(0.49, abs=0.01)
        assert snap.ask == pytest.approx(0.51, abs=0.01)

    def test_snapshot_rebuilds_timestamps(self, loader):
        now = datetime.now(timezone.utc)
        prices = [
            PricePoint(timestamp=now - timedelta(hours=1), price=0.50, volume=100,
                       bid=0.49, ask=0.51),
            PricePoint(timestamp=now, price=0.55, volume=200, bid=0.54, ask=0.56),
        ]
        m = MarketHistory(condition_id="0xrebuild", question="Q", prices=prices)
        m._timestamps = []  # force empty
        snap = loader.get_snapshot(m, now)
        assert snap is not None
        assert len(m._timestamps) == 2


# ============================================================
# 7. DataLoader.preprocess_kaggle_to_cache()
# ============================================================

class TestPreprocessKaggleToCache:
    """Tests for DataLoader.preprocess_kaggle_to_cache()."""

    def test_uses_existing_cache(self, loader, tmp_path):
        cache = tmp_path / "cache.json"
        # Write a valid cache file with a market that has enough points
        now = datetime.now(timezone.utc)
        market_data = {
            "markets": [{
                "condition_id": "0xcached",
                "question": "Cached?",
                "resolution": "YES",
                "resolution_time": now.isoformat(),
                "prices": [
                    {"timestamp": (now - timedelta(hours=i)).isoformat(),
                     "price": 0.50, "volume": 100, "bid": 0.49, "ask": 0.51}
                    for i in range(5, 0, -1)
                ],
            }],
        }
        cache.write_text(json.dumps(market_data))
        count = loader.preprocess_kaggle_to_cache(
            zip_path=str(tmp_path / "fake.zip"),
            cache_path=str(cache),
        )
        assert count == 1
        assert "0xcached" in loader.markets

    def test_builds_new_cache_and_filters(self, loader, tmp_path):
        cache_path = str(tmp_path / "new_cache.json")
        # Pre-populate loader with markets of varying point counts
        now = datetime.now(timezone.utc)
        for i in range(5):
            num_pts = 50 + i * 30  # 50,80,110,140,170
            prices = [
                PricePoint(
                    timestamp=now - timedelta(hours=num_pts - j),
                    price=0.50, volume=100, bid=0.49, ask=0.51,
                )
                for j in range(num_pts)
            ]
            loader.markets[f"0xm{i}"] = MarketHistory(
                condition_id=f"0xm{i}", question=f"M{i}",
                prices=prices, resolution="YES",
                resolution_time=prices[-1].timestamp,
            )

        # Patch load_kaggle_dataset to not actually need a zip
        with patch.object(loader, 'load_kaggle_dataset', return_value=5):
            count = loader.preprocess_kaggle_to_cache(
                zip_path=str(tmp_path / "fake.zip"),
                cache_path=cache_path,
                min_price_points=100,
            )
        # Markets with <100 points should be filtered
        for cid, m in loader.markets.items():
            assert len(m.prices) >= 100

    def test_filters_by_min_points(self, loader, tmp_path):
        cache_path = str(tmp_path / "filter_cache.json")
        now = datetime.now(timezone.utc)
        # One market with 10 points (below threshold), one with 200
        for num_pts, cid in [(10, "0xsmall"), (200, "0xlarge")]:
            prices = [
                PricePoint(
                    timestamp=now - timedelta(hours=num_pts - j),
                    price=0.50, volume=100, bid=0.49, ask=0.51,
                )
                for j in range(num_pts)
            ]
            loader.markets[cid] = MarketHistory(
                condition_id=cid, question="Q", prices=prices,
            )
        with patch.object(loader, 'load_kaggle_dataset', return_value=2):
            loader.preprocess_kaggle_to_cache(
                zip_path=str(tmp_path / "fake.zip"),
                cache_path=cache_path,
                min_price_points=100,
            )
        assert "0xsmall" not in loader.markets
        assert "0xlarge" in loader.markets


# ============================================================
# 8. DataLoader._load_cache()
# ============================================================

class TestLoadCache:
    """Tests for DataLoader._load_cache()."""

    def test_loads_and_rebuilds_timestamps(self, loader, tmp_path):
        cache = tmp_path / "cache.json"
        now = datetime.now(timezone.utc)
        market_data = {
            "markets": [{
                "condition_id": "0xc1",
                "question": "C1?",
                "resolution": None,
                "resolution_time": None,
                "prices": [
                    {"timestamp": (now - timedelta(hours=i)).isoformat(),
                     "price": 0.50, "volume": 100, "bid": 0.49, "ask": 0.51}
                    for i in range(5, 0, -1)
                ],
            }],
        }
        cache.write_text(json.dumps(market_data))
        count = loader._load_cache(str(cache))
        assert count == 1
        m = loader.markets["0xc1"]
        assert len(m._timestamps) == 5
        assert m._timestamps[0] < m._timestamps[-1]


# ============================================================
# 9. DataLoader.get_resolved_markets()
# ============================================================

class TestGetResolvedMarkets:
    """Tests for DataLoader.get_resolved_markets()."""

    def test_filters_resolved(self, loaded_loader):
        resolved = loaded_loader.get_resolved_markets()
        for m in resolved:
            assert m.resolution is not None

    def test_excludes_unresolved(self, loader):
        now = datetime.now(timezone.utc)
        prices = [PricePoint(timestamp=now, price=0.50)]
        loader.markets["0xr"] = MarketHistory(
            condition_id="0xr", question="R?", prices=prices, resolution="YES")
        loader.markets["0xu"] = MarketHistory(
            condition_id="0xu", question="U?", prices=prices, resolution=None)
        resolved = loader.get_resolved_markets()
        ids = [m.condition_id for m in resolved]
        assert "0xr" in ids
        assert "0xu" not in ids


# ============================================================
# 10. DataLoader.get_markets_by_duration()
# ============================================================

class TestGetMarketsByDuration:
    """Tests for DataLoader.get_markets_by_duration()."""

    def test_min_max_days_filtering(self, loader):
        now = datetime.now(timezone.utc)
        # 3-day market
        p3 = [PricePoint(timestamp=now - timedelta(days=3), price=0.50),
              PricePoint(timestamp=now, price=0.60)]
        # 10-day market
        p10 = [PricePoint(timestamp=now - timedelta(days=10), price=0.50),
               PricePoint(timestamp=now, price=0.60)]
        # 60-day market
        p60 = [PricePoint(timestamp=now - timedelta(days=60), price=0.50),
               PricePoint(timestamp=now, price=0.60)]
        loader.markets["0x3d"] = MarketHistory(condition_id="0x3d", question="3d", prices=p3)
        loader.markets["0x10d"] = MarketHistory(condition_id="0x10d", question="10d", prices=p10)
        loader.markets["0x60d"] = MarketHistory(condition_id="0x60d", question="60d", prices=p60)

        result = loader.get_markets_by_duration(min_days=7, max_days=30)
        ids = [m.condition_id for m in result]
        assert "0x10d" in ids
        assert "0x3d" not in ids
        assert "0x60d" not in ids

    def test_single_point_excluded(self, loader, single_point_market):
        loader.markets["0xsingle"] = single_point_market
        result = loader.get_markets_by_duration(min_days=0, max_days=365)
        assert len(result) == 0  # single point => len < 2


# ============================================================
# 11. DataLoader.get_time_range()
# ============================================================

class TestGetTimeRange:
    """Tests for DataLoader.get_time_range()."""

    def test_empty_returns_none_tuple(self, loader):
        assert loader.get_time_range() == (None, None)

    def test_with_data(self, loaded_loader):
        min_t, max_t = loaded_loader.get_time_range()
        assert min_t is not None
        assert max_t is not None
        assert min_t < max_t


# ============================================================
# 12. DataLoader.load_kaggle_dataset()
# ============================================================

class TestLoadKaggleDataset:
    """Tests for DataLoader.load_kaggle_dataset() using mock zipfile."""

    def test_nonexistent_zip_returns_zero(self, loader, tmp_path):
        count = loader.load_kaggle_dataset(str(tmp_path / "does_not_exist.zip"))
        assert count == 0

    def test_loads_from_mock_zip(self, loader, tmp_path):
        """Create a real in-memory ZIP with ndjson content."""
        zip_path = tmp_path / "kaggle.zip"
        now_ts = int(datetime.now(timezone.utc).timestamp())

        ndjson_content = "\n".join([
            json.dumps({"token_id": "t1", "outcome_index": 0, "t": now_ts - 3600 * i, "p": 0.50})
            for i in range(10, 0, -1)
        ])

        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr(
                "Polymarket_dataset/market=0xabc123/price/token=t1.ndjson",
                ndjson_content,
            )

        count = loader.load_kaggle_dataset(str(zip_path))
        assert count == 1
        assert "0xabc123" in loader.markets
        assert len(loader.markets["0xabc123"].prices) == 10

    def test_max_markets_limits_loading(self, loader, tmp_path):
        zip_path = tmp_path / "kaggle2.zip"
        now_ts = int(datetime.now(timezone.utc).timestamp())

        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            for j in range(5):
                ndjson_content = "\n".join([
                    json.dumps({"token_id": f"t{j}", "outcome_index": 0,
                                "t": now_ts - 3600 * i, "p": 0.50})
                    for i in range(5, 0, -1)
                ])
                zf.writestr(
                    f"Polymarket_dataset/market=0xmarket{j}/price/token=t{j}.ndjson",
                    ndjson_content,
                )

        count = loader.load_kaggle_dataset(str(zip_path), max_markets=2)
        assert count == 2

    def test_deduplicates_timestamps(self, loader, tmp_path):
        zip_path = tmp_path / "kaggle_dup.zip"
        now_ts = int(datetime.now(timezone.utc).timestamp())

        # Two files for same market with overlapping timestamps
        ndjson1 = "\n".join([
            json.dumps({"token_id": "t1", "outcome_index": 0, "t": now_ts - 3600, "p": 0.50}),
            json.dumps({"token_id": "t1", "outcome_index": 0, "t": now_ts, "p": 0.55}),
        ])
        ndjson2 = "\n".join([
            json.dumps({"token_id": "t2", "outcome_index": 0, "t": now_ts - 3600, "p": 0.50}),
            json.dumps({"token_id": "t2", "outcome_index": 0, "t": now_ts - 1800, "p": 0.52}),
        ])

        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr("data/market=0xdup/price/token=t1.ndjson", ndjson1)
            zf.writestr("data/market=0xdup/price/token=t2.ndjson", ndjson2)

        count = loader.load_kaggle_dataset(str(zip_path))
        assert count == 1
        # Duplicate timestamp should be removed
        timestamps = [p.timestamp for p in loader.markets["0xdup"].prices]
        assert len(timestamps) == len(set(t.isoformat() for t in timestamps))

    def test_resolution_inferred_from_final_price(self, loader, tmp_path):
        zip_path = tmp_path / "kaggle_res.zip"
        now_ts = int(datetime.now(timezone.utc).timestamp())

        ndjson = "\n".join([
            json.dumps({"t": now_ts - 3600, "p": 0.80, "outcome_index": 0}),
            json.dumps({"t": now_ts, "p": 0.98, "outcome_index": 0}),
        ])
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr("data/market=0xyes/price/token=t1.ndjson", ndjson)

        loader.load_kaggle_dataset(str(zip_path))
        assert loader.markets["0xyes"].resolution == "YES"

    def test_no_resolution_inferred(self, loader, tmp_path):
        zip_path = tmp_path / "kaggle_no.zip"
        now_ts = int(datetime.now(timezone.utc).timestamp())

        ndjson = "\n".join([
            json.dumps({"t": now_ts - 3600, "p": 0.20, "outcome_index": 0}),
            json.dumps({"t": now_ts, "p": 0.02, "outcome_index": 0}),
        ])
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr("data/market=0xno/price/token=t1.ndjson", ndjson)

        loader.load_kaggle_dataset(str(zip_path))
        assert loader.markets["0xno"].resolution == "NO"


# ============================================================
# 13. DataLoader._extract_condition_id_from_path()
# ============================================================

class TestExtractConditionIdFromPath:
    """Tests for DataLoader._extract_condition_id_from_path()."""

    def test_market_equals_format(self, loader):
        path = "data/market=0xabc123def/price/token=t1.ndjson"
        assert loader._extract_condition_id_from_path(path) == "0xabc123def"

    def test_fallback_legacy_format(self, loader):
        path = "some_condition_id/price.json"
        assert loader._extract_condition_id_from_path(path) == "some_condition_id"

    def test_returns_none_for_unrecognized(self, loader):
        path = "random/path/data.csv"
        assert loader._extract_condition_id_from_path(path) is None

    def test_nested_market_format(self, loader):
        path = "Polymarket_dataset/Polymarket_dataset/market=0xFOO/price/token=bar.ndjson"
        assert loader._extract_condition_id_from_path(path) == "0xFOO"


# ============================================================
# 14. DataLoader._parse_ndjson_prices()
# ============================================================

class TestParseNdjsonPrices:
    """Tests for DataLoader._parse_ndjson_prices()."""

    def test_space_separated_json(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        content = (
            f'{{"t": {now_ts - 3600}, "p": 0.50, "outcome_index": 0}} '
            f'{{"t": {now_ts}, "p": 0.55, "outcome_index": 0}}'
        )
        prices = loader._parse_ndjson_prices(content, "0x1")
        assert len(prices) == 2

    def test_newline_separated(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        content = (
            f'{{"t": {now_ts - 3600}, "p": 0.50, "outcome_index": 0}}\n'
            f'{{"t": {now_ts}, "p": 0.55, "outcome_index": 0}}\n'
        )
        prices = loader._parse_ndjson_prices(content, "0x1")
        assert len(prices) == 2

    def test_filters_no_token(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        content = (
            f'{{"t": {now_ts}, "p": 0.50, "outcome_index": 0}}\n'
            f'{{"t": {now_ts + 60}, "p": 0.40, "outcome_index": 1}}\n'
        )
        prices = loader._parse_ndjson_prices(content, "0x1", yes_token_only=True)
        assert len(prices) == 1
        assert prices[0].price == 0.50

    def test_empty_content(self, loader):
        assert loader._parse_ndjson_prices("", "0x1") == []
        assert loader._parse_ndjson_prices("   ", "0x1") == []

    def test_invalid_json_skipped(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        content = (
            f'{{"t": {now_ts}, "p": 0.50}}\n'
            f'NOT VALID JSON\n'
            f'{{"t": {now_ts + 60}, "p": 0.55}}\n'
        )
        prices = loader._parse_ndjson_prices(content, "0x1")
        assert len(prices) == 2

    def test_price_out_of_range_skipped(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        content = (
            f'{{"t": {now_ts}, "p": 1.50}}\n'
            f'{{"t": {now_ts + 60}, "p": -0.10}}\n'
            f'{{"t": {now_ts + 120}, "p": 0.50}}\n'
        )
        prices = loader._parse_ndjson_prices(content, "0x1")
        assert len(prices) == 1
        assert prices[0].price == 0.50

    def test_missing_t_or_p_skipped(self, loader):
        content = '{"t": 1234567890}\n{"p": 0.50}\n'
        prices = loader._parse_ndjson_prices(content, "0x1")
        assert len(prices) == 0

    def test_yes_token_only_false(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        content = (
            f'{{"t": {now_ts}, "p": 0.50, "outcome_index": 0}}\n'
            f'{{"t": {now_ts + 60}, "p": 0.40, "outcome_index": 1}}\n'
        )
        prices = loader._parse_ndjson_prices(content, "0x1", yes_token_only=False)
        assert len(prices) == 2


# ============================================================
# 15. DataLoader._parse_kaggle_price_data()
# ============================================================

class TestParseKagglePriceData:
    """Tests for DataLoader._parse_kaggle_price_data()."""

    def test_empty_list(self, loader):
        assert loader._parse_kaggle_price_data("0x1", []) is None

    def test_timestamp_and_price_keys(self, loader):
        now = datetime.now(timezone.utc)
        data = [
            {"timestamp": now.isoformat(), "price": 0.50},
            {"timestamp": (now + timedelta(hours=1)).isoformat(), "price": 0.55},
        ]
        result = loader._parse_kaggle_price_data("0x1", data)
        assert result is not None
        assert len(result.prices) == 2

    def test_t_and_p_keys(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        data = [
            {"t": now_ts, "p": 0.50},
            {"t": now_ts + 3600, "p": 0.55},
        ]
        result = loader._parse_kaggle_price_data("0x1", data)
        assert result is not None
        assert len(result.prices) == 2

    def test_resolution_yes_from_high_final(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        data = [
            {"t": now_ts, "p": 0.80},
            {"t": now_ts + 3600, "p": 0.98},
        ]
        result = loader._parse_kaggle_price_data("0x1", data)
        assert result.resolution == "YES"

    def test_resolution_no_from_low_final(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        data = [
            {"t": now_ts, "p": 0.20},
            {"t": now_ts + 3600, "p": 0.03},
        ]
        result = loader._parse_kaggle_price_data("0x1", data)
        assert result.resolution == "NO"

    def test_no_resolution_mid_price(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        data = [
            {"t": now_ts, "p": 0.50},
            {"t": now_ts + 3600, "p": 0.55},
        ]
        result = loader._parse_kaggle_price_data("0x1", data)
        assert result.resolution is None

    def test_invalid_data_skipped(self, loader):
        data = [
            {"timestamp": "not-a-date", "price": 0.50},
            {"price": 0.50},  # missing timestamp
        ]
        result = loader._parse_kaggle_price_data("0x1", data)
        assert result is None  # all points failed, empty prices

    def test_sorts_by_timestamp(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        data = [
            {"t": now_ts + 3600, "p": 0.55},
            {"t": now_ts, "p": 0.50},
        ]
        result = loader._parse_kaggle_price_data("0x1", data)
        assert result.prices[0].timestamp < result.prices[1].timestamp


# ============================================================
# 16. DataLoader.load_kaggle_csv()
# ============================================================

class TestLoadKaggleCsv:
    """Tests for DataLoader.load_kaggle_csv()."""

    def test_nonexistent_csv_returns_zero(self, loader, tmp_path):
        count = loader.load_kaggle_csv(str(tmp_path / "nofile.csv"))
        assert count == 0

    def test_loads_valid_csv(self, loader, tmp_path):
        csv_path = tmp_path / "markets.csv"
        now = datetime.now(timezone.utc)
        rows = [
            {"condition_id": "0xcsv1", "timestamp": (now - timedelta(hours=2)).isoformat(),
             "price": "0.50", "volume": "1000"},
            {"condition_id": "0xcsv1", "timestamp": now.isoformat(),
             "price": "0.55", "volume": "2000"},
            {"condition_id": "0xcsv2", "timestamp": (now - timedelta(hours=1)).isoformat(),
             "price": "0.30", "volume": "500"},
            {"condition_id": "0xcsv2", "timestamp": now.isoformat(),
             "price": "0.35", "volume": "800"},
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["condition_id", "timestamp", "price", "volume"])
            writer.writeheader()
            writer.writerows(rows)

        count = loader.load_kaggle_csv(str(csv_path))
        assert count == 2
        assert "0xcsv1" in loader.markets
        assert "0xcsv2" in loader.markets

    def test_csv_resolution_yes(self, loader, tmp_path):
        csv_path = tmp_path / "yes_market.csv"
        now = datetime.now(timezone.utc)
        rows = [
            {"condition_id": "0xyes", "timestamp": (now - timedelta(hours=1)).isoformat(),
             "price": "0.80", "volume": "100"},
            {"condition_id": "0xyes", "timestamp": now.isoformat(),
             "price": "0.98", "volume": "200"},
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["condition_id", "timestamp", "price", "volume"])
            writer.writeheader()
            writer.writerows(rows)

        loader.load_kaggle_csv(str(csv_path))
        assert loader.markets["0xyes"].resolution == "YES"

    def test_csv_with_market_id_column(self, loader, tmp_path):
        csv_path = tmp_path / "alt.csv"
        now = datetime.now(timezone.utc)
        rows = [
            {"market_id": "0xalt", "time": now.isoformat(), "price": "0.50", "volume": "100"},
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["market_id", "time", "price", "volume"])
            writer.writeheader()
            writer.writerows(rows)

        count = loader.load_kaggle_csv(str(csv_path))
        assert count == 1
        assert "0xalt" in loader.markets

    def test_csv_with_invalid_rows(self, loader, tmp_path):
        csv_path = tmp_path / "bad.csv"
        now = datetime.now(timezone.utc)
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["condition_id", "timestamp", "price", "volume"])
            writer.writeheader()
            # Good row
            writer.writerow({"condition_id": "0xgood", "timestamp": now.isoformat(),
                             "price": "0.50", "volume": "100"})
            # Bad row (invalid timestamp)
            writer.writerow({"condition_id": "0xbad", "timestamp": "not-a-date",
                             "price": "0.50", "volume": "100"})

        count = loader.load_kaggle_csv(str(csv_path))
        assert count == 1
        assert "0xgood" in loader.markets


# ============================================================
# 17. Async API methods
# ============================================================

class TestFetchFromApi:
    """Tests for DataLoader.fetch_from_api()."""

    @pytest.mark.asyncio
    async def test_fetch_from_api_success(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        mock_json = {
            "history": [
                {"t": now_ts - 3600, "p": 0.50},
                {"t": now_ts, "p": 0.55},
            ]
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_json)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            count = await loader.fetch_from_api(["token123"])

        assert count == 1
        assert "token123" in loader.markets
        assert len(loader.markets["token123"].prices) == 2

    @pytest.mark.asyncio
    async def test_fetch_from_api_failure(self, loader):
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            count = await loader.fetch_from_api(["bad_token"])

        assert count == 0

    @pytest.mark.asyncio
    async def test_fetch_from_api_exception(self, loader):
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=Exception("Network error"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            count = await loader.fetch_from_api(["error_token"])

        assert count == 0


class TestFetchPriceHistory:
    """Tests for DataLoader._fetch_price_history()."""

    @pytest.mark.asyncio
    async def test_returns_none_on_non_200(self, loader):
        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = await loader._fetch_price_history(mock_session, "tok1", "max", 60)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_history(self, loader):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"history": []})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = await loader._fetch_price_history(mock_session, "tok1", "max", 60)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_market_history_on_success(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "history": [
                {"t": now_ts - 7200, "p": 0.40},
                {"t": now_ts - 3600, "p": 0.50},
                {"t": now_ts, "p": 0.55},
            ]
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        result = await loader._fetch_price_history(mock_session, "tok1", "max", 60)
        assert result is not None
        assert len(result.prices) == 3
        assert result.prices[0].timestamp < result.prices[1].timestamp


class TestFetchActiveMarkets:
    """Tests for DataLoader.fetch_active_markets()."""

    @pytest.mark.asyncio
    async def test_returns_markets_on_success(self, loader):
        mock_markets = [{"conditionId": "0x1", "question": "Q1"}]

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_markets)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await loader.fetch_active_markets(limit=10)

        assert result == mock_markets

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self, loader):
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await loader.fetch_active_markets()

        assert result == []


class TestFetchResolvedMarkets:
    """Tests for DataLoader.fetch_resolved_markets()."""

    @pytest.mark.asyncio
    async def test_returns_resolved_on_success(self, loader):
        mock_data = [{"conditionId": "0xr1", "outcome": "Yes"}]

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await loader.fetch_resolved_markets(limit=50)

        assert result == mock_data

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, loader):
        mock_resp = AsyncMock()
        mock_resp.status = 403
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await loader.fetch_resolved_markets()

        assert result == []


class TestBuildDatasetFromApi:
    """Tests for DataLoader.build_dataset_from_api()."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_markets(self, loader):
        with patch.object(loader, 'fetch_active_markets', new_callable=AsyncMock, return_value=[]):
            count = await loader.build_dataset_from_api(num_markets=5)
        assert count == 0

    @pytest.mark.asyncio
    async def test_fetches_active_markets(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        mock_markets = [
            {
                "conditionId": "0xbuild1",
                "question": "Build test?",
                "clobTokenIds": ["token_yes", "token_no"],
                "outcome": None,
            },
        ]

        mock_history = MarketHistory(
            condition_id="token_yes",
            question="Market token_yes...",
            prices=[
                PricePoint(timestamp=datetime.fromtimestamp(now_ts - 3600, tz=timezone.utc), price=0.50),
                PricePoint(timestamp=datetime.fromtimestamp(now_ts, tz=timezone.utc), price=0.55),
            ],
        )

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "history": [
                {"t": now_ts - 3600, "p": 0.50},
                {"t": now_ts, "p": 0.55},
            ]
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch.object(loader, 'fetch_active_markets', new_callable=AsyncMock, return_value=mock_markets):
            with patch("aiohttp.ClientSession", return_value=mock_session):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    count = await loader.build_dataset_from_api(num_markets=5)

        assert count == 1
        assert "0xbuild1" in loader.markets

    @pytest.mark.asyncio
    async def test_uses_resolved_markets_when_flag_set(self, loader):
        with patch.object(loader, 'fetch_resolved_markets', new_callable=AsyncMock, return_value=[]) as mock_fetch:
            count = await loader.build_dataset_from_api(num_markets=5, include_resolved=True)
        mock_fetch.assert_called_once()
        assert count == 0

    @pytest.mark.asyncio
    async def test_parses_string_token_ids(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        mock_markets = [
            {
                "conditionId": "0xstrtoken",
                "question": "String tokens?",
                "clobTokenIds": '["tok_str_1", "tok_str_2"]',
                "outcome": "Yes",
            },
        ]

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "history": [
                {"t": now_ts - 3600, "p": 0.50},
                {"t": now_ts, "p": 0.96},
            ]
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch.object(loader, 'fetch_active_markets', new_callable=AsyncMock, return_value=mock_markets):
            with patch("aiohttp.ClientSession", return_value=mock_session):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    count = await loader.build_dataset_from_api(num_markets=5)

        assert count == 1
        m = loader.markets["0xstrtoken"]
        assert m.resolution == "YES"

    @pytest.mark.asyncio
    async def test_skips_market_with_empty_token_ids(self, loader):
        mock_markets = [
            {
                "conditionId": "0xnotoken",
                "question": "No tokens?",
                "clobTokenIds": [],
                "outcome": None,
            },
        ]

        with patch.object(loader, 'fetch_active_markets', new_callable=AsyncMock, return_value=mock_markets):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                count = await loader.build_dataset_from_api(num_markets=5)

        assert count == 0

    @pytest.mark.asyncio
    async def test_handles_exception_during_fetch(self, loader):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        mock_markets = [
            {
                "conditionId": "0xerr",
                "question": "Error?",
                "clobTokenIds": ["tok_err"],
                "outcome": None,
            },
        ]

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=Exception("Timeout"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch.object(loader, 'fetch_active_markets', new_callable=AsyncMock, return_value=mock_markets):
            with patch("aiohttp.ClientSession", return_value=mock_session):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    count = await loader.build_dataset_from_api(num_markets=5)

        assert count == 0


# ============================================================
# 18. save_to_file / load_from_file round-trip
# ============================================================

class TestSaveLoadRoundTrip:
    """Tests for save_to_file and load_from_file."""

    def test_round_trip_preserves_data(self, loaded_loader, tmp_path):
        filepath = str(tmp_path / "roundtrip.json")
        loaded_loader.save_to_file(filepath)

        loader2 = DataLoader()
        count = loader2.load_from_file(filepath)
        assert count == len(loaded_loader.markets)

        for cid, original in loaded_loader.markets.items():
            loaded = loader2.markets[cid]
            assert loaded.condition_id == original.condition_id
            assert loaded.question == original.question
            assert loaded.resolution == original.resolution
            assert len(loaded.prices) == len(original.prices)

    def test_load_nonexistent_returns_zero(self, loader, tmp_path):
        assert loader.load_from_file(str(tmp_path / "nope.json")) == 0

    def test_save_includes_resolution_time(self, loader, tmp_path):
        now = datetime.now(timezone.utc)
        loader.markets["0xrt"] = MarketHistory(
            condition_id="0xrt", question="RT?",
            prices=[PricePoint(timestamp=now, price=0.99)],
            resolution="YES",
            resolution_time=now,
        )
        filepath = str(tmp_path / "rt.json")
        loader.save_to_file(filepath)

        with open(filepath) as f:
            data = json.load(f)

        assert data["markets"][0]["resolution_time"] is not None


# ============================================================
# 19. _parse_market_data
# ============================================================

class TestParseMarketData:
    """Tests for DataLoader._parse_market_data()."""

    def test_parse_valid_data(self, loader):
        now = datetime.now(timezone.utc)
        data = {
            "condition_id": "0xparse1",
            "question": "Parse?",
            "resolution": "YES",
            "resolution_time": now.isoformat(),
            "prices": [
                {"timestamp": now.isoformat(), "price": 0.50, "volume": 100,
                 "bid": 0.49, "ask": 0.51},
            ],
        }
        result = loader._parse_market_data(data)
        assert result is not None
        assert result.condition_id == "0xparse1"
        assert len(result.prices) == 1

    def test_missing_condition_id(self, loader):
        data = {"question": "No ID?", "prices": []}
        assert loader._parse_market_data(data) is None

    def test_conditionId_key(self, loader):
        now = datetime.now(timezone.utc)
        data = {
            "conditionId": "0xalt",
            "prices": [
                {"timestamp": now.isoformat(), "price": 0.50},
            ],
        }
        result = loader._parse_market_data(data)
        assert result is not None
        assert result.condition_id == "0xalt"

    def test_invalid_price_entry_skipped(self, loader):
        data = {
            "condition_id": "0xbad",
            "prices": [
                {"timestamp": "not-valid", "price": 0.50},
                {"price": 0.50},  # missing timestamp
            ],
        }
        result = loader._parse_market_data(data)
        assert result is not None
        assert len(result.prices) == 0

    def test_invalid_resolution_time(self, loader):
        data = {
            "condition_id": "0xbadrt",
            "resolution_time": "nope",
            "prices": [],
        }
        result = loader._parse_market_data(data)
        assert result.resolution_time is None


# ============================================================
# 20. summary()
# ============================================================

class TestSummary:
    """Tests for DataLoader.summary()."""

    def test_empty_loader(self, loader):
        assert loader.summary() == "No data loaded"

    def test_with_data(self, loaded_loader):
        s = loaded_loader.summary()
        assert "Markets: 10" in s
        assert "Resolved:" in s
        assert "Duration:" in s


# ============================================================
# 21. get_markets_active_at()
# ============================================================

class TestGetMarketsActiveAt:
    """Tests for DataLoader.get_markets_active_at()."""

    def test_returns_active(self, loaded_loader):
        min_t, max_t = loaded_loader.get_time_range()
        mid = min_t + (max_t - min_t) / 2
        active = loaded_loader.get_markets_active_at(mid)
        assert len(active) > 0

    def test_none_active_far_future(self, loaded_loader):
        far_future = datetime.now(timezone.utc) + timedelta(days=365)
        active = loaded_loader.get_markets_active_at(far_future)
        assert len(active) == 0

    def test_none_active_far_past(self, loaded_loader):
        far_past = datetime.now(timezone.utc) - timedelta(days=365)
        active = loaded_loader.get_markets_active_at(far_past)
        assert len(active) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
