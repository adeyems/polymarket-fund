#!/usr/bin/env python3
"""
Full wallet asset audit for Polymarket trading wallet.
Outputs structured JSON with all asset types.

Usage:
    source /run/sovereign-hive/env && python3 /app/sovereign-hive/tools/wallet_audit.py

The monitor agent runs this via SSH to get the COMPLETE picture — not just USDC.

Assets checked:
1. USDC.e balance (wallet cash)
2. Conditional tokens on CTF Exchange (shares from trades)
3. NegRisk adapter tokens
4. Open CLOB orders (escrowed USDC)
5. Market resolution status
6. Current CLOB orderbook prices
7. POL balance (gas)
"""
import os
import json
import sys
from datetime import datetime, timezone

# ── Bootstrap ──────────────────────────────────────────────────────────
for envpath in ["/run/sovereign-hive/env", "/app/sovereign-hive/.env"]:
    if os.path.exists(envpath):
        try:
            from dotenv import load_dotenv
            load_dotenv(envpath)
        except ImportError:
            # Manual parsing if dotenv not available
            with open(envpath) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip("'\"")

try:
    from web3 import Web3
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    import requests
except ImportError as e:
    print(json.dumps({"error": "missing dependency: %s" % e, "timestamp": datetime.now(timezone.utc).isoformat()}))
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────
WALLET_KEY = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEGRISK_ADDRESS = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
RPC_ENDPOINTS = [
    "https://1rpc.io/matic",
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.llamarpc.com",
]

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}],
     "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
]
CTF_ABI = [
    {"constant": True,
     "inputs": [{"name": "_owner", "type": "address"}, {"name": "_id", "type": "uint256"}],
     "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}],
     "type": "function"}
]

result = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "wallet_address": None,
    "usdc_balance": 0.0,
    "pol_balance": 0.0,
    "conditional_tokens": [],
    "open_orders": [],
    "clob_locked": 0.0,
    "sell_order_shares_value": 0.0,
    "total_shares_value": 0.0,
    "total_assets": 0.0,
    "starting_balance": 82.88,
    "pnl": 0.0,
    "errors": [],
    "actions_needed": [],
}


def get_web3():
    """Try multiple RPC endpoints."""
    for rpc in RPC_ENDPOINTS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
            if w3.is_connected():
                return w3
        except Exception:
            continue
    return None


def get_clob_client():
    """Initialize CLOB client."""
    creds = ApiCreds(
        api_key=os.environ.get("CLOB_API_KEY", ""),
        api_secret=os.environ.get("CLOB_SECRET", ""),
        api_passphrase=os.environ.get("CLOB_PASSPHRASE", "")
    )
    return ClobClient(
        host="https://clob.polymarket.com", chain_id=137,
        key=WALLET_KEY, creds=creds, signature_type=0,
    )


def check_usdc_and_pol(w3, address):
    """Check USDC.e and POL balances."""
    try:
        usdc = w3.eth.contract(
            address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI
        )
        raw = usdc.functions.balanceOf(address).call()
        decimals = usdc.functions.decimals().call()
        result["usdc_balance"] = raw / (10 ** decimals)
    except Exception as e:
        result["errors"].append("USDC check failed: %s" % str(e)[:100])

    try:
        result["pol_balance"] = w3.eth.get_balance(address) / 1e18
    except Exception as e:
        result["errors"].append("POL check failed: %s" % str(e)[:100])


def check_clob_trades_and_tokens(w3, address, client):
    """Get all CLOB trades, then check on-chain token balances."""
    # Get all trades to find asset IDs and outcome labels
    asset_ids = set()
    asset_outcomes = {}  # asset_id -> outcome label from trade data
    trades = []
    try:
        raw_trades = client.get_trades()
        for t in raw_trades:
            trade = {
                "side": t.get("side", "?"),
                "size": float(t.get("size", 0)),
                "price": float(t.get("price", 0)),
                "asset_id": t.get("asset_id", ""),
                "market": t.get("market", ""),
                "outcome": t.get("outcome", ""),
                "match_time": t.get("match_time", ""),
                "trader_side": t.get("trader_side", ""),
            }
            trades.append(trade)
            if trade["asset_id"]:
                asset_ids.add(trade["asset_id"])
                # Save outcome label from trade data (CLOB trades have the outcome)
                if trade["outcome"]:
                    asset_outcomes[trade["asset_id"]] = trade["outcome"]
    except Exception as e:
        result["errors"].append("CLOB trades failed: %s" % str(e)[:100])

    # Check conditional token balances for every traded asset
    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI)
    neg_risk = w3.eth.contract(address=Web3.to_checksum_address(NEGRISK_ADDRESS), abi=CTF_ABI)

    for asset_id in asset_ids:
        try:
            token_id = int(asset_id)
        except (ValueError, TypeError):
            continue

        shares = 0.0
        source = None

        # Check CTF Exchange
        try:
            balance = ctf.functions.balanceOf(address, token_id).call()
            ctf_shares = balance / 1e6
            if ctf_shares > 0.001:
                shares = ctf_shares
                source = "CTF"
        except Exception:
            pass

        # Check NegRisk Adapter
        try:
            balance = neg_risk.functions.balanceOf(address, token_id).call()
            nr_shares = balance / 1e6
            if nr_shares > 0.001:
                shares += nr_shares
                if source:
                    source += "+NegRisk"
                else:
                    source = "NegRisk"
        except Exception:
            pass

        if shares > 0.001:
            # Use outcome from trade data if available (more reliable than Gamma for token matching)
            known_outcome = asset_outcomes.get(asset_id, "unknown")

            # Look up market info
            token_info = {
                "asset_id": asset_id,
                "shares": round(shares, 4),
                "source": source,
                "market_question": "unknown",
                "outcome": known_outcome,
                "resolved": False,
                "winner": False,
                "closed": False,
                "current_price": 0.0,
                "current_value": 0.0,
                "max_value": round(shares, 2),  # $1 per share if wins
            }

            # Get market details from Gamma API
            try:
                resp = requests.get(
                    "https://gamma-api.polymarket.com/markets?clob_token_ids=%s" % asset_id,
                    timeout=10
                )
                data = resp.json()
                if data:
                    m = data[0]
                    token_info["market_question"] = m.get("question", "unknown")
                    token_info["resolved"] = bool(m.get("resolved"))
                    token_info["closed"] = bool(m.get("closed"))

                    # Try to find our specific token in the market's tokens array
                    matched_token = False
                    for tok in m.get("tokens", []):
                        if tok.get("token_id") == asset_id:
                            matched_token = True
                            token_info["outcome"] = tok.get("outcome", known_outcome)
                            token_info["winner"] = bool(tok.get("winner"))
                            price = tok.get("price")
                            if price is not None:
                                token_info["current_price"] = float(price)

                    # If Gamma didn't match, keep outcome from trade data
                    if not matched_token and known_outcome != "unknown":
                        token_info["outcome"] = known_outcome

                    # Check CLOB orderbook for current sellable price (only for open markets)
                    if not token_info["closed"]:
                        try:
                            book_resp = requests.get(
                                "https://clob.polymarket.com/book?token_id=%s" % asset_id,
                                timeout=10
                            )
                            if book_resp.status_code == 200:
                                book = book_resp.json()
                                bids = book.get("bids", [])
                                if bids:
                                    best_bid = max(bids, key=lambda x: float(x.get("price", 0)))
                                    token_info["current_price"] = float(best_bid.get("price", 0))
                        except Exception:
                            pass

                    token_info["current_value"] = round(shares * token_info["current_price"], 2)

                    # Determine action needed
                    if token_info["resolved"] and token_info["winner"]:
                        token_info["action"] = "REDEEM — resolved in our favor, worth $%.2f" % shares
                        token_info["current_value"] = round(shares, 2)  # $1 per share
                        result["actions_needed"].append(
                            "REDEEM %.2f shares of '%s' ($%.2f)" % (
                                shares, token_info["outcome"], shares
                            )
                        )
                    elif token_info["resolved"] and not token_info["winner"]:
                        token_info["action"] = "WORTHLESS — resolved against us"
                        token_info["current_value"] = 0.0
                    elif token_info["closed"] and not token_info["resolved"]:
                        # Market closed but not yet resolved — likely pending resolution
                        # For closed markets, value at max (pending outcome) for conservative reporting
                        token_info["action"] = "PENDING RESOLUTION — market closed, awaiting result"
                        token_info["current_value"] = round(shares, 2)  # Assume $1 until resolution (conservative high)
                        result["actions_needed"].append(
                            "CHECK resolution for '%s' (%s) — %.2f shares (worth $%.2f if wins, $0 if loses)" % (
                                token_info["market_question"][:60],
                                token_info["outcome"], shares, shares
                            )
                        )
                    else:
                        token_info["action"] = "OPEN — can sell at $%.2f or hold" % token_info["current_price"]

            except Exception as e:
                result["errors"].append("Gamma lookup failed for %s: %s" % (asset_id[:12], str(e)[:80]))

            result["conditional_tokens"].append(token_info)
            result["total_shares_value"] += token_info["current_value"]


def check_open_orders(client):
    """Check for open CLOB orders with locked USDC."""
    try:
        orders = client.get_orders()
        for o in orders:
            side = o.get("side", "?")
            size = float(o.get("original_size", 0))
            price = float(o.get("price", 0))
            matched = float(o.get("size_matched", 0))
            remaining = size - matched
            locked_usdc = remaining * price if side == "BUY" else 0
            locked_shares_value = remaining * price if side == "SELL" else 0

            result["open_orders"].append({
                "side": side,
                "size": size,
                "price": price,
                "matched": matched,
                "remaining": remaining,
                "locked_usdc": round(locked_usdc, 2),
                "locked_shares_value": round(locked_shares_value, 2),
                "status": o.get("status", "?"),
            })
            result["clob_locked"] += locked_usdc
            result["sell_order_shares_value"] += locked_shares_value
    except Exception as e:
        result["errors"].append("CLOB orders failed: %s" % str(e)[:100])


def main():
    if not WALLET_KEY:
        result["errors"].append("POLYMARKET_PRIVATE_KEY not set")
        print(json.dumps(result, indent=2))
        sys.exit(1)

    w3 = get_web3()
    if not w3:
        result["errors"].append("All RPC endpoints failed")
        print(json.dumps(result, indent=2))
        sys.exit(1)

    account = w3.eth.account.from_key(WALLET_KEY)
    address = account.address
    result["wallet_address"] = address

    # 1. USDC + POL
    check_usdc_and_pol(w3, address)

    # 2. CLOB client
    client = get_clob_client()

    # 3. Trades → Token balances → Market info
    check_clob_trades_and_tokens(w3, address, client)

    # 4. Open orders
    check_open_orders(client)

    # 5. Calculate totals
    # NOTE: clob_locked (unfilled BUY orders) is NOT real money — it's an off-chain
    # intent on Polymarket's CLOB. USDC only moves on-chain when orders are FILLED.
    # Do NOT add clob_locked to total_assets. Only count on-chain balances:
    #   - USDC in wallet (already includes any locked amounts — they were never sent)
    #   - Conditional tokens held on-chain (shares)
    #   - Shares locked in SELL orders (still ours until sold)
    result["clob_locked"] = round(result["clob_locked"], 2)
    result["sell_order_shares_value"] = round(result["sell_order_shares_value"], 2)
    result["total_shares_value"] = round(result["total_shares_value"], 2)
    result["total_assets"] = round(
        result["usdc_balance"] + result["total_shares_value"]
        + result["sell_order_shares_value"], 2
    )
    result["pnl"] = round(result["total_assets"] - result["starting_balance"], 2)

    # 6. Summary line for quick parsing
    result["summary"] = (
        "USDC=$%.2f | Shares=$%.2f | SellOrders=$%.2f | CLOBIntents=$%.2f | "
        "Total=$%.2f | P&L=$%+.2f | POL=%.1f | Actions=%d"
    ) % (
        result["usdc_balance"], result["total_shares_value"],
        result["sell_order_shares_value"], result["clob_locked"],
        result["total_assets"], result["pnl"], result["pol_balance"],
        len(result["actions_needed"])
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
