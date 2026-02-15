
import os
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON
from curl_cffi import requests as cffi_requests
from dotenv import load_dotenv

load_dotenv("/app/hft/.env")

PROXY_URL = "REDACTED"
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}
MAKER_ADDRESS = "0xb22028EA4E841CA321eb917C706C931a94b564AB"

import py_clob_client.http_helpers.helpers as _clob_helpers
session = cffi_requests.Session(impersonate="chrome110", proxies=SYS_PROXIES)
session.headers = {"Referer": "https://polymarket.com/", "Origin": "https://polymarket.com"}

def patched_request(endpoint, method, headers=None, data=None, **kwargs):
    final_headers = {"Referer": "https://polymarket.com/", "Origin": "https://polymarket.com"}
    if headers: final_headers.update(headers)
    if method == "GET": resp = session.get(endpoint, headers=final_headers)
    elif method == "POST": resp = session.post(endpoint, headers=final_headers, json=data)
    else: return {}
    return resp.json()

_clob_helpers.request = patched_request

pk = os.getenv("POLYMARKET_PRIVATE_KEY")
creds = ApiCreds(
    api_key=os.getenv("CLOB_API_KEY"),
    api_secret=os.getenv("CLOB_SECRET"),
    api_passphrase=os.getenv("CLOB_PASSPHRASE")
)

client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=POLYGON, creds=creds, signature_type=0, funder=MAKER_ADDRESS)

trade_id = "05fe43dc-2385-42de-9d5c-d95b0f4fad7f"
print(f"--- RAW TRADE DATA: {trade_id} ---")
try:
    # There isn't a get_trade by ID in basic py_clob_client, so fetch trades and filter
    trades = client.get_trades(params=None)
    for t in trades:
        if t.get('id') == trade_id:
            print(json.dumps(t, indent=2))
except Exception as e:
    print(f"Error: {e}")
