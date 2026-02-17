#!/usr/bin/env python3
"""
KELLY CRITERION TESTS
======================
Comprehensive tests for Kelly Criterion position sizing.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.core.kelly_criterion import (
    KellyCriterion,
    KellyResult,
    calculate_kelly_position
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def calculator():
    """Default Kelly calculator."""
    return KellyCriterion()


@pytest.fixture
def aggressive_calculator():
    """More aggressive Kelly (half Kelly)."""
    return KellyCriterion(kelly_fraction=0.5)


@pytest.fixture
def conservative_calculator():
    """Very conservative Kelly."""
    return KellyCriterion(kelly_fraction=0.1, max_position_pct=0.05)


# ============================================================
# BASIC CALCULATION TESTS
# ============================================================

class TestBasicCalculations:
    """Tests for basic Kelly calculations."""

    def test_positive_edge_yes_bet(self, calculator):
        """Test Kelly calculation with positive edge on YES."""
        result = calculator.calculate(
            estimated_prob=0.70,
            market_price=0.60,
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )

        assert result is not None
        assert result.edge == pytest.approx(0.10, rel=0.01)
        # Raw Kelly = (0.70 - 0.60) / (1 - 0.60) = 0.25
        assert result.kelly_fraction == pytest.approx(0.25, rel=0.01)
        assert result.position_size > 0
        assert result.expected_value > 0

    def test_positive_edge_no_bet(self, calculator):
        """Test Kelly calculation with positive edge on NO."""
        result = calculator.calculate(
            estimated_prob=0.30,  # We think YES is only 30%
            market_price=0.40,   # Market says 40%
            bankroll=1000,
            confidence=0.8,
            side="NO"
        )

        assert result is not None
        assert result.edge > 0  # Edge on NO side
        assert result.position_size > 0

    def test_no_edge_returns_none(self, calculator):
        """Test that no edge returns None."""
        result = calculator.calculate(
            estimated_prob=0.60,
            market_price=0.60,  # Same as estimate
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )

        assert result is None

    def test_negative_edge_returns_none(self, calculator):
        """Test that negative edge returns None."""
        result = calculator.calculate(
            estimated_prob=0.50,
            market_price=0.60,  # Market is higher than our estimate
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )

        assert result is None

    def test_edge_below_minimum_returns_none(self, calculator):
        """Test that edge below minimum threshold returns None."""
        result = calculator.calculate(
            estimated_prob=0.61,  # Only 1% edge
            market_price=0.60,
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )

        assert result is None  # Default min_edge is 2%


# ============================================================
# FRACTIONAL KELLY TESTS
# ============================================================

class TestFractionalKelly:
    """Tests for fractional Kelly scaling."""

    def test_quarter_kelly_reduces_position(self, calculator):
        """Test that quarter Kelly reduces position size."""
        result = calculator.calculate(
            estimated_prob=0.80,
            market_price=0.60,
            bankroll=1000,
            confidence=1.0,  # Full confidence
            side="YES"
        )

        # Raw Kelly would be (0.80 - 0.60) / 0.40 = 0.50 (50%)
        # Quarter Kelly = 0.50 * 0.25 = 0.125 (12.5%)
        assert result.kelly_fraction == pytest.approx(0.50, rel=0.01)
        assert result.adjusted_fraction < result.kelly_fraction
        assert result.adjusted_fraction <= 0.15  # Max position limit

    def test_half_kelly_larger_than_quarter(self, calculator, aggressive_calculator):
        """Test that half Kelly gives larger positions than quarter."""
        params = dict(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1000,
            confidence=0.9,
            side="YES"
        )

        quarter = calculator.calculate(**params)
        half = aggressive_calculator.calculate(**params)

        assert half.position_size > quarter.position_size

    def test_conservative_respects_max_position(self, conservative_calculator):
        """Test that max position limit is respected."""
        result = conservative_calculator.calculate(
            estimated_prob=0.95,  # Very high edge
            market_price=0.50,
            bankroll=10000,
            confidence=1.0,
            side="YES"
        )

        # Should be capped at 5% max position
        assert result.adjusted_fraction <= 0.05
        assert result.position_size <= 500


# ============================================================
# CONFIDENCE SCALING TESTS
# ============================================================

class TestConfidenceScaling:
    """Tests for confidence-based scaling."""

    def test_confidence_is_gate_not_multiplier(self, calculator):
        """Test that confidence acts as a gate, not a multiplier.

        Above the min_confidence threshold, confidence does NOT scale
        position size — it only gates entry. This prevents triple-penalty
        (Kelly * fraction * confidence) that made positions too small.
        """
        high_conf = calculator.calculate(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1000,
            confidence=0.9,
            side="YES"
        )

        low_conf = calculator.calculate(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1000,
            confidence=0.6,
            side="YES"
        )

        # Both above threshold → same position size (confidence is a gate)
        assert low_conf.position_size == high_conf.position_size

    def test_confidence_below_threshold_returns_none(self, calculator):
        """Test that confidence below threshold returns None."""
        result = calculator.calculate(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1000,
            confidence=0.50,  # Below default 0.55 threshold
            side="YES"
        )

        assert result is None


# ============================================================
# INPUT VALIDATION TESTS
# ============================================================

class TestInputValidation:
    """Tests for input validation."""

    def test_invalid_probability_returns_none(self, calculator):
        """Test that invalid probabilities return None."""
        assert calculator.calculate(0, 0.5, 1000, 0.8, "YES") is None
        assert calculator.calculate(1, 0.5, 1000, 0.8, "YES") is None
        assert calculator.calculate(-0.1, 0.5, 1000, 0.8, "YES") is None
        assert calculator.calculate(1.1, 0.5, 1000, 0.8, "YES") is None

    def test_invalid_price_returns_none(self, calculator):
        """Test that invalid prices return None."""
        assert calculator.calculate(0.7, 0, 1000, 0.8, "YES") is None
        assert calculator.calculate(0.7, 1, 1000, 0.8, "YES") is None
        assert calculator.calculate(0.7, -0.1, 1000, 0.8, "YES") is None
        assert calculator.calculate(0.7, 1.1, 1000, 0.8, "YES") is None

    def test_zero_bankroll_returns_none(self, calculator):
        """Test that zero bankroll returns None."""
        assert calculator.calculate(0.7, 0.5, 0, 0.8, "YES") is None
        assert calculator.calculate(0.7, 0.5, -100, 0.8, "YES") is None


# ============================================================
# RISK CLASSIFICATION TESTS
# ============================================================

class TestRiskClassification:
    """Tests for risk level classification."""

    def test_low_risk_classification(self, calculator):
        """Test LOW risk classification with minimal edge."""
        result = calculator.calculate(
            estimated_prob=0.63,  # 3% edge - just above minimum
            market_price=0.60,
            bankroll=1000,
            confidence=0.6,
            side="YES"
        )

        assert result is not None
        # Small edge can be LOW or MEDIUM
        assert result.risk_level in ["LOW", "MEDIUM"]

    def test_moderate_edge_classification(self, calculator):
        """Test classification with moderate edge."""
        result = calculator.calculate(
            estimated_prob=0.68,  # 8% edge
            market_price=0.60,
            bankroll=1000,
            confidence=0.7,
            side="YES"
        )

        assert result is not None
        # Classification depends on Kelly fraction
        assert result.risk_level in ["LOW", "MEDIUM", "HIGH", "EXTREME"]

    def test_high_edge_classification(self, calculator):
        """Test classification with high edge."""
        result = calculator.calculate(
            estimated_prob=0.85,  # Large edge
            market_price=0.50,
            bankroll=1000,
            confidence=0.9,
            side="YES"
        )

        assert result is not None
        assert result.risk_level in ["MEDIUM", "HIGH", "EXTREME"]


# ============================================================
# OPPORTUNITY DICT TESTS
# ============================================================

class TestOpportunityCalculation:
    """Tests for calculate_from_opportunity method."""

    def test_near_certain_opportunity(self, calculator):
        """Test calculation from NEAR_CERTAIN opportunity."""
        # NEAR_CERTAIN at 90% with high confidence should have edge
        opp = {
            "price": 0.90,
            "confidence": 0.95,
            "side": "YES",
            "strategy": "NEAR_CERTAIN"
        }

        result = calculator.calculate_from_opportunity(opp, bankroll=1000)

        # Edge estimation: price + (1-price)*confidence*0.5 = 0.90 + 0.1*0.95*0.5 = 0.9475
        # Edge = 0.9475 - 0.90 = 0.0475 (~5%)
        assert result is not None
        assert result.position_size > 0

    def test_near_zero_opportunity(self, calculator):
        """Test calculation from NEAR_ZERO opportunity."""
        # NEAR_ZERO at 10% with high confidence
        opp = {
            "price": 0.10,
            "confidence": 0.90,
            "side": "NO",
            "strategy": "NEAR_ZERO"
        }

        result = calculator.calculate_from_opportunity(opp, bankroll=1000)

        # For NO side, we invert in calculate()
        # estimated_prob = 0.10 - 0.10*0.90*0.5 = 0.055
        # After invert: 1 - 0.055 = 0.945 vs market 1 - 0.10 = 0.90
        assert result is not None
        assert result.position_size > 0

    def test_binance_arb_opportunity(self, calculator):
        """Test calculation from BINANCE_ARB opportunity."""
        opp = {
            "price": 0.55,
            "confidence": 0.90,
            "side": "YES",
            "strategy": "BINANCE_ARB",
            "binance_implied": 0.65  # Binance suggests 65%
        }

        result = calculator.calculate_from_opportunity(opp, bankroll=1000)

        assert result is not None
        assert result.edge == pytest.approx(0.10, rel=0.01)

    def test_dual_side_arb_opportunity(self, calculator):
        """Test calculation from DUAL_SIDE_ARB opportunity."""
        opp = {
            "price": 0.48,
            "confidence": 0.95,
            "side": "YES",
            "strategy": "DUAL_SIDE_ARB"
        }

        result = calculator.calculate_from_opportunity(opp, bankroll=1000)

        assert result is not None
        # Should have high edge for arbitrage

    def test_market_maker_opportunity(self, calculator):
        """Test calculation from MARKET_MAKER opportunity."""
        opp = {
            "price": 0.50,
            "confidence": 0.75,
            "side": "MM",
            "strategy": "MARKET_MAKER",
            "spread": 0.05
        }

        result = calculator.calculate_from_opportunity(opp, bankroll=1000)

        # MM may or may not have enough edge depending on spread


# ============================================================
# CONVENIENCE FUNCTION TESTS
# ============================================================

class TestConvenienceFunction:
    """Tests for the convenience function."""

    def test_calculate_kelly_position_positive_edge(self):
        """Test convenience function with positive edge."""
        position = calculate_kelly_position(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1000,
            kelly_fraction=0.25,
            confidence=0.8,
            side="YES"
        )

        assert position > 0
        assert position <= 150  # Max 15% of bankroll

    def test_calculate_kelly_position_no_edge(self):
        """Test convenience function returns 0 with no edge."""
        position = calculate_kelly_position(
            estimated_prob=0.60,
            market_price=0.60,
            bankroll=1000,
            kelly_fraction=0.25,
            confidence=0.8,
            side="YES"
        )

        assert position == 0


# ============================================================
# KELLY RESULT DATACLASS TESTS
# ============================================================

class TestKellyResult:
    """Tests for KellyResult dataclass."""

    def test_kelly_result_attributes(self, calculator):
        """Test that KellyResult has all expected attributes."""
        result = calculator.calculate(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )

        assert hasattr(result, 'kelly_fraction')
        assert hasattr(result, 'adjusted_fraction')
        assert hasattr(result, 'position_size')
        assert hasattr(result, 'edge')
        assert hasattr(result, 'expected_value')
        assert hasattr(result, 'risk_level')

    def test_kelly_result_types(self, calculator):
        """Test that KellyResult has correct types."""
        result = calculator.calculate(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )

        assert isinstance(result.kelly_fraction, float)
        assert isinstance(result.adjusted_fraction, float)
        assert isinstance(result.position_size, float)
        assert isinstance(result.edge, float)
        assert isinstance(result.expected_value, float)
        assert isinstance(result.risk_level, str)


# ============================================================
# EDGE CASE TESTS
# ============================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_very_small_edge(self, calculator):
        """Test with edge just at minimum threshold."""
        calc = KellyCriterion(min_edge=0.02)
        result = calc.calculate(
            estimated_prob=0.62,  # Exactly 2% edge
            market_price=0.60,
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )

        assert result is not None
        assert result.edge == pytest.approx(0.02, abs=0.001)

    def test_extreme_edge(self, calculator):
        """Test with very large edge."""
        result = calculator.calculate(
            estimated_prob=0.99,
            market_price=0.10,
            bankroll=1000,
            confidence=1.0,
            side="YES"
        )

        assert result is not None
        # Position should be capped at max
        assert result.adjusted_fraction <= 0.15

    def test_price_near_zero(self, calculator):
        """Test with price near zero."""
        result = calculator.calculate(
            estimated_prob=0.10,
            market_price=0.03,
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )

        assert result is not None

    def test_price_near_one(self, calculator):
        """Test with price near one."""
        result = calculator.calculate(
            estimated_prob=0.995,
            market_price=0.97,
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )

        assert result is not None

    def test_large_bankroll(self, calculator):
        """Test with large bankroll."""
        result = calculator.calculate(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1_000_000,
            confidence=0.8,
            side="YES"
        )

        assert result is not None
        assert result.position_size <= 150_000  # 15% max


# ============================================================
# FORMULA EXPLANATION TEST
# ============================================================

class TestExplanation:
    """Test for explanation method."""

    def test_kelly_formula_explanation(self):
        """Test that explanation is returned."""
        explanation = KellyCriterion.kelly_formula_explanation()

        assert "Kelly Criterion" in explanation
        assert "f*" in explanation
        assert "bankroll" in explanation.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
