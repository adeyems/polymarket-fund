#!/usr/bin/env python3
"""
AI Execute Decision — Runs CLOB actions based on dual-brain consensus.

Accepts JSON on stdin describing the action. Executes and returns result.
Called by the monitor agent ONLY after ai_position_review.py + consensus.

Usage (EC2):
    echo '{"action":"CANCEL_ORDER","order_id":"0xabc..."}' | \
        sudo bash -c 'source /run/sovereign-hive/env && cd /app/sovereign-hive && \
        ./venv/bin/python tools/ai_execute_decision.py'

Supported actions:
    CANCEL_ORDER  - Cancel a specific order by ID
    ADJUST_SELL   - Cancel old sell, post new sell at different price
    EMERGENCY_EXIT - Cross spread to exit fast (taker order)

Safety:
    - ADJUST_SELL enforces sell_price >= 90% of entry price
    - EMERGENCY_EXIT enforces min_price floor
    - All actions logged to /var/log/sovereign-hive/autonomous_actions.log
    - NegRisk balance resync before any sell
"""
import os
import sys
import json
import time
from datetime import datetime, timezone

# ── Bootstrap ──────────────────────────────────────────────────────────
for envpath in ["/run/sovereign-hive/env", "/app/sovereign-hive/.env", ".env"]:
    if os.path.exists(envpath):
        try:
            from dotenv import load_dotenv
            load_dotenv(envpath)
        except ImportError:
            with open(envpath) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip("'\"")

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        ApiCreds, OrderArgs, OrderType,
        BalanceAllowanceParams, AssetType,
    )
except ImportError as e:
    print(json.dumps({"error": f"missing dependency: {e}",
                       "timestamp": datetime.now(timezone.utc).isoformat()}))
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────
WALLET_KEY = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
LOG_FILE = "/var/log/sovereign-hive/autonomous_actions.log"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTFOLIO_DIR = os.path.join(PROJECT_ROOT, "sovereign_hive", "data")

# Safety: minimum sell price = 90% of entry
MIN_SELL_PCT = 0.90


def get_clob_client():
    """Initialize CLOB client."""
    creds = ApiCreds(
        api_key=os.environ.get("CLOB_API_KEY", ""),
        api_secret=os.environ.get("CLOB_SECRET", ""),
        api_passphrase=os.environ.get("CLOB_PASSPHRASE", "")
    )
    return ClobClient(
        host="https://clob.polymarket.com", chain_id=137,
        key=WALLET_KEY, creds=creds, signature_type=0,
    )


def log_action(action_input, result):
    """Append action to autonomous actions log."""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input": action_input,
            "result": result,
        }
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[EXEC] Log warning: {e}", file=sys.stderr)


def load_portfolio():
    """Load portfolio to get entry prices for safety checks."""
    for name in ["portfolio_market_maker.json", "portfolio_live.json", "portfolio.json"]:
        path = os.path.join(PORTFOLIO_DIR, name)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return {}


def get_entry_price(portfolio, token_id):
    """Find entry price for a token from portfolio."""
    for cid, pos in portfolio.get("positions", {}).items():
        if pos.get("token_id") == token_id:
            return float(pos.get("entry_price", 0))
    return 0.0


def resync_negrisk_balance(client, token_id):
    """Force CLOB to resync balance cache (fixes NegRisk stale cache bug)."""
    try:
        params = BalanceAllowanceParams(
            asset_type=AssetType.CONDITIONAL,
            token_id=token_id,
            signature_type=0,
        )
        client.update_balance_allowance(params)
    except Exception as e:
        print(f"[EXEC] NegRisk resync warning: {e}", file=sys.stderr)


def cancel_order(client, order_id):
    """Cancel a single order."""
    try:
        resp = client.cancel(order_id)
        cancelled = resp.get("canceled", [])
        success = order_id in cancelled if isinstance(cancelled, list) else bool(cancelled)
        return {"success": success, "cancelled_id": order_id, "response": str(resp)[:200]}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def post_sell_order(client, token_id, price, size, post_only=True):
    """Post a GTC sell limit order."""
    try:
        fee_bps = client.get_fee_rate_bps(token_id)
        o_args = OrderArgs(
            price=price,
            size=round(size, 2),
            side="SELL",
            token_id=token_id,
            fee_rate_bps=int(fee_bps),
        )
        signed_order = client.create_order(o_args)
        resp = client.post_order(signed_order, OrderType.GTC, post_only)
        order_id = resp.get("orderID", "")
        return {
            "success": bool(order_id),
            "order_id": order_id,
            "price": price,
            "size": round(size, 2),
            "post_only": post_only,
        }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def execute_action(client, action_input, portfolio):
    """Execute a single action and return result."""
    action = action_input.get("action", "")

    if action == "CANCEL_ORDER":
        order_id = action_input.get("order_id", "")
        if not order_id:
            return {"success": False, "error": "Missing order_id"}
        return cancel_order(client, order_id)

    elif action == "ADJUST_SELL":
        cancel_id = action_input.get("cancel_order_id", "")
        token_id = action_input.get("token_id", "")
        new_price = float(action_input.get("new_price", 0))
        size = float(action_input.get("size", 0))

        if not all([cancel_id, token_id, new_price > 0, size > 0]):
            return {"success": False, "error": "Missing required fields for ADJUST_SELL"}

        # Safety: enforce minimum sell price (90% of entry)
        entry_price = get_entry_price(portfolio, token_id)
        if entry_price > 0:
            min_price = round(entry_price * MIN_SELL_PCT, 3)
            if new_price < min_price:
                return {
                    "success": False,
                    "error": f"Price ${new_price} below safety floor ${min_price} (90% of entry ${entry_price})",
                    "blocked_by": "SAFETY_FLOOR",
                }

        # Step 1: Cancel old order
        cancel_result = cancel_order(client, cancel_id)
        if not cancel_result.get("success"):
            return {"success": False, "error": f"Cancel failed: {cancel_result.get('error', 'unknown')}",
                    "cancel_result": cancel_result}

        # Brief pause for CLOB to process cancellation
        time.sleep(0.5)

        # Step 2: Resync NegRisk balance cache
        resync_negrisk_balance(client, token_id)

        # Step 3: Post new sell order (post_only=False to allow taker if needed)
        post_only = action_input.get("post_only", True)
        sell_result = post_sell_order(client, token_id, new_price, size, post_only)

        return {
            "success": sell_result.get("success", False),
            "cancel_result": cancel_result,
            "new_order": sell_result,
            "adjusted_from": cancel_id,
            "new_price": new_price,
        }

    elif action == "EMERGENCY_EXIT":
        token_id = action_input.get("token_id", "")
        size = float(action_input.get("size", 0))
        min_price = float(action_input.get("min_price", 0))

        if not all([token_id, size > 0]):
            return {"success": False, "error": "Missing required fields for EMERGENCY_EXIT"}

        # Get best bid from order book
        try:
            book = client.get_order_book(token_id)
            best_bid = float(book.bids[0].price) if book.bids else 0.0
        except Exception:
            best_bid = 0.0

        if best_bid <= 0:
            return {"success": False, "error": "No bids in order book"}

        # Enforce min_price floor
        exit_price = max(best_bid, min_price)

        # Resync and post taker sell
        resync_negrisk_balance(client, token_id)
        sell_result = post_sell_order(client, token_id, exit_price, size, post_only=False)

        return {
            "success": sell_result.get("success", False),
            "exit_price": exit_price,
            "best_bid": best_bid,
            "min_price_enforced": exit_price > best_bid,
            "order": sell_result,
        }

    else:
        return {"success": False, "error": f"Unknown action: {action}"}


def main():
    # Read action from stdin
    if sys.stdin.isatty():
        print(json.dumps({"error": "No input on stdin. Pipe a JSON action."}))
        sys.exit(1)

    try:
        raw = sys.stdin.read()
        action_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        print(json.dumps({"error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    if not WALLET_KEY:
        print(json.dumps({"error": "POLYMARKET_PRIVATE_KEY not set"}))
        sys.exit(1)

    client = get_clob_client()
    portfolio = load_portfolio()

    # Execute
    result = execute_action(client, action_input, portfolio)

    # Log to file
    log_action(action_input, result)

    # Output JSON
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action_input.get("action", "UNKNOWN"),
        "result": result,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
