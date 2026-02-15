import os
import time
import json
import requests
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from dotenv import load_dotenv

# Try loading from production path first
load_dotenv("/app/hft/.env")
# Fallback to local if needed
if not os.getenv("POLYMARKET_API_KEY"):
    load_dotenv()

# Constants
HOST = "https://clob.polymarket.com"
PK = "0xfe6397d5ae3bae43522f791a0fa0c0dc5fb8e0b9cfa541e858cbc608e5cc2033"
CLOB_KEY = "b876b8be-9f64-e69f-2ef3-d3f4a1441f6e"
SECRET = "XQ2eo3XOCYTydDUFSEy1toEg6ph8gaABx-RQBt4-F5w="
PASSPHRASE = "1b08229607ddaa4079b480efa07aa3ddc632e40b5c98f420587f31fd5b6633bc"

def main():
    # 1. Fetch Candidates from Gamma (using requests like before)
    print("Fetching Top Candidates from Gamma...")
    slug = "what-price-will-bitcoin-hit-in-january-2026"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    r = requests.get(url)
    try:
        data = r.json()
        if not data:
            print("No Data")
            return
        event = data[0]
        markets = event.get('markets', [])
    except Exception as e:
        print(f"API Error: {e}")
        return
    
    # Sort by Vol
    markets.sort(key=lambda x: float(x.get('volume', 0)), reverse=True)
    top_5 = markets[:5] # Check top 5

    # 2. Check via CLOB Client
    print("\nAuditing CLOB Connectivity & Order Books...")
    from py_clob_client.clob_types import ApiCreds
    creds = ApiCreds(api_key=CLOB_KEY, api_secret=SECRET, api_passphrase=PASSPHRASE)
    client = ClobClient(HOST, key=PK, chain_id=137, creds=creds)

    print(f"{'QUESTION':<40} | {'BID':<5} | {'ASK':<5} | {'SPREAD':<6} | {'ID'}")
    print("-" * 100)

    for m in top_5:
        q = m.get('question')
        try:
            clob_ids = json.loads(m.get('clobTokenIds', '[]'))
            if not clob_ids: continue
            token_id = clob_ids[0]
            
            book = client.get_order_book(token_id)
            
            best_bid = float(book.bids[0].price) if book.bids else 0.0
            best_ask = float(book.asks[0].price) if book.asks else 1.0
            spread = best_ask - best_bid
            
            print(f"{q:<40} | {best_bid:<5.2f} | {best_ask:<5.2f} | {spread:<6.2f} | {token_id}")
        except Exception as e:
            print(f"{q:<40} | ERROR: {e}")

if __name__ == "__main__":
    main()
