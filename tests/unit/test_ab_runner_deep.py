#!/usr/bin/env python3
"""
DEEP UNIT TESTS - IsolatedStrategyRunner
==========================================
Fill coverage gaps in sovereign_hive/ab_test/strategy_runner.py.

Targets uncovered paths in:
- check_exits() - standard TP/SL with mock prices, None price handling
- _check_mm_exit() - timeout, stop loss
- execute_trade() - dual side arb execution
- get_performance() - with actual strategy metrics
- run_cycle() - full cycle with mock scanner
- stop() - sets running flag
"""

import pytest
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.ab_test.strategy_runner import (
    IsolatedStrategyRunner, VALID_STRATEGIES
)
from sovereign_hive.run_simulation import CONFIG


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def runner_factory(tmp_path):
    """Factory to create runners with temp files for any strategy."""
    def _make(strategy: str, balance: float = 1000.0):
        with patch('sovereign_hive.ab_test.strategy_runner.Path') as mock_path:
            mock_path.return_value.parent.parent = tmp_path
            runner = IsolatedStrategyRunner(strategy, initial_balance=balance)
            runner.portfolio.data_file = tmp_path / f"portfolio_{strategy.lower()}.json"
            runner.log_file = tmp_path / f"log_{strategy.lower()}.txt"
        return runner
    return _make


@pytest.fixture
def mm_runner(runner_factory):
    """Create a MARKET_MAKER runner with temp files."""
    return runner_factory("MARKET_MAKER")


@pytest.fixture
def near_zero_runner(runner_factory):
    """Create a NEAR_ZERO runner."""
    return runner_factory("NEAR_ZERO")


@pytest.fixture
def dual_runner(runner_factory):
    """Create a DUAL_SIDE_ARB runner."""
    return runner_factory("DUAL_SIDE_ARB")


# ============================================================
# CHECK_EXITS - TAKE PROFIT
# ============================================================

class TestCheckExitsTakeProfit:
    """Test check_exits triggers TAKE_PROFIT correctly."""

    @pytest.mark.asyncio
    async def test_check_exits_take_profit(self, near_zero_runner):
        """Mock price to trigger TP on a standard YES position."""
        runner = near_zero_runner

        # Open a YES position at 0.50
        runner.portfolio.buy(
            condition_id="0xtp_test",
            question="TP test market",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="NEAR_ZERO"
        )

        # Current price at 0.60 => PnL = (200 shares * 0.60 - 100) / 100 = 20% > 10% TP
        with patch.object(
            runner.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.60  # 20% gain
        ):
            await runner.check_exits()

        # Position should be closed
        assert "0xtp_test" not in runner.portfolio.positions
        # Trade should be recorded
        assert len(runner.portfolio.trade_history) == 1
        assert runner.portfolio.trade_history[0]["exit_reason"] == "TAKE_PROFIT"
        assert runner.portfolio.trade_history[0]["pnl"] > 0


# ============================================================
# CHECK_EXITS - STOP LOSS
# ============================================================

class TestCheckExitsStopLoss:
    """Test check_exits triggers STOP_LOSS correctly."""

    @pytest.mark.asyncio
    async def test_check_exits_stop_loss(self, near_zero_runner):
        """Mock price to trigger SL on a standard YES position."""
        runner = near_zero_runner

        # Open a YES position at 0.50
        runner.portfolio.buy(
            condition_id="0xsl_test",
            question="SL test market",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="NEAR_ZERO"
        )

        # Current price at 0.43 => PnL = (200 * 0.43 - 100) / 100 = -14% < -5% SL
        with patch.object(
            runner.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.43
        ):
            await runner.check_exits()

        assert "0xsl_test" not in runner.portfolio.positions
        assert len(runner.portfolio.trade_history) == 1
        assert runner.portfolio.trade_history[0]["exit_reason"] == "STOP_LOSS"
        assert runner.portfolio.trade_history[0]["pnl"] < 0


# ============================================================
# CHECK_EXITS - PRICE NONE
# ============================================================

class TestCheckExitsPriceNone:
    """Test check_exits when scanner returns None price."""

    @pytest.mark.asyncio
    async def test_check_exits_price_none(self, near_zero_runner):
        """Scanner returns None -- position should remain open."""
        runner = near_zero_runner

        runner.portfolio.buy(
            condition_id="0xnone_test",
            question="None price test",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="NEAR_ZERO"
        )

        with patch.object(
            runner.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=None  # Scanner can't get price
        ):
            await runner.check_exits()

        # Position should still be open
        assert "0xnone_test" in runner.portfolio.positions
        assert len(runner.portfolio.trade_history) == 0


# ============================================================
# _CHECK_MM_EXIT - TIMEOUT
# ============================================================

class TestMmExitTimeout:
    """Test MM exit on timeout (hold > max hours)."""

    @pytest.mark.asyncio
    async def test_mm_exit_timeout(self, mm_runner):
        """Hold > max hours triggers MM_TIMEOUT."""
        # Open an MM position with old entry time
        mm_runner.portfolio.buy(
            condition_id="0xmm_timeout",
            question="MM timeout test",
            side="MM",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="MARKET_MAKER"
        )
        pos = mm_runner.portfolio.positions["0xmm_timeout"]
        pos["mm_bid"] = 0.50
        pos["mm_ask"] = 0.52
        # Set entry time to 5 hours ago (exceeds mm_max_hold_hours=4)
        pos["mm_entry_time"] = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        mm_runner.portfolio._save()

        # Price at 0.505 -- above entry but below ask (0.52), so no fill
        with patch.object(
            mm_runner.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.505
        ):
            await mm_runner.check_exits()

        assert "0xmm_timeout" not in mm_runner.portfolio.positions
        assert len(mm_runner.portfolio.trade_history) == 1
        assert mm_runner.portfolio.trade_history[0]["exit_reason"] == "MM_TIMEOUT"


# ============================================================
# _CHECK_MM_EXIT - STOP LOSS
# ============================================================

class TestMmExitStopLoss:
    """Test MM exit on price drop > 3%."""

    @pytest.mark.asyncio
    async def test_mm_exit_stop_loss(self, mm_runner):
        """Price drop > 3% triggers MM_STOP."""
        mm_runner.portfolio.buy(
            condition_id="0xmm_stop",
            question="MM stop test",
            side="MM",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="MARKET_MAKER"
        )
        pos = mm_runner.portfolio.positions["0xmm_stop"]
        pos["mm_bid"] = 0.50
        pos["mm_ask"] = 0.52
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
        mm_runner.portfolio._save()

        # Price at 0.48 => (0.48 - 0.50) / 0.50 = -4% < -3% stop
        with patch.object(
            mm_runner.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.48
        ):
            await mm_runner.check_exits()

        assert "0xmm_stop" not in mm_runner.portfolio.positions
        assert len(mm_runner.portfolio.trade_history) == 1
        assert mm_runner.portfolio.trade_history[0]["exit_reason"] == "MM_STOP"


# ============================================================
# EXECUTE_TRADE - DUAL SIDE ARB
# ============================================================

class TestExecuteDualSideArb:
    """Test dual side arb execution (BOTH side)."""

    @pytest.mark.asyncio
    async def test_execute_dual_side_arb(self, dual_runner):
        """BOTH side execution buys both YES and NO."""
        opp = {
            "condition_id": "0xdual_deep",
            "question": "Dual side deep test",
            "strategy": "DUAL_SIDE_ARB",
            "side": "BOTH",
            "price": 0.96,
            "yes_price": 0.48,
            "no_price": 0.48,  # Total = 0.96 < 1.0 => profit!
            "liquidity": 50000,
            "confidence": 0.99,
            "reason": "Deep test dual"
        }

        await dual_runner.execute_trade(opp)

        assert "0xdual_deep" in dual_runner.portfolio.positions
        pos = dual_runner.portfolio.positions["0xdual_deep"]
        assert pos["side"] == "BOTH"
        assert pos["strategy"] == "DUAL_SIDE_ARB"
        # Balance should have decreased
        assert dual_runner.portfolio.balance < 1000.0


# ============================================================
# GET_PERFORMANCE - WITH ACTUAL TRADES
# ============================================================

class TestGetPerformanceWithTrades:
    """Test get_performance returns proper metrics after trading."""

    def test_get_performance_with_trades(self, mm_runner):
        """Verify metrics dict has correct structure after trades."""
        # Execute two trades: one win, one loss
        mm_runner.portfolio.buy(
            condition_id="0xwin",
            question="Win trade",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="MARKET_MAKER"
        )
        mm_runner.portfolio.sell("0xwin", 0.60, "TAKE_PROFIT")

        mm_runner.portfolio.buy(
            condition_id="0xloss",
            question="Loss trade",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="MARKET_MAKER"
        )
        mm_runner.portfolio.sell("0xloss", 0.45, "STOP_LOSS")

        perf = mm_runner.get_performance()

        assert perf["strategy"] == "MARKET_MAKER"
        assert perf["total_trades"] == 2
        assert perf["wins"] == 1
        assert perf["total_pnl"] != 0
        assert perf["strategy_pnl"] != 0
        assert "balance" in perf
        assert "roi_pct" in perf
        assert "open_positions" in perf
        assert perf["open_positions"] == 0
        assert perf["win_rate"] >= 0


# ============================================================
# RUN_CYCLE - FULL CYCLE WITH MOCK SCANNER
# ============================================================

class TestRunCycleFindsAndTrades:
    """Test run_cycle full cycle with mock scanner returning opportunities."""

    @pytest.mark.asyncio
    async def test_run_cycle_finds_and_trades(self, mm_runner):
        """Mock full cycle: scanner finds markets, finds opps, executes trades."""
        mock_markets = [
            {"conditionId": "0xcycle1", "liquidityNum": 100000}
        ]
        mock_opps = [
            {
                "condition_id": "0xcycle1",
                "question": "Cycle trade test",
                "strategy": "MARKET_MAKER",
                "side": "MM",
                "price": 0.50,
                "mm_bid": 0.49,
                "mm_ask": 0.51,
                "liquidity": 50000,
                "confidence": 0.75,
                "reason": "Cycle test"
            }
        ]

        with patch.object(
            mm_runner.scanner, 'get_active_markets',
            new_callable=AsyncMock,
            return_value=mock_markets
        ):
            with patch.object(
                mm_runner.scanner, 'find_opportunities',
                return_value=mock_opps
            ):
                await mm_runner.run_cycle()

        # Should have executed the MM trade
        assert "0xcycle1" in mm_runner.portfolio.positions


# ============================================================
# STOP - SETS RUNNING FALSE
# ============================================================

class TestStopSetsRunningFalse:
    """Test stop() sets self.running = False."""

    def test_stop_sets_running_false(self, mm_runner):
        """stop() should set running to False."""
        mm_runner.running = True
        mm_runner.stop()
        assert mm_runner.running is False

    def test_stop_from_initial_state(self, mm_runner):
        """stop() from initial state (running=False) should be safe."""
        assert mm_runner.running is False
        mm_runner.stop()
        assert mm_runner.running is False


# ============================================================
# CHECK_EXITS - NO SIDE (edge case)
# ============================================================

class TestCheckExitsNoSide:
    """Test check_exits when position side is YES (standard NO-side path)."""

    @pytest.mark.asyncio
    async def test_check_exits_no_side_position(self, near_zero_runner):
        """Test TP on a NO-side position (current_price = 1 - yes_price)."""
        runner = near_zero_runner

        # Open a NO position at price 0.95 (buying NO side)
        runner.portfolio.buy(
            condition_id="0xno_tp",
            question="NO side TP test",
            side="NO",
            price=0.95,
            amount=100,
            reason="Test",
            strategy="NEAR_ZERO"
        )

        # yes_price = 0.30, so NO current_price = 1.0 - 0.30 = 0.70
        # shares = 100 / 0.95 ~= 105.26
        # current_value = 105.26 * 0.70 = 73.68
        # pnl_pct = (73.68 - 100) / 100 = -26.3% => STOP LOSS
        with patch.object(
            runner.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.30  # yes_price=0.30, so NO side = 0.70
        ):
            await runner.check_exits()

        # Should have triggered stop loss
        assert "0xno_tp" not in runner.portfolio.positions
        assert len(runner.portfolio.trade_history) == 1
        assert runner.portfolio.trade_history[0]["exit_reason"] == "STOP_LOSS"


# ============================================================
# _CHECK_MM_EXIT - PRICE NONE
# ============================================================

class TestMmExitPriceNone:
    """Test MM exit when price is None."""

    @pytest.mark.asyncio
    async def test_mm_exit_price_none(self, mm_runner):
        """MM position stays open when scanner returns None."""
        mm_runner.portfolio.buy(
            condition_id="0xmm_none",
            question="MM none price",
            side="MM",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="MARKET_MAKER"
        )
        pos = mm_runner.portfolio.positions["0xmm_none"]
        pos["mm_bid"] = 0.50
        pos["mm_ask"] = 0.52
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
        mm_runner.portfolio._save()

        with patch.object(
            mm_runner.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=None
        ):
            await mm_runner.check_exits()

        # Position should remain open
        assert "0xmm_none" in mm_runner.portfolio.positions


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
