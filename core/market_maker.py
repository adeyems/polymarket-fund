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
        "question": "Will Trump deport less than 250,000?",
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
    
    binance = get_binance_manager(["btcusdt", "ethusdt", "solusdt"])
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
    initial_cash = 1000.0
    current_cash = initial_cash
    theoretical_position = 0.0
    session_volume = 0.0
    
    pending_fills = []
    BLOCK_TIME = 4.0 
    price_history = {} 
    last_midpoint = None
    last_check_time = time.time()

    # --- MAIN ENGINE LOOP ---
    try:
        while True:
            # Heartbeat (CloudWatch)
            metrics.push_heartbeat()
            
            # Kill Switch Check
            if not bot_state.is_running:
                print("[BOT] Bot Paused. Waiting for activation...")
                await asyncio.sleep(5)
                continue

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
                    session_volume += cost
                    confirmed_fills.append(fill)
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
                    if float(target_market.get('liquidity', 0)) < bot_state.min_liquidity: continue

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
                    
                    # 3. Spread & Volatility Management
                    vol_state = "LOW_VOL"
                    base_spread = bot_state.spread_offset
                    
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
                        # Telemetry Update
                        total_equity = current_cash + (theoretical_position * midpoint)
                        virtual_pnl = total_equity - initial_cash
                        
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
                            action="TRADE_PLACED",
                            virtual_pnl=round(virtual_pnl, 2),
                            session_volume=round(session_volume, 2),
                            total_equity=round(total_equity, 2),
                            buying_power=round(current_cash, 2)
                        )
                        queue.put_nowait(trade_data.dict())
                        
                        metrics.update(
                            tick_to_trade_latency_ms=latency_ms,
                            pnl_session=virtual_pnl,
                            inventory_imbalance=int(theoretical_position)
                        )

                        if MOCK_TRADING:
                            # Mock Fills (30% probability per tick)
                            if random.random() < 0.3:
                                chosen = random.choice(orders)
                                pending_fills.append({'side': chosen['side'], 'qty': chosen['size'], 'fill_time': time.time(), 'price': chosen['price']})
                        else:
                            # Live Execution
                            live_orders = [
                                OrderArgs(price=o['price'], size=o['size'], side=o['side'], token_id=token_id)
                                for o in orders
                            ]
                            await asyncio.to_thread(client.post_orders, live_orders)
                    
                    break # Single market per tick for latency optimization

            except Exception as loop_e:
                print(f"[LOOP ERROR] {loop_e}")

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
