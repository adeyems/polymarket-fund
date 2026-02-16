#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.constants import POLYGON
from curl_cffi import requests as cffi_requests
import py_clob_client.http_helpers.helpers as _clob_helpers

load_dotenv(".env")
load_dotenv("/app/hft/.env")

MAKER_ADDRESS = "0xb22028EA4E841CA321eb917C706C931a94b564AB"
PROXY_URL = os.getenv("PROXY_URL", "")
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}

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
    print("🚨 EMERGENCY: CANCELLING ALL ORDERS")
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    creds = ApiCreds(api_key=os.getenv("CLOB_API_KEY"), api_secret=os.getenv("CLOB_SECRET"), api_passphrase=os.getenv("CLOB_PASSPHRASE"))
    client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=POLYGON, creds=creds, signature_type=0, funder=MAKER_ADDRESS)

    try:
        resp = client.cancel_all()
        print(f"✅ CANCEL REQUEST SENT: {resp}")
    except Exception as e:
        print(f"❌ CANCEL FAILED: {e}")

if __name__ == "__main__":
    main()
