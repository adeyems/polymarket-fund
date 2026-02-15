#!/usr/bin/env python3
"""
A/B RUNNER TESTS
=================
Tests for the isolated strategy runner used in A/B testing.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.ab_test.strategy_runner import (
    IsolatedStrategyRunner, VALID_STRATEGIES
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def mm_runner(tmp_path):
    """Create a Market Maker runner with temp files."""
    with patch('sovereign_hive.ab_test.strategy_runner.Path') as mock_path:
        mock_path.return_value.parent.parent = tmp_path
        runner = IsolatedStrategyRunner("MARKET_MAKER", initial_balance=1000.0)
        runner.portfolio.data_file = tmp_path / "test_portfolio.json"
        runner.log_file = tmp_path / "test_log.txt"
    return runner


@pytest.fixture
def binance_runner(tmp_path):
    """Create a Binance Arb runner."""
    with patch('sovereign_hive.ab_test.strategy_runner.Path') as mock_path:
        mock_path.return_value.parent.parent = tmp_path
        runner = IsolatedStrategyRunner("BINANCE_ARB", initial_balance=1000.0)
        runner.portfolio.data_file = tmp_path / "test_portfolio.json"
        runner.log_file = tmp_path / "test_log.txt"
    return runner


@pytest.fixture
def sample_opportunities():
    """Sample opportunities for testing."""
    return [
        {
            "condition_id": "0xmm1",
            "question": "MM Market 1",
            "strategy": "MARKET_MAKER",
            "side": "MM",
            "price": 0.50,
            "mm_bid": 0.495,
            "mm_ask": 0.505,
            "liquidity": 50000,
            "confidence": 0.75,
            "reason": "Test MM"
        },
        {
            "condition_id": "0xbin1",
            "question": "BTC Market",
            "strategy": "BINANCE_ARB",
            "side": "YES",
            "price": 0.40,
            "edge": 10,
            "binance_price": 95000,
            "target_price": 100000,
            "liquidity": 20000,
            "confidence": 0.80,
            "reason": "Test Binance"
        },
        {
            "condition_id": "0xnz1",
            "question": "Near Zero Market",
            "strategy": "NEAR_ZERO",
            "side": "NO",
            "price": 0.96,
            "liquidity": 30000,
            "confidence": 0.90,
            "reason": "Test Near Zero"
        }
    ]


# ============================================================
# INITIALIZATION TESTS
# ============================================================

class TestIsolatedStrategyRunnerInit:
    """Tests for runner initialization."""

    def test_valid_strategy_init(self, tmp_path):
        """Test initialization with valid strategy."""
        with patch('sovereign_hive.ab_test.strategy_runner.Path') as mock_path:
            mock_path.return_value.parent.parent = tmp_path
            runner = IsolatedStrategyRunner("MARKET_MAKER")

        assert runner.strategy == "MARKET_MAKER"
        assert runner.initial_balance == 1000.0

    def test_invalid_strategy_raises(self):
        """Test invalid strategy raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            IsolatedStrategyRunner("INVALID_STRATEGY")

        assert "Invalid strategy" in str(exc_info.value)

    def test_custom_initial_balance(self, tmp_path):
        """Test custom initial balance."""
        with patch('sovereign_hive.ab_test.strategy_runner.Path') as mock_path:
            mock_path.return_value.parent.parent = tmp_path
            runner = IsolatedStrategyRunner("NEAR_ZERO", initial_balance=5000.0)

        assert runner.initial_balance == 5000.0

    def test_all_valid_strategies(self):
        """Test that all expected strategies are valid."""
        expected = {
            "MARKET_MAKER", "BINANCE_ARB", "NEAR_ZERO", "NEAR_CERTAIN",
            "DUAL_SIDE_ARB", "MID_RANGE", "DIP_BUY", "VOLUME_SURGE"
        }
        assert VALID_STRATEGIES == expected


# ============================================================
# FILTER OPPORTUNITIES TESTS
# ============================================================

class TestFilterOpportunities:
    """Tests for opportunity filtering."""

    def test_filter_mm_opportunities(self, mm_runner, sample_opportunities):
        """Test filtering for MM opportunities only."""
        filtered = mm_runner.filter_opportunities(sample_opportunities)

        assert len(filtered) == 1
        assert filtered[0]["strategy"] == "MARKET_MAKER"

    def test_filter_binance_opportunities(self, binance_runner, sample_opportunities):
        """Test filtering for Binance arb only."""
        filtered = binance_runner.filter_opportunities(sample_opportunities)

        assert len(filtered) == 1
        assert filtered[0]["strategy"] == "BINANCE_ARB"

    def test_filter_empty_list(self, mm_runner):
        """Test filtering empty list."""
        filtered = mm_runner.filter_opportunities([])
        assert filtered == []

    def test_filter_no_matches(self, mm_runner):
        """Test filtering when no strategy matches."""
        opportunities = [
            {"condition_id": "0x1", "strategy": "NEAR_ZERO"},
            {"condition_id": "0x2", "strategy": "DIP_BUY"},
        ]
        filtered = mm_runner.filter_opportunities(opportunities)
        assert filtered == []


# ============================================================
# EXECUTE TRADE TESTS
# ============================================================

class TestExecuteTrade:
    """Tests for trade execution."""

    @pytest.mark.asyncio
    async def test_execute_standard_trade(self, tmp_path):
        """Test standard trade execution."""
        with patch('sovereign_hive.ab_test.strategy_runner.Path') as mock_path:
            mock_path.return_value.parent.parent = tmp_path
            runner = IsolatedStrategyRunner("NEAR_ZERO", initial_balance=1000.0)
            runner.log_file = tmp_path / "log.txt"

        opp = {
            "condition_id": "0xtest",
            "question": "Test market",
            "strategy": "NEAR_ZERO",
            "side": "NO",
            "price": 0.95,
            "liquidity": 50000,
            "confidence": 0.90,
            "reason": "Test"
        }

        await runner.execute_trade(opp)

        assert "0xtest" in runner.portfolio.positions

    @pytest.mark.asyncio
    async def test_execute_mm_trade(self, mm_runner):
        """Test MM trade execution."""
        opp = {
            "condition_id": "0xmm_test",
            "question": "MM test",
            "strategy": "MARKET_MAKER",
            "side": "MM",
            "price": 0.50,
            "mm_bid": 0.495,
            "mm_ask": 0.505,
            "liquidity": 50000,
            "confidence": 0.75,
            "reason": "Test MM"
        }

        await mm_runner.execute_trade(opp)

        assert "0xmm_test" in mm_runner.portfolio.positions
        pos = mm_runner.portfolio.positions["0xmm_test"]
        assert pos["side"] == "MM"
        assert "mm_bid" in pos
        assert "mm_ask" in pos

    @pytest.mark.asyncio
    async def test_skip_existing_position(self, mm_runner):
        """Test skipping if already in position."""
        mm_runner.portfolio.buy(
            condition_id="0xexisting",
            question="Existing",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="TEST"
        )

        opp = {
            "condition_id": "0xexisting",
            "question": "Duplicate",
            "strategy": "MARKET_MAKER",
            "side": "MM",
            "price": 0.50,
            "liquidity": 50000,
            "confidence": 0.75,
            "reason": "Test"
        }

        initial_balance = mm_runner.portfolio.balance
        await mm_runner.execute_trade(opp)

        # Balance unchanged - trade skipped
        assert mm_runner.portfolio.balance == initial_balance

    @pytest.mark.asyncio
    async def test_skip_at_max_positions(self, mm_runner):
        """Test skipping at max positions."""
        for i in range(8):  # Max is 8 for isolated runner
            mm_runner.portfolio.buy(
                condition_id=f"0xpos{i}",
                question=f"Position {i}",
                side="YES",
                price=0.50,
                amount=10,
                reason="Fill",
                strategy="TEST"
            )

        opp = {
            "condition_id": "0xnew",
            "question": "New market",
            "strategy": "MARKET_MAKER",
            "side": "MM",
            "price": 0.50,
            "liquidity": 50000,
            "confidence": 0.75,
            "reason": "Test"
        }

        await mm_runner.execute_trade(opp)

        assert "0xnew" not in mm_runner.portfolio.positions

    @pytest.mark.asyncio
    async def test_skip_low_amount(self, mm_runner):
        """Test skipping when calculated amount is too low."""
        mm_runner.portfolio.balance = 50  # Low balance

        opp = {
            "condition_id": "0xlow",
            "question": "Low amount",
            "strategy": "MARKET_MAKER",
            "side": "MM",
            "price": 0.50,
            "liquidity": 100,  # Very low liquidity → $1 max
            "confidence": 0.75,
            "reason": "Test"
        }

        await mm_runner.execute_trade(opp)

        # Should skip (amount < $10)
        assert "0xlow" not in mm_runner.portfolio.positions


# ============================================================
# DUAL SIDE ARB TESTS
# ============================================================

class TestDualSideExecution:
    """Tests for dual-side arb execution."""

    @pytest.mark.asyncio
    async def test_dual_side_execution(self, tmp_path):
        """Test dual-side arb trade."""
        with patch('sovereign_hive.ab_test.strategy_runner.Path') as mock_path:
            mock_path.return_value.parent.parent = tmp_path
            runner = IsolatedStrategyRunner("DUAL_SIDE_ARB", initial_balance=1000.0)
            runner.log_file = tmp_path / "log.txt"

        opp = {
            "condition_id": "0xdual",
            "question": "Dual side test",
            "strategy": "DUAL_SIDE_ARB",
            "side": "BOTH",
            "price": 0.96,
            "yes_price": 0.48,
            "no_price": 0.48,
            "liquidity": 50000,
            "confidence": 0.99,
            "reason": "Test dual"
        }

        await runner.execute_trade(opp)

        assert "0xdual" in runner.portfolio.positions
        pos = runner.portfolio.positions["0xdual"]
        assert pos["side"] == "BOTH"

    @pytest.mark.asyncio
    async def test_dual_side_no_profit(self, tmp_path):
        """Test dual-side skipped when no profit."""
        with patch('sovereign_hive.ab_test.strategy_runner.Path') as mock_path:
            mock_path.return_value.parent.parent = tmp_path
            runner = IsolatedStrategyRunner("DUAL_SIDE_ARB", initial_balance=1000.0)
            runner.log_file = tmp_path / "log.txt"

        opp = {
            "condition_id": "0xnoprofit",
            "question": "No profit",
            "strategy": "DUAL_SIDE_ARB",
            "side": "BOTH",
            "price": 1.00,
            "yes_price": 0.55,
            "no_price": 0.50,  # Total = 1.05 → no profit
            "liquidity": 50000,
            "confidence": 0.99,
            "reason": "Test"
        }

        await runner.execute_trade(opp)

        assert "0xnoprofit" not in runner.portfolio.positions


# ============================================================
# CHECK EXITS TESTS
# ============================================================

class TestCheckExits:
    """Tests for exit checking."""

    @pytest.mark.asyncio
    async def test_check_mm_exit_filled(self, mm_runner):
        """Test MM exit when filled."""
        mm_runner.portfolio.buy(
            condition_id="0xmm_check",
            question="MM check",
            side="MM",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="MARKET_MAKER"
        )
        pos = mm_runner.portfolio.positions["0xmm_check"]
        pos["mm_bid"] = 0.50
        pos["mm_ask"] = 0.51
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
        mm_runner.portfolio._save()

        with patch.object(
            mm_runner.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.52  # Above ask
        ):
            await mm_runner.check_exits()

        assert "0xmm_check" not in mm_runner.portfolio.positions

    @pytest.mark.asyncio
    async def test_dual_side_not_exited(self, tmp_path):
        """Test BOTH positions are not exited early."""
        with patch('sovereign_hive.ab_test.strategy_runner.Path') as mock_path:
            mock_path.return_value.parent.parent = tmp_path
            runner = IsolatedStrategyRunner("DUAL_SIDE_ARB", initial_balance=1000.0)
            runner.log_file = tmp_path / "log.txt"

        runner.portfolio.buy(
            condition_id="0xboth",
            question="Both test",
            side="BOTH",
            price=0.96,
            amount=100,
            reason="Test",
            strategy="DUAL_SIDE_ARB"
        )

        with patch.object(
            runner.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.50
        ):
            await runner.check_exits()

        # Should still be open
        assert "0xboth" in runner.portfolio.positions


# ============================================================
# PERFORMANCE TESTS
# ============================================================

class TestGetPerformance:
    """Tests for performance reporting."""

    def test_get_performance_initial(self, mm_runner):
        """Test initial performance metrics."""
        perf = mm_runner.get_performance()

        assert perf["strategy"] == "MARKET_MAKER"
        assert perf["balance"] == 1000.0
        assert perf["initial_balance"] == 1000.0
        assert perf["total_pnl"] == 0
        assert perf["roi_pct"] == 0

    def test_get_performance_after_trades(self, mm_runner):
        """Test performance after trades."""
        # Buy and sell at profit
        mm_runner.portfolio.buy(
            condition_id="0xtest",
            question="Test",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="MARKET_MAKER"
        )
        mm_runner.portfolio.sell("0xtest", 0.60, "TAKE_PROFIT")

        perf = mm_runner.get_performance()

        assert perf["total_pnl"] > 0
        assert perf["total_trades"] == 1
        assert perf["wins"] == 1


# ============================================================
# RUN CYCLE TESTS
# ============================================================

class TestRunCycle:
    """Tests for run_cycle method."""

    @pytest.mark.asyncio
    async def test_run_cycle_scans_markets(self, mm_runner):
        """Test run_cycle scans for opportunities."""
        with patch.object(
            mm_runner.scanner, 'get_active_markets',
            new_callable=AsyncMock,
            return_value=[]
        ) as mock_scan:
            await mm_runner.run_cycle()

        mock_scan.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_cycle_filters_by_strategy(self, mm_runner):
        """Test run_cycle only trades its strategy."""
        markets = [{"conditionId": "0x1", "liquidityNum": 100000}]
        opportunities = [
            {
                "condition_id": "0x1",
                "question": "Near zero market",
                "strategy": "NEAR_ZERO",
                "side": "NO",
                "price": 0.95,
                "liquidity": 50000,
                "confidence": 0.90,
                "reason": "Test"
            },
            {
                "condition_id": "0x2",
                "question": "MM market",
                "strategy": "MARKET_MAKER",
                "side": "MM",
                "price": 0.50,
                "mm_bid": 0.495,
                "mm_ask": 0.505,
                "liquidity": 50000,
                "confidence": 0.75,
                "reason": "Test MM"
            },
        ]

        with patch.object(
            mm_runner.scanner, 'get_active_markets',
            new_callable=AsyncMock,
            return_value=markets
        ):
            with patch.object(
                mm_runner.scanner, 'find_opportunities',
                return_value=opportunities
            ):
                await mm_runner.run_cycle()

        # Should only execute MM trades (filtered to MARKET_MAKER only)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
