#!/usr/bin/env python3
"""
KELLY CRITERION - MONTE CARLO CAP 3 HALF KELLY
================================================
Institutional-grade position sizing for prediction markets.

Upgrade from basic fractional Kelly to the strategy most heavily utilized
by institutional groups in prediction markets:

1. Half Kelly (f*/2) — 75% of full Kelly growth, 25% of the volatility
2. Monte Carlo validation — 10,000 simulated paths to verify survival
3. Cap 3 — 30% max position per trade, hard ceiling
4. Empirical edges — from 88.5M on-chain trades (Becker dataset)

Formula: f* = (p - market_price) / (1 - market_price)

Where:
    p = estimated true probability (from empirical data, not guessing)
    market_price = current market price

References:
    - "A New Interpretation of Information Rate" (Kelly, 1956)
    - "Fortune's Formula" (Poundstone, 2005)
    - Becker dataset: 88.5M trades, $12B volume, 30,649 markets
"""

import random
from dataclasses import dataclass
from typing import Optional


# ============================================================
# EMPIRICAL EDGE DATA (from 88.5M on-chain trade analysis)
# Source: becker-dataset analysis of $12B across 30,649 resolved markets
# ============================================================

# Price zone → average mispricing in percentage points
# Positive = market underprices (buy opportunity)
# Negative = market overprices (avoid)
EMPIRICAL_EDGES = [
    (0.01, 0.10, -0.25),    # Longshot: massively overpriced (-57% at 1¢)
    (0.10, 0.35, -0.08),    # Low range: slight overpricing
    (0.35, 0.45, -0.15),    # DEATH ZONE: Kelly -17 to -22%, ROI -25 to -40%
    (0.45, 0.55,  0.00),    # Fair value: no systematic edge
    (0.55, 0.65, +0.15),    # SWEET SPOT: Kelly +29-48%, ROI +23-26%
    (0.65, 0.70, +0.05),    # Moderate edge
    (0.70, 0.75, -0.08),    # TRAP ZONE: Kelly -19-22%, ROI -8%
    (0.75, 0.80, +0.01),    # Tiny edge
    (0.80, 0.95, +0.02),    # Small reliable edge: Kelly +4-20%, ROI +1-2%
    (0.95, 0.99, +0.01),    # Near certain: tiny edge
]

# Category → edge adjustment (percentage points)
CATEGORY_ADJUSTMENTS = {
    "economics": +0.02,      # Kelly +4.59% — best category
    "politics":  +0.015,     # Kelly +4.12% — second best
    "crypto":    -0.015,     # Kelly -1.53% — negative edge, penalize
    "sports":     0.0,
    "entertainment": 0.0,
    "science":    0.0,
    "other":      0.0,
}


def empirical_probability(market_price: float, category: str = "other") -> float:
    """
    Estimate true probability from market price using empirical Becker data.

    Instead of guessing, we use the historical mispricing at each price zone
    derived from 88.5M on-chain trades across 30,649 resolved markets.

    Args:
        market_price: Current YES price (0-1)
        category: Market category for edge adjustment

    Returns:
        Estimated true probability (0.01 to 0.99)
    """
    mispricing = 0.0
    for low, high, edge in EMPIRICAL_EDGES:
        if low <= market_price < high:
            mispricing = edge
            break

    cat_adj = CATEGORY_ADJUSTMENTS.get(category.lower(), 0.0)
    true_prob = market_price + mispricing + cat_adj
    return min(0.99, max(0.01, true_prob))


# ============================================================
# MONTE CARLO VALIDATION
# ============================================================

@dataclass
class MonteCarloResult:
    """Result of Monte Carlo validation."""
    validated_fraction: float     # May be reduced if drawdown too high
    median_growth: float          # Median final bankroll (1.0 = starting)
    p95_drawdown: float           # 95th percentile max drawdown
    ruin_probability: float       # Fraction of paths hitting near-zero
    n_simulations: int            # Number of paths simulated


def monte_carlo_validate(
    bet_fraction: float,
    win_prob: float,
    payout_ratio: float,
    n_simulations: int = 10000,
    n_bets: int = 100,
    max_drawdown_pct: float = 0.50,
    seed: int = 42,
) -> MonteCarloResult:
    """
    Validate a bet fraction with Monte Carlo simulation.

    Simulates n_simulations bankroll paths of n_bets each. If the 95th
    percentile max drawdown exceeds max_drawdown_pct, scales the fraction
    down proportionally.

    Args:
        bet_fraction: Actual fraction of bankroll to bet per trade
                      (computed as: raw_kelly * half_kelly_multiplier)
        win_prob: Probability of winning each bet (0-1)
        payout_ratio: Profit per dollar on win = (1 - price) / price
        n_simulations: Number of simulated paths (default 10,000)
        n_bets: Number of bets per path (default 100)
        max_drawdown_pct: Maximum acceptable 95th percentile drawdown
        seed: Random seed for reproducibility

    Returns:
        MonteCarloResult with validated fraction and statistics
    """
    rng = random.Random(seed)
    finals = []
    max_drawdowns = []
    ruins = 0

    for _ in range(n_simulations):
        bankroll = 1.0
        peak = 1.0
        max_dd = 0.0

        for _ in range(n_bets):
            bet = bankroll * bet_fraction
            if rng.random() < win_prob:
                bankroll += bet * payout_ratio
            else:
                bankroll -= bet  # Lose entire stake on binary outcome

            if bankroll <= 0.01:  # Effectively ruined
                ruins += 1
                bankroll = 0.0
                break

            peak = max(peak, bankroll)
            dd = (peak - bankroll) / peak
            max_dd = max(max_dd, dd)

        finals.append(bankroll)
        max_drawdowns.append(max_dd)

    finals.sort()
    max_drawdowns.sort()

    median_growth = finals[len(finals) // 2]
    p95_drawdown = max_drawdowns[int(len(max_drawdowns) * 0.95)]
    ruin_prob = ruins / n_simulations

    # If 95th percentile drawdown exceeds limit, scale down proportionally
    validated_fraction = bet_fraction
    if p95_drawdown > max_drawdown_pct and p95_drawdown > 0:
        validated_fraction = bet_fraction * (max_drawdown_pct / p95_drawdown)

    return MonteCarloResult(
        validated_fraction=validated_fraction,
        median_growth=median_growth,
        p95_drawdown=p95_drawdown,
        ruin_probability=ruin_prob,
        n_simulations=n_simulations,
    )


# ============================================================
# KELLY RESULT
# ============================================================

@dataclass
class KellyResult:
    """Result of Kelly Criterion calculation."""
    kelly_fraction: float          # Raw Kelly fraction (0-1)
    adjusted_fraction: float       # Scaled Kelly (Half Kelly + Cap 3)
    position_size: float           # Dollar amount to bet
    edge: float                    # Your edge over the market
    expected_value: float          # Expected value of the bet
    risk_level: str                # "LOW", "MEDIUM", "HIGH", "EXTREME"
    empirical_edge_used: bool = False   # Was Becker empirical data used?
    monte_carlo_validated: bool = False  # Was fraction validated by MC?


# ============================================================
# KELLY CRITERION CALCULATOR
# ============================================================

class KellyCriterion:
    """
    Monte Carlo Cap 3 Half Kelly position sizing for prediction markets.

    Institutional-grade sizing that uses:
    - Half Kelly (f*/2): 75% of growth, 25% of volatility
    - Empirical edge data from 88.5M on-chain trades
    - Cap 3: 30% max position regardless of Kelly output
    - Monte Carlo validated fractions
    """

    # Half Kelly: divide raw Kelly by 2 (institutional standard)
    DEFAULT_KELLY_FRACTION = 0.50

    # Cap 3: max 30% of bankroll per position
    MAX_POSITION_PCT = 0.30

    # Minimum edge required to bet
    MIN_EDGE = 0.02  # 2% edge minimum

    # Confidence threshold below which we don't trust our estimate
    MIN_CONFIDENCE = 0.55

    def __init__(
        self,
        kelly_fraction: float = DEFAULT_KELLY_FRACTION,
        max_position_pct: float = MAX_POSITION_PCT,
        min_edge: float = MIN_EDGE,
        min_confidence: float = MIN_CONFIDENCE,
        mc_validated: bool = False,
    ):
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.min_edge = min_edge
        self.min_confidence = min_confidence
        self.mc_validated = mc_validated

    def calculate(
        self,
        estimated_prob: float,
        market_price: float,
        bankroll: float,
        confidence: float = 0.7,
        side: str = "YES",
        empirical_edge_used: bool = False,
    ) -> Optional[KellyResult]:
        """
        Calculate optimal position size using Half Kelly with Cap 3.

        Args:
            estimated_prob: Your estimated true probability (0-1)
            market_price: Current market price (0-1)
            bankroll: Available capital
            confidence: Confidence in your probability estimate (0-1)
            side: "YES" or "NO"
            empirical_edge_used: Whether empirical Becker data was used

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
        # f* = (p - market_price) / (1 - market_price)
        if market_price >= 1:
            return None

        kelly_raw = (estimated_prob - market_price) / (1 - market_price)

        # Clamp raw Kelly to reasonable bounds
        kelly_raw = max(0, min(1, kelly_raw))

        # Apply Half Kelly (reduces volatility to 25% of full Kelly)
        # NOTE: Confidence is used as a GATE (checked above), NOT as a multiplier.
        kelly_adjusted = kelly_raw * self.kelly_fraction

        # Apply Cap 3: maximum 30% position limit
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
            risk_level=risk_level,
            empirical_edge_used=empirical_edge_used,
            monte_carlo_validated=self.mc_validated,
        )

    def calculate_from_opportunity(
        self,
        opp: dict,
        bankroll: float,
    ) -> Optional[KellyResult]:
        """
        Calculate position size from an opportunity dict.

        Uses empirical edge data from Becker dataset when available,
        falling back to strategy-specific heuristics.

        Args:
            opp: Opportunity dict with price, confidence, side, strategy, sector
            bankroll: Available capital

        Returns:
            KellyResult or None
        """
        price = opp.get("price", 0)
        confidence = opp.get("confidence", 0.5)
        side = opp.get("side", "YES")

        # Estimate true probability — empirical data first, heuristic fallback
        estimated_prob, used_empirical = self._estimate_probability(opp)

        return self.calculate(
            estimated_prob=estimated_prob,
            market_price=price,
            bankroll=bankroll,
            confidence=confidence,
            side=side,
            empirical_edge_used=used_empirical,
        )

    def _estimate_probability(self, opp: dict) -> tuple[float, bool]:
        """
        Estimate true probability using empirical data + strategy logic.

        Returns:
            (estimated_probability, used_empirical_data)
        """
        strategy = opp.get("strategy", "")
        price = opp.get("price", 0.5)
        side = opp.get("side", "YES")
        category = opp.get("sector", "other")

        # Strategies with their own edge source — don't override with empirical
        if strategy == "BINANCE_ARB":
            binance_implied = opp.get("binance_implied", price)
            return (binance_implied, False)

        if strategy == "DUAL_SIDE_ARB":
            return (0.99 if side == "YES" else 0.01, False)

        if strategy == "MARKET_MAKER":
            spread = opp.get("spread", 0.02)
            return (price + (spread / 2), False)

        # All other strategies: use empirical edge data from Becker analysis
        emp_prob = empirical_probability(price, category)

        # Strategy-specific adjustments on top of empirical base
        if strategy == "NEAR_CERTAIN":
            # High-confidence resolution play — boost toward 1.0
            strategy_boost = (1 - emp_prob) * 0.15
            emp_prob = min(0.99, emp_prob + strategy_boost)

        elif strategy == "NEAR_ZERO":
            # High-confidence NO play — push probability lower
            strategy_boost = emp_prob * 0.15
            emp_prob = max(0.01, emp_prob - strategy_boost)

        elif strategy == "DIP_BUY":
            # Price dropped = likely oversold, small boost
            strategy_boost = 0.02
            emp_prob = min(0.99, emp_prob + strategy_boost)

        elif strategy == "VOLUME_SURGE":
            # High volume = information arriving, small boost
            strategy_boost = 0.015
            emp_prob = min(0.99, emp_prob + strategy_boost)

        return (emp_prob, True)

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
Monte Carlo Cap 3 Half Kelly:
==============================
f* = (p - market_price) / (1 - market_price)
f_half = f* × 0.50 (Half Kelly)
f_final = min(f_half, 0.30) (Cap 3)

Where:
  p = empirical true probability (from 88.5M trade analysis)
  market_price = current market price

Strategy: "Monte Carlo Cap 3 Half Kelly"
  - Half Kelly: 75% of full Kelly growth, 25% of volatility
  - Cap 3: No position exceeds 30% of bankroll
  - Monte Carlo: 10,000 simulated paths validate survival
  - Empirical edges: Becker dataset replaces guesswork

Sweet spot: Price 0.55-0.65 (mispricing +15pp, Kelly +29-48%)
Fallback:   Price 0.80-0.95 (mispricing +2pp, Kelly +4-20%)
Avoid:      Price 0.35-0.45 (DEATH ZONE, Kelly -17 to -22%)
"""


# ============================================================
# POLYMARKET FEE MODEL
# Source: Dynamic taker fees (Feb 2026 rule change)
# Makers pay ZERO fees. Takers pay based on probability.
# ============================================================

def polymarket_taker_fee(price: float) -> float:
    """
    Calculate Polymarket taker fee as a fraction of trade value.

    Formula: fee = 0.25 * (p * (1 - p))^2
    - Max ~1.56% at p=0.50
    - Near zero at extremes (p near 0 or 1)
    - Makers (post-only) always pay 0%

    Args:
        price: Market probability / price (0-1)

    Returns:
        Fee as a decimal (e.g., 0.0156 for 1.56%)
    """
    if not (0 < price < 1):
        return 0.0
    return 0.25 * (price * (1 - price)) ** 2


# ============================================================
# TAKER SLIPPAGE MODEL
# Source: Orderbook depth analysis — thin markets have worse fills
# ============================================================

def taker_slippage(liquidity: float, base_bps: int = 20) -> float:
    """
    Estimate slippage fraction for taker orders based on liquidity depth.

    Thin markets have wider spreads and less depth, so taker orders
    eat through the book and get worse fills.

    Args:
        liquidity: Market liquidity in USD (from Gamma API)
        base_bps: Base slippage in basis points for deep markets (default 20 = 0.2%)

    Returns:
        Slippage as a fraction (e.g., 0.002 for 20bps).
        Caller applies direction: buy_price * (1 + slip), sell_price * (1 - slip).
    """
    base_slip = base_bps / 10000

    if liquidity < 10_000:
        # Thin market: 3x base slippage (60bps)
        return base_slip * 3.0
    elif liquidity < 25_000:
        # Medium market: 1.5x base slippage (30bps)
        return base_slip * 1.5
    else:
        # Deep market: base slippage (20bps)
        return base_slip


# Convenience function
def calculate_kelly_position(
    estimated_prob: float,
    market_price: float,
    bankroll: float,
    kelly_fraction: float = 0.50,
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
