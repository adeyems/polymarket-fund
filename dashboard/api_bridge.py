# ═══════════════════════════════════════════════════════════════════════
# DEPRECATED (2026-02-25): This file is INSECURE and must NOT be deployed.
#
# Security issues:
#   - Binds to 0.0.0.0 (exposed to internet)
#   - CORS allows all origins (*)
#   - Unauthenticated WebSocket
#   - Bot process coupled to API server
#   - Led to EIP-7702 wallet drain (~$70 lost)
#
# Use dashboard/server.py instead (localhost-only, auth, read-only).
# ═══════════════════════════════════════════════════════════════════════
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio
import json
import os
import time
import threading
import secrets
import queue as sync_queue
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

from core.shared_schemas import TradeData, BotParams, KillSwitchRequest
from pathlib import Path
import sys

# Add sovereign_hive to path for backtest imports
sys.path.insert(0, str(Path(__file__).parent.parent / "sovereign_hive"))

# Mock or real client reference for shutdown
# In a real scenario, we'd want this handed back from the bot thread
clob_client_global = None

# Shared State
queue = None
bot_state = None

# --- SECURITY MIDDLEWARE ---
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY")

async def verify_api_key(x_api_key: str = Header(None)):
    if not DASHBOARD_API_KEY:
        # Fallback if key missing in .env (should not happen in production)
        raise HTTPException(status_code=500, detail="Security key not configured on server")
    
    if not x_api_key or not secrets.compare_digest(x_api_key, DASHBOARD_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid or missing X-API-KEY")
    return x_api_key

@asynccontextmanager
async def lifespan(app: FastAPI):
    global queue, bot_state
    
    print("[API] Starting API Bridge...")
    queue = sync_queue.Queue()
    bot_state = BotParams()
    app.state.queue = queue
    app.state.bot_state = bot_state
    
    broadcast_task = asyncio.create_task(broadcast_loop(queue))
    
    # Store thread/loop references for cleanup
    bot_loop = None
    
    def bot_thread_target(q, state):
        nonlocal bot_loop
        print(f"[THREAD] Bot Thread Started (PID: {os.getpid()})")
        try:
            from core.market_maker import run_bot
            bot_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(bot_loop)
            bot_loop.run_until_complete(run_bot(q, state))
        except Exception as e:
            print(f"[THREAD] Bot CRASHED: {e}")
        finally:
            print("[THREAD] Bot Thread Exited.")

    t = threading.Thread(target=bot_thread_target, args=(queue, bot_state), daemon=True)
    t.start()
    
    yield
    
    # Shutdown logic
    print("[API] Shutting down...")
    bot_state.is_running = False
    
    # Give the bot loop a chance to process the shutdown
    if bot_loop:
        for task in asyncio.all_tasks(bot_loop):
            task.cancel()
        bot_loop.stop()
    
    broadcast_task.cancel()
    print("[API] Graceful shutdown complete.")

app = FastAPI(title="Polymarket Bot Bridge", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (dashboard UI)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def serve_dashboard():
    """Serve the dashboard UI."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Dashboard not found. Visit /docs for API documentation."}

# --- WEBSOCKET MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[API] New Client Connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print(f"[API] Client Disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        json_msg = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(json_msg)
            except Exception as e:
                pass

manager = ConnectionManager()

# --- BACKGROUND BROADCASTER ---
async def broadcast_loop(queue: sync_queue.Queue):
    print("[API] Broadcast Loop Started")
    while True:
        try:
            if not queue.empty():
                try:
                    data = queue.get_nowait()
                    await manager.broadcast(data)
                    queue.task_done()
                except:
                    pass
            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            break
        except Exception as e:
            await asyncio.sleep(0.1)

# --- ENDPOINTS ---

@app.websocket("/api/v1/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    # Public WebSocket for streaming data
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() 
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.patch("/api/v1/control/parameters", dependencies=[Depends(verify_api_key)])
async def update_parameters(params: BotParams):
    """
    Update live bot parameters. Locked by API Key.
    """
    bot_state: BotParams = app.state.bot_state
    
    bot_state.spread_offset = params.spread_offset
    bot_state.order_size = params.order_size
    bot_state.max_position = params.max_position
    bot_state.min_liquidity = params.min_liquidity
    bot_state.is_running = params.is_running
    
    print(f"[API] Parameters Updated (SECURE): {params}")
    return {"status": "updated", "current_state": bot_state}

@app.post("/api/v1/control/emergency-stop", dependencies=[Depends(verify_api_key)])
async def emergency_stop(req: KillSwitchRequest):
    """
    Global Kill Switch. Locked by API Key.
    """
    bot_state: BotParams = app.state.bot_state
    bot_state.is_running = False
    
    print(f"[API] EMERGENCY STOP TRIGGERED SECURELY: {req.reason}")
    
    return {"status": "EMERGENCY_STOP_ACTIVATED", "reason": req.reason}

@app.get("/health")
async def health_check():
    # Public Health Check
    return {"status": "ok", "connections": len(manager.active_connections)}

# --- BACKTEST ENDPOINTS ---

@app.get("/api/v1/backtest/strategies")
async def get_available_strategies():
    """Get list of available backtest strategies."""
    try:
        from backtest.engine import BUILTIN_STRATEGIES
        return {
            "strategies": list(BUILTIN_STRATEGIES.keys()),
            "recommended": "MEAN_REVERSION",
            "disabled": ["DIP_BUY"]  # Underperforming strategies
        }
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Backtest module not available: {e}")

@app.get("/api/v1/backtest/optimized-config")
async def get_optimized_config():
    """Get the optimized strategy configuration from backtesting."""
    config_path = Path(__file__).parent.parent / "sovereign_hive" / "config" / "optimized_strategies.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {
        "error": "No optimized config found",
        "default_config": {
            "max_position_pct": 0.15,
            "take_profit_pct": 0.10,
            "stop_loss_pct": -0.05,
            "kelly_fraction": 0.15
        }
    }

@app.post("/api/v1/backtest/run")
async def run_backtest(
    strategy: str = "MEAN_REVERSION",
    days: int = 30,
    markets: int = 30,
    capital: float = 10000
):
    """
    Run a quick backtest with synthetic data.
    For live API data backtests, use the CLI tool.
    """
    try:
        from backtest.data_loader import DataLoader
        from backtest.engine import BacktestEngine, BacktestConfig, BUILTIN_STRATEGIES

        if strategy not in BUILTIN_STRATEGIES:
            raise HTTPException(status_code=400, detail=f"Unknown strategy: {strategy}")

        # Load synthetic data (fast)
        loader = DataLoader()
        loader.generate_synthetic(num_markets=markets, days=days, interval_hours=1)

        # Configure with optimized parameters
        config = BacktestConfig(
            initial_capital=capital,
            use_kelly=True,
            kelly_fraction=0.15,
            max_position_pct=0.15,
            take_profit_pct=0.10,
            stop_loss_pct=-0.05
        )

        # Run backtest
        engine = BacktestEngine(loader, config)
        engine.add_strategy(strategy, BUILTIN_STRATEGIES[strategy])
        results = engine.run()

        metrics = results[strategy]

        return {
            "strategy": strategy,
            "config": {
                "days": days,
                "markets": markets,
                "capital": capital
            },
            "results": metrics.to_dict(),
            "equity_curve": [
                {"timestamp": p.timestamp.isoformat(), "equity": p.equity}
                for p in metrics.equity_curve[::max(1, len(metrics.equity_curve)//100)]  # Sample 100 points
            ]
        }
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Backtest module error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest failed: {e}")

@app.get("/api/v1/backtest/monte-carlo/{strategy}")
async def run_monte_carlo(
    strategy: str,
    simulations: int = 500,
    days: int = 30,
    markets: int = 30
):
    """
    Run Monte Carlo simulation for risk estimation.
    """
    try:
        from backtest.data_loader import DataLoader
        from backtest.engine import BacktestEngine, BacktestConfig, BUILTIN_STRATEGIES
        from backtest.monte_carlo import run_monte_carlo_from_metrics

        if strategy not in BUILTIN_STRATEGIES:
            raise HTTPException(status_code=400, detail=f"Unknown strategy: {strategy}")

        # Run backtest first
        loader = DataLoader()
        loader.generate_synthetic(num_markets=markets, days=days, interval_hours=1)

        config = BacktestConfig(
            initial_capital=10000,
            use_kelly=True,
            kelly_fraction=0.15,
            max_position_pct=0.15,
            take_profit_pct=0.10,
            stop_loss_pct=-0.05
        )

        engine = BacktestEngine(loader, config)
        engine.add_strategy(strategy, BUILTIN_STRATEGIES[strategy])
        results = engine.run()
        metrics = results[strategy]

        # Run Monte Carlo
        mc_result = run_monte_carlo_from_metrics(metrics, simulations, seed=42)

        return {
            "strategy": strategy,
            "simulations": simulations,
            "mean_return_pct": mc_result.mean_return_pct,
            "median_return_pct": mc_result.median_return_pct,
            "ci_95": [mc_result.ci_95_lower, mc_result.ci_95_upper],
            "prob_positive": mc_result.prob_positive_return,
            "var_95": mc_result.var_95,
            "var_99": mc_result.var_99,
            "mean_max_drawdown": mc_result.mean_max_drawdown,
            "return_distribution": mc_result.all_returns[::max(1, len(mc_result.all_returns)//50)]  # Sample 50 points
        }
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Monte Carlo module error: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Monte Carlo failed: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    # Final cleanup before process exit
    print("[TERMINAL] Triggering final bot shutdown and order cancellation...")
    # NOTE: In a production environment with a live client, 
    # we would call client.cancel_all() here.
    # Since the bot loop checks bot_state.is_running, it will stop its next tick.

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
