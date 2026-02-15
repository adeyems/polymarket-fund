#!/usr/bin/env python3
"""
Sell 5 shares of Kevin Warsh YES position at market price.
Uses the same request patching as the working market_maker.py
"""
import os
import sys
import json

# Fix dotenv path explicitly
from dotenv import load_dotenv
load_dotenv('/Users/qudus-mac/PycharmProjects/polymarket-fund/.env')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Config
HOST = "https://clob.polymarket.com"
PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
PROXY_URL = "REDACTED"

# Kevin Warsh YES token
TOKEN_ID = "51338236787729560681434534660841415073585974762690814047670810862722808070955"

# ============ PATCH REQUESTS (same as market_maker.py) ============
from curl_cffi import requests as cffi_requests

SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}
_cffi_session = cffi_requests.Session(impersonate="chrome110", proxies=SYS_PROXIES)

BROWSER_HEADERS = {
    "User-Agent": "curl/7.68.0",
    "Accept": "application/json",
    "Origin": "https://polymarket.com",
    "Referer": "https://polymarket.com/",
}

def _cffi_request(endpoint: str, method: str, headers=None, data=None):
    """Replacement request function using curl_cffi for TLS spoofing."""
    from py_clob_client.exceptions import PolyApiException

    final_headers = BROWSER_HEADERS.copy()
    final_headers.update({"Content-Type": "application/json"})
    if headers:
        final_headers.update(headers)

    try:
        if method == "GET":
            resp = _cffi_session.get(endpoint, headers=final_headers, timeout=30)
        elif method == "POST":
            json_payload = None
            if isinstance(data, str):
                try:
                    json_payload = json.loads(data)
                except:
                    pass
            else:
                json_payload = data

            if json_payload:
                resp = _cffi_session.post(endpoint, headers=final_headers, json=json_payload, timeout=30)
            else:
                resp = _cffi_session.post(endpoint, headers=final_headers, data=data, timeout=30)
        elif method == "DELETE":
            resp = _cffi_session.delete(endpoint, headers=final_headers, json=data, timeout=30)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if resp.status_code != 200 and resp.status_code != 201:
            print(f"[API-ERROR] {method} {endpoint} -> {resp.status_code}: {resp.text[:200]}")

            class MockResp:
                def __init__(self, status_code, text):
                    self.status_code = status_code
                    self.text = text
            raise PolyApiException(MockResp(resp.status_code, resp.text))

        if method == "POST":
            print(f"[CURL-DEBUG] Success POST to {endpoint}")

        try:
            return resp.json()
        except ValueError:
            return resp.text
    except cffi_requests.RequestsError as e:
        raise PolyApiException(error_msg=f"Request exception: {e}")

# Patch py_clob_client helpers
import py_clob_client.http_helpers.helpers as helpers
helpers.request = _cffi_request

# ============ MAIN ============
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.constants import POLYGON


def main():
    print("=" * 60)
    print("SELL ORDER: Kevin Warsh YES - 5 Shares")
    print("=" * 60)
    print(f"[PROXY] Using: {PROXY_URL.split('@')[1]}")

    # Initialize client (correct wallet address derived from private key)
    client = ClobClient(
        host=HOST,
        key=PRIVATE_KEY,
        chain_id=POLYGON,
        signature_type=0,  # EOA mode
        funder="0xb22028EA4E841CA321eb917C706C931a94b564AB"
    )

    # Use API creds for CORRECT wallet (created 2026-02-03)
    from py_clob_client.clob_types import ApiCreds
    creds = ApiCreds(
        api_key="9377cf5f-f279-b7e1-9dcc-f8ef0e23b2d5",
        api_secret="1HQ_pSFzoaLan0pYbqjrRziQWh0vQs6goSMhKOI2FQg=",
        api_passphrase="9d649a52f83748fc17be24164ebd8954b6806e0d59b947368d0e6ac252546c96"
    )
    client.set_api_creds(creds)
    print(f"[AUTH] Using credentials for correct wallet: {creds.api_key[:8]}...")

    # Use known best bid from order book check
    # Best bid is $0.98 with 102 shares
    best_bid = 0.98
    print(f"\n[ORDERBOOK] Using best bid: ${best_bid:.4f}")

    # Sell 5 shares at best bid (market is Neg Risk)
    sell_price = best_bid  # Match the best bid exactly
    sell_qty = 5.0

    print(f"\n[ORDER] SELL {sell_qty} shares @ ${sell_price:.3f}")
    print(f"[ORDER] Expected proceeds: ${sell_qty * sell_price:.2f}")

    # Create and submit order
    try:
        order_args = OrderArgs(
            price=sell_price,
            size=sell_qty,
            side="SELL",
            token_id=TOKEN_ID
        )

        signed_order = client.create_order(order_args)
        result = client.post_order(signed_order, OrderType.GTC)

        print(f"\n[SUCCESS] Order submitted!")
        print(f"[ORDER_ID] {result.get('orderID', 'N/A')}")
        print(f"[STATUS] {result.get('status', 'N/A')}")

        if result.get('status') == 'matched':
            print(f"\n✅ SOLD! Proceeds: ~${sell_qty * sell_price:.2f} USDC.e")
        elif result.get('status') == 'live':
            print(f"\n⏳ Order is live, waiting for fill...")

        return result

    except Exception as e:
        print(f"\n[ERROR] Order failed: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
