
import asyncio
from py_clob_client.clob_types import OrderArgs
from py_clob_client.exceptions import PolyApiException

# Constants
BUY = "BUY"
SELL = "SELL"

async def place_limit_order(client, token_id: str, price: float, size: float, side: str = "BUY", mock: bool = False):
    """
    Submits a signed Limit Order to the CLOB.
    Wraps create_and_post_order with error handling and logging.
    """
    if size <= 0:
        return {"status": "SKIPPED", "reason": "Size <= 0"}
    
    order_data = {
        "price": price,
        "size": size,
        "side": side,
        "token_id": token_id
    }

    if mock:
        print(f"[MOCK] Order Placed: {order_data}")
        return {"status": "MOCK_SUCCESS", "data": order_data}

    try:
        print(f"[EXEC] Sending Order: {order_data}")
        
        args = OrderArgs(
            price=price,
            size=size,
            side=side,
            token_id=token_id
        )
        
        # Execute via Client (which should use the patched connection under the hood)
        resp = await asyncio.to_thread(client.create_and_post_order, args)
        
        print(f"[EXEC] Response: {resp}")
        return {"status": "LIVE_SUCCESS", "response": resp, "data": order_data}

    except Exception as e:
        print(f"[EXEC] Error: {e}")
        error_details = parse_clob_error(e)
        if error_details:
             print(f"[DEEP-LOG] {error_details}")
             
        return {"status": "ORDER_FAILED", "error": str(e)}

def parse_clob_error(e):
    """Extracts readable error messages from complex CLOB exceptions."""
    try:
        if hasattr(e, 'status_code'):
            return f"Status: {e.status_code}"
        
        if hasattr(e, 'error_message'):
            msg = e.error_message
            if hasattr(msg, 'text'):
                return f"Raw Error Body: {msg.text}"
            return f"Raw Error: {msg}"
            
    except:
        return None
    return None

def calculate_notional_size(price: float, notional_usd: float = 5.05):
    """Calculates quantity for a target USD deployment."""
    if price <= 0: return 0.0
    return round(notional_usd / price, 2)
