import requests

SLUG = "what-price-will-bitcoin-hit-in-january-2026"
URL = f"https://gamma-api.polymarket.com/events?slug={SLUG}"

try:
    r = requests.get(URL)
    r.raise_for_status()
    data = r.json()
    
    if not data:
        print("No event found.")
        exit(1)
        
    event = data[0]
    markets = event.get('markets', [])
    
    if not markets:
        print("No markets in event.")
        exit(1)
        
    # Find active markets with clobTokenIds
    import json
    valid = []
    for m in markets:
        raw_ids = m.get('clobTokenIds')
        if raw_ids:
            try:
                ids = json.loads(raw_ids)
                if ids:
                    m['parsed_ids'] = ids
                    valid.append(m)
            except:
                pass
    
    # Remove specific filtering to see ALL options using the loop above
    
    # Sort by volume descending
    valid.sort(key=lambda x: float(x.get('volume', 0)), reverse=True)
    
    print(f"{'QUESTION':<50} | {'VOL':<10} | {'BID':<5} | {'ASK':<5} | {'SPREAD':<6} | {'ID'}")
    print("-" * 130)
    for m in valid:
        q = m.get('question')
        v = float(m.get('volume', 0))
        id_ = m.get('parsed_ids')[0]
        
        # Gamma API output usually has 'bestBid'/'bestAsk' string or numeric
        bid = float(m.get('bestBid', 0) or 0) # Handle None/Empty strings safely
        ask = float(m.get('bestAsk', 0) or 0)
        spread = ask - bid
        
        print(f"{q:<50} | ${v/1e6:,.1f}M | {bid:<5.2f} | {ask:<5.2f} | {spread:<6.2f} | {id_}")
    
except Exception as e:
    print(f"Error: {e}")
