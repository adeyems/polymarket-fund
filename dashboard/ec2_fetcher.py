#!/usr/bin/env python3
"""
EC2 Data Fetcher — Background SSH Pull
=======================================
Periodically SSHes into EC2 to fetch live portfolio JSON.
Runs as a daemon thread. Zero ports exposed on EC2.
Falls back to monitor_state.json when EC2 is unreachable.
"""
import json
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FETCH_INTERVAL = 60  # seconds
SSH_TIMEOUT = 10  # seconds
EC2_USER = "ec2-user"
EC2_IP = "16.54.60.150"
REMOTE_PORTFOLIO = "/app/sovereign-hive/sovereign_hive/data/portfolio_market_maker.json"
CLOB_BOOK_URL = "https://clob.polymarket.com/book?token_id="


def _fetch_orderbook(token_id: str) -> dict:
    """Query CLOB orderbook for a single token. Returns {best_bid, best_ask, spread_pct}."""
    try:
        req = urllib.request.Request(CLOB_BOOK_URL + token_id, headers={"User-Agent": "SH-Dashboard/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 1.0
        spread = (best_ask - best_bid) / max(best_ask, 0.01) if best_ask > best_bid else 1.0
        return {"best_bid": best_bid, "best_ask": best_ask, "spread_pct": round(spread * 100, 1)}
    except Exception:
        return {"best_bid": 0, "best_ask": 1, "spread_pct": 100.0}


def _enrich_positions_with_orderbook(portfolio: dict) -> dict:
    """Query CLOB orderbook for each open position and store health data."""
    positions = portfolio.get("positions", {})
    orderbook_data = {}
    for cid, pos in positions.items():
        token_id = pos.get("token_id", "")
        if token_id:
            orderbook_data[cid] = _fetch_orderbook(token_id)
    portfolio["_orderbook_health"] = orderbook_data
    return portfolio


def fetch_ec2_portfolio(cache_dir: Path, project_dir: Path) -> bool:
    """Fetch portfolio JSON from EC2 via SSH. Returns True on success."""
    ssh_key = project_dir / "infra" / "live" / "prod" / "sovereign-hive-key"
    cache_file = cache_dir / "ec2_live.json"

    if not ssh_key.exists():
        return False

    cmd = [
        "ssh",
        "-o", "IdentitiesOnly=yes",
        "-i", str(ssh_key),
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        f"{EC2_USER}@{EC2_IP}",
        f"cat {REMOTE_PORTFOLIO}",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=SSH_TIMEOUT
        )
        if result.returncode == 0 and result.stdout.strip():
            portfolio = json.loads(result.stdout)
            # Enrich with live CLOB orderbook data
            portfolio = _enrich_positions_with_orderbook(portfolio)
            wrapped = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": "ec2_ssh",
                "ec2_ip": EC2_IP,
                "portfolio": portfolio,
            }
            cache_file.write_text(json.dumps(wrapped, indent=2))
            return True
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass

    return False


def _fetcher_loop(cache_dir: Path, project_dir: Path):
    """Background loop that fetches EC2 data periodically."""
    while True:
        try:
            success = fetch_ec2_portfolio(cache_dir, project_dir)
            if success:
                print("[DASHBOARD] EC2 data fetched OK")
        except Exception:
            pass  # Never crash the fetcher thread
        time.sleep(FETCH_INTERVAL)


def start_fetcher(cache_dir: Path, project_dir: Path):
    """Start the EC2 fetcher as a daemon thread."""
    t = threading.Thread(
        target=_fetcher_loop,
        args=(cache_dir, project_dir),
        daemon=True,
        name="ec2-fetcher",
    )
    t.start()
    print("[DASHBOARD] EC2 fetcher started (every %ds)" % FETCH_INTERVAL)
