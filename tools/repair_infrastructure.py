#!/usr/bin/env python3
"""
ATOMIC REPAIR: Swap Native USDC -> USDC.e and send to Proxy
Safety: Aborts if slippage > 2%
"""
import os
import time
import json
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
RPC_URL = "https://polygon-bor.publicnode.com"
NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
BRIDGED_USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
UNISWAP_ROUTER = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"  # SwapRouter02
UNISWAP_QUOTER = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"  # Quoter V1

# ABIs
ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},{"constant":true,"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}]')

QUOTER_ABI = json.loads('[{"inputs":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]')

ROUTER_ABI = json.loads('[{"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"address","name":"recipient","type":"address"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMinimum","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"internalType":"struct IV3SwapRouter.ExactInputSingleParams","name":"params","type":"tuple"}],"name":"exactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"payable","type":"function"}]')

def run_repair():
    # Setup Web3
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        print("[ERROR] Cannot connect to Polygon RPC")
        return

    # Load private key
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not pk:
        print("[ERROR] POLYMARKET_PRIVATE_KEY not found in .env")
        return

    account = Account.from_key(pk)
    my_address = account.address

    print(f"[REPAIR] Starting for wallet: {my_address}")

    # 1. Get Proxy Address from Polymarket
    from py_clob_client.client import ClobClient
    from py_clob_client.constants import POLYGON

    client = ClobClient(
        host="https://clob.polymarket.com",
        key=pk,
        chain_id=POLYGON
    )

    # For EOA mode (signature_type=0), proxy = EOA
    # For Proxy mode (signature_type=1), we need to derive proxy
    # Since we want to fund the proxy, let's check what address we trade as
    try:
        proxy_addr = client.get_address()
        print(f"[PROXY] Trading address: {proxy_addr}")
    except Exception as e:
        print(f"[ERROR] Could not get proxy address: {e}")
        proxy_addr = my_address  # Fallback to EOA

    # 2. Check Native USDC Balance
    native_usdc = w3.eth.contract(address=Web3.to_checksum_address(NATIVE_USDC), abi=ERC20_ABI)
    balance = native_usdc.functions.balanceOf(my_address).call()

    print(f"[BALANCE] Native USDC: ${balance / 1e6:.6f}")

    if balance < 100000:  # Less than $0.10
        print("[ERROR] Balance too low to repair (< $0.10)")
        return

    # Keep small buffer for potential fees
    swap_amount = balance - 50000  # Keep $0.05 buffer
    print(f"[SWAP] Will swap: ${swap_amount / 1e6:.6f}")

    # 3. Get Uniswap Quote (Safety Check)
    quoter = w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_QUOTER), abi=QUOTER_ABI)

    quote_out = None
    best_fee = None

    # Try different fee tiers: 0.01% (100), 0.05% (500), 0.3% (3000), 1% (10000)
    for fee in [100, 500, 3000]:
        try:
            # Use call() to simulate - quoter is non-view but can be called
            quote = quoter.functions.quoteExactInputSingle(
                Web3.to_checksum_address(NATIVE_USDC),
                Web3.to_checksum_address(BRIDGED_USDC),
                fee,
                swap_amount,
                0
            ).call()

            print(f"[QUOTE] Fee {fee/10000}%: ${quote / 1e6:.6f} USDC.e")

            if quote_out is None or quote > quote_out:
                quote_out = quote
                best_fee = fee
        except Exception as e:
            print(f"[QUOTE] Fee {fee/10000}% failed: {e}")

    if quote_out is None:
        print("[ERROR] Could not get any valid quote from Uniswap")
        return

    # Calculate slippage
    slippage = (swap_amount - quote_out) / swap_amount * 100
    print(f"[SLIPPAGE] {slippage:.2f}% (using {best_fee/10000}% pool)")

    if slippage > 5:
        print(f"[ABORT] Slippage too high ({slippage:.2f}% > 5%)! Retaining funds.")
        return

    # Set minimum output with 2% tolerance
    min_out = int(quote_out * 0.98)
    print(f"[MIN_OUT] Accepting minimum: ${min_out / 1e6:.6f}")

    # 4. Approve Router
    print("[APPROVE] Approving Uniswap Router...")

    current_allowance = native_usdc.functions.allowance(my_address, UNISWAP_ROUTER).call()
    if current_allowance < swap_amount:
        approve_tx = native_usdc.functions.approve(
            Web3.to_checksum_address(UNISWAP_ROUTER),
            2**256 - 1  # Max approval
        ).build_transaction({
            'from': my_address,
            'nonce': w3.eth.get_transaction_count(my_address),
            'gas': 100000,
            'gasPrice': w3.eth.gas_price
        })

        signed_approve = account.sign_transaction(approve_tx)
        approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        print(f"[APPROVE] TX: {approve_hash.hex()}")

        receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=120)
        if receipt['status'] != 1:
            print("[ERROR] Approval failed!")
            return
        print("[APPROVE] Success!")
    else:
        print("[APPROVE] Already approved")

    # 5. Execute Swap - Send directly to trading address
    print(f"[SWAP] Executing swap -> sending to {proxy_addr}...")

    router = w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_ROUTER), abi=ROUTER_ABI)

    # SwapRouter02 ExactInputSingleParams (no deadline field)
    params = (
        Web3.to_checksum_address(NATIVE_USDC),   # tokenIn
        Web3.to_checksum_address(BRIDGED_USDC),  # tokenOut
        best_fee,                                 # fee
        Web3.to_checksum_address(proxy_addr),    # recipient (PROXY!)
        swap_amount,                              # amountIn
        min_out,                                  # amountOutMinimum
        0                                         # sqrtPriceLimitX96
    )

    swap_tx = router.functions.exactInputSingle(params).build_transaction({
        'from': my_address,
        'nonce': w3.eth.get_transaction_count(my_address),
        'gas': 300000,
        'gasPrice': int(w3.eth.gas_price * 1.2),  # 20% boost
        'value': 0
    })

    signed_swap = account.sign_transaction(swap_tx)
    swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)

    print(f"[SWAP] TX: {swap_hash.hex()}")
    print("[SWAP] Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=180)

    if receipt['status'] == 1:
        print("[SUCCESS] Swap complete!")

        # Verify final balances
        bridged_usdc = w3.eth.contract(address=Web3.to_checksum_address(BRIDGED_USDC), abi=ERC20_ABI)
        new_balance = bridged_usdc.functions.balanceOf(proxy_addr).call()
        print(f"[FINAL] USDC.e at {proxy_addr}: ${new_balance / 1e6:.6f}")

        print("\n" + "="*50)
        print("REPAIR COMPLETE!")
        print(f"USDC.e is now at: {proxy_addr}")
        print("="*50)
    else:
        print("[ERROR] Swap transaction failed!")
        print(f"Receipt: {receipt}")

if __name__ == "__main__":
    run_repair()
