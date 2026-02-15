#!/usr/bin/env python3
"""
ASYNC OMEGA GUARDIAN - Real-Time Risk Monitoring
=================================================
Continuous health checks and risk management.
"""

import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Optional
import os
import sys
sys.path.insert(0, str(__file__).rsplit('/', 2)[0])

from core.redis_state import get_state


# Risk Limits
MAX_DRAWDOWN = 20.0
MAX_SINGLE_LOSS = 10.0
MIN_GAS = 1.0


class AsyncOmegaGuardian:
    """
    Real-time risk monitoring and system health.
    """

    def __init__(self):
        self.state = get_state()
        self.running = False
        self.alerts = []

    async def get_balances(self) -> dict:
        """Fetch wallet balances asynchronously."""
        try:
            from web3 import Web3

            WALLET = os.getenv("WALLET_ADDRESS", "0xb22028EA4E841CA321eb917C706C931a94b564AB")
            USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

            w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
            erc20_abi = [{'inputs': [{'name': 'account', 'type': 'address'}], 'name': 'balanceOf', 'outputs': [{'name': '', 'type': 'uint256'}], 'stateMutability': 'view', 'type': 'function'}]

            usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=erc20_abi)
            usdc_balance = usdc.functions.balanceOf(Web3.to_checksum_address(WALLET)).call() / 1e6
            pol_balance = w3.eth.get_balance(Web3.to_checksum_address(WALLET)) / 1e18

            return {"usdc": usdc_balance, "pol": pol_balance}
        except Exception as e:
            print(f"[OMEGA] Balance error: {e}")
            return {"usdc": 0, "pol": 0}

    async def check_market_status(self, condition_id: str) -> dict:
        """Check if market has resolved."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://gamma-api.polymarket.com/markets?conditionId={condition_id}"
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        markets = await resp.json()
                        if markets:
                            m = markets[0]
                            return {
                                "closed": m.get("closed", False),
                                "last_price": float(m.get("lastTradePrice") or 0)
                            }
        except:
            pass
        return {"closed": False, "last_price": 0}

    async def monitor(self):
        """Single monitoring cycle."""
        self.alerts = []
        risk_state = "HEALTHY"

        # 1. Check balances
        balances = await self.get_balances()
        self.state._set("hive:balances", str(balances).replace("'", '"'))

        if balances["pol"] < MIN_GAS:
            self.alerts.append(f"⚠️ LOW GAS: {balances['pol']:.4f} POL")
            risk_state = "WARNING"

        # 2. Check positions
        positions = self.state.get_positions()
        total_exposure = 0
        resolved = []

        for pos in positions:
            status = await self.check_market_status(pos["condition_id"])

            if status["closed"]:
                resolved.append(pos)
                print(f"[OMEGA] 🎉 Resolved: {pos['question'][:40]}...")
                continue

            # Calculate P&L
            entry = pos.get("entry_price", 0)
            current = status["last_price"] or entry
            pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0

            value = pos.get("size", 0) * current
            total_exposure += value

            if pnl_pct < -MAX_DRAWDOWN:
                self.alerts.append(f"🔴 STOP LOSS: {pos['question'][:30]}... {pnl_pct:.0f}%")
                risk_state = "CRITICAL"

        # 3. Handle resolved positions
        for pos in resolved:
            self.state.remove_position(pos["condition_id"])
            self.state.incr_metric("positions_resolved")

        # 4. Update state
        self.state.set_risk_state(risk_state)

        # 5. Print status
        print(f"[OMEGA] Balance: ${balances['usdc']:.2f} | Positions: {len(positions)} | Exposure: ${total_exposure:.2f} | Risk: {risk_state}")

        if self.alerts:
            for alert in self.alerts:
                print(f"[OMEGA] {alert}")
            await self.send_alert("\n".join(self.alerts))

        return {"risk_state": risk_state, "alerts": self.alerts}

    async def send_alert(self, message: str):
        """Send alert to Discord/webhook."""
        webhook = os.getenv("ALERT_WEBHOOK_URL")
        if not webhook:
            return

        try:
            async with aiohttp.ClientSession() as session:
                await session.post(webhook, json={"content": f"🚨 OMEGA ALERT\n{message}"})
        except:
            pass

    async def run(self, interval: float = 10.0):
        """Main monitoring loop."""
        self.running = True
        print("[OMEGA] Guardian started")

        while self.running:
            try:
                await self.monitor()
            except Exception as e:
                print(f"[OMEGA] Error: {e}")

            await asyncio.sleep(interval)

    def stop(self):
        self.running = False

    def emergency_halt(self):
        """Emergency stop."""
        self.state.set_risk_state("HALTED")
        print("[OMEGA] 🛑 EMERGENCY HALT")

    def resume(self):
        """Resume trading."""
        self.state.set_risk_state("HEALTHY")
        print("[OMEGA] ✅ Trading resumed")


async def main():
    guardian = AsyncOmegaGuardian()

    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "--halt":
            guardian.emergency_halt()
            return
        elif sys.argv[1] == "--resume":
            guardian.resume()
            return

    try:
        await guardian.run()
    except KeyboardInterrupt:
        guardian.stop()


if __name__ == "__main__":
    asyncio.run(main())
