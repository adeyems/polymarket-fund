#!/usr/bin/env python3
"""
ASYNC HIVE ORCHESTRATOR - Concurrent Agent Execution
=====================================================
Runs all agents in parallel with proper lifecycle management.

Latency Target: <500ms end-to-end cycle
"""

import asyncio
import signal
import sys
from datetime import datetime, timezone

# Ensure path
sys.path.insert(0, str(__file__).rsplit('/', 1)[0])

from core.redis_state import get_state
from agents.async_alpha import AsyncAlphaScout
from agents.async_beta import AsyncBetaAnalyst
from agents.async_gamma import AsyncGammaSniper
from agents.async_omega import AsyncOmegaGuardian
from agents.sentiment_streamer import SentimentStreamer


class AsyncHiveOrchestrator:
    """
    Master orchestrator running all agents concurrently.

    Agent Hierarchy:
    - ALPHA Scout: Detects anomalies (10s interval)
    - BETA Analyst: Vets opportunities (5s interval)
    - GAMMA Sniper: Executes trades (3s interval)
    - OMEGA Guardian: Risk monitoring (10s interval)
    - Sentiment Streamer: Background pre-caching (30s interval)
    """

    def __init__(self, dry_run: bool = True):
        self.state = get_state()
        self.dry_run = dry_run
        self.running = False
        self._tasks = []

        # Initialize agents
        self.alpha = AsyncAlphaScout()
        self.beta = AsyncBetaAnalyst()
        self.gamma = AsyncGammaSniper(dry_run=dry_run)
        self.omega = AsyncOmegaGuardian()
        self.sentiment = SentimentStreamer()

    async def start(self):
        """Start all agents concurrently."""
        self.running = True
        mode = "DRY RUN" if self.dry_run else "🔴 LIVE MODE"

        print("=" * 60)
        print(f"  SOVEREIGN HIVE V4 - ASYNC ARCHITECTURE")
        print(f"  Mode: {mode}")
        print(f"  Started: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 60)
        print()
        print("  Agents:")
        print("    [ALPHA] Scout - Anomaly detection (10s)")
        print("    [BETA]  Analyst - Opportunity vetting (5s)")
        print("    [GAMMA] Sniper - Trade execution (3s)")
        print("    [OMEGA] Guardian - Risk monitoring (10s)")
        print("    [SENT]  Streamer - Sentiment pre-cache (30s)")
        print()
        print("=" * 60)

        # Set initial risk state
        self.state.set_risk_state("HEALTHY")

        # Create tasks for each agent
        self._tasks = [
            asyncio.create_task(self._run_alpha(), name="alpha"),
            asyncio.create_task(self._run_beta(), name="beta"),
            asyncio.create_task(self._run_gamma(), name="gamma"),
            asyncio.create_task(self._run_omega(), name="omega"),
            asyncio.create_task(self._run_sentiment(), name="sentiment"),
            asyncio.create_task(self._run_status(), name="status"),
        ]

        # Wait for all tasks
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            print("\n[HIVE] Shutting down...")

    async def _run_alpha(self):
        """Run Alpha Scout."""
        try:
            await self.alpha.run()
        except Exception as e:
            print(f"[HIVE] Alpha error: {e}")

    async def _run_beta(self):
        """Run Beta Analyst."""
        try:
            await self.beta.run()
        except Exception as e:
            print(f"[HIVE] Beta error: {e}")

    async def _run_gamma(self):
        """Run Gamma Sniper."""
        try:
            await self.gamma.run()
        except Exception as e:
            print(f"[HIVE] Gamma error: {e}")

    async def _run_omega(self):
        """Run Omega Guardian."""
        try:
            await self.omega.run()
        except Exception as e:
            print(f"[HIVE] Omega error: {e}")

    async def _run_sentiment(self):
        """Run Sentiment Streamer."""
        try:
            await self.sentiment.stream()
        except Exception as e:
            print(f"[HIVE] Sentiment error: {e}")

    async def _run_status(self):
        """Periodic status report."""
        while self.running:
            await asyncio.sleep(60)  # Every minute
            self._print_status()

    def _print_status(self):
        """Print current hive status."""
        risk_state = self.state.get_risk_state()
        positions = len(self.state.get_positions())
        vetted = len(self.state.get_vetted())
        opportunities = len(self.state.get_opportunities())

        alpha_scans = self.state.get_metric("alpha_scans")
        gamma_executed = self.state.get_metric("gamma_executed")

        print()
        print("-" * 40)
        print(f"[STATUS] Risk: {risk_state} | Pos: {positions} | Vetted: {vetted} | Opps: {opportunities}")
        print(f"[STATUS] Scans: {alpha_scans} | Executed: {gamma_executed}")
        print("-" * 40)
        print()

    async def stop(self):
        """Stop all agents gracefully."""
        self.running = False

        # Signal all agents to stop
        self.alpha.stop()
        self.beta.stop()
        self.gamma.stop()
        self.omega.stop()
        self.sentiment.stop()

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        print("[HIVE] All agents stopped")

    def emergency_halt(self):
        """Emergency stop all trading."""
        self.state.set_risk_state("HALTED")
        print("[HIVE] 🛑 EMERGENCY HALT - Trading disabled")


async def main():
    import sys

    dry_run = "--live" not in sys.argv

    orchestrator = AsyncHiveOrchestrator(dry_run=dry_run)

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def shutdown_handler():
        print("\n[HIVE] Received shutdown signal...")
        asyncio.create_task(orchestrator.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_handler)

    try:
        await orchestrator.start()
    except KeyboardInterrupt:
        await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
