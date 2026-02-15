#!/usr/bin/env python3
"""
TRADING ENGINE TESTS
=====================
Comprehensive tests for TradingEngine class including execute_trade,
check_exits, and strategy-specific execution methods.
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.run_simulation import (
    TradingEngine, Portfolio, MarketScanner, CONFIG
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def temp_engine(tmp_path):
    """Create a TradingEngine with temporary portfolio."""
    portfolio_file = tmp_path / "test_portfolio.json"

    with patch.object(Portfolio, '__init__', lambda self, **kwargs: None):
        engine = TradingEngine(live=False)

    engine.portfolio = Portfolio(
        initial_balance=1000.0,
        data_file=str(portfolio_file)
    )
    engine.scanner = MarketScanner()
    engine.live = False
    engine.running = False

    return engine


@pytest.fixture
def mock_opportunity():
    """Standard opportunity for testing."""
    return {
        "condition_id": "0xtest123",
        "question": "Test market question?",
        "strategy": "MID_RANGE",
        "side": "YES",
        "price": 0.50,
        "expected_return": 0.05,
        "annualized_return": 3.65,
        "days_to_resolve": 5,
        "liquidity": 100000,
        "confidence": 0.70,
        "reason": "Test opportunity"
    }


@pytest.fixture
def mock_mm_opportunity():
    """Market maker opportunity for testing."""
    return {
        "condition_id": "0xmm123",
        "question": "MM test market?",
        "strategy": "MARKET_MAKER",
        "side": "MM",
        "price": 0.50,
        "best_bid": 0.48,
        "best_ask": 0.52,
        "spread": 0.04,
        "spread_pct": 0.08,
        "mm_bid": 0.495,
        "mm_ask": 0.505,
        "expected_return": 0.01,
        "annualized_return": 10.0,
        "days_to_resolve": 1,
        "liquidity": 50000,
        "volume_24h": 30000,
        "confidence": 0.75,
        "reason": "MM opportunity"
    }


@pytest.fixture
def mock_dual_side_opportunity():
    """Dual-side arbitrage opportunity."""
    return {
        "condition_id": "0xdual123",
        "question": "Dual arb test?",
        "strategy": "DUAL_SIDE_ARB",
        "side": "BOTH",
        "price": 0.96,
        "yes_price": 0.48,
        "no_price": 0.48,
        "expected_return": 0.042,
        "annualized_return": 10.0,
        "days_to_resolve": 1,
        "liquidity": 50000,
        "confidence": 0.99,
        "reason": "Dual side arb"
    }


@pytest.fixture
def mock_binance_opportunity():
    """Binance arbitrage opportunity."""
    return {
        "condition_id": "0xbtc123",
        "question": "Will Bitcoin hit $100k?",
        "strategy": "BINANCE_ARB",
        "side": "YES",
        "price": 0.35,
        "best_bid": 0.33,
        "best_ask": 0.35,
        "binance_price": 95000,
        "target_price": 100000,
        "binance_prob": 0.70,
        "poly_prob": 0.35,
        "edge": 35,
        "expected_return": 0.35,
        "annualized_return": 10.0,
        "days_to_resolve": 7,
        "liquidity": 20000,
        "volume_24h": 50000,
        "confidence": 0.85,
        "reason": "Binance arb"
    }


# ============================================================
# TRADING ENGINE INITIALIZATION TESTS
# ============================================================

class TestTradingEngineInit:
    """Tests for TradingEngine initialization."""

    def test_init_simulation_mode(self, tmp_path):
        """Test engine initializes in simulation mode."""
        with patch.object(Portfolio, '__init__', lambda self, **kwargs: None):
            engine = TradingEngine(live=False)

        assert engine.live is False

    def test_init_live_mode(self, tmp_path):
        """Test engine initializes in live mode."""
        with patch.object(Portfolio, '__init__', lambda self, **kwargs: None):
            engine = TradingEngine(live=True)

        assert engine.live is True


# ============================================================
# EXECUTE TRADE TESTS
# ============================================================

class TestExecuteTrade:
    """Tests for execute_trade method."""

    @pytest.mark.asyncio
    async def test_execute_standard_trade(self, temp_engine, mock_opportunity):
        """Test executing a standard trade."""
        # Use MEAN_REVERSION strategy (excluded from Kelly) so position sizing
        # isn't reduced below the $50 minimum by Kelly fraction
        mock_opportunity["strategy"] = "MEAN_REVERSION"
        initial_balance = temp_engine.portfolio.balance

        await temp_engine.execute_trade(mock_opportunity)

        assert temp_engine.portfolio.balance < initial_balance
        assert mock_opportunity["condition_id"] in temp_engine.portfolio.positions

    @pytest.mark.asyncio
    async def test_execute_trade_insufficient_balance(self, temp_engine, mock_opportunity):
        """Test trade is skipped with insufficient balance."""
        temp_engine.portfolio.balance = 3.0  # Below $5 minimum

        await temp_engine.execute_trade(mock_opportunity)

        assert mock_opportunity["condition_id"] not in temp_engine.portfolio.positions

    @pytest.mark.asyncio
    async def test_execute_trade_invalid_price(self, temp_engine, mock_opportunity):
        """Test trade is skipped with invalid price."""
        mock_opportunity["price"] = -0.10

        await temp_engine.execute_trade(mock_opportunity)

        assert mock_opportunity["condition_id"] not in temp_engine.portfolio.positions

    @pytest.mark.asyncio
    async def test_execute_trade_price_above_one(self, temp_engine, mock_opportunity):
        """Test trade is skipped with price > 1."""
        mock_opportunity["price"] = 1.50

        await temp_engine.execute_trade(mock_opportunity)

        assert mock_opportunity["condition_id"] not in temp_engine.portfolio.positions

    @pytest.mark.asyncio
    async def test_execute_trade_respects_liquidity_limit(self, temp_engine, mock_opportunity):
        """Test trade respects 1% liquidity limit."""
        mock_opportunity["liquidity"] = 1000  # Low liquidity
        initial_balance = temp_engine.portfolio.balance

        await temp_engine.execute_trade(mock_opportunity)

        # Should only buy $10 (1% of $1000 liquidity)
        if mock_opportunity["condition_id"] in temp_engine.portfolio.positions:
            pos = temp_engine.portfolio.positions[mock_opportunity["condition_id"]]
            assert pos["cost_basis"] <= 10.0

    @pytest.mark.asyncio
    async def test_execute_trade_live_mode_no_execution(self, temp_engine, mock_opportunity):
        """Test live mode doesn't execute (just prints)."""
        temp_engine.live = True
        initial_balance = temp_engine.portfolio.balance

        await temp_engine.execute_trade(mock_opportunity)

        # Balance should be unchanged in live mode (no simulation buy)
        assert temp_engine.portfolio.balance == initial_balance


# ============================================================
# MARKET MAKER EXECUTION TESTS
# ============================================================

class TestMarketMakerExecution:
    """Tests for MM-specific execution."""

    @pytest.mark.asyncio
    async def test_execute_mm_trade(self, temp_engine, mock_mm_opportunity):
        """Test executing a market maker trade."""
        await temp_engine.execute_trade(mock_mm_opportunity)

        assert mock_mm_opportunity["condition_id"] in temp_engine.portfolio.positions
        pos = temp_engine.portfolio.positions[mock_mm_opportunity["condition_id"]]
        assert pos["side"] == "MM"
        assert "mm_bid" in pos
        assert "mm_ask" in pos

    @pytest.mark.asyncio
    async def test_mm_trade_has_entry_time(self, temp_engine, mock_mm_opportunity):
        """Test MM position has entry time for timeout tracking."""
        await temp_engine.execute_trade(mock_mm_opportunity)

        pos = temp_engine.portfolio.positions[mock_mm_opportunity["condition_id"]]
        assert "mm_entry_time" in pos

    @pytest.mark.asyncio
    async def test_mm_trade_invalid_price(self, temp_engine, mock_mm_opportunity):
        """Test MM trade is skipped with invalid mid price."""
        mock_mm_opportunity["price"] = 0

        await temp_engine.execute_trade(mock_mm_opportunity)

        assert mock_mm_opportunity["condition_id"] not in temp_engine.portfolio.positions


# ============================================================
# DUAL SIDE ARB EXECUTION TESTS
# ============================================================

class TestDualSideArbExecution:
    """Tests for dual-side arbitrage execution."""

    @pytest.mark.asyncio
    async def test_execute_dual_side_trade(self, temp_engine, mock_dual_side_opportunity):
        """Test executing a dual-side arb trade."""
        await temp_engine.execute_trade(mock_dual_side_opportunity)

        assert mock_dual_side_opportunity["condition_id"] in temp_engine.portfolio.positions
        pos = temp_engine.portfolio.positions[mock_dual_side_opportunity["condition_id"]]
        assert pos["side"] == "BOTH"

    @pytest.mark.asyncio
    async def test_dual_side_no_arb_when_total_above_one(self, temp_engine, mock_dual_side_opportunity):
        """Test dual-side arb skipped when total >= 1."""
        mock_dual_side_opportunity["yes_price"] = 0.55
        mock_dual_side_opportunity["no_price"] = 0.50  # Total = 1.05

        await temp_engine.execute_trade(mock_dual_side_opportunity)

        # Should not execute when no profit
        assert mock_dual_side_opportunity["condition_id"] not in temp_engine.portfolio.positions


# ============================================================
# BINANCE ARB EXECUTION TESTS
# ============================================================

class TestBinanceArbExecution:
    """Tests for Binance arbitrage execution."""

    @pytest.mark.asyncio
    async def test_execute_binance_arb_trade(self, temp_engine, mock_binance_opportunity):
        """Test executing a Binance arb trade."""
        await temp_engine.execute_trade(mock_binance_opportunity)

        assert mock_binance_opportunity["condition_id"] in temp_engine.portfolio.positions
        pos = temp_engine.portfolio.positions[mock_binance_opportunity["condition_id"]]
        assert pos["strategy"] == "BINANCE_ARB"


# ============================================================
# CHECK EXITS TESTS
# ============================================================

class TestCheckExits:
    """Tests for check_exits method."""

    @pytest.mark.asyncio
    async def test_take_profit_exit(self, temp_engine):
        """Test take profit exit triggers correctly."""
        # Create position
        temp_engine.portfolio.buy(
            condition_id="0xtp_test",
            question="Take profit test",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="TEST"
        )

        # Mock price fetch to return profitable price
        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.60  # 20% profit
        ):
            await temp_engine.check_exits()

        # Position should be closed
        assert "0xtp_test" not in temp_engine.portfolio.positions
        assert len(temp_engine.portfolio.trade_history) == 1
        assert temp_engine.portfolio.trade_history[0]["exit_reason"] == "TAKE_PROFIT"

    @pytest.mark.asyncio
    async def test_stop_loss_exit(self, temp_engine):
        """Test stop loss exit triggers correctly."""
        # Create position
        temp_engine.portfolio.buy(
            condition_id="0xsl_test",
            question="Stop loss test",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="TEST"
        )

        # Mock price fetch to return losing price
        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.40  # 20% loss
        ):
            await temp_engine.check_exits()

        # Position should be closed
        assert "0xsl_test" not in temp_engine.portfolio.positions
        assert len(temp_engine.portfolio.trade_history) == 1
        assert temp_engine.portfolio.trade_history[0]["exit_reason"] == "STOP_LOSS"

    @pytest.mark.asyncio
    async def test_no_exit_when_in_range(self, temp_engine):
        """Test no exit when price is within TP/SL range."""
        # Create position
        temp_engine.portfolio.buy(
            condition_id="0xhold_test",
            question="Hold test",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="TEST"
        )

        # Mock price fetch to return price within range
        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.51  # 2% profit - below TP threshold
        ):
            await temp_engine.check_exits()

        # Position should still be open
        assert "0xhold_test" in temp_engine.portfolio.positions

    @pytest.mark.asyncio
    async def test_no_position_check_skipped(self, temp_engine):
        """Test check_exits handles None price gracefully."""
        temp_engine.portfolio.buy(
            condition_id="0xnone_test",
            question="None price test",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="TEST"
        )

        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=None
        ):
            await temp_engine.check_exits()

        # Position should still be open (no price available)
        assert "0xnone_test" in temp_engine.portfolio.positions

    @pytest.mark.asyncio
    async def test_no_side_position_uses_inverted_price(self, temp_engine):
        """Test NO positions use inverted price for PnL."""
        # Create NO position
        temp_engine.portfolio.buy(
            condition_id="0xno_test",
            question="NO side test",
            side="NO",
            price=0.40,  # Entry price for NO
            amount=100,
            reason="Test",
            strategy="TEST"
        )

        # Mock YES price at 0.30 → NO price = 0.70 (profit!)
        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.30  # YES price
        ):
            await temp_engine.check_exits()

        # Should take profit (NO price went from 0.40 to 0.70)
        assert "0xno_test" not in temp_engine.portfolio.positions

    @pytest.mark.asyncio
    async def test_dual_side_position_not_exited(self, temp_engine):
        """Test BOTH positions are not exited early."""
        temp_engine.portfolio.buy(
            condition_id="0xboth_test",
            question="Dual side test",
            side="BOTH",
            price=0.96,
            amount=100,
            reason="Dual arb",
            strategy="DUAL_SIDE_ARB"
        )

        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.50
        ):
            await temp_engine.check_exits()

        # Position should still be open (BOTH waits for resolution)
        assert "0xboth_test" in temp_engine.portfolio.positions


# ============================================================
# MM EXIT TESTS
# ============================================================

class TestMMExit:
    """Tests for _check_mm_exit method."""

    @pytest.mark.asyncio
    async def test_mm_filled_exit(self, temp_engine):
        """Test MM position exits when price reaches ask."""
        # Create MM position
        temp_engine.portfolio.buy(
            condition_id="0xmm_fill",
            question="MM fill test",
            side="MM",
            price=0.50,
            amount=100,
            reason="MM test",
            strategy="MARKET_MAKER"
        )
        pos = temp_engine.portfolio.positions["0xmm_fill"]
        pos["mm_bid"] = 0.50
        pos["mm_ask"] = 0.51
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
        temp_engine.portfolio._save()

        # Mock price at ask level
        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.51
        ):
            await temp_engine.check_exits()

        assert "0xmm_fill" not in temp_engine.portfolio.positions
        assert temp_engine.portfolio.trade_history[-1]["exit_reason"] == "MM_FILLED"

    @pytest.mark.asyncio
    async def test_mm_stop_exit(self, temp_engine):
        """Test MM position stops out on large drop."""
        temp_engine.portfolio.buy(
            condition_id="0xmm_stop",
            question="MM stop test",
            side="MM",
            price=0.50,
            amount=100,
            reason="MM test",
            strategy="MARKET_MAKER"
        )
        pos = temp_engine.portfolio.positions["0xmm_stop"]
        pos["mm_bid"] = 0.50
        pos["mm_ask"] = 0.51
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
        temp_engine.portfolio._save()

        # Mock price dropped 5% (below 3% stop)
        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.47
        ):
            await temp_engine.check_exits()

        assert "0xmm_stop" not in temp_engine.portfolio.positions
        assert temp_engine.portfolio.trade_history[-1]["exit_reason"] == "MM_STOP"

    @pytest.mark.asyncio
    async def test_mm_timeout_exit(self, temp_engine):
        """Test MM position exits on timeout."""
        temp_engine.portfolio.buy(
            condition_id="0xmm_timeout",
            question="MM timeout test",
            side="MM",
            price=0.50,
            amount=100,
            reason="MM test",
            strategy="MARKET_MAKER"
        )
        pos = temp_engine.portfolio.positions["0xmm_timeout"]
        pos["mm_bid"] = 0.50
        pos["mm_ask"] = 0.51
        # Set entry time to 25 hours ago (beyond 24h timeout)
        pos["mm_entry_time"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        temp_engine.portfolio._save()

        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.505
        ):
            await temp_engine.check_exits()

        assert "0xmm_timeout" not in temp_engine.portfolio.positions
        assert temp_engine.portfolio.trade_history[-1]["exit_reason"] == "MM_TIMEOUT"


# ============================================================
# EVALUATE OPPORTUNITY TESTS
# ============================================================

class TestEvaluateOpportunity:
    """Tests for evaluate_opportunity method."""

    @pytest.mark.asyncio
    async def test_skip_existing_position(self, temp_engine, mock_opportunity):
        """Test opportunity is skipped if already in position."""
        temp_engine.portfolio.buy(
            condition_id=mock_opportunity["condition_id"],
            question="Already in",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="TEST"
        )

        result = await temp_engine.evaluate_opportunity(mock_opportunity)
        assert result is False

    @pytest.mark.asyncio
    async def test_skip_at_max_positions(self, temp_engine, mock_opportunity):
        """Test opportunity is skipped at max positions."""
        # Fill up positions
        for i in range(CONFIG["max_positions"]):
            temp_engine.portfolio.buy(
                condition_id=f"0xpos{i}",
                question=f"Position {i}",
                side="YES",
                price=0.50,
                amount=10,
                reason="Fill",
                strategy="TEST"
            )

        result = await temp_engine.evaluate_opportunity(mock_opportunity)
        assert result is False

    @pytest.mark.asyncio
    async def test_accept_high_confidence(self, temp_engine, mock_opportunity):
        """Test high confidence opportunity is accepted."""
        mock_opportunity["confidence"] = 0.80

        result = await temp_engine.evaluate_opportunity(mock_opportunity)
        assert result is True

    @pytest.mark.asyncio
    async def test_reject_low_confidence(self, temp_engine, mock_opportunity):
        """Test low confidence opportunity is rejected."""
        mock_opportunity["confidence"] = 0.40  # Below min_confidence

        result = await temp_engine.evaluate_opportunity(mock_opportunity)
        assert result is False

    @pytest.mark.asyncio
    async def test_dip_buy_with_bullish_news(self, temp_engine):
        """Test DIP_BUY accepted with bullish news."""
        opp = {
            "condition_id": "0xdip",
            "question": "Dip buy test?",
            "strategy": "DIP_BUY",
            "side": "YES",
            "price": 0.40,
            "confidence": 0.65,
            "reason": "Test dip"
        }

        with patch.object(
            temp_engine.news, 'analyze_market',
            new_callable=AsyncMock,
            return_value={"direction": "BULLISH", "confidence": 0.70}
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        assert result is True

    @pytest.mark.asyncio
    async def test_dip_buy_rejected_bearish_news(self, temp_engine):
        """Test DIP_BUY rejected with bearish news."""
        opp = {
            "condition_id": "0xdip2",
            "question": "Dip buy bearish?",
            "strategy": "DIP_BUY",
            "side": "YES",
            "price": 0.40,
            "confidence": 0.65,
            "reason": "Test dip"
        }

        with patch.object(
            temp_engine.news, 'analyze_market',
            new_callable=AsyncMock,
            return_value={"direction": "BEARISH", "confidence": 0.80}
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        assert result is False

    @pytest.mark.asyncio
    async def test_dip_buy_rejected_low_confidence_news(self, temp_engine):
        """Test DIP_BUY rejected with low confidence bullish news."""
        opp = {
            "condition_id": "0xdip3",
            "question": "Dip buy low conf?",
            "strategy": "DIP_BUY",
            "side": "YES",
            "price": 0.40,
            "confidence": 0.65,
            "reason": "Test dip"
        }

        with patch.object(
            temp_engine.news, 'analyze_market',
            new_callable=AsyncMock,
            return_value={"direction": "BULLISH", "confidence": 0.40}  # Below 0.6
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        assert result is False

    @pytest.mark.asyncio
    async def test_volume_surge_with_news(self, temp_engine):
        """Test VOLUME_SURGE checks news but doesn't require bullish."""
        opp = {
            "condition_id": "0xvol",
            "question": "Volume surge?",
            "strategy": "VOLUME_SURGE",
            "side": "YES",
            "price": 0.50,
            "confidence": 0.65,
            "reason": "Test volume"
        }

        with patch.object(
            temp_engine.news, 'analyze_market',
            new_callable=AsyncMock,
            return_value={"direction": "NEUTRAL", "confidence": 0.50}
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        assert result is True  # VOLUME_SURGE doesn't require bullish

    @pytest.mark.asyncio
    async def test_dip_buy_no_news(self, temp_engine):
        """Test DIP_BUY when no news is found."""
        opp = {
            "condition_id": "0xdip4",
            "question": "Dip no news?",
            "strategy": "DIP_BUY",
            "side": "YES",
            "price": 0.40,
            "confidence": 0.65,
            "reason": "Test dip"
        }

        with patch.object(
            temp_engine.news, 'analyze_market',
            new_callable=AsyncMock,
            return_value=None
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        # Should pass (no news doesn't block)
        assert result is True


# ============================================================
# RUN CYCLE TESTS
# ============================================================

class TestRunCycle:
    """Tests for run_cycle method."""

    @pytest.mark.asyncio
    async def test_run_cycle_scans_markets(self, temp_engine):
        """Test run_cycle scans for markets."""
        with patch.object(
            temp_engine.scanner, 'get_active_markets',
            new_callable=AsyncMock,
            return_value=[]
        ) as mock_scan:
            with patch.object(
                temp_engine.scanner, 'get_binance_prices',
                new_callable=AsyncMock,
                return_value={}
            ):
                await temp_engine.run_cycle()

        mock_scan.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_cycle_checks_exits(self, temp_engine):
        """Test run_cycle checks exits on existing positions."""
        temp_engine.portfolio.buy(
            condition_id="0xexist",
            question="Existing position",
            side="YES",
            price=0.50,
            amount=100,
            reason="Test",
            strategy="TEST"
        )

        with patch.object(temp_engine, 'check_exits', new_callable=AsyncMock) as mock_exits:
            with patch.object(
                temp_engine.scanner, 'get_active_markets',
                new_callable=AsyncMock,
                return_value=[]
            ):
                with patch.object(
                    temp_engine.scanner, 'get_binance_prices',
                    new_callable=AsyncMock,
                    return_value={}
                ):
                    await temp_engine.run_cycle()

        mock_exits.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
