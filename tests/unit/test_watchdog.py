"""Tests for the Watchdog agent."""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock


class TestHeartbeatCheck:
    """Test heartbeat freshness detection."""

    def _write_heartbeat(self, tmp_dir, age_seconds=0, **overrides):
        """Write a heartbeat file with configurable age."""
        ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        data = {
            "ts": ts.isoformat(),
            "positions": 3,
            "balance": 850.0,
            "pnl": 12.50,
            "trades": 10,
            "win_rate": 65.0,
        }
        data.update(overrides)
        hb_path = Path(tmp_dir) / ".heartbeat.json"
        with open(hb_path, "w") as f:
            json.dump(data, f)
        return hb_path

    def test_fresh_heartbeat_healthy(self, tmp_path):
        """Heartbeat < 5 min old should be healthy."""
        from sovereign_hive.agents_v2 import watchdog

        hb_path = self._write_heartbeat(tmp_path, age_seconds=30)
        with patch.object(watchdog, "HEARTBEAT_FILE", hb_path):
            with patch.object(watchdog, "STALE_THRESHOLD", 300):
                result = watchdog.check_heartbeat()
        assert result["healthy"] is True
        assert result["age_seconds"] < 300

    def test_stale_heartbeat_unhealthy(self, tmp_path):
        """Heartbeat > 5 min old should be unhealthy."""
        from sovereign_hive.agents_v2 import watchdog

        hb_path = self._write_heartbeat(tmp_path, age_seconds=600)
        with patch.object(watchdog, "HEARTBEAT_FILE", hb_path):
            with patch.object(watchdog, "STALE_THRESHOLD", 300):
                result = watchdog.check_heartbeat()
        assert result["healthy"] is False
        assert "stale" in result["reason"].lower()

    def test_missing_heartbeat_unhealthy(self, tmp_path):
        """Missing heartbeat file should be unhealthy."""
        from sovereign_hive.agents_v2 import watchdog

        missing_path = Path(tmp_path) / ".heartbeat.json"
        with patch.object(watchdog, "HEARTBEAT_FILE", missing_path):
            result = watchdog.check_heartbeat()
        assert result["healthy"] is False
        assert "no heartbeat" in result["reason"].lower()

    def test_corrupt_heartbeat_unhealthy(self, tmp_path):
        """Corrupt heartbeat file should be unhealthy."""
        from sovereign_hive.agents_v2 import watchdog

        hb_path = Path(tmp_path) / ".heartbeat.json"
        with open(hb_path, "w") as f:
            f.write("not json")
        with patch.object(watchdog, "HEARTBEAT_FILE", hb_path):
            result = watchdog.check_heartbeat()
        assert result["healthy"] is False


class TestPortfolioSanity:
    def test_normal_balance_healthy(self, tmp_path):
        """Normal balance should be healthy."""
        from sovereign_hive.agents_v2 import watchdog

        hb_path = Path(tmp_path) / ".heartbeat.json"
        with open(hb_path, "w") as f:
            json.dump({"balance": 950.0}, f)

        with patch.object(watchdog, "HEARTBEAT_FILE", hb_path):
            watchdog._last_balance = None
            result = watchdog.check_portfolio_sanity()
        assert result["healthy"] is True

    def test_zero_balance_unhealthy(self, tmp_path):
        """Zero balance should trigger anomaly."""
        from sovereign_hive.agents_v2 import watchdog

        hb_path = Path(tmp_path) / ".heartbeat.json"
        with open(hb_path, "w") as f:
            json.dump({"balance": 0}, f)

        with patch.object(watchdog, "HEARTBEAT_FILE", hb_path):
            watchdog._last_balance = None
            result = watchdog.check_portfolio_sanity()
        assert result["healthy"] is False

    def test_massive_drop_unhealthy(self, tmp_path):
        """50%+ balance drop in one check should trigger anomaly."""
        from sovereign_hive.agents_v2 import watchdog

        hb_path = Path(tmp_path) / ".heartbeat.json"
        with open(hb_path, "w") as f:
            json.dump({"balance": 400.0}, f)

        with patch.object(watchdog, "HEARTBEAT_FILE", hb_path):
            watchdog._last_balance = 1000.0  # Simulate previous check
            result = watchdog.check_portfolio_sanity()
        assert result["healthy"] is False
        assert "dropped" in result["reason"].lower()


class TestWatchdogEvents:
    def test_write_event(self, tmp_path):
        """Events should be written as JSONL."""
        from sovereign_hive.agents_v2 import watchdog
        from sovereign_hive.agents_v2.models import WatchdogEvent

        events_path = Path(tmp_path) / ".watchdog_events.jsonl"
        with patch.object(watchdog, "EVENTS_FILE", events_path):
            event = WatchdogEvent(
                ts=datetime.now(timezone.utc).isoformat(),
                event_type="restart",
                message="Trader restarted",
                severity="warning",
            )
            watchdog.write_event(event)

        assert events_path.exists()
        with open(events_path) as f:
            line = f.readline()
        data = json.loads(line)
        assert data["event_type"] == "restart"
        assert data["severity"] == "warning"
