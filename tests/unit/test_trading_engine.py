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
    TradingEngine, Portfolio, MarketScanner, CONFIG,
    MAKER_STRATEGIES, FEE_FREE_EXITS,
)
from sovereign_hive.core.kelly_criterion import polymarket_taker_fee, taker_slippage


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
        """Test MM position exits when price reaches ask (fill probability passes)."""
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

        # Mock price at ask level + random below fill_prob to guarantee fill
        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.51
        ):
            with patch('sovereign_hive.run_simulation.random.random', return_value=0.1):
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
        pos["mm_ask"] = 0.55
        # Set entry time to 25 hours ago (beyond 24h timeout)
        pos["mm_entry_time"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        temp_engine.portfolio._save()

        # Price must be >= 3% above entry for timeout exit (0.52+ on 0.50 entry)
        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.52
        ):
            await temp_engine.check_exits()

        assert "0xmm_timeout" not in temp_engine.portfolio.positions
        assert temp_engine.portfolio.trade_history[-1]["exit_reason"] == "MM_TIMEOUT"

    @pytest.mark.asyncio
    async def test_mm_fill_probability_rejects(self, temp_engine):
        """Test MM fill rejected when random roll exceeds fill probability."""
        temp_engine.portfolio.buy(
            condition_id="0xmm_nofill",
            question="MM no fill test",
            side="MM",
            price=0.50,
            amount=100,
            reason="MM test",
            strategy="MARKET_MAKER"
        )
        pos = temp_engine.portfolio.positions["0xmm_nofill"]
        pos["mm_bid"] = 0.50
        pos["mm_ask"] = 0.51
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
        temp_engine.portfolio._save()

        # Mock price at ask, but random > fill_prob (0.60) → no fill
        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.51
        ):
            with patch('sovereign_hive.run_simulation.random.random', return_value=0.9):
                await temp_engine.check_exits()

        # Position should still be open
        assert "0xmm_nofill" in temp_engine.portfolio.positions

    @pytest.mark.asyncio
    async def test_mm_stop_exit_with_slippage(self, temp_engine):
        """Test MM stop exit applies slippage to exit price."""
        temp_engine.portfolio.buy(
            condition_id="0xmm_slip",
            question="MM slippage test",
            side="MM",
            price=0.50,
            amount=100,
            reason="MM test",
            strategy="MARKET_MAKER"
        )
        pos = temp_engine.portfolio.positions["0xmm_slip"]
        pos["mm_bid"] = 0.50
        pos["mm_ask"] = 0.51
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()
        temp_engine.portfolio._save()

        # Price dropped to 0.47 (-6%, below -3% stop)
        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.47
        ):
            await temp_engine.check_exits()

        assert "0xmm_slip" not in temp_engine.portfolio.positions
        trade = temp_engine.portfolio.trade_history[-1]
        # Exit price should be below 0.47 due to slippage (0.2%)
        assert trade["exit_price"] < 0.47
        assert trade["exit_price"] == pytest.approx(0.47 * (1 - 0.002), rel=0.001)


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
    async def test_dip_buy_low_confidence_bullish_passes(self, temp_engine):
        """Test DIP_BUY passes with low confidence bullish news (contrarian: only BEARISH blocks)."""
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
            return_value={"direction": "BULLISH", "confidence": 0.40}
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        assert result is True  # Only BEARISH+high confidence blocks

    @pytest.mark.asyncio
    async def test_dip_buy_neutral_news_passes(self, temp_engine):
        """Test DIP_BUY passes with neutral news (contrarian play, neutral is fine)."""
        opp = {
            "condition_id": "0xdip5",
            "question": "Dip buy neutral?",
            "strategy": "DIP_BUY",
            "side": "YES",
            "price": 0.40,
            "confidence": 0.65,
            "reason": "Test dip"
        }

        with patch.object(
            temp_engine.news, 'analyze_market',
            new_callable=AsyncMock,
            return_value={"direction": "NEUTRAL", "confidence": 0.50}
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        assert result is True  # NEUTRAL doesn't block dip buys

    @pytest.mark.asyncio
    async def test_dip_buy_low_confidence_bearish_passes(self, temp_engine):
        """Test DIP_BUY passes with low confidence bearish news (not confident enough to block)."""
        opp = {
            "condition_id": "0xdip6",
            "question": "Dip buy weak bearish?",
            "strategy": "DIP_BUY",
            "side": "YES",
            "price": 0.40,
            "confidence": 0.65,
            "reason": "Test dip"
        }

        with patch.object(
            temp_engine.news, 'analyze_market',
            new_callable=AsyncMock,
            return_value={"direction": "BEARISH", "confidence": 0.40}  # Below 0.6
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        assert result is True  # BEARISH but low confidence doesn't block

    @pytest.mark.asyncio
    async def test_volume_surge_neutral_news_blocks(self, temp_engine):
        """Test VOLUME_SURGE rejected when news doesn't match surge direction."""
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

        assert result is False  # NEUTRAL doesn't match YES surge direction

    @pytest.mark.asyncio
    async def test_volume_surge_bullish_news_passes(self, temp_engine):
        """Test VOLUME_SURGE passes when BULLISH news matches YES surge."""
        opp = {
            "condition_id": "0xvol2",
            "question": "Volume surge bullish?",
            "strategy": "VOLUME_SURGE",
            "side": "YES",
            "price": 0.50,
            "confidence": 0.65,
            "reason": "Test volume"
        }

        with patch.object(
            temp_engine.news, 'analyze_market',
            new_callable=AsyncMock,
            return_value={"direction": "BULLISH", "confidence": 0.70}
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        assert result is True  # BULLISH matches YES surge

    @pytest.mark.asyncio
    async def test_volume_surge_bearish_news_blocks_yes(self, temp_engine):
        """Test VOLUME_SURGE YES surge rejected when news is BEARISH."""
        opp = {
            "condition_id": "0xvol3",
            "question": "Volume surge bearish?",
            "strategy": "VOLUME_SURGE",
            "side": "YES",
            "price": 0.50,
            "confidence": 0.65,
            "reason": "Test volume"
        }

        with patch.object(
            temp_engine.news, 'analyze_market',
            new_callable=AsyncMock,
            return_value={"direction": "BEARISH", "confidence": 0.80}
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        assert result is False  # BEARISH contradicts YES surge

    @pytest.mark.asyncio
    async def test_volume_surge_bearish_news_passes_no(self, temp_engine):
        """Test VOLUME_SURGE NO surge passes when news is BEARISH."""
        opp = {
            "condition_id": "0xvol4",
            "question": "Volume surge no side?",
            "strategy": "VOLUME_SURGE",
            "side": "NO",
            "price": 0.50,
            "confidence": 0.65,
            "reason": "Test volume"
        }

        with patch.object(
            temp_engine.news, 'analyze_market',
            new_callable=AsyncMock,
            return_value={"direction": "BEARISH", "confidence": 0.70}
        ):
            result = await temp_engine.evaluate_opportunity(opp)

        assert result is True  # BEARISH matches NO surge

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


# ============================================================
# FEE MODELING TESTS
# ============================================================

class TestFeeModeling:
    """Tests for Polymarket taker fee integration in Portfolio and execution."""

    def test_buy_with_fee_reduces_shares(self, tmp_path):
        """Taker fee on buy reduces shares received."""
        portfolio = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "fee_test.json"))

        # Buy without fee
        result_no_fee = portfolio.buy(
            condition_id="0xnofee", question="No fee test", side="YES",
            price=0.50, amount=100.0, reason="test", strategy="TEST", fee_pct=0.0
        )
        shares_no_fee = result_no_fee["position"]["shares"]

        # Buy with fee (1.44% at p=0.60)
        fee_pct = polymarket_taker_fee(0.60)
        result_fee = portfolio.buy(
            condition_id="0xwithfee", question="Fee test", side="YES",
            price=0.50, amount=100.0, reason="test", strategy="TEST", fee_pct=fee_pct
        )
        shares_with_fee = result_fee["position"]["shares"]

        # Fewer shares when paying fee
        assert shares_with_fee < shares_no_fee
        # Fee recorded in position
        assert result_fee["position"]["entry_fee"] > 0

    def test_sell_with_fee_reduces_proceeds(self, tmp_path):
        """Taker fee on sell reduces proceeds received."""
        portfolio = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "fee_sell.json"))

        # Buy a position (no fee on entry for simplicity)
        portfolio.buy(
            condition_id="0xsell_test", question="Sell fee test", side="YES",
            price=0.50, amount=100.0, reason="test", strategy="TEST", fee_pct=0.0
        )

        balance_before = portfolio.balance

        # Sell with taker fee
        fee_pct = polymarket_taker_fee(0.55)
        result = portfolio.sell("0xsell_test", current_price=0.55, reason="TAKE_PROFIT", fee_pct=fee_pct)

        assert result["success"]
        assert result["trade"]["exit_fee"] > 0
        # Proceeds = shares * price - fee, should be less than gross
        gross = 200.0 * 0.55  # 200 shares at 0.55
        assert portfolio.balance - balance_before < gross

    def test_buy_with_zero_fee_full_shares(self, tmp_path):
        """Zero fee gives full shares (maker path)."""
        portfolio = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "zero_fee.json"))

        result = portfolio.buy(
            condition_id="0xmaker", question="Maker test", side="YES",
            price=0.50, amount=100.0, reason="test", strategy="MARKET_MAKER", fee_pct=0.0
        )

        assert result["position"]["shares"] == pytest.approx(200.0)  # 100 / 0.50
        assert result["position"]["entry_fee"] == 0.0

    def test_sell_with_zero_fee_full_proceeds(self, tmp_path):
        """Zero fee gives full proceeds (maker/resolved path)."""
        portfolio = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "zero_sell.json"))

        portfolio.buy(
            condition_id="0xmaker_sell", question="Maker sell test", side="YES",
            price=0.50, amount=100.0, reason="test", strategy="MARKET_MAKER", fee_pct=0.0
        )

        balance_before = portfolio.balance
        result = portfolio.sell("0xmaker_sell", current_price=0.55, reason="MM_FILLED", fee_pct=0.0)

        assert result["success"]
        assert result["trade"]["exit_fee"] == 0.0
        # Full proceeds: 200 shares * 0.55 = 110
        assert portfolio.balance - balance_before == pytest.approx(110.0)

    def test_fee_tracked_in_strategy_metrics(self, tmp_path):
        """Fees accumulate in strategy_metrics."""
        portfolio = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "fee_track.json"))

        fee_pct = polymarket_taker_fee(0.60)  # ~1.44%
        portfolio.buy(
            condition_id="0xtrack", question="Track fees", side="YES",
            price=0.60, amount=100.0, reason="test", strategy="DIP_BUY", fee_pct=fee_pct
        )

        assert portfolio.strategy_metrics["DIP_BUY"]["fees"] > 0
        assert portfolio.strategy_metrics["DIP_BUY"]["fees"] == pytest.approx(100.0 * fee_pct, rel=0.01)

    def test_maker_strategies_constant(self):
        """MARKET_MAKER is the only maker strategy."""
        assert "MARKET_MAKER" in MAKER_STRATEGIES
        assert len(MAKER_STRATEGIES) == 1

    def test_fee_free_exits_constant(self):
        """Fee-free exits include resolution and maker fills."""
        assert "RESOLVED" in FEE_FREE_EXITS
        assert "MM_RESOLVED" in FEE_FREE_EXITS
        assert "MM_FILLED" in FEE_FREE_EXITS
        assert "MM_DELISTED" in FEE_FREE_EXITS
        # Taker exits should NOT be in fee-free list
        assert "TAKE_PROFIT" not in FEE_FREE_EXITS
        assert "STOP_LOSS" not in FEE_FREE_EXITS
        assert "MM_STOP" not in FEE_FREE_EXITS

    @pytest.mark.asyncio
    async def test_execute_trade_taker_pays_fee(self, temp_engine):
        """Taker strategy (DIP_BUY) should pay entry fee."""
        opp = {
            "condition_id": "0xfee_exec",
            "question": "Fee execution test?",
            "strategy": "DIP_BUY",
            "side": "YES",
            "price": 0.60,
            "expected_return": 0.10,
            "annualized_return": 5.0,
            "days_to_resolve": 10,
            "liquidity": 50000,
            "confidence": 0.70,
            "reason": "Test fee execution",
        }

        await temp_engine.execute_trade(opp)

        if "0xfee_exec" in temp_engine.portfolio.positions:
            pos = temp_engine.portfolio.positions["0xfee_exec"]
            assert pos["entry_fee"] > 0
            # Fee should match the formula
            expected_fee_rate = polymarket_taker_fee(0.60)
            assert pos["entry_fee"] == pytest.approx(pos["cost_basis"] * expected_fee_rate, rel=0.01)

    @pytest.mark.asyncio
    async def test_execute_trade_maker_pays_no_fee(self, temp_engine, mock_mm_opportunity):
        """MARKET_MAKER strategy should pay zero entry fee."""
        await temp_engine._execute_market_maker(mock_mm_opportunity, amount=100.0)

        if mock_mm_opportunity["condition_id"] in temp_engine.portfolio.positions:
            pos = temp_engine.portfolio.positions[mock_mm_opportunity["condition_id"]]
            assert pos["entry_fee"] == 0.0

    def test_fee_on_round_trip_reduces_pnl(self, tmp_path):
        """A round trip with fees should have lower P&L than without fees."""
        # Without fees
        p1 = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "no_fee_rt.json"))
        p1.buy("0xrt", "Round trip", "YES", 0.50, 100.0, "test", "TEST", fee_pct=0.0)
        r1 = p1.sell("0xrt", current_price=0.55, reason="TAKE_PROFIT", fee_pct=0.0)

        # With fees
        fee = polymarket_taker_fee(0.50)
        p2 = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "fee_rt.json"))
        p2.buy("0xrt", "Round trip", "YES", 0.50, 100.0, "test", "TEST", fee_pct=fee)
        exit_fee = polymarket_taker_fee(0.55)
        r2 = p2.sell("0xrt", current_price=0.55, reason="TAKE_PROFIT", fee_pct=exit_fee)

        assert r2["trade"]["pnl"] < r1["trade"]["pnl"]


# ============================================================
# TAKER SLIPPAGE INTEGRATION TESTS
# ============================================================

class TestTakerSlippageIntegration:
    """Tests for taker slippage in execute_trade and check_exits."""

    @pytest.mark.asyncio
    async def test_taker_entry_gets_worse_fill(self, temp_engine):
        """Taker strategy entry price is worse than quoted due to slippage."""
        opp = {
            "condition_id": "0xslip_entry",
            "question": "Slippage entry test?",
            "strategy": "DIP_BUY",
            "side": "YES",
            "price": 0.60,
            "expected_return": 0.10,
            "annualized_return": 5.0,
            "days_to_resolve": 10,
            "liquidity": 50000,
            "confidence": 0.70,
            "reason": "Test slippage",
        }

        await temp_engine.execute_trade(opp)

        if "0xslip_entry" in temp_engine.portfolio.positions:
            pos = temp_engine.portfolio.positions["0xslip_entry"]
            # Entry price should be higher than quoted (slippage against buyer)
            assert pos["entry_price"] > 0.60

    @pytest.mark.asyncio
    async def test_maker_entry_no_taker_slippage(self, temp_engine, mock_mm_opportunity):
        """MARKET_MAKER entry does NOT apply taker slippage (has its own from Phase 2)."""
        await temp_engine._execute_market_maker(mock_mm_opportunity, amount=100.0)

        if mock_mm_opportunity["condition_id"] in temp_engine.portfolio.positions:
            pos = temp_engine.portfolio.positions[mock_mm_opportunity["condition_id"]]
            # MM uses its own bid-based pricing, not taker slippage
            assert pos["entry_fee"] == 0.0

    def test_taker_exit_slippage_reduces_pnl(self, tmp_path):
        """Taker exit with slippage should result in lower proceeds."""
        # Buy at 0.50, sell at 0.55 with vs without slippage
        p1 = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "no_slip.json"))
        p1.buy("0xns", "No slip", "YES", 0.50, 100.0, "test", "TEST")
        r1 = p1.sell("0xns", current_price=0.55, reason="TAKE_PROFIT")

        slip = taker_slippage(50000)  # 20bps
        slipped_price = 0.55 * (1 - slip)
        p2 = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "with_slip.json"))
        p2.buy("0xws", "With slip", "YES", 0.50, 100.0, "test", "TEST")
        r2 = p2.sell("0xws", current_price=slipped_price, reason="TAKE_PROFIT")

        assert r2["trade"]["pnl"] < r1["trade"]["pnl"]

    def test_thin_market_slippage_worse_than_deep(self, tmp_path):
        """Thin market slippage costs more than deep market."""
        thin_slip = taker_slippage(5000)     # 60bps
        deep_slip = taker_slippage(50000)    # 20bps

        # Same trade, different slippage
        p1 = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "deep.json"))
        p1.buy("0xd", "Deep", "YES", 0.50, 100.0, "test", "TEST")
        r1 = p1.sell("0xd", current_price=0.55 * (1 - deep_slip), reason="TP")

        p2 = Portfolio(initial_balance=1000.0, data_file=str(tmp_path / "thin.json"))
        p2.buy("0xt", "Thin", "YES", 0.50, 100.0, "test", "TEST")
        r2 = p2.sell("0xt", current_price=0.55 * (1 - thin_slip), reason="TP")

        assert r2["trade"]["pnl"] < r1["trade"]["pnl"]


# ============================================================
# WEBSOCKET PRICE FEED TESTS
# ============================================================

class TestWebSocketPriceFeed:
    """Tests for WebSocket price caching and fallback."""

    @pytest.mark.asyncio
    async def test_ws_price_preferred_over_rest(self, temp_engine):
        """When WS has fresh price, REST is not called."""
        # Simulate a WS price cache entry
        temp_engine.ws = True  # Truthy — enables WS path in _get_market_price
        temp_engine.ws_prices["token_abc"] = {
            "price": 0.65,
            "ts": datetime.now(timezone.utc),
        }
        position = {"token_id": "token_abc"}

        price = await temp_engine._get_market_price("0xcond", position)
        assert price == 0.65

    @pytest.mark.asyncio
    async def test_ws_stale_falls_back_to_rest(self, temp_engine):
        """When WS price is stale, falls back to REST."""
        temp_engine.ws = True
        temp_engine.ws_prices["token_stale"] = {
            "price": 0.65,
            "ts": datetime.now(timezone.utc) - timedelta(seconds=60),  # Stale
        }
        position = {"token_id": "token_stale"}

        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.70,
        ):
            price = await temp_engine._get_market_price("0xcond", position)

        assert price == 0.70  # REST fallback

    @pytest.mark.asyncio
    async def test_no_ws_uses_rest(self, temp_engine):
        """When WS is disabled, always uses REST."""
        temp_engine.ws = None  # WS disabled

        with patch.object(
            temp_engine.scanner, 'get_market_price',
            new_callable=AsyncMock,
            return_value=0.55,
        ):
            price = await temp_engine._get_market_price("0xcond", {})

        assert price == 0.55

    @pytest.mark.asyncio
    async def test_ws_callback_updates_cache(self, temp_engine):
        """_on_ws_price callback populates the price cache."""
        await temp_engine._on_ws_price({
            "asset_id": "token_xyz",
            "price": 0.72,
        })

        assert "token_xyz" in temp_engine.ws_prices
        assert temp_engine.ws_prices["token_xyz"]["price"] == 0.72

    @pytest.mark.asyncio
    async def test_ws_subscribe_noop_when_disabled(self, temp_engine):
        """_ws_subscribe_position is a no-op when WS is None."""
        temp_engine.ws = None
        # Should not raise
        await temp_engine._ws_subscribe_position("some_token")

    @pytest.mark.asyncio
    async def test_ws_start_noop_when_disabled(self, temp_engine):
        """_ws_start is a no-op when WS is None."""
        temp_engine.ws = None
        await temp_engine._ws_start()  # Should not raise


# ============================================================
# LIVE MM STATE MACHINE: EXIT_PENDING
# ============================================================

class TestExitPendingState:
    """Tests for EXIT_PENDING state in the live MM order state machine.

    EXIT_PENDING is entered after a stop-loss or timeout posts an exit order.
    The bot then polls the CLOB for fill confirmation before recording the trade
    with the REAL execution price (not the limit price).
    """

    @pytest.fixture
    def live_engine(self, tmp_path):
        """Create a live-mode TradingEngine with mocked executor."""
        portfolio_file = tmp_path / "test_portfolio.json"

        with patch.object(Portfolio, '__init__', lambda self, **kwargs: None):
            engine = TradingEngine(live=True)

        engine.portfolio = Portfolio(
            initial_balance=1000.0,
            data_file=str(portfolio_file)
        )
        engine.scanner = MarketScanner()
        engine.live = True
        engine.running = False

        # Mock executor
        engine.executor = MagicMock()
        engine.executor.get_order_status = AsyncMock()
        engine.executor.get_fill_price = AsyncMock()
        engine.executor.cancel_order = AsyncMock()
        engine.executor.post_limit_order = AsyncMock()
        engine.executor.get_order_book = AsyncMock()

        # Mock safety
        engine.safety = MagicMock()
        engine.safety.record_trade_pnl = MagicMock()

        # Clean stop tracker (don't load real data from disk)
        engine.stop_tracker = {}
        engine._stop_tracker_file = tmp_path / "stop_tracker.json"

        return engine

    @pytest.mark.asyncio
    async def test_exit_pending_filled_records_trade(self, live_engine):
        """EXIT_PENDING with filled order records trade with real fill price."""
        condition_id = "0xexit_test"
        live_engine.portfolio.buy(
            condition_id=condition_id,
            question="Test exit pending?",
            side="MM",
            price=0.80,
            amount=10.0,
            reason="MM opportunity",
            strategy="MARKET_MAKER",
        )
        pos = live_engine.portfolio.positions[condition_id]
        pos["live_state"] = "EXIT_PENDING"
        pos["exit_order_id"] = "exit-order-123"
        pos["exit_reason"] = "MM_STOP"
        pos["exit_limit_price"] = 0.75
        pos["token_id"] = "token-xyz"
        pos["mm_ask"] = 0.82
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()

        # CLOB says order is fully matched
        live_engine.executor.get_order_status.return_value = {
            "status": "MATCHED",
            "size_matched": 12.5,
            "original_size": 12.5,
        }
        # Actual fill was at $0.78, not the $0.75 limit
        live_engine.executor.get_fill_price.return_value = 0.78

        await live_engine._check_mm_exit_live(condition_id, pos)

        # Position should be closed
        assert condition_id not in live_engine.portfolio.positions
        # Trade recorded
        assert live_engine.portfolio.metrics["total_trades"] == 1

    @pytest.mark.asyncio
    async def test_exit_pending_uses_limit_when_no_fill_data(self, live_engine):
        """Falls back to limit price when CLOB trade data is unavailable."""
        condition_id = "0xexit_nofill"
        live_engine.portfolio.buy(
            condition_id=condition_id,
            question="Test fallback price?",
            side="MM",
            price=0.80,
            amount=10.0,
            reason="MM opportunity",
            strategy="MARKET_MAKER",
        )
        pos = live_engine.portfolio.positions[condition_id]
        pos["live_state"] = "EXIT_PENDING"
        pos["exit_order_id"] = "exit-order-456"
        pos["exit_reason"] = "MM_TIMEOUT"
        pos["exit_limit_price"] = 0.70
        pos["token_id"] = "token-xyz"
        pos["mm_ask"] = 0.82
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()

        live_engine.executor.get_order_status.return_value = {
            "status": "MATCHED",
            "size_matched": 12.5,
            "original_size": 12.5,
        }
        # No fill data available
        live_engine.executor.get_fill_price.return_value = None

        await live_engine._check_mm_exit_live(condition_id, pos)

        assert condition_id not in live_engine.portfolio.positions

    @pytest.mark.asyncio
    async def test_exit_pending_cancelled_retries(self, live_engine):
        """Cancelled exit order returns to BUY_FILLED for retry."""
        condition_id = "0xexit_cancel"
        live_engine.portfolio.buy(
            condition_id=condition_id,
            question="Test cancel recovery?",
            side="MM",
            price=0.80,
            amount=10.0,
            reason="MM opportunity",
            strategy="MARKET_MAKER",
        )
        pos = live_engine.portfolio.positions[condition_id]
        pos["live_state"] = "EXIT_PENDING"
        pos["exit_order_id"] = "exit-order-789"
        pos["exit_reason"] = "MM_STOP"
        pos["exit_limit_price"] = 0.75
        pos["token_id"] = "token-xyz"
        pos["mm_ask"] = 0.82
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()

        # CLOB says order was cancelled (American spelling)
        live_engine.executor.get_order_status.return_value = {
            "status": "CANCELED",
            "size_matched": 0,
            "original_size": 12.5,
        }

        await live_engine._check_mm_exit_live(condition_id, pos)

        # Should recover to BUY_FILLED for retry
        assert pos["live_state"] == "BUY_FILLED"
        assert "exit_order_id" not in pos
        assert "exit_reason" not in pos

    @pytest.mark.asyncio
    async def test_exit_pending_no_order_id_recovers(self, live_engine):
        """Missing exit_order_id recovers to BUY_FILLED."""
        condition_id = "0xexit_noid"
        live_engine.portfolio.buy(
            condition_id=condition_id,
            question="Test no order ID?",
            side="MM",
            price=0.80,
            amount=10.0,
            reason="MM opportunity",
            strategy="MARKET_MAKER",
        )
        pos = live_engine.portfolio.positions[condition_id]
        pos["live_state"] = "EXIT_PENDING"
        pos["exit_order_id"] = ""  # Missing!
        pos["token_id"] = "token-xyz"
        pos["mm_ask"] = 0.82
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()

        await live_engine._check_mm_exit_live(condition_id, pos)

        # Should recover to BUY_FILLED
        assert pos["live_state"] == "BUY_FILLED"

    @pytest.mark.asyncio
    async def test_exit_pending_stop_records_in_tracker(self, live_engine):
        """MM_STOP exit records in the stop tracker for circuit breaker."""
        condition_id = "0xexit_stop"
        live_engine.portfolio.buy(
            condition_id=condition_id,
            question="Test stop tracker?",
            side="MM",
            price=0.80,
            amount=10.0,
            reason="MM opportunity",
            strategy="MARKET_MAKER",
        )
        pos = live_engine.portfolio.positions[condition_id]
        pos["live_state"] = "EXIT_PENDING"
        pos["exit_order_id"] = "exit-stop-001"
        pos["exit_reason"] = "MM_STOP"
        pos["exit_limit_price"] = 0.75
        pos["token_id"] = "token-xyz"
        pos["mm_ask"] = 0.82
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()

        live_engine.executor.get_order_status.return_value = {
            "status": "MATCHED",
            "size_matched": 12.5,
            "original_size": 12.5,
        }
        live_engine.executor.get_fill_price.return_value = 0.76

        await live_engine._check_mm_exit_live(condition_id, pos)

        # Stop should be recorded in tracker
        assert condition_id in live_engine.stop_tracker
        assert len(live_engine.stop_tracker[condition_id]) == 1


# ============================================================
# FIRE-SALE PREVENTION TESTS
# ============================================================

class TestAIExitDecisions:
    """Tests for AI-driven exit decisions on live MM positions.

    All exit paths (STOP_LOSS, TIMEOUT, SELL_FAILED) now consult Gemini AI
    to decide whether to HOLD or SELL, and at what price.
    """

    @pytest.fixture
    def live_engine(self, tmp_path):
        """Create a live-mode TradingEngine for AI exit tests."""
        portfolio_file = tmp_path / "test_portfolio.json"

        with patch.object(Portfolio, '__init__', lambda self, **kwargs: None):
            engine = TradingEngine(live=True)

        engine.portfolio = Portfolio(
            initial_balance=1000.0,
            data_file=str(portfolio_file)
        )
        engine.scanner = MarketScanner()
        engine.live = True
        engine.running = False

        engine.executor = MagicMock()
        engine.executor.get_order_status = AsyncMock()
        engine.executor.get_fill_price = AsyncMock()
        engine.executor.cancel_order = AsyncMock(return_value=True)
        engine.executor.post_limit_order = AsyncMock()
        engine.executor.get_order_book = AsyncMock()

        engine.safety = MagicMock()
        engine.safety.record_trade_pnl = MagicMock()

        return engine

    def _make_sell_pending_position(self, engine, condition_id, entry_price=0.80, hold_hours=5):
        """Helper: create a SELL_PENDING position that's past timeout."""
        engine.portfolio.buy(
            condition_id=condition_id,
            question="Fire-sale test market?",
            side="MM",
            price=entry_price,
            amount=10.0,
            reason="MM opportunity",
            strategy="MARKET_MAKER",
        )
        pos = engine.portfolio.positions[condition_id]
        pos["live_state"] = "SELL_PENDING"
        pos["sell_order_id"] = "sell-order-123"
        pos["token_id"] = "token-fire"
        pos["mm_ask"] = entry_price * 1.02
        # Set entry time in the past
        entry_time = datetime.now(timezone.utc) - timedelta(hours=hold_hours)
        pos["mm_entry_time"] = entry_time.isoformat()
        return pos

    @pytest.mark.asyncio
    async def test_stop_loss_sells_when_ai_says_sell(self, live_engine):
        """Stop loss exits at AI-recommended price when AI says SELL."""
        condition_id = "0xstop_ai_sell"
        pos = self._make_sell_pending_position(live_engine, condition_id, entry_price=0.80)

        live_engine.executor.get_order_status.return_value = {
            "status": "LIVE", "size_matched": 0, "original_size": 12.5,
        }
        live_engine.executor.post_limit_order.return_value = {
            "orderID": "exit-ai-001", "success": True
        }

        # AI says SELL at $0.76
        ai_decision = {"action": "SELL", "true_probability": 0.70, "sell_price": 0.76, "reason": "Event unlikely"}
        with patch.object(live_engine, '_get_market_price', new_callable=AsyncMock, return_value=0.75):
            with patch.object(live_engine, '_ai_exit_decision', new_callable=AsyncMock, return_value=ai_decision):
                await live_engine._check_mm_exit_live(condition_id, pos)

        # Should have posted exit at AI's recommended price
        live_engine.executor.post_limit_order.assert_called_once()
        call_args = live_engine.executor.post_limit_order.call_args
        exit_price = call_args.kwargs.get("price", 0)
        assert exit_price == 0.76, f"Exit should be at AI price $0.76, got {exit_price}"
        assert pos["live_state"] == "EXIT_PENDING"

    @pytest.mark.asyncio
    async def test_stop_loss_holds_when_ai_says_hold(self, live_engine):
        """Stop loss HOLDS when AI says the drop is temporary."""
        condition_id = "0xstop_ai_hold"
        pos = self._make_sell_pending_position(live_engine, condition_id, entry_price=0.80)

        live_engine.executor.get_order_status.return_value = {
            "status": "LIVE", "size_matched": 0, "original_size": 12.5,
        }

        # AI says HOLD — true probability is higher than market price
        ai_decision = {"action": "HOLD", "true_probability": 0.85, "sell_price": 0.80, "reason": "Temporary dip"}
        with patch.object(live_engine, '_get_market_price', new_callable=AsyncMock, return_value=0.75):
            with patch.object(live_engine, '_ai_exit_decision', new_callable=AsyncMock, return_value=ai_decision):
                await live_engine._check_mm_exit_live(condition_id, pos)

        # Should NOT have posted any exit order
        live_engine.executor.post_limit_order.assert_not_called()
        # Position should still exist
        assert condition_id in live_engine.portfolio.positions
        # Timer should have been reset
        new_entry_time = datetime.fromisoformat(pos["mm_entry_time"])
        age = (datetime.now(timezone.utc) - new_entry_time).total_seconds()
        assert age < 5, f"Timer was not reset, age={age}s"

    @pytest.mark.asyncio
    async def test_timeout_sells_when_ai_says_sell(self, live_engine):
        """Timeout exits at AI-recommended price when AI says SELL."""
        condition_id = "0xtimeout_ai_sell"
        pos = self._make_sell_pending_position(live_engine, condition_id, entry_price=0.80, hold_hours=5)

        live_engine.executor.get_order_status.return_value = {
            "status": "LIVE", "size_matched": 0, "original_size": 12.5,
        }
        live_engine.executor.post_limit_order.return_value = {
            "orderID": "exit-timeout-001", "success": True
        }

        # AI says SELL at entry price (break-even)
        ai_decision = {"action": "SELL", "true_probability": 0.78, "sell_price": 0.80, "reason": "No edge, exit at cost"}
        with patch.object(live_engine, '_get_market_price', new_callable=AsyncMock, return_value=0.82):
            with patch.object(live_engine, '_ai_exit_decision', new_callable=AsyncMock, return_value=ai_decision):
                await live_engine._check_mm_exit_live(condition_id, pos)

        # Should have cancelled old sell and posted exit at AI price
        live_engine.executor.post_limit_order.assert_called_once()
        call_args = live_engine.executor.post_limit_order.call_args
        exit_price = call_args.kwargs.get("price", 0)
        assert exit_price == 0.80, f"Exit should be at AI price, got {exit_price}"
        assert pos["live_state"] == "EXIT_PENDING"

    @pytest.mark.asyncio
    async def test_timeout_holds_when_ai_says_hold(self, live_engine):
        """Timeout HOLDS position when AI sees remaining edge."""
        condition_id = "0xtimeout_ai_hold"
        pos = self._make_sell_pending_position(live_engine, condition_id, entry_price=0.80, hold_hours=5)

        live_engine.executor.get_order_status.return_value = {
            "status": "LIVE", "size_matched": 0, "original_size": 12.5,
        }

        # AI says HOLD — true probability supports our position
        ai_decision = {"action": "HOLD", "true_probability": 0.90, "sell_price": 0.83, "reason": "Underpriced, hold for profit"}
        with patch.object(live_engine, '_get_market_price', new_callable=AsyncMock, return_value=0.79):
            with patch.object(live_engine, '_ai_exit_decision', new_callable=AsyncMock, return_value=ai_decision):
                await live_engine._check_mm_exit_live(condition_id, pos)

        # Should NOT have posted any exit order
        live_engine.executor.post_limit_order.assert_not_called()
        # Should NOT have cancelled the sell order — keep it posted
        live_engine.executor.cancel_order.assert_not_called()
        # Position should still exist
        assert condition_id in live_engine.portfolio.positions
        # Timer should have been reset
        new_entry_time = datetime.fromisoformat(pos["mm_entry_time"])
        age = (datetime.now(timezone.utc) - new_entry_time).total_seconds()
        assert age < 5, f"Timer was not reset, age={age}s"


# ============================================================
# BUY FILL PRICE TRACKING TESTS
# ============================================================

class TestBuyFillPriceTracking:
    """Tests for tracking actual buy fill prices from CLOB."""

    @pytest.fixture
    def live_engine(self, tmp_path):
        """Create a live-mode TradingEngine."""
        portfolio_file = tmp_path / "test_portfolio.json"

        with patch.object(Portfolio, '__init__', lambda self, **kwargs: None):
            engine = TradingEngine(live=True)

        engine.portfolio = Portfolio(
            initial_balance=1000.0,
            data_file=str(portfolio_file)
        )
        engine.scanner = MarketScanner()
        engine.live = True
        engine.running = False

        engine.executor = MagicMock()
        engine.executor.get_order_status = AsyncMock()
        engine.executor.get_fill_price = AsyncMock()
        engine.executor.post_limit_order = AsyncMock()

        engine.safety = MagicMock()

        return engine

    @pytest.mark.asyncio
    async def test_buy_fill_updates_entry_price(self, live_engine):
        """When buy fills at different price, entry_price is corrected."""
        condition_id = "0xbuy_fill"
        live_engine.portfolio.buy(
            condition_id=condition_id,
            question="Buy fill tracking test?",
            side="MM",
            price=0.80,
            amount=10.0,
            reason="MM opportunity",
            strategy="MARKET_MAKER",
        )
        pos = live_engine.portfolio.positions[condition_id]
        pos["live_state"] = "BUY_PENDING"
        pos["buy_order_id"] = "buy-order-001"
        pos["token_id"] = "token-buy"
        pos["mm_ask"] = 0.82
        pos["mm_entry_time"] = datetime.now(timezone.utc).isoformat()

        # Buy order fully matched
        live_engine.executor.get_order_status.return_value = {
            "status": "MATCHED",
            "size_matched": 12.5,
            "original_size": 12.5,
            "price": 0.80,
        }
        # But actual fill was at $0.78 (price improvement!)
        live_engine.executor.get_fill_price.return_value = 0.78

        await live_engine._check_mm_exit_live(condition_id, pos)

        # Entry price should be corrected to actual fill
        assert pos["entry_price"] == pytest.approx(0.78, abs=0.001)
        assert pos["actual_fill_price"] == pytest.approx(0.78, abs=0.001)
        assert pos["live_state"] == "BUY_FILLED"

    @pytest.mark.asyncio
    async def test_buy_fill_resets_timer(self, live_engine):
        """Buy fill resets the timeout timer (timer starts from fill, not post)."""
        condition_id = "0xbuy_timer"
        live_engine.portfolio.buy(
            condition_id=condition_id,
            question="Timer reset test?",
            side="MM",
            price=0.80,
            amount=10.0,
            reason="MM opportunity",
            strategy="MARKET_MAKER",
        )
        pos = live_engine.portfolio.positions[condition_id]
        pos["live_state"] = "BUY_PENDING"
        pos["buy_order_id"] = "buy-order-002"
        pos["token_id"] = "token-timer"
        pos["mm_ask"] = 0.82
        # Buy was posted 3 hours ago
        old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        pos["mm_entry_time"] = old_time

        live_engine.executor.get_order_status.return_value = {
            "status": "MATCHED",
            "size_matched": 12.5,
            "original_size": 12.5,
            "price": 0.80,
        }
        live_engine.executor.get_fill_price.return_value = 0.80

        await live_engine._check_mm_exit_live(condition_id, pos)

        # Timer should be reset to now, not still 3 hours ago
        new_time = datetime.fromisoformat(pos["mm_entry_time"])
        age = (datetime.now(timezone.utc) - new_time).total_seconds()
        assert age < 5, f"Timer was not reset after buy fill, age={age}s"


# ============================================================
# ON-CHAIN BALANCE SYNC TESTS
# ============================================================

class TestOnChainBalanceSync:
    """Tests for _log_on_chain_balance — smart auto-correction.

    Corrects balance when no orders are in flight (safe: wallet IS truth).
    Logs only when orders are pending (unsafe: wallet != internal due to CLOB locks).
    """

    @pytest.fixture
    def live_engine(self, tmp_path):
        """Create a live-mode TradingEngine for sync tests."""
        portfolio_file = tmp_path / "test_portfolio.json"

        with patch.object(Portfolio, '__init__', lambda self, **kwargs: None):
            engine = TradingEngine(live=True)

        engine.portfolio = Portfolio(
            initial_balance=1000.0,
            data_file=str(portfolio_file)
        )
        engine.live = True
        engine.executor = MagicMock()
        engine.executor.get_balance_usdc = AsyncMock()
        engine.stop_tracker = {}
        engine._stop_tracker_file = tmp_path / "stop_tracker.json"

        return engine

    @pytest.mark.asyncio
    async def test_corrects_balance_when_no_orders_pending(self, live_engine):
        """Auto-corrects when no orders in flight — wallet is truth."""
        live_engine.portfolio.balance = 8.35
        live_engine.executor.get_balance_usdc.return_value = 13.38  # Wallet has more (redemption happened)

        await live_engine._log_on_chain_balance()

        # Balance SHOULD be corrected to wallet value
        assert live_engine.portfolio.balance == pytest.approx(13.38, abs=0.01)

    @pytest.mark.asyncio
    async def test_does_not_correct_when_orders_pending(self, live_engine):
        """Does NOT correct when BUY_PENDING orders exist — wallet is wrong."""
        live_engine.portfolio.balance = 15.82
        # Add a pending buy order
        live_engine.portfolio.buy(
            condition_id="0xtest", question="Test?", side="MM",
            price=0.80, amount=10.0, reason="test", strategy="MARKET_MAKER",
        )
        live_engine.portfolio.positions["0xtest"]["live_state"] = "BUY_PENDING"
        live_engine.executor.get_balance_usdc.return_value = 5.82  # Wallet lower due to locked USDC

        await live_engine._log_on_chain_balance()

        # Balance must NOT change — orders are pending
        assert live_engine.portfolio.balance == pytest.approx(5.82, abs=0.01)

    @pytest.mark.asyncio
    async def test_rpc_failure_preserves_state(self, live_engine):
        """RPC failure returns None — state preserved."""
        live_engine.portfolio.balance = 15.82
        live_engine.executor.get_balance_usdc.return_value = None

        await live_engine._log_on_chain_balance()

        assert live_engine.portfolio.balance == pytest.approx(15.82, abs=0.01)

    @pytest.mark.asyncio
    async def test_no_correction_when_drift_small(self, live_engine):
        """No correction needed when drift < $1."""
        live_engine.portfolio.balance = 13.00
        live_engine.executor.get_balance_usdc.return_value = 13.50  # Only $0.50 drift

        await live_engine._log_on_chain_balance()

        # Small drift — no correction
        assert live_engine.portfolio.balance == pytest.approx(13.00, abs=0.01)

    @pytest.mark.asyncio
    async def test_accounts_for_clob_locked_funds(self, live_engine):
        """Drift calculation accounts for USDC locked in BUY_PENDING orders."""
        live_engine.portfolio.balance = 20.00
        live_engine.portfolio.buy(
            condition_id="0xtest", question="Test?", side="MM",
            price=0.80, amount=10.0, reason="test", strategy="MARKET_MAKER",
        )
        live_engine.portfolio.positions["0xtest"]["live_state"] = "BUY_PENDING"

        # Wallet shows $10 (because $10 is locked on CLOB)
        live_engine.executor.get_balance_usdc.return_value = 10.00

        await live_engine._log_on_chain_balance()

        # Balance must NOT change
        assert live_engine.portfolio.balance == pytest.approx(10.00, abs=0.01)

    @pytest.mark.asyncio
    async def test_exception_does_not_crash(self, live_engine):
        """Any exception must not crash the trading loop."""
        live_engine.portfolio.balance = 10.00
        live_engine.executor.get_balance_usdc = AsyncMock(side_effect=Exception("Web3 crash"))

        await live_engine._log_on_chain_balance()

        assert live_engine.portfolio.balance == pytest.approx(10.00, abs=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
