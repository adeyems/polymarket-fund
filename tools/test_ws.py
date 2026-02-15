import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://localhost:8000/api/v1/ws/stream"
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Connected to {uri}")
            while True:
                msg = await websocket.recv()
                data = json.loads(msg)
                print(f"Received: Equity=${data.get('total_equity')} | PnL=${data.get('virtual_pnl')}")
                break # Just need one message to verify
    except Exception as e:
        print(f"WS Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
