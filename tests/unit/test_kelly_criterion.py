#!/usr/bin/env python3
"""
KELLY CRITERION TESTS - Monte Carlo Cap 3 Half Kelly
======================================================
Tests for institutional-grade position sizing:
- Half Kelly (f*/2)
- Monte Carlo validation (10,000 paths)
- Cap 3 (30% max position)
- Empirical edge data (88.5M Becker trades)
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.core.kelly_criterion import (
    KellyCriterion,
    MonteCarloResult,
    calculate_kelly_position,
    empirical_probability,
    monte_carlo_validate,
    polymarket_taker_fee,
    taker_slippage,
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def calculator():
    """Default Half Kelly calculator (institutional standard)."""
    return KellyCriterion()


@pytest.fixture
def aggressive_calculator():
    """Full Kelly (no fractional reduction)."""
    return KellyCriterion(kelly_fraction=1.0)


@pytest.fixture
def conservative_calculator():
    """Quarter Kelly with tight cap."""
    return KellyCriterion(kelly_fraction=0.25, max_position_pct=0.10)


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
# HALF KELLY TESTS
# ============================================================

class TestHalfKelly:
    """Tests for Half Kelly (f*/2) sizing."""

    def test_half_kelly_is_half_of_full(self, calculator, aggressive_calculator):
        """Half Kelly produces ~50% of full Kelly position size."""
        params = dict(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1000,
            confidence=0.9,
            side="YES"
        )

        full = aggressive_calculator.calculate(**params)
        half = calculator.calculate(**params)

        # Half Kelly should be smaller than full Kelly
        assert half.position_size < full.position_size
        # Raw Kelly is the same
        assert half.kelly_fraction == full.kelly_fraction
        # Half Kelly adjusted = raw * 0.50, Full Kelly adjusted = raw * 1.0 (may be capped)
        # Compare against uncapped: half should be exactly raw * 0.50
        raw = half.kelly_fraction
        assert half.adjusted_fraction == pytest.approx(raw * 0.50, rel=0.01)

    def test_half_kelly_default_fraction(self, calculator):
        """Default calculator uses 0.50 (Half Kelly)."""
        assert calculator.kelly_fraction == 0.50

    def test_half_kelly_reduces_volatility(self, calculator, aggressive_calculator):
        """Half Kelly gives smaller positions = lower volatility."""
        params = dict(
            estimated_prob=0.80,
            market_price=0.60,
            bankroll=10000,
            confidence=0.9,
            side="YES"
        )

        full = aggressive_calculator.calculate(**params)
        half = calculator.calculate(**params)

        assert half.position_size < full.position_size
        assert half.position_size > 0  # But still positive

    def test_quarter_kelly_smaller_than_half(self, calculator, conservative_calculator):
        """Quarter Kelly gives smaller positions than Half Kelly."""
        params = dict(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1000,
            confidence=0.9,
            side="YES"
        )

        half = calculator.calculate(**params)
        quarter = conservative_calculator.calculate(**params)

        assert quarter.position_size < half.position_size


# ============================================================
# CAP 3 TESTS
# ============================================================

class TestCap3:
    """Tests for Cap 3 (30% max position)."""

    def test_cap3_limits_position(self, calculator):
        """No position exceeds 30% of bankroll."""
        result = calculator.calculate(
            estimated_prob=0.99,  # Extreme edge
            market_price=0.10,   # Cheap price = huge Kelly
            bankroll=1000,
            confidence=1.0,
            side="YES"
        )

        assert result is not None
        assert result.adjusted_fraction <= 0.30
        assert result.position_size <= 300

    def test_cap3_default_value(self, calculator):
        """Default max_position_pct is 0.30 (Cap 3)."""
        assert calculator.max_position_pct == 0.30

    def test_cap3_large_bankroll(self):
        """Cap 3 scales with bankroll but always respects percentage."""
        calc = KellyCriterion()
        result = calc.calculate(
            estimated_prob=0.90,
            market_price=0.50,
            bankroll=100_000,
            confidence=0.9,
            side="YES"
        )

        assert result is not None
        assert result.position_size <= 30_000  # 30% of 100k

    def test_cap3_applies_after_half_kelly(self, calculator):
        """Cap applies after Half Kelly scaling, not before."""
        # Raw Kelly = (0.95 - 0.30) / (1 - 0.30) = 0.929
        # Half Kelly = 0.929 * 0.50 = 0.464
        # Cap 3 = min(0.464, 0.30) = 0.30
        result = calculator.calculate(
            estimated_prob=0.95,
            market_price=0.30,
            bankroll=1000,
            confidence=0.9,
            side="YES"
        )

        assert result is not None
        assert result.adjusted_fraction == 0.30
        assert result.kelly_fraction > 0.30  # Raw Kelly is higher


# ============================================================
# EMPIRICAL EDGE TESTS
# ============================================================

class TestEmpiricalEdges:
    """Tests for Becker dataset empirical edge data."""

    def test_sweet_spot_positive_edge(self):
        """Price 0.55-0.65 (sweet spot) has positive mispricing."""
        prob = empirical_probability(0.60)
        assert prob > 0.60  # Market underprices

    def test_death_zone_negative_edge(self):
        """Price 0.35-0.45 (death zone) has negative mispricing."""
        prob = empirical_probability(0.40)
        assert prob < 0.40  # Market overprices

    def test_trap_zone_negative_edge(self):
        """Price 0.70-0.75 (trap zone) has negative mispricing."""
        prob = empirical_probability(0.72)
        assert prob < 0.72  # Market overprices

    def test_fair_value_no_edge(self):
        """Price 0.45-0.55 has no systematic mispricing."""
        prob = empirical_probability(0.50)
        assert prob == pytest.approx(0.50, abs=0.01)

    def test_fallback_zone_small_edge(self):
        """Price 0.80-0.95 has small positive edge."""
        prob = empirical_probability(0.85)
        assert prob > 0.85
        assert prob < 0.90  # Edge is small, not huge

    def test_economics_category_boost(self):
        """Economics category gets +2pp boost."""
        base = empirical_probability(0.60, "other")
        econ = empirical_probability(0.60, "economics")
        assert econ > base
        assert econ - base == pytest.approx(0.02, abs=0.005)

    def test_politics_category_boost(self):
        """Politics category gets +1.5pp boost."""
        base = empirical_probability(0.60, "other")
        politics = empirical_probability(0.60, "politics")
        assert politics > base

    def test_crypto_category_penalty(self):
        """Crypto category gets -1.5pp penalty."""
        base = empirical_probability(0.60, "other")
        crypto = empirical_probability(0.60, "crypto")
        assert crypto < base

    def test_probability_clamped(self):
        """Output is always between 0.01 and 0.99."""
        # Very low price + negative edge shouldn't go below 0.01
        prob_low = empirical_probability(0.02, "crypto")
        assert prob_low >= 0.01

        # Very high price + positive edge shouldn't go above 0.99
        prob_high = empirical_probability(0.98, "economics")
        assert prob_high <= 0.99

    def test_longshot_overpriced(self):
        """Very low prices (1-10c) are overpriced."""
        prob = empirical_probability(0.05)
        assert prob < 0.05  # -25pp mispricing

    def test_all_zones_covered(self):
        """Every price from 0.01 to 0.99 returns a valid probability."""
        for price_cents in range(1, 100):
            price = price_cents / 100
            prob = empirical_probability(price)
            assert 0.01 <= prob <= 0.99, f"Failed for price {price}"


# ============================================================
# MONTE CARLO VALIDATION TESTS
# ============================================================

class TestMonteCarloValidation:
    """Tests for Monte Carlo fraction validation."""

    def test_mc_returns_result(self):
        """Monte Carlo returns a MonteCarloResult."""
        result = monte_carlo_validate(
            bet_fraction=0.1875,
            win_prob=0.75,
            payout_ratio=0.667,
        )
        assert isinstance(result, MonteCarloResult)
        assert result.n_simulations == 10000

    def test_mc_half_kelly_survives_sweet_spot(self):
        """Half Kelly at sweet-spot edge survives Monte Carlo."""
        # Compute actual bet fraction for sweet-spot trade:
        # Price 0.60, empirical prob ~0.75 (+15pp), raw Kelly = 0.375, Half = 0.1875
        result = monte_carlo_validate(
            bet_fraction=0.1875,   # Half Kelly on sweet spot
            win_prob=0.75,         # Empirical true probability
            payout_ratio=0.667,    # (1-0.60)/0.60
        )
        # Half Kelly should survive with sweet spot edge
        assert result.ruin_probability < 0.01  # <1% ruin
        assert result.median_growth > 1.0  # Grows on average

    def test_mc_reduces_aggressive_fraction(self):
        """Monte Carlo reduces fraction when drawdown is too high."""
        result = monte_carlo_validate(
            bet_fraction=0.90,    # Way too aggressive
            win_prob=0.55,        # Slight edge
            payout_ratio=0.50,    # Low payout
            max_drawdown_pct=0.30,
        )
        # Should reduce the fraction
        assert result.validated_fraction < 0.90

    def test_mc_keeps_safe_fraction(self):
        """Monte Carlo doesn't reduce already-safe fraction."""
        result = monte_carlo_validate(
            bet_fraction=0.05,    # Very conservative
            win_prob=0.70,        # Strong edge
            payout_ratio=1.0,     # Good payout
            max_drawdown_pct=0.50,
        )
        assert result.validated_fraction == 0.05  # No reduction needed

    def test_mc_reproducible(self):
        """Same seed gives same results."""
        r1 = monte_carlo_validate(bet_fraction=0.1875, win_prob=0.75, payout_ratio=0.667, seed=42)
        r2 = monte_carlo_validate(bet_fraction=0.1875, win_prob=0.75, payout_ratio=0.667, seed=42)
        assert r1.validated_fraction == r2.validated_fraction
        assert r1.p95_drawdown == r2.p95_drawdown

    def test_mc_different_seeds(self):
        """Different seeds give different (but similar) results."""
        r1 = monte_carlo_validate(bet_fraction=0.1875, win_prob=0.75, payout_ratio=0.667, seed=42)
        r2 = monte_carlo_validate(bet_fraction=0.1875, win_prob=0.75, payout_ratio=0.667, seed=123)
        # Results should be similar but not identical
        assert abs(r1.p95_drawdown - r2.p95_drawdown) < 0.10

    def test_mc_high_ruin_with_bad_edge(self):
        """Bad edge + aggressive sizing = high ruin probability."""
        result = monte_carlo_validate(
            bet_fraction=0.80,
            win_prob=0.45,       # Negative edge!
            payout_ratio=0.50,
        )
        assert result.ruin_probability > 0.10  # Significant ruin risk

    def test_mc_drawdown_reported(self):
        """95th percentile drawdown is always between 0 and 1."""
        result = monte_carlo_validate(
            bet_fraction=0.1875,
            win_prob=0.75,
            payout_ratio=0.667,
        )
        assert 0 <= result.p95_drawdown <= 1.0


# ============================================================
# CONFIDENCE SCALING TESTS
# ============================================================

class TestConfidenceScaling:
    """Tests for confidence-based scaling."""

    def test_confidence_is_gate_not_multiplier(self, calculator):
        """Confidence acts as a gate, not a multiplier."""
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

        # Both above threshold -> same position size
        assert low_conf.position_size == high_conf.position_size

    def test_confidence_below_threshold_returns_none(self, calculator):
        """Confidence below threshold returns None."""
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
        assert calculator.calculate(0, 0.5, 1000, 0.8, "YES") is None
        assert calculator.calculate(1, 0.5, 1000, 0.8, "YES") is None
        assert calculator.calculate(-0.1, 0.5, 1000, 0.8, "YES") is None
        assert calculator.calculate(1.1, 0.5, 1000, 0.8, "YES") is None

    def test_invalid_price_returns_none(self, calculator):
        assert calculator.calculate(0.7, 0, 1000, 0.8, "YES") is None
        assert calculator.calculate(0.7, 1, 1000, 0.8, "YES") is None
        assert calculator.calculate(0.7, -0.1, 1000, 0.8, "YES") is None
        assert calculator.calculate(0.7, 1.1, 1000, 0.8, "YES") is None

    def test_zero_bankroll_returns_none(self, calculator):
        assert calculator.calculate(0.7, 0.5, 0, 0.8, "YES") is None
        assert calculator.calculate(0.7, 0.5, -100, 0.8, "YES") is None


# ============================================================
# RISK CLASSIFICATION TESTS
# ============================================================

class TestRiskClassification:
    """Tests for risk level classification."""

    def test_low_risk_classification(self, calculator):
        result = calculator.calculate(
            estimated_prob=0.63,
            market_price=0.60,
            bankroll=1000,
            confidence=0.6,
            side="YES"
        )
        assert result is not None
        assert result.risk_level in ["LOW", "MEDIUM"]

    def test_high_edge_classification(self, calculator):
        result = calculator.calculate(
            estimated_prob=0.85,
            market_price=0.50,
            bankroll=1000,
            confidence=0.9,
            side="YES"
        )
        assert result is not None
        assert result.risk_level in ["MEDIUM", "HIGH", "EXTREME"]


# ============================================================
# OPPORTUNITY DICT TESTS (with empirical edges)
# ============================================================

class TestOpportunityCalculation:
    """Tests for calculate_from_opportunity with empirical data."""

    def test_sweet_spot_opportunity_uses_empirical(self, calculator):
        """Sweet spot opportunity uses empirical edge data."""
        opp = {
            "price": 0.60,
            "confidence": 0.75,
            "side": "YES",
            "strategy": "MID_RANGE",
            "sector": "politics",
        }
        result = calculator.calculate_from_opportunity(opp, bankroll=1000)

        assert result is not None
        assert result.empirical_edge_used is True
        assert result.position_size > 0

    def test_death_zone_rejected(self, calculator):
        """Death zone opportunity should be rejected (negative edge)."""
        opp = {
            "price": 0.40,
            "confidence": 0.65,
            "side": "YES",
            "strategy": "DIP_BUY",
            "sector": "other",
        }
        result = calculator.calculate_from_opportunity(opp, bankroll=1000)

        # Death zone mispricing is -0.15, so estimated_prob < market_price = no edge
        assert result is None

    def test_near_certain_strategy_boost(self, calculator):
        """NEAR_CERTAIN gets strategy boost on top of empirical."""
        opp = {
            "price": 0.93,
            "confidence": 0.95,
            "side": "YES",
            "strategy": "NEAR_CERTAIN",
            "sector": "politics",
        }
        result = calculator.calculate_from_opportunity(opp, bankroll=1000)
        assert result is not None
        assert result.empirical_edge_used is True

    def test_binance_arb_uses_own_edge(self, calculator):
        """BINANCE_ARB uses Binance implied probability, not empirical."""
        opp = {
            "price": 0.55,
            "confidence": 0.90,
            "side": "YES",
            "strategy": "BINANCE_ARB",
            "binance_implied": 0.65,
        }
        result = calculator.calculate_from_opportunity(opp, bankroll=1000)

        assert result is not None
        assert result.empirical_edge_used is False
        assert result.edge == pytest.approx(0.10, rel=0.01)

    def test_dual_side_arb_uses_own_edge(self, calculator):
        """DUAL_SIDE_ARB uses guaranteed profit, not empirical."""
        opp = {
            "price": 0.48,
            "confidence": 0.95,
            "side": "YES",
            "strategy": "DUAL_SIDE_ARB",
        }
        result = calculator.calculate_from_opportunity(opp, bankroll=1000)

        assert result is not None
        assert result.empirical_edge_used is False

    def test_market_maker_uses_spread(self, calculator):
        """MARKET_MAKER uses spread-based edge, not empirical."""
        opp = {
            "price": 0.50,
            "confidence": 0.75,
            "side": "MM",
            "strategy": "MARKET_MAKER",
            "spread": 0.05,
        }
        result = calculator.calculate_from_opportunity(opp, bankroll=1000)
        # MM may or may not have enough edge depending on spread
        if result:
            assert result.empirical_edge_used is False

    def test_dip_buy_gets_strategy_boost(self, calculator):
        """DIP_BUY gets small boost on top of empirical edge."""
        opp_dip = {
            "price": 0.60,
            "confidence": 0.65,
            "side": "YES",
            "strategy": "DIP_BUY",
            "sector": "economics",
        }
        opp_mid = {
            "price": 0.60,
            "confidence": 0.65,
            "side": "YES",
            "strategy": "MID_RANGE",
            "sector": "economics",
        }
        result_dip = calculator.calculate_from_opportunity(opp_dip, bankroll=1000)
        result_mid = calculator.calculate_from_opportunity(opp_mid, bankroll=1000)

        # DIP_BUY should have slightly larger edge than MID_RANGE (strategy boost)
        assert result_dip is not None
        assert result_mid is not None
        assert result_dip.edge >= result_mid.edge


# ============================================================
# CONVENIENCE FUNCTION TESTS
# ============================================================

class TestConvenienceFunction:
    """Tests for the convenience function."""

    def test_calculate_kelly_position_positive_edge(self):
        position = calculate_kelly_position(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1000,
            kelly_fraction=0.50,
            confidence=0.8,
            side="YES"
        )
        assert position > 0
        assert position <= 300  # Cap 3: max 30% of bankroll

    def test_calculate_kelly_position_no_edge(self):
        position = calculate_kelly_position(
            estimated_prob=0.60,
            market_price=0.60,
            bankroll=1000,
            kelly_fraction=0.50,
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
        assert hasattr(result, 'empirical_edge_used')
        assert hasattr(result, 'monte_carlo_validated')

    def test_kelly_result_types(self, calculator):
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
        assert isinstance(result.empirical_edge_used, bool)
        assert isinstance(result.monte_carlo_validated, bool)


# ============================================================
# EDGE CASE TESTS
# ============================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_very_small_edge(self):
        calc = KellyCriterion(min_edge=0.02)
        result = calc.calculate(
            estimated_prob=0.62,
            market_price=0.60,
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )
        assert result is not None
        assert result.edge == pytest.approx(0.02, abs=0.001)

    def test_extreme_edge(self, calculator):
        result = calculator.calculate(
            estimated_prob=0.99,
            market_price=0.10,
            bankroll=1000,
            confidence=1.0,
            side="YES"
        )
        assert result is not None
        assert result.adjusted_fraction <= 0.30  # Cap 3

    def test_price_near_zero(self, calculator):
        result = calculator.calculate(
            estimated_prob=0.10,
            market_price=0.03,
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )
        assert result is not None

    def test_price_near_one(self, calculator):
        result = calculator.calculate(
            estimated_prob=0.995,
            market_price=0.97,
            bankroll=1000,
            confidence=0.8,
            side="YES"
        )
        assert result is not None

    def test_large_bankroll(self, calculator):
        result = calculator.calculate(
            estimated_prob=0.75,
            market_price=0.60,
            bankroll=1_000_000,
            confidence=0.8,
            side="YES"
        )
        assert result is not None
        assert result.position_size <= 300_000  # Cap 3: 30% max


# ============================================================
# FORMULA EXPLANATION TEST
# ============================================================

class TestExplanation:
    """Test for explanation method."""

    def test_kelly_formula_explanation(self):
        explanation = KellyCriterion.kelly_formula_explanation()
        assert "Half Kelly" in explanation
        assert "Cap 3" in explanation
        assert "Monte Carlo" in explanation
        assert "empirical" in explanation.lower()


# ============================================================
# POLYMARKET TAKER FEE TESTS
# ============================================================

class TestPolymarketTakerFee:
    """Tests for the dynamic taker fee formula: fee = 0.25 * (p * (1-p))^2"""

    def test_fee_at_50_percent(self):
        """Maximum fee at p=0.50 (~1.56%)."""
        fee = polymarket_taker_fee(0.50)
        assert fee == pytest.approx(0.015625, rel=0.001)

    def test_fee_at_60_percent(self):
        """Fee at p=0.60 (DIP_BUY sweet spot) ~1.44%."""
        fee = polymarket_taker_fee(0.60)
        expected = 0.25 * (0.60 * 0.40) ** 2  # 0.0144
        assert fee == pytest.approx(expected, rel=0.001)

    def test_fee_at_90_percent(self):
        """Fee at p=0.90 is small (~0.20%)."""
        fee = polymarket_taker_fee(0.90)
        expected = 0.25 * (0.90 * 0.10) ** 2  # 0.002025
        assert fee == pytest.approx(expected, rel=0.001)
        assert fee < 0.003  # Well under 0.3%

    def test_fee_at_95_percent(self):
        """Fee at p=0.95 (NEAR_CERTAIN zone) is tiny (~0.06%)."""
        fee = polymarket_taker_fee(0.95)
        expected = 0.25 * (0.95 * 0.05) ** 2
        assert fee < 0.001  # Under 0.1%

    def test_fee_symmetric(self):
        """Fee is symmetric: fee(p) == fee(1-p)."""
        assert polymarket_taker_fee(0.30) == pytest.approx(polymarket_taker_fee(0.70))
        assert polymarket_taker_fee(0.20) == pytest.approx(polymarket_taker_fee(0.80))
        assert polymarket_taker_fee(0.10) == pytest.approx(polymarket_taker_fee(0.90))

    def test_fee_at_extremes_near_zero(self):
        """Fee at extremes (p near 0 or 1) is negligible."""
        assert polymarket_taker_fee(0.01) < 0.0001
        assert polymarket_taker_fee(0.99) < 0.0001

    def test_fee_invalid_prices(self):
        """Invalid prices return 0."""
        assert polymarket_taker_fee(0.0) == 0.0
        assert polymarket_taker_fee(1.0) == 0.0
        assert polymarket_taker_fee(-0.5) == 0.0
        assert polymarket_taker_fee(1.5) == 0.0

    def test_fee_monotonic_toward_center(self):
        """Fee increases as price moves toward 0.50."""
        fee_90 = polymarket_taker_fee(0.90)
        fee_70 = polymarket_taker_fee(0.70)
        fee_50 = polymarket_taker_fee(0.50)
        assert fee_90 < fee_70 < fee_50


# ============================================================
# TAKER SLIPPAGE TESTS
# ============================================================

class TestTakerSlippage:
    """Tests for liquidity-based taker slippage model."""

    def test_deep_market_base_slippage(self):
        """Deep market ($50k+) gets base 20bps slippage."""
        slip = taker_slippage(50000)
        assert slip == pytest.approx(0.002, rel=0.01)

    def test_medium_market_higher_slippage(self):
        """Medium market ($10k-25k) gets 1.5x base = 30bps."""
        slip = taker_slippage(15000)
        assert slip == pytest.approx(0.003, rel=0.01)

    def test_thin_market_highest_slippage(self):
        """Thin market (<$10k) gets 3x base = 60bps."""
        slip = taker_slippage(5000)
        assert slip == pytest.approx(0.006, rel=0.01)

    def test_slippage_increases_with_lower_liquidity(self):
        """Less liquidity = more slippage."""
        assert taker_slippage(5000) > taker_slippage(15000) > taker_slippage(50000)

    def test_custom_base_bps(self):
        """Custom base_bps parameter works."""
        slip = taker_slippage(50000, base_bps=10)
        assert slip == pytest.approx(0.001, rel=0.01)

    def test_boundary_10k(self):
        """Exactly $10k is medium tier, not thin."""
        assert taker_slippage(10000) == pytest.approx(0.003, rel=0.01)

    def test_boundary_25k(self):
        """Exactly $25k is deep tier."""
        assert taker_slippage(25000) == pytest.approx(0.002, rel=0.01)

    def test_zero_liquidity(self):
        """Zero liquidity gets thin market slippage."""
        slip = taker_slippage(0)
        assert slip == pytest.approx(0.006, rel=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
