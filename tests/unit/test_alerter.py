"""Tests for the Discord Alerter agent."""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock


class TestPortfolioLoading:
    def test_find_portfolio_file(self, tmp_path):
        """Should find the most recently modified portfolio file."""
        from sovereign_hive.agents_v2 import alerter

        # Create a portfolio file
        portfolio = {
            "balance": 900.0,
            "initial_balance": 1000.0,
            "positions": {},
            "trade_history": [],
            "metrics": {"total_pnl": -10.0, "total_trades": 5, "winning_trades": 3},
            "strategy_metrics": {},
        }
        pf_path = tmp_path / "portfolio_sim.json"
        with open(pf_path, "w") as f:
            json.dump(portfolio, f)

        with patch.object(alerter, "DATA_DIR", tmp_path):
            found = alerter._find_portfolio_file()
        assert found is not None

    def test_load_portfolio(self, tmp_path):
        """Should load and parse portfolio JSON."""
        from sovereign_hive.agents_v2 import alerter

        portfolio = {
            "balance": 900.0,
            "initial_balance": 1000.0,
            "positions": {"0x1": {"question": "Test", "cost_basis": 100}},
            "trade_history": [{"pnl": 5.0, "strategy": "MM"}],
            "metrics": {"total_pnl": 5.0},
            "strategy_metrics": {},
        }
        pf_path = tmp_path / "portfolio_sim.json"
        with open(pf_path, "w") as f:
            json.dump(portfolio, f)

        with patch.object(alerter, "DATA_DIR", tmp_path):
            loaded = alerter._load_portfolio()
        assert loaded is not None
        assert loaded["balance"] == 900.0
        assert len(loaded["positions"]) == 1


class TestTradeDetection:
    @pytest.mark.asyncio
    async def test_detects_new_closed_trade(self):
        """Should detect when trade_history grows."""
        from sovereign_hive.agents_v2 import alerter

        # Set initial state
        alerter._last_trade_count = 1
        alerter._last_positions = {"0x1"}

        portfolio = {
            "positions": {"0x1": {}},
            "trade_history": [
                {"pnl": 5.0, "pnl_pct": 2.5, "question": "Old trade", "strategy": "MM",
                 "side": "YES", "entry_price": 0.50, "exit_price": 0.55, "exit_reason": "TAKE_PROFIT"},
                {"pnl": -3.0, "pnl_pct": -1.5, "question": "New trade", "strategy": "DIP_BUY",
                 "side": "YES", "entry_price": 0.60, "exit_price": 0.57, "exit_reason": "STOP_LOSS"},
            ],
        }

        with patch.object(alerter, "send_discord_embed", new_callable=AsyncMock) as mock_send:
            await alerter.check_new_trades(portfolio)

        # Should have sent a notification for the new closed trade
        assert mock_send.called
        call_kwargs = mock_send.call_args
        title = call_kwargs.kwargs.get("title", "")
        assert "CLOSED" in title
        assert "-3.00" in title  # P&L in title

    @pytest.mark.asyncio
    async def test_detects_new_position(self):
        """Should detect when a new position is opened."""
        from sovereign_hive.agents_v2 import alerter

        # Set initial state (had 1 position)
        alerter._last_trade_count = 0
        alerter._last_positions = {"0x1"}

        portfolio = {
            "positions": {
                "0x1": {"question": "Old", "strategy": "MM", "side": "YES", "entry_price": 0.5, "cost_basis": 100},
                "0x2": {"question": "New market", "strategy": "NEAR_CERTAIN", "side": "NO",
                        "entry_price": 0.95, "cost_basis": 150},
            },
            "trade_history": [],
        }

        with patch.object(alerter, "send_discord_embed", new_callable=AsyncMock) as mock_send:
            await alerter.check_new_trades(portfolio)

        assert mock_send.called
        # Check it mentions the new position
        call_args_str = str(mock_send.call_args_list)
        assert "NEAR_CERTAIN" in call_args_str

    @pytest.mark.asyncio
    async def test_no_alert_on_first_load(self):
        """Should not alert when initializing (first load)."""
        from sovereign_hive.agents_v2 import alerter

        # Empty initial state (first load)
        alerter._last_trade_count = 0
        alerter._last_positions = set()  # Empty = first load

        portfolio = {
            "positions": {"0x1": {"question": "Existing", "strategy": "MM", "side": "YES",
                                  "entry_price": 0.5, "cost_basis": 100}},
            "trade_history": [],
        }

        with patch.object(alerter, "send_discord_embed", new_callable=AsyncMock) as mock_send:
            await alerter.check_new_trades(portfolio)

        # Should NOT send alerts on first load
        assert not mock_send.called


class TestWatchdogEventForwarding:
    @pytest.mark.asyncio
    async def test_reads_watchdog_events(self, tmp_path):
        """Should read and forward watchdog events."""
        from sovereign_hive.agents_v2 import alerter

        events_path = tmp_path / ".watchdog_events.jsonl"
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": "restart",
            "message": "Trader restarted due to stale heartbeat",
            "severity": "warning",
        }
        with open(events_path, "w") as f:
            f.write(json.dumps(event) + "\n")

        alerter._last_event_line = 0

        with patch.object(alerter, "EVENTS_FILE", events_path):
            with patch.object(alerter, "send_discord_embed", new_callable=AsyncMock) as mock_send:
                await alerter.check_watchdog_events()

        assert mock_send.called
        call_args_str = str(mock_send.call_args_list)
        assert "RESTART" in call_args_str
