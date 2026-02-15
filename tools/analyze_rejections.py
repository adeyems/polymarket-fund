
import csv
from datetime import datetime, timedelta

def analyze():
    print("Loading rejections...")
    rejections = []
    
    # 1. Load Data
    with open('data/rejection_audit.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rejections.append(row)
            
    print(f"Total Records: {len(rejections)}")
    
    # 2. Filter Last 24h
    now = datetime.now()
    cutoff = now - timedelta(hours=24)
    # Timestamp format in log: ISO (e.g., 2026-01-23T09:30:00.123456)
    
    recent = []
    for r in rejections:
        try:
            ts = datetime.fromisoformat(r['timestamp'])
            if ts > cutoff:
                recent.append(r)
        except ValueError:
            continue
            
    print(f"Last 24h Records: {len(recent)}")
    
    # 3. Filter for "Spread Too Wide" (but close to 5%)
    # The log marks 'failed_filter' as the reason.
    # We want ones where failed_filter == 'SPREAD_TOO_WIDE' (or similar string used in code)
    # Let's check the code: "[SCANNER] ⛔ Spread too wide" -> logic likely passes 'SPREAD_TOO_WIDE' or similar to log_rejection
    
    candidates = []
    for r in recent:
        if 'SPREAD' in r['failed_filter'].upper():
            try:
                spread = float(r['spread_pct'])
                if spread >= 5.0: # Only those that failed (>5%)
                    r['spread_val'] = spread
                    diff = spread - 5.0
                    r['diff'] = diff
                    candidates.append(r)
            except:
                continue
                
    # 4. Rank by Closeness to 5% (Ascending diff)
    candidates.sort(key=lambda x: x['diff'])
    
    top_5 = candidates[:5]
    
    print("\n=== TOP 5 'NEAR MISS' REJECTIONS (Closest to 5% Passing) ===")
    print(f"{'MARKET':<60} | {'SPREAD':<8} | {'VOLUME':<10} | {'BID/ASK':<15}")
    print("-" * 100)
    
    for i, r in enumerate(top_5):
        market = r['market_name'][:58]
        spread = f"{r['spread_val']}%"
        vol = f"${float(r['volume_24h']):.0f}"
        ba = f"{r['best_bid']} / {r['best_ask']}"
        print(f"{i+1}. {market:<57} | {spread:<8} | {vol:<10} | {ba:<15}")

    # Profit Hypothetical
    # If we bought at Ask, we need Price > Ask to profit.
    # Spread is (Ask - Bid) / Mid.
    # If Spread is 5.1%, basically we start -2.5% down from mid?
    # No, Spread = (Ask-Bid)/Mid. 
    # Example: Bid 0.50, Ask 0.525. Spread = 0.025 / 0.5125 = ~4.8%
    # If Spread is 6%, cost to enter/exit immediate is 6%.
    # "Would we have been in profit?" -> Depends on price movement since then.
    # Without current price, we can only say "You saved X% spread cost".

if __name__ == "__main__":
    analyze()
