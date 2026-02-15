#!/usr/bin/env python3
"""
Swap USDC.e (Bridged) to Native USDC on Polygon
Uses QuickSwap Router for the swap
"""
import os
import sys
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv

load_dotenv()

# Polygon RPC
RPC_URLS = [
    "https://1rpc.io/matic",
    "https://polygon-rpc.com",
    "https://rpc-mainnet.maticvigil.com"
]

# Token Addresses
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # Bridged USDC (6 decimals)
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # Native USDC (6 decimals)

# QuickSwap Router V2
QUICKSWAP_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"

# Minimal ABIs
ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}
]

ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForTokens",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"}
        ],
        "name": "getAmountsOut",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    }
]

def connect_web3():
    """Connect to Polygon RPC with failover."""
    from web3.middleware import ExtraDataToPOAMiddleware

    for rpc in RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc))
            # Inject POA middleware for Polygon
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.is_connected():
                print(f"[CONNECTED] {rpc}")
                return w3
        except Exception as e:
            print(f"[FAILED] {rpc}: {e}")
    raise Exception("All RPCs failed")

def swap_usdc_e_to_native(amount_to_swap=None):
    """
    Swap USDC.e to Native USDC

    Args:
        amount_to_swap: Amount in human-readable format (e.g., 99.93). If None, swaps all.
    """
    # Load credentials
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not pk:
        print("[ERROR] POLYMARKET_PRIVATE_KEY not found in .env")
        return

    # Connect
    w3 = connect_web3()
    account = Account.from_key(pk)
    address = account.address
    print(f"[WALLET] {address}")

    # Load contracts
    usdc_e_contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=ERC20_ABI)
    usdc_native_contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_NATIVE), abi=ERC20_ABI)
    router = w3.eth.contract(address=Web3.to_checksum_address(QUICKSWAP_ROUTER), abi=ROUTER_ABI)

    # Check balances
    usdc_e_balance_raw = usdc_e_contract.functions.balanceOf(address).call()
    usdc_e_balance = usdc_e_balance_raw / 1e6

    usdc_native_balance_raw = usdc_native_contract.functions.balanceOf(address).call()
    usdc_native_balance = usdc_native_balance_raw / 1e6

    print(f"[BALANCE] USDC.e: {usdc_e_balance:.6f}")
    print(f"[BALANCE] Native USDC: {usdc_native_balance:.6f}")

    if usdc_e_balance == 0:
        print("[ERROR] No USDC.e to swap")
        return

    # Determine swap amount
    if amount_to_swap is None:
        amount_in = usdc_e_balance_raw  # Swap all
    else:
        amount_in = int(amount_to_swap * 1e6)

    amount_in_human = amount_in / 1e6
    print(f"[SWAP] Amount: {amount_in_human:.6f} USDC.e")

    # Check/Approve Router
    allowance = usdc_e_contract.functions.allowance(address, QUICKSWAP_ROUTER).call()
    if allowance < amount_in:
        print(f"[APPROVE] Approving QuickSwap Router...")
        approve_tx = usdc_e_contract.functions.approve(
            QUICKSWAP_ROUTER,
            2**256 - 1  # Max approval
        ).build_transaction({
            'from': address,
            'gas': 100000,
            'gasPrice': w3.eth.gas_price,
            'nonce': w3.eth.get_transaction_count(address)
        })

        signed_approve = account.sign_transaction(approve_tx)
        approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        print(f"[APPROVE] TX: {approve_hash.hex()}")

        receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=120)
        if receipt['status'] != 1:
            print("[ERROR] Approval failed")
            return
        print(f"[APPROVE] Success")

    # Get expected output
    path = [USDC_E, USDC_NATIVE]
    try:
        amounts_out = router.functions.getAmountsOut(amount_in, path).call()
        expected_out = amounts_out[1] / 1e6
        print(f"[QUOTE] Expected output: {expected_out:.6f} Native USDC")

        # Set slippage to 0.5%
        min_out = int(amounts_out[1] * 0.995)
    except Exception as e:
        print(f"[WARN] Could not get quote: {e}")
        # Set conservative slippage
        min_out = int(amount_in * 0.99)  # 1% slippage

    # Execute Swap
    deadline = w3.eth.get_block('latest')['timestamp'] + 600  # 10 minutes

    print(f"[SWAP] Executing swap...")
    swap_tx = router.functions.swapExactTokensForTokens(
        amount_in,
        min_out,
        path,
        address,
        deadline
    ).build_transaction({
        'from': address,
        'gas': 300000,
        'gasPrice': int(w3.eth.gas_price * 1.2),  # 20% boost
        'nonce': w3.eth.get_transaction_count(address)
    })

    signed_swap = account.sign_transaction(swap_tx)
    swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
    print(f"[SWAP] TX: {swap_hash.hex()}")
    print(f"[SWAP] Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=180)

    if receipt['status'] == 1:
        print(f"[SUCCESS] Swap complete!")

        # Check new balances
        new_usdc_e = usdc_e_contract.functions.balanceOf(address).call() / 1e6
        new_native = usdc_native_contract.functions.balanceOf(address).call() / 1e6

        print(f"[NEW BALANCE] USDC.e: {new_usdc_e:.6f}")
        print(f"[NEW BALANCE] Native USDC: {new_native:.6f}")
        print(f"[RECEIVED] {new_native - usdc_native_balance:.6f} Native USDC")
    else:
        print(f"[ERROR] Swap failed")
        print(f"[DEBUG] Receipt: {receipt}")

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        amount = float(sys.argv[1])
        print(f"[MODE] Swapping {amount} USDC.e")
        swap_usdc_e_to_native(amount)
    else:
        print(f"[MODE] Swapping ALL USDC.e")
        swap_usdc_e_to_native()
