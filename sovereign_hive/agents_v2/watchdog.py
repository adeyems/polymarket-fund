"""
Watchdog Agent — Health monitoring and auto-restart.

Runs every 10 minutes. Checks:
1. Heartbeat freshness (trader alive?)
2. Docker container health
3. Portfolio sanity (no impossible P&L)
4. API connectivity

Conservative: auto-restart crashed processes, alert on issues,
NEVER auto-fix code.
"""

import os
import sys
import json
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sovereign_hive.agents_v2.models import WatchdogEvent

DATA_DIR = Path(__file__).parent.parent / "data"
HEARTBEAT_FILE = DATA_DIR / ".heartbeat.json"
EVENTS_FILE = DATA_DIR / ".watchdog_events.jsonl"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

INTERVAL = int(os.getenv("WATCHDOG_INTERVAL", "600"))  # 10 min
STALE_THRESHOLD = int(os.getenv("HEARTBEAT_STALE_THRESHOLD", "300"))  # 5 min
RESTART_COOLDOWN = 60  # seconds between restart attempts

_last_restart_time = None
_last_balance = None


def write_event(event: WatchdogEvent):
    """Append event for the alerter to read."""
    try:
        with open(EVENTS_FILE, "a") as f:
            f.write(event.model_dump_json() + "\n")
    except Exception as e:
        print(f"[WATCHDOG] Failed to write event: {e}")


async def send_discord(message: str, color: int = 16776960):
    """Send alert directly to Discord (backup if alerter is down)."""
    if not DISCORD_WEBHOOK:
        return
    try:
        payload = {
            "embeds": [{
                "title": "WATCHDOG ALERT",
                "description": message,
                "color": color,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(DISCORD_WEBHOOK, json=payload, timeout=10) as resp:
                if resp.status not in (200, 204):
                    print(f"[WATCHDOG] Discord returned {resp.status}")
    except Exception as e:
        print(f"[WATCHDOG] Discord error: {e}")


def check_heartbeat() -> dict:
    """Check if trader heartbeat is fresh.

    Returns: {"healthy": bool, "age_seconds": int, "data": dict}
    """
    if not HEARTBEAT_FILE.exists():
        return {"healthy": False, "age_seconds": -1, "data": {}, "reason": "No heartbeat file"}

    try:
        with open(HEARTBEAT_FILE) as f:
            data = json.load(f)

        ts = datetime.fromisoformat(data["ts"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds()

        if age > STALE_THRESHOLD:
            return {"healthy": False, "age_seconds": int(age), "data": data,
                    "reason": f"Heartbeat stale ({int(age)}s > {STALE_THRESHOLD}s)"}

        return {"healthy": True, "age_seconds": int(age), "data": data, "reason": "OK"}
    except Exception as e:
        return {"healthy": False, "age_seconds": -1, "data": {}, "reason": f"Parse error: {e}"}


def check_portfolio_sanity() -> dict:
    """Check portfolio for anomalies.

    Returns: {"healthy": bool, "reason": str, "balance": float}
    """
    global _last_balance

    # Read from heartbeat data (already parsed)
    if not HEARTBEAT_FILE.exists():
        return {"healthy": True, "reason": "No data yet", "balance": 0}

    try:
        with open(HEARTBEAT_FILE) as f:
            data = json.load(f)

        balance = data.get("balance", 0)

        # Check for zero or negative balance
        if balance <= 0:
            return {"healthy": False, "reason": f"Balance is ${balance:.2f}", "balance": balance}

        # Check for massive swing (>50% drop in one check)
        if _last_balance is not None and _last_balance > 0:
            change_pct = (balance - _last_balance) / _last_balance
            if change_pct < -0.50:
                return {"healthy": False,
                        "reason": f"Balance dropped {change_pct:.0%}: ${_last_balance:.2f} -> ${balance:.2f}",
                        "balance": balance}

        _last_balance = balance
        return {"healthy": True, "reason": "OK", "balance": balance}
    except Exception as e:
        return {"healthy": True, "reason": f"Parse error: {e}", "balance": 0}


async def check_api_connectivity() -> dict:
    """Check if Gamma API is reachable.

    Returns: {"healthy": bool, "reason": str}
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://gamma-api.polymarket.com/markets?limit=1",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return {"healthy": True, "reason": "OK"}
                return {"healthy": False, "reason": f"Gamma API returned {resp.status}"}
    except Exception as e:
        return {"healthy": False, "reason": f"Gamma API unreachable: {e}"}


def restart_trader():
    """Restart the trader container via Docker SDK."""
    global _last_restart_time

    # Cooldown check
    now = datetime.now(timezone.utc)
    if _last_restart_time:
        elapsed = (now - _last_restart_time).total_seconds()
        if elapsed < RESTART_COOLDOWN:
            print(f"[WATCHDOG] Restart cooldown ({RESTART_COOLDOWN - elapsed:.0f}s remaining)")
            return False

    try:
        import docker
        client = docker.from_env()

        # Find trader container
        project = os.getenv("COMPOSE_PROJECT", "sovereign-hive")
        containers = client.containers.list(all=True, filters={"name": f"{project}-trader"})

        if not containers:
            print("[WATCHDOG] Trader container not found")
            return False

        trader = containers[0]
        print(f"[WATCHDOG] Restarting trader container (status: {trader.status})")
        trader.restart(timeout=30)
        _last_restart_time = now
        return True
    except ImportError:
        print("[WATCHDOG] Docker SDK not available (running outside Docker?)")
        return False
    except Exception as e:
        print(f"[WATCHDOG] Restart failed: {e}")
        return False


async def run_check():
    """Run all health checks once."""
    print(f"\n[WATCHDOG] Health check @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

    # 1. Heartbeat
    hb = check_heartbeat()
    status = "OK" if hb["healthy"] else "FAIL"
    print(f"  Heartbeat: {status} (age: {hb['age_seconds']}s) - {hb['reason']}")

    if not hb["healthy"] and hb["age_seconds"] > 0:
        event = WatchdogEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            event_type="stale_heartbeat",
            message=hb["reason"],
            severity="critical",
        )
        write_event(event)
        await send_discord(f"Trader heartbeat stale: {hb['reason']}", color=15158332)

        # Attempt restart
        if restart_trader():
            restart_event = WatchdogEvent(
                ts=datetime.now(timezone.utc).isoformat(),
                event_type="restart",
                message="Trader container restarted due to stale heartbeat",
                severity="warning",
            )
            write_event(restart_event)
            await send_discord("Trader container restarted", color=16776960)

    # 2. Portfolio sanity
    ps = check_portfolio_sanity()
    status = "OK" if ps["healthy"] else "FAIL"
    print(f"  Portfolio: {status} (${ps['balance']:.2f}) - {ps['reason']}")

    if not ps["healthy"]:
        event = WatchdogEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            event_type="anomaly",
            message=ps["reason"],
            severity="critical",
        )
        write_event(event)
        await send_discord(f"Portfolio anomaly: {ps['reason']}", color=15158332)

    # 3. API connectivity
    api = await check_api_connectivity()
    status = "OK" if api["healthy"] else "FAIL"
    print(f"  Gamma API: {status} - {api['reason']}")

    if not api["healthy"]:
        event = WatchdogEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            event_type="api_down",
            message=api["reason"],
            severity="warning",
        )
        write_event(event)

    # Summary
    all_healthy = hb["healthy"] and ps["healthy"] and api["healthy"]
    if all_healthy:
        hb_data = hb.get("data", {})
        print(f"  Status: ALL HEALTHY | Balance: ${hb_data.get('balance', 0):.2f} | "
              f"Positions: {hb_data.get('positions', 0)} | P&L: ${hb_data.get('pnl', 0):+.2f}")


async def main():
    """Main watchdog loop."""
    print(f"[WATCHDOG] Starting (interval={INTERVAL}s, stale_threshold={STALE_THRESHOLD}s)")

    while True:
        try:
            await run_check()
        except Exception as e:
            print(f"[WATCHDOG] Check error: {e}")

        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
