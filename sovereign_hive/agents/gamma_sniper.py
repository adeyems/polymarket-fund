#!/usr/bin/env python3
"""
AGENT GAMMA - THE SNIPER
========================
Capital Deployment Engine. Executes on vetted trades.

Workflow:
1. Read VETTED trades from blackboard
2. Check wallet balance
3. Optimize order (maker vs taker)
4. Execute and log
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

BLACKBOARD_PATH = Path(__file__).parent.parent / "blackboard.json"
ENV_PATH = Path(__file__).parent.parent.parent / ".env"

# Load environment
load_dotenv(ENV_PATH)

# Execution constraints
MIN_ORDER_SIZE = 5.0           # Polymarket minimum
MAX_PRICE_ARBITRAGE = 0.998    # Don't buy arbitrage above this
MAKER_OFFSET = 0.001           # Place limit below ask for maker fee


def load_blackboard() -> dict:
    """Load the shared blackboard."""
    try:
        with open(BLACKBOARD_PATH, "r") as f:
            return json.load(f)
    except:
        return {"opportunities": [], "vetted_trades": [], "active_positions": [], "risk_state": "HEALTHY"}


def save_blackboard(blackboard: dict):
    """Save the blackboard."""
    with open(BLACKBOARD_PATH, "w") as f:
        json.dump(blackboard, f, indent=2)


def get_wallet_balance() -> float:
    """Get current USDC.e balance from chain."""
    try:
        from web3 import Web3

        WALLET = os.getenv("WALLET_ADDRESS", "0xb22028EA4E841CA321eb917C706C931a94b564AB")
        USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

        w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
        erc20_abi = [{'inputs': [{'name': 'account', 'type': 'address'}], 'name': 'balanceOf', 'outputs': [{'name': '', 'type': 'uint256'}], 'stateMutability': 'view', 'type': 'function'}]

        usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=erc20_abi)
        balance = usdc.functions.balanceOf(Web3.to_checksum_address(WALLET)).call() / 1e6
        return balance
    except Exception as e:
        print(f"[GAMMA] Balance check error: {e}")
        return 0.0


def get_market_token_id(condition_id: str) -> str:
    """Fetch the YES token ID for a market."""
    try:
        import requests
        resp = requests.get(
            f"https://gamma-api.polymarket.com/markets?conditionId={condition_id}",
            timeout=10
        )
        if resp.status_code == 200:
            markets = resp.json()
            if markets:
                token_ids = json.loads(markets[0].get("clobTokenIds", "[]"))
                if token_ids:
                    return token_ids[0]  # YES token
        return ""
    except:
        return ""


def calculate_order(trade: dict, available_cash: float) -> dict:
    """
    Calculate optimal order parameters.
    Returns order spec or None if not executable.
    """
    anomaly_type = trade.get("anomaly_type", "")
    best_ask = trade.get("best_ask", 0)
    best_bid = trade.get("best_bid", 0)
    condition_id = trade.get("condition_id", "")

    # Get token ID
    token_id = get_market_token_id(condition_id)
    if not token_id:
        return None

    # Determine order price based on strategy
    if anomaly_type == "ARBITRAGE":
        # For arbitrage, we want certainty - hit the ask or slightly below
        if best_ask > MAX_PRICE_ARBITRAGE:
            print(f"[GAMMA] Price ${best_ask:.3f} > ${MAX_PRICE_ARBITRAGE} limit. Skipping.")
            return None
        # Place as maker just below ask
        order_price = round(best_ask - MAKER_OFFSET, 3)
        order_price = max(order_price, best_bid + 0.001)  # Don't go below bid
    else:
        # For other types, join the bid
        order_price = best_bid

    # Calculate size
    max_notional = available_cash - 0.50  # Keep buffer
    if max_notional < MIN_ORDER_SIZE * order_price:
        print(f"[GAMMA] Insufficient funds. Need ${MIN_ORDER_SIZE * order_price:.2f}, have ${available_cash:.2f}")
        return None

    order_size = min(max_notional / order_price, 100)  # Cap at 100 shares
    order_size = max(order_size, MIN_ORDER_SIZE)  # Minimum 5 shares

    return {
        "token_id": token_id,
        "condition_id": condition_id,
        "side": "BUY",
        "price": order_price,
        "size": round(order_size, 2),
        "notional": round(order_size * order_price, 2),
        "strategy": anomaly_type
    }


def execute_order(order: dict, dry_run: bool = True) -> dict:
    """
    Execute an order on Polymarket CLOB.

    Args:
        order: Order specification
        dry_run: If True, simulate only (no real execution)

    Returns:
        Execution result
    """
    if dry_run:
        print(f"[GAMMA] 🔫 DRY RUN - Would execute:")
        print(f"        Token: {order['token_id'][:20]}...")
        print(f"        Side: {order['side']}")
        print(f"        Price: ${order['price']:.3f}")
        print(f"        Size: {order['size']:.2f} shares")
        print(f"        Notional: ${order['notional']:.2f}")
        return {
            "success": True,
            "dry_run": True,
            "order_id": "DRY_RUN_" + order["condition_id"][:16],
            "status": "SIMULATED"
        }

    # === LIVE EXECUTION ===
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds, OrderArgs

        creds = ApiCreds(
            api_key=os.getenv("CLOB_API_KEY"),
            api_secret=os.getenv("CLOB_SECRET"),
            api_passphrase=os.getenv("CLOB_PASSPHRASE")
        )

        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=os.getenv("POLYMARKET_PRIVATE_KEY"),
            creds=creds
        )

        o_args = OrderArgs(
            price=order["price"],
            size=order["size"],
            side="BUY",
            token_id=order["token_id"]
        )

        resp = client.create_and_post_order(o_args)
        print(f"[GAMMA] 🎯 ORDER PLACED: {resp}")

        return {
            "success": resp.get("success", False),
            "dry_run": False,
            "order_id": resp.get("orderID", ""),
            "status": resp.get("status", "UNKNOWN"),
            "response": resp
        }

    except Exception as e:
        print(f"[GAMMA] ❌ Execution error: {e}")
        return {
            "success": False,
            "dry_run": False,
            "error": str(e)
        }


def run_sniper(dry_run: bool = True):
    """Main sniper loop - execute on vetted trades."""
    print(f"\n{'='*60}")
    print(f"[GAMMA SNIPER] Initiated at {datetime.now(timezone.utc).isoformat()}")
    print(f"[GAMMA] Mode: {'DRY RUN' if dry_run else '🔴 LIVE EXECUTION'}")
    print(f"{'='*60}")

    blackboard = load_blackboard()

    # Check risk state
    if blackboard.get("risk_state") != "HEALTHY":
        print(f"[GAMMA] ⚠️ Risk state is {blackboard.get('risk_state')}. Aborting.")
        return

    vetted_trades = blackboard.get("vetted_trades", [])
    active_positions = blackboard.get("active_positions", [])

    # Filter to unexecuted vetted trades
    executed_ids = {p.get("condition_id") for p in active_positions}
    pending_trades = [t for t in vetted_trades if t["condition_id"] not in executed_ids]

    print(f"[GAMMA] Found {len(pending_trades)} vetted trades pending execution")

    if not pending_trades:
        print("[GAMMA] No trades to execute.")
        return

    # Get wallet balance
    balance = get_wallet_balance()
    print(f"[GAMMA] Wallet balance: ${balance:.2f}")

    if balance < 2.0:
        print("[GAMMA] ⚠️ Insufficient balance (< $2). Aborting.")
        return

    available_cash = balance

    # Sort by confidence/score
    pending_trades.sort(key=lambda x: x.get("analyst_confidence", 0), reverse=True)

    for trade in pending_trades:
        if available_cash < 2.0:
            print("[GAMMA] Out of capital. Stopping.")
            break

        question = trade.get("question", "Unknown")[:50]
        print(f"\n[GAMMA] Processing: {question}...")

        # Calculate order
        order = calculate_order(trade, available_cash)
        if not order:
            continue

        # Execute
        result = execute_order(order, dry_run=dry_run)

        if result["success"]:
            # Record position
            position = {
                "condition_id": trade["condition_id"],
                "question": trade["question"],
                "entry_price": order["price"],
                "size": order["size"],
                "notional": order["notional"],
                "order_id": result["order_id"],
                "status": result["status"],
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "dry_run": dry_run
            }
            active_positions.append(position)
            available_cash -= order["notional"]

    # Save blackboard
    blackboard["active_positions"] = active_positions
    blackboard["last_execution"] = datetime.now(timezone.utc).isoformat()
    save_blackboard(blackboard)

    print(f"\n[GAMMA] === EXECUTION COMPLETE ===")
    print(f"  Active Positions: {len(active_positions)}")
    print(f"  Remaining Cash: ${available_cash:.2f}")


def main():
    import sys

    dry_run = True
    if len(sys.argv) > 1:
        if sys.argv[1] == "--live":
            dry_run = False
            print("[GAMMA] ⚠️  LIVE MODE ENABLED - Real orders will be placed!")
        elif sys.argv[1] == "--once":
            dry_run = True

    run_sniper(dry_run=dry_run)


if __name__ == "__main__":
    main()
