#!/usr/bin/env python3
"""
Redeem resolved conditional tokens for USDC.

When a Polymarket condition resolves in your favor, your shares are worth $1 each.
Call redeemPositions() on the CTF contract to convert shares → USDC.

Usage (on EC2):
    sudo bash -c 'set -a && source /run/sovereign-hive/env && set +a && \
        cd /app/sovereign-hive && ./venv/bin/python tools/redeem_shares.py'
"""
import os
import sys
import json
from web3 import Web3

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

PK = os.environ.get("POLYMARKET_PRIVATE_KEY")
if not PK:
    print("ERROR: POLYMARKET_PRIVATE_KEY not set")
    sys.exit(1)

RPC_ENDPOINTS = [
    "https://1rpc.io/matic",
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.llamarpc.com",
]

# Polymarket contracts
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# Tennis market (Auger-Aliassime vs Zhang)
CONDITION_ID = "0x0e71b3c6b61504df944761289aea4aef1d4587cee4050e4ce07e3299c54a9248"
TOKEN_ID = "49689741427622618555134572237092324131804188952521642977757233337834517599219"

# CTF redeemPositions ABI
CTF_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"}
        ],
        "name": "redeemPositions",
        "outputs": [],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_id", "type": "uint256"}
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "", "type": "bytes32"},
            {"name": "", "type": "uint256"}
        ],
        "name": "payoutNumerators",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "", "type": "bytes32"}],
        "name": "payoutDenominator",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
]

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}],
     "type": "function"},
]


def get_web3():
    for rpc in RPC_ENDPOINTS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
            if w3.is_connected():
                return w3
        except Exception:
            continue
    return None


def main():
    w3 = get_web3()
    if not w3:
        print("ERROR: All RPC endpoints failed")
        sys.exit(1)

    account = w3.eth.account.from_key(PK)
    addr = account.address
    print(f"Wallet: {addr}")

    ctf = w3.eth.contract(address=Web3.to_checksum_address(CTF), abi=CTF_ABI)
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)

    # Check USDC balance before
    usdc_before = usdc.functions.balanceOf(addr).call() / 1e6
    print(f"USDC before: ${usdc_before:.2f}")

    # Check conditional token balance
    token_balance = ctf.functions.balanceOf(addr, int(TOKEN_ID)).call()
    shares = token_balance / 1e6
    print(f"Tennis shares: {shares:.4f}")

    if shares < 0.001:
        print("No shares to redeem.")
        sys.exit(0)

    # Verify condition is resolved
    condition_bytes = bytes.fromhex(CONDITION_ID[2:])
    denom = ctf.functions.payoutDenominator(condition_bytes).call()
    if denom == 0:
        print("ERROR: Condition not resolved yet. Cannot redeem.")
        sys.exit(1)

    p0 = ctf.functions.payoutNumerators(condition_bytes, 0).call()
    p1 = ctf.functions.payoutNumerators(condition_bytes, 1).call()
    print(f"Payout: [{p0}, {p1}] (denom={denom})")

    if p0 == 0:
        print("WARNING: Outcome 0 (Auger-Aliassime) did NOT win. Shares are worthless.")
        sys.exit(1)

    # Redeem positions
    # For binary markets: indexSets = [1] for outcome 0, [2] for outcome 1
    # Outcome 0 (Auger-Aliassime) has indexSet = 1 (binary: 01)
    parent_collection_id = bytes(32)  # 0x0 for root collection

    print(f"\nRedeeming {shares:.4f} shares for ~${shares:.2f} USDC...")

    nonce = w3.eth.get_transaction_count(addr)
    gas_price = int(w3.eth.gas_price * 1.5)

    tx = ctf.functions.redeemPositions(
        Web3.to_checksum_address(USDC),   # collateralToken
        parent_collection_id,              # parentCollectionId (root)
        condition_bytes,                   # conditionId
        [1]                                # indexSets: [1] = outcome 0
    ).build_transaction({
        "from": addr,
        "nonce": nonce,
        "gas": 200000,
        "gasPrice": gas_price,
        "chainId": 137,
    })

    signed = w3.eth.account.sign_transaction(tx, PK)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"TX: {tx_hash.hex()}")
    print("Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt.status == 1:
        # Check balances after
        usdc_after = usdc.functions.balanceOf(addr).call() / 1e6
        shares_after = ctf.functions.balanceOf(addr, int(TOKEN_ID)).call() / 1e6
        print(f"\nSUCCESS!")
        print(f"USDC before: ${usdc_before:.2f}")
        print(f"USDC after:  ${usdc_after:.2f}")
        print(f"Redeemed:    ${usdc_after - usdc_before:.2f}")
        print(f"Shares remaining: {shares_after:.4f}")
    else:
        print(f"\nFAILED: Transaction reverted")
        print(f"Gas used: {receipt.gasUsed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
