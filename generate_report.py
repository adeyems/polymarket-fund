import pandas as pd
import sys
import os
import requests
import time

def get_market_volume(token_id):
    # Fetch 24h Volume from Gamma API
    # Endpoint: /markets?clob_token_id={token_id}
    url = "https://gamma-api.polymarket.com/markets"
    try:
        resp = requests.get(url, params={"clob_token_id": token_id})
        resp.raise_for_status()
        data = resp.json()
        
        if data and isinstance(data, list):
            market = data[0]
            vol = float(market.get('volume24hr', 0))
            if vol > 0:
                print(f"  Using Market Volume: ${vol:,.2f}")
                return vol
            
            # Fallback: Fetch Parent Event Volume
            condition_id = market.get('conditionId')
            # Gamma doesn't always accept conditionId for events, let's try to get event info from market
            # Market often has "events" list with IDs
            events = market.get('events', [])
            if events:
                event_id = events[0].get('id')
                if event_id:
                    event_url = f"https://gamma-api.polymarket.com/events/{event_id}"
                    ev_resp = requests.get(event_url)
                    if ev_resp.ok:
                        ev_data = ev_resp.json()
                        ev_vol = float(ev_data.get('volume', 0))
                        print(f"  Using Event Volume (Fallback): ${ev_vol:,.2f}")
                        return ev_vol
            
            return 100000.0 # Ultimate Fallback
            
    except Exception as e:
        print(f"Error fetching volume for {token_id}: {e}")
    return 100000.0 # Fallback

def generate_report():
    csv_file = "simulation_trades.csv"
    if not os.path.exists(csv_file):
        print("No simulation data found.")
        return

    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    if df.empty:
        print("No trades recorded.")
        return

    print("=== 24-Hour Simulation Report ===")
    
    # 1. Diagnostics (Tick Analysis)
    total_ticks = len(df)
    print(f"Total Ticks Logged: {total_ticks}")
    
    if 'action_taken' in df.columns:
        action_counts = df['action_taken'].value_counts()
        print("\n--- Action Breakdown ---")
        print(action_counts)
        print("------------------------\n")
        
        # Filter for actual trades for profitability analysis
        trades_df = df[df['action_taken'] == 'TRADE_PLACED'].copy()
    else:
        print("Warning: 'action_taken' column missing. Assuming all rows are trades.")
        trades_df = df.copy()

    print(f"Total Trades Simulated: {len(trades_df)}")
    
    if trades_df.empty:
        print("No trades executed. Exiting analysis.")
        return
        
    df = trades_df # Use filtered DF for rest of report
    
    # Reward Zone Analysis (Spread <= 0.03)
    reward_zone_trades = df[df['spread'] <= 0.03]
    reward_percentage = (len(reward_zone_trades) / len(df)) * 100
    reward_percentage = (len(reward_zone_trades) / len(df)) * 100
    print(f"Reward Zone Compliance: {reward_percentage:.2f}% ({len(reward_zone_trades)} orders)")

    # Volatility Analysis
    if 'vol_state' in df.columns:
        print("\n=== Efficiency Analysis (Vol-Adjusted) ===")
        low_vol = df[df['vol_state'] == 'LOW_VOL']
        high_vol = df[df['vol_state'] == 'HIGH_VOL']
        
        print(f"Low Volatility Trades: {len(low_vol)} (Spread 0.5c)")
        print(f"High Volatility Trades: {len(high_vol)} (Spread 2.0c)")
        
        # Calculate theoretical PnL/Rewards per state?
        # For now just volume capture
        low_vol_vol = (low_vol['price'] * low_vol['size']).sum()
        high_vol_vol = (high_vol['price'] * high_vol['size']).sum()
        print(f"Low Vol Volume: ${low_vol_vol:.2f}")
        print(f"High Vol Volume: ${high_vol_vol:.2f}")

    # API Performance
    avg_latency = df['latency_ms'].mean()
    max_latency = df['latency_ms'].max()
    print(f"Average API Latency: {avg_latency:.2f} ms")
    print(f"Max API Latency: {max_latency:.2f} ms")

    # Liquidity Reward Estimator
    if 'midpoint' in df.columns:
        # Calculate deviation from midpoint
        df['deviation'] = abs(df['price'] - df['midpoint'])
        df['max_deviation'] = df['midpoint'] * 0.02
        
        # Valid Reward Orders with epsilon for float tolerance
        reward_df = df[df['deviation'] <= (df['max_deviation'] + 1e-9)].copy()
        
        # Calculate Points
        reward_df['points'] = (reward_df['size'] / reward_df['spread']) * 60
        
        total_points = reward_df['points'].sum()
        print(f"Total Liquidity Points: {total_points:.2f}")
        
        # Fetch Real Volume for Token(s)
        # Assuming single market for simple reports, or average volume?
        # Let's get unique tokens
        unique_tokens = df['token_id'].unique()
        total_market_volume = 0
        for tid in unique_tokens:
            vol = get_market_volume(str(tid))
            print(f"Fetched 24h Volume for {tid[:10]}...: ${vol:,.2f}")
            total_market_volume += vol # Summing might be wrong if multiple tokens are same market? 
            # Usually we trade Yes/No. Volume is per market. 
            # Ideally we map token -> market, but let's assume one main market active or sum distinct market vols.
            # Gamma gives market volume. If we trade Yes and No of same market, we shouldn't double count.
            # But the loop in market_maker only picks one token per market. So summing is "safe" for distinct markets.
        
        if total_market_volume == 0: total_market_volume = 100000

        estimated_earnings = (total_points / total_market_volume) * 2000
        
        print(f"Estimated Daily Earnings (vs ${total_market_volume:,.0f} Vol): ${estimated_earnings:.2f}")

        # Maker Rebate Estimation (Promo: Jan 12-18)
        # Formula: Share = (My_Vol / (Total_Vol + My_Vol)) * (Total_Vol * Taker_Fee * Promo_Share)
        # Constants
        TAKER_FEE = 0.015 # 1.5%
        PROMO_SHARE = 0.20 # 20%
        
        # Calculate My Simulated Volume (Sum of Price * Size)
        # df['price'] is execution price, size is usually 10 shares
        my_volume = (df['price'] * df['size']).sum()
        
        # Pool
        total_fees = total_market_volume * TAKER_FEE
        promo_pool = total_fees * PROMO_SHARE
        
        # My Share
        if (total_market_volume + my_volume) > 0:
             # FIX: True Promo Share Formula
             # My_Share = (My_Vol / (Total_Vol + My_Vol)) ...
             my_share_ratio = my_volume / (total_market_volume + my_volume)
             
             # Total Pool = (Total_Vol * Fee * Share)
             # But actually, rebates come from the fees generated by the TOTAL pool including ME.
             pool_basis = (total_market_volume + my_volume) * TAKER_FEE * PROMO_SHARE
             maker_rebates = pool_basis * my_share_ratio
        else:
             maker_rebates = 0
             
        print(f"My Simulated Volume: ${my_volume:.2f}")
        print(f"Estimated Maker Rebates (Promo Share): ${maker_rebates:.2f}")

    else:
        print("Midpoint data missing. Cannot calculate rewards.")

    total_volume = df['price'].sum() * 10 # Size 10
    print(f"Total Theoretical Volume: ${total_volume:.2f}")
    
    # Error Log Analysis
    error_log = "simulation_errors.log"
    error_count = 0
    if os.path.exists(error_log):
        with open(error_log, "r") as f:
            error_count = len(f.readlines())
    print(f"Total API Errors: {error_count}")
    
    print("=================================")

if __name__ == "__main__":
    generate_report()
