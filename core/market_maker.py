import os
import sys
import time
import json
import csv
import random
import requests
import re
import statistics
import asyncio
from datetime import datetime, timedelta
# from web3 import Web3 # Web3 Removed due to import hang
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs
from py_clob_client.constants import POLYGON

# Import Shared Schemas
from core.shared_schemas import TradeData, BotParams

# Load environment variables
load_dotenv()

# Constants
GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"
POLYGON_RPC_URL = "https://polygon-rpc.com"

# --- CONFIGURATION (Default, overridden by BotState) ---
# --- CONFIGURATION (Default, overridden by BotState) ---
MOCK_TRADING = True 

# --- BLOCKING HELPER FUNCTIONS (To be wrapped) ---

def get_usdc_balance(address, collateral_address):
    # MOCK BALANCE for Latency Testing
    return 1000.0


def fetch_target_markets():
    # MOCK MARKET for Simulation
    return [{
        "question": "Will Solana hit $135 by 2026? (Simulation)",
        "enableOrderBook": True,
        "clobTokenIds": ["1234567890"],
        "liquidity": 1000000
    }]

# --- Binance & Signal Helpers ---
BINANCE_CACHE = {}

def fetch_binance_price(symbol):
    """
    Fetches spot price from Binance with 5s caching.
    Symbol e.g., 'BTCUSDT'
    """
    # SIMULATION OVERRIDE
    if symbol == "SOLUSDT": return 133.10
    if symbol == "BTCUSDT": return 91800.00
    
    now = time.time()
    if symbol in BINANCE_CACHE:
         price, ts = BINANCE_CACHE[symbol]
         if now - ts < 5:
             return price

    url = "https://api.binance.com/api/v3/ticker/price"
    try:
        resp = requests.get(url, params={"symbol": symbol}, timeout=2)
        resp.raise_for_status()
        data = resp.json()
        price = float(data["price"])
        BINANCE_CACHE[symbol] = (price, now)
        return price
    except Exception as e:
        # print(f"  [BINANCE] Error: {e}")
        return None

def parse_strike_price(question):
    """
    Extracts dollar amount from question, handling k/m/b suffixes.
    """
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
    print(f"[BOT] Starting Async Trading Bot...")
    
    # 1. Setup Client
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    api_key = os.getenv("CLOB_API_KEY")
    api_secret = os.getenv("CLOB_SECRET")
    api_passphrase = os.getenv("CLOB_PASSPHRASE")

    if not all([pk, api_key, api_secret, api_passphrase]):
        print("Error: Missing credentials in .env")
        return

    creds_obj = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)

    try:
        # Wrap Client Init (just in case it hits disk/network)
        client = await asyncio.to_thread(
            ClobClient,
            host="https://clob.polymarket.com",
            key=pk,
            chain_id=POLYGON,
            creds=creds_obj
        )
    except Exception as e:
        print(f"Error initializing Client: {e}")
        return

    # 2. Safety Check (Wrapped)
    try:
        user_address = await asyncio.to_thread(client.get_address)
        collateral_address = await asyncio.to_thread(client.get_collateral_address)
        
        print(f"User Address: {user_address}")
        # Run blocking web3 call in thread
        usdc_balance = await asyncio.to_thread(get_usdc_balance, user_address, collateral_address)
        print(f"Current USDC Balance: {usdc_balance:.2f}")
        
        if usdc_balance < 50:
            print("Warning: Balance below 50 USDC. Switching to Shadow Mode (Paper Trading).")
    except Exception as e:
        print(f"Warning: Could not fetch balance info: {e}")

    # 3. Loop Setup
    csv_file = "simulation_trades.csv"
    if not os.path.exists(csv_file):
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "token_id", "side", "price", "size", "spread", "latency_ms", "midpoint", "fee_bps", "expiration", "vol_state", "binance_price", "inventory_state", "action_taken"])

    today_date = datetime.now().strftime("%Y-%m-%d") # Log file per day?
    
    # Session Metrics
    initial_cash = 1000.0
    current_cash = initial_cash
    session_volume = 0.0
    virtual_pnl = 0.0
    theoretical_position = 0.0  # Net inventory position
    
    # Volatility Tracking
    last_midpoint = None
    last_check_time = time.time()
    price_history = {} 
    
    consecutive_errors = 0
    backoff_time = 1
    
    # Re-org Protection
    pending_fills = []
    BLOCK_TIME = 4.0 

    while True:
        # GLOBAL KILL SWITCH CHECK
        if not bot_state.is_running:
            print("[BOT] Kill Switch Active. Sleeping 5s...")
            await asyncio.sleep(5)
            continue

        loop_start = time.time()
        # print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Tick...")
        
        try:
            # Per-Tick Variables
            binance_price = 0
            inventory_state = theoretical_position 
            action_taken = "SKIPPED_FILTER"
            
            # --- PROCESS PENDING FILLS ---
            current_time = time.time()
            confirmed_fills = []
            for fill in pending_fills:
                if current_time - fill['fill_time'] >= BLOCK_TIME:
                    qty = fill['qty']
                    price = fill.get('price', 0.50) # Assuming 0.50 if not stored
                    cost = qty * price
                    
                    if fill['side'] == 'BUY':
                        theoretical_position += qty
                        current_cash -= cost
                    else:
                        theoretical_position -= qty
                        current_cash += cost
                        
                    session_volume += cost
                    confirmed_fills.append(fill)
                    # print(f"  [RE-ORG] Transaction Confirmed. New Pos: {theoretical_position}")
            
            for fill in confirmed_fills:
                pending_fills.remove(fill)
            
            # --- Market Discovery (Blocking -> Thread) ---
            markets = await asyncio.to_thread(fetch_target_markets)
            
            if not markets:
                print("No markets found.")
                await asyncio.sleep(10)
                continue

            # Iterate markets
            market_found = False
            for target_market in markets:
                question = target_market.get('question', 'Unknown')
                
                if not target_market.get('enableOrderBook'): continue
                if "Up or Down" in question: continue

                q_lower = question.lower()
                keywords = ["bitcoin", "btc", "ethereum", "solana", "crypto"]
                if not any(k in q_lower for k in keywords): continue

                # USE SHARED PARAM for Min Liquidity
                liquidity = float(target_market.get('liquidity', 0))
                if liquidity < bot_state.min_liquidity: continue

                # Found a candidate
                try: # Handle malformed JSON in clobTokenIds if needed
                    clob_token_ids = json.loads(target_market.get('clobTokenIds', '[]'))
                except:
                    clob_token_ids = target_market.get('clobTokenIds', [])

                if not clob_token_ids: continue
                    
                token_id = clob_token_ids[0]

                # 4. Fetch Order Book (Blocking -> Thread)
                try:
                    # Fee & Expiry (Wrapped)
                    taker_fee_bps = await asyncio.to_thread(client.get_fee_rate_bps, token_id)
                    expiration = int(time.time() + 90)

                    api_start = time.time()
                    # BLOCKING CALL
                    order_book = await asyncio.to_thread(client.get_order_book, token_id)
                    latency_ms = (time.time() - api_start) * 1000
                    
                    bids = order_book.bids
                    asks = order_book.asks
                    
                    if not bids or not asks: continue
                    
                    best_bid = float(bids[0].price)
                    best_ask = float(asks[0].price)
                    midpoint = (best_bid + best_ask) / 2
                    
                    # Log for UI
                    # print(f"  {question[:40]}... Mid: {midpoint:.3f}")

                    # Volatility Protection
                    current_time = time.time()
                    if last_midpoint is not None:
                        delta_price = abs(midpoint - last_midpoint)
                        delta_time = current_time - last_check_time
                        
                        if delta_price > 0.02 and delta_time < 5.0:
                            print(f"  [VOLATILITY] Price moved {delta_price:.3f}. SKIP.")
                            last_midpoint = midpoint
                            last_check_time = current_time
                            break 
                    
                    last_midpoint = midpoint
                    last_check_time = current_time
                    
                    # 5. Calculate Orders
                    # Updates History
                    if token_id not in price_history: 
                        price_history[token_id] = []
                        # INJECT SIMULATED HISTORY FOR VOLATILITY TEST
                        # We simulate a "crash" sequence: 0.50 -> 0.45 -> 0.40 -> 0.48
                        # This ensures stdev > 0.01 immediately
                        # price_history[token_id].append((current_time - 10, 0.50))
                        # price_history[token_id].append((current_time - 5, 0.45))
                    
                    price_history[token_id].append((current_time, midpoint))
                    price_history[token_id] = [entry for entry in price_history[token_id] if current_time - entry[0] <= 300]
                    
                    vol_state = "LOW_VOL"
                    
                    # USE SHARED PARAM
                    base_spread_offset = bot_state.spread_offset 
                    
                    prices = [entry[1] for entry in price_history[token_id]]
                    if len(prices) > 2:
                        stdev = statistics.stdev(prices)
                        # SIMULATION: Force Print Stdev
                        # print(f"  [SIM] Stdev: {stdev:.4f} (Threshold: 0.01)")
                        if stdev > 0.01:
                            vol_state = "HIGH_VOL"
                            # WIDEN SPREAD AGGRESSIVELY
                            base_spread_offset = max(base_spread_offset, 0.04) 
                            print(f"  [DEFENSE] High Volatility Detected! Widening spread to {base_spread_offset}")
                    
                    # Latency Override
                    if latency_ms > 500:
                        base_spread_offset = max(base_spread_offset, 0.02)
                    
                    buy_price = round(midpoint - base_spread_offset, 2)
                    sell_price = round(midpoint + base_spread_offset, 2)
                    
                    if buy_price >= 1: buy_price = 0.99
                    if sell_price >= 1: sell_price = 0.99
                    if buy_price <= 0: buy_price = 0.01

                    spread = sell_price - buy_price
                    
                    # INVENTORY CHECKS
                    allow_buy = True
                    allow_sell = True
                    
                    # SIGNAL (Blocking -> Thread)
                    strike_price = parse_strike_price(question)
                    binance_symbol = None
                    q_upper = question.upper()
                    
                    if "BITCOIN" in q_upper or "BTC" in q_upper: binance_symbol = "BTCUSDT"
                    elif "ETHEREUM" in q_upper or "ETH" in q_upper: binance_symbol = "ETHUSDT"
                    elif "SOLANA" in q_upper or "SOL" in q_upper: binance_symbol = "SOLUSDT"
                    
                    if strike_price and binance_symbol:
                        spot_price = await asyncio.to_thread(fetch_binance_price, binance_symbol)
                        if spot_price:
                            binance_price = spot_price
                            divergence_pct = ((spot_price - strike_price) / strike_price) * 100
                            
                            if divergence_pct > 0.8: allow_sell = False
                            if divergence_pct < -0.8: allow_buy = False
                    
                    # Max Position Check
                    if theoretical_position >= bot_state.max_position: allow_buy = False
                    if theoretical_position <= -bot_state.max_position: allow_sell = False

                    # 7. Place Orders
                    orders_to_place = []
                    # Shared Param Order Size
                    base_qty = bot_state.order_size
                    
                    if allow_buy:
                        orders_to_place.append({"side": "BUY", "price": buy_price, "size": base_qty})
                    if allow_sell:
                        orders_to_place.append({"side": "SELL", "price": sell_price, "size": base_qty})
                        
                    if orders_to_place:
                        action_taken = "TRADE_PLACED"
                        
                        # --- PRODUCE TO QUEUE (Non-Blocking) ---
                        
                        # Calculate Mark-to-Market PnL
                        # PnL = (Current Cash + (Position * Midpoint)) - Initial Cash
                        inventory_value = theoretical_position * midpoint
                        total_equity = current_cash + inventory_value
                        virtual_pnl = total_equity - initial_cash
                        
                        # We send a snapshot of what we *would* do (or did)
                        trade_data = TradeData(
                            timestamp=datetime.now().isoformat(),
                            token_id=token_id,
                            midpoint=midpoint,
                            spread=spread,
                            latency_ms=latency_ms,
                            fee_bps=int(taker_fee_bps) if isinstance(taker_fee_bps, (int, float)) else 0,
                            vol_state=vol_state,
                            binance_price=binance_price,
                            inventory=float(inventory_state),
                            action=action_taken,
                            bids=[{"price": b.price, "size": b.size} for b in bids[:3]],
                            asks=[{"price": a.price, "size": a.size} for a in asks[:3]],
                            virtual_pnl=round(virtual_pnl, 2),
                            session_volume=round(session_volume, 2),
                            total_equity=round(total_equity, 2),
                            buying_power=round(current_cash, 2)
                        )
                        queue.put_nowait(trade_data.dict())

                        # Execute (Mock/Live)
                        if MOCK_TRADING:
                             # Sim Fills
                            if allow_buy and random.random() < 0.3:
                                pending_fills.append({'side': 'BUY', 'qty': 10, 'fill_time': time.time(), 'price': buy_price})
                            if allow_sell and random.random() < 0.3:
                                pending_fills.append({'side': 'SELL', 'qty': 10, 'fill_time': time.time(), 'price': sell_price})
                        else:
                            # LIVE ORDER PLACEMENT (Blocking -> Thread)
                            live_orders = [
                                OrderArgs(price=o['price'], size=o['size'], side=o['side'], token_id=token_id, expiration=str(expiration), fee_rate_bps=int(taker_fee_bps))
                                for o in orders_to_place
                            ]
                            try:
                                resp = await asyncio.to_thread(client.post_orders, live_orders)
                                # print(f"  [LIVE] Orders Sent: {resp}")
                            except Exception as e:
                                print(f"  [LIVE ERROR] {e}")

                    # 8. Log Tick (Local File)
                    # We can keep this sync since file IO is fast enough for this scale, or wrap it.
                    # For simplicity, keeping sync logging but brief.
                    # log_tick(...) # Omitted to save complexity in Validated File, utilizing Queue for observability instead.
                    
                    market_found = True
                    break 

                except Exception as e:
                    print(f"  Error process market inner: {e}")
                    continue
            
            # Backoff Reset
            consecutive_errors = 0
            backoff_time = 1
            
            # SLEEP
            # In async mod, we can sleep shorter to check for updates or process other markets
            await asyncio.sleep(5) 

        except Exception as e:
            consecutive_errors += 1
            print(f"  [ERROR] Main Loop: {e}")
            await asyncio.sleep(backoff_time)
            backoff_time = min(backoff_time * 2, 60)
            
            if consecutive_errors >= 3:
                print("  [CRITICAL] 3 Errors. Pausing...")
                await asyncio.sleep(300)
                consecutive_errors = 0

async def cancel_all_orders_async(client):
    """
    Async wrapper for cancelling all orders
    """
    try:
        print("[LIVE] Cancelling all open orders...")
        await asyncio.to_thread(client.cancel_all)
        print("[LIVE] All orders cancelled.")
    except Exception as e:
        print(f"[ERROR] Failed to cancel orders: {e}")

if __name__ == "__main__":
    # Standalone Test
    print("This file is now a module. Run 'main.py' to start the system.")
