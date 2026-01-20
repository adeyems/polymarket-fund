import uvicorn
import api_bridge
import os
import sys

if __name__ == "__main__":
    print(f"[RUNNER] Starting Uvicorn for api_bridge:app (PID: {os.getpid()})")
    try:
        uvicorn.run(
            "api_bridge:app", 
            host="127.0.0.1", 
            port=8002, 
            log_level="info", 
            reload=False
        )
    except Exception as e:
        print(f"[RUNNER] CRITICAL ERROR: {e}")
        sys.exit(1)
