#!/usr/bin/env python3
"""
ASYNC GAMMA SNIPER - Complete Position Management
==================================================
BUY execution, SELL exits, and market resolution.
The bot that only buys is a money incinerator.
"""

import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Optional, List
import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from core.redis_state import get_state
from core.async_executor import get_executor
from core.simulation import get_simulation
from core.trade_history import get_history


# Execution Constraints
MIN_ORDER_SIZE = 5.0
MAX_PRICE_ARBITRAGE = 0.998
MAKER_OFFSET = 0.001

# Exit Strategy Constants
DEFAULT_TAKE_PROFIT = 0.05   # +5% profit target
DEFAULT_STOP_LOSS = -0.15    # -15% stop loss
ARBITRAGE_TAKE_PROFIT = 0.02 # +2% for arb (tight)

# Order Status Constants
STATUS_PENDING = "PENDING"
STATUS_LIVE = "LIVE"
STATUS_MATCHED = "MATCHED"
STATUS_FILLED = "FILLED"
STATUS_CANCELLED = "CANCELLED"
STATUS_CLOSED = "CLOSED"  # Position exited


class AsyncGammaSniper:
    """
    Non-blocking order execution.
    """

    def __init__(self, dry_run: bool = True):
        self.state = get_state()
        self.executor = get_executor()
        self.simulation = get_simulation() if dry_run else None
        self.history = get_history()
        self.dry_run = dry_run
        self.running = False
        self._pending_orders = {}  # order_id -> position info

    async def get_balance(self) -> float:
        """Get USDC balance (simulation or real)."""
        # Use simulation balance in dry run mode
        if self.dry_run and self.simulation:
            return self.simulation.get_balance()["usdc"]

        # Try cached first
        balances = self.state._get("hive:balances")
        if balances:
            import json
            return json.loads(balances).get("usdc", 0)

        # Fetch fresh from chain
        try:
            from web3 import Web3
            import os

            WALLET = os.getenv("WALLET_ADDRESS", "0xb22028EA4E841CA321eb917C706C931a94b564AB")
            USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

            w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
            erc20_abi = [{'inputs': [{'name': 'account', 'type': 'address'}], 'name': 'balanceOf', 'outputs': [{'name': '', 'type': 'uint256'}], 'stateMutability': 'view', 'type': 'function'}]

            usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=erc20_abi)
            balance = usdc.functions.balanceOf(Web3.to_checksum_address(WALLET)).call() / 1e6
            return balance
        except:
            return 0

    def calculate_order(self, trade: dict, available: float) -> Optional[dict]:
        """Calculate optimal order parameters."""
        anomaly_type = trade.get("anomaly_type", "")
        best_ask = trade.get("best_ask", 0)
        best_bid = trade.get("best_bid", 0)
        token_id = trade.get("token_id", "")

        if not token_id:
            return None

        # Price based on strategy
        if anomaly_type == "ARBITRAGE":
            if best_ask > MAX_PRICE_ARBITRAGE:
                return None
            price = round(best_ask - MAKER_OFFSET, 3)
            price = max(price, best_bid + 0.001)
        else:
            price = best_bid

        if price <= 0:
            return None

        # Size
        max_notional = available - 0.50
        if max_notional < MIN_ORDER_SIZE * price:
            return None

        size = min(max_notional / price, 100)
        size = max(size, MIN_ORDER_SIZE)

        return {
            "token_id": token_id,
            "condition_id": trade["condition_id"],
            "side": "BUY",
            "price": price,
            "size": round(size, 2),
            "notional": round(size * price, 2),
            "strategy": anomaly_type
        }

    async def execute_vetted(self):
        """Execute all vetted trades."""
        # Check risk state
        if self.state.get_risk_state() != "HEALTHY":
            print(f"[GAMMA] Risk state not HEALTHY. Skipping.")
            return

        # Get vetted trades not yet executed
        vetted = self.state.get_vetted()
        positions = self.state.get_positions()
        executed_ids = {p["condition_id"] for p in positions}

        pending = [t for t in vetted if t["condition_id"] not in executed_ids]

        if not pending:
            return

        # Get balance
        balance = await self.get_balance()
        print(f"[GAMMA] Balance: ${balance:.2f}, Pending: {len(pending)}")

        if balance < 2.0:
            print("[GAMMA] Insufficient balance")
            return

        available = balance

        # Sort by confidence
        pending.sort(key=lambda x: x.get("analyst_confidence", 0), reverse=True)

        for trade in pending:
            if available < 2.0:
                break

            order = self.calculate_order(trade, available)
            if not order:
                continue

            print(f"[GAMMA] Executing: {trade['question'][:40]}...")

            # Use simulation for dry run, real executor for live
            if self.dry_run and self.simulation:
                result = self.simulation.execute_buy(
                    size=order["size"],
                    price=order["price"],
                    condition_id=order["condition_id"]
                )
            else:
                result = await self.executor.execute_order(
                    token_id=order["token_id"],
                    side=order["side"],
                    price=order["price"],
                    size=order["size"],
                    dry_run=self.dry_run
                )

            if result["success"]:
                # Record position
                position = {
                    "condition_id": trade["condition_id"],
                    "question": trade["question"],
                    "entry_price": order["price"],
                    "size": order["size"],
                    "notional": order["notional"],
                    "order_id": result.get("order_id", ""),
                    "status": result.get("status", "FILLED" if self.dry_run else ""),
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                    "dry_run": self.dry_run,
                    "simulated": self.dry_run
                }

                # Calculate exit targets based on strategy
                strategy = trade.get("anomaly_type", "")
                if strategy == "ARBITRAGE":
                    take_profit = order["price"] * (1 + ARBITRAGE_TAKE_PROFIT)
                    stop_loss = order["price"] * (1 + DEFAULT_STOP_LOSS)
                else:
                    take_profit = order["price"] * (1 + DEFAULT_TAKE_PROFIT)
                    stop_loss = order["price"] * (1 + DEFAULT_STOP_LOSS)

                position["take_profit"] = round(take_profit, 3)
                position["stop_loss"] = round(stop_loss, 3)
                position["token_id"] = order["token_id"]

                self.state.add_position(position)
                self.state.remove_vetted(trade["condition_id"])
                available -= order["notional"]

                self.state.incr_metric("gamma_executed")
                mode = "[SIM]" if self.dry_run else ""
                print(f"[GAMMA] ✅ {mode} BUY: {order['size']:.2f} @ ${order['price']:.3f}")
                print(f"[GAMMA]    TP: ${take_profit:.3f} | SL: ${stop_loss:.3f}")

                if self.dry_run and self.simulation:
                    print(f"[GAMMA]    Balance: ${result.get('remaining_balance', 0):.2f}")
            else:
                print(f"[GAMMA] ❌ Failed: {result.get('error', 'Unknown')}")

    async def check_order_status(self, order_id: str) -> dict:
        """Check order status via CLOB API."""
        if self.dry_run:
            return {"status": STATUS_FILLED, "filled_size": 0}

        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://clob.polymarket.com/order/{order_id}"
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "status": data.get("status", "UNKNOWN"),
                            "filled_size": float(data.get("size_matched", 0)),
                            "remaining": float(data.get("size", 0)) - float(data.get("size_matched", 0))
                        }
        except Exception as e:
            print(f"[GAMMA] Order check error: {e}")

        return {"status": "UNKNOWN", "filled_size": 0}

    async def verify_pending_orders(self):
        """Verify status of all pending orders and update positions."""
        positions = self.state.get_positions()

        for pos in positions:
            order_id = pos.get("order_id", "")
            current_status = pos.get("status", "")

            # Skip already filled or dry run orders
            if current_status in [STATUS_FILLED, STATUS_MATCHED, "SIMULATED"]:
                continue

            if not order_id or order_id.startswith("DRY_"):
                continue

            # Check order status
            status_info = await self.check_order_status(order_id)
            new_status = status_info["status"]

            if new_status != current_status:
                print(f"[GAMMA] Order {order_id[:16]}... status: {current_status} -> {new_status}")

                # Update position
                self.state.update_position(pos["condition_id"], {
                    "status": new_status,
                    "filled_size": status_info.get("filled_size", 0),
                    "last_checked": datetime.now(timezone.utc).isoformat()
                })

                if new_status == STATUS_MATCHED or new_status == STATUS_FILLED:
                    self.state.incr_metric("orders_filled")
                    print(f"[GAMMA] ✅ Order FILLED: {pos['question'][:30]}...")

                elif new_status == STATUS_CANCELLED:
                    self.state.incr_metric("orders_cancelled")
                    print(f"[GAMMA] ⚠️ Order CANCELLED: {pos['question'][:30]}...")

    async def get_open_orders(self) -> List[dict]:
        """Get all open orders from positions."""
        positions = self.state.get_positions()
        return [
            p for p in positions
            if p.get("status") in [STATUS_PENDING, STATUS_LIVE, ""]
            and not p.get("order_id", "").startswith("DRY_")
        ]

    # ================================================================
    # POSITION MANAGEMENT - THE EXIT VALVE
    # ================================================================

    async def get_current_price(self, condition_id: str) -> dict:
        """Fetch current market price from Gamma API."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://gamma-api.polymarket.com/markets?conditionId={condition_id}"
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        markets = await resp.json()
                        if markets:
                            m = markets[0]
                            return {
                                "best_bid": float(m.get("bestBid") or 0),
                                "best_ask": float(m.get("bestAsk") or 0),
                                "last_price": float(m.get("lastTradePrice") or 0),
                                "closed": m.get("closed", False),
                                "resolved": m.get("resolutionSource") is not None
                            }
        except Exception as e:
            print(f"[GAMMA] Price fetch error: {e}")

        return {"best_bid": 0, "best_ask": 0, "last_price": 0, "closed": False, "resolved": False}

    async def execute_sell(self, position: dict, price: float, reason: str) -> dict:
        """Execute a SELL order to exit a position."""
        condition_id = position["condition_id"]
        token_id = position.get("token_id", "")
        size = position.get("size", 0)

        if not token_id or size <= 0:
            return {"success": False, "error": "Invalid position"}

        print(f"[GAMMA] 📤 SELLING: {position['question'][:35]}... ({reason})")

        # Use simulation for dry run
        if self.dry_run and self.simulation:
            result = self.simulation.execute_sell(
                size=size,
                price=price,
                condition_id=condition_id
            )
        else:
            result = await self.executor.execute_order(
                token_id=token_id,
                side="SELL",
                price=price,
                size=size,
                dry_run=self.dry_run
            )

        if result["success"]:
            # Calculate P&L
            entry_price = position.get("entry_price", 0)
            pnl = (price - entry_price) * size
            pnl_pct = ((price - entry_price) / entry_price * 100) if entry_price > 0 else 0

            # Update position as closed
            self.state.update_position(condition_id, {
                "status": STATUS_CLOSED,
                "exit_price": price,
                "exit_reason": reason,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "closed_at": datetime.now(timezone.utc).isoformat()
            })

            # Remove from active positions after recording
            self.state.remove_position(condition_id)

            self.state.incr_metric("positions_closed")
            self.state.incr_metric("total_pnl", int(pnl * 100))  # Store as cents

            # Log to trade history
            self.history.log_trade({
                **position,
                "exit_price": price,
                "exit_reason": reason,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "simulated": self.dry_run
            })

            emoji = "🟢" if pnl >= 0 else "🔴"
            mode = "[SIM]" if self.dry_run else ""
            print(f"[GAMMA] {emoji} {mode} SOLD @ ${price:.3f} | P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)")

            if self.dry_run and self.simulation:
                print(f"[GAMMA]    Balance: ${result.get('remaining_balance', 0):.2f}")

            return {"success": True, "pnl": pnl, "pnl_pct": pnl_pct}
        else:
            print(f"[GAMMA] ❌ Sell failed: {result.get('error', 'Unknown')}")
            return result

    async def check_exit_conditions(self):
        """Check all positions for take-profit or stop-loss triggers."""
        positions = self.state.get_positions()

        for pos in positions:
            # Skip closed or pending positions
            if pos.get("status") == STATUS_CLOSED:
                continue

            condition_id = pos["condition_id"]
            entry_price = pos.get("entry_price", 0)
            take_profit = pos.get("take_profit", entry_price * 1.05)
            stop_loss = pos.get("stop_loss", entry_price * 0.85)

            # Get current price
            price_data = await self.get_current_price(condition_id)
            current_price = price_data["best_bid"]  # Use bid for selling

            if current_price <= 0:
                continue

            # Check for market resolution first
            if price_data["closed"] or price_data["resolved"]:
                print(f"[GAMMA] 🎉 Market RESOLVED: {pos['question'][:40]}...")
                await self.handle_resolution(pos, price_data)
                continue

            # TAKE PROFIT
            if current_price >= take_profit:
                await self.execute_sell(pos, current_price, "TAKE_PROFIT")
                continue

            # STOP LOSS (emergency exit at market)
            if current_price <= stop_loss:
                # For stop loss, use a more aggressive price to ensure fill
                emergency_price = current_price * 0.99  # Slight discount for quick fill
                await self.execute_sell(pos, emergency_price, "STOP_LOSS")
                continue

            # Update position with current price for monitoring
            self.state.update_position(condition_id, {
                "current_price": current_price,
                "unrealized_pnl": round((current_price - entry_price) * pos.get("size", 0), 2),
                "last_price_check": datetime.now(timezone.utc).isoformat()
            })

    async def handle_resolution(self, position: dict, price_data: dict):
        """Handle a resolved market - redeem winnings."""
        condition_id = position["condition_id"]
        entry_price = position.get("entry_price", 0)
        size = position.get("size", 0)

        # If market closed, shares are worth $1.00 (win) or $0.00 (lose)
        # Check the final price to determine outcome
        final_price = price_data.get("last_price", 0)

        if final_price >= 0.99:
            # WIN - shares worth $1.00
            payout = size * 1.0
            pnl = payout - (size * entry_price)
            outcome = "WIN"
        elif final_price <= 0.01:
            # LOSE - shares worth $0.00
            payout = 0
            pnl = -(size * entry_price)
            outcome = "LOSE"
        else:
            # Market closed but price unclear - wait for full resolution
            print(f"[GAMMA] ⏳ Awaiting final resolution: {position['question'][:30]}...")
            return

        # Update simulation balance
        if self.dry_run and self.simulation:
            self.simulation.settle_position(
                condition_id=condition_id,
                outcome=outcome,
                entry_price=entry_price,
                size=size
            )

        # Record the resolution
        self.state.update_position(condition_id, {
            "status": STATUS_CLOSED,
            "exit_reason": f"RESOLVED_{outcome}",
            "exit_price": 1.0 if outcome == "WIN" else 0.0,
            "pnl": round(pnl, 2),
            "payout": round(payout, 2),
            "resolved_at": datetime.now(timezone.utc).isoformat()
        })

        # Remove from active positions
        self.state.remove_position(condition_id)

        self.state.incr_metric("positions_resolved")
        self.state.incr_metric("total_pnl", int(pnl * 100))

        # Log to trade history
        self.history.log_trade({
            **position,
            "exit_price": 1.0 if outcome == "WIN" else 0.0,
            "exit_reason": f"RESOLVED_{outcome}",
            "pnl": pnl,
            "pnl_pct": ((1.0 if outcome == "WIN" else 0.0) - entry_price) / entry_price * 100 if entry_price > 0 else 0,
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "simulated": self.dry_run
        })

        emoji = "🏆" if outcome == "WIN" else "💀"
        mode = "[SIM]" if self.dry_run else ""
        print(f"[GAMMA] {emoji} {mode} {outcome}: ${payout:.2f} payout | P&L: ${pnl:+.2f}")

        if self.dry_run and self.simulation:
            print(f"[GAMMA]    Balance: ${self.simulation.virtual_balance:.2f}")

    async def run(self, interval: float = 3.0):
        """Main execution loop with complete position management."""
        self.running = True
        mode = "DRY RUN" if self.dry_run else "🔴 LIVE"
        print(f"[GAMMA] Sniper started ({mode})")
        print(f"[GAMMA] Exit strategy: TP +{DEFAULT_TAKE_PROFIT*100:.0f}% | SL {DEFAULT_STOP_LOSS*100:.0f}%")

        # Initialize executor
        await self.executor.init()

        cycle_counter = 0
        while self.running:
            try:
                # === BUY: Execute vetted trades ===
                await self.execute_vetted()

                cycle_counter += 1

                # === SELL: Check exit conditions every 5 cycles (15s) ===
                if cycle_counter % 5 == 0:
                    await self.check_exit_conditions()

                # === VERIFY: Check order status every 5 cycles ===
                if cycle_counter % 5 == 0:
                    await self.verify_pending_orders()

                # Reset counter to prevent overflow
                if cycle_counter >= 1000:
                    cycle_counter = 0

            except Exception as e:
                print(f"[GAMMA] Error: {e}")

            await asyncio.sleep(interval)

    def stop(self):
        self.running = False


async def main():
    import sys
    dry_run = "--live" not in sys.argv

    sniper = AsyncGammaSniper(dry_run=dry_run)
    try:
        await sniper.run()
    except KeyboardInterrupt:
        sniper.stop()


if __name__ == "__main__":
    asyncio.run(main())
