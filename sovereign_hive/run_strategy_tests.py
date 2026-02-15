#!/usr/bin/env python3
"""
Multi-Strategy Parallel Tester
Runs 9 strategies in parallel with isolated $1000 capital each
Each strategy gets its own log file for clean benchmarking
"""

import subprocess
import time
import os
import signal
import sys
from datetime import datetime

STRATEGIES = [
    "MARKET_MAKER",
    "MEAN_REVERSION",
    "BINANCE_ARB",
    "DUAL_SIDE_ARB",
    "NEAR_CERTAIN",
    "NEAR_ZERO",
    "MID_RANGE",
    "VOLUME_SURGE",
    "DIP_BUY",
]

LOG_DIR = "/Users/qudus-mac/PycharmProjects/polymarket-fund/sovereign_hive/logs/strategies"
PROJECT_ROOT = "/Users/qudus-mac/PycharmProjects/polymarket-fund"

def create_strategy_config(strategy_name):
    """Create a strategy-specific config that enables only this strategy."""
    config_file = f"{LOG_DIR}/{strategy_name}_config.json"

    config = {
        "initial_balance": 1000,
        "enabled_strategies": [strategy_name],
        "strategy_name": strategy_name,
    }

    # Strategy-specific settings
    if strategy_name == "MARKET_MAKER":
        config.update({
            "mm_min_volume_24h": 15000,
            "mm_min_liquidity": 30000,
            "mm_min_spread": 0.02,
            "mm_max_spread": 0.10,
        })

    import json
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)

    return config_file

def launch_strategy_test(strategy_name, test_num):
    """Launch a single strategy test in background."""
    log_file = f"{LOG_DIR}/{strategy_name}.log"
    portfolio_file = f"{LOG_DIR}/portfolio_{strategy_name}.json"

    # Clear old log
    open(log_file, "w").close()

    # Create command to run simulation with this strategy only
    cmd = f"""
    cd {PROJECT_ROOT}
    export STRATEGY_FILTER="{strategy_name}"
    export PORTFOLIO_FILE="{portfolio_file}"
    nohup caffeinate -i python -u sovereign_hive/run_simulation.py >> {log_file} 2>&1 &
    """

    print(f"[{test_num}/9] Launching {strategy_name:20} → {log_file}")

    # Run command
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ Error: {result.stderr}")
    else:
        print(f"  ✅ Started (PID will show in log)")

    return log_file

def monitor_tests():
    """Monitor all running tests."""
    print(f"\n{'='*80}")
    print(f"  STRATEGY ISOLATION TEST - MONITORING")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Log directory: {LOG_DIR}")
    print(f"{'='*80}\n")

    print("To monitor all tests in real-time, run:")
    print("  watch -n 5 'ls -lh /Users/qudus-mac/PycharmProjects/polymarket-fund/sovereign_hive/logs/strategies/*.log'\n")

    print("To follow a specific strategy:")
    for strat in STRATEGIES:
        log_file = f"{LOG_DIR}/{strat}.log"
        print(f"  tail -f {log_file}")

    print(f"\n{'='*80}")
    print("Waiting for tests to complete (~6 hours)...")
    print(f"{'='*80}\n")

    # Monitor for 6 hours
    start_time = time.time()
    test_duration = 6 * 3600  # 6 hours

    while time.time() - start_time < test_duration:
        time.sleep(60)

        # Print status every 10 minutes
        if int(time.time() - start_time) % 600 == 0:
            elapsed = int(time.time() - start_time) // 60
            remaining = (test_duration - (time.time() - start_time)) // 60
            print(f"[{elapsed}m/{int(test_duration/60)}m] Tests running... ({int(remaining)}m remaining)")

            # Show log sizes
            for strat in STRATEGIES:
                log_file = f"{LOG_DIR}/{strat}.log"
                if os.path.exists(log_file):
                    size = os.path.getsize(log_file) / 1024  # KB
                    print(f"  {strat:20} : {size:8.1f} KB")

def main():
    print(f"""
╔{'='*78}╗
║  SOVEREIGN HIVE - MULTI-STRATEGY ISOLATION TEST                                 ║
║  Running 9 strategies in PARALLEL with isolated $1000 capital each               ║
║  Each strategy gets its own log file for clean benchmarking                      ║
╚{'='*78}╝
    """)

    # Kill any existing simulations
    print("\n[STARTUP] Killing existing simulations...")
    subprocess.run("pkill -f 'run_simulation.py'", shell=True)
    time.sleep(2)

    # Launch all 9 strategies in parallel
    print(f"\n[STARTUP] Launching 9 strategy tests in parallel...\n")

    for i, strategy in enumerate(STRATEGIES, 1):
        launch_strategy_test(strategy, i)
        time.sleep(1)  # Small delay between launches

    print(f"\n✅ All 9 strategies launched!\n")

    # Monitor tests
    monitor_tests()

    print(f"\n{'='*80}")
    print("TEST COMPLETE - Generating results...")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[SHUTDOWN] Test interrupted by user")
        print("Logs preserved in: /Users/qudus-mac/PycharmProjects/polymarket-fund/sovereign_hive/logs/strategies/")
        sys.exit(0)
