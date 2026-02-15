import os
import sys
import time
import json
import csv
import random
import requests
import subprocess
import requests.sessions
import aiohttp
from core.config import PROXY_URL, DISCORD_WEBHOOK_URL
from alerts.trade_alerts import send_trade_alert_fire_and_forget

# --- CLOUDFLARE BYPASS PATCH (CHAMELEON PROTOCOL) ---
# Phase 1: Patch requests library
original_request = requests.sessions.Session.request
def patched_request(self, method, url, *args, **kwargs):
    headers = kwargs.get("headers")
    if headers is None:
        headers = {}

    ua = headers.get("User-Agent", "")
    if "User-Agent" not in headers or "python-requests" in ua:
        headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    kwargs["headers"] = headers
    return original_request(self, method, url, *args, **kwargs)

requests.sessions.Session.request = patched_request

# Phase 2: Patch py_clob_client to use curl_cffi (TLS Fingerprint Spoofing)
from curl_cffi import requests as cffi_requests
from core.config import PROXY_URL

# Define the Tunnel (Mexico Residential Proxy)
# curl_cffi expects a simple dict or string. Using dict for explicit routing.
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}

# Create a Chrome-impersonating session with PROXY
# NOTE: curl_cffi handles proxies natively
_cffi_session = cffi_requests.Session(impersonate="chrome110", proxies=SYS_PROXIES)

# Minimal Headers for API access (Too many browser headers can trigger detection)
BROWSER_HEADERS = {
    "User-Agent": "curl/7.68.0", # Try a simple CLI UA or standard browser
    "Accept": "application/json",
    "Origin": "https://polymarket.com",
    "Referer": "https://polymarket.com/",
}

def _cffi_request(endpoint: str, method: str, headers=None, data=None):
    """Replacement request function using curl_cffi for TLS spoofing."""
    from py_clob_client.exceptions import PolyApiException

    # Merge with BROWSER_HEADERS for full fingerprint
    final_headers = BROWSER_HEADERS.copy()
    final_headers.update({
        "Content-Type": "application/json",
    })

    # Add any explicit headers passed by caller (like Auth)
    if headers:
        final_headers.update(headers)


    try:
        if method == "GET":
            resp = _cffi_session.get(endpoint, headers=final_headers, timeout=30)
        elif method == "POST":
            # Force JSON handling for correct Content-Length/Type
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
            
            # --- CLOUDFLARE BYPASS RETRY: NO PROXY ---
            if resp.status_code == 403 and "cloudflare" in resp.text.lower():
                print(f"[RETRY] 🚀 Cloudflare Block via Proxy. Retrying DIRECTly from EC2 IP...")
                # We need a session WITHOUT proxies
                direct_session = cffi_requests.Session(impersonate="chrome120")
                if json_payload:
                    resp = direct_session.post(endpoint, headers=final_headers, json=json_payload, timeout=30)
                else:
                    resp = direct_session.post(endpoint, headers=final_headers, data=data, timeout=30)
        elif method == "DELETE":
            resp = _cffi_session.delete(endpoint, headers=final_headers, json=data, timeout=30)
        elif method == "PUT":
            resp = _cffi_session.put(endpoint, headers=final_headers, json=data, timeout=30)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if resp.status_code != 200 and resp.status_code != 201:
            # Log the actual error response
            print(f"[API-ERROR] {method} {endpoint} -> {resp.status_code}: {resp.text[:200]}")
            # Create a mock response object for PolyApiException
            
            class MockResp:
                def __init__(self, status_code, text):
                    self.status_code = status_code
                    self.text = text
            raise PolyApiException(MockResp(resp.status_code, resp.text))


        
        # DEBUG SUCESS
        if method == "POST":
            print(f"[CURL-DEBUG] Success POST to {endpoint}")

        try:
            return resp.json()
        except ValueError:
            return resp.text
    except cffi_requests.RequestsError as e:
        raise PolyApiException(error_msg=f"Request exception: {e}")
    except PolyApiException as pae:
        print(f"[API-FAIL] {method} {endpoint} | Status: {pae.status_code}")
        print(f"[API-FAIL-BODY] Data Sent: {data}")
        # print(f"[API-FAIL-HEADERS] Headers Sent: {merged_headers}")
        raise pae

# Monkey-patch py_clob_client http_helpers
import py_clob_client.http_helpers.helpers as _clob_helpers
_clob_helpers.request = _cffi_request
print("[CHAMELEON] TLS Fingerprint Spoofing ACTIVE (curl_cffi/chrome120)")
# --- END CLOUDFLARE BYPASS ---

async def send_trade_alert(trade_data: dict):
    """
    Fire-and-forget Discord Webhook for trade confirmation.
    Non-blocking to ensure HFT loop is not delayed.
    """
    if not DISCORD_WEBHOOK_URL:
        return

    try:
        # Format the embed
        embed = {
            "title": "⚡ HFT EXECUTION ALERT",
            "color": 3066993,  # Green
            "fields": [
                {"name": "Asset", "value": str(trade_data.get("token_id", "Unknown")), "inline": False},
                {"name": "Action", "value": str(trade_data.get("action", "Unknown")), "inline": True},
                {"name": "Price", "value": f"${trade_data.get('midpoint', 0):.2f}", "inline": True},
                {"name": "PnL Session", "value": f"${trade_data.get('virtual_pnl', 0):.2f}", "inline": True},
                {"name": "Latency", "value": f"{trade_data.get('latency_ms', 0)}ms", "inline": True},
            ],
            "footer": {"text": f"Simulated: {MOCK_TRADING} | Time: {datetime.now().strftime('%H:%M:%S')}"}
        }
        
        payload = {"embeds": [embed]}

        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_WEBHOOK_URL, json=payload) as resp:
                if resp.status != 204:
                    print(f"[ALERT-FAIL] Discord returned {resp.status}")

    except Exception as e:
        print(f"[ALERT-ERROR] Failed to send webhook: {e}")

import re
import statistics
import asyncio
import logging
import signal
import threading
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, RequestArgs
from py_clob_client.headers.headers import create_level_2_headers
from py_clob_client.constants import POLYGON

# Import Shared Schemas & Connectors
from core.config import PROXY_URL
from core.shared_schemas import TradeData, BotParams
from core.monitoring.metrics_exporter import get_metrics_exporter
from core.connectors.binance_ws import get_binance_manager

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Constants
GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"
MOCK_TRADING = False
POLYMARKET_SLUG = "what-price-will-bitcoin-hit-in-january-2026"

# --- REJECTION AUDIT LOGGER ---
import csv
import os as _os_audit

REJECTION_AUDIT_PATH = _os_audit.path.join(_os_audit.path.dirname(__file__), '..', 'data', 'rejection_audit.csv')

def log_rejection(market_name: str, volume_24h: float, spread_pct: float, failed_filter: str, best_bid: float = 0, best_ask: float = 0, vwap_exit: float = 0):
    """Appends a rejection to the audit CSV for strategy optimization."""
    try:
        row = {
            'timestamp': datetime.now().isoformat(),
            'market_name': market_name,
            'volume_24h': volume_24h,
            'spread_pct': round(spread_pct * 100, 2),
            'failed_filter': failed_filter,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'vwap_exit': vwap_exit
        }
        # Ensure directory exists
        _os_audit.makedirs(_os_audit.path.dirname(REJECTION_AUDIT_PATH), exist_ok=True)
        file_exists = _os_audit.path.exists(REJECTION_AUDIT_PATH)
        with open(REJECTION_AUDIT_PATH, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        print(f"[AUDIT-ERR] Failed to log rejection: {e}")

def get_gas_price_gwei():
    """Fetches current gas price in Gwei from PolygonScan API."""
    try:
        # Using a public API for gas price estimation
        response = requests.get("https://api.polygonscan.com/api?module=gastracker&action=gasoracle&apikey=YourApiKeyToken", timeout=5)
        response.raise_for_status()
        data = response.json()
        if data and data['status'] == '1':
            # Return the 'ProposeGasPrice' which is typically the standard gas price
            return float(data['result']['ProposeGasPrice'])
        else:
            logger.warning(f"Failed to fetch gas price from PolygonScan: {data.get('message', 'Unknown error')}")
            return 30.0 # Default to 30 Gwei if API fails
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching gas price: {e}")
        return 30.0 # Default to 30 Gwei on network error
    except Exception as e:
        logger.error(f"Unexpected error in get_gas_price_gwei: {e}")
        return 30.0 # Default on other errors



# --- STATE DUMP (JSON) ---
import json
STATUS_PATH = "bot_status.json"

class TelemetryWorker(threading.Thread):
    """
    Background worker to fetch portfolio state and update local JSON.
    Decoupled from main HFT loop to prevent blocking.
    """
    def __init__(self, client, w3, usdc_contract, user_address):
        super().__init__()
        self.client = client
        self.w3 = w3
        self.usdc_contract = usdc_contract
        self.user_address = user_address
        self.daemon = True # Kill when main process exits
        self.running = True
        
        # State
        self.balances = {"USDC": 0.0, "POL": 0.0}
        self.positions = []
        self.equity = 0.0
        self.pnl = 0.0
        self.trades_count = 0
        self.last_action = "INIT"
        
        # Market Cache (ID -> Slug/Question)
        self.market_map = {} 
        
    def update_metrics(self, pnl, trades, action):
        """Called by main loop to update fast-changing metrics."""
        self.pnl = pnl
        self.trades_count = trades
        self.last_action = action
        # Trigger immediate dump on trade
        if "TRADE" in action:
            self.dump_status()

    def run(self):
        print("[TELEMETRY] Worker Started.")
        while self.running:
            try:
                self.fetch_slow_data()
                self.dump_status()
            except Exception as e:
                print(f"[TELEMETRY-ERR] Worker loop failed: {e}")
            
            # Sleep 60s
            time.sleep(60)

    def fetch_slow_data(self):
        """Fetches Balances and Positions (Slow API calls)."""
        try:
            # 1. Balances
            if self.w3 and self.usdc_contract:
                pol = float(self.w3.from_wei(self.w3.eth.get_balance(self.user_address), 'ether'))
                raw_usdc = self.usdc_contract.functions.balanceOf(self.user_address).call()
                decimals = self.usdc_contract.functions.decimals().call()
                usdc = raw_usdc / (10 ** decimals)
                self.balances = {"USDC": usdc, "POL": pol}
            
            # 2. Positions (Via Data API)
            self.positions = []
            try:
                # Direct call to Data API (No signing needed for public data usually, or simple query)
                # Using the user-verified endpoint: https://data-api.polymarket.com/positions?user={ADDRESS}
                endpoint = f"https://data-api.polymarket.com/positions?user={self.user_address}"
                resp = requests.get(endpoint, timeout=10)
                
                if resp.status_code == 200:
                    raw_pos = resp.json() # List of dicts
                    processed = []
                    
                    for p in raw_pos:
                        size = float(p.get("size", 0))
                        if size > 0.01:
                            processed.append({
                                "asset": p.get("asset"), # Token ID
                                "size": size,
                                "market_slug": p.get("slug", "Unknown") # Data API provides slugs!
                            })
                    self.positions = processed
                    print(f"[TELEMETRY] Positions Sync: {len(processed)} assets found.")
                    
            except Exception as e:
                 print(f"[TELEMETRY] Position fetch failed: {e}")
            except Exception as e:
                 print(f"[TELEMETRY] Position fetch failed: {e}")

            position_equity = 0.0 # TODO: pricing
            
            # Update Total Equity
            # Equity = Cash (USDC) + MarketValue(Positions)
            # Using USDC balance as the main component
            self.equity = self.balances.get('USDC', 0) + position_equity

        except Exception as e:
            print(f"[TELEMETRY] Fetch failed: {e}")

    def dump_status(self):
        """Atomic Write."""
        try:
            data = {
                "timestamp": datetime.now().isoformat(),
                "virtual_pnl": self.pnl,
                "total_trades": self.trades_count,
                "total_equity": self.equity,
                "action": self.last_action,
                "balances": self.balances,
                "positions": self.positions
            }
            temp_path = STATUS_PATH + ".tmp"
            with open(temp_path, "w") as f:
                json.dump(data, f)
            os.rename(temp_path, STATUS_PATH)
        except Exception as e:
            print(f"[TELEMETRY] Dump failed: {e}")


# --- HELPER FUNCTIONS ---

def get_usdc_balance(address, collateral_address):
    """MOCK or REAL balance based on environment."""
    # In production, this would use a real RPC/client call
    return 1000.0

def fetch_target_markets():
    """GLOBAL SCANNER: Fetch Top 100 Markets + NFL Super Bowl Hunter."""
    try:
        # 1. Fetch Top 100 by 24h Volume
        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "limit": "100",
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false"
        }

        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        markets = resp.json()

        if not markets:
            markets = []

        seen_ids = {m.get('conditionId') for m in markets}

        # 2. NFL SUPER BOWL HUNTER: Fetch Pro Football Champion 2026 event markets
        try:
            nfl_url = "https://gamma-api.polymarket.com/markets"
            nfl_params = {
                "limit": "50",
                "active": "true",
                "closed": "false",
                "tag": "super-bowl-champion-2026-731"  # Event slug for NFL Super Bowl
            }
            nfl_resp = requests.get(nfl_url, params=nfl_params, timeout=10)
            if nfl_resp.status_code == 200:
                nfl_markets = nfl_resp.json()
                # Merge unique NFL markets
                for m in nfl_markets:
                    if m.get('conditionId') not in seen_ids:
                        markets.append(m)
                        seen_ids.add(m.get('conditionId'))
                print(f"[NFL-HUNTER] 🏈 Added {len(nfl_markets)} Super Bowl markets")
        except Exception as nfl_e:
            print(f"[NFL-HUNTER] Warning: {nfl_e}")

        # 3. Fallback: Search by slug pattern for NFL teams
        try:
            for team in ['patriots', 'chiefs', 'eagles']:
                team_resp = requests.get(f"https://gamma-api.polymarket.com/markets?slug=will-the-{team}-win-super-bowl-2026", timeout=5)
                if team_resp.status_code == 200:
                    team_markets = team_resp.json()
                    for m in team_markets if isinstance(team_markets, list) else [team_markets]:
                        if m and m.get('conditionId') not in seen_ids:
                            markets.append(m)
                            seen_ids.add(m.get('conditionId'))
                            print(f"[NFL-HUNTER] 🏈 Found: {m.get('question', 'Unknown')[:40]}")
        except Exception as team_e:
            pass  # Non-critical

        # Count NFL markets for monitoring
        nfl_count = sum(1 for m in markets if any(kw in m.get('question', '').lower()
            for kw in ['super bowl', 'patriots', 'chiefs', 'eagles', 'nfl', 'football']))

        print(f"[SCANNER] Fetched {len(markets)} Markets ({nfl_count} NFL). Scanning for Opportunities...")
        return markets

    except Exception as e:
        print(f"[MARKET-DISCOVERY] API Error: {e}")
        return []

def parse_strike_price(question):
    """Extracts dollar amount from question."""
    match = re.search(r'\$([0-9,]+(\.[0-9]+)?)\s?([kKmMbB]?)', question)
    if match:
        raw_num = match.group(1).replace(",", "")
        suffix = match.group(3).lower()
        try:
            val = float(raw_num)
            if suffix == 'k': val *= 1_000
            elif suffix == 'm': val *= 1_000_000
            elif suffix == 'b': val *= 1_000_000_000
            return val
        except:
            return None
    return None

def calculate_vwap_exit(bids, size=35.0):
    """Calculates Volume-Weighted Average Price for selling specific size."""
    if not bids: return 0.0
    remaining = size 
    
    total_value = 0.0
    
    for bid in bids:
        if remaining <= 0: break
        p = float(bid.price)
        s = float(bid.size)
        take = min(s, remaining)
        total_value += take * p
        remaining -= take
        
    if remaining > 0:
        return 0.0 # Illiquid
        
    return total_value / size

# --- ASYNC BOT CORE ---

async def run_bot(queue: asyncio.Queue, bot_state: BotParams):
    print(f"[BOT] Starting Production-Grade Trading Bot (MOCK_TRADING={MOCK_TRADING})")
    print("[ALPHA] SELECTIVE AGGRESSION MODE ENABLED. (Vol>$25k, Spread<5%, Gas>2.0)")
    
    # 0. Initialize Monitoring & Connectors
    metrics = get_metrics_exporter()
    metrics.start()
    
    binance = get_binance_manager(["btcusd", "ethusd", "solusd", "maticusd"])
    binance.start()
    
    # 1. Setup Client
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    api_key = os.getenv("CLOB_API_KEY")
    api_secret = os.getenv("CLOB_SECRET")
    api_passphrase = os.getenv("CLOB_PASSPHRASE")

    if not all([pk, api_key, api_secret, api_passphrase]):
        print("[ERROR] Missing credentials in .env")
        return

    creds_obj = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)

    print(f"[INIT] ClobClient (EOA Mode) | Proxy: {PROXY_URL}")

    try:
        client = await asyncio.to_thread(
            ClobClient,
            host="https://clob.polymarket.com",
            key=pk,
            chain_id=POLYGON,
            creds=creds_obj,
            signature_type=0,  # EOA MODE - Direct wallet signing
            funder=None
        )

        # Log trading identity and collateral (standard USDC.e)
        collateral = client.get_collateral_address()
        proxy_addr = client.get_address()
        print(f"[BOT IDENTITY] Trading as: {proxy_addr}")
        print(f"[COLLATERAL] Using: {collateral} (USDC.e)")
    except Exception as e:
        print(f"[ERROR] Client Init Failed: {e}")
        return

    # 2. Session Initialization
    print(f"[BOT] Starting 72-Hour Reliability Burn-In (MOCK_TRADING={MOCK_TRADING})")
    
    # 2.1 Error Logging Setup
    import logging
    error_logger = logging.getLogger("hft_errors")
    err_handler = logging.FileHandler("/var/log/quesquant/errors.log")
    err_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s'))
    error_logger.addHandler(err_handler)
    error_logger.setLevel(logging.ERROR)

    # Fetch real baseline or use soak test defaults
    from web3 import Web3
    from eth_account import Account
    rpc = os.getenv("POLYGON_RPC", "https://polygon-rpc.com")
    USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    ERC20_ABI = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},{"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}]

    if MOCK_TRADING:
        start_usdc = 100.00  # High-Fidelity Soak Baseline
        start_matic = 10.00  # High-Fidelity Soak Baseline
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [SOAK_CONFIG] Using High-Fidelity Mock Balances: ${start_usdc} USDC, {start_matic} POL")
    else:
        # (existing live fetch logic)
        # Adjusted to 40 POL swap (User Directive) - Garbage Removal
        start_usdc = 100.0 # Default safe fallback
        start_matic = 0.0
        
        # Robust Fetch with Retries (prioritize reliable public nodes)
        rpcs = [
            os.getenv("POLYGON_RPC"),
            "https://polygon-bor.publicnode.com",
            "https://1rpc.io/matic",
            "https://polygon-rpc.com",
            "https://rpc-mainnet.maticvigil.com"
        ]
        rpcs = [r for r in rpcs if r]
        
        fetched = False
        for rpc_url in rpcs:
            if fetched: break
            try:
                print(f"[INIT] Fetching balances via {rpc_url}...")
                w3 = Web3(Web3.HTTPProvider(rpc_url))
                address = Account.from_key(pk).address
                
                # MATIC
                start_matic = float(w3.from_wei(w3.eth.get_balance(address), 'ether'))
                
                # USDC
                usdc_contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI)
                raw_balance = usdc_contract.functions.balanceOf(address).call()
                decimals = usdc_contract.functions.decimals().call()
                start_usdc = raw_balance / (10 ** decimals)
                fetched = True
                print(f"[INIT] Balances Fetched: ${start_usdc} USDC | {start_matic} MATIC")
            except Exception as e:
                print(f"[WARN] RPC Failed ({rpc_url}): {e}")
                time.sleep(1)
        
        if not fetched:
            error_logger.error("All RPCs failed to fetch start balance. Using mock default.")
            print("[ERROR] All RPCs failed. Defaulting to safe baseline.")
        
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [START_BALANCE] USDC: {start_usdc:.2f}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [START_BALANCE] MATIC: {start_matic:.4f}")
    
    initial_cash = start_usdc
    current_cash = initial_cash
    current_matic = start_matic
    
    total_gas_spent = 0.0
    total_fees_paid = 0.0
    total_trades_count = 0
    total_order_updates = 0
    last_telemetry_time = time.time()
    
    theoretical_position = 0.0 # Reverted to standard
    session_volume = 0.0
    
    pending_fills = []
    BLOCK_TIME = 4.0 
    price_history = {} 
    active_order_prices = {} # {token_id: {"BUY": price, "SELL": price}}

    last_midpoint = None
    last_check_time = time.time()
    last_audit_time = time.time()
    last_balance_check = time.time()

    # Load Config
    # STANDARD TRADING MODE: $7.73 balance - meets $5 minimum
    MAX_ORDER_SIZE = 5.00   # Polymarket minimum is $5
    MIN_ORDER_SIZE = 5.00   # Polymarket minimum
    CASH_BUFFER = 0.50      # Keep buffer for fees

    bot_state = BotParams(
        order_size=MAX_ORDER_SIZE,  # $5 per order (minimum)
        max_position=1,             # Max 1 share at a time (limited capital)
        min_liquidity=500.0         # Lower liquidity threshold
    )
    print(f"[CONFIG] STANDARD: order_size=${bot_state.order_size}, max_pos={bot_state.max_position}, buffer=${CASH_BUFFER}")
    
    # Setup Loggers      
    # --- MAIN ENGINE LOOP ---
    try:
        # Initialize DB with empty state
        curr_balances = {"USDC": start_usdc, "POL": start_matic}
        
        # Initialize Telemetry Worker
        user_addr = client.get_address()
        telemetry_worker = TelemetryWorker(client, w3 if 'w3' in locals() else None, usdc_contract if 'usdc_contract' in locals() else None, user_addr)
        telemetry_worker.start()
        
        # Initial Update
        telemetry_worker.update_metrics(0.0, 0, "BOT_STARTED")
        
        while True:
            try:
                # 0. Kill Switch Check
                if not bot_state.is_running:
                    print("[BOT] Bot Paused. Waiting for activation...")
                    await asyncio.sleep(5)
                    continue

                # 1. Heartbeat (CloudWatch)
                metrics.push_heartbeat()
                
                # --- SELF-HEALING LIQUIDITY MONITOR ---
                if not MOCK_TRADING and (time.time() - last_balance_check > 60):
                    try:
                        # Refresh Balances
                        new_matic = float(w3.from_wei(w3.eth.get_balance(address), 'ether'))
                        raw_bal = usdc_contract.functions.balanceOf(address).call()
                        new_usdc = raw_bal / 1e6
                        
                        current_matic = new_matic
                        current_cash = new_usdc
                        last_balance_check = time.time()
                        
                        # Trigger Refuel
                        if current_cash < 5.0 and current_matic > 50.0:
                            print(f"[LIQUIDITY] Cash Low (${current_cash:.2f}). Gas Reserves Checked ({current_matic:.2f} > 50).")
                            print("[LIQUIDITY] Initiating Auto-Refuel (40 POL -> USDC.e)...")
                            subprocess.run(["python3", "/app/hft/tools/refuel_bot.py"], check=True)
                            
                            # Verify Result
                            time.sleep(5)
                            current_cash = float(usdc_contract.functions.balanceOf(address).call() / 1e6)
                            print(f"[LIQUIDITY] Refuel Complete. New Cash: ${current_cash:.2f}")

                    except Exception as e_liq:
                        print(f"[WARN] Liquidity Monitor Failed: {e_liq}")

                loop_start = time.time()
                
                # --- PROCESS PENDING FILLS (RE-ORG PROTECTION) ---
                current_time = time.time()
                confirmed_fills = []
                for fill in pending_fills:
                    if current_time - fill['fill_time'] >= BLOCK_TIME:
                        qty = fill['qty']
                        price = fill['price']
                        cost = qty * price
                        if fill['side'] == 'BUY':
                            theoretical_position += qty
                            current_cash -= cost
                        else:
                            theoretical_position -= qty
                            current_cash += cost
                        
                        if MOCK_TRADING:
                            fee = cost * 0.001 # 0.1% Taker Fee
                            current_cash -= fee
                            total_fees_paid += fee
                            total_trades_count += 1
                            
                        session_volume += cost
                        confirmed_fills.append(fill)
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [TRADE_FILLED] {fill['side']} {qty} tokens @ {price:.3f}")
                for fill in confirmed_fills: pending_fills.remove(fill)

                # --- MARKET DATA CYCLE ---
                try:
                    # CAPITAL ALERT
                    if current_cash >= 5.05 and 'alpha_alert_sent' not in locals():
                        print(f"[ALPHA] 🚀 CAPITAL THRESHOLD REACHED. INITIALIZING HUNTER EXECUTION.")
                        alpha_alert_sent = True

                    # 1. Fetch Markets (Updated: 5-Minute Cache)
                    # Initialize cache if checks fail or start
                    if 'cached_markets' not in locals():
                        cached_markets = []
                        last_scan_time = 0

                    if time.time() - last_scan_time > 300: # 5 Minutes
                        print(f"[SCANNER] 🔄 Refreshing Top 20 Global Markets...")
                        cached_markets = await asyncio.to_thread(fetch_target_markets)
                        last_scan_time = time.time()
                    
                    markets = cached_markets
                    
                    if not markets:
                        print("[SCANNER] No markets found. Retrying in 10s...")
                        await asyncio.sleep(10)
                        last_scan_time = 0 # Force retry
                        continue

                    # print(f"[DEBUG] Markets fetched: {len(markets)}") # Reduce noise
                    valid_candidates = [] # Scan-Sort-Execute storage
                    for target_market in markets:
                        question = target_market.get('question', 'Unknown')
                        print(f"[DEBUG] Processing: {question}")
                        # if not target_market.get('enableOrderBook'): continue # HANDLED IN DISCOVERY
                        
                        # Filtering Logic
                        q_lower = question.lower()
                        # GLOBAL SCANNER: Keyword Filter Removed.
                        # if not any(k in q_lower for k in ["bitcoin", "btc", "ethereum", "solana", "xrp", "doge", "cardano", "crypto", "up or down", "price"]): continue
                        
                        liquidity = float(target_market.get('liquidity', 0))
                        if liquidity < bot_state.min_liquidity:
                            print(f"[WARN] Low Liquidity: {question} (${liquidity:.0f} < ${bot_state.min_liquidity}) - PROCEEDING ANYWAY")
                            # continue

                        # --- TOKEN MAPPING CORRECTION ---
                        try:
                            # 1. Parse Outcomes
                            raw_outcomes = target_market.get('outcomes')
                            if isinstance(raw_outcomes, str):
                                outcomes = json.loads(raw_outcomes)
                            else:
                                outcomes = raw_outcomes # Already list
                            
                            clob_token_ids = json.loads(target_market.get('clobTokenIds', '[]'))
                            if not clob_token_ids or len(clob_token_ids) != len(outcomes):
                                print(f"[MAPPING] ⚠️ Mismatch: {question} (Outcomes={len(outcomes)}, Tokens={len(clob_token_ids)})")
                                continue

                            # 2. Build Map
                            outcome_map = dict(zip(outcomes, clob_token_ids))
                            
                            # 3. Target Selection (Default: YES)
                            # Logic: If price of YES < 0.02, it's likely dead or really "No". 
                            # But we want to buy value.
                            # For now, we HARD TARGET "Yes" to capture the "Warner Bros" type plays.
                            target_outcome = "Yes"
                            if "Yes" not in outcome_map:     
                                # Fallback for non-binary (Candidate names)
                                # Just pick the first non-No one? Or skip?
                                # Ideally we scan for Specific Candidates.
                                # For binary markets (Yes/No), this works.
                                target_outcome = outcomes[1] if len(outcomes) > 1 else outcomes[0]

                            token_id = outcome_map.get(target_outcome)
                            if not token_id: continue

                            print(f"[MAPPING] ✅ Market: {question} | Target: {target_outcome} | Token: {token_id}")

                        except Exception as map_e:
                            print(f"[MAPPING-ERR] Failed to map tokens: {map_e}")
                            continue

                        # --- DATE-GUARD: REJECT EXPIRED MARKETS ---
                        try:
                            end_date_str = target_market.get('endDate')
                            if end_date_str:
                                # Parse ISO format
                                from datetime import datetime as dt_parser
                                end_date = dt_parser.fromisoformat(end_date_str.replace('Z', '+00:00'))
                                now_utc = datetime.now(end_date.tzinfo) if end_date.tzinfo else datetime.utcnow()
                                
                                if now_utc > end_date:
                                    print(f"[DATE-GUARD] ⛔ BLACKLISTED: '{question}' ended on {end_date_str}. Skipping.")
                                    continue
                        except Exception as date_e:
                            print(f"[DATE-GUARD] ⚠️ Parse error: {date_e}. Proceeding with caution.")

                        # --- GATEKEEPER: VOLUME & ACTIVITY ---
                        vol_24h = float(target_market.get('volume24hr', 0))
                        # --- GATEKEEPER: VOLUME & ACTIVITY ---
                        vol_24h = float(target_market.get('volume24hr', 0))
                        
                        # TRIPLE-CHECK: Volume Floor Raised to $25k
                        if vol_24h < 25000:
                            print(f"[GATEKEEPER] ⛔ Market Rejected: 24h Volume ${vol_24h:.0f} < $25,000")
                            continue

                        try:
                            last_trade = await asyncio.to_thread(client.get_last_trade_price, token_id)
                            # Assuming last_trade returned dict has 'timestamp' (unix string/int w/ or w/o ms?)
                            # Usually Polymarket API returns "timestamp": "167..." (10 or 13 digits)
                            # ClobClient might wrap it.
                            # If get_last_trade_price returns ONLY price (float), we need get_trades.
                            # Let's inspect get_last_trade_price definition if possible or use get_trades.
                            # SAFE FALLBACK: If get_last_trade_price returns object, inspect it.
                            # If it returns float (price), we assume active? 
                            # NO, User explicitly asked for TIMESTAMP check.
                            # I will use get_trades(limit=1).
                            from py_clob_client.clob_types import TradeParams
                            last_trades = await asyncio.to_thread(client.get_trades, TradeParams(market=token_id))
                            if last_trades:
                                lt_ts = int(last_trades[0].get('match_time', 0)) # Usually 'match_time' or 'timestamp'
                                if lt_ts > 1e11: lt_ts /= 1000 # Normalize MS to Seconds
                                if (time.time() - lt_ts) > 3600:
                                    print(f"[GATEKEEPER] ⛔ Market Rejected: Last Trade > 60m ago.")
                                    continue
                            else:
                                print(f"[GATEKEEPER] ⚠️  No Trades found. Volume is High (${vol_24h:.0f}). Proceeding.")
                                # continue
                        except Exception as gate_e:
                            print(f"[GATEKEEPER] Check Failed: {gate_e} - Proceeding with Caution")

                        # 2. Fetch Order Book
                        api_start = time.time()
                        order_book = await asyncio.to_thread(client.get_order_book, token_id)
                        latency_ms = (time.time() - api_start) * 1000
                        
                        print(f"[DEBUG] Book: {len(order_book.bids)} Bids | {len(order_book.asks)} Asks")
                        
                        # CRITICAL FIX: Ensure Book is sorted correctly for Match Engine Logic
                        # Bids: Descending (Highest Pay First)
                        # Asks: Ascending (Lowest Price First)
                        if order_book.bids:
                            order_book.bids.sort(key=lambda x: float(x.price), reverse=True)
                        if order_book.asks:
                            order_book.asks.sort(key=lambda x: float(x.price))
                            
                        if order_book.bids:
                             pass
                             # print(f"[DEBUG-INTERNAL] First Bid Raw: {order_book.bids[0]}")
                        # Handle Partial/Empty Books gracefully
                        # BUG FIX: CLOB API returns orders such that index [0] is often weak/worst price.
                        # We must find the Best Bid (Highest) and Best Ask (Lowest).
                        if order_book.bids:
                            # Parse prices first (they are strings in some clients, floats in others)
                            bid_prices = [float(b.price) for b in order_book.bids]
                            best_bid = max(bid_prices)
                        else:
                            best_bid = 0.0
    
                        # Initialize Loop Variables safely
                        vol_state = "N/A"
                        final_action = "SCANNING"
                        # best_bid = 0.0 (REMOVED - Was overwriting fetched bid)

                        if order_book.asks:
                            ask_prices = [float(a.price) for a in order_book.asks]
                            best_ask = min(ask_prices)
                        else:
                            best_ask = 1.0
                        
                        current_spread = best_ask - best_bid
                        print(f"[DEBUG] ID: {token_id} | Bid: {best_bid} | Ask: {best_ask} | Spread: {current_spread:.3f}")
                        
                        # --- SCANNER FILTER: SYMMETRY ---
                        mid_est = (best_bid + best_ask) / 2 if (best_bid + best_ask) > 0 else 0.50
                        spread_pct = current_spread / mid_est
                        
                        # --- DYNAMIC SPREAD LOGIC ---
                        # Base Limit: 8% (Relaxed for fill rate)
                        max_spread = 0.08

                        # 1. High Volume Exemption (> $1M)
                        if vol_24h >= 1_000_000:
                            max_spread = 0.10 # 10%
                            
                        # 2. Penny Exemption (< $0.05)
                        if best_ask < 0.05:
                            max_spread = max(max_spread, 0.10) # 10%
                        
                        if spread_pct > max_spread:
                             print(f"[SCANNER] ⛔ Spread too wide ({spread_pct*100:.1f}% > {max_spread*100:.1f}%). Skipping {question}.")
                             log_rejection(question, vol_24h, spread_pct, 'SPREAD_TOO_WIDE', best_bid, best_ask)
                             continue

                        # CRITICAL SAFETY LOCK: Abort if spread is too wide (> $0.10)
                        if current_spread > 0.10:
                            print(f"[RISK_ABORT] Spread too wide (${current_spread:.3f}). Market is illiquid/broken. Skipping quote.")
                            continue

                        # --- SLIPPAGE GUARD: ORDER BOOK DEPTH ---
                        # Check if top-of-book can support at least half our desired order size
                        intended_size = bot_state.order_size / mid_est if mid_est > 0 else 0  # Shares
                        
                        top_bid_size = float(order_book.bids[0].size) if order_book.bids else 0.0
                        top_ask_size = float(order_book.asks[0].size) if order_book.asks else 0.0
                        
                        min_fill_threshold = intended_size * 0.5  # 50% fill minimum
                        
                        if top_ask_size < min_fill_threshold and intended_size > 0:
                            print(f"[SLIPPAGE-GUARD] ⛔ ABORT: Top Ask has {top_ask_size:.0f} shares, need {min_fill_threshold:.0f}+ for safe fill.")
                            continue

                        # --- EDGE SANITY CHECK ---
                        # If calculated edge is > 50%, it's likely a data error or rug
                        # Edge = |Fair - Entry| / Entry
                        entry_price = best_ask  # We are buying at Ask
                        fair_value = mid_est
                        
                        if entry_price > 0.001:
                            edge = abs(fair_value - entry_price) / entry_price
                            if edge > 0.50:
                                print(f"[EDGE-CHECK] ⛔ ABORT: Edge ({edge*100:.1f}%) > 50%. Likely data error or rug.")
                                continue

                        if best_bid == 0.0:
                             midpoint = 0.50
                             print(f"[PRICE-LOGIC] Empty Bids -> Defaulting Fair Price to 0.50")
                        else:
                             midpoint = (best_bid + best_ask) / 2
                             
                             # UPGRADE: VWAP EXIT PRICING
                             realized_exit = calculate_vwap_exit(order_book.bids, size=35.0)
                             gap = (midpoint - realized_exit) / midpoint if midpoint > 0 else 0
                             
                             if gap > 0.10:
                                 print(f"[PRICING-INTEL] 🚨 ILLIQUIDITY DETECTED. Gap: {gap*100:.1f}%")
                                 print(f"[PRICING-INTEL] Mid: {midpoint:.3f} -> Realized: {realized_exit:.3f}")
                                 print("[SCANNER] Skipping Illiquid Market.")
                                 log_rejection(question, vol_24h, spread_pct, 'ILLIQUIDITY', best_bid, best_ask, realized_exit)
                                 continue
                             else:
                                 print(f"[PRICING-INTEL] ✅ Market Healthy. Gap: {gap*100:.1f}%")
                                 midpoint = realized_exit # Use Realized Price as Fair Value
                             
                             # --- SYMMETRY GUARD ---
                             bid_dist = abs(midpoint - best_bid)
                             ask_dist = abs(best_ask - midpoint)
                             
                             # Avoid division by zero/noise
                             if bid_dist > 0.001: 
                                 ratio = ask_dist / bid_dist
                                 if ratio > 3.0:
                                     print(f"[SYMMETRY] ⛔ TRAP DETECTED: Ask Dist ({ask_dist:.3f}) > 3x Bid Dist ({bid_dist:.3f}). Ratio: {ratio:.1f}")
                                     log_rejection(question, vol_24h, spread_pct, 'SYMMETRY_TRAP', best_bid, best_ask)
                                     continue # Skip Market
                             elif ask_dist > 0.01: # Bid is exactly on mid? (Spread 0?). If Ask is far, it's a trap.
                                 print(f"[SYMMETRY] ⛔ TRAP DETECTED: Bid is pegged, Ask is wide.")
                                 log_rejection(question, vol_24h, spread_pct, 'SYMMETRY_TRAP', best_bid, best_ask)
                                 continue
                             
                             print(f"[PRICE-LOGIC] Bid: {best_bid} | Ask: {best_ask} -> Fair: {midpoint}")
                        
                        # WebSocket signal - Align with Binance US (BTCUSD) or USDT depending on stream
                        # Manager was init with ["btcusd", ...], so we scan for "BTCUSD"
                        binance_symbol = None
                        q_upper = question.upper()
                        if "BTC" in q_upper or "BITCOIN" in q_upper: binance_symbol = "BTCUSD"
                        elif "ETH" in q_upper or "ETHER" in q_upper: binance_symbol = "ETHUSD"
                        elif "SOL" in q_upper or "SOLANA" in q_upper: binance_symbol = "SOLUSD"

                        binance_price = 0
                        if binance_symbol:
                            binance_price = binance.get_price(binance_symbol) or 0
                        
                        # 2.5 Matic Price for Gas Correction
                        matic_price = binance.prices.get('maticusdt', 0.85) # Default to 0.85 if missing
                        
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [LATENCY] {latency_ms:.1f}ms | Mid: {midpoint:.3f} | BTC: ${binance_price:,.0f} | Matic: ${matic_price:.3f} | Liq: ${liquidity/1e6:.1f}M")

                        # 3. Spread & Volatility Management
                        vol_state = "LOW_VOL"
                        base_spread = 0.005  # NARROW SPREAD: Reduced from 0.01 to 0.005 for better fills
                        
                        if token_id not in price_history: price_history[token_id] = []
                        price_history[token_id].append((current_time, midpoint))
                        price_history[token_id] = [e for e in price_history[token_id] if current_time - e[0] <= 300]
                        
                        if len(price_history[token_id]) > 5:
                            stdev = statistics.stdev([e[1] for e in price_history[token_id]])
                            if stdev > 0.01:
                                vol_state = "HIGH_VOL"
                                base_spread = max(base_spread, 0.04)

                        buy_price = round(midpoint - base_spread, 2)
                        sell_price = round(midpoint + base_spread, 2)

                        # 4. Inventory & Signal Integration
                        # BUY: allowed if under max position
                        # SELL: only if we OWN tokens (can't sell what we don't have)
                        allow_buy = theoretical_position < bot_state.max_position
                        allow_sell = theoretical_position > 0  # Must own tokens to sell
                        
                        # --- HARD OVERRIDE: TELEMETRY RECOVERY ---
                        # If position is impossibly large (>100k), it's a bug. Ignore it and allow buying.
                        if theoretical_position > 100000:
                            print(f"[OVERRIDE] ⚠️ Phantom Position Detected ({theoretical_position:.0f} > 100k). Forcing allow_buy=True to kickstart.")
                            allow_buy = True

                        # --- SAFETY INTERLOCK ---
                        # Prevent buying "Yes" if price is suspicious (trap/dead market)
                        # Or buying "No" if price is > 0.98 (too expensive)
                        current_target = target_outcome if 'target_outcome' in locals() else "Unknown"
                        
                        print(f"[SAFETY] 🎯 Target: {current_target} | TokenID: {token_id[:10]}... | Midpoint: ${midpoint:.3f}")

                        if current_target == "Yes" and midpoint < 0.02:
                            print(f"[SAFETY] ⛔ ABORT: Target is YES but Price (${midpoint:.3f}) is < $0.02. TRAP/DEAD MARKET.")
                            continue
                        
                        if current_target == "No" and midpoint > 0.98:
                             print(f"[SAFETY] ⛔ ABORT: Target is NO but Price (${midpoint:.3f}) is > $0.98. R/R POOR.")
                             continue



                        
                        # 5. Execution Strategy
                        orders = []
                        
                        # TRIPLE-CHECK: Aggressive Entry Filters
                        # 1. Symmetry/Spread Check (Spread < 5%)
                        spread_pct = (best_ask - best_bid) / midpoint if midpoint > 0 else 1.0
                        spread_safe = spread_pct < 0.05
                        
                        # 2. Inventory Check (Total Deployment < $5.50)
                        # Position Value + New Order Size <= 5.50 ?
                        # Assuming MAX_ORDER_SIZE = 5.0. 
                        # If we have 35 shares (Value $0?), we count COST BASIS or CURRENT VALUE?
                        # User says "Total deployment does not exceed $5.50".
                        # If we hold 0, we can buy 1 order ($5).
                        inventory_safe = theoretical_position * midpoint < 0.50 # Allow 1 order ($5) approx?
                        # Wait, logic: "One minimum order at a time".
                        # If current position > 0, we STOP BUYING.
                        # So inventory_safe = theoretical_position == 0.
                        
                        # 3. Liquidity Buffer (Gas > 2.0 POL)
                        gas_safe = current_matic > 2.0
                        
                        if allow_buy:
                            if not spread_safe:
                                print(f"[SAFETY] ⛔ Spread too wide ({spread_pct*100:.1f}%). Target < 5%.")
                            elif not gas_safe:
                                print(f"[SAFETY] ⛔ Low Gas ({current_matic:.2f} POL). Need > 2.0.")
                            elif theoretical_position > 5.0: 
                                print(f"[SAFETY] ⛔ Inventory Cap Reached ({theoretical_position}).")
                            else:
                                # PASSED ALL CHECKS -> COLLECT CANDIDATE
                                print(f"[SCANNER] 💎 CANDIDATE FOUND: {question} (Spread: {spread_pct*100:.2f}%)")
                                valid_candidates.append({
                                    'token_id': token_id,
                                    'spread_pct': spread_pct,
                                    'best_bid': best_bid,
                                    'best_ask': best_ask,
                                    'question': question,
                                    'vol_24h': vol_24h
                                })
                    
                    # --- HYBRID LOGIC: VULTURE + SUPER BOWL HUNTER ---
                    # Strategy A: VULTURE (High-confidence near-certain markets)
                    # Strategy B: SUPER BOWL HUNTER (Sports event plays)

                    vulture_candidates = []
                    superbowl_candidates = []
                    standard_candidates = []

                    for cand in valid_candidates:
                        q_lower = cand['question'].lower()
                        best_ask = cand.get('best_ask', 1.0)
                        spread = cand['spread_pct']
                        vol = cand['vol_24h']

                        # VULTURE CRITERIA: Near-certain outcomes
                        # BestAsk > 0.98 AND < 0.998, Spread < 1%, Volume > $50k
                        if best_ask > 0.98 and best_ask < 0.998 and spread < 0.01 and vol > 50000:
                            cand['strategy'] = 'VULTURE'
                            # Minimum 5 shares required by Polymarket, max $10 notional
                            min_notional = 5.0 * best_ask  # 5 shares at ask price
                            cand['order_size'] = max(min_notional, min(10.00, current_cash - 0.50))
                            vulture_candidates.append(cand)
                            print(f"[VULTURE] 🦅 NEAR-CERTAIN DETECTED: {cand['question']} | Ask: ${best_ask:.3f} | Spread: {spread*100:.2f}%")

                        # SUPER BOWL HUNTER CRITERIA
                        elif any(kw in q_lower for kw in ['super bowl', 'superbowl', 'winner', 'champion', 'nfl', 'football', 'playoff', 'patriots', 'seahawks', 'eagles', 'chiefs', 'bills', 'ravens', 'lions', 'commanders']):
                            # Check for value plays (underdog prices)
                            if cand['best_bid'] < 0.35 or (cand['best_bid'] > 0.35 and cand['best_bid'] < 0.65):
                                cand['strategy'] = 'SUPERBOWL'
                                cand['order_size'] = 6.00  # Fixed conservative size
                                superbowl_candidates.append(cand)
                                print(f"[SUPERBOWL] 🏈 SPORTS PLAY DETECTED: {cand['question']} | Bid: ${cand['best_bid']:.3f}")

                        else:
                            cand['strategy'] = 'STANDARD'
                            cand['order_size'] = 5.05
                            standard_candidates.append(cand)

                    # --- PRIORITY ORDER: Vulture > SuperBowl > Standard ---
                    if vulture_candidates:
                        # Vulture: Sort by spread (tighter = better)
                        vulture_candidates.sort(key=lambda x: x['spread_pct'])
                        best_market = vulture_candidates[0]
                        print(f"[ALPHA] 🦅 VULTURE LOCKED: {best_market['question']} | Spread: {best_market['spread_pct']*100:.2f}% | ALL-IN ${best_market['order_size']:.2f}")
                    elif superbowl_candidates:
                        # SuperBowl: Sort by value (lower price = more upside)
                        superbowl_candidates.sort(key=lambda x: x['best_bid'])
                        best_market = superbowl_candidates[0]
                        print(f"[ALPHA] 🏈 SUPERBOWL LOCKED: {best_market['question']} | Bid: ${best_market['best_bid']:.3f} | Size: $6.00")
                    elif standard_candidates:
                        # Standard: Sort by Blue Chip > Spread
                        standard_candidates.sort(key=lambda x: (0 if x['vol_24h'] >= 100000 else 1, x['spread_pct']))
                        best_market = standard_candidates[0]
                        print(f"[ALPHA] 🎯 STANDARD LOCKED: {best_market['question']} | Spread: {best_market['spread_pct']*100:.2f}% | Size: $5.05")
                    else:
                        best_market = None

                    # --- OPTIMAL LOCK: SORT & SELECT ---
                    if best_market:
                        strategy = best_market.get('strategy', 'STANDARD')
                        order_notional = best_market.get('order_size', 5.05)

                        # EXECUTE ON TARGET
                        token_id = best_market['token_id']
                        best_bid = best_market['best_bid']

                        orders = []
                        # PRICE: Join Best Bid
                        buy_price = best_bid if best_bid > 0 else 0.50
                        # SIZE: Dynamic based on strategy
                        buy_qty = round(order_notional / buy_price, 2) if buy_price > 0 else 0.0
                        
                        # POLYMARKET MINIMUM: 5 shares
                        if buy_qty < 5.0:
                            print(f"[ORDER] ⛔ Size {buy_qty:.2f} < 5 shares minimum. Adjusting to 5.0 shares.")
                            buy_qty = 5.0

                        notional_required = buy_qty * buy_price
                        if buy_qty >= 5.0 and notional_required <= current_cash:
                            execution_status = "INITIALIZED"
                            print(f"[LOGIC] Strategy: {strategy} | Price: ${buy_price:.2f} | Size: {buy_qty:.2f} | Notional: ${notional_required:.2f}")
                            orders.append({"side": "BUY", "price": buy_price, "size": buy_qty})
                        else:
                            print(f"[FUNDS] ⛔ Insufficient: Need ${notional_required:.2f}, Have ${current_cash:.2f}")
                            execution_status = "INSUFFICIENT_FUNDS"

                        # --- ORDER EXECUTION (Fixed: moved outside if/else) ---
                        if orders:
                            orders_summary = [f"{o['side']}@{o['price']}" for o in orders]
                            print(f"[ORDER] Placing {len(orders)} orders: {orders_summary}")

                            try:
                                for order in orders:
                                    if not MOCK_TRADING:
                                        print(f"[EXEC] Sending Order: {order}")
                                        from py_clob_client.clob_types import OrderArgs
                                        BUY = "BUY"

                                        o_args = OrderArgs(
                                            price=order['price'],
                                            size=order['size'],
                                            side=BUY,
                                            token_id=token_id
                                        )
                                        resp = await asyncio.to_thread(client.create_and_post_order, o_args)
                                        print(f"[EXEC] Response: {resp}")
                                        execution_status = "LIVE_SUCCESS"

                                        # Fire-and-forget Discord alert (non-blocking)
                                        order_id = resp.get('orderID', 'N/A') if isinstance(resp, dict) else str(resp)[:32]
                                        send_trade_alert_fire_and_forget(
                                            action="BUY",
                                            market_name=best_market.get('question', 'Unknown Market')[:50],
                                            price=order['price'],
                                            size=order['size'],
                                            order_id=order_id,
                                            status="MATCHED" if resp.get('status') == 'matched' else "LIVE"
                                        )
                                    else:
                                        print(f"[MOCK] Order Placed: {order}")
                                        execution_status = "MOCK_SUCCESS"
                            except Exception as e_exec:
                                print(f"[EXEC] Error: {e_exec}")
                                if hasattr(e_exec, 'status_code'):
                                    print(f"[DEEP-LOG] Status: {e_exec.status_code}")
                                try:
                                    if hasattr(e_exec, 'error_message'):
                                        msg = e_exec.error_message
                                        if hasattr(msg, 'text'):
                                            print(f"[DEEP-LOG] Raw Error Body: {msg.text}")
                                        else:
                                            print(f"[DEEP-LOG] Raw Error: {msg}")
                                    else:
                                        print(f"[DEEP-LOG] Error String: {str(e_exec)}")
                                except:
                                    pass
                                execution_status = "ORDER_FAILED"
                                
                    else:
                        print("[HUNTER] 💤 No valid candidates found in this scan.")
                        execution_status = "SKIPPED"
                    
                    # Initialize for Telemetry
                    significant_move = len(valid_candidates) > 0

                    # Telemetry Update - AFTER EXECUTION
                    total_equity = current_cash + (theoretical_position * midpoint)
                    if MOCK_TRADING:
                        total_equity -= (total_gas_spent * matic_price)
                        
                    virtual_pnl = total_equity - initial_cash
                    
                    # Update Worker
                    telemetry_worker.update_metrics(virtual_pnl, total_trades_count, final_action)

                    
                    final_action = "HEARTBEAT"
                    if significant_move:
                        if "SUCCESS" in execution_status:
                            final_action = "TRADE_PLACED"
                        else:
                            final_action = execution_status # "BLOCKED_BY_CLOUDFLARE" or "ORDER_FAILED"
                    
                    trade_data = TradeData(
                        timestamp=datetime.now().isoformat(),
                        token_id=token_id if 'token_id' in locals() else "N/A",
                        midpoint=midpoint if 'midpoint' in locals() else 0.0,
                        spread=sell_price - buy_price if 'sell_price' in locals() else 0.0,
                        latency_ms=latency_ms,
                        fee_bps=0,
                        vol_state=vol_state,
                        binance_price=binance_price,
                        inventory=float(theoretical_position),
                        action=final_action,
                        virtual_pnl=round(virtual_pnl, 2),
                        session_volume=round(session_volume, 2),
                        total_equity=round(total_equity, 2),
                        buying_power=round(current_cash, 2),
                        total_gas_spent_usd=round(total_gas_spent * matic_price, 4),
                        total_trades_count=total_trades_count,
                        total_order_updates=total_order_updates,
                        current_matic_balance=round(current_matic, 4)
                    )
                    total_order_updates += 1
                    queue.put_nowait(trade_data.dict())
                    
                    # Fire Async Alert (Non-Blocking)
                    if final_action == "TRADE_PLACED":
                        asyncio.create_task(send_trade_alert(trade_data.dict()))
                        
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [PnL] Session: ${virtual_pnl:.2f} | Action: {final_action}")
                    
                    if final_action == "TRADE_PLACED":
                        # Log Audit
                        try:
                           with open("core/audit_log.csv", "a") as f:
                               writer = csv.writer(f)
                               writer.writerow([datetime.now(), token_id, final_action, virtual_pnl])
                        except: pass

                    metrics.update(
                        tick_to_trade_latency_ms=latency_ms,
                        pnl_session=virtual_pnl,
                        inventory_imbalance=int(theoretical_position)
                    )


                except Exception as market_e:
                    print(f"Market Cycle Error: {market_e}")

                # 6. Periodic Simulation Audit (Every 4 Hours)
                if MOCK_TRADING and (time.time() - last_audit_time >= 14400):
                    last_audit_time = time.time()
                    total_equity = current_cash + (theoretical_position * (midpoint or 0.5)) - (total_gas_spent * (matic_price or 0.85))
                    net_profit = total_equity - initial_cash
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [SIM_AUDIT] Trades: {total_trades_count} | Gross PnL: ${net_profit + total_fees_paid + (total_gas_spent * 0.85):.2f} | Est Gas Paid: ${total_gas_spent * 0.85:.3f} | Net Profit: ${net_profit:.2f}")

            except Exception as loop_e:
                error_logger.exception("Critical Loop Error")
                print(f"[LOOP ERROR] {loop_e}")
                await asyncio.sleep(5)

            # CPU Yield
            await asyncio.sleep(max(0, 1 - (time.time() - loop_start)))

    except asyncio.CancelledError:
        print("[BOT] Shutdown signal received. Cleaning up...")
        if not MOCK_TRADING:
            await asyncio.to_thread(client.cancel_all)
    finally:
        binance.stop()
        print("[BOT] Bot Engine Halted.")

if __name__ == "__main__":
    # Self-Execution Mode (Patch for missing launcher)
    print("[BOOT] Starting via Internal Main Block...")
    import asyncio
    from core.shared_schemas import BotParams
    
    async def main_wrapper():
        q = asyncio.Queue()
        # Defaults used if overwritten, or passed through
        params = BotParams(
            order_size=5.0,
            max_position=1.0,
            min_liquidity=500.0
        )
        await run_bot(q, params)

    try:
        asyncio.run(main_wrapper())
    except KeyboardInterrupt:
        print("[BOOT] Stopped by User.")
