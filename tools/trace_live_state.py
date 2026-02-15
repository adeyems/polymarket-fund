import asyncio
import os
import json
import time
from datetime import datetime
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
import websockets

# Load Environment from where the bot runs
load_dotenv("/app/hft/.env")

TOKEN_ID = "101676997363687199724245607342877036148401850938023978421879460310389391082353"
BINANCE_URL = "wss://stream.binance.us:9443/ws/btcusdt@aggTrade/ethusdt@aggTrade/solusdt@aggTrade/maticusdt@aggTrade"

async def check_binance():
    print(f"\n[1] CHECKING EXTERNAL FEED (Binance US)...")
    print(f"Connecting to {BINANCE_URL}...")
    try:
        async with websockets.connect(BINANCE_URL) as ws:
            print("Connected! Listening for 5 seconds...")
            start = time.time()
            count = 0
            while time.time() - start < 5:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(msg)
                    print(f" -> Ticker: {data.get('s')} | Price: {data.get('p')}")
                    count += 1
                except asyncio.TimeoutError:
                    continue
            if count == 0:
                print(" -> [WARNING] No ticks received! Feed might be silent.")
            else:
                print(f" -> Received {count} ticks. Feed is ALIVE.")
    except Exception as e:
        print(f" -> [ERROR] Binance Connection Failed: {e}")

async def check_polymarket():
    print(f"\n[2] CHECKING POLYMARKET CONNECTION...")
    
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    api_key = os.getenv("CLOB_API_KEY")
    api_secret = os.getenv("CLOB_SECRET")
    api_passphrase = os.getenv("CLOB_PASSPHRASE")
    
    creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
    client = ClobClient("https://clob.polymarket.com", key=pk, chain_id=137, creds=creds)
    
    print(f"Fetching Order Book for Token: {TOKEN_ID[:20]}...")
    try:
        book = client.get_order_book(TOKEN_ID)
        print(f" -> Bids: {book.bids[:3]}")
        print(f" -> Asks: {book.asks[:3]}")
        
        if book.bids and book.asks:
            best_bid = float(book.bids[0].price)
            best_ask = float(book.asks[0].price)
            mid = (best_bid + best_ask) / 2
            print(f" -> Calculated Internal Mid: {mid:.4f}")
            
            if mid == 0.500:
                print(" -> [CRITICAL] Market is indeed FLAT at 0.500.")
            else:
                print(f" -> [DISCREPANCY] Market is active! Dashboard is stale.")
        else:
            print(" -> [ERROR] Order Book is empty!")
            
    except Exception as e:
        print(f" -> [ERROR] Polymarket Fetch Failed: {e}")

async def main():
    print("=== LIVE SYSTEM INVESTIGATION TRACE ===")
    await check_binance()
    await check_polymarket()
    print("\n=== TRACE COMPLETE ===")

if __name__ == "__main__":
    asyncio.run(main())
