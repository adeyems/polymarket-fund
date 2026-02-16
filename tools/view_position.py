#!/usr/bin/env python3
import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv

# Try to load local .env if available, otherwise rely on env vars
load_dotenv(".env")
load_dotenv("/app/hft/.env") # Fallback for server path

# ---------------- CONFIGURATION ----------------
PROXY_URL = os.getenv("PROXY_URL", "")
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}

# EOA Address (Hardcoded for certainty as per user request)
MAKER_ADDRESS = "0xb22028EA4E841CA321eb917C706C931a94b564AB"

# RPC for Balance Check (USDC.e on Polygon)
RPC_URL = "https://1rpc.io/matic"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

# ---------------- IMPORTS ----------------
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
    from py_clob_client.constants import POLYGON
    from curl_cffi import requests as cffi_requests
    from web3 import Web3
except ImportError:
    print("Missing dependencies! Run: pip install py-clob-client curl-cffi web3 python-dotenv")
    sys.exit(1)

# ---------------- MONKEY PATCH ----------------
# Patch py_clob_client to use curl_cffi with Mexico Proxy
import py_clob_client.http_helpers.helpers as _clob_helpers
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

# ---------------- MAIN ----------------
def main():
    print(f"\n======== POLYMARKET EOA COMPREHENSIVE AUDIT ========")
    print(f"Address: {MAKER_ADDRESS}")
    
    # 1. CHAIN BALANCES
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        if w3.is_connected():
            matic_bal = w3.from_wei(w3.eth.get_balance(MAKER_ADDRESS), 'ether')
            # USDC.e
            abi = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"}]
            ct = w3.eth.contract(address=USDC_ADDRESS, abi=abi)
            usdc_raw = ct.functions.balanceOf(MAKER_ADDRESS).call()
            usdc_dec = ct.functions.decimals().call()
            usdc_bal = usdc_raw / (10 ** usdc_dec)
            print(f"\n[WALLET BALANCES]")
            print(f" - USDC.e: ${usdc_bal:.2f}")
            print(f" - MATIC : {matic_bal:.4f}")

            # Native USDC
            native_ct = w3.eth.contract(address=Web3.to_checksum_address(NATIVE_USDC), abi=abi)
            native_bal = native_ct.functions.balanceOf(MAKER_ADDRESS).call() / (10**6)
            print(f" - Native USDC: ${native_bal:.2f}")
        else:
            print(f"\n[RPC ERROR] Could not connect to {RPC_URL}")
    except Exception as e:
        print(f"\n[CHAIN ERROR] {e}")

    # 2. CLOB DATA
    try:
        pk = os.getenv("POLYMARKET_PRIVATE_KEY")
        if not pk:
            print("\n[ERROR] POLYMARKET_PRIVATE_KEY not found in env!")
            return
        
        creds = ApiCreds(
            api_key=os.getenv("CLOB_API_KEY"),
            api_secret=os.getenv("CLOB_SECRET"),
            api_passphrase=os.getenv("CLOB_PASSPHRASE")
        )

        client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=POLYGON, creds=creds, signature_type=0, funder=MAKER_ADDRESS)

        # 2.1 CHECK POSITION FOR TARGET ASSET (BTC Dip)
        target_token = "65596524896985010415844814777069255362767748488616308434723608750130614059462"
        try:
            bal_params = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=target_token)
            bal_resp = client.get_balance_allowance(bal_params)
            print(f"\n[TARGET MARKET POSITION]")
            print(f" - Token Balance: {bal_resp.get('balance', '0')} shares")
        except: pass

        # 2.2 FETCH & ANALYZE TRADES
        trades = client.get_trades(params=None)
        print(f"\n[TRADE LOG - DETAILED ATTRIBUTION]")
        if not trades:
            print(" - No trades found.")
        else:
            trades.sort(key=lambda x: int(x.get('match_time', 0)), reverse=True)
            realized_pnl = 0.0
            pnl_tracker = {} # asset -> {pos, cost}

            for t in reversed(trades): # Chronological
                asset = t.get('asset_id')
                side = t.get('side') # Taker side
                size = float(t.get('size', 0))
                price = float(t.get('price', 0))
                
                # Correction: Determine user's actual side and actual size matched in the multi-maker trade
                my_actual_size = 0.0
                my_side = None
                
                # Check maker orders for our contribution
                if 'maker_orders' in t:
                    for mo in t['maker_orders']:
                        if mo.get('maker_address') == MAKER_ADDRESS:
                            my_actual_size += float(mo.get('matched_amount', 0))
                            my_side = mo.get('side')
                
                if my_actual_size == 0:
                      # If not maker, maybe we were taker?
                      # For this bot, we are usually maker. Let's assume taker if maker_orders not present/matching
                      pass

                if my_side and my_actual_size > 0:
                    if asset not in pnl_tracker: pnl_tracker[asset] = {"pos": 0.0, "cost": 0.0}
                    if my_side == 'BUY':
                        pnl_tracker[asset]["pos"] += my_actual_size
                        pnl_tracker[asset]["cost"] += (my_actual_size * price)
                    else: # SELL
                        if pnl_tracker[asset]["pos"] > 0:
                            avg_cost = pnl_tracker[asset]["cost"] / pnl_tracker[asset]["pos"]
                            realized_pnl += (price - avg_cost) * my_actual_size
                            pnl_tracker[asset]["pos"] -= my_actual_size
                            pnl_tracker[asset]["cost"] -= (my_actual_size * avg_cost)
                        else:
                            pnl_tracker[asset]["pos"] -= my_actual_size
                            pnl_tracker[asset]["cost"] -= (my_actual_size * price)

            # Display Trades
            for t in trades[:15]:
                dt = datetime.fromtimestamp(int(t.get('match_time', 0)))
                # Calculate my specific action in this trade for the log
                my_size = sum(float(mo['matched_amount']) for mo in t.get('maker_orders', []) if mo['maker_address'] == MAKER_ADDRESS)
                if my_size > 0:
                    print(f" - {dt.strftime('%H:%M:%S')} | BOUGHT {my_size} @ ${t['price']} (Part of larger {t['side']} {t['size']} trade)")

            print(f"\n[ACCOUNT REALIZED PnL]")
            print(f" - Session Balance Profit/Loss: ${realized_pnl:.4f}")
            for asset, data in pnl_tracker.items():
                if abs(data['pos']) > 0.001:
                    print(f" - Open Position: {data['pos']:.2f} tokens (Asset ...{asset[-6:]})")
                    print(f"   Avg Entry: ${data['cost']/data['pos']:.3f}")

    except Exception as e:
        print(f"\n[API ERROR] {e}")

    print("====================================================\n")

if __name__ == "__main__":
    main()
