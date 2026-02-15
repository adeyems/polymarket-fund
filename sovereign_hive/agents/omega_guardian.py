#!/usr/bin/env python3
"""
AGENT OMEGA - THE GUARDIAN
==========================
Compliance & Risk Engine. Watches the other agents.

Responsibilities:
1. Monitor active positions for settlement
2. Kill trades exceeding risk limits
3. Track gas/POL balance
4. Auto-recycle capital when markets resolve
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

BLACKBOARD_PATH = Path(__file__).parent.parent / "blackboard.json"
ENV_PATH = Path(__file__).parent.parent.parent / ".env"

load_dotenv(ENV_PATH)

# Risk Limits
MAX_SINGLE_POSITION = 10.0     # Max $10 in any single market
MAX_TOTAL_EXPOSURE = 50.0      # Max $50 total deployed
MIN_GAS_BALANCE = 1.0          # Minimum POL for gas
MAX_LOSS_PERCENT = 20.0        # Kill trade if down > 20%


def load_blackboard() -> dict:
    try:
        with open(BLACKBOARD_PATH, "r") as f:
            return json.load(f)
    except:
        return {"opportunities": [], "vetted_trades": [], "active_positions": [], "risk_state": "HEALTHY"}


def save_blackboard(blackboard: dict):
    with open(BLACKBOARD_PATH, "w") as f:
        json.dump(blackboard, f, indent=2)


def get_balances() -> dict:
    """Get wallet balances (USDC.e and POL)."""
    try:
        from web3 import Web3

        WALLET = os.getenv("WALLET_ADDRESS", "0xb22028EA4E841CA321eb917C706C931a94b564AB")
        USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

        w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
        erc20_abi = [{'inputs': [{'name': 'account', 'type': 'address'}], 'name': 'balanceOf', 'outputs': [{'name': '', 'type': 'uint256'}], 'stateMutability': 'view', 'type': 'function'}]

        usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=erc20_abi)
        usdc_balance = usdc.functions.balanceOf(Web3.to_checksum_address(WALLET)).call() / 1e6
        pol_balance = w3.eth.get_balance(Web3.to_checksum_address(WALLET)) / 1e18

        return {
            "usdc": usdc_balance,
            "pol": pol_balance
        }
    except Exception as e:
        print(f"[OMEGA] Balance error: {e}")
        return {"usdc": 0, "pol": 0}


def check_market_status(condition_id: str) -> dict:
    """Check if a market has resolved."""
    try:
        import requests
        resp = requests.get(
            f"https://gamma-api.polymarket.com/markets?conditionId={condition_id}",
            timeout=10
        )
        if resp.status_code == 200:
            markets = resp.json()
            if markets:
                m = markets[0]
                return {
                    "closed": m.get("closed", False),
                    "resolved": m.get("closed", False),
                    "best_bid": float(m.get("bestBid") or 0),
                    "best_ask": float(m.get("bestAsk") or 0),
                    "last_price": float(m.get("lastTradePrice") or 0)
                }
        return {"closed": False, "resolved": False}
    except:
        return {"closed": False, "resolved": False}


def calculate_pnl(position: dict, current_price: float) -> dict:
    """Calculate P&L for a position."""
    entry_price = position.get("entry_price", 0)
    size = position.get("size", 0)

    if entry_price == 0:
        return {"pnl": 0, "pnl_pct": 0}

    current_value = size * current_price
    entry_value = size * entry_price
    pnl = current_value - entry_value
    pnl_pct = (current_price - entry_price) / entry_price * 100

    return {
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "current_value": round(current_value, 2)
    }


def run_guardian():
    """Main guardian monitoring loop."""
    print(f"\n{'='*60}")
    print(f"[OMEGA GUARDIAN] Scan at {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}")

    blackboard = load_blackboard()

    # === 1. CHECK WALLET HEALTH ===
    balances = get_balances()
    print(f"\n[OMEGA] 💰 WALLET STATUS")
    print(f"  USDC.e: ${balances['usdc']:.2f}")
    print(f"  POL: {balances['pol']:.4f}")

    risk_state = "HEALTHY"
    alerts = []

    if balances["pol"] < MIN_GAS_BALANCE:
        alerts.append(f"⚠️ LOW GAS: {balances['pol']:.4f} POL (min: {MIN_GAS_BALANCE})")
        risk_state = "WARNING"

    # === 2. CHECK ACTIVE POSITIONS ===
    active_positions = blackboard.get("active_positions", [])
    print(f"\n[OMEGA] 📊 ACTIVE POSITIONS: {len(active_positions)}")

    total_exposure = 0
    resolved_positions = []
    risk_positions = []

    for pos in active_positions:
        condition_id = pos.get("condition_id", "")
        question = pos.get("question", "Unknown")[:40]

        # Check market status
        status = check_market_status(condition_id)

        if status["closed"]:
            resolved_positions.append(pos)
            print(f"  🎉 RESOLVED: {question}")
            continue

        # Calculate P&L
        current_price = status.get("last_price", pos.get("entry_price", 0))
        pnl_data = calculate_pnl(pos, current_price)

        total_exposure += pnl_data["current_value"]

        # Check for excessive loss
        if pnl_data["pnl_pct"] < -MAX_LOSS_PERCENT:
            risk_positions.append(pos)
            alerts.append(f"🔴 STOP LOSS: {question} down {pnl_data['pnl_pct']:.1f}%")
            risk_state = "CRITICAL"

        print(f"  • {question}")
        print(f"    Entry: ${pos.get('entry_price', 0):.3f} | Now: ${current_price:.3f} | P&L: {pnl_data['pnl_pct']:+.1f}%")

    # === 3. CHECK EXPOSURE LIMITS ===
    if total_exposure > MAX_TOTAL_EXPOSURE:
        alerts.append(f"⚠️ OVER EXPOSED: ${total_exposure:.2f} > ${MAX_TOTAL_EXPOSURE} limit")
        risk_state = "WARNING"

    # === 4. HANDLE RESOLVED POSITIONS ===
    if resolved_positions:
        print(f"\n[OMEGA] 🎯 SETTLED MARKETS: {len(resolved_positions)}")
        # Remove resolved from active
        active_ids = {p["condition_id"] for p in resolved_positions}
        blackboard["active_positions"] = [
            p for p in active_positions if p["condition_id"] not in active_ids
        ]
        # Signal scout to find new opportunities
        blackboard["capital_freed"] = True

    # === 5. UPDATE RISK STATE ===
    blackboard["risk_state"] = risk_state
    blackboard["last_guardian_scan"] = datetime.now(timezone.utc).isoformat()
    blackboard["wallet_balances"] = balances
    blackboard["total_exposure"] = round(total_exposure, 2)

    # === 6. REPORT ALERTS ===
    if alerts:
        print(f"\n[OMEGA] 🚨 ALERTS:")
        for alert in alerts:
            print(f"  {alert}")
        blackboard["alerts"] = alerts
    else:
        print(f"\n[OMEGA] ✅ All systems healthy")
        blackboard["alerts"] = []

    save_blackboard(blackboard)

    print(f"\n[OMEGA] Risk State: {risk_state}")
    print(f"[OMEGA] Total Exposure: ${total_exposure:.2f}")

    return {
        "risk_state": risk_state,
        "alerts": alerts,
        "resolved_count": len(resolved_positions),
        "total_exposure": total_exposure
    }


def emergency_halt():
    """Emergency stop - sets risk state to HALTED."""
    blackboard = load_blackboard()
    blackboard["risk_state"] = "HALTED"
    blackboard["halt_reason"] = "Manual emergency halt"
    blackboard["halted_at"] = datetime.now(timezone.utc).isoformat()
    save_blackboard(blackboard)
    print("[OMEGA] 🛑 EMERGENCY HALT ACTIVATED")


def resume_trading():
    """Resume trading after halt."""
    blackboard = load_blackboard()
    blackboard["risk_state"] = "HEALTHY"
    blackboard["halt_reason"] = None
    save_blackboard(blackboard)
    print("[OMEGA] ✅ Trading resumed")


def main():
    import sys
    import time

    if len(sys.argv) > 1:
        if sys.argv[1] == "--halt":
            emergency_halt()
        elif sys.argv[1] == "--resume":
            resume_trading()
        elif sys.argv[1] == "--once":
            run_guardian()
    else:
        # Continuous monitoring
        while True:
            try:
                run_guardian()
                print(f"\n[OMEGA] Sleeping 300s until next scan...")
                time.sleep(300)
            except KeyboardInterrupt:
                print("\n[OMEGA] Guardian terminated.")
                break


if __name__ == "__main__":
    main()
