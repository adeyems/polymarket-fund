#!/usr/bin/env python3
"""
SIMULATION TEST - Verify Full Trading Loop
===========================================
Tests the complete flow: BUY -> MONITOR -> SELL
"""

import sys
sys.path.insert(0, str(__file__).rsplit('/', 1)[0])

from core.redis_state import get_state
from core.simulation import get_simulation
from core.trade_history import get_history


def test_simulation():
    """Run a complete simulation cycle."""
    print()
    print("=" * 60)
    print("  SOVEREIGN HIVE V4 - SIMULATION TEST")
    print("=" * 60)
    print()

    # Get core components
    state = get_state()
    sim = get_simulation()
    history = get_history()

    # Reset simulation for clean test
    sim.reset(starting_balance=100.0)

    # Clear any existing positions
    for pos in state.get_positions():
        state.remove_position(pos["condition_id"])

    print("[TEST] Initial state:")
    print(f"  Balance: ${sim.virtual_balance:.2f}")
    print(f"  Positions: {len(state.get_positions())}")
    print()

    # Simulate a trade
    test_trade = {
        "condition_id": "TEST_MARKET_001",
        "question": "Will Bitcoin reach $100k by 2025?",
        "token_id": "TOKEN_YES_001",
        "outcome": "YES",
        "entry_price": 0.45,
        "size": 50,  # 50 shares
        "notional": 22.50,  # 50 * 0.45
        "anomaly_type": "VOLUME_SPIKE",
        "executed_at": "2025-01-01T12:00:00Z",
    }

    print("[TEST] Executing simulated BUY...")
    buy_result = sim.execute_buy(
        size=test_trade["size"],
        price=test_trade["entry_price"],
        condition_id=test_trade["condition_id"]
    )

    if buy_result["success"]:
        print(f"  Order ID: {buy_result['order_id']}")
        print(f"  Status: {buy_result['status']}")
        print(f"  Remaining Balance: ${buy_result['remaining_balance']:.2f}")

        # Add position to state
        test_trade["filled_price"] = test_trade["entry_price"]
        test_trade["filled_size"] = test_trade["size"]
        state.add_position(test_trade)
        print(f"  Position added to state")
    else:
        print(f"  ERROR: {buy_result['error']}")
        return

    print()

    # Simulate price movement and SELL
    print("[TEST] Simulating price movement...")
    new_price = 0.50  # Price went up (take profit)
    pnl_pct = (new_price - test_trade["entry_price"]) / test_trade["entry_price"]
    print(f"  Entry: ${test_trade['entry_price']:.3f}")
    print(f"  Current: ${new_price:.3f}")
    print(f"  P&L: {pnl_pct * 100:+.1f}%")
    print()

    print("[TEST] Executing simulated SELL (take profit)...")
    sell_result = sim.execute_sell(
        size=test_trade["size"],
        price=new_price,
        condition_id=test_trade["condition_id"]
    )

    if sell_result["success"]:
        print(f"  Proceeds: ${sell_result['proceeds']:.2f}")
        print(f"  New Balance: ${sell_result['remaining_balance']:.2f}")

        # Log to trade history
        pnl = (new_price - test_trade["entry_price"]) * test_trade["size"]
        history.log_trade({
            "condition_id": test_trade["condition_id"],
            "question": test_trade["question"],
            "entry_price": test_trade["entry_price"],
            "exit_price": new_price,
            "size": test_trade["size"],
            "notional": test_trade["notional"],
            "pnl": pnl,
            "pnl_pct": pnl_pct * 100,
            "exit_reason": "TAKE_PROFIT",
            "strategy": test_trade["anomaly_type"],
            "simulated": True,
        })

        # Remove position from state
        state.remove_position(test_trade["condition_id"])
        print(f"  Position closed")
    else:
        print(f"  ERROR: {sell_result['error']}")

    print()
    print("-" * 60)

    # Show final state
    print()
    print("[TEST] FINAL STATE:")
    sim.report()

    # Show trade history
    history.report()

    print()
    print("[TEST] Simulation complete!")
    print()


if __name__ == "__main__":
    test_simulation()
