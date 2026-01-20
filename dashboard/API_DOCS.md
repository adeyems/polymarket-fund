# Polymarket HFT API Documentation

**Base URL**: `http://localhost:8002` (or your server IP)
**WebSocket URL**: `ws://localhost:8002/api/v1/ws/stream`

---

## Quick Start

```bash
# Navigate to project directory
cd /path/to/polymarket-trading

# Start the server (use hypercorn, NOT uvicorn)
python3 -m hypercorn api_bridge:app --bind 0.0.0.0:8002

# Verify: http://localhost:8002/docs
```

---

## Security
The `/control/` endpoints are protected. All `POST`, `PUT`, and `PATCH` requests must include:
- **Header**: `X-API-KEY`
- **Value**: Your `DASHBOARD_API_KEY` (from `.env`)

---

## 1. WebSocket Stream
**Endpoint**: `/api/v1/ws/stream`
**Method**: `GET` (Upgrade to WebSocket)

### Message Schema (`TradeData`)
The server pushes JSON packets on every internal tick (approx 100ms - 1s).

```json
{
  "timestamp": "2026-01-18T10:00:00.123456",
  "token_id": "1234567890",
  "midpoint": 0.52,
  "spread": 0.01,
  "latency_ms": 150.5,
  "fee_bps": 0,
  "vol_state": "LOW_VOL",
  "binance_price": 98500.00,
  "inventory": 15.0,
  "action": "TRADE_PLACED",
  "bids": [
    {"price": 0.51, "size": 100},
    {"price": 0.50, "size": 500}
  ],
  "asks": [
    {"price": 0.53, "size": 100},
    {"price": 0.54, "size": 500}
  ],
  "virtual_pnl": 12.50,
  "session_volume": 450.00,
  "total_equity": 1012.50,
  "buying_power": 940.00
}
```

### Field Definitions (New)
- **virtual_pnl**: Floating point profit/loss (Mark-to-Market).
- **session_volume**: Total notional volume traded since server start.
- **total_equity**: Current Account Value (Cash + Inventory Value).
- **buying_power**: Available Cash for new orders.

### Client Example (React/JS)
```javascript
const ws = new WebSocket("ws://localhost:8002/api/v1/ws/stream");

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Tick:", data.midpoint);
  // Update state: setRows((prev) => [data, ...prev]);
};
```

---

## 2. Control Endpoints

### Update Parameters
**Endpoint**: `/api/v1/control/parameters`
**Method**: `PATCH`
**Content-Type**: `application/json`

Update the bot's live trading variables without restarting.

**Request Body (`BotParams`)**:
```json
{
  "spread_offset": 0.02,        // Increase spread to 2 cents
  "order_size": 20,             // Increase size to 20 shares
  "max_position": 100,          // Cap position at 100
  "min_liquidity": 5000.0,      // Loosen liquidity filter
  "is_running": true            // Set false to pause loop
}
```
*Note: You can send partial updates.*

### Emergency Stop (Kill Switch)
**Endpoint**: `/api/v1/control/emergency-stop`
**Method**: `POST`
**Content-Type**: `application/json`

Immediately pauses the trading loop and triggers a `cancel_all_orders` command.

**Request Body (`KillSwitchRequest`)**:
```json
{
  "reason": "Market crash detected"
}
```

**Response**:
```json
{
  "status": "EMERGENCY_STOP_ACTIVATED",
  "reason": "Market crash detected"
}
```

---

## 3. Health Check
**Endpoint**: `/health`
**Method**: `GET`
*(Note: Health check typically remains at root or strictly utility path, but can be moved if requested. Kept at /health for standard probe compatibility)*

Returns status and active connection count.
```json
{
  "status": "ok",
  "connections": 1
}
```
