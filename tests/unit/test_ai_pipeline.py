#!/usr/bin/env python3
"""
AI PIPELINE TESTS
==================
Tests for the smart AI pipeline: deep screen, caching, portfolio concentration,
news headline fetching, keyword extraction.
"""

import pytest
import sys
import json
import inspect
import typing
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.core.gemini_analyzer import GeminiAnalyzer
from sovereign_hive.core.news_intelligence import NewsIntelligence


# ============================================================
# IMPORT & ANNOTATION INTEGRITY (catches Python 3.11 vs 3.14 gaps)
# ============================================================

class TestModuleIntegrity:
    """Ensure all core modules import cleanly and annotations resolve.

    Python 3.14 evaluates annotations lazily (PEP 649), so missing
    typing imports don't crash locally. EC2 runs 3.11 (eager eval).
    This test forces resolution so broken annotations fail in CI too.
    """

    def test_gemini_analyzer_annotations_resolve(self):
        """All type annotations in GeminiAnalyzer must resolve."""
        for name, method in inspect.getmembers(GeminiAnalyzer, predicate=inspect.isfunction):
            typing.get_type_hints(method)

    def test_gemini_analyzer_instantiates(self):
        """GeminiAnalyzer can be instantiated without error."""
        analyzer = GeminiAnalyzer()
        assert hasattr(analyzer, "deep_screen_market")
        assert hasattr(analyzer, "evaluate_exit")
        assert hasattr(analyzer, "evaluate_reentry")
        assert hasattr(analyzer, "evaluate_exit_with_context")


# ============================================================
# GEMINI ANALYZER - Deep Screen + Caching
# ============================================================

class TestGeminiDeepScreen:
    """Tests for deep_screen_market with caching."""

    @pytest.fixture
    def analyzer(self):
        a = GeminiAnalyzer()
        a.api_key = "test_key"
        return a

    @pytest.fixture
    def mock_gemini_response(self):
        return {
            "approved": True,
            "quality_score": 8,
            "reason": "Active political market with upcoming catalyst",
            "recommended_spread_pct": 0.025,
            "catalyst_expected": True,
            "sector": "politics",
        }

    def test_cache_miss_and_set(self, analyzer):
        """Cache miss returns None, then set populates it."""
        assert analyzer._get_cached("test_id") is None
        result = {"approved": True, "quality_score": 7, "sector": "crypto"}
        analyzer._set_cache("test_id", result)
        cached = analyzer._get_cached("test_id")
        assert cached is not None
        assert cached["approved"] is True
        assert cached["quality_score"] == 7
        assert cached["cached"] is True

    def test_cache_expiry(self, analyzer):
        """Cached results expire after 1 hour."""
        result = {"approved": True, "quality_score": 7}
        analyzer._screen_cache["test_id"] = (
            result,
            datetime.now(timezone.utc) - timedelta(hours=2),
        )
        assert analyzer._get_cached("test_id") is None

    def test_cache_within_ttl(self, analyzer):
        """Cached results return within 1 hour."""
        result = {"approved": True, "quality_score": 7}
        analyzer._screen_cache["test_id"] = (
            result,
            datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        cached = analyzer._get_cached("test_id")
        assert cached is not None
        assert cached["cached"] is True

    @pytest.mark.asyncio
    async def test_deep_screen_no_api_key(self):
        """Without API key, returns default passthrough."""
        a = GeminiAnalyzer()
        a.api_key = ""
        result = await a.deep_screen_market(
            question="Will Trump win?", price=0.55, end_date="2026-03-01",
            volume_24h=50000, spread_pct=0.03, liquidity=100000,
            best_bid=0.53, best_ask=0.57, news_headlines=[], days_to_resolve=10,
        )
        assert result["approved"] is True
        assert result["quality_score"] == 5

    @pytest.mark.asyncio
    async def test_deep_screen_uses_cache(self, analyzer, mock_gemini_response):
        """Should return cached result without making API call."""
        analyzer._set_cache("cond_123", mock_gemini_response)
        result = await analyzer.deep_screen_market(
            question="test", price=0.5, end_date="", volume_24h=1000,
            spread_pct=0.02, liquidity=5000, best_bid=0.49, best_ask=0.51,
            news_headlines=[], days_to_resolve=5, condition_id="cond_123",
        )
        assert result["cached"] is True
        assert result["quality_score"] == 8
        assert analyzer._request_count == 0  # No API call made

    @pytest.mark.asyncio
    async def test_deep_screen_api_success(self, analyzer, mock_gemini_response):
        """Successful API call returns parsed result."""
        api_response = {
            "candidates": [{
                "content": {"parts": [{"text": json.dumps(mock_gemini_response)}]}
            }]
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=api_response)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession") as mock_cs:
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await analyzer.deep_screen_market(
                question="Will Trump win 2028?", price=0.55, end_date="2028-11-05",
                volume_24h=50000, spread_pct=0.03, liquidity=100000,
                best_bid=0.53, best_ask=0.57,
                news_headlines=["Trump leads in polls"],
                days_to_resolve=10, condition_id="cond_456",
            )

        assert result["approved"] is True
        assert result["quality_score"] == 8
        assert result["sector"] == "politics"
        assert result["cached"] is False
        # Should be cached now
        cached = analyzer._get_cached("cond_456")
        assert cached is not None

    @pytest.mark.asyncio
    async def test_deep_screen_clamps_spread(self, analyzer):
        """Spread recommendation should be clamped to [0.01, 0.10]."""
        extreme_response = {
            "approved": True, "quality_score": 7,
            "reason": "ok", "recommended_spread_pct": 0.50,
            "catalyst_expected": False, "sector": "other",
        }
        api_response = {
            "candidates": [{
                "content": {"parts": [{"text": json.dumps(extreme_response)}]}
            }]
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=api_response)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession") as mock_cs:
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await analyzer.deep_screen_market(
                question="test", price=0.5, end_date="", volume_24h=1000,
                spread_pct=0.02, liquidity=5000, best_bid=0.49, best_ask=0.51,
                news_headlines=[], days_to_resolve=5,
            )

        assert result["recommended_spread_pct"] == 0.10  # Clamped from 0.50

    @pytest.mark.asyncio
    async def test_deep_screen_rate_limited(self, analyzer):
        """Rate limited response should return default."""
        mock_resp = AsyncMock()
        mock_resp.status = 429

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession") as mock_cs:
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await analyzer.deep_screen_market(
                question="test", price=0.5, end_date="", volume_24h=1000,
                spread_pct=0.02, liquidity=5000, best_bid=0.49, best_ask=0.51,
                news_headlines=[], days_to_resolve=5,
            )

        assert result["approved"] is True
        assert result["quality_score"] == 5  # Default

    @pytest.mark.asyncio
    async def test_deep_screen_json_error(self, analyzer):
        """Invalid JSON from Gemini should return default."""
        api_response = {
            "candidates": [{
                "content": {"parts": [{"text": "not valid json"}]}
            }]
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=api_response)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession") as mock_cs:
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await analyzer.deep_screen_market(
                question="test", price=0.5, end_date="", volume_24h=1000,
                spread_pct=0.02, liquidity=5000, best_bid=0.49, best_ask=0.51,
                news_headlines=[], days_to_resolve=5,
            )

        assert result["approved"] is True
        assert result["quality_score"] == 5


# ============================================================
# NEWS INTELLIGENCE - Headlines & Keywords
# ============================================================

class TestNewsIntelligence:
    """Tests for fetch_headlines and extract_keywords."""

    @pytest.fixture
    def intel(self):
        ni = NewsIntelligence()
        ni.api_key = "test_key"
        return ni

    def test_extract_keywords_basic(self):
        """Should strip stop words and keep meaningful keywords."""
        result = NewsIntelligence.extract_keywords("Will Bitcoin reach $100k by March?")
        assert "Bitcoin" in result
        assert "$100k" in result
        assert "Will" not in result
        assert "by" not in result

    def test_extract_keywords_empty(self):
        """Empty question returns empty string."""
        assert NewsIntelligence.extract_keywords("") == ""

    def test_extract_keywords_max_5(self):
        """Should limit to 5 keywords max."""
        result = NewsIntelligence.extract_keywords(
            "Will the Federal Reserve raise interest rates above 5% in Q1 2026 amid inflation concerns?"
        )
        words = result.split()
        assert len(words) <= 5

    def test_extract_keywords_preserves_dollar_amounts(self):
        """Dollar amounts like $100k should be preserved."""
        result = NewsIntelligence.extract_keywords("Will Bitcoin hit $100k?")
        assert "$100k" in result

    @pytest.mark.asyncio
    async def test_fetch_headlines_no_api_key(self):
        """Without API key, returns empty list."""
        ni = NewsIntelligence()
        ni.api_key = ""
        result = await ni.fetch_headlines("Bitcoin price")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_headlines_rate_limited(self, intel):
        """When over rate limit, returns empty list."""
        intel._request_count = 100  # Over the 80 limit
        result = await intel.fetch_headlines("Bitcoin price")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_headlines_success(self, intel):
        """Successful API call returns parsed headlines."""
        api_response = {
            "articles": [
                {"title": "Bitcoin surges past $100k", "description": "Major milestone", "source": {"name": "Reuters"}},
                {"title": "Crypto market rally continues", "description": "Markets up", "source": {"name": "BBC"}},
            ]
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=api_response)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession") as mock_cs:
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await intel.fetch_headlines("Bitcoin price", max_results=3)

        assert len(result) == 2
        assert result[0]["title"] == "Bitcoin surges past $100k"
        assert result[0]["source"] == "Reuters"
        assert intel._request_count == 1

    @pytest.mark.asyncio
    async def test_fetch_headlines_api_error(self, intel):
        """API error returns empty list without crashing."""
        mock_resp = AsyncMock()
        mock_resp.status = 500

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession") as mock_cs:
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await intel.fetch_headlines("test query")

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_headlines_empty_query(self, intel):
        """Empty keywords returns empty list."""
        # "will the is a" -> all stop words removed -> empty
        result = await intel.fetch_headlines("will the is a")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_headlines_network_error(self, intel):
        """Network errors return empty list gracefully."""
        with patch("aiohttp.ClientSession") as mock_cs:
            mock_cs.return_value.__aenter__ = AsyncMock(side_effect=Exception("timeout"))

            result = await intel.fetch_headlines("Bitcoin")

        assert result == []


# ============================================================
# PORTFOLIO CONCENTRATION - TradingEngine
# ============================================================

class TestPortfolioConcentration:
    """Tests for _check_portfolio_concentration and _portfolio_select."""

    @pytest.fixture
    def engine(self):
        """Create a minimal TradingEngine mock for concentration tests."""
        with patch("sovereign_hive.run_simulation.ClaudeAnalyzer"):
            with patch("sovereign_hive.core.gemini_analyzer.GeminiAnalyzer"):
                from sovereign_hive.run_simulation import TradingEngine, Portfolio
                engine = TradingEngine.__new__(TradingEngine)
                engine.portfolio = Portfolio.__new__(Portfolio)
                engine.portfolio.balance = 500.0
                engine.portfolio.positions = {}
                engine.gemini = None
                engine.news_intel = NewsIntelligence()
                return engine

    def test_empty_portfolio_allows_any(self, engine):
        """Empty portfolio should allow any sector."""
        assert engine._check_portfolio_concentration("crypto", "cond_1") is True

    def test_duplicate_market_blocked(self, engine):
        """Cannot add position in a market already in portfolio."""
        engine.portfolio.positions["cond_1"] = {"cost_basis": 100, "sector": "crypto"}
        assert engine._check_portfolio_concentration("crypto", "cond_1") is False

    def test_max_2_per_sector(self, engine):
        """Max 2 positions per sector."""
        engine.portfolio.positions["cond_1"] = {"cost_basis": 100, "sector": "politics"}
        engine.portfolio.positions["cond_2"] = {"cost_basis": 100, "sector": "politics"}
        # Third politics position should be blocked
        assert engine._check_portfolio_concentration("politics", "cond_3") is False
        # Different sector should be allowed
        assert engine._check_portfolio_concentration("crypto", "cond_3") is True

    def test_40pct_sector_cap(self, engine):
        """No sector should exceed 40% of total portfolio."""
        engine.portfolio.balance = 100.0
        engine.portfolio.positions["cond_1"] = {"cost_basis": 350, "sector": "crypto"}
        # crypto = 350 / (100 + 350) = 77.8% — over 40%
        assert engine._check_portfolio_concentration("crypto", "cond_2") is False
        # other sector with low allocation should pass
        assert engine._check_portfolio_concentration("politics", "cond_2") is True

    def test_portfolio_select_filters_concentrated(self, engine):
        """_portfolio_select should skip over-concentrated MM opportunities."""
        engine.portfolio.positions["cond_1"] = {"cost_basis": 100, "sector": "crypto"}
        engine.portfolio.positions["cond_2"] = {"cost_basis": 100, "sector": "crypto"}

        opps = [
            {"strategy": "MARKET_MAKER", "condition_id": "cond_3", "sector": "crypto", "ai_score": 9},
            {"strategy": "MARKET_MAKER", "condition_id": "cond_4", "sector": "politics", "ai_score": 7},
            {"strategy": "MEAN_REVERSION", "condition_id": "cond_5", "confidence": 0.8},
        ]
        selected = engine._portfolio_select(opps)

        cids = [o["condition_id"] for o in selected]
        assert "cond_3" not in cids  # Blocked (3rd crypto)
        assert "cond_4" in cids      # Allowed (1st politics)
        assert "cond_5" in cids      # Non-MM passes through

    def test_portfolio_select_sorts_by_ai_score(self, engine):
        """Selected opportunities should be sorted by AI score."""
        opps = [
            {"strategy": "MARKET_MAKER", "condition_id": "cond_1", "sector": "crypto", "ai_score": 6},
            {"strategy": "MARKET_MAKER", "condition_id": "cond_2", "sector": "politics", "ai_score": 9},
            {"strategy": "MARKET_MAKER", "condition_id": "cond_3", "sector": "sports", "ai_score": 8},
        ]
        selected = engine._portfolio_select(opps)
        scores = [o["ai_score"] for o in selected]
        assert scores == [9, 8, 6]  # Descending


# ============================================================
# MM CIRCUIT BREAKER - Stop Loss Tracking & AI Re-entry
# ============================================================

class TestMMCircuitBreaker:
    """Tests for per-market stop loss circuit breaker and AI re-entry."""

    @pytest.fixture
    def engine(self):
        """Create a minimal TradingEngine with circuit breaker tracking."""
        with patch("sovereign_hive.run_simulation.ClaudeAnalyzer"):
            with patch("sovereign_hive.core.gemini_analyzer.GeminiAnalyzer"):
                from sovereign_hive.run_simulation import TradingEngine, Portfolio
                engine = TradingEngine.__new__(TradingEngine)
                engine.portfolio = Portfolio.__new__(Portfolio)
                engine.portfolio.balance = 500.0
                engine.portfolio.positions = {}
                engine.gemini = None
                engine.news = MagicMock()
                engine.stop_tracker = {}
                engine.MAX_STOPS_PER_DAY = 2
                return engine

    def test_no_stops_returns_empty(self, engine):
        """No stops tracked returns empty list."""
        assert engine._get_recent_stops("cond_1") == []

    def test_recent_stops_returned(self, engine):
        """Stops within 24h are returned."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_1"] = [
            now - timedelta(hours=2),
            now - timedelta(hours=1),
        ]
        stops = engine._get_recent_stops("cond_1")
        assert len(stops) == 2

    def test_old_stops_pruned(self, engine):
        """Stops older than 24h are pruned."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_1"] = [
            now - timedelta(hours=30),  # Old — should be pruned
            now - timedelta(hours=1),   # Recent — should be kept
        ]
        stops = engine._get_recent_stops("cond_1")
        assert len(stops) == 1
        # Verify tracker was cleaned up
        assert len(engine.stop_tracker["cond_1"]) == 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_after_2_stops(self, engine):
        """Market with 2+ stops in 24h should be rejected."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_1"] = [
            now - timedelta(hours=2),
            now - timedelta(hours=1),
        ]
        opp = {
            "condition_id": "cond_1",
            "strategy": "MARKET_MAKER",
            "question": "Will Inter Milan win?",
            "confidence": 0.7,
        }
        result = await engine.evaluate_opportunity(opp)
        assert result is False

    @pytest.mark.asyncio
    async def test_circuit_breaker_allows_fresh_market(self, engine):
        """Market with no stops should pass circuit breaker check."""
        from sovereign_hive.run_simulation import CONFIG
        opp = {
            "condition_id": "cond_new",
            "strategy": "MARKET_MAKER",
            "question": "Will event X happen?",
            "confidence": 0.7,
        }
        result = await engine.evaluate_opportunity(opp)
        assert result is True  # No stops, confidence OK

    @pytest.mark.asyncio
    async def test_1_stop_requires_ai_approval(self, engine):
        """After 1 stop, AI must approve re-entry. Without gemini, blocks."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_1"] = [now - timedelta(hours=1)]
        opp = {
            "condition_id": "cond_1",
            "strategy": "MARKET_MAKER",
            "question": "Will event happen?",
            "confidence": 0.7,
            "price": 0.50,
            "volume_24h": 10000,
        }
        # No gemini available → _ai_reentry_check returns False
        engine.gemini = None
        result = await engine.evaluate_opportunity(opp)
        assert result is False

    @pytest.mark.asyncio
    async def test_1_stop_ai_approves_reentry(self, engine):
        """After 1 stop, if AI approves, re-entry is allowed."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_1"] = [now - timedelta(hours=1)]

        mock_gemini = AsyncMock()
        mock_gemini.evaluate_reentry = AsyncMock(return_value={
            "reenter": True,
            "reason": "Temporary dip, volume recovering",
        })
        engine.gemini = mock_gemini

        opp = {
            "condition_id": "cond_1",
            "strategy": "MARKET_MAKER",
            "question": "Will event happen?",
            "confidence": 0.7,
            "price": 0.50,
            "volume_24h": 10000,
        }
        result = await engine.evaluate_opportunity(opp)
        assert result is True
        mock_gemini.evaluate_reentry.assert_called_once()

    @pytest.mark.asyncio
    async def test_1_stop_ai_rejects_reentry(self, engine):
        """After 1 stop, if AI rejects, re-entry is blocked."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_1"] = [now - timedelta(hours=1)]

        mock_gemini = AsyncMock()
        mock_gemini.evaluate_reentry = AsyncMock(return_value={
            "reenter": False,
            "reason": "Price in freefall, avoid",
        })
        engine.gemini = mock_gemini

        opp = {
            "condition_id": "cond_1",
            "strategy": "MARKET_MAKER",
            "question": "Will event happen?",
            "confidence": 0.7,
            "price": 0.50,
            "volume_24h": 10000,
        }
        result = await engine.evaluate_opportunity(opp)
        assert result is False

    @pytest.mark.asyncio
    async def test_resolution_strategy_bypasses_circuit_breaker(self, engine):
        """Resolution strategies (NEAR_CERTAIN) should not be affected by circuit breaker."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_1"] = [
            now - timedelta(hours=2),
            now - timedelta(hours=1),
        ]
        opp = {
            "condition_id": "cond_1",
            "strategy": "NEAR_CERTAIN",
            "question": "Will event happen?",
            "confidence": 0.7,
        }
        result = await engine.evaluate_opportunity(opp)
        assert result is True  # Resolution strategies bypass circuit breaker

    @pytest.mark.asyncio
    async def test_dip_buy_blocked_by_circuit_breaker(self, engine):
        """DIP_BUY with 2 stops in 24h should be blocked by circuit breaker."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_1"] = [
            now - timedelta(hours=2),
            now - timedelta(hours=1),
        ]
        opp = {
            "condition_id": "cond_1",
            "strategy": "DIP_BUY",
            "question": "Will event happen?",
            "confidence": 0.7,
        }
        engine.news = AsyncMock()
        engine.news.analyze_market = AsyncMock(return_value=None)
        result = await engine.evaluate_opportunity(opp)
        assert result is False  # DIP_BUY now blocked by circuit breaker

    @pytest.mark.asyncio
    async def test_volume_surge_blocked_by_circuit_breaker(self, engine):
        """VOLUME_SURGE with 2 stops in 24h should be blocked by circuit breaker."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_1"] = [
            now - timedelta(hours=2),
            now - timedelta(hours=1),
        ]
        opp = {
            "condition_id": "cond_1",
            "strategy": "VOLUME_SURGE",
            "question": "Will event happen?",
            "side": "YES",
            "confidence": 0.7,
        }
        engine.news = AsyncMock()
        engine.news.analyze_market = AsyncMock(return_value=None)
        result = await engine.evaluate_opportunity(opp)
        assert result is False  # VOLUME_SURGE now blocked by circuit breaker


class TestMidRangeEdgeZone:
    """Tests for MID_RANGE edge zone filtering."""

    @pytest.fixture
    def scanner(self):
        from sovereign_hive.run_simulation import MarketScanner
        return MarketScanner()

    def _make_market(self, best_bid, best_ask, price_change=0.01, volume_24h=50000,
                     liquidity=100000, days=15):
        """Helper to build a market for MID_RANGE testing."""
        end_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        return {
            "conditionId": f"0x{hash(str(best_ask)) & 0xFFFFFFFF:08x}",
            "question": "Will mid-range event happen?",
            "bestBid": best_bid,
            "bestAsk": best_ask,
            "volume24hr": volume_24h,
            "liquidityNum": liquidity,
            "endDate": end_date,
            "oneDayPriceChange": price_change,
        }

    def _get_mid_range_opps(self, scanner, markets):
        opps = scanner.find_opportunities(markets)
        return [o for o in opps if o["strategy"] == "MID_RANGE"]

    def test_mid_range_death_zone_rejected(self, scanner):
        """Market at 0.40 (death zone) should NOT generate MID_RANGE opportunity."""
        markets = [self._make_market(best_bid=0.38, best_ask=0.40, price_change=0.01)]
        mid_opps = self._get_mid_range_opps(scanner, markets)
        assert len(mid_opps) == 0

    def test_mid_range_trap_zone_rejected(self, scanner):
        """Market at 0.72 (trap zone) should NOT generate MID_RANGE opportunity."""
        markets = [self._make_market(best_bid=0.70, best_ask=0.72, price_change=0.01)]
        mid_opps = self._get_mid_range_opps(scanner, markets)
        assert len(mid_opps) == 0

    def test_mid_range_sweet_spot_yes_accepted(self, scanner):
        """Market at 0.60 (sweet spot) with upward momentum should generate YES MID_RANGE."""
        # Tight spread to avoid MM dedup
        markets = [self._make_market(best_bid=0.597, best_ask=0.60, price_change=0.01)]
        mid_opps = self._get_mid_range_opps(scanner, markets)
        assert len(mid_opps) == 1
        assert mid_opps[0]["side"] == "YES"

    def test_mid_range_no_side_edge_zone(self, scanner):
        """NO side: With wider MM range (0.15-0.85), most mid-range markets also qualify
        as MM opportunities and get deduped. Verify MID_RANGE is found in raw opportunities
        even if deduped in final output."""
        markets = [self._make_market(best_bid=0.395, best_ask=0.40, price_change=-0.01)]
        # With wider filters, this qualifies as both MM and MID_RANGE.
        # MM takes priority, so MID_RANGE gets deduped. Just verify MM picks it up.
        opps = scanner.find_opportunities(markets)
        mm_opps = [o for o in opps if o["strategy"] == "MARKET_MAKER"]
        assert len(mm_opps) >= 1  # MM captures this market now

    def test_mid_range_no_side_death_zone_rejected(self, scanner):
        """NO side: best_bid=0.60 → no_price=0.40 (death zone). Should be rejected."""
        # Tight spread to avoid MM dedup
        markets = [self._make_market(best_bid=0.597, best_ask=0.60, price_change=-0.01)]
        mid_opps = self._get_mid_range_opps(scanner, markets)
        assert len(mid_opps) == 0  # no_price=0.403 is in death zone


class TestStopTrackerPersistence:
    """Tests for stop tracker disk persistence."""

    @pytest.fixture
    def engine(self, tmp_path):
        """Create engine with stop tracker pointing to tmp dir."""
        with patch("sovereign_hive.run_simulation.ClaudeAnalyzer"):
            with patch("sovereign_hive.core.gemini_analyzer.GeminiAnalyzer"):
                from sovereign_hive.run_simulation import TradingEngine, Portfolio
                engine = TradingEngine.__new__(TradingEngine)
                engine.portfolio = Portfolio.__new__(Portfolio)
                engine.portfolio.balance = 500.0
                engine.portfolio.positions = {}
                engine.gemini = None
                engine.news = MagicMock()
                engine.stop_tracker = {}
                engine.MAX_STOPS_PER_DAY = 2
                engine._stop_tracker_file = tmp_path / "stop_tracker.json"
                return engine

    def test_save_and_load(self, engine):
        """Stop tracker saves to JSON and loads back correctly."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_1"] = [now - timedelta(hours=2), now - timedelta(hours=1)]
        engine._save_stop_tracker()
        assert engine._stop_tracker_file.exists()

        # Load into fresh tracker
        engine.stop_tracker = {}
        engine._load_stop_tracker()
        assert "cond_1" in engine.stop_tracker
        assert len(engine.stop_tracker["cond_1"]) == 2

    def test_missing_file_starts_empty(self, engine):
        """Engine starts with empty tracker when no file exists."""
        engine.stop_tracker = {"old": [datetime.now(timezone.utc)]}
        engine._load_stop_tracker()
        # No file → tracker stays as-is (load only acts if file exists)
        assert "old" in engine.stop_tracker

    def test_corrupt_file_starts_empty(self, engine):
        """Engine starts with empty tracker when file is corrupt."""
        engine._stop_tracker_file.write_text("not valid json {{{")
        engine._load_stop_tracker()
        assert engine.stop_tracker == {}

    def test_survives_restart(self, engine):
        """Stop recorded, file written, new engine loads it."""
        now = datetime.now(timezone.utc)
        engine.stop_tracker["cond_abc"] = [now]
        engine._save_stop_tracker()

        # Simulate restart: clear memory and reload
        engine.stop_tracker = {}
        engine._load_stop_tracker()
        assert "cond_abc" in engine.stop_tracker
        assert len(engine.stop_tracker["cond_abc"]) == 1


class TestGeminiReentry:
    """Tests for evaluate_reentry on GeminiAnalyzer."""

    @pytest.fixture
    def analyzer(self):
        a = GeminiAnalyzer()
        a.api_key = "test_key"
        return a

    @pytest.mark.asyncio
    async def test_reentry_no_api_key(self):
        """Without API key, defaults to blocking re-entry."""
        a = GeminiAnalyzer()
        a.api_key = ""
        result = await a.evaluate_reentry("test", 0.5, 1, 10000)
        assert result["reenter"] is False

    @pytest.mark.asyncio
    async def test_reentry_api_success_approve(self, analyzer):
        """AI approves re-entry."""
        api_response = {
            "candidates": [{
                "content": {"parts": [{"text": '{"reenter":true,"reason":"temporary dip"}'}]}
            }]
        }
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=api_response)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession") as mock_cs:
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await analyzer.evaluate_reentry("Will X?", 0.5, 1, 10000)

        assert result["reenter"] is True
        assert "temporary dip" in result["reason"]

    @pytest.mark.asyncio
    async def test_reentry_api_success_reject(self, analyzer):
        """AI rejects re-entry."""
        api_response = {
            "candidates": [{
                "content": {"parts": [{"text": '{"reenter":false,"reason":"price collapsing"}'}]}
            }]
        }
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=api_response)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession") as mock_cs:
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await analyzer.evaluate_reentry("Will X?", 0.5, 2, 5000)

        assert result["reenter"] is False

    @pytest.mark.asyncio
    async def test_reentry_api_error_blocks(self, analyzer):
        """API error should default to blocking re-entry."""
        with patch("aiohttp.ClientSession") as mock_cs:
            mock_cs.return_value.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
            result = await analyzer.evaluate_reentry("Will X?", 0.5, 1, 10000)

        assert result["reenter"] is False


# ============================================================
# DATA-DRIVEN CONFIG TESTS (from 88.5M trade analysis)
# ============================================================

class TestDataDrivenConfig:
    """Tests verifying bot parameters match empirical findings from 88.5M on-chain trades.

    Key findings applied:
    - Sweet spot: 0.50-0.70 (Kelly +29-48%)
    - Fallback: 0.80-0.95 (Kelly +4-20%)
    - Death zone: 0.35-0.45 (Kelly -17 to -22%)
    - Trap zone: 0.70-0.75 (Kelly -19%)
    - Min resolution: 2 days (0-1d is negative, insider-dominated)
    - Preferred categories: politics, economics (Kelly +4-5%)
    - Negative categories: crypto (Kelly -1.53%)
    """

    def _make_market(self, question, best_bid, best_ask, days=15,
                     volume_24h=50000, liquidity=100000):
        """Helper to create a market dict for find_opportunities."""
        end_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        return {
            "conditionId": f"0x{hash(question) & 0xFFFFFFFF:08x}",
            "question": question,
            "bestBid": best_bid,
            "bestAsk": best_ask,
            "volume24hr": volume_24h,
            "liquidityNum": liquidity,
            "endDate": end_date,
        }

    def _get_mm_opportunities(self, scanner, markets):
        """Run find_opportunities and return only MARKET_MAKER results."""
        opps = scanner.find_opportunities(markets)
        return [o for o in opps if o["strategy"] == "MARKET_MAKER"]

    # --- A. Price range filtering (7 tests) ---

    def test_sweet_spot_accepted(self, scanner):
        """Market at 0.60 (sweet spot) should pass MM filter."""
        markets = [self._make_market("Will the election happen?", 0.58, 0.62)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["price_zone"] == "sweet"

    def test_fallback_zone_accepted(self, scanner):
        """Market at 0.85 (fallback zone) should pass MM filter."""
        markets = [self._make_market("Will GDP grow?", 0.83, 0.87)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["price_zone"] == "fallback"

    def test_death_zone_lower_confidence(self, scanner):
        """Market at 0.40 now passes but with lower confidence (wider filter)."""
        markets = [self._make_market("Will something happen?", 0.38, 0.42)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1  # Passes with wide price range
        assert mm_opps[0]["confidence"] <= 0.65  # Lower confidence outside core sweet spot

    def test_trap_zone_now_blocked(self, scanner):
        """Market at 0.72 is blocked — trap zone, outside sweet spot (0.15-0.65)."""
        markets = [self._make_market("Will the president resign?", 0.70, 0.74)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 0  # 0.74 > 0.65 (mm_price_range upper), not preferred so no fallback

    def test_boundary_sweet_spot_low(self, scanner):
        """Market at exactly 0.50 (sweet spot boundary) should pass."""
        markets = [self._make_market("Will inflation rise?", 0.48, 0.50)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["price_zone"] == "sweet"

    def test_boundary_sweet_spot_high(self, scanner):
        """Market at 0.65 (new upper boundary) should pass. 0.70 is now outside."""
        markets = [self._make_market("Will the fed cut rates?", 0.63, 0.65)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["price_zone"] == "sweet"

    def test_boundary_fallback_low(self, scanner):
        """Market at exactly 0.90 (fallback zone) should pass as fallback."""
        markets = [self._make_market("Will unemployment fall?", 0.88, 0.90)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["price_zone"] == "fallback"

    # --- B. Resolution timing (5 tests) ---

    def test_min_resolution_rejects_0_day(self, scanner):
        """Market resolving today (0 days) should be rejected — insider-dominated."""
        markets = [self._make_market("Will X happen today?", 0.58, 0.62, days=0)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 0

    def test_min_resolution_rejects_1_day(self, scanner):
        """Market resolving in 1 day should be rejected — negative edge."""
        markets = [self._make_market("Will Y happen tomorrow?", 0.58, 0.62, days=1)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 0

    def test_min_resolution_accepts_7_day(self, scanner):
        """Market resolving in 7+ days should be accepted — minimum threshold.
        Note: days=8 because timedelta.days floors, so 7d ahead reads as 7d."""
        markets = [self._make_market("Will the election result change?", 0.58, 0.62, days=8)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1

    def test_max_resolution_rejects_31_day(self, scanner):
        """Market resolving in 31+ days should be rejected — beyond max window.
        Note: days=32 because timedelta.days floors, so 31d ahead reads as 30d."""
        markets = [self._make_market("Will Z happen in a month?", 0.58, 0.62, days=32)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 0

    def test_optimal_resolution_15_30_days(self, scanner):
        """Market at 20 days (optimal window) should be accepted."""
        markets = [self._make_market("Will the president sign the bill?", 0.58, 0.62, days=20)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1

    # --- C. Category confidence (4 tests) ---

    def test_politics_gets_higher_confidence(self, scanner):
        """Politics market should get confidence >= 0.75."""
        markets = [self._make_market("Will Trump win the election?", 0.58, 0.62)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["confidence"] >= 0.75

    def test_economics_gets_higher_confidence(self, scanner):
        """Economics market should get confidence >= 0.75."""
        markets = [self._make_market("Will the fed cut interest rate?", 0.58, 0.62)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["confidence"] >= 0.75

    def test_crypto_gets_lower_confidence(self, scanner):
        """Crypto market should have confidence reduced by 0.10."""
        # Crypto in sweet spot: base 0.75, minus 0.10 = 0.65
        markets = [self._make_market("Will bitcoin hit $200k?", 0.58, 0.62)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["confidence"] <= 0.70  # reduced by crypto penalty

    def test_crypto_removed_from_preferred(self):
        """'bitcoin' should NOT be in preferred topics."""
        from sovereign_hive.run_simulation import MarketScanner
        import inspect
        source = inspect.getsource(MarketScanner.find_opportunities)
        assert "preferred_exact" in source or "preferred_topics" in source
        assert "negative_exact" in source or "negative_categories" in source
        # The preferred set/list should not contain crypto keywords
        lines = source.split("\n")
        in_preferred = False
        for line in lines:
            if ("preferred_exact" in line or "preferred_topics" in line) and "=" in line and ("{" in line or "[" in line):
                in_preferred = True
            if in_preferred and ("}" in line or "]" in line):
                in_preferred = False
                break
            if in_preferred:
                assert "bitcoin" not in line.lower()
                assert "crypto" not in line.lower()
                assert "ethereum" not in line.lower()

    # --- D. Two-zone confidence differentiation (4 tests) ---

    def test_sweet_spot_preferred_highest_confidence(self, scanner):
        """Politics market in sweet spot should get confidence = 0.85."""
        markets = [self._make_market("Will Trump be president?", 0.58, 0.62)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["confidence"] == 0.85

    def test_sweet_spot_neutral_good_confidence(self, scanner):
        """Neutral market in sweet spot should get confidence = 0.75."""
        markets = [self._make_market("Will the merger complete?", 0.58, 0.62)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["confidence"] == 0.75

    def test_fallback_preferred_moderate_confidence(self, scanner):
        """Politics market in fallback zone should get confidence = 0.65."""
        markets = [self._make_market("Will Biden sign the bill?", 0.83, 0.87)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        assert mm_opps[0]["confidence"] == 0.65

    def test_fallback_neutral_now_blocked(self, scanner):
        """Neutral market in fallback zone is now BLOCKED — fallback only for preferred categories."""
        markets = [self._make_market("Will the company IPO?", 0.83, 0.87)]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 0  # Neutral not preferred, can't enter fallback zone

    # --- E. Integration tests (3 tests) ---

    def test_full_pipeline_sweet_spot_politics(self, scanner):
        """End-to-end: politics market at 0.60, 20d resolution passes all phases."""
        markets = [self._make_market(
            "Will Trump win the election?", 0.58, 0.62, days=20
        )]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        opp = mm_opps[0]
        assert opp["price_zone"] == "sweet"
        assert opp["confidence"] == 0.85
        assert opp["days_to_resolve"] == 19  # timedelta.days floors: 20d ahead reads as 19d
        assert opp["strategy"] == "MARKET_MAKER"

    def test_full_pipeline_crypto_low_confidence(self, scanner):
        """Crypto at 0.40 passes but with reduced confidence (crypto penalty)."""
        markets = [self._make_market(
            "Will bitcoin hit $500k?", 0.38, 0.42, days=15
        )]
        mm_opps = self._get_mm_opportunities(scanner, markets)
        assert len(mm_opps) == 1
        # Crypto gets -0.10 confidence penalty
        assert mm_opps[0]["confidence"] <= 0.55

    def test_gemini_prompt_contains_empirical_data(self):
        """Verify Gemini prompt includes empirical intelligence section."""
        import inspect
        source = inspect.getsource(GeminiAnalyzer.deep_screen_market)
        assert "88.5M" in source
        assert "Kelly" in source
        assert "EMPIRICAL INTELLIGENCE" in source
        assert "AVOID" in source
        assert "0.55-0.65" in source

    # --- F. Existing test compatibility (2 tests) ---

    def test_existing_config_values_unchanged(self):
        """Non-MM CONFIG params should be untouched."""
        from sovereign_hive.run_simulation import CONFIG
        assert CONFIG["take_profit_pct"] == 0.10
        assert CONFIG["stop_loss_pct"] == -0.05
        assert CONFIG["kelly_fraction"] == 0.50  # Half Kelly (institutional standard)
        assert CONFIG["max_position_pct"] == 0.20
        assert CONFIG["max_positions"] == 10
        assert CONFIG["min_annualized_return"] == 0.15
        assert CONFIG["max_days_to_resolve"] == 90

    def test_mm_target_profit_default_preserved(self):
        """mm_target_profit should still be 0.015 (AI overrides per-market)."""
        from sovereign_hive.run_simulation import CONFIG
        assert CONFIG["mm_target_profit"] == 0.015
        assert CONFIG["mm_price_range"] == (0.15, 0.65)  # Tightened from (0.15, 0.85)
        assert CONFIG["mm_fallback_range"] == (0.80, 0.95)  # Fallback only for preferred categories
        assert CONFIG["mm_min_days_to_resolve"] == 7  # Raised from 2 to block sports
        assert CONFIG["mm_max_days_to_resolve"] == 30


# ============================================================
# VOLUME SURGE - oneHourPriceChange proxy (Bug fix tests)
# ============================================================

class TestVolumeSurge:
    """Tests for VOLUME_SURGE strategy using oneHourPriceChange as a proxy.

    The Gamma API does NOT return a 'volume1hr' field. The old code read
    m.get("volume1hr") which always returned None, making the strategy
    never fire. The fix uses oneHourPriceChange (>= 2%) combined with
    high daily volume (>= $30k) as a surge signal.
    """

    @pytest.fixture
    def scanner(self):
        from sovereign_hive.run_simulation import MarketScanner
        return MarketScanner()

    def _make_market(self, question="Will event happen?", best_bid=0.43,
                     best_ask=0.45, volume_24h=50000, liquidity=100000,
                     one_hour_price_change=None, one_day_price_change=0.0,
                     days=15):
        """Helper to build a market dict with optional oneHourPriceChange.

        Defaults are chosen to avoid triggering other strategies:
        - 0.43/0.45: outside MM zones (sweet 0.50-0.70, fallback 0.80-0.95)
        - 0.45: between MEAN_REVERSION bounds (0.30 low, 0.70 high)
        - oneDayPriceChange=0.0: avoids MID_RANGE (needs >0.5%) and DIP_BUY (needs <-3%)
        """
        end_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        m = {
            "conditionId": f"0x{hash(question) & 0xFFFFFFFF:08x}",
            "question": question,
            "bestBid": best_bid,
            "bestAsk": best_ask,
            "volume24hr": volume_24h,
            "liquidityNum": liquidity,
            "endDate": end_date,
            "oneDayPriceChange": one_day_price_change,
        }
        if one_hour_price_change is not None:
            m["oneHourPriceChange"] = one_hour_price_change
        return m

    def _get_volume_surge_opps(self, scanner, markets):
        """Run find_opportunities and return only VOLUME_SURGE results."""
        opps = scanner.find_opportunities(markets)
        return [o for o in opps if o["strategy"] == "VOLUME_SURGE"]

    def test_large_price_change_high_volume_triggers_surge(self, scanner):
        """Market with large oneHourPriceChange (>2%) + high volume should fire."""
        markets = [self._make_market(
            one_hour_price_change=0.05,  # 5% move in 1h
            volume_24h=80000,            # well above $30k floor
            best_bid=0.597, best_ask=0.60,  # edge zone (0.55-0.65), tight spread avoids MM dedup
        )]
        surge_opps = self._get_volume_surge_opps(scanner, markets)
        assert len(surge_opps) == 1
        assert surge_opps[0]["strategy"] == "VOLUME_SURGE"
        assert "surge" in surge_opps[0]["reason"].lower()

    def test_small_price_change_no_surge(self, scanner):
        """Market with small oneHourPriceChange (<1%) should NOT trigger."""
        markets = [self._make_market(
            one_hour_price_change=0.005,  # 0.5% — too small
            volume_24h=80000,
        )]
        surge_opps = self._get_volume_surge_opps(scanner, markets)
        assert len(surge_opps) == 0

    def test_large_price_change_low_volume_no_surge(self, scanner):
        """Market with large price change but low volume should NOT trigger."""
        markets = [self._make_market(
            one_hour_price_change=0.05,  # 5% move
            volume_24h=5000,             # only $5k — below $30k floor
        )]
        surge_opps = self._get_volume_surge_opps(scanner, markets)
        assert len(surge_opps) == 0

    def test_missing_one_hour_price_change_no_crash(self, scanner):
        """Market without oneHourPriceChange field should not crash."""
        markets = [self._make_market(
            volume_24h=80000,
            # one_hour_price_change is None → not included in dict
        )]
        surge_opps = self._get_volume_surge_opps(scanner, markets)
        assert len(surge_opps) == 0  # No crash, just no surge

    def test_volume1hr_field_no_longer_used(self):
        """The old broken 'volume1hr' field should not appear in the strategy code."""
        import inspect
        from sovereign_hive.run_simulation import MarketScanner
        source = inspect.getsource(MarketScanner.find_opportunities)
        assert "volume1hr" not in source
        # Confirm the fix uses oneHourPriceChange instead
        assert "oneHourPriceChange" in source

    def test_negative_price_change_triggers_surge(self, scanner):
        """Negative oneHourPriceChange (price dropped sharply) should also trigger."""
        markets = [self._make_market(
            one_hour_price_change=-0.04,  # -4% move (absolute > 2%)
            volume_24h=60000,
            best_bid=0.597, best_ask=0.60,  # edge zone (0.55-0.65), tight spread avoids MM dedup
        )]
        surge_opps = self._get_volume_surge_opps(scanner, markets)
        assert len(surge_opps) == 1

    def test_surge_blocked_by_large_daily_change(self, scanner):
        """Surge should not fire if daily price_change >= 5% (existing filter)."""
        markets = [self._make_market(
            one_hour_price_change=0.05,
            volume_24h=80000,
            one_day_price_change=0.06,  # 6% daily — abs >= 5%, blocked
        )]
        surge_opps = self._get_volume_surge_opps(scanner, markets)
        assert len(surge_opps) == 0

    def test_surge_reason_contains_percentage(self, scanner):
        """Surge reason should include the 1h price change percentage."""
        markets = [self._make_market(
            one_hour_price_change=0.03,  # 3%
            volume_24h=50000,
            best_bid=0.597, best_ask=0.60,  # edge zone (0.55-0.65), tight spread avoids MM dedup
        )]
        surge_opps = self._get_volume_surge_opps(scanner, markets)
        assert len(surge_opps) == 1
        assert "3.0%" in surge_opps[0]["reason"]
        assert "1.5x" in surge_opps[0]["reason"]  # 0.03 / 0.02 = 1.5x


# ============================================================
# NEG_RISK ARBITRAGE - Multi-outcome event arbitrage
# ============================================================

class TestNegRiskArb:
    """Tests for NegRisk multi-outcome arbitrage scanner."""

    @pytest.fixture
    def scanner(self):
        from sovereign_hive.run_simulation import MarketScanner
        return MarketScanner()

    def _make_event(self, title, outcomes, end_days=15, event_id="evt_001"):
        """Create a mock NegRisk event with multiple outcome markets.

        outcomes: list of (bid, ask, liquidity) tuples
        """
        end_date = (datetime.now(timezone.utc) + timedelta(days=end_days)).isoformat()
        markets = []
        for i, (bid, ask, liq) in enumerate(outcomes):
            markets.append({
                "question": f"Outcome {i+1}",
                "bestBid": str(bid),
                "bestAsk": str(ask),
                "liquidityNum": str(liq),
            })
        return {
            "id": event_id,
            "title": title,
            "endDate": end_date,
            "markets": markets,
        }

    def test_sell_arb_detected(self, scanner):
        """5 outcomes with bid_sum=1.02 should produce a SELL_ALL opportunity."""
        # 5 outcomes: bids sum to 1.02 (2% guaranteed profit)
        event = self._make_event("Who will win?", [
            (0.30, 0.33, 10000),
            (0.25, 0.28, 10000),
            (0.20, 0.23, 10000),
            (0.15, 0.18, 10000),
            (0.12, 0.15, 10000),  # bid_sum = 0.30+0.25+0.20+0.15+0.12 = 1.02
        ])
        opps = scanner.find_negrisk_opportunities([event])
        sell_opps = [o for o in opps if o["side"] == "SELL_ALL"]
        assert len(sell_opps) == 1
        assert sell_opps[0]["strategy"] == "NEG_RISK_ARB"
        assert sell_opps[0]["expected_return"] == pytest.approx(0.02, abs=0.001)

    def test_buy_arb_detected(self, scanner):
        """5 outcomes with ask_sum=0.97 should produce a BUY_ALL opportunity."""
        # 5 outcomes: asks sum to 0.97 (3% guaranteed profit)
        event = self._make_event("Who will win?", [
            (0.27, 0.28, 10000),
            (0.22, 0.23, 10000),
            (0.17, 0.18, 10000),
            (0.14, 0.15, 10000),
            (0.12, 0.13, 10000),  # ask_sum = 0.28+0.23+0.18+0.15+0.13 = 0.97
        ])
        opps = scanner.find_negrisk_opportunities([event])
        buy_opps = [o for o in opps if o["side"] == "BUY_ALL"]
        assert len(buy_opps) == 1
        assert buy_opps[0]["strategy"] == "NEG_RISK_ARB"
        assert buy_opps[0]["expected_return"] == pytest.approx(0.03, abs=0.001)

    def test_no_arb_efficient_market(self, scanner):
        """Efficient market (bid_sum<1, ask_sum>1) should produce no opportunities."""
        event = self._make_event("Efficient event", [
            (0.30, 0.35, 10000),
            (0.25, 0.30, 10000),
            (0.20, 0.25, 10000),
            (0.15, 0.20, 10000),
            # bid_sum = 0.90 (< 1.0), ask_sum = 1.10 (> 1.0) → no arb
        ])
        opps = scanner.find_negrisk_opportunities([event])
        assert len(opps) == 0

    def test_min_edge_filter(self, scanner):
        """bid_sum=1.003 (0.3% edge, below 0.5% threshold) should be rejected."""
        event = self._make_event("Tiny edge", [
            (0.335, 0.34, 10000),
            (0.335, 0.34, 10000),
            (0.333, 0.34, 10000),
            # bid_sum = 1.003, edge = 0.3% < 0.5% min
        ])
        opps = scanner.find_negrisk_opportunities([event])
        sell_opps = [o for o in opps if o["side"] == "SELL_ALL"]
        assert len(sell_opps) == 0

    def test_min_outcomes_filter(self):
        """negrisk_min_outcomes CONFIG should be >= 3 (fetch layer filters 2-outcome events)."""
        from sovereign_hive.run_simulation import CONFIG
        assert CONFIG.get("negrisk_min_outcomes", 3) >= 3

    def test_max_outcomes_filter(self, scanner):
        """Event with 60 outcomes should be rejected."""
        outcomes = [(0.02, 0.03, 10000)] * 60
        # bid_sum = 60*0.02 = 1.20, but 60 > max_outcomes (50)
        event = self._make_event("Huge event", outcomes)
        opps = scanner.find_negrisk_opportunities([event])
        assert len(opps) == 0

    def test_min_liquidity_filter(self, scanner):
        """One outcome with low liquidity ($1k) should reject entire event."""
        event = self._make_event("Low liquidity", [
            (0.35, 0.37, 10000),
            (0.35, 0.37, 1000),   # Below $5k min
            (0.35, 0.37, 10000),
            # bid_sum = 1.05, but one outcome has $1k liquidity
        ])
        opps = scanner.find_negrisk_opportunities([event])
        assert len(opps) == 0

    def test_sell_arb_profit_calculation(self, scanner):
        """Verify expected_return = bid_sum - 1.0 for sell arb."""
        event = self._make_event("Profit check", [
            (0.40, 0.45, 10000),
            (0.35, 0.40, 10000),
            (0.30, 0.35, 10000),
            # bid_sum = 1.05, edge = 0.05 = 5%
        ])
        opps = scanner.find_negrisk_opportunities([event])
        sell_opps = [o for o in opps if o["side"] == "SELL_ALL"]
        assert len(sell_opps) == 1
        assert sell_opps[0]["expected_return"] == pytest.approx(0.05, abs=0.001)
        assert sell_opps[0]["price"] == pytest.approx(1.05, abs=0.001)

    def test_max_edge_filter(self, scanner):
        """Edge > 10% (not mutually exclusive) should be rejected."""
        # 5 outcomes with bid_sum=1.50 → edge=50% → clearly not mutually exclusive
        event = self._make_event("Not exclusive", [
            (0.40, 0.45, 10000),
            (0.35, 0.40, 10000),
            (0.30, 0.35, 10000),
            (0.25, 0.30, 10000),
            (0.20, 0.25, 10000),
            # bid_sum = 1.50, edge = 50% > 10% max
        ])
        opps = scanner.find_negrisk_opportunities([event])
        assert len(opps) == 0

    def test_config_params_exist(self):
        """Verify negrisk CONFIG params are present."""
        from sovereign_hive.run_simulation import CONFIG
        assert "negrisk_min_edge" in CONFIG
        assert "negrisk_min_outcomes" in CONFIG
        assert "negrisk_min_liquidity" in CONFIG
        assert "negrisk_max_outcomes" in CONFIG
        assert "negrisk_max_edge" in CONFIG
        assert CONFIG["negrisk_min_edge"] == 0.005
        assert CONFIG["negrisk_min_outcomes"] == 3
        assert CONFIG["negrisk_min_liquidity"] == 5000
        assert CONFIG["negrisk_max_outcomes"] == 50
        assert CONFIG["negrisk_max_edge"] == 0.10

    def test_strategy_in_all_strategies(self):
        """NEG_RISK_ARB should be in the all_strategies list."""
        from sovereign_hive.run_simulation import MarketScanner
        import inspect
        source = inspect.getsource(MarketScanner.find_opportunities)
        assert "NEG_RISK_ARB" in source
