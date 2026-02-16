
import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON
from curl_cffi import requests as cffi_requests
from dotenv import load_dotenv

load_dotenv("/app/hft/.env")

PROXY_URL = os.getenv("PROXY_URL", "")
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}

# Monkey patch requests to use proxy
import py_clob_client.http_helpers.helpers as _clob_helpers
session = cffi_requests.Session(impersonate="chrome110", proxies=SYS_PROXIES)
session.headers = {"Referer": "https://polymarket.com/", "Origin": "https://polymarket.com"}

def patched_request(endpoint, method, headers=None, data=None, **kwargs):
    # Strip manual headers that might break fingerprint, keep Auth
    final_headers = {"Referer": "https://polymarket.com/", "Origin": "https://polymarket.com"}
    if headers: final_headers.update(headers)
    
    if method == "GET":
        resp = session.get(endpoint, headers=final_headers)
    elif method == "POST":
         resp = session.post(endpoint, headers=final_headers, json=data)
    elif method == "DELETE":
         resp = session.delete(endpoint, headers=final_headers)
    else:
        return {}
        
    return resp.json()

_clob_helpers.request = patched_request

pk = os.getenv("POLYMARKET_PRIVATE_KEY")
creds = ApiCreds(
    api_key=os.getenv("CLOB_API_KEY"),
    api_secret=os.getenv("CLOB_SECRET"),
    api_passphrase=os.getenv("CLOB_PASSPHRASE")
)

client = ClobClient(
    host="https://clob.polymarket.com",
    key=pk,
    chain_id=POLYGON,
    creds=creds,
    signature_type=0, # FORCE EOA
    funder="0xb22028EA4E841CA321eb917C706C931a94b564AB"
)

print(f"[CHECK] Fetching Orders for {client.signer.address()}...")
try:
    # Get Open Orders
    orders = client.get_orders()
    print(f"\n[OPEN ORDERS] Count: {len(orders)}")
    for o in orders:
        print(f" - ID: {o.get('orderID')} | Side: {o.get('side')} | Size: {o.get('size')} | Price: {o.get('price')}")
        
    # Get Trades
    trades = client.get_trades(params=None)
    print(f"\n[TRADES] Count: {len(trades)}")
    for t in trades:
        print(f" - ID: {t.get('id')} | Side: {t.get('side')} | Size: {t.get('size')} | Price: {t.get('price')} | Match: {t.get('match_time')}")
        
    # Check Specific Order
    target_id = "0x5b088ece7f78baeef3a00c8b0b2daf36d54d97e68190c191fe8b3918f6c36e42"
    print(f"\n[CHECK ORDER] {target_id}")
    try:
        o_status = client.get_order(target_id)
        print(f" - Status: {o_status}")
    except Exception as e:
        print(f" - Error fetching order: {e}")
        
except Exception as e:
    print(f"[ERROR] {e}")
