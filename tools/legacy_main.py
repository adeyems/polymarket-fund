import asyncio
import uvicorn
import signal
import sys
from api_bridge import app, broadcast_loop
from market_maker import run_bot
from shared_schemas import BotParams

# Global State placeholdes
# queue will be init in main
bot_state = BotParams() 

async def main():
    print("[SYSTEM] Initializing Monorepo Environment...")
    
    # 1. Init Queue in Loop
    queue = asyncio.Queue()
    
    # 2. Dependency Injection
    # Inject shared state into FastAPI app so endpoints can access it
    app.state.queue = queue
    app.state.bot_state = bot_state
    
    # 2. Server Configuration
    config = uvicorn.Config(app=app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    
    # 3. Concurrent Tasks
    # We run:
    # A. The API Server (Listens for HTTP/WS)
    # B. The Broadcast Loop (Pushes Queue -> WS)
    # C. The Trading Bot (The Core Engine)
    
    try:
        await asyncio.gather(
            server.serve(),
            broadcast_loop(queue),
            run_bot(queue, bot_state),
        )
    except asyncio.CancelledError:
        print("[SYSTEM] Tasks Cancelled.")
    except Exception as e:
        print(f"[SYSTEM] Critical Error: {e}")
    finally:
        print("[SYSTEM] Shutdown complete.")

if __name__ == "__main__":
    try:
        # Windows compatibility for some versions (not needed for Mac but good practice)
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
             
        asyncio.run(main())
    except KeyboardInterrupt:
        # This catch is often redundant with asyncio.run handling SIGINT, 
        # but ensures a clean printing on exit.
        print("\n[SYSTEM] KeyboardInterrupt received. Exiting...")
