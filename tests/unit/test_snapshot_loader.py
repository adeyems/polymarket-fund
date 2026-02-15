"""
Unit tests for sovereign_hive/backtest/snapshot_loader.py
=========================================================
Covers: get_snapshot_files, count_snapshot_days, load_snapshots, snapshot_summary

All tests monkeypatch SNAPSHOT_DIR to use tmp_path so no real filesystem is touched.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import sovereign_hive.backtest.snapshot_loader as sl


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def snapshot_dir(tmp_path, monkeypatch):
    """Redirect SNAPSHOT_DIR to a temp directory."""
    monkeypatch.setattr(sl, "SNAPSHOT_DIR", tmp_path)
    return tmp_path


def _write_ndjson(filepath: Path, records: list):
    """Helper: write a list of dicts as newline-delimited JSON."""
    with open(filepath, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _make_snapshot(ts_str, markets):
    """Helper: create a snapshot dict."""
    return {"ts": ts_str, "markets": markets}


def _make_market(cid="0xabc", question="Test?", bid=0.45, ask=0.47, vol=50000, end=""):
    """Helper: create a market entry."""
    m = {"id": cid, "q": question, "bid": bid, "ask": ask, "vol24h": vol}
    if end:
        m["end"] = end
    return m


# ============================================================
# get_snapshot_files
# ============================================================

class TestGetSnapshotFiles:

    def test_returns_empty_when_dir_does_not_exist(self, tmp_path, monkeypatch):
        """get_snapshot_files returns [] when SNAPSHOT_DIR does not exist."""
        nonexistent = tmp_path / "nonexistent"
        monkeypatch.setattr(sl, "SNAPSHOT_DIR", nonexistent)
        assert sl.get_snapshot_files() == []

    def test_returns_sorted_ndjson_files(self, snapshot_dir):
        """get_snapshot_files returns .ndjson files sorted by name."""
        (snapshot_dir / "2026-02-12.ndjson").write_text("")
        (snapshot_dir / "2026-02-14.ndjson").write_text("")
        (snapshot_dir / "2026-02-13.ndjson").write_text("")

        result = sl.get_snapshot_files()
        names = [f.name for f in result]
        assert names == ["2026-02-12.ndjson", "2026-02-13.ndjson", "2026-02-14.ndjson"]

    def test_ignores_non_ndjson_files(self, snapshot_dir):
        """get_snapshot_files ignores .txt, .json, and other non-.ndjson files."""
        (snapshot_dir / "2026-02-12.ndjson").write_text("")
        (snapshot_dir / "notes.txt").write_text("some notes")
        (snapshot_dir / "cache.json").write_text("{}")
        (snapshot_dir / "readme.md").write_text("# readme")

        result = sl.get_snapshot_files()
        assert len(result) == 1
        assert result[0].name == "2026-02-12.ndjson"


# ============================================================
# count_snapshot_days
# ============================================================

class TestCountSnapshotDays:

    def test_counts_correctly(self, snapshot_dir):
        """count_snapshot_days returns the number of .ndjson files."""
        for i in range(5):
            (snapshot_dir / f"2026-02-{10+i:02d}.ndjson").write_text("")
        assert sl.count_snapshot_days() == 5

    def test_returns_zero_when_empty(self, snapshot_dir):
        """count_snapshot_days returns 0 when directory has no ndjson files."""
        assert sl.count_snapshot_days() == 0


# ============================================================
# load_snapshots
# ============================================================

class TestLoadSnapshots:

    def test_returns_none_when_below_min_days(self, snapshot_dir):
        """load_snapshots returns None when fewer files than min_days."""
        (snapshot_dir / "2026-02-12.ndjson").write_text("")
        result = sl.load_snapshots(min_days=3)
        assert result is None

    def test_loads_valid_ndjson_data(self, snapshot_dir):
        """load_snapshots parses NDJSON files and returns a DataLoader with markets."""
        ts1 = "2026-02-14T12:00:00+00:00"
        ts2 = "2026-02-14T13:00:00+00:00"
        ts3 = "2026-02-14T14:00:00+00:00"
        records = [
            _make_snapshot(ts1, [_make_market("0xabc", "Will it rain?", 0.45, 0.47, 50000)]),
            _make_snapshot(ts2, [_make_market("0xabc", "Will it rain?", 0.50, 0.52, 60000)]),
            _make_snapshot(ts3, [_make_market("0xabc", "Will it rain?", 0.55, 0.57, 70000)]),
        ]
        _write_ndjson(snapshot_dir / "2026-02-14.ndjson", records)

        loader = sl.load_snapshots(min_days=1)
        assert loader is not None
        assert "0xabc" in loader.markets
        history = loader.markets["0xabc"]
        assert history.question == "Will it rain?"
        assert len(history.prices) == 3
        # Price should be (bid+ask)/2
        assert history.prices[0].price == pytest.approx((0.45 + 0.47) / 2)

    def test_respects_max_markets_limit(self, snapshot_dir):
        """load_snapshots only loads up to max_markets markets."""
        ts1 = "2026-02-14T12:00:00+00:00"
        ts2 = "2026-02-14T13:00:00+00:00"
        records = [
            _make_snapshot(ts1, [
                _make_market("0x001", "Market 1", 0.4, 0.5, 1000),
                _make_market("0x002", "Market 2", 0.3, 0.6, 2000),
                _make_market("0x003", "Market 3", 0.2, 0.7, 3000),
            ]),
            _make_snapshot(ts2, [
                _make_market("0x001", "Market 1", 0.41, 0.51, 1100),
                _make_market("0x002", "Market 2", 0.31, 0.61, 2100),
                _make_market("0x003", "Market 3", 0.21, 0.71, 3100),
            ]),
        ]
        _write_ndjson(snapshot_dir / "2026-02-14.ndjson", records)

        loader = sl.load_snapshots(min_days=1, max_markets=2)
        assert loader is not None
        assert len(loader.markets) == 2

    def test_skips_invalid_json_lines(self, snapshot_dir):
        """load_snapshots gracefully skips lines that are not valid JSON."""
        ts1 = "2026-02-14T12:00:00+00:00"
        ts2 = "2026-02-14T13:00:00+00:00"
        filepath = snapshot_dir / "2026-02-14.ndjson"
        with open(filepath, "w") as f:
            f.write("NOT VALID JSON\n")
            f.write(json.dumps(_make_snapshot(ts1, [_make_market()])) + "\n")
            f.write("{bad json\n")
            f.write(json.dumps(_make_snapshot(ts2, [_make_market()])) + "\n")

        loader = sl.load_snapshots(min_days=1)
        assert loader is not None
        assert "0xabc" in loader.markets
        assert len(loader.markets["0xabc"].prices) == 2

    def test_skips_entries_with_no_bid_ask(self, snapshot_dir):
        """load_snapshots skips market entries where both bid and ask are 0."""
        ts1 = "2026-02-14T12:00:00+00:00"
        ts2 = "2026-02-14T13:00:00+00:00"
        records = [
            _make_snapshot(ts1, [
                _make_market("0xabc", "Good market", 0.45, 0.47),
                _make_market("0xbad", "Bad market", 0, 0),
            ]),
            _make_snapshot(ts2, [
                _make_market("0xabc", "Good market", 0.50, 0.52),
                _make_market("0xbad", "Bad market", 0, 0),
            ]),
        ]
        _write_ndjson(snapshot_dir / "2026-02-14.ndjson", records)

        loader = sl.load_snapshots(min_days=1)
        assert loader is not None
        assert "0xabc" in loader.markets
        assert "0xbad" not in loader.markets

    def test_deduplicates_by_timestamp(self, snapshot_dir):
        """load_snapshots deduplicates price points with the same timestamp."""
        same_ts = "2026-02-14T12:00:00+00:00"
        ts2 = "2026-02-14T13:00:00+00:00"
        records = [
            _make_snapshot(same_ts, [_make_market("0xabc", "Test", 0.45, 0.47)]),
            _make_snapshot(same_ts, [_make_market("0xabc", "Test", 0.46, 0.48)]),
            _make_snapshot(ts2, [_make_market("0xabc", "Test", 0.50, 0.52)]),
        ]
        _write_ndjson(snapshot_dir / "2026-02-14.ndjson", records)

        loader = sl.load_snapshots(min_days=1)
        assert loader is not None
        # The first of the duplicate timestamps should be kept, plus the unique one
        assert len(loader.markets["0xabc"].prices) == 2

    def test_determines_resolution_from_end_date(self, snapshot_dir):
        """load_snapshots sets resolution to YES when final price >= 0.95 past end_date."""
        end_dt = "2026-02-14T11:00:00+00:00"
        ts1 = "2026-02-14T10:00:00+00:00"
        ts2 = "2026-02-14T12:00:00+00:00"  # After end date
        records = [
            _make_snapshot(ts1, [_make_market("0xabc", "Resolved?", 0.80, 0.82, end=end_dt)]),
            _make_snapshot(ts2, [_make_market("0xabc", "Resolved?", 0.96, 0.98, end=end_dt)]),
        ]
        _write_ndjson(snapshot_dir / "2026-02-14.ndjson", records)

        loader = sl.load_snapshots(min_days=1)
        assert loader is not None
        history = loader.markets["0xabc"]
        assert history.resolution == "YES"

    def test_resolution_no_when_final_price_low(self, snapshot_dir):
        """load_snapshots sets resolution to NO when final price <= 0.05 past end_date."""
        end_dt = "2026-02-14T11:00:00+00:00"
        ts1 = "2026-02-14T10:00:00+00:00"
        ts2 = "2026-02-14T12:00:00+00:00"
        records = [
            _make_snapshot(ts1, [_make_market("0xabc", "Resolved?", 0.10, 0.12, end=end_dt)]),
            _make_snapshot(ts2, [_make_market("0xabc", "Resolved?", 0.02, 0.04, end=end_dt)]),
        ]
        _write_ndjson(snapshot_dir / "2026-02-14.ndjson", records)

        loader = sl.load_snapshots(min_days=1)
        assert loader is not None
        history = loader.markets["0xabc"]
        assert history.resolution == "NO"

    def test_returns_none_when_no_markets_loaded(self, snapshot_dir):
        """load_snapshots returns None when all markets have < 2 price points."""
        ts1 = "2026-02-14T12:00:00+00:00"
        records = [
            _make_snapshot(ts1, [_make_market("0xabc", "One point", 0.45, 0.47)]),
        ]
        _write_ndjson(snapshot_dir / "2026-02-14.ndjson", records)

        loader = sl.load_snapshots(min_days=1)
        # Only 1 price point for the market, so it is skipped; count==0 -> None
        assert loader is None

    def test_skips_entries_with_invalid_timestamp(self, snapshot_dir):
        """load_snapshots skips snapshot lines with invalid/empty timestamps."""
        ts_good = "2026-02-14T12:00:00+00:00"
        ts_good2 = "2026-02-14T13:00:00+00:00"
        filepath = snapshot_dir / "2026-02-14.ndjson"
        with open(filepath, "w") as f:
            # Bad ts values: empty string, non-parseable string, None-like
            f.write(json.dumps({"ts": "", "markets": [{"id": "0xbad", "q": "X", "bid": 0.5, "ask": 0.6, "vol24h": 1}]}) + "\n")
            f.write(json.dumps({"ts": "not-a-date", "markets": [{"id": "0xbad", "q": "X", "bid": 0.5, "ask": 0.6, "vol24h": 1}]}) + "\n")
            # Good entries
            f.write(json.dumps(_make_snapshot(ts_good, [_make_market("0xabc")])) + "\n")
            f.write(json.dumps(_make_snapshot(ts_good2, [_make_market("0xabc")])) + "\n")

        loader = sl.load_snapshots(min_days=1)
        assert loader is not None
        assert "0xabc" in loader.markets
        # The bad entries should be skipped, 0xbad should not appear
        assert "0xbad" not in loader.markets

    def test_skips_entries_with_no_condition_id(self, snapshot_dir):
        """load_snapshots skips market entries that have no 'id' field."""
        ts1 = "2026-02-14T12:00:00+00:00"
        ts2 = "2026-02-14T13:00:00+00:00"
        records = [
            _make_snapshot(ts1, [
                {"q": "No id field", "bid": 0.5, "ask": 0.6, "vol24h": 100},
                {"id": "", "q": "Empty id", "bid": 0.5, "ask": 0.6, "vol24h": 100},
                _make_market("0xgood", "Good", 0.4, 0.5),
            ]),
            _make_snapshot(ts2, [
                _make_market("0xgood", "Good", 0.41, 0.51),
            ]),
        ]
        _write_ndjson(snapshot_dir / "2026-02-14.ndjson", records)

        loader = sl.load_snapshots(min_days=1)
        assert loader is not None
        assert "0xgood" in loader.markets
        assert "" not in loader.markets

    def test_resolution_time_is_set(self, snapshot_dir):
        """load_snapshots sets resolution_time when end_date is present and conditions met."""
        end_dt = "2026-02-14T11:00:00+00:00"
        ts1 = "2026-02-14T10:00:00+00:00"
        ts2 = "2026-02-14T12:00:00+00:00"
        records = [
            _make_snapshot(ts1, [_make_market("0xabc", "R?", 0.80, 0.82, end=end_dt)]),
            _make_snapshot(ts2, [_make_market("0xabc", "R?", 0.96, 0.98, end=end_dt)]),
        ]
        _write_ndjson(snapshot_dir / "2026-02-14.ndjson", records)

        loader = sl.load_snapshots(min_days=1)
        history = loader.markets["0xabc"]
        assert history.resolution_time is not None

    def test_skips_blank_lines(self, snapshot_dir):
        """load_snapshots skips empty/blank lines in NDJSON files."""
        ts1 = "2026-02-14T12:00:00+00:00"
        ts2 = "2026-02-14T13:00:00+00:00"
        filepath = snapshot_dir / "2026-02-14.ndjson"
        with open(filepath, "w") as f:
            f.write("\n")
            f.write(json.dumps(_make_snapshot(ts1, [_make_market()])) + "\n")
            f.write("   \n")
            f.write(json.dumps(_make_snapshot(ts2, [_make_market()])) + "\n")
            f.write("\n")

        loader = sl.load_snapshots(min_days=1)
        assert loader is not None
        assert len(loader.markets["0xabc"].prices) == 2


# ============================================================
# snapshot_summary
# ============================================================

class TestSnapshotSummary:

    def test_returns_message_when_no_data(self, snapshot_dir):
        """snapshot_summary returns a helpful message when no files exist."""
        result = sl.snapshot_summary()
        assert "No snapshot data collected yet" in result

    def test_returns_formatted_stats_with_data(self, snapshot_dir):
        """snapshot_summary returns statistics when data is present."""
        ts1 = "2026-02-14T12:00:00+00:00"
        records = [
            _make_snapshot(ts1, [
                _make_market("0xabc", "Q1"),
                _make_market("0xdef", "Q2"),
            ]),
        ]
        _write_ndjson(snapshot_dir / "2026-02-14.ndjson", records)

        result = sl.snapshot_summary()
        assert "1 days" in result
        assert "2026-02-14" in result
        assert "Unique markets: 2" in result
        assert "Has real bid/ask: YES" in result

    def test_includes_date_range_and_market_count(self, snapshot_dir):
        """snapshot_summary includes correct date range across multiple files."""
        _write_ndjson(
            snapshot_dir / "2026-02-10.ndjson",
            [_make_snapshot("2026-02-10T12:00:00+00:00", [_make_market("0xabc")])]
        )
        _write_ndjson(
            snapshot_dir / "2026-02-14.ndjson",
            [_make_snapshot("2026-02-14T12:00:00+00:00", [_make_market("0xdef")])]
        )

        result = sl.snapshot_summary()
        assert "2 days" in result
        assert "2026-02-10" in result
        assert "2026-02-14" in result
        assert "Unique markets: 2" in result
