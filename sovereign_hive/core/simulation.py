#!/usr/bin/env python3
"""
SIMULATION MODE - Virtual Trading Environment
==============================================
Allows testing the full pipeline without real funds.
Tracks virtual balance, positions, and P&L.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from .redis_state import get_state

# Default simulation settings
DEFAULT_STARTING_BALANCE = 100.0  # $100 USDC
DEFAULT_GAS_BALANCE = 5.0  # 5 POL


class SimulationState:
    """
    Virtual trading state for simulation mode.
    Tracks mock balance, positions, and calculates P&L.
    """

    def __init__(self, starting_balance: float = DEFAULT_STARTING_BALANCE):
        self.state = get_state()
        self.starting_balance = starting_balance
        self.virtual_balance = starting_balance
        self.virtual_gas = DEFAULT_GAS_BALANCE
        self.trades_executed = 0
        self.total_invested = 0.0
        self.total_returned = 0.0
        self._persistence_file = Path(__file__).parent.parent / "simulation_state.json"

        # Load existing simulation state
        self._load()

    def _load(self):
        """Load simulation state from disk."""
        if self._persistence_file.exists():
            try:
                with open(self._persistence_file) as f:
                    data = json.load(f)
                self.virtual_balance = data.get("balance", self.starting_balance)
                self.virtual_gas = data.get("gas", DEFAULT_GAS_BALANCE)
                self.trades_executed = data.get("trades_executed", 0)
                self.total_invested = data.get("total_invested", 0.0)
                self.total_returned = data.get("total_returned", 0.0)
                print(f"[SIM] Loaded state: ${self.virtual_balance:.2f} balance")
            except Exception as e:
                print(f"[SIM] Load error: {e}")

    def _save(self):
        """Save simulation state to disk."""
        try:
            data = {
                "balance": self.virtual_balance,
                "gas": self.virtual_gas,
                "trades_executed": self.trades_executed,
                "total_invested": self.total_invested,
                "total_returned": self.total_returned,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            with open(self._persistence_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SIM] Save error: {e}")

    def get_balance(self) -> dict:
        """Get virtual balances."""
        return {
            "usdc": self.virtual_balance,
            "pol": self.virtual_gas
        }

    def execute_buy(self, size: float, price: float, condition_id: str) -> dict:
        """Execute a simulated buy order."""
        notional = size * price

        if notional > self.virtual_balance:
            return {
                "success": False,
                "error": f"Insufficient balance: need ${notional:.2f}, have ${self.virtual_balance:.2f}"
            }

        # Deduct balance
        self.virtual_balance -= notional
        self.total_invested += notional
        self.trades_executed += 1

        # Simulate gas cost
        self.virtual_gas -= 0.01

        self._save()

        return {
            "success": True,
            "order_id": f"SIM_{condition_id[:16]}_{self.trades_executed}",
            "status": "FILLED",
            "filled_price": price,
            "filled_size": size,
            "notional": notional,
            "remaining_balance": self.virtual_balance
        }

    def execute_sell(self, size: float, price: float, condition_id: str) -> dict:
        """Execute a simulated sell order."""
        proceeds = size * price

        # Add to balance
        self.virtual_balance += proceeds
        self.total_returned += proceeds

        # Simulate gas cost
        self.virtual_gas -= 0.01

        self._save()

        return {
            "success": True,
            "order_id": f"SIM_SELL_{condition_id[:16]}",
            "status": "FILLED",
            "filled_price": price,
            "filled_size": size,
            "proceeds": proceeds,
            "remaining_balance": self.virtual_balance
        }

    def settle_position(self, condition_id: str, outcome: str, entry_price: float, size: float):
        """
        Settle a position when market resolves.
        outcome: "WIN" (price goes to 1.0) or "LOSE" (price goes to 0)
        """
        if outcome == "WIN":
            # Position worth $1 per share
            payout = size * 1.0
            profit = payout - (size * entry_price)
        else:
            # Position worthless
            payout = 0
            profit = -(size * entry_price)

        self.virtual_balance += payout
        self.total_returned += payout

        self._save()

        return {
            "outcome": outcome,
            "payout": payout,
            "profit": profit,
            "new_balance": self.virtual_balance
        }

    def get_pnl(self) -> dict:
        """Calculate profit/loss statistics."""
        positions = self.state.get_positions()

        # Calculate unrealized P&L (mark to market)
        unrealized = 0.0
        for pos in positions:
            entry = pos.get("entry_price", 0)
            size = pos.get("size", 0)
            # For simulation, we'd need current price - use entry as estimate
            unrealized += size * entry  # Placeholder

        realized = self.total_returned - self.total_invested
        total_pnl = realized + (self.virtual_balance - self.starting_balance + self.total_invested - self.total_returned)

        return {
            "starting_balance": self.starting_balance,
            "current_balance": self.virtual_balance,
            "total_invested": self.total_invested,
            "total_returned": self.total_returned,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": total_pnl,
            "trades": self.trades_executed,
            "positions": len(positions)
        }

    def reset(self, starting_balance: float = None):
        """Reset simulation to starting state."""
        self.virtual_balance = starting_balance or self.starting_balance
        self.virtual_gas = DEFAULT_GAS_BALANCE
        self.trades_executed = 0
        self.total_invested = 0.0
        self.total_returned = 0.0
        self._save()
        print(f"[SIM] Reset to ${self.virtual_balance:.2f}")

    def report(self):
        """Print simulation report."""
        pnl = self.get_pnl()

        print()
        print("=" * 50)
        print("  SIMULATION REPORT")
        print("=" * 50)
        print(f"  Starting Balance:  ${pnl['starting_balance']:.2f}")
        print(f"  Current Balance:   ${pnl['current_balance']:.2f}")
        print(f"  Total Invested:    ${pnl['total_invested']:.2f}")
        print(f"  Total Returned:    ${pnl['total_returned']:.2f}")
        print("-" * 50)
        print(f"  Realized P&L:      ${pnl['realized_pnl']:+.2f}")
        print(f"  Total P&L:         ${pnl['total_pnl']:+.2f}")
        print(f"  Trades:            {pnl['trades']}")
        print(f"  Open Positions:    {pnl['positions']}")
        print("=" * 50)
        print()


# Singleton
_sim_state = None


def get_simulation() -> SimulationState:
    global _sim_state
    if _sim_state is None:
        _sim_state = SimulationState()
    return _sim_state
