import pandas as pd
import numpy as np

def audit_csv():
    try:
        df = pd.read_csv("simulation_trades.csv")
        print(f"Total Rows: {len(df)}")
        
        # 1. Column Completeness
        required_cols = ["binance_price", "midpoint", "inventory_state"]
        print("\n--- Column Check ---")
        for col in required_cols:
            if col in df.columns:
                print(f"[PASS] {col} exists.")
            else:
                print(f"[FAIL] {col} is MISSING.")

        # 2. Data Type Check
        print("\n--- Data Type Check ---")
        numeric_cols = ["price", "size", "midpoint", "latency_ms"]
        for col in numeric_cols:
            if col in df.columns:
                is_float = pd.api.types.is_float_dtype(df[col]) or pd.api.types.is_integer_dtype(df[col])
                if is_float:
                    print(f"[PASS] {col} is numeric ({df[col].dtype}).")
                else:
                    print(f"[FAIL] {col} looks like {df[col].dtype} (could be string wrapped).")
                    # Check first value
                    print(f"       Sample value: {df[col].iloc[0]} (Type: {type(df[col].iloc[0])})")
        
        # 3. Frequency & Drift
        print("\n--- Time Analysis ---")
        if "timestamp" in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Sort just in case
            df = df.sort_values('timestamp')
            
            start_time = df['timestamp'].iloc[0]
            end_time = df['timestamp'].iloc[-1]
            duration = end_time - start_time
            
            print(f"Start Time: {start_time}")
            print(f"End Time:   {end_time}")
            print(f"Total Drift (Duration): {duration}")

            # Gaps
            df['delta'] = df['timestamp'].diff().dt.total_seconds()
            avg_delta = df['delta'].mean()
            max_delta = df['delta'].max()
            
            print(f"Avg Gap: {avg_delta:.2f} seconds")
            print(f"Max Gap: {max_delta:.2f} seconds")
            
            if max_delta > 300: # 5 minutes
                print(f"[FAIL] Found gap > 5 minutes ({max_delta}s)!")
            else:
                print("[PASS] No gaps > 5 minutes found.")
        else:
            print("[FAIL] 'timestamp' column missing.")

    except Exception as e:
        print(f"Audit failed: {e}")

if __name__ == "__main__":
    audit_csv()
