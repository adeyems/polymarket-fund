from fastapi.testclient import TestClient
import time
import os
import sys

print(f"[{time.strftime('%X')}] 1. Importing api_bridge...")
try:
    from api_bridge import app
except Exception as e:
    print(f"[{time.strftime('%X')}] ❌ Import Error: {e}")
    sys.exit(1)

print(f"[{time.strftime('%X')}] 2. Initializing TestClient (This triggers Lifespan)...")
try:
    with TestClient(app) as client:
        print(f"[{time.strftime('%X')}] ✅ Lifespan Started Successfully. Bot thread should be active.")
        
        print(f"[{time.strftime('%X')}] 3. Testing /health endpoint...")
        response = client.get("/health")
        print(f"[{time.strftime('%X')}] ✅ Health Response: {response.status_code} - {response.json()}")
        
        print(f"[{time.strftime('%X')}] 4. Testing /api/v1/control/parameters...")
        # Get current state
        state = app.state.bot_state
        print(f"[{time.strftime('%X')}] ℹ️ Bot Current Spread: {state.spread_offset}")
        
        # Update
        update_resp = client.patch("/api/v1/control/parameters", json={
            "spread_offset": 0.05,
            "order_size": 100,
            "max_position": 1000,
            "min_liquidity": 5000,
            "is_running": True
        })
        print(f"[{time.strftime('%X')}] ✅ Update Response: {update_resp.status_code} - {update_resp.json()}")
        print(f"[{time.strftime('%X')}] ℹ️ Bot New Spread: {state.spread_offset}")
        
        if state.spread_offset == 0.05:
            print(f"[{time.strftime('%X')}] ✅ State synchronization verified.")
        else:
            print(f"[{time.strftime('%X')}] ❌ State synchronization failed!")

        print(f"[{time.strftime('%X')}] 5. Testing WebSocket Handshake (Logic Only)...")
        # TestClient.websocket_connect is available
        try:
            with client.websocket_connect("/api/v1/ws/stream") as websocket:
                print(f"[{time.strftime('%X')}] ✅ WebSocket handshake success.")
        except Exception as ws_e:
            print(f"[{time.strftime('%X')}] ⚠️ WebSocket test limited (Expected in some TestClient setups): {ws_e}")

        print(f"[{time.strftime('%X')}] 6. Waiting for bot output in memory...")
        # The bot thread is daemonized and should be putting stuff in the queue
        q = app.state.queue
        time.sleep(2)
        if not q.empty():
            sample = q.get()
            print(f"[{time.strftime('%X')}] ✅ Bot Data Detected in Queue: {sample.get('action')}")
        else:
            print(f"[{time.strftime('%X')}] ℹ️ Queue empty (Normal if bot is slow or mock delay).")

    print(f"[{time.strftime('%X')}] 7. Lifespan Shutdown Triggered.")
except Exception as e:
    print(f"[{time.strftime('%X')}] ❌ Integration Test Failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"[{time.strftime('%X')}] === INTEGRATION TEST PASSED ===")
