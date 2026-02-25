#!/usr/bin/env python3
"""
LIVE SAFETY - Pre-order safety checks for production trading.
=============================================================
Guards against runaway losses, oversized positions, and bugs.
"""

import os
from datetime import datetime, timezone


class LiveSafety:
    """Safety checks that must pass before any live order is placed."""

    MAX_SINGLE_ORDER_USD = 25        # No single order > $25
    MAX_TOTAL_EXPOSURE_PCT = 0.80    # Max 80% of portfolio in open positions
    DAILY_LOSS_LIMIT_USD = 10        # Halt new orders if daily P&L < -$10
    BALANCE_BUFFER_PCT = 0.05        # Require 5% balance buffer above order amount
    KILL_SWITCH_FILE = "/run/sovereign-hive/kill_switch"

    def __init__(self):
        self._daily_pnl = 0.0
        self._daily_reset_date = None
        self._halted = False

    def _check_daily_reset(self):
        """Reset daily P&L tracker at midnight UTC."""
        today = datetime.now(timezone.utc).date()
        if self._daily_reset_date != today:
            self._daily_pnl = 0.0
            self._daily_reset_date = today
            self._halted = False

    def record_trade_pnl(self, pnl: float):
        """Record a completed trade's P&L for daily tracking."""
        self._check_daily_reset()
        self._daily_pnl += pnl
        if self._daily_pnl <= -self.DAILY_LOSS_LIMIT_USD:
            self._halted = True
            print(f"[SAFETY] DAILY LOSS LIMIT HIT: ${self._daily_pnl:.2f}. Halting new orders.")

    def check_kill_switch(self) -> bool:
        """Check if emergency kill switch is activated."""
        return os.path.exists(self.KILL_SWITCH_FILE)

    def pre_order_check(
        self,
        order_amount: float,
        portfolio_balance: float,
        total_exposure: float,
    ) -> tuple:
        """
        Run all safety checks before placing an order.

        Returns:
            (safe: bool, reason: str)
        """
        self._check_daily_reset()

        # Kill switch
        if self.check_kill_switch():
            return False, "Kill switch activated"

        # Daily loss limit
        if self._halted:
            return False, f"Daily loss limit reached (${self._daily_pnl:.2f})"

        # Per-order cap
        if order_amount > self.MAX_SINGLE_ORDER_USD:
            return False, f"Order ${order_amount:.2f} exceeds max ${self.MAX_SINGLE_ORDER_USD}"

        # Balance buffer
        min_balance = order_amount * (1 + self.BALANCE_BUFFER_PCT)
        if portfolio_balance < min_balance:
            return False, f"Balance ${portfolio_balance:.2f} < required ${min_balance:.2f} (5% buffer)"

        # Total exposure cap (based on actual capital: balance + deployed)
        actual_capital = portfolio_balance + total_exposure
        new_exposure = total_exposure + order_amount
        max_exposure = actual_capital * self.MAX_TOTAL_EXPOSURE_PCT
        if new_exposure > max_exposure:
            return False, f"Total exposure ${new_exposure:.2f} would exceed {self.MAX_TOTAL_EXPOSURE_PCT:.0%} cap (${max_exposure:.2f})"

        return True, "OK"
