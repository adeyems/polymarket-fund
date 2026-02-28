#!/usr/bin/env python3
"""
Secure Read-Only Dashboard Server
==================================
- Binds to 127.0.0.1 ONLY (never 0.0.0.0)
- Ephemeral auth token per startup
- Read-only: only reads JSON files, never writes to bot state
- Never imports web3 or touches private keys
- Completely decoupled from bot process
"""
import json
import secrets
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from dashboard.onchain import get_cached_state, start_onchain_fetcher, fetch_full_state

# ── Paths ───────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "sovereign_hive" / "data"
CACHE_DIR = DASHBOARD_DIR / "cache"
MONITOR_STATE = PROJECT_DIR / "tools" / "monitor_state.json"

# ── Auth ────────────────────────────────────────────────────────────────
AUTH_TOKEN = secrets.token_urlsafe(32)
SESSION_SECRET = secrets.token_urlsafe(32)
VALID_SESSIONS: set[str] = set()

# ── App ─────────────────────────────────────────────────────────────────
app = FastAPI(title="Sovereign Hive Dashboard", docs_url=None, redoc_url=None)


def safe_read_json(path: Path) -> Optional[dict]:
    """Read a JSON file safely. Returns None on any error."""
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, FileNotFoundError, PermissionError, OSError):
        return None


def to_num(value, default=0) -> float:
    """Coerce a value to float. Returns default for non-numeric strings."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return float(default)
    return float(default)


def is_authenticated(request: Request) -> bool:
    """Check if request has a valid session cookie."""
    session_id = request.cookies.get("sh_session")
    return session_id in VALID_SESSIONS


# ── Auth Endpoints ──────────────────────────────────────────────────────

@app.get("/auth")
async def auth(token: str = Query(...), response: Response = None):
    """Validate ephemeral token, set session cookie, redirect to dashboard."""
    if not secrets.compare_digest(token, AUTH_TOKEN):
        return JSONResponse({"error": "invalid token"}, status_code=401)
    session_id = secrets.token_urlsafe(32)
    VALID_SESSIONS.add(session_id)
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(
        key="sh_session",
        value=session_id,
        httponly=True,
        samesite="strict",
        secure=False,  # localhost doesn't use HTTPS
        max_age=86400,  # 24 hours
    )
    return resp


# ── Dashboard ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not is_authenticated(request):
        return HTMLResponse(
            "<h2 style='font-family:sans-serif;color:#c9d1d9;background:#0d1117;"
            "padding:40px;text-align:center'>Unauthorized. Use the token URL from terminal.</h2>",
            status_code=401,
        )
    return HTMLResponse((DASHBOARD_DIR / "static" / "index.html").read_text())


# ── Health (no auth) ────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


# ── On-Chain Verified Data ─────────────────────────────────────────────

@app.get("/api/onchain")
async def onchain_state(request: Request):
    """Real on-chain wallet state — queries Polygon RPC directly."""
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    state = get_cached_state()
    if not state:
        return JSONResponse({"error": "on-chain data not yet fetched, wait ~30s"}, status_code=503)
    return state


@app.get("/api/onchain/refresh")
async def onchain_refresh(request: Request):
    """Force an immediate on-chain refresh."""
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        state = fetch_full_state()
        return state
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Paper Trading Endpoints ─────────────────────────────────────────────

@app.get("/api/paper/summary")
async def paper_summary(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    portfolio = safe_read_json(DATA_DIR / "portfolio_sim.json")
    if not portfolio:
        return JSONResponse({"error": "no data"}, status_code=404)

    metrics = portfolio.get("metrics", {})
    strategy_metrics = portfolio.get("strategy_metrics", {})
    positions = portfolio.get("positions", {})

    # Count open positions
    open_count = len(positions) if isinstance(positions, dict) else 0
    total_trades = metrics.get("total_trades", 0)
    winning = metrics.get("winning_trades", 0)
    win_rate = (winning / total_trades * 100) if total_trades > 0 else 0

    strategies = {}
    for name, sm in strategy_metrics.items():
        s_trades = sm.get("trades", 0)
        s_wins = sm.get("wins", 0)
        strategies[name] = {
            "trades": s_trades,
            "wins": s_wins,
            "pnl": round(sm.get("pnl", 0), 2),
            "fees": round(sm.get("fees", 0), 2),
            "win_rate": round(s_wins / s_trades * 100, 1) if s_trades > 0 else 0,
        }

    return {
        "balance": round(portfolio.get("balance", 0), 2),
        "initial_balance": portfolio.get("initial_balance", 1000),
        "total_pnl": round(metrics.get("total_pnl", 0), 2),
        "roi_pct": round(
            metrics.get("total_pnl", 0) / portfolio.get("initial_balance", 1000) * 100, 1
        ),
        "open_positions": open_count,
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "max_drawdown": round(metrics.get("max_drawdown", 0) * 100, 1),
        "strategies": strategies,
        "last_updated": portfolio.get("last_updated", ""),
    }


@app.get("/api/paper/positions")
async def paper_positions(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    portfolio = safe_read_json(DATA_DIR / "portfolio_sim.json")
    if not portfolio:
        return JSONResponse({"error": "no data"}, status_code=404)

    positions = portfolio.get("positions", {})
    result = []

    if isinstance(positions, dict):
        for cid, pos in positions.items():
            result.append({
                "condition_id": cid,
                "question": pos.get("question", "Unknown")[:80],
                "strategy": pos.get("strategy", ""),
                "side": pos.get("side", ""),
                "entry_price": round(pos.get("entry_price", 0), 4),
                "shares": round(pos.get("shares", 0), 2),
                "cost_basis": round(pos.get("cost_basis", 0), 2),
                "entry_time": pos.get("entry_time", ""),
                "sector": pos.get("sector", ""),
            })

    return {"positions": result, "count": len(result)}


@app.get("/api/paper/trades")
async def paper_trades(request: Request, limit: int = Query(50, ge=1, le=500)):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    portfolio = safe_read_json(DATA_DIR / "portfolio_sim.json")
    if not portfolio:
        return JSONResponse({"error": "no data"}, status_code=404)

    trades = portfolio.get("trade_history", [])
    # Most recent first
    recent = sorted(trades, key=lambda t: t.get("exit_time", ""), reverse=True)[:limit]

    result = []
    for t in recent:
        result.append({
            "question": t.get("question", "Unknown")[:80],
            "strategy": t.get("strategy", ""),
            "side": t.get("side", ""),
            "entry_price": round(t.get("entry_price", 0), 4),
            "exit_price": round(t.get("exit_price", 0), 4),
            "shares": round(t.get("shares", 0), 2),
            "pnl": round(t.get("pnl", 0), 2),
            "pnl_pct": round(t.get("pnl_pct", 0), 1),
            "fees": round(t.get("entry_fee", 0) + t.get("exit_fee", 0), 4),
            "exit_reason": t.get("exit_reason", ""),
            "entry_time": t.get("entry_time", ""),
            "exit_time": t.get("exit_time", ""),
        })

    return {"trades": result, "count": len(result), "total": len(trades)}


# ── Live Trading Endpoints ──────────────────────────────────────────────

@app.get("/api/live/summary")
async def live_summary(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    ec2_data = safe_read_json(CACHE_DIR / "ec2_live.json")
    monitor = safe_read_json(MONITOR_STATE)

    if not monitor and not ec2_data:
        return JSONResponse({"error": "no live data"}, status_code=404)

    strategy = (monitor or {}).get("strategies", {}).get("MARKET_MAKER", {})
    paper_strats = (monitor or {}).get("paper_strategies", {})
    monitor_wallet = (monitor or {}).get("wallet_assets", {})

    # Wallet audit (monitor_state) is the single source of truth for totals.
    # total = on-chain USDC + on-chain conditional token value.
    # CLOB "locked" amounts are OFF-CHAIN intents — NOT real money.
    wallet = {
        "usdc": to_num(monitor_wallet.get("usdc", 0)),
        "shares_value": to_num(monitor_wallet.get("shares_value", 0)),
        "total": to_num(monitor_wallet.get("total", 0)),
        "pnl": to_num(monitor_wallet.get("pnl", 0)),
        "starting_balance": to_num(monitor_wallet.get("starting_balance", 20)),
        "pol": to_num(monitor_wallet.get("pol", 0)),
    }

    # Build open orders list from audit data
    tokens = []
    for order in monitor_wallet.get("open_orders", []):
        tokens.append({
            "market": order.get("market", "Unknown"),
            "outcome": order.get("side", "BUY"),
            "shares": to_num(order.get("size", 0)),
            "current_value": to_num(order.get("locked_usdc", 0)),
            "status": order.get("status", "LIVE"),
        })
    # Also include conditional tokens from audit
    for tok in monitor_wallet.get("tokens", []):
        tokens.append(tok)

    # Use ec2 portfolio for position details (market names) if available
    if ec2_data and ec2_data.get("portfolio"):
        p = ec2_data["portfolio"]
        positions = p.get("positions", {})
        metrics = p.get("metrics", {})
        total_trades = metrics.get("total_trades", 0)
        winning = metrics.get("winning_trades", 0)
        win_rate = round(winning / total_trades * 100, 1) if total_trades > 0 else 0

        # Enrich tokens with market names from portfolio positions
        if positions and not tokens:
            for cid, pos in positions.items():
                tokens.append({
                    "market": pos.get("question", "Unknown"),
                    "outcome": pos.get("side", ""),
                    "shares": round(to_num(pos.get("shares", 0)), 2),
                    "current_value": round(to_num(pos.get("cost_basis", 0)), 2),
                    "status": pos.get("live_state", "OPEN"),
                })

        strategy_status = {
            "status": strategy.get("status", "running"),
            "trades": total_trades,
            "win_rate": win_rate,
            "pnl": round(to_num(metrics.get("total_pnl", 0)), 2),
            "note": strategy.get("note", ""),
        }
    else:
        strategy_status = {
            "status": strategy.get("status", "unknown"),
            "trades": strategy.get("last_trades", 0),
            "win_rate": strategy.get("last_win_rate", 0),
            "pnl": strategy.get("last_pnl", 0),
            "note": strategy.get("note", ""),
        }

    # Deposit tracking from portfolio
    deposits = []
    total_deposited = wallet.get("starting_balance", 20)
    if ec2_data and ec2_data.get("portfolio"):
        p = ec2_data["portfolio"]
        deposits = p.get("deposits", [])
        total_deposited = p.get("initial_balance", 20) + sum(
            d.get("amount", 0) for d in deposits
        )

    # Fix ROI to use total capital deployed, not just initial
    true_roi = round(wallet.get("pnl", 0) / max(total_deposited, 1) * 100, 1)

    return {
        "source": "wallet_audit",
        "last_updated": monitor_wallet.get("last_audit", (monitor or {}).get("last_run", "")),
        "wallet": wallet,
        "tokens": tokens,
        "strategy_status": strategy_status,
        "warnings": (monitor or {}).get("active_warnings", []),
        "deposits": deposits,
        "total_deposited": round(total_deposited, 2),
        "true_roi_pct": true_roi,
        "paper_strategies": {
            name: {
                "status": s.get("status", ""),
                "balance": s.get("balance", 0),
                "pnl": s.get("pnl", 0),
                "win_rate": s.get("win_rate", 0),
                "trades": s.get("trades", 0),
                "open_positions": s.get("open_positions", 0),
            }
            for name, s in paper_strats.items()
        },
    }


# ── Live Positions & Trades ────────────────────────────────────────────

@app.get("/api/live/positions")
async def live_positions(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    ec2_data = safe_read_json(CACHE_DIR / "ec2_live.json")
    monitor = safe_read_json(MONITOR_STATE)

    if not ec2_data and not monitor:
        return JSONResponse({"error": "no live data"}, status_code=404)

    positions = []
    has_dead_orderbook = False
    # From EC2 portfolio (bot's view of positions with market names)
    if ec2_data and ec2_data.get("portfolio"):
        orderbook_health = ec2_data["portfolio"].get("_orderbook_health", {})
        for cid, pos in ec2_data["portfolio"].get("positions", {}).items():
            entry_price = pos.get("entry_price", 0)
            shares = pos.get("shares", 0)
            health_data = orderbook_health.get(cid, {})
            current_bid = health_data.get("best_bid", 0)
            current_ask = health_data.get("best_ask", 1)
            spread_pct = health_data.get("spread_pct", 100.0)
            unrealized_pnl = round((current_bid - entry_price) * shares, 2) if current_bid > 0 else 0

            # Health status based on spread
            if spread_pct > 50:
                health = "dead"
                has_dead_orderbook = True
            elif spread_pct > 20:
                health = "warning"
            else:
                health = "healthy"

            # Hold time
            hold_hours = 0
            entry_time = pos.get("entry_time") or pos.get("mm_entry_time", "")
            if entry_time:
                try:
                    entry_dt = datetime.fromisoformat(entry_time)
                    hold_hours = round((datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600, 1)
                except (ValueError, TypeError):
                    pass

            positions.append({
                "condition_id": cid,
                "question": pos.get("question", "Unknown")[:80],
                "strategy": pos.get("strategy", ""),
                "side": pos.get("side", ""),
                "entry_price": round(entry_price, 4),
                "shares": round(shares, 2),
                "cost_basis": round(pos.get("cost_basis", 0), 2),
                "entry_time": pos.get("entry_time", ""),
                "sector": pos.get("sector", ""),
                "live_state": pos.get("live_state", "OPEN"),
                "ai_score": pos.get("ai_score", 0),
                "current_bid": round(current_bid, 4),
                "current_ask": round(current_ask, 4),
                "spread_pct": round(spread_pct, 1),
                "unrealized_pnl": unrealized_pnl,
                "hold_hours": hold_hours,
                "health": health,
            })

    # Open CLOB orders from wallet audit
    open_orders = []
    if monitor:
        wallet = monitor.get("wallet_assets", {})
        for order in wallet.get("open_orders", []):
            open_orders.append({
                "market": order.get("market", "Unknown"),
                "side": order.get("side", "BUY"),
                "size": to_num(order.get("size", 0)),
                "price": to_num(order.get("price", 0)),
                "locked_usdc": to_num(order.get("locked_usdc", 0)),
                "status": order.get("status", "LIVE"),
                "matched": to_num(order.get("matched", 0)),
            })

    return {
        "positions": positions,
        "open_orders": open_orders,
        "count": len(positions),
        "orders_count": len(open_orders),
        "has_dead_orderbook": has_dead_orderbook,
    }


@app.get("/api/live/trades")
async def live_trades(request: Request, limit: int = Query(50, ge=1, le=500)):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    ec2_data = safe_read_json(CACHE_DIR / "ec2_live.json")
    if not ec2_data or not ec2_data.get("portfolio"):
        return JSONResponse({"error": "no live trade data"}, status_code=404)

    trades = ec2_data["portfolio"].get("trade_history", [])
    recent = sorted(trades, key=lambda t: t.get("exit_time", ""), reverse=True)[:limit]

    result = []
    for t in recent:
        result.append({
            "question": t.get("question", "Unknown")[:80],
            "strategy": t.get("strategy", ""),
            "side": t.get("side", ""),
            "entry_price": round(t.get("entry_price", 0), 4),
            "exit_price": round(t.get("exit_price", 0), 4),
            "shares": round(t.get("shares", 0), 2),
            "pnl": round(t.get("pnl", 0), 2),
            "pnl_pct": round(t.get("pnl_pct", 0), 1),
            "fees": round(t.get("entry_fee", 0) + t.get("exit_fee", 0), 4),
            "exit_reason": t.get("exit_reason", ""),
            "entry_time": t.get("entry_time", ""),
            "exit_time": t.get("exit_time", ""),
        })

    return {"trades": result, "count": len(result), "total": len(trades)}


# ── Main ────────────────────────────────────────────────────────────────

def main():
    import uvicorn

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Start EC2 fetcher in background (for portfolio positions data)
    from dashboard.ec2_fetcher import start_fetcher
    start_fetcher(CACHE_DIR, PROJECT_DIR)

    # Start on-chain verifier (queries Polygon RPC directly, no EC2 needed)
    start_onchain_fetcher()

    url = f"http://127.0.0.1:8050/auth?token={AUTH_TOKEN}"
    print("=" * 60)
    print("  Sovereign Hive Dashboard")
    print("=" * 60)
    print(f"  URL: {url}")
    print("  Security: localhost-only, ephemeral auth")
    print("  Mode: READ-ONLY (no bot control)")
    print("=" * 60)

    # Open browser after short delay
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    # SECURITY: host MUST be 127.0.0.1, NEVER 0.0.0.0
    uvicorn.run(app, host="127.0.0.1", port=8050, log_level="warning")


if __name__ == "__main__":
    main()
