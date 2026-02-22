"""Tests for the AI Validator agent."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from sovereign_hive.agents_v2.validator import app
    return TestClient(app)


class TestValidatorHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestValidatorApproval:
    def _make_request(self, **overrides):
        base = {
            "condition_id": "0xabc123",
            "question": "Will X happen?",
            "strategy": "MARKET_MAKER",
            "side": "YES",
            "price": 0.55,
            "amount": 100.0,
            "confidence": 0.75,
            "ai_score": 8.0,
            "portfolio_summary": {
                "balance": 800.0,
                "positions": {},
                "open_positions": 0,
                "total_pnl": 10.0,
                "win_rate": 65.0,
                "roi_pct": 1.0,
            },
        }
        base.update(overrides)
        return base

    def test_normal_trade_approved(self, client):
        """Standard trade should be approved."""
        resp = client.post("/validate", json=self._make_request())
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is True
        assert len(data["risk_flags"]) == 0

    def test_duplicate_position_rejected(self, client):
        """Trading on a market we already hold should be rejected."""
        req = self._make_request(
            portfolio_summary={
                "balance": 800.0,
                "positions": {"0xabc123": {"cost_basis": 100, "strategy": "MARKET_MAKER"}},
                "open_positions": 1,
                "total_pnl": 0,
                "win_rate": 0,
                "roi_pct": 0,
            }
        )
        resp = client.post("/validate", json=req)
        data = resp.json()
        assert data["approved"] is False
        assert "DUPLICATE" in data["reason"]

    def test_invalid_price_rejected(self, client):
        """Price > 1.0 should be rejected."""
        req = self._make_request(price=1.5)
        resp = client.post("/validate", json=req)
        data = resp.json()
        assert data["approved"] is False
        assert "PRICE" in data["reason"]

    def test_concentration_warning(self, client):
        """Trade >40% of total portfolio value should flag warning."""
        req = self._make_request(
            amount=500.0,
            portfolio_summary={
                "balance": 800.0,
                "positions": {},
                "open_positions": 0,
                "total_pnl": 0,
                "win_rate": 0,
                "roi_pct": 0,
            }
        )
        resp = client.post("/validate", json=req)
        data = resp.json()
        # 500/800 = 62.5% > 40% threshold
        assert data["approved"] is True  # Warning, not rejection
        assert any("CONCENTRATION" in f for f in data["risk_flags"])

    def test_size_warning(self, client):
        """Trade >30% of balance should flag warning."""
        req = self._make_request(
            amount=300.0,
            portfolio_summary={
                "balance": 800.0,
                "positions": {},
                "open_positions": 0,
                "total_pnl": 0,
                "win_rate": 0,
                "roi_pct": 0,
            }
        )
        resp = client.post("/validate", json=req)
        data = resp.json()
        assert data["approved"] is True
        assert any("SIZE" in f for f in data["risk_flags"])

    def test_high_yes_price_warning(self, client):
        """Buying YES at >$0.95 should flag warning."""
        req = self._make_request(side="YES", price=0.97)
        resp = client.post("/validate", json=req)
        data = resp.json()
        assert data["approved"] is True
        assert any("PRICE" in f for f in data["risk_flags"])

    def test_low_confidence_large_size_warning(self, client):
        """Low confidence (<0.55) with large position (>$100) should warn."""
        req = self._make_request(confidence=0.50, amount=150.0)
        resp = client.post("/validate", json=req)
        data = resp.json()
        assert any("CONFIDENCE" in f for f in data["risk_flags"])

    def test_no_portfolio_summary_approved(self, client):
        """Missing portfolio summary should still approve (graceful)."""
        req = self._make_request(portfolio_summary=None)
        resp = client.post("/validate", json=req)
        data = resp.json()
        assert data["approved"] is True
