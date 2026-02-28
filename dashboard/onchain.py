#!/usr/bin/env python3
"""
On-Chain Wallet Verifier — READ-ONLY
======================================
Queries Polygon RPC directly for wallet balances.
No private keys needed — only the public wallet address.
Works independently of EC2 (no SSH required).

Data sources:
- Polygon RPC: USDC.e balance, POL balance
- CLOB API: Open orders, orderbook for each position
- Gamma API: Market metadata (question text, resolution status)
"""
import json
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────────
WALLET = "0x572FA217B5981d5f9F337a5eD5561084C665AD9A"
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e (Bridged) on Polygon
CTF_EXCHANGE = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEGRISK_ADAPTER = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

# Public RPCs (no API key needed for basic balance queries)
POLYGON_RPCS = [
    "https://polygon-rpc.com",
    "https://rpc-mainnet.matic.quiknode.pro",
    "https://polygon.llamarpc.com",
]

CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"

# ERC-20 balanceOf(address) → uint256
BALANCE_OF_SELECTOR = "0x70a08231"
# Pad address to 32 bytes
WALLET_PADDED = WALLET.lower().replace("0x", "").zfill(64)

REFRESH_INTERVAL = 120  # seconds between on-chain queries

# Cache
_cache = {
    "last_fetched": None,
    "data": None,
    "error": None,
}
_cache_lock = threading.Lock()


def _rpc_call(method: str, params: list, rpc_url: str, timeout: int = 10) -> Optional[dict]:
    """Make a JSON-RPC call to a Polygon node."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }).encode()
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _eth_call(to: str, data: str) -> Optional[str]:
    """Execute eth_call against multiple RPCs with fallback."""
    for rpc in POLYGON_RPCS:
        result = _rpc_call("eth_call", [{"to": to, "data": data}, "latest"], rpc)
        if result and "result" in result:
            return result["result"]
    return None


def get_usdc_balance() -> float:
    """Get USDC.e balance for our wallet (6 decimals)."""
    call_data = BALANCE_OF_SELECTOR + WALLET_PADDED
    result = _eth_call(USDC_E, call_data)
    if result and result != "0x":
        raw = int(result, 16)
        return raw / 1_000_000  # USDC has 6 decimals
    return 0.0


def get_pol_balance() -> float:
    """Get native POL (MATIC) balance."""
    for rpc in POLYGON_RPCS:
        result = _rpc_call("eth_getBalance", [WALLET, "latest"], rpc)
        if result and "result" in result:
            raw = int(result["result"], 16)
            return raw / 1e18  # 18 decimals
    return 0.0


def get_conditional_token_balance(token_id: str, exchange: str = CTF_EXCHANGE) -> float:
    """Get balance of a conditional token (ERC-1155).
    balanceOf(address,uint256) = 0x00fdd58e
    """
    selector = "0x00fdd58e"
    token_hex = hex(int(token_id))[2:].zfill(64) if token_id.isdigit() else token_id.zfill(64)
    call_data = selector + WALLET_PADDED + token_hex
    result = _eth_call(exchange, call_data)
    if result and result != "0x":
        raw = int(result, 16)
        return raw / 1e6  # Conditional tokens use 6 decimals (USDC-denominated)
    return 0.0


def _fetch_clob_orders() -> list:
    """Fetch open CLOB orders for our wallet (public API, no auth needed for read)."""
    # The CLOB open orders endpoint requires API key.
    # Fall back to cached portfolio data for order info.
    return []


def _fetch_clob_orderbook(token_id: str) -> dict:
    """Query CLOB orderbook for current bid/ask."""
    try:
        url = f"{CLOB_BASE}/book?token_id={token_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "SH-Dashboard/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 1.0
        spread = (best_ask - best_bid) / max(best_ask, 0.01) if best_ask > best_bid else 1.0
        bid_depth = sum(float(b.get("size", 0)) for b in bids[:5])
        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread * 100, 1),
            "bid_depth": round(bid_depth, 0),
        }
    except Exception:
        return {"best_bid": 0, "best_ask": 1, "spread_pct": 100.0, "bid_depth": 0}


def _fetch_market_info(condition_id: str) -> dict:
    """Get market metadata from Gamma API."""
    try:
        url = f"{GAMMA_BASE}/markets?condition_ids={condition_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "SH-Dashboard/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            markets = json.loads(resp.read())
        if markets:
            m = markets[0]
            return {
                "question": m.get("question", "Unknown"),
                "end_date": m.get("endDate", ""),
                "closed": m.get("closed", False),
                "resolved": m.get("resolved", False),
                "best_bid": float(m.get("bestBid", 0) or 0),
                "best_ask": float(m.get("bestAsk", 0) or 0),
                "volume_24h": float(m.get("volume24hr", 0) or 0),
                "liquidity": float(m.get("liquidityNum", 0) or 0),
            }
    except Exception:
        pass
    return {}


def fetch_full_state() -> dict:
    """Fetch complete on-chain + CLOB state. Called periodically."""
    now = datetime.now(timezone.utc)

    # 1. On-chain balances
    usdc = get_usdc_balance()
    pol = get_pol_balance()

    # 2. Known positions from cached ec2_live.json (for token IDs)
    cache_file = Path(__file__).parent / "cache" / "ec2_live.json"
    positions = {}
    try:
        ec2_data = json.loads(cache_file.read_text())
        raw_positions = ec2_data.get("portfolio", {}).get("positions", {})
        trade_history = ec2_data.get("portfolio", {}).get("trade_history", [])
    except (FileNotFoundError, json.JSONDecodeError):
        raw_positions = {}
        trade_history = []

    # 3. For each position, check on-chain token balance + CLOB orderbook
    total_position_value = 0.0
    for cid, pos in raw_positions.items():
        token_id = pos.get("token_id", "")
        entry_price = pos.get("entry_price", 0)
        cost_basis = pos.get("cost_basis", 0)
        shares_reported = pos.get("shares", 0)

        # On-chain token balance (verify we actually hold the shares)
        onchain_shares = 0.0
        if token_id and token_id.isdigit():
            onchain_shares = get_conditional_token_balance(token_id, CTF_EXCHANGE)
            if onchain_shares == 0:
                # Try NegRisk adapter
                onchain_shares = get_conditional_token_balance(token_id, NEGRISK_ADAPTER)

        # CLOB orderbook for current price
        orderbook = _fetch_clob_orderbook(token_id) if token_id else {}

        # Market metadata
        market_info = _fetch_market_info(cid)

        current_bid = orderbook.get("best_bid", 0)
        mark_value = onchain_shares * current_bid if current_bid > 0 else 0
        total_position_value += mark_value

        # Health assessment
        spread = orderbook.get("spread_pct", 100)
        if spread > 50:
            health = "dead"
        elif spread > 20:
            health = "warning"
        elif spread > 10:
            health = "caution"
        else:
            health = "healthy"

        positions[cid] = {
            "question": pos.get("question", market_info.get("question", "Unknown")),
            "token_id": token_id,
            "entry_price": entry_price,
            "cost_basis": cost_basis,
            "shares_reported": shares_reported,
            "shares_onchain": onchain_shares,
            "shares_match": abs(onchain_shares - shares_reported) < 0.1,
            "live_state": pos.get("live_state", "UNKNOWN"),
            "sell_order_id": pos.get("sell_order_id", ""),
            "current_bid": current_bid,
            "current_ask": orderbook.get("best_ask", 1),
            "spread_pct": spread,
            "bid_depth": orderbook.get("bid_depth", 0),
            "mark_value": round(mark_value, 2),
            "unrealized_pnl": round(mark_value - cost_basis, 2) if mark_value > 0 else round(-cost_basis, 2),
            "unrealized_pnl_pct": round((mark_value - cost_basis) / cost_basis * 100, 1) if cost_basis > 0 and mark_value > 0 else -100.0,
            "health": health,
            "market_closed": market_info.get("closed", False),
            "market_resolved": market_info.get("resolved", False),
            "end_date": market_info.get("end_date", ""),
            "sector": pos.get("sector", ""),
            "entry_time": pos.get("entry_time", ""),
            "hold_hours": 0,
        }

        # Calculate hold time
        entry_time = pos.get("entry_time", "")
        if entry_time:
            try:
                entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                positions[cid]["hold_hours"] = round((now - entry_dt).total_seconds() / 3600, 1)
            except (ValueError, TypeError):
                pass

    # 4. Total portfolio value
    total_invested = 85.0  # $20 initial + $65 deposit
    total_value = usdc + total_position_value
    pnl = total_value - total_invested

    state = {
        "fetched_at": now.isoformat(),
        "source": "onchain_direct",
        "wallet_address": WALLET,
        "polygonscan_url": f"https://polygonscan.com/address/{WALLET}",
        "balances": {
            "usdc": round(usdc, 2),
            "pol": round(pol, 4),
            "positions_mark_value": round(total_position_value, 2),
            "total": round(total_value, 2),
        },
        "pnl": {
            "total_invested": total_invested,
            "current_value": round(total_value, 2),
            "pnl_usd": round(pnl, 2),
            "pnl_pct": round(pnl / total_invested * 100, 1) if total_invested > 0 else 0,
        },
        "positions": positions,
        "trade_history": trade_history,
        "position_count": len(positions),
    }

    return state


def _refresh_loop():
    """Background thread that refreshes on-chain data periodically."""
    while True:
        try:
            data = fetch_full_state()
            with _cache_lock:
                _cache["data"] = data
                _cache["last_fetched"] = datetime.now(timezone.utc).isoformat()
                _cache["error"] = None
            # Also save to disk for persistence
            cache_file = Path(__file__).parent / "cache" / "onchain_state.json"
            cache_file.write_text(json.dumps(data, indent=2, default=str))
            print(f"[ONCHAIN] Refreshed: USDC=${data['balances']['usdc']:.2f}, "
                  f"Positions=${data['balances']['positions_mark_value']:.2f}, "
                  f"Total=${data['balances']['total']:.2f}")
        except Exception as e:
            with _cache_lock:
                _cache["error"] = str(e)
            print(f"[ONCHAIN] Error: {e}")
        time.sleep(REFRESH_INTERVAL)


def get_cached_state() -> Optional[dict]:
    """Get the most recent cached on-chain state."""
    with _cache_lock:
        return _cache["data"]


def start_onchain_fetcher():
    """Start the on-chain data fetcher as a daemon thread."""
    t = threading.Thread(target=_refresh_loop, daemon=True, name="onchain-fetcher")
    t.start()
    print(f"[ONCHAIN] Fetcher started (every {REFRESH_INTERVAL}s)")
