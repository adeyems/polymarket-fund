"""
BACKTESTING FRAMEWORK
======================
Test trading strategies on historical data before risking real capital.
"""

from .engine import BacktestEngine
from .metrics import PerformanceMetrics
from .data_loader import DataLoader

__all__ = ["BacktestEngine", "PerformanceMetrics", "DataLoader"]
