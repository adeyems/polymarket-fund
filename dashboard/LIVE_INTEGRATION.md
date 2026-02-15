# QuesQuant HFT Backend - LIVE API Specification

> **For:** Frontend Agent (Production Environment)  
> **Host:** `100.50.168.104`  
> **Port:** `8002`  
> **Last Updated:** 2026-01-20

---

## 1. Connection Details (PRODUCTION)

| Property | Value |
|----------|-------|
| **Base URL** | `http://100.50.168.104:8002` |
| **WebSocket URL** | `ws://100.50.168.104:8002/api/v1/ws/stream` |
| **Protocol** | HTTP/1.1, WebSocket |
| **Content-Type** | `application/json` |

---

## 2. Authentication (CRITICAL)

The live server **strictly enforces** authentication for control endpoints.

| Endpoint Type | Auth Required | Header |
|---------------|---------------|--------|
| `GET /health` | ❌ No | - |
| `WS /api/v1/ws/stream` | ❌ No | - |
| `PATCH /api/v1/control/parameters` | ✅ Yes | `X-API-KEY` |
| `POST /api/v1/control/emergency-stop` | ✅ Yes | `X-API-KEY` |

### Security Implementation
- **Header Name:** `X-API-KEY`
- **Frontend Policy:** NEVER expose the API key in the browser. You must route all `PATCH` or `POST` requests through your Next.js server-side API routes.
- **WebSocket:** Currently public for read-only telemetry. If we enable secret-based handshakes later, this doc will be updated.

---

## 3. WebSocket Stream Schema

The schema remains identical to the local integration for dev/prod parity.

### Endpoint
```
ws://100.50.168.104:8002/api/v1/ws/stream
```

### High-Fidelity Simulation Metrics
During the 72-hour burn-in, note the following field behaviors:
- `virtual_pnl`: Includes synthetic leakage (fees/gas).
- `vol_state`: Reaches `"HIGH_VOL"` more frequently; UI should trigger "Panic Mode" (Red Borders) when active.

---

## 4. Production Environment Variables

Update your `.env.production` in the frontend repo:

```env
# Public (Production IP)
NEXT_PUBLIC_API_URL=http://100.50.168.104:8002
NEXT_PUBLIC_WS_URL=ws://100.50.168.104:8002

# Private (Copy from production .env - ask USER for secret)
DASHBOARD_API_KEY=YOUR_PRODUCTION_API_KEY
```

---

## 5. Deployment Checklist
1. [ ] **Firewall:** Ensure port `8002` is open on the EC2 Security Group (Security → Inbound Rules).
2. [ ] **Latency:** Monitor the `latency_ms` field. If > 300ms, investigate network path from frontend origin.
3. [ ] **Kill Switch:** Test the Emergency Stop from a secured admin dashboard using the `X-API-KEY`.
