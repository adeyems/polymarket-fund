#!/usr/bin/env python3
"""
NEWS ANALYZER TESTS
====================
Tests for NewsAnalyzer class.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.run_simulation import NewsAnalyzer


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def news_analyzer():
    """Create a NewsAnalyzer with mocked dependencies."""
    with patch('sovereign_hive.run_simulation.ClaudeAnalyzer'):
        analyzer = NewsAnalyzer()
        analyzer.news_api_key = "test_api_key"
    return analyzer


@pytest.fixture
def news_analyzer_no_key():
    """Create a NewsAnalyzer without API key."""
    with patch('sovereign_hive.run_simulation.ClaudeAnalyzer'):
        analyzer = NewsAnalyzer()
        analyzer.news_api_key = ""
    return analyzer


# ============================================================
# NEWS ANALYZER TESTS
# ============================================================

class TestNewsAnalyzer:
    """Tests for NewsAnalyzer class."""

    @pytest.mark.asyncio
    async def test_analyze_market_no_api_key(self, news_analyzer_no_key):
        """Test analysis fails without API key."""
        result = await news_analyzer_no_key.analyze_market("Will Bitcoin hit $100k?")
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_market_success(self, news_analyzer):
        """Test successful news analysis."""
        mock_articles = [
            {
                "title": "Bitcoin surges to new highs",
                "description": "Bitcoin reaches new all-time high amid institutional buying"
            }
        ]

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"articles": mock_articles})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_response)

        mock_claude_result = {
            "direction": "BULLISH",
            "confidence": 0.80,
            "reasoning": "Positive market sentiment"
        }
        news_analyzer.claude.analyze_news = AsyncMock(return_value=mock_claude_result)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            result = await news_analyzer.analyze_market("Will Bitcoin hit $100k?")

        assert result is not None
        assert result["direction"] == "BULLISH"
        assert "headline" in result

    @pytest.mark.asyncio
    async def test_analyze_market_no_articles(self, news_analyzer):
        """Test handling of no articles found."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"articles": []})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_response)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            result = await news_analyzer.analyze_market("Obscure topic?")

        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_market_api_error(self, news_analyzer):
        """Test handling of API error."""
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(return_value=mock_response)

        with patch('aiohttp.ClientSession', return_value=mock_session):
            result = await news_analyzer.analyze_market("Will Bitcoin hit $100k?")

        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_market_exception(self, news_analyzer):
        """Test handling of network exception."""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            result = await news_analyzer.analyze_market("Will Bitcoin hit $100k?")

        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
