
import os
import json
import sys
from curl_cffi import requests as cffi_requests
from py_clob_client.constants import POLYGON
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, ApiCreds
from py_clob_client.order_builder.constants import BUY
from dotenv import load_dotenv

# Load Env
load_dotenv("/app/hft/.env")

# CONFIGURATION
# USDC.e (Bridged) on Polygon
TOKEN_ADDRESS_USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
# USDC (Native) on Polygon
TOKEN_ADDRESS_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

# Verify Env
pk = os.getenv("POLYMARKET_PRIVATE_KEY")
if not pk:
    print("[ERROR] POLYMARKET_PRIVATE_KEY is Missing!")
    sys.exit(1)

PROXY_URL = os.getenv("PROXY_URL", "")
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}

print(f"[TEST] Hooking Proxy: {PROXY_URL}")

# Create Session
session = cffi_requests.Session(impersonate="chrome110", proxies=SYS_PROXIES)

# Minimal Headers
session.headers = {
    "Referer": "https://polymarket.com/",
    "Origin": "https://polymarket.com",
    "Content-Type": "application/json"
}

def patched_post(url, headers=None, data=None, **kwargs):
    print(f"[POST] {url}")
    # Force JSON
    if data and isinstance(data, str):
        try:
            kwargs['json'] = json.loads(data)
        except:
            kwargs['data'] = data
    elif data:
        kwargs['json'] = data
        
    try:
        resp = session.post(url, headers=headers, **kwargs)
        if resp.status_code != 200:
            print(f"[FAIL] {resp.status_code} | {resp.text}")
        else:
            print(f"[SUCCESS] {resp.json()}")
        return resp
    except Exception as e:
        print(f"[CRITICAL] {e}")
        raise e

# Monkey Patch
import py_clob_client.http_helpers.helpers as _clob_helpers
_clob_helpers.request = lambda url, method, headers=None, data=None, **kwargs: patched_post(url, headers=headers, data=data, **kwargs) if method == "POST" else session.request(method, url, headers=headers, json=data, **kwargs).json()

print("[TEST] Initializing Client...")
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

print(f"[TEST] Signer Address: {client.signer.address}")
try:
    # Check if we have a proxy
    print(f"[TEST] Creds derivation...")
except:
    pass

print("[TEST] Fetching Balances...")
try:
    # Manual Web3 Balance Check for diagnostic
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
    
    # USDC.e
    contract_e = w3.eth.contract(address=w3.to_checksum_address(TOKEN_ADDRESS_USDC_E), abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"type":"function"}])
    bal_e = contract_e.functions.balanceOf(client.signer.address()).call()
    print(f"[TEST] USDC.e Balance (EOA): {bal_e / 1e6}")
    
    # Native USDC
    contract_n = w3.eth.contract(address=w3.to_checksum_address(TOKEN_ADDRESS_NATIVE), abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":False,"type":"function"}])
    bal_n = contract_n.functions.balanceOf(client.signer.address()).call()
    print(f"[TEST] Native USDC Balance (EOA): {bal_n / 1e6}")
except Exception as e:
    print(f"[TEST] Balance Check Error: {e}")

print("[TEST] Fetching Market Data (Gamma API)...")
try:
    token_id = "65596524896985010415844814777069255362767748488616308434723608750130614059462"
    # Gamma API uses hash or slug usually, but let's try searching by token_id via events or similar
    # The token_id is a boolean outcome token.
    # We can try to get the market via CLOB API again but ensuring correct endpoint?
    # Actually, simpler: Use requests to get Clob Market
    resp = session.get(f"https://clob.polymarket.com/sampling-simplified-markets")
    if resp.status_code == 200:
        markets = resp.json().get('data', []) or resp.json()
        found = False
        for m in markets:
            if m.get('token_id') == token_id or m.get('asset_id') == token_id:
                print(f"[TEST] Market Found: {str(m)[:300]}")
                found = True
                break
        if not found:
            print("[TEST] Market NOT found in sampling")
    else:
        print(f"[TEST] CLOB Sampling Failed: {resp.status_code}")
        
except Exception as e:
    print(f"[TEST] Gamma/Fetch Error: {e}")

print(f"[TEST] Using Collateral (USDC.e): 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
print("[TEST] Signing Order...")
# Will Bitcoin dip to $85,000 in January?
token_id = "65596524896985010415844814777069255362767748488616308434723608750130614059462"
# Force Maker to be Signer (EOA)
order_args = OrderArgs(
    token_id=token_id,
    price=0.50,
    size=10.0,
    side=BUY
)
signed_order = client.create_order(order_args)

print("[TEST] Sending Order...")
try:
    resp = client.post_order(signed_order, OrderType.GTC)
    print(f"[RESULT] {resp}")
except Exception as e:
    print(f"[ERROR] {e}")
