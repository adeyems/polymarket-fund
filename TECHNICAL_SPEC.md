# QuesQuant HFT Technical Specification

**Date:** 2026-01-19  
**Version:** 1.0  
**Status:** Production Ready (Environment: Local/Mac)

---

## 1. System Architecture

The system follows a **Producer-Consumer** architecture designed for low-latency market making. It decouples the blocking trading logic from the high-throughput API layer using thread isolation and async queues.

### High-Level Diagram
```mermaid
graph TD
    subgraph "Core Logic (Daemon Thread)"
        MM[Market Maker Loop] -->|Fetches Data| CLOB[Polymarket CLOB]
        MM -->|Checks| BIN[Binance Price Feed]
        MM -->|Calculates| STRAT[Strategy Engine]
        STRAT -->|Executes| ORDERS[Order Management]
    end

    subgraph "Data Bridge (FastAPI)"
        Q[Async Queue (Thread-Safe)]
        WS[WebSocket Manager]
        API[REST Control API]
        
        MM -->|Push Updates| Q
        Q -->|Pop & Broadcast| WS
        API -->|Update Params / Kill| MM
    end

    subgraph "Frontend (Next.js)"
        DASH[Dashboard UI] <-->|WS Stream| WS
        DASH -->|Commands (Secure)| API
    end
```

---

## 2. Core Components

### A. The Trading Engine (`market_maker.py`)
Running in a dedicated **Daemon Thread**, this component is the "brain" of the operation. It runs an infinite loop that never blocks the API server.

1.  **Market Discovery**: Scans Polymarket for active `Crypto` binary markets (Bitcoin, Ethereum, Solana).
2.  **Signal Correlation**: Fetches real-time spot prices from **Binance** (e.g., BTCUSDT) to calculate the "Fair Value" of the binary option.
    *   *Logic*: If Spot Price > Strike Price, the "Yes" share should approach $1.00.
    *   *Divergence Check*: If Polymarket price deviates > 0.8% from theoretical fair value, it inhibits trading on that side.
3.  **Volatility Guard**: Tracks price standard deviation over a sliding window. If volatility spikes (`stdev > 0.01`), it automatically widens spreads to protect capital.
4.  **Inventory Management**: Enforces a `max_position` limit (default: 50 contracts) to prevent over-exposure.
5.  **Execution**:
    *   Calculates `Bid = Midpoint - Spread` / `Ask = Midpoint + Spread`.
    *   Submits orders via `py-clob-client`.
6.  **Telemetry**: Pushes a rich JSON snapshot (`TradeData`) to the `queue` on every tick.

### B. The API Bridge (`api_bridge.py`)
This is the interface layer powered by **FastAPI** and **Hypercorn**.

1.  **Thread Isolation**: Launches the `market_maker` in a separate background thread (`daemon=True`) so that `Ctrl+C` or API requests are never blocked by network lag in the bot.
2.  **WebSocket Broadcast**: A dedicated asyncio task (`broadcast_loop`) polls the shared queue and pushes updates to all connected frontend clients.
3.  **Security Middleware**: Validates a server-side `X-API-KEY` for all control actions.
4.  **Control Endpoints**:
    *   `PATCH /parameters`: Updates the running bot's variables (spread, size, pause/resume) in real-time **without restarting**.
    *   `POST /emergency-stop`: Immediately halts the loop and triggers a `cancel_all` signal.

---

## 3. Security Model

1.  **API Key Authentication**:
    *   The backend enforces `X-API-KEY` on all state-changing endpoints.
    *   Key: `DASHBOARD_API_KEY` (Stored in `.env`, never exposed to browser context).
2.  **Frontend Proxy**:
    *   The Next.js frontend uses **Server-Side API Routes** to proxy requests. The browser sends a request to Next.js, and Next.js attaches the secret key before calling the Python backend. This ensures the key never leaks to the client side.
3.  **Environment Isolation**:
    *   Bot credentials (`POLYMARKET_PRIVATE_KEY`) are loaded only within the daemon thread and are never accessible via the API.

---

## 4. Operational Status

- **Server**: Running on `Hypercorn` (Port 8002) to bypass MacOS LibreSSL deadlocks.
- **Latency**: Internal processing latency is tracked and broadcasted (target < 500ms).
- **Safety**:
    *   **Kill Switch**: Verified working.
    *   **Startup**: Verified reliable using Hypercorn.
    *   **Shutdown**: Gracefully cancels tasks and kills the daemon thread.

---

## 5. Directory Structure ("The Vault")

```text
polymarket-fund/
├── .agent/                 # Agent logs, scratchpads (HIDDEN)
│   ├── logs/
│   └── scratchpads/
├── infra/                  # Terraform Infrastructure
│   ├── modules/            # Reusable VPC, SG components
│   └── live/prod/          # Production environment
├── core/                   # Python Trading Engine
│   ├── market_maker.py
│   └── shared_schemas.py
├── dashboard/              # FastAPI + React
│   └── api_bridge.py
├── tools/                  # Deployment scripts
├── .env                    # Local secrets (prod uses AWS Secrets Manager)
└── launcher.py             # Startup script
```
