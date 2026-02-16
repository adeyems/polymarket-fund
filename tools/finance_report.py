#!/usr/bin/env python3
import os
import sys
import math
from dotenv import load_dotenv
from web3 import Web3
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from py_clob_client.constants import POLYGON
from curl_cffi import requests as cffi_requests
import py_clob_client.http_helpers.helpers as _clob_helpers

# --- CONFIG ---
load_dotenv(".env")
load_dotenv("/app/hft/.env")

RPC_URL = "https://1rpc.io/matic"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
MAKER_ADDRESS = "0xb22028EA4E841CA321eb917C706C931a94b564AB"
GAS_COST_PER_TRADE = 0.05
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

def get_market_midpoint(client, token_id):
    try:
        orderbook = client.get_order_book(token_id)
        bids = orderbook.bids
        asks = orderbook.asks
        if bids and asks:
            best_bid = float(bids[0].price)
            best_ask = float(asks[0].price)
            return (best_bid + best_ask) / 2
        return 0.0
    except:
        return 0.0

def main():
    print("\nProcessing Financial Data...\n")

    # 1. LIQUIDITY (CHAIN)
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    matic_bal = w3.from_wei(w3.eth.get_balance(MAKER_ADDRESS), 'ether')
    
    abi = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"}]
    
    usdc_ct = w3.eth.contract(address=USDC_ADDRESS, abi=abi)
    usdc_bal = usdc_ct.functions.balanceOf(MAKER_ADDRESS).call() / (10 ** 6)

    native_ct = w3.eth.contract(address=Web3.to_checksum_address(NATIVE_USDC), abi=abi)
    native_bal = native_ct.functions.balanceOf(MAKER_ADDRESS).call() / (10 ** 6)

    # 2. INVENTORY (API)
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    creds = ApiCreds(api_key=os.getenv("CLOB_API_KEY"), api_secret=os.getenv("CLOB_SECRET"), api_passphrase=os.getenv("CLOB_PASSPHRASE"))
    client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=POLYGON, creds=creds, signature_type=0, funder=MAKER_ADDRESS)

    # Hardcoded target for MVP speed, ideally fetch all
    target_token = "65596524896985010415844814777069255362767748488616308434723608750130614059462"
    pos_shares = 0
    try:
        bal_resp = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=target_token))
        pos_shares = float(bal_resp.get('balance', '0')) / (10 ** 6)
    except: pass

    current_price = get_market_midpoint(client, target_token)
    pos_value = pos_shares * current_price
    
    # 3. ANALYSIS
    liq_status = "🟢 HEALTHY" if usdc_bal >= 5.0 else "🔴 LOW FUNDS (<$5.00)"
    runway = math.floor(float(matic_bal) / GAS_COST_PER_TRADE)
    net_worth = usdc_bal + (float(matic_bal) * 0.85) + pos_value # Approx POL=$0.85

    # 4. REPORT
    print("┌────────────────────────────────────────────────────────┐")
    print("│              💰  CFO FINANCIAL REPORT  💰              │")
    print("└────────────────────────────────────────────────────────┘")
    
    print("\n1️⃣  LIQUIDITY (Buying Power)")
    print(f" • USDC.e Balance   : ${usdc_bal:.2f}  {liq_status}")
    print(f" • Native USDC      : ${native_bal:.2f}  (Stuck Funds)")
    
    print("\n2️⃣  OPERATIONS (Gas)")
    print(f" • POL Balance      : {matic_bal:.4f} POL")
    print(f" • Est. Runway      : ~{runway} Trades (@ {GAS_COST_PER_TRADE} POL/tx)")
    
    print("\n3️⃣  INVENTORY (Positions)")
    if pos_shares > 0:
        avg_entry = 0.27 # Known from previous logs, ideally fetched
        unrealized = (current_price - avg_entry) * pos_shares
        pnl_icon = "🟢" if unrealized >= 0 else "🔴"
        print(f" • Active Position  : {pos_shares} Shares (Asset ...59462)")
        print(f" • Current Price    : ${current_price:.3f}")
        print(f" • Position Value   : ${pos_value:.2f}")
        print(f" • Unrealized PnL   : {pnl_icon} ${unrealized:+.2f} ({unrealized/(avg_entry*pos_shares)*100:+.1f}%)")
    else:
        print(" • No Active Positions")

    print("\n══════════════════════════════════════════════════════════")
    print(f"💎 TOTAL NET WORTH: ${net_worth:.2f}")
    print("══════════════════════════════════════════════════════════\n")

if __name__ == "__main__":
    main()
