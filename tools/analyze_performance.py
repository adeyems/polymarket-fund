#!/usr/bin/env python3
import re
import sys
import os
import json
from datetime import datetime
from collections import deque
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import ApiCreds
from dotenv import load_dotenv

LOG_FILE = "/var/log/quesquant/hft_bot.log"
ENV_FILE = "/app/hft/.env"

def get_live_stats():
    """Fetch live USDC and MATIC balance from Polygon."""
    load_dotenv(ENV_FILE)
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    # Try multiple RPCs to avoid rate limits
    rpcs = [os.getenv("POLYGON_RPC"), "https://polygon-rpc.com", "https://rpc-mainnet.maticvigil.com"]
    rpcs = [r for r in rpcs if r]
    
    if not pk: return 0.0, 0.0, "UNKNOWN"
    
    USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174" # USDC.e
    ERC20_ABI = [
        {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
        {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
    ]

    from web3 import Web3
    from eth_account import Account
    address = Account.from_key(pk).address

    for rpc in rpcs:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc))
            # Matic Balance
            current_matic = float(w3.from_wei(w3.eth.get_balance(address), 'ether'))
            
            # USDC Balance
            usdc_contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI)
            raw_balance = usdc_contract.functions.balanceOf(address).call()
            decimals = usdc_contract.functions.decimals().call()
            current_usdc = raw_balance / (10 ** decimals)
            
            return current_usdc, current_matic, address
        except Exception as e:
            print(f"RPC Error ({rpc}): {e}")
            continue
            
    return 0.0, 0.0, address

def analyze():
    if not os.path.exists(LOG_FILE):
        print(f"Error: Log file not found at {LOG_FILE}")
        return

    # Data Structures
    start_usdc = 100.0 # Default fallback if not found in logs
    start_matic = 0.0
    matic_price = 0.85
    buys = deque() # (timestamp, price, qty)
    sells = deque()
    
    total_buy_val = 0
    total_sell_val = 0
    total_volume = 0
    
    realized_pnl = 0
    round_trips = 0
    winning_trades = 0
    
    hold_times = []
    
    adverse_checks = [] # (type, price, fill_time)
    toxic_hits = 0
    total_toxic_checks = 0

    # Regex Patterns
    trade_pattern = re.compile(r"\[(\d{2}:\d{2}:\d{2})\] \[TRADE_FILLED\] (\w+) (\d+\.?\d*) tokens @ (\d+\.\d+)")
    latency_pattern = re.compile(r"\[(\d{2}:\d{2}:\d{2})\] \[LATENCY\] .*? Matic: \$(\d+\.\d+)")
    toxic_flow_pattern = re.compile(r"\[(\d{2}:\d{2}:\d{2})\] \[LATENCY\] .*? Mid: (\d+\.\d+)")
    start_usdc_pattern = re.compile(r"\[START_BALANCE\] USDC: (\d+\.\d+)")
    start_matic_pattern = re.compile(r"\[START_BALANCE\] MATIC: (\d+\.\d+)")

    with open(LOG_FILE, "r") as f:
        for line in f:
            # 0. Parse Start Balances
            su_match = start_usdc_pattern.search(line)
            if su_match: start_usdc = float(su_match.group(1))
            sm_match = start_matic_pattern.search(line)
            if sm_match: start_matic = float(sm_match.group(1))
            
            # 0.1 Update Matic Price for current state
            lat_match = latency_pattern.search(line)
            if lat_match: 
                # We reuse lat_match later for toxic checks too, but here we grab matic
                ts_str, m_price = lat_match.groups()
                matic_price = float(m_price)

            # 1. Parse Trades
            trade_match = trade_pattern.search(line)
            if trade_match:
                ts_str, side, qty, price = trade_match.groups()
                qty = float(qty)
                price = float(price)
                ts = datetime.strptime(ts_str, "%H:%M:%S")
                
                total_volume += (qty * price)
                
                # Adverse selection check setup (check next midpoint)
                adverse_checks.append({'side': side, 'price': price, 'time': ts})
                
                if side == "BUY":
                    total_buy_val += (qty * price)
                    # Matching Sells for Win Rate / Turnover
                    while qty > 0 and sells:
                        s_ts, s_price, s_qty = sells.popleft()
                        match_qty = min(qty, s_qty)
                        
                        pnl = (s_price - price) * match_qty
                        realized_pnl += pnl
                        round_trips += 1
                        if pnl > 0: winning_trades += 1
                        
                        hold_times.append((ts - s_ts).total_seconds())
                        
                        qty -= match_qty
                        if s_qty > match_qty:
                            sells.appendleft((s_ts, s_price, s_qty - match_qty))
                    
                    if qty > 0:
                        buys.append((ts, price, qty))
                
                else: # SELL
                    total_sell_val += (qty * price)
                    # Matching Buys
                    while qty > 0 and buys:
                        b_ts, b_price, b_qty = buys.popleft()
                        match_qty = min(qty, b_qty)
                        
                        pnl = (price - b_price) * match_qty
                        realized_pnl += pnl
                        round_trips += 1
                        if pnl > 0: winning_trades += 1
                        
                        hold_times.append((ts - b_ts).total_seconds())
                        
                        qty -= match_qty
                        if b_qty > match_qty:
                            buys.appendleft((b_ts, b_price, b_qty - match_qty))
                            
                    if qty > 0:
                        sells.append((ts, price, qty))

            # 2. Parse Latency (Midpoint for Toxic Flow)
            lat_match = toxic_flow_pattern.search(line)
            if lat_match:
                ts_str, mid = lat_match.groups()
                mid = float(mid)
                
                processed_checks = []
                for check in adverse_checks:
                    # Time threshold (1s)
                    time_diff = (ts - check['time']).total_seconds()
                    if time_diff > 1.2: # Allow small buffer for loop jitter
                        total_toxic_checks += 1
                        processed_checks.append(check)
                        continue
                        
                    # 0.5% move threshold
                    threshold = check['price'] * 0.005
                    
                    if check['side'] == 'BUY' and (mid < (check['price'] - threshold)):
                        toxic_hits += 1
                        total_toxic_checks += 1
                        processed_checks.append(check)
                    elif check['side'] == 'SELL' and (mid > (check['price'] + threshold)):
                        toxic_hits += 1
                        total_toxic_checks += 1
                        processed_checks.append(check)
                    # If we have a mid within 1s but not toxic, we keep checking until 1s passes or it hits toxic
                
                for p in processed_checks:
                    adverse_checks.remove(p)

    # Calculate Summaries
    toxic_ratio = (toxic_hits / total_toxic_checks * 100) if total_toxic_checks > 0 else 0
    win_rate = (winning_trades / round_trips * 100) if round_trips > 0 else 0
    avg_turnover = (sum(hold_times) / len(hold_times)) if hold_times else 0
    rebate = total_volume * 0.0005

    # Print Table
    print("\n" + "="*50)
    print(" QUESQUANT HFT - DIRECT-ACTION PERFORMANCE REPORT ")
    print("="*50)
    print(f" {'Metric':<25} | {'Value':<15} ")
    print("-" * 50)
    print(f" {'Realized PnL':<25} | ${realized_pnl:>14.2f} ")
    print(f" {'Toxic Flow Ratio':<25} | {toxic_ratio:>14.2f}% ")
    print(f" {'Inventory Turnover':<25} | {avg_turnover:>13.1f}s ")
    print(f" {'Win Rate':<25} | {win_rate:>14.2f}% ")
    print(f" {'Rebate Estimator':<25} | ${rebate:>14.4f} ")
    print("-" * 50)
    print(f" {'Total Volume':<25} | ${total_volume:>14.2f} ")
    print(f" {'Round Trips':<25} | {round_trips:>15} ")
    print("="*50 + "\n")

    # Discrepancy Report
    current_usdc, current_matic, address = get_live_stats()
    usdc_delta = current_usdc - start_usdc
    gas_spent = start_matic - current_matic
    true_alpha = usdc_delta - (gas_spent * matic_price)
    
    discrepancy = true_alpha - realized_pnl
    
    print("="*50)
    print(" QUESQUANT HFT - BLOCKCHAIN DISCREPANCY REPORT ")
    print("="*50)
    print(f" {'Wallet Address':<25} | {address} ")
    print(f" {'Metric':<25} | {'Value':<15} ")
    print("-" * 50)
    print(f" {'Initial USDC (Logs)':<25} | ${start_usdc:>14.2f} ")
    print(f" {'Current USDC (Chain)':<25} | ${current_usdc:>14.2f} ")
    print(f" {'USDC Delta':<25} | ${usdc_delta:>14.2f} ")
    print(f" {'Gas Spent (MATIC)':<25} | {gas_spent:>15.4f} ")
    print(f" {'Gas Cost (USD)':<25} | ${gas_spent*matic_price:>14.4f} ")
    print("-" * 50)
    print(f" {'True Alpha (Blockchain)':<25} | ${true_alpha:>14.2f} ")
    print(f" {'Log PnL (Theoretical)':<25} | ${realized_pnl:>14.2f} ")
    print(f" {'Discrepancy (Leakage)':<25} | ${discrepancy:>14.2f} ")
    print("-" * 50)
    if abs(discrepancy) > 1.0:
        print(" [WARNING] Significant Discrepancy Detected! Check for fees/slippage.")
    else:
        print(" [STATUS] Wallet Delta aligns with theoretical PnL.")
    print("="*50 + "\n")

    # CSV Append for Historical Audit
    HISTORY_FILE = "/var/log/quesquant/perf_history.csv"
    try:
        file_exists = os.path.exists(HISTORY_FILE)
        with open(HISTORY_FILE, "a") as f:
            if not file_exists:
                f.write("timestamp,realized_pnl,toxic_ratio,avg_turnover,win_rate,volume,round_trips\n")
            f.write(f"{datetime.now().isoformat()},{realized_pnl:.2f},{toxic_ratio:.2f},{avg_turnover:.1f},{win_rate:.2f},{total_volume:.2f},{round_trips}\n")
    except Exception as e:
        print(f"Warning: Could not write to history file: {e}")

if __name__ == "__main__":
    analyze()
