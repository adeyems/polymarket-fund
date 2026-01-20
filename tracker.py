import json
import os
import sys
import requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import ApiCreds

load_dotenv()

def run_tracker():
    file_path = "paper_trades.json"
    if not os.path.exists(file_path):
        print("No paper trades file found.")
        return

    try:
        with open(file_path, "r") as f:
            trades = json.load(f)
    except Exception as e:
        print(f"Error reading trades file: {e}")
        return

    if not trades:
        print("No trades to track.")
        return

    # Initialize Client for fetching current prices
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    api_key = os.getenv("CLOB_API_KEY")
    api_secret = os.getenv("CLOB_SECRET")
    api_passphrase = os.getenv("CLOB_PASSPHRASE")
    
    # We need to manually construct the creds object
    from py_clob_client.clob_types import ApiCreds
    creds_obj = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
    
    try:
        client = ClobClient(
            host="https://clob.polymarket.com",
            key=pk,
            chain_id=POLYGON,
            creds=creds_obj
        )
    except Exception as e:
        print(f"Error initializing Client: {e}")
        return

    print(f"\nAnalyzing {len(trades)} Paper Trades...")
    print("-" * 60)

    for i, trade in enumerate(trades):
        token_id = trade.get("token_id")
        entry_price = trade.get("price")
        side = trade.get("side")
        size = trade.get("size")
        
        try:
            order_book = client.get_order_book(token_id)
            
            # For a BUY trade to be profitable (closed), we need to SELL it.
            # Convert Entry Buy -> Exit Sell (use Best Bid from market perspective?)
            # Wait:
            # If we BOUGHT at EntryPrice, we are Long. To close, we SELL at Current Best Bid.
            # If we SOLD at EntryPrice, we are Short. To close, we BUY at Current Best Ask.
            
            current_bids = order_book.bids
            current_asks = order_book.asks
            
            best_bid = float(current_bids[0].price) if current_bids else 0
            best_ask = float(current_asks[0].price) if current_asks else 1
            
            pnl = 0
            current_market_price = 0
            
            if side == "BUY":
                # We own the token. Sell into the Bid.
                current_market_price = best_bid
                pnl = (current_market_price - entry_price) * size
            elif side == "SELL":
                # We are short. Buy back from the Ask.
                current_market_price = best_ask
                pnl = (entry_price - current_market_price) * size
                
            status = "PROFITABLE" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
            
            print(f"Trade #{i+1}: {side} {trade['market_question'][:30]}...")
            print(f"  Entry: {entry_price:.2f} | Current Market Exit: {current_market_price:.2f}")
            print(f"  PnL: ${pnl:.2f} [{status}]")
            print("-" * 60)
            
        except Exception as e:
            print(f"Error analyzing trade {i+1}: {e}")

if __name__ == "__main__":
    run_tracker()
