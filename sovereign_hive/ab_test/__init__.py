"""
A/B Testing Framework for Trading Strategies
=============================================

Run isolated strategies to compare performance:
    python -m sovereign_hive.ab_test.strategy_runner --strategy MARKET_MAKER
    python -m sovereign_hive.ab_test.compare_strategies --watch
"""

from .strategy_runner import IsolatedStrategyRunner, VALID_STRATEGIES

__all__ = ["IsolatedStrategyRunner", "VALID_STRATEGIES"]
