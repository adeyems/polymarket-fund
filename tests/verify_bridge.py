import asyncio
import json
import websockets
import sys

async def verify_stream():
    uri = "ws://127.0.0.1:8002/api/v1/ws/stream"
    print(f"Connecting to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected! Waiting for data...")
            
            # Wait for 1 message
            message = await asyncio.wait_for(websocket.recv(), timeout=15.0)
            data = json.loads(message)
            
            print("Received Data Packet:")
            print(json.dumps(data, indent=2))
            
            # Validate Fields
            required = ["midpoint", "spread", "timestamp", "action"]
            if all(k in data for k in required):
                print("PASS: Schema Validation Successful.")
                sys.exit(0)
            else:
                print(f"FAIL: Missing fields. Got: {data.keys()}")
                sys.exit(1)
                
    except asyncio.TimeoutError:
        print("FAIL: Timeout waiting for data (15s). Bot might be sleeping or market closed.")
        sys.exit(1)
    except Exception as e:
        print(f"FAIL: Connection Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(verify_stream())
