#!/usr/bin/env python3
"""
SOVEREIGN HIVE - MASTER ORCHESTRATOR
====================================
Coordinates all agents in the decentralized firm.

Usage:
  python run_hive.py              # Run all agents (dry-run mode)
  python run_hive.py --live       # Run with live execution
  python run_hive.py --scan       # Run single scan cycle
  python run_hive.py --status     # Show blackboard status
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Agent imports
from agents.alpha_scout import run_scan as alpha_scan
from agents.beta_analyst import vet_opportunities as beta_vet
from agents.gamma_sniper import run_sniper as gamma_execute
from agents.omega_guardian import run_guardian as omega_monitor

BLACKBOARD_PATH = Path(__file__).parent / "blackboard.json"


def load_blackboard() -> dict:
    try:
        with open(BLACKBOARD_PATH, "r") as f:
            return json.load(f)
    except:
        return {}


def print_status():
    """Print current blackboard status."""
    bb = load_blackboard()

    print(f"\n{'='*60}")
    print(f"SOVEREIGN HIVE STATUS - {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}")

    print(f"\n📡 RISK STATE: {bb.get('risk_state', 'UNKNOWN')}")

    balances = bb.get("wallet_balances", {})
    print(f"\n💰 WALLET:")
    print(f"  USDC.e: ${balances.get('usdc', 0):.2f}")
    print(f"  POL: {balances.get('pol', 0):.4f}")

    opps = bb.get("opportunities", [])
    print(f"\n🔍 OPPORTUNITIES: {len(opps)}")
    for o in opps[:3]:
        print(f"  • [{o.get('anomaly_type')}] {o.get('question', '')[:40]}... @ ${o.get('best_ask', 0):.3f}")

    vetted = bb.get("vetted_trades", [])
    print(f"\n✅ VETTED TRADES: {len(vetted)}")
    for v in vetted[:3]:
        print(f"  • {v.get('question', '')[:40]}... (Confidence: {v.get('analyst_confidence', 0):.0%})")

    positions = bb.get("active_positions", [])
    print(f"\n📊 ACTIVE POSITIONS: {len(positions)}")
    for p in positions:
        print(f"  • {p.get('question', '')[:40]}...")
        print(f"    Entry: ${p.get('entry_price', 0):.3f} | Size: {p.get('size', 0):.2f}")

    alerts = bb.get("alerts", [])
    if alerts:
        print(f"\n🚨 ALERTS:")
        for a in alerts:
            print(f"  {a}")

    print(f"\n📅 Last Scan: {bb.get('last_scan', 'Never')}")
    print(f"📅 Last Analysis: {bb.get('last_analysis', 'Never')}")
    print(f"📅 Last Execution: {bb.get('last_execution', 'Never')}")


def run_cycle(dry_run: bool = True):
    """Run one complete cycle of all agents."""
    print(f"\n{'#'*60}")
    print(f"# SOVEREIGN HIVE - CYCLE START")
    print(f"# Mode: {'DRY RUN' if dry_run else '🔴 LIVE'}")
    print(f"# Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'#'*60}")

    # 1. OMEGA: Check risk state first
    print("\n[1/4] OMEGA GUARDIAN - Pre-flight check...")
    guardian_result = omega_monitor()

    if guardian_result["risk_state"] == "HALTED":
        print("[HIVE] ⛔ System HALTED. Aborting cycle.")
        return

    # 2. ALPHA: Scan for opportunities
    print("\n[2/4] ALPHA SCOUT - Scanning markets...")
    alpha_scan()

    # 3. BETA: Vet opportunities
    print("\n[3/4] BETA ANALYST - Vetting opportunities...")
    beta_vet()

    # 4. GAMMA: Execute vetted trades
    print("\n[4/4] GAMMA SNIPER - Executing trades...")
    gamma_execute(dry_run=dry_run)

    # Final status
    print_status()


def main():
    dry_run = True

    if len(sys.argv) > 1:
        arg = sys.argv[1]

        if arg == "--live":
            dry_run = False
            print("⚠️  LIVE MODE - Real trades will be executed!")
            confirm = input("Type 'CONFIRM' to proceed: ")
            if confirm != "CONFIRM":
                print("Aborted.")
                return

        elif arg == "--scan":
            run_cycle(dry_run=True)
            return

        elif arg == "--status":
            print_status()
            return

        elif arg == "--help":
            print(__doc__)
            return

    # Continuous mode
    print("Starting Sovereign Hive in continuous mode...")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("Press Ctrl+C to stop.\n")

    cycle_interval = 300  # 5 minutes

    while True:
        try:
            run_cycle(dry_run=dry_run)
            print(f"\n[HIVE] Sleeping {cycle_interval}s until next cycle...")
            time.sleep(cycle_interval)
        except KeyboardInterrupt:
            print("\n[HIVE] Sovereign Hive terminated.")
            break
        except Exception as e:
            print(f"\n[HIVE] Error in cycle: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
