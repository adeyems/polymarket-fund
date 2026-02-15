
import os
import csv
from datetime import datetime

# --- LOGGING UTILITY ---
REJECTION_AUDIT_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'rejection_audit.csv')

def log_rejection(market_name: str, volume_24h: float, spread_pct: float, failed_filter: str, best_bid: float = 0, best_ask: float = 0, vwap_exit: float = 0):
    """Appends a rejection to the audit CSV for strategy optimization."""
    try:
        row = {
            'timestamp': datetime.now().isoformat(),
            'market_name': market_name,
            'volume_24h': volume_24h,
            'spread_pct': round(spread_pct * 100, 2),
            'failed_filter': failed_filter,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'vwap_exit': vwap_exit
        }
        # Ensure directory exists
        os.makedirs(os.path.dirname(REJECTION_AUDIT_PATH), exist_ok=True)
        file_exists = os.path.exists(REJECTION_AUDIT_PATH)
        with open(REJECTION_AUDIT_PATH, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        print(f"[AUDIT-ERR] Failed to log rejection: {e}")

# --- GUARDS ---

def check_date_guard(market, current_time=None):
    """
    Returns True if market is active (not expired).
    Returns False if market has ended.
    """
    try:
        end_date_str = market.get('endDate')
        if not end_date_str: return True
        
        # Parse ISO format
        from datetime import datetime as dt_parser
        end_date = dt_parser.fromisoformat(end_date_str.replace('Z', '+00:00'))
        
        if not current_time:
            current_time = datetime.now(end_date.tzinfo) if end_date.tzinfo else datetime.utcnow()
            
        if current_time > end_date:
            print(f"[DATE-GUARD] ⛔ BLACKLISTED: '{market.get('question')}' ended on {end_date_str}.")
            return False
            
        return True
    except Exception as e:
        print(f"[DATE-GUARD] ⚠️ Parse error: {e}. Proceeding.")
        return True

def check_volume_floor(vol_24h, min_vol=25000):
    """Returns False if volume is below threshold."""
    if vol_24h < min_vol:
        print(f"[GATEKEEPER] ⛔ Market Rejected: 24h Volume ${vol_24h:.0f} < ${min_vol}")
        return False
    return True

def check_slippage_guard(order_book, intended_size):
    """
    Checks if Top-of-Book has enough liquidity.
    Returns True if safe.
    """
    top_ask_size = float(order_book.asks[0].size) if order_book.asks else 0.0
    min_fill_threshold = intended_size * 0.5
    
    if top_ask_size < min_fill_threshold and intended_size > 0:
        print(f"[SLIPPAGE-GUARD] ⛔ ABORT: Top Ask has {top_ask_size:.0f} shares, need {min_fill_threshold:.0f}+.")
        return False
    return True

def check_symmetry_guard(bid_dist, ask_dist, ratio_limit=3.0):
    """
    Detects market traps where Ask is significantly wider than Bid.
    Returns True if safe.
    """
    if bid_dist > 0.001: 
        ratio = ask_dist / bid_dist
        if ratio > ratio_limit:
            print(f"[SYMMETRY] ⛔ TRAP DETECTED: Ratio {ratio:.1f} > {ratio_limit}.")
            return False
    elif ask_dist > 0.01: 
        print(f"[SYMMETRY] ⛔ TRAP DETECTED: Bid is pegged, Ask is wide.")
        return False
        
    return True

def check_safety_interlock(target_outcome, price):
    """
    Prevents buying traps (Yes < $0.02) or expensive bets (No > $0.98).
    Returns True if safe.
    """
    if target_outcome == "Yes" and price < 0.02:
        print(f"[SAFETY] ⛔ ABORT: Target is YES but Price (${price:.3f}) is < $0.02. TRAP.")
        return False
    
    if target_outcome == "No" and price > 0.98:
        print(f"[SAFETY] ⛔ ABORT: Target is NO but Price (${price:.3f}) is > $0.98. R/R POOR.")
        return False
        
    return True

def check_edge_sanity(fair_value, entry_price):
    """
    Aborts if edge > 50% (likely data error).
    """
    if entry_price > 0.001:
        edge = abs(fair_value - entry_price) / entry_price
        if edge > 0.50:
            print(f"[EDGE-CHECK] ⛔ ABORT: Edge ({edge*100:.1f}%) > 50%. Likely data error.")
            return False
    return True

def calculate_vwap_exit(bids, size=35.0):
    """Calculates Volume-Weighted Average Price for selling specific size."""
    if not bids: return 0.0
    remaining = size 
    total_value = 0.0
    
    for bid in bids:
        if remaining <= 0: break
        p = float(bid.price)
        s = float(bid.size)
        take = min(s, remaining)
        total_value += take * p
        remaining -= take
        
    if remaining > 0:
        return 0.0 # Illiquid
        
    return total_value / size


# --- COMPOSITE GUARD ---

def check_all_guards(market, order_book=None, intended_size=5.0):
    """
    V3 Composite Guard: Runs all safety checks and returns (is_safe, reason).
    Used by the Brain Orchestrator for pre-flight validation.
    """
    question = market.get('question', 'Unknown')
    
    # 1. Date Guard
    if not check_date_guard(market):
        return False, f"DATE_EXPIRED: {question}"
    
    # 2. Volume Floor
    vol_24h = float(market.get('volume24hr', market.get('volume', 0)))
    if not check_volume_floor(vol_24h, min_vol=25000):
        return False, f"LOW_VOLUME: ${vol_24h:.0f}"
    
    # 3. Slippage (if order book provided)
    if order_book:
        if not check_slippage_guard(order_book, intended_size):
            return False, "SLIPPAGE_RISK"
    
    # 4. Safety Interlock (parse target outcome)
    # Default to "Yes" for binary markets
    import json
    raw_outcomes = market.get('outcomes')
    if isinstance(raw_outcomes, str):
        outcomes = json.loads(raw_outcomes)
    else:
        outcomes = raw_outcomes or []
    
    target_outcome = "Yes" if "Yes" in outcomes else (outcomes[0] if outcomes else "Unknown")
    
    # Get price estimate from market data
    best_bid = float(market.get('bestBid', 0.5))
    best_ask = float(market.get('bestAsk', 0.5))
    midpoint = (best_bid + best_ask) / 2 if (best_bid + best_ask) > 0 else 0.5
    
    if not check_safety_interlock(target_outcome, midpoint):
        return False, f"TRAP_DETECTED: {target_outcome} @ ${midpoint:.3f}"
    
    # All checks passed
    return True, "OK"

