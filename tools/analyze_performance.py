#!/usr/bin/env python3
import re
import sys
import os
from datetime import datetime
from collections import deque

LOG_FILE = "/var/log/quesquant/hft_bot.log"

def analyze():
    if not os.path.exists(LOG_FILE):
        print(f"Error: Log file not found at {LOG_FILE}")
        return

    # Data Structures
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
    latency_pattern = re.compile(r"\[(\d{2}:\d{2}:\d{2})\] \[LATENCY\] .*? Mid: (\d+\.\d+)")

    with open(LOG_FILE, "r") as f:
        for line in f:
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
            lat_match = latency_pattern.search(line)
            if lat_match:
                ts_str, mid = lat_match.groups()
                mid = float(mid)
                
                processed_checks = []
                for check in adverse_checks:
                    # If this midpoint is after the fill
                    if check['side'] == 'BUY' and mid < check['price']:
                        toxic_hits += 1
                        total_toxic_checks += 1
                        processed_checks.append(check)
                    elif check['side'] == 'SELL' and mid > check['price']:
                        toxic_hits += 1
                        total_toxic_checks += 1
                        processed_checks.append(check)
                    else:
                        # Only check the immediate next midpoint for "Toxic Flow"
                        total_toxic_checks += 1
                        processed_checks.append(check)
                
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

if __name__ == "__main__":
    analyze()
