from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any

class TradeData(BaseModel):
    """
    Standardizes the data packet sent from the Bot to the API/UI.
    """
    timestamp: str
    token_id: str
    midpoint: float
    spread: float
    latency_ms: float
    fee_bps: int
    vol_state: str = "LOW_VOL"
    binance_price: float = 0.0
    inventory: float = 0.0
    action: str = "" # "TRADE_PLACED", "SKIPPED_FILTER", etc.
    
    # Optional fields for deeper introspection
    bids: Optional[list] = None
    asks: Optional[list] = None
    
    # Financial Metrics (Added for Frontend)
    virtual_pnl: float = 0.0
    session_volume: float = 0.0
    total_equity: float = 0.0
    buying_power: float = 0.0

class BotParams(BaseModel):
    """
    Dynamic parameters that can be updated via the API.
    """
    spread_offset: float = Field(0.005, description="Base spread offset in dollars (e.g., 0.005 = 0.5 cents)")
    order_size: int = Field(10, description="Standard order size in shares")
    is_running: bool = Field(True, description="Master switch for the trading loop")
    
    # Advanced 
    max_position: int = Field(50, description="Max absolute position size")
    min_liquidity: float = Field(10000.0, description="Minimum market liquidity to trade")

class KillSwitchRequest(BaseModel):
    """
    Payload for the emergency stop endpoint.
    """
    reason: str = "Emergency Stop Triggered by User"
