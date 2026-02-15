import os
import sys
import time
import json
import asyncio
import requests
import statistics
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, TradeParams
from py_clob_client.constants import POLYGON

# --- CLOUDFLARE BYPASS PATCH (CHAMELEON PROTOCOL) ---
import requests.sessions
from curl_cffi import requests as cffi_requests
from core.config import PROXY_URL

# Patch requests
original_request = requests.sessions.Session.request
def patched_request(self, method, url, *args, **kwargs):
    headers = kwargs.get("headers", {})
    if "User-Agent" not in headers:
        headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    kwargs["headers"] = headers
    return original_request(self, method, url, *args, **kwargs)
requests.sessions.Session.request = patched_request

# Patch py_clob_client
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}
_cffi_session = cffi_requests.Session(impersonate="chrome120", proxies=SYS_PROXIES)

def _cffi_request(endpoint: str, method: str, headers=None, data=None):
    from py_clob_client.exceptions import PolyApiException
    final_headers = {
        "Content-Type": "application/json",
        "Referer": "https://polymarket.com/",
        "Origin": "https://polymarket.com"
    }
    if headers: final_headers.update(headers)
    
    try:
        if method == "GET":
            resp = _cffi_session.get(endpoint, headers=final_headers, timeout=30)
        elif method == "POST":
            if isinstance(data, str):
                resp = _cffi_session.post(endpoint, headers=final_headers, data=data, timeout=30)
            else:
                resp = _cffi_session.post(endpoint, headers=final_headers, json=data, timeout=30)
        
        if resp.status_code != 200:
             # Mock response for error handling
            class MockResp:
                def __init__(self, s, t): self.status_code = s; self._text = t
                def text(self): return self._text
            raise PolyApiException(MockResp(resp.status_code, resp.text))
            
        try: return resp.json()
        except: return resp.text
    except Exception as e:
        raise PolyApiException(error_msg=f"Request exception: {e}")

import py_clob_client.http_helpers.helpers as _clob_helpers
_clob_helpers.request = _cffi_request
# --- END PATCH ---

load_dotenv()
GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"

def fetch_top_3_markets():
    try:
        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "limit": "3", # LIMIT TO TOP 3
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false"
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        markets = resp.json()
        print(f"[AUDIT] Fetched Top {len(markets)} Markets.")
        return markets
    except Exception as e:
        print(f"[ERROR] API Error: {e}")
        return []

def calculate_vwap_exit(bids, size=35.0):
    if not bids: return 0.0
    remaining = size * 1e6
    total_value = 0.0
    for bid in bids:
        if remaining <= 0: break
        p = float(bid.price)
        s = float(bid.size)
        take = min(s, remaining)
        total_value += (take / 1e6) * p
        remaining -= take
    if remaining > 0: return 0.0
    return total_value / size

async def run_audit():
    print("======== ALPHA DRY RUN: TOP 3 MARKETS ========")
    
    # Init Client
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    api_key = os.getenv("CLOB_API_KEY")
    api_secret = os.getenv("CLOB_SECRET")
    api_passphrase = os.getenv("CLOB_PASSPHRASE")
    creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
    
    client = await asyncio.to_thread(
        ClobClient,
        host="https://clob.polymarket.com",
        key=pk,
        chain_id=POLYGON,
        creds=creds,
        signature_type=0,
        funder=None
    )
    
    markets = fetch_top_3_markets()
    
    for market in markets:
        print("-" * 60)
        question = market.get('question', 'Unknown')
        print(f"[MARKET] {question}")
        
        # 1. Volume Check
        vol_24h = float(market.get('volume24hr', 0))
        print(f"  > Volume (24h): ${vol_24h:,.0f}")
        
        # 2. Spread & VWAP
        clob_ids = json.loads(market.get('clobTokenIds', '[]'))
        if not clob_ids:
            print("  > VERDICT: FAIL (No CLOB ID)")
            continue
        token_id = clob_ids[0]
        
        order_book = await asyncio.to_thread(client.get_order_book, token_id)
        
        best_bid = 0.0
        if order_book.bids:
            best_bid = max([float(b.price) for b in order_book.bids])
            
        best_ask = 1.0
        if order_book.asks:
            best_ask = min([float(a.price) for a in order_book.asks])
            
        current_spread = best_ask - best_bid
        midpoint = (best_bid + best_ask) / 2 if (best_bid + best_ask) > 0 else 0.50
        spread_pct = (best_ask - best_bid) / midpoint if midpoint > 0 else 1.0
        
        print(f"  > Spread: {spread_pct*100:.2f}% (Bid: {best_bid} | Ask: {best_ask})")
        
        vwap_exit = calculate_vwap_exit(order_book.bids, size=35.0)
        print(f"  > VWAP Exit (35 shares): ${vwap_exit:.3f}")
        
        # DECISION
        checks = []
        fail_reasons = []
        
        # check 1: volume
        if vol_24h > 25000: checks.append("✅ Volume")
        else: fail_reasons.append(f"Volume Low (${vol_24h:,.0f} < $25k)")
        
        # check 2: spread
        if spread_pct < 0.05: checks.append("✅ Spread")
        else: fail_reasons.append(f"Spread Wide ({spread_pct*100:.1f}% > 5%)")
        
        # check 3: vwap
        gap = (midpoint - vwap_exit) / midpoint if midpoint > 0 else 0
        if gap < 0.10 and vwap_exit > 0: checks.append("✅ VWAP")
        else: fail_reasons.append(f"Illiquid (Gap {gap*100:.1f}%)")
        
        if not fail_reasons:
            print(f"  > 🏆 VERDICT: PASS")
            
            # SIMULATION
            buy_price = best_bid if best_bid > 0 else 0.50
            buy_qty = round(5.05 / buy_price, 2) if buy_price > 0 else 0.0
            print(f"  > [SIMULATION] Would have placed $5.05 Buy at ${buy_price:.2f} (Size: {buy_qty} Shares)")
        else:
            print(f"  > ⛔ VERDICT: FAIL")
            for reason in fail_reasons:
                print(f"    - {reason}")
                
    print("-" * 60)
    print("======== AUDIT COMPLETE ========")

if __name__ == "__main__":
    asyncio.run(run_audit())
