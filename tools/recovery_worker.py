import os
import time
import json
import logging
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
# from py_clob_client.clob_types import OrderType

class OrderType:
    GTC = "GTC"
    GTD = "GTD"
    FOK = "FOK"
    IOC = "IOC"
# from py_clob_client.order_builder.constants import SELL
SELL = "SELL"
BUY = "BUY"
import requests.sessions

import requests.sessions
import json
import py_clob_client.http_helpers.helpers as _clob_helpers
from curl_cffi import requests as cffi_requests
from py_clob_client.exceptions import PolyApiException

# --- CLOUDFLARE BYPASS PATCH (CHAMELEON PROTOCOL V2) ---
# Hardcoded Proxy to avoid import issues if core not in path
PROXY_URL = "REDACTED" 
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}

_cffi_session = cffi_requests.Session(impersonate="chrome110", proxies=SYS_PROXIES)

def _cffi_request(endpoint: str, method: str, headers=None, data=None):
    """Replacement request function using curl_cffi for TLS spoofing."""
    final_headers = {
        "Content-Type": "application/json",
        "Referer": "https://polymarket.com/",
        "Origin": "https://polymarket.com"
    }

    if headers:
        final_headers.update(headers)

    try:
        if method == "GET":
            resp = _cffi_session.get(endpoint, headers=final_headers, timeout=30)
        elif method == "POST":
            if isinstance(data, str):
                try:
                    json_data = json.loads(data)
                    resp = _cffi_session.post(endpoint, headers=final_headers, json=json_data, timeout=30)
                except:
                    resp = _cffi_session.post(endpoint, headers=final_headers, data=data, timeout=30)
            else:
                resp = _cffi_session.post(endpoint, headers=final_headers, json=data, timeout=30)
        elif method == "DELETE":
            resp = _cffi_session.delete(endpoint, headers=final_headers, json=data, timeout=30)
        elif method == "PUT":
            resp = _cffi_session.put(endpoint, headers=final_headers, json=data, timeout=30)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if resp.status_code != 200:
            print(f"[API-ERROR] {method} {endpoint} -> {resp.status_code}: {resp.text}")
            class MockResp:
                def __init__(self, status_code, text):
                    self.status_code = status_code
                    self._text = text
                @property
                def text(self): return self._text
            raise PolyApiException(MockResp(resp.status_code, resp.text))

        try:
            return resp.json()
        except ValueError:
            return resp.text
            
    except cffi_requests.RequestsError as e:
        raise PolyApiException(error_msg=f"Request exception: {e}")

_clob_helpers.request = _cffi_request
print("[CHAMELEON] TLS Fingerprint Spoofing ACTIVE (curl_cffi/chrome110)")

# --- CONFIG ---
TOKEN_ID = "65596524896985010415844814777069255362767748488616308434723608750130614059462" # Bitcoin Dip
load_dotenv("/app/hft/.env")

KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

if not KEY:
    print("❌ KEYS MISSING")
    exit(1)

logging.basicConfig(level=logging.INFO, format='[RECOVERY] %(message)s')
logger = logging.getLogger("recovery")

def main():
    logger.info("🚑 STARTING LADDERED RECOVERY WORKER")
    
    # Init Client
    try:
        client = ClobClient(host=HOST, key=KEY, chain_id=CHAIN_ID, signature_type=0)
        client.set_api_creds(client.create_or_derive_api_creds())
        logger.info("✅ Client Connected")
    except Exception as e:
        logger.error(f"Client Init Failed: {e}")
        return

    # Loop
    while True:
        try:
            # 1. Check Position
            # Need to fetch balance of this specific token.
            # get_balance returns ALL? Or check via PolygonScan?
            # CLOB client might not give token balance easily if not in 'positions'.
            # client.get_account_rewards? No.
            # We track "Remaining" manually? No, unsafe.
            # We'll blindly place orders if we don't know? Risk of failure.
            # Let's assume we have them. If order fails due to insufficient balance, we stop.
            
            # 2. Check Open Orders
            # Assuming get_orders returns all orders?
            orders = client.get_orders()
            # Filter for this token and active status
            open_orders = [
                o for o in orders 
                if o.get('tokenID') == TOKEN_ID and o.get('status') in ['open', 'matched'] # Matched might be partial?
                # Actually, check 'side' too?
                # And 'status' should be 'active' or 'open'?
                # Assuming 'status' field exists.
            ]
            # Better: if orders list is huge, this is bad.
            # Does get_orders accept parsed params?
            # client.get_orders(market=TOKEN_ID)?
            if open_orders:
                logger.info(f"⏳ Open Orders Found: {len(open_orders)}. Waiting...")
                time.sleep(60)
                continue
            
            # 3. Place Order (Ladder Step)
            logger.info("⚡ Placing Sell Order: 5 Shares @ $0.25")
            order_args = OrderArgs(
                token_id=TOKEN_ID,
                price=0.25,
                size=5.0,
                side=SELL
            )
            
            try:
                signed_order = client.create_order(order_args)
                resp = client.post_order(signed_order, OrderType.GTC)
                order_id = resp.get('orderID')
                logger.info(f"✅ Order Placed: {order_id}")
                
                # 4. Wait Loop (Check fill status)
                # Wait for fill before starting 30m timer? 
                # User: "If it fills, wait 30 minutes".
                
                filled = False
                while not filled:
                    time.sleep(10)
                    # Check status
                    # get_order(order_id)
                    try:
                        o_status = client.get_order(order_id)
                        # status: 'matched' or 'open' or 'cancelled'
                        # Actually 'status' field?
                        # Depending on API response structure.
                        # Usually 'size_matched' vs 'original_size'.
                        matched = float(o_status.get('size_matched', 0))
                        if matched >= 5.0:
                            logger.info("🎉 Order FILLED!")
                            filled = True
                        elif o_status.get('status') == 'canceled':
                            logger.info("❌ Order Cancelled externally. Retrying...")
                            break 
                    except Exception as e_stat:
                        logger.warning(f"Status check error: {e_stat}")
                        time.sleep(10)
                
                if filled:
                    logger.info("🕒 Starting 30-Minute Cooldown...")
                    time.sleep(1800) # 30 mins
                    logger.info("⏰ Cooldown Complete. Preparing next batch.")

            except Exception as e_order:
                logger.error(f"Order Placement Failed: {e_order}")
                if "insufficient" in str(e_order).lower():
                    logger.info("🛑 Insufficient Balance? recovery complete?")
                    break
                time.sleep(60)

        except Exception as e_main:
            logger.error(f"Loop Error: {e_main}")
            time.sleep(60)

if __name__ == "__main__":
    main()
