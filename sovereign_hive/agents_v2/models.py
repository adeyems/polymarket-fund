"""Pydantic models for the multi-agent trading system."""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ValidationRequest(BaseModel):
    """Trade validation request from the trader to the validator."""
    condition_id: str
    question: str
    strategy: str
    side: Optional[str] = None
    price: Optional[float] = None
    amount: float
    confidence: Optional[float] = None
    ai_score: Optional[float] = None
    portfolio_summary: Optional[Dict[str, Any]] = None


class ValidationResponse(BaseModel):
    """Trade validation response from the validator."""
    approved: bool
    reason: str
    risk_flags: List[str] = []


class Heartbeat(BaseModel):
    """Heartbeat written by the trader, read by the watchdog."""
    ts: str
    positions: int
    balance: float
    pnl: float
    trades: int = 0
    win_rate: float = 0.0


class WatchdogEvent(BaseModel):
    """Event written by the watchdog, read by the alerter."""
    ts: str
    event_type: str  # "restart", "stale_heartbeat", "anomaly", "api_down"
    message: str
    severity: str = "warning"  # "info", "warning", "critical"


class PortfolioSnapshot(BaseModel):
    """Snapshot of portfolio state for change detection."""
    balance: float
    positions: Dict[str, Any]
    trade_count: int
    pnl: float
