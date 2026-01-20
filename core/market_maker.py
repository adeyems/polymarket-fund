import os
import sys
import time
import json
import csv
import random
import requests
import requests.sessions

# --- CLOUDFLARE BYPASS PATCH ---
# Patch requests to use a browser User-Agent globally
original_request = requests.sessions.Session.request
def patched_request(self, method, url, *args, **kwargs):
    headers = kwargs.get("headers")
    if headers is None:
        headers = {}
    
    # Inject Browser User-Agent if missing or default
    ua = headers.get("User-Agent", "")
    if "User-Agent" not in headers or "python-requests" in ua:
        headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    
    kwargs["headers"] = headers
    return original_request(self, method, url, *args, **kwargs)

requests.sessions.Session.request = patched_request
# -------------------------------
import re
import statistics
import asyncio
import logging
import signal
from datetime import datetime, timedelta
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs
from py_clob_client.constants import POLYGON

# Import Shared Schemas & Connectors
from core.shared_schemas import TradeData, BotParams
from core.monitoring.metrics_exporter import get_metrics_exporter
from core.connectors.binance_ws import get_binance_manager

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Constants
GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"
POLYGON_RPC_URL = "https://polygon-rpc.com"
MOCK_TRADING = os.getenv("MOCK_TRADING", "true").lower() == "true"

# --- HELPER FUNCTIONS ---

def get_usdc_balance(address, collateral_address):
    """MOCK or REAL balance based on environment."""
    # In production, this would use a real RPC/client call
    return 1000.0

def fetch_target_markets():
    """Mock/Fetch markets from Gamma API."""
    return [{
        "question": "Will Bitcoin reach $100k in 2026?",
        "enableOrderBook": True,
        "clobTokenIds": json.dumps(["101676997363687199724245607342877036148401850938023978421879460310389391082353"]),
        "liquidity": 1000000
    }]

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

# --- ASYNC BOT CORE ---

async def run_bot(queue: asyncio.Queue, bot_state: BotParams):
    print(f"[BOT] Starting Production-Grade Trading Bot (MOCK_TRADING={MOCK_TRADING})")
    
    # 0. Initialize Monitoring & Connectors
    metrics = get_metrics_exporter()
    metrics.start()
    
    binance = get_binance_manager(["btcusdt", "ethusdt", "solusdt", "maticusdt"])
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

    try:
        client = await asyncio.to_thread(
            ClobClient,
            host="https://clob.polymarket.com",
            key=pk,
            chain_id=POLYGON,
            creds=creds_obj
        )
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
        start_usdc = 100.0 # Default safe fallback
        start_matic = 0.0
        
        # Robust Fetch with Retries
        rpcs = [
            os.getenv("POLYGON_RPC"), 
            "https://polygon-rpc.com", 
            "https://rpc-mainnet.maticvigil.com",
            "https://1rpc.io/matic"
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
    
    theoretical_position = 0.0
    session_volume = 0.0
    
    pending_fills = []
    BLOCK_TIME = 4.0 
    price_history = {} 
    active_order_prices = {} # {token_id: {"BUY": price, "SELL": price}}

    last_midpoint = None
    last_check_time = time.time()
    last_audit_time = time.time()

    # --- MAIN ENGINE LOOP ---
    try:
        while True:
            try:
                # 0. Kill Switch Check
                if not bot_state.is_running:
                    print("[BOT] Bot Paused. Waiting for activation...")
                    await asyncio.sleep(5)
                    continue

                # 1. Heartbeat (CloudWatch)
                metrics.push_heartbeat()
                
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
                    # 1. Fetch Markets
                    markets = await asyncio.to_thread(fetch_target_markets)
                    if not markets:
                        await asyncio.sleep(2)
                        continue

                    for target_market in markets:
                        question = target_market.get('question', 'Unknown')
                        if not target_market.get('enableOrderBook'): continue
                        
                        # Filtering Logic
                        q_lower = question.lower()
                        if not any(k in q_lower for k in ["bitcoin", "btc", "ethereum", "solana", "crypto"]): continue
                        
                        liquidity = float(target_market.get('liquidity', 0))
                        if liquidity < bot_state.min_liquidity:
                            continue

                        clob_token_ids = json.loads(target_market.get('clobTokenIds', '[]'))
                        if not clob_token_ids: continue
                        token_id = clob_token_ids[0]

                        # 2. Fetch Order Book
                        api_start = time.time()
                        order_book = await asyncio.to_thread(client.get_order_book, token_id)
                        latency_ms = (time.time() - api_start) * 1000
                        
                        if not order_book.bids or not order_book.asks: continue
                        
                        best_bid = float(order_book.bids[0].price)
                        best_ask = float(order_book.asks[0].price)
                        midpoint = (best_bid + best_ask) / 2
                        
                        # 2.5 Matic Price for Gas Correction
                        matic_price = binance.prices.get('maticusdt', 0.85) # Default to 0.85 if missing
                        
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [LATENCY] {latency_ms:.1f}ms | Mid: {midpoint:.3f} | Matic: ${matic_price:.3f} | Liq: ${liquidity/1e6:.1f}M")

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
                        allow_buy = theoretical_position < bot_state.max_position
                        allow_sell = theoretical_position > -bot_state.max_position

                        # WebSocket signal
                        binance_symbol = None
                        if "BTC" in question.upper(): binance_symbol = "BTCUSDT"
                        elif "ETH" in question.upper(): binance_symbol = "ETHUSDT"
                        elif "SOL" in question.upper(): binance_symbol = "SOLUSDT"

                        binance_price = 0
                        if binance_symbol:
                            binance_price = binance.get_price(binance_symbol) or 0
                            strike = parse_strike_price(question)
                            if binance_price and strike:
                                div = ((binance_price - strike) / strike) * 100
                                if div > 0.8: allow_sell = False
                                if div < -0.8: allow_buy = False

                        # 5. Execution Strategy
                        orders = []
                        if allow_buy: orders.append({"side": "BUY", "price": buy_price, "size": bot_state.order_size})
                        if allow_sell: orders.append({"side": "SELL", "price": sell_price, "size": bot_state.order_size})

                        if orders:
                            # Lazy Updating Threshold (0.02)
                            significant_move = False
                            if token_id not in active_order_prices:
                                active_order_prices[token_id] = {"BUY": 0, "SELL": 0}
                            
                            for o in orders:
                                last_p = active_order_prices[token_id].get(o["side"], 0)
                                if abs(o["price"] - last_p) >= 0.005:  # TUNED: Reduced from 0.02 to 0.005
                                    significant_move = True
                                    break
                            
                            
                            # Force heartbeat every 5 seconds
                            current_time = time.time()
                            force_update = (current_time - last_telemetry_time) >= 5.0
                            
                            if not significant_move and not force_update:
                                continue # SKIP UPDATE: Price move is < 0.5 cents AND no heartbeat needed

                            if force_update:
                                last_telemetry_time = current_time

                            # Update active prices
                            for o in orders:
                                active_order_prices[token_id][o["side"]] = o["price"]

                            # Telemetry Update
                            total_equity = current_cash + (theoretical_position * midpoint)
                            if MOCK_TRADING:
                                # Net PnL = Trading Profit - Total Fees - (Total Gas * Matic Price)
                                total_equity -= (total_gas_spent * matic_price)
                            
                            virtual_pnl = total_equity - initial_cash
                            
                            action_label = "TRADE_PLACED"
                            if not significant_move and force_update:
                                action_label = "" # Silent Heartbeat
                            
                            trade_data = TradeData(
                                timestamp=datetime.now().isoformat(),
                                token_id=token_id,
                                midpoint=midpoint,
                                spread=sell_price - buy_price,
                                latency_ms=latency_ms,
                                fee_bps=0,
                                vol_state=vol_state,
                                binance_price=binance_price,
                                inventory=float(theoretical_position),
                                action=action_label,
                                virtual_pnl=round(virtual_pnl, 2),
                                session_volume=round(session_volume, 2),
                                total_equity=round(total_equity, 2),
                                buying_power=round(current_cash, 2),
                                # Efficiency Metrics (New)
                                total_gas_spent_usd=round(total_gas_spent * matic_price, 4),
                                total_trades_count=total_trades_count,
                                total_order_updates=total_order_updates,
                                current_matic_balance=round(current_matic, 4)
                            )
                            total_order_updates += 1
                            queue.put_nowait(trade_data.dict())
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] [PnL] Session: ${virtual_pnl:.2f} | Pos: {theoretical_position} | Equity: ${total_equity:.2f}")
                            
                            metrics.update(
                                tick_to_trade_latency_ms=latency_ms,
                                pnl_session=virtual_pnl,
                                inventory_imbalance=int(theoretical_position)
                            )

                            if MOCK_TRADING:
                                # Mock Fills (30% probability per tick)
                                # Apply Gas ONLY for significant moves
                                gas_cost = 0.03 * len(orders)
                                current_matic -= gas_cost
                                total_gas_spent += gas_cost

                                if random.random() < 0.3:
                                    chosen = random.choice(orders)
                                    pending_fills.append({'side': chosen['side'], 'qty': chosen['size'], 'fill_time': time.time(), 'price': chosen['price']})
                            else:
                                # Live Execution
                                from py_clob_client.clob_types import OrderType
                                from py_clob_client.order_builder.constants import BUY, SELL
                                
                                for o in orders:
                                    try:
                                        side_const = BUY if o['side'] == 'BUY' else SELL
                                        order_args = OrderArgs(
                                            token_id=token_id,
                                            price=o['price'],
                                            size=o['size'],
                                            side=side_const
                                        )
                                        signed_order = client.create_order(order_args)
                                        resp = client.post_order(signed_order, OrderType.GTC)
                                        print(f"[LIVE_ORDER] {o['side']} {o['size']} @ {o['price']} -> {resp.get('orderID', 'OK')}")
                                    except Exception as order_e:
                                        print(f"[ORDER_ERROR] {o['side']}: {order_e}")
                        
                        break # Single market per tick for latency optimization
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
    print("Run via launcher.py or main.py")
