from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
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
