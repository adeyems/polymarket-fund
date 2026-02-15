#!/usr/bin/env python3
"""
KELLY CRITERION - OPTIMAL POSITION SIZING
==========================================
Mathematical framework for position sizing based on edge and confidence.

Formula: f* = (p*b - q) / b

For prediction markets:
    f* = (estimated_prob - market_price) / (1 - market_price)

Where:
    p = estimated true probability
    q = 1 - p (probability of losing)
    b = odds = (1/price) - 1

References:
    - "A New Interpretation of Information Rate" (Kelly, 1956)
    - "Fortune's Formula" (Poundstone, 2005)
    - RohOnChain Polymarket trading articles
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class KellyResult:
    """Result of Kelly Criterion calculation."""
    kelly_fraction: float      # Raw Kelly fraction (0-1)
    adjusted_fraction: float   # Scaled Kelly (applying fractional Kelly)
    position_size: float       # Dollar amount to bet
    edge: float               # Your edge over the market
    expected_value: float     # Expected value of the bet
    risk_level: str           # "LOW", "MEDIUM", "HIGH", "EXTREME"


class KellyCriterion:
    """
    Kelly Criterion calculator for prediction market position sizing.

    The Kelly Criterion tells you the optimal fraction of your bankroll
    to bet given your edge. Using fractional Kelly (typically 25-50%)
    reduces volatility while capturing most of the growth.
    """

    # Fractional Kelly multiplier (0.25 = quarter Kelly, safer)
    DEFAULT_KELLY_FRACTION = 0.25

    # Maximum position size regardless of Kelly (risk management)
    MAX_POSITION_PCT = 0.15

    # Minimum edge required to bet
    MIN_EDGE = 0.02  # 2% edge minimum

    # Confidence threshold below which we don't trust our estimate
    MIN_CONFIDENCE = 0.55

    def __init__(
        self,
        kelly_fraction: float = DEFAULT_KELLY_FRACTION,
        max_position_pct: float = MAX_POSITION_PCT,
        min_edge: float = MIN_EDGE,
        min_confidence: float = MIN_CONFIDENCE
    ):
        """
        Initialize Kelly calculator.

        Args:
            kelly_fraction: Fraction of full Kelly to use (0.25 = quarter Kelly)
            max_position_pct: Maximum position size as fraction of bankroll
            min_edge: Minimum edge required to take a position
            min_confidence: Minimum confidence in probability estimate
        """
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.min_edge = min_edge
        self.min_confidence = min_confidence

    def calculate(
        self,
        estimated_prob: float,
        market_price: float,
        bankroll: float,
        confidence: float = 0.7,
        side: str = "YES"
    ) -> Optional[KellyResult]:
        """
        Calculate optimal position size using Kelly Criterion.

        Args:
            estimated_prob: Your estimated true probability (0-1)
            market_price: Current market price (0-1)
            bankroll: Available capital
            confidence: Confidence in your probability estimate (0-1)
            side: "YES" or "NO"

        Returns:
            KellyResult with position sizing info, or None if no bet recommended
        """
        # Validate inputs
        if not (0 < estimated_prob < 1):
            return None
        if not (0 < market_price < 1):
            return None
        if bankroll <= 0:
            return None
        if confidence < self.min_confidence:
            return None

        # For NO bets, invert the prices
        if side == "NO":
            estimated_prob = 1 - estimated_prob
            market_price = 1 - market_price

        # Calculate edge
        edge = estimated_prob - market_price

        # Check minimum edge
        if edge < self.min_edge:
            return None

        # Kelly formula for binary outcomes:
        # f* = (p*b - q) / b where b = (1/price) - 1
        # Simplified: f* = (p - market_price) / (1 - market_price)
        if market_price >= 1:
            return None

        kelly_raw = (estimated_prob - market_price) / (1 - market_price)

        # Clamp raw Kelly to reasonable bounds
        kelly_raw = max(0, min(1, kelly_raw))

        # Apply fractional Kelly (reduces volatility)
        # Also scale by confidence (less confident = smaller bet)
        kelly_adjusted = kelly_raw * self.kelly_fraction * confidence

        # Apply maximum position limit
        kelly_adjusted = min(kelly_adjusted, self.max_position_pct)

        # Calculate position size
        position_size = bankroll * kelly_adjusted

        # Expected value = edge * position_size
        expected_value = edge * position_size

        # Risk classification
        risk_level = self._classify_risk(kelly_raw, edge)

        return KellyResult(
            kelly_fraction=kelly_raw,
            adjusted_fraction=kelly_adjusted,
            position_size=position_size,
            edge=edge,
            expected_value=expected_value,
            risk_level=risk_level
        )

    def calculate_from_opportunity(
        self,
        opp: dict,
        bankroll: float
    ) -> Optional[KellyResult]:
        """
        Calculate position size from an opportunity dict.

        Args:
            opp: Opportunity dict with price, confidence, side
            bankroll: Available capital

        Returns:
            KellyResult or None
        """
        price = opp.get("price", 0)
        confidence = opp.get("confidence", 0.5)
        side = opp.get("side", "YES")
        strategy = opp.get("strategy", "")

        # Estimate true probability based on strategy
        estimated_prob = self._estimate_probability(opp)

        return self.calculate(
            estimated_prob=estimated_prob,
            market_price=price,
            bankroll=bankroll,
            confidence=confidence,
            side=side
        )

    def _estimate_probability(self, opp: dict) -> float:
        """
        Estimate true probability based on opportunity and strategy.

        Different strategies imply different probability estimates:
        - NEAR_CERTAIN: We think YES probability is higher than market
        - NEAR_ZERO: We think NO probability is higher than market
        - BINANCE_ARB: Edge comes from price discrepancy
        - MARKET_MAKER: Edge comes from spread, not direction
        """
        strategy = opp.get("strategy", "")
        price = opp.get("price", 0.5)
        confidence = opp.get("confidence", 0.5)
        side = opp.get("side", "YES")

        if strategy == "NEAR_CERTAIN":
            # We believe YES is more likely than market shows
            # Estimate = price + edge based on confidence
            edge_estimate = (1 - price) * confidence * 0.5
            return min(0.99, price + edge_estimate)

        elif strategy == "NEAR_ZERO":
            # We believe NO is more likely than market shows
            # For NO bets, price is inverted in calculate()
            edge_estimate = price * confidence * 0.5
            return max(0.01, price - edge_estimate)

        elif strategy == "BINANCE_ARB":
            # Edge comes from Binance price discrepancy
            binance_implied = opp.get("binance_implied", price)
            return binance_implied

        elif strategy == "DUAL_SIDE_ARB":
            # Arbitrage - guaranteed profit, use max confidence
            return 0.99 if side == "YES" else 0.01

        elif strategy == "MARKET_MAKER":
            # Market maker edge is from spread, not direction
            # Use neutral probability but scale by spread
            spread = opp.get("spread", 0.02)
            return price + (spread / 2)  # Slight edge from spread

        else:
            # Default: slight edge based on confidence
            if side == "YES":
                return min(0.95, price + confidence * 0.1)
            else:
                return max(0.05, price - confidence * 0.1)

    def _classify_risk(self, kelly_fraction: float, edge: float) -> str:
        """Classify risk level of the bet."""
        if kelly_fraction < 0.05 and edge < 0.05:
            return "LOW"
        elif kelly_fraction < 0.15 and edge < 0.10:
            return "MEDIUM"
        elif kelly_fraction < 0.30:
            return "HIGH"
        else:
            return "EXTREME"

    @staticmethod
    def kelly_formula_explanation() -> str:
        """Return explanation of Kelly Criterion for logging."""
        return """
Kelly Criterion Formula:
========================
f* = (p*b - q) / b

For prediction markets:
f* = (estimated_prob - market_price) / (1 - market_price)

Where:
  f* = optimal fraction of bankroll to bet
  p = estimated true probability
  q = 1 - p (probability of losing)
  b = odds = (1/price) - 1

Example:
  Market price: $0.60 for YES
  You estimate: 70% true probability

  f* = (0.70 - 0.60) / (1 - 0.60) = 0.10 / 0.40 = 25%

  With quarter Kelly (0.25 multiplier):
  Bet = 25% * 0.25 = 6.25% of bankroll

Benefits of Fractional Kelly:
  - Reduces volatility significantly
  - Still captures most of the growth
  - More forgiving of estimation errors
"""


# Convenience function
def calculate_kelly_position(
    estimated_prob: float,
    market_price: float,
    bankroll: float,
    kelly_fraction: float = 0.25,
    confidence: float = 0.7,
    side: str = "YES"
) -> float:
    """
    Quick function to calculate Kelly position size.

    Returns dollar amount to bet, or 0 if no bet recommended.
    """
    calculator = KellyCriterion(kelly_fraction=kelly_fraction)
    result = calculator.calculate(
        estimated_prob=estimated_prob,
        market_price=market_price,
        bankroll=bankroll,
        confidence=confidence,
        side=side
    )
    return result.position_size if result else 0.0
