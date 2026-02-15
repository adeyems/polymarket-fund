import asyncio
import websockets
import json
import sys

async def test_ws():
    uri = "ws://localhost:8002/api/v1/ws/stream"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Connected!")
            while True:
                msg = await websocket.recv()
                data = json.loads(msg)
                print(f"Received: Equity=${data.get('total_equity')} | PnL=${data.get('virtual_pnl')}")
                break
    except Exception as e:
        print(f"WS Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
