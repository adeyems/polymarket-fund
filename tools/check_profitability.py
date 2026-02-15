
import requests

def check_prices():
    queries = [
        "measles cases in the U.S.",
        "Rockets vs. 76ers",
        "Russia x Ukraine ceasefire by January 31, 2026"
    ]
    
    print(f"{'MARKET':<50} | {'ENTRY (ASK)':<12} | {'CURRENT (MID)':<15} | {'PROFIT?'}")
    print("-" * 100)
    
    for q in queries:
        try:
            # simple search
            url = "https://gamma-api.polymarket.com/events"
            params = {"q": q, "limit": 1}
            r = requests.get(url, params=params).json()
            
            if r:
                # Gamma returns events. Need first market.
                event = r[0]
                markets = event.get('markets', [])
                if markets:
                    m = markets[0] # Assume main market
                    
                    # Get Outcome Prices (outcome 0 and 1)
                    # We need to know which one we likely rejected.
                    # Usually we look at the liqudity/volume.
                    # Or just print the ClOB mid.
                    # We'll print the "Yes" price usually or the one with price ~ rejection log.
                    # Measles log: Bid 0.286 / Ask 0.301. Look for price around 30c.
                    
                    outcome = "Unknown"
                    curr_price = 0.0
                    
                    # Simple heuristic: find outcome closest to log price?
                    # Or just print all outcomes.
                    outcomes = m.get('outcomes', [])
                    clob_rewards = m.get('clobTokenIds', []) # If available
                    
                    # Gamma doesn't always have live clob price in /events.
                    # Need /markets
                    
                    mwt_id = m.get('id')
                    try:
                        m_url = f"https://gamma-api.polymarket.com/markets/{mwt_id}"
                        mr = requests.get(m_url).json()
                        # Gamma returns price history or stats?
                        # Use orderbook endpoint for price? 
                        # Or just use the 'bestAsk' 'bestBid' if available in market obj.
                        # It is usually under 'bestAsk'
                        
                        best_ask = mr.get('bestAsk', 'N/A')
                        best_bid = mr.get('bestBid', 'N/A')
                        mid = (float(best_ask) + float(best_bid))/2 if best_ask != 'N/A' and best_bid != 'N/A' else 0.0
                        
                        print(f"{q[:48]:<50} | {'(Log Check)':<12} | {mid:.3f} (Mid)    | ???")
                        
                    except:
                        print(f"{q[:48]:<50} | {'Err':<12} | {'Err':<15} | ???")

            else:
                 print(f"{q[:48]:<50} | {'Not Found':<12} | {'-':<15} | -")
                 
        except Exception as e:
            print(f"Error {q}: {e}")

if __name__ == "__main__":
    check_prices()
