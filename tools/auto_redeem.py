#!/usr/bin/env python3
"""
Auto-redeem resolved Polymarket positions.

Discovers all positions with shares > 0, checks if markets are resolved,
and redeems winning/50-50 positions on-chain. Safe to run repeatedly
(idempotent — if no redeemable shares, exits cleanly).

Outputs structured JSON for the monitor agent to parse.

Usage (EC2):
    sudo bash -c 'set -a && source /run/sovereign-hive/env && set +a && \
        cd /app/sovereign-hive && ./venv/bin/python tools/auto_redeem.py'

Usage (local):
    python tools/auto_redeem.py
"""
import os
import sys
import json
import time
from datetime import datetime, timezone

# ── Bootstrap ──────────────────────────────────────────────────────────
for envpath in ["/run/sovereign-hive/env", "/app/sovereign-hive/.env", ".env"]:
    if os.path.exists(envpath):
        try:
            from dotenv import load_dotenv
            load_dotenv(envpath)
        except ImportError:
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
    print(json.dumps({"error": f"missing dependency: {e}",
                       "timestamp": datetime.now(timezone.utc).isoformat()}))
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────
WALLET_KEY = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
NEGRISK_ADDRESS = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
GAMMA_API = "https://gamma-api.polymarket.com/markets"

RPC_ENDPOINTS = [
    "https://1rpc.io/matic",
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.llamarpc.com",
]

CTF_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_id", "type": "uint256"},
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "", "type": "bytes32"}, {"name": "", "type": "uint256"}],
        "name": "payoutNumerators",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "payoutDenominator",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}],
     "type": "function"},
]


# ── Helpers ────────────────────────────────────────────────────────────

def get_web3():
    for rpc in RPC_ENDPOINTS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
            if w3.is_connected():
                return w3
        except Exception:
            continue
    return None


def get_clob_client():
    return ClobClient(
        host="https://clob.polymarket.com", chain_id=137,
        key=WALLET_KEY,
        creds=ApiCreds(
            api_key=os.environ.get("CLOB_API_KEY", ""),
            api_secret=os.environ.get("CLOB_SECRET", ""),
            api_passphrase=os.environ.get("CLOB_PASSPHRASE", ""),
        ),
        signature_type=0,
    )


# ── Position Discovery ────────────────────────────────────────────────

def discover_positions(w3, address, client):
    """Find all positions with shares > 0 on-chain."""
    asset_ids = set()
    asset_outcomes = {}

    try:
        for t in client.get_trades():
            aid = t.get("asset_id", "")
            if aid:
                asset_ids.add(aid)
                outcome = t.get("outcome", "")
                if outcome:
                    asset_outcomes[aid] = outcome
    except Exception as e:
        return [], [f"CLOB trades failed: {str(e)[:100]}"]

    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI)
    neg = w3.eth.contract(address=Web3.to_checksum_address(NEGRISK_ADDRESS), abi=CTF_ABI[:2])

    positions = []
    errors = []

    for aid in asset_ids:
        try:
            token_id = int(aid)
        except (ValueError, TypeError):
            continue

        shares = 0.0
        source = None

        try:
            bal = ctf.functions.balanceOf(address, token_id).call()
            ctf_shares = bal / 1e6
            if ctf_shares > 0.001:
                shares = ctf_shares
                source = "CTF"
        except Exception:
            pass

        try:
            bal = neg.functions.balanceOf(address, token_id).call()
            nr_shares = bal / 1e6
            if nr_shares > 0.001:
                shares += nr_shares
                source = (source + "+NegRisk") if source else "NegRisk"
        except Exception:
            pass

        if shares > 0.001:
            positions.append({
                "asset_id": aid,
                "shares": round(shares, 4),
                "source": source,
                "outcome": asset_outcomes.get(aid, "unknown"),
            })

    return positions, errors


# ── Redeemability Check ───────────────────────────────────────────────

def check_redeemability(w3, ctf, positions):
    """Check Gamma API + on-chain to determine which positions are redeemable."""
    enriched = []

    for pos in positions:
        info = {**pos, "is_redeemable": False, "condition_id": None,
                "index_set": None, "payout_type": None,
                "expected_value": 0.0, "market": "unknown", "skip_reason": None}

        # Gamma API lookup
        try:
            resp = requests.get(f"{GAMMA_API}?clob_token_ids={pos['asset_id']}", timeout=10)
            data = resp.json()
            if not data:
                info["skip_reason"] = "not found on Gamma API"
                enriched.append(info)
                continue

            m = data[0]
            info["market"] = m.get("question", "unknown")[:80]
            info["condition_id"] = m.get("conditionId")

            if not m.get("resolved"):
                info["skip_reason"] = "not resolved"
                enriched.append(info)
                continue

            # Determine our outcome index from token matching
            outcome_index = None
            for i, tok in enumerate(m.get("tokens", [])):
                if tok.get("token_id") == pos["asset_id"]:
                    outcome_index = i
                    info["outcome"] = tok.get("outcome", pos["outcome"])
                    break

            if outcome_index is None:
                info["skip_reason"] = "token not found in market tokens array"
                enriched.append(info)
                continue

            info["index_set"] = 1 << outcome_index

        except Exception as e:
            info["skip_reason"] = f"Gamma API error: {str(e)[:80]}"
            enriched.append(info)
            continue

        # On-chain verification
        try:
            cid = info["condition_id"]
            condition_bytes = bytes.fromhex(cid[2:]) if cid.startswith("0x") else bytes.fromhex(cid)
            denom = ctf.functions.payoutDenominator(condition_bytes).call()

            if denom == 0:
                info["skip_reason"] = "payoutDenominator is 0 (not resolved on-chain)"
                enriched.append(info)
                continue

            p_ours = ctf.functions.payoutNumerators(condition_bytes, outcome_index).call()

            if p_ours == 0:
                info["payout_type"] = "loser"
                info["expected_value"] = 0.0
                info["skip_reason"] = "our outcome lost (payout numerator = 0)"
                enriched.append(info)
                continue

            # Determine payout type
            p_other = ctf.functions.payoutNumerators(condition_bytes, 1 - outcome_index).call()
            if p_other == 0:
                info["payout_type"] = "full_win"
                info["expected_value"] = round(pos["shares"], 2)
            else:
                info["payout_type"] = "partial_50_50"
                payout_ratio = p_ours / denom
                info["expected_value"] = round(pos["shares"] * payout_ratio, 2)

            # NegRisk-only positions: conservative skip
            if pos["source"] == "NegRisk":
                info["skip_reason"] = "NegRisk-only position — may need manual unwrap"
                enriched.append(info)
                continue

            info["is_redeemable"] = True

        except Exception as e:
            info["skip_reason"] = f"on-chain check error: {str(e)[:80]}"

        enriched.append(info)

    return enriched


# ── Redemption Execution ──────────────────────────────────────────────

def redeem_position(w3, ctf, usdc, account, pos):
    """Execute on-chain redemption for a single position."""
    addr = account.address
    token_id = int(pos["asset_id"])
    cid = pos["condition_id"]
    condition_bytes = bytes.fromhex(cid[2:]) if cid.startswith("0x") else bytes.fromhex(cid)

    # Pre-flight: verify shares still exist
    balance = ctf.functions.balanceOf(addr, token_id).call()
    if balance < 1000:  # < 0.001 shares (in 6-decimal raw units)
        return {"status": "SKIPPED", "error": "no shares on-chain (already redeemed?)"}

    usdc_before = usdc.functions.balanceOf(addr).call() / 1e6

    # Build tx
    nonce = w3.eth.get_transaction_count(addr)
    gas_price = int(w3.eth.gas_price * 1.5)

    tx = ctf.functions.redeemPositions(
        Web3.to_checksum_address(USDC_ADDRESS),
        bytes(32),       # parentCollectionId (root)
        condition_bytes,
        [pos["index_set"]],
    ).build_transaction({
        "from": addr,
        "nonce": nonce,
        "gas": 200000,
        "gasPrice": gas_price,
        "chainId": 137,
    })

    signed = w3.eth.account.sign_transaction(tx, WALLET_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt.status != 1:
        return {"status": "FAILED", "error": "transaction reverted",
                "tx_hash": tx_hash.hex(), "gas_used": receipt.gasUsed}

    # Post-flight: verify USDC increased
    usdc_after = usdc.functions.balanceOf(addr).call() / 1e6
    actual_gained = round(usdc_after - usdc_before, 2)
    shares_remaining = ctf.functions.balanceOf(addr, token_id).call() / 1e6

    return {
        "status": "SUCCESS",
        "tx_hash": tx_hash.hex(),
        "usdc_gained": actual_gained,
        "shares_remaining": round(shares_remaining, 4),
    }


# ── Main ──────────────────────────────────────────────────────────────

def main():
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "wallet_address": None,
        "usdc_before": 0.0,
        "usdc_after": 0.0,
        "positions_found": 0,
        "positions_redeemable": 0,
        "positions_redeemed": 0,
        "total_redeemed_usdc": 0.0,
        "transactions": [],
        "errors": [],
    }

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
    result["wallet_address"] = account.address

    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI)
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI)

    result["usdc_before"] = round(usdc.functions.balanceOf(account.address).call() / 1e6, 2)

    # Discover positions
    client = get_clob_client()
    positions, disc_errors = discover_positions(w3, account.address, client)
    result["errors"].extend(disc_errors)
    result["positions_found"] = len(positions)

    if not positions:
        result["usdc_after"] = result["usdc_before"]
        print(json.dumps(result, indent=2))
        return

    # Check redeemability
    enriched = check_redeemability(w3, ctf, positions)
    redeemable = [p for p in enriched if p["is_redeemable"]]
    result["positions_redeemable"] = len(redeemable)

    # Log skipped positions
    for p in enriched:
        if not p["is_redeemable"] and p.get("skip_reason"):
            result["errors"].append(
                f"SKIP {p['market'][:40]}: {p['skip_reason']}"
            )

    # Redeem each
    for pos in redeemable:
        tx_result = {
            "market": pos["market"],
            "outcome": pos["outcome"],
            "shares": pos["shares"],
            "payout_type": pos["payout_type"],
            "expected_usdc": pos["expected_value"],
            "actual_usdc": 0.0,
            "tx_hash": None,
            "status": "PENDING",
            "error": None,
        }

        try:
            r = redeem_position(w3, ctf, usdc, account, pos)
            tx_result["status"] = r["status"]
            tx_result["tx_hash"] = r.get("tx_hash")
            tx_result["actual_usdc"] = r.get("usdc_gained", 0.0)
            tx_result["error"] = r.get("error")

            if r["status"] == "SUCCESS":
                result["positions_redeemed"] += 1
                # Small delay between transactions to avoid nonce issues
                time.sleep(2)
        except Exception as e:
            tx_result["status"] = "ERROR"
            tx_result["error"] = str(e)[:200]

        result["transactions"].append(tx_result)

    # Final balance
    result["usdc_after"] = round(usdc.functions.balanceOf(account.address).call() / 1e6, 2)
    result["total_redeemed_usdc"] = round(result["usdc_after"] - result["usdc_before"], 2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
