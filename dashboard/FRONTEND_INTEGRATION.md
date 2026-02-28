# QuesQuant HFT Backend - API Specification

> **For:** Frontend Agent (Next.js 16 + React Native)  
> **Version:** 1.0  
> **Last Updated:** 2026-01-19

---

## 1. Connection Details

| Property | Value |
|----------|-------|
| **Base URL** | `http://localhost:8002` |
| **WebSocket URL** | `ws://localhost:8002/api/v1/ws/stream` |
| **Protocol** | HTTP/1.1, WebSocket |
| **Content-Type** | `application/json` |

### Server Launch Command
```bash
python3 -m hypercorn api_bridge:app --bind 0.0.0.0:8002
```

---

## 2. Authentication

| Endpoint Type | Auth Required | Header |
|---------------|---------------|--------|
| `GET /health` | ❌ No | - |
| `WS /api/v1/ws/stream` | ❌ No | - |
| `PATCH /api/v1/control/parameters` | ✅ Yes | `X-API-KEY` |
| `POST /api/v1/control/emergency-stop` | ✅ Yes | `X-API-KEY` |

### Security Key
- **Header Name:** `X-API-KEY`
- **Source:** `DASHBOARD_API_KEY` from backend `.env`
- **Frontend Handling:** Store in server-side environment only (NOT `NEXT_PUBLIC_`). Proxy via Next.js API Routes.

---

## 3. WebSocket Stream

### Endpoint
```
ws://localhost:8002/api/v1/ws/stream
```

### Behavior
- **Direction:** Server → Client (push-only)
- **Frequency:** ~100ms - 5s (variable based on market activity)
- **Reconnect:** Client should implement auto-reconnect on disconnect

### Message Schema (`TradeData`)

```json
{
  "timestamp": "2026-01-19T14:30:00.123456",
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
  ]
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO 8601 string | Server-side tick timestamp |
| `token_id` | string | Polymarket market token ID |
| `midpoint` | float | Current mid-price (0.00 - 1.00) |
| `spread` | float | Bid-ask spread in dollars |
| `latency_ms` | float | API round-trip latency |
| `fee_bps` | int | Taker fee in basis points |
| `vol_state` | string | `"LOW_VOL"` or `"HIGH_VOL"` |
| `binance_price` | float | Reference spot price (BTC/ETH) |
| `inventory` | float | Current position size |
| `action` | string | `"TRADE_PLACED"`, `"SKIPPED_FILTER"`, etc. |
| `bids` | array | Top 3 bid levels |
| `asks` | array | Top 3 ask levels |
| `virtual_pnl` | float | Session PnL (Trading Profit - Fees - Gas) |
| `session_volume` | float | Total trading volume in session |
| `total_equity` | float | Current total equity (cash + positions) |
| `buying_power` | float | Available cash for trading |
| `total_gas_spent_usd` | float | **NEW** Total gas spent in USD |
| `total_trades_count` | int | **NEW** Number of filled trades |
| `total_order_updates` | int | **NEW** Number of order updates (reposts) |
| `current_matic_balance` | float | **NEW** Current MATIC/POL balance for gas |

---

## 4. Control Endpoints

### 4.1 Update Parameters

**Endpoint:** `PATCH /api/v1/control/parameters`  
**Auth:** Required (`X-API-KEY` header)

#### Request Body (`BotParams`)

```json
{
  "spread_offset": 0.02,
  "order_size": 20,
  "max_position": 100,
  "min_liquidity": 5000.0,
  "is_running": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `spread_offset` | float | 0.005 | Spread offset in dollars |
| `order_size` | int | 10 | Order size in shares |
| `max_position` | int | 50 | Max absolute position |
| `min_liquidity` | float | 10000.0 | Min market liquidity filter |
| `is_running` | bool | true | Master on/off switch |

> **Note:** Partial updates supported. Only send fields you want to change.

#### Response (200 OK)

```json
{
  "status": "updated",
  "current_state": {
    "spread_offset": 0.02,
    "order_size": 20,
    "max_position": 100,
    "min_liquidity": 5000.0,
    "is_running": true
  }
}
```

---

### 4.2 Emergency Stop (Kill Switch)

**Endpoint:** `POST /api/v1/control/emergency-stop`  
**Auth:** Required (`X-API-KEY` header)

#### Request Body (`KillSwitchRequest`)

```json
{
  "reason": "Manual stop via dashboard"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reason` | string | No | Audit log reason |

#### Response (200 OK)

```json
{
  "status": "EMERGENCY_STOP_ACTIVATED",
  "reason": "Manual stop via dashboard"
}
```

---

## 5. Health Check

**Endpoint:** `GET /health`  
**Auth:** Not required

#### Response (200 OK)

```json
{
  "status": "ok",
  "connections": 1
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"ok"` if server is running |
| `connections` | int | Active WebSocket connections |

---

## 6. Error Responses

### 403 Forbidden (Missing/Invalid API Key)

```json
{
  "detail": "Invalid or missing X-API-KEY"
}
```

### 500 Server Error (API Key Not Configured)

```json
{
  "detail": "Security key not configured on server"
}
```

---

## 7. Frontend Environment Variables

```env
# Option 1: Tunnel (Recommended for Security)
NEXT_PUBLIC_API_URL=http://localhost:8002
NEXT_PUBLIC_WS_URL=ws://localhost:8002

# Option 2: Direct Connection (If on VPN/Mesh)
# NEXT_PUBLIC_API_URL=http://100.50.168.104:8002
# NEXT_PUBLIC_WS_URL=ws://100.50.168.104:8002

# Private (server-side only, for API route proxies)
DASHBOARD_API_KEY=<REDACTED — generate your own with: python -c "import secrets; print(secrets.token_urlsafe(32))">
```

---

## 8. Integration Notes for QuesQuant Frontend

### Web (Next.js 16)
- Use `TradingContext` to hold WebSocket state
- `useTradeStream` hook should connect to `ws://localhost:8002/api/v1/ws/stream`
- Control actions (kill switch, parameters) must go through Next.js API Routes to keep `DASHBOARD_API_KEY` server-side

### Mobile (React Native)
- Same WebSocket URL
- Implement `react-native-haptic-feedback` for kill switch confirmation
- Handle network drops with exponential backoff reconnect

### Critical UI Elements
- **Latency Indicator:** Show warning if `latency_ms > 500`
- **Kill Switch:** Should be prominent, possibly with confirmation modal
- **Inventory Display:** Show `inventory` with color coding (green = balanced, red = directional risk)

---

## 9. Handling Heartbeats (Action: "HEARTBEAT")

The backend sends a "Heartbeat" message every 5 seconds to keep the WebSocket connection alive and update top-level metrics (Equity, PnL, etc.).

**These messages MUST be filtered out of the Trade Blotter / Shark Tank.**

### Recommended Frontend Logic (React):

```javascript
// inside your WebSocket message handler
const handleMessage = (newData) => {
  // Always update global metrics (Equity, PnL, Latency)
  updateMetrics(newData);

  // ONLY add to Trade Logs if it is NOT a heartbeat
  if (newData.action !== "HEARTBEAT") {
    setTradeLogs(prevLogs => [newData, ...prevLogs].slice(0, 50));
  }
};
```
