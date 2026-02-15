import os
import time
import json
import asyncio
import logging
import requests.sessions
from dotenv import load_dotenv

# Load environment FIRST
load_dotenv()

# --- CLOUDFLARE BYPASS PATCH (Must be BEFORE py_clob_client imports) ---
from curl_cffi import requests as cffi_requests
from core.config import PROXY_URL

# Phase 1: Patch standard requests library
original_request = requests.sessions.Session.request
def patched_request(self, method, url, *args, **kwargs):
    headers = kwargs.get("headers") or {}
    if "User-Agent" not in headers or "python-requests" in headers.get("User-Agent", ""):
        headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    kwargs["headers"] = headers
    return original_request(self, method, url, *args, **kwargs)
requests.sessions.Session.request = patched_request

# Phase 2: Create curl_cffi session with Mexico proxy
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}
_cffi_session = cffi_requests.Session(impersonate="chrome110", proxies=SYS_PROXIES)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://polymarket.com",
    "Referer": "https://polymarket.com/",
}

def _cffi_request(endpoint: str, method: str, headers=None, data=None):
    """Replacement request function using curl_cffi for TLS spoofing."""
    from py_clob_client.exceptions import PolyApiException

    final_headers = BROWSER_HEADERS.copy()
    final_headers["Content-Type"] = "application/json"
    if headers:
        final_headers.update(headers)

    json_payload = None
    if isinstance(data, str):
        try:
            json_payload = json.loads(data)
        except:
            pass
    else:
        json_payload = data

    try:
        if method == "GET":
            resp = _cffi_session.get(endpoint, headers=final_headers, timeout=30)
        elif method == "POST":
            resp = _cffi_session.post(endpoint, headers=final_headers, json=json_payload, timeout=30)
        elif method == "DELETE":
            resp = _cffi_session.delete(endpoint, headers=final_headers, json=json_payload, timeout=30)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if resp.status_code not in [200, 201]:
            print(f"[CFFI-ERROR] {method} {endpoint} -> {resp.status_code}")
            class MockResp:
                def __init__(self, sc, txt):
                    self.status_code = sc
                    self.text = txt
            raise PolyApiException(MockResp(resp.status_code, resp.text))

        print(f"[CFFI-OK] {method} {endpoint}")
        return resp.json() if resp.text else {}

    except PolyApiException:
        raise
    except Exception as e:
        raise PolyApiException(error_msg=f"Request exception: {e}")

# Phase 3: Monkey-patch py_clob_client
import py_clob_client.http_helpers.helpers as _clob_helpers
_clob_helpers.request = _cffi_request
print(f"[CHAMELEON] TLS Bypass ACTIVE via Mexico Proxy: {PROXY_URL[:30]}...")

# --- END CLOUDFLARE BYPASS ---

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON
from core.execution.connection import get_protected_session
from core.execution.safety import check_all_guards
from core.execution.trader import place_limit_order

# Setup Logging
logging.basicConfig(level=logging.INFO, format='[BRAIN] %(message)s')
logger = logging.getLogger("V3_BRAIN")

# CONFIGURATION: Alpha Targets (Feb 2026 - Super Bowl LIX)
TARGETS = {
    "SUPER_BOWL": {
        "keywords": ["Super Bowl", "Patriots", "Seahawks", "Winner"],
        "min_volume": 10000
    },
    "EARNINGS": {
        "keywords": ["NVIDIA", "NVDA", "Earnings"],
        "min_volume": 5000
    }
}

def scan_markets(session):
    """Scans Gamma API for high-value targets."""
    logger.info("👁️ Scanning active markets...")
    try:
        url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=50&sort=volume"
        response = session.get(url)
        if response.status_code != 200:
            logger.error(f"Scan Error: {response.status_code}")
            return []

        markets = response.json()
        candidates = []

        for market in markets:
            question = market.get('question', '')
            for category, criteria in TARGETS.items():
                if any(k in question for k in criteria['keywords']):
                    vol = float(market.get('volume', 0) or 0)
                    if vol > criteria['min_volume']:
                        logger.info(f"💡 CANDIDATE FOUND ({category}): {question}")
                        candidates.append(market)
        return candidates
    except Exception as e:
        logger.error(f"Scan Exception: {e}")
        return []

async def execute_hunt(client, session, market):
    """Orchestrates the safety check and execution."""
    # 1. Safety Check
    is_safe, reason = check_all_guards(market)
    if not is_safe:
        logger.warning(f"🛡️ REJECTED: {reason}")
        return

    # 2. Price Check
    best_bid = float(market.get('bestBid', 0) or 0)
    best_ask = float(market.get('bestAsk', 0) or 0)
    midpoint = (best_bid + best_ask) / 2 if (best_bid + best_ask) > 0 else 0

    if midpoint < 0.20 or midpoint > 0.80:
        logger.warning(f"💀 PRICE FILTER: Midpoint ${midpoint:.2f} outside [0.20, 0.80]. Skipping.")
        return

    if midpoint < 0.30 or midpoint > 0.70:
        logger.warning(f"⚠️ EDGE PRICE: Midpoint ${midpoint:.2f} near boundary. Proceed with caution.")

    logger.info(f"✅ PRICE OK: Midpoint ${midpoint:.2f}")

    # 3. Session Warming (Anti-403)
    logger.info("🔥 Warming session...")
    session.get("https://polymarket.com")
    await asyncio.sleep(1)

    # 4. Parse Token ID and Outcomes
    raw_tokens = market.get('clobTokenIds', '[]')
    if isinstance(raw_tokens, str):
        tokens = json.loads(raw_tokens)
    else:
        tokens = raw_tokens or []

    raw_outcomes = market.get('outcomes', '[]')
    if isinstance(raw_outcomes, str):
        outcomes = json.loads(raw_outcomes)
    else:
        outcomes = raw_outcomes or []

    token_id = tokens[0] if tokens else "UNKNOWN"
    outcome_name = outcomes[0] if outcomes else "UNKNOWN"

    if token_id == "UNKNOWN":
        logger.error("❌ No token ID found. Skipping.")
        return

    # 5. LIVE Execution
    logger.info(f"🔫 EXECUTING: BUY {outcome_name} @ ${midpoint:.2f} (Token: {token_id[:20]}...)")
    result = await place_limit_order(client, token_id, midpoint, 5.0, "BUY")
    logger.info(f"📋 Result: {result}")

async def init_client():
    """Initialize ClobClient with credentials from .env"""
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    api_key = os.getenv("CLOB_API_KEY")
    api_secret = os.getenv("CLOB_SECRET")
    passphrase = os.getenv("CLOB_PASSPHRASE")

    if not all([pk, api_key, api_secret, passphrase]):
        raise ValueError("Missing credentials in .env")

    creds = ApiCreds(
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=passphrase
    )

    client = await asyncio.to_thread(
        ClobClient,
        host="https://clob.polymarket.com",
        key=pk,
        chain_id=POLYGON,
        creds=creds,
        signature_type=0  # EOA Mode
    )

    logger.info(f"✅ ClobClient initialized (EOA Mode) via Mexico Proxy")
    return client

async def main():
    logger.info("🤖 V3 SOVEREIGN HUNTER STARTING...")

    # Initialize
    session = get_protected_session(PROXY_URL)
    client = await init_client()

    while True:
        candidates = scan_markets(session)
        for market in candidates:
            await execute_hunt(client, session, market)

        logger.info("💤 Sleeping 60s...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
