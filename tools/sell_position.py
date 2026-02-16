#!/usr/bin/env python3
import os
import sys
import time
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, BalanceAllowanceParams, AssetType, OrderType
from py_clob_client.constants import POLYGON
from curl_cffi import requests as cffi_requests
import py_clob_client.http_helpers.helpers as _clob_helpers

# --- CONFIG ---
load_dotenv(".env")
load_dotenv("/app/hft/.env")

MAKER_ADDRESS = "0xb22028EA4E841CA321eb917C706C931a94b564AB"
TARGET_TOKEN = "65596524896985010415844814777069255362767748488616308434723608750130614059462"
PROXY_URL = os.getenv("PROXY_URL", "")
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}

# --- PROXY PATCH ---
session = cffi_requests.Session(impersonate="chrome110", proxies=SYS_PROXIES)
session.headers = {"Referer": "https://polymarket.com/", "Origin": "https://polymarket.com"}
def patched_request(endpoint, method, headers=None, data=None, **kwargs):
    final_headers = {"Referer": "https://polymarket.com/", "Origin": "https://polymarket.com"}
    if headers: final_headers.update(headers)
    if method == "GET": resp = session.get(endpoint, headers=final_headers)
    elif method == "POST": resp = session.post(endpoint, headers=final_headers, json=data)
    elif method == "DELETE": resp = session.delete(endpoint, headers=final_headers)
    else: return {}
    return resp.json()
_clob_helpers.request = patched_request

def main():
    print("🚀 SMART LIQUIDATOR ACTIVATED")
    
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    creds = ApiCreds(api_key=os.getenv("CLOB_API_KEY"), api_secret=os.getenv("CLOB_SECRET"), api_passphrase=os.getenv("CLOB_PASSPHRASE"))
    client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=POLYGON, creds=creds, signature_type=0, funder=MAKER_ADDRESS)

    # 1. STOP BOT (Check)
    # Assumed stopped via systemctl command

    # 2. CHECK & LOOP
    for i in range(3): # Try 3 times
        try:
            bal_resp = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=TARGET_TOKEN))
            raw_balance = float(bal_resp.get('balance', '0'))
            shares = raw_balance / (10 ** 6)
            print(f"[Attempt {i+1}] Current Position: {shares} shares")
            
            if shares < 1.0:
                print("✅ Position successfully closed.")
                sys.exit(0)
            
            # Fetch Book
            book = client.get_order_book(TARGET_TOKEN)
            if not book.bids:
                print("❌ No Bids available to sell into!")
                sys.exit(1)
                
            best_bid = float(book.bids[0].price)
            sell_price = round(best_bid - 0.01, 2) # Cross by 1 cent
            
            # Safety checks
            if sell_price < 0.05: sell_price = 0.05 
            
            print(f"      Best Bid: {best_bid} | Executing Sell @ {sell_price}")
            
            order_args = OrderArgs(
                price=sell_price,
                size=raw_balance,
                side="SELL",
                token_id=TARGET_TOKEN
            )
            signed_order = client.create_order(order_args)
            resp = client.post_order(signed_order, OrderType.GTC)
            print(f"      ✅ ORDER PLACED: {resp.get('orderID')}")
            
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(1)

    print("⚠️  Liquidation process finished (Verify outcome).")

if __name__ == "__main__":
    main()
