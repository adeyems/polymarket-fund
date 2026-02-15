#!/usr/bin/env python3
"""
Token Migration Script: Native USDC → USDC.e (Bridged)
Executes a Uniswap V3 swap on Polygon to convert Native USDC to USDC.e for Polymarket.
"""
import os
import sys
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

# Load environment
load_dotenv()

# Constants
POLYGON_RPC = os.getenv("POLYGON_RPC", "https://polygon-bor-rpc.publicnode.com")
PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")

NATIVE_USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
USDC_E = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
UNISWAP_ROUTER = Web3.to_checksum_address("0xE592427A0AEce92De3Edee1F18E0157C05861564")  # Uniswap V3 SwapRouter

# ABIs
ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

SWAP_ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    }
]

def main():
    if not PRIVATE_KEY:
        print("[ERROR] POLYMARKET_PRIVATE_KEY not found in .env")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
    
    # Polygon is a POA chain - inject middleware
    from web3.middleware import ExtraDataToPOAMiddleware
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    
    if not w3.is_connected():
        print("[ERROR] Failed to connect to Polygon RPC")
        sys.exit(1)

    account = Account.from_key(PRIVATE_KEY)
    address = account.address
    print(f"[WALLET] {address}")

    # Check Native USDC Balance
    native_usdc = w3.eth.contract(address=NATIVE_USDC, abi=ERC20_ABI)
    balance = native_usdc.functions.balanceOf(address).call()
    decimals = native_usdc.functions.decimals().call()
    human_balance = balance / (10 ** decimals)

    print(f"[BALANCE] Native USDC: ${human_balance:.2f}")

    if balance == 0:
        print("[INFO] No Native USDC to swap. Exiting.")
        sys.exit(0)

    # Step 1: Approve Uniswap Router
    print(f"[STEP 1] Approving Uniswap Router to spend {human_balance:.2f} USDC...")
    
    allowance = native_usdc.functions.allowance(address, UNISWAP_ROUTER).call()
    if allowance < balance:
        approve_txn = native_usdc.functions.approve(UNISWAP_ROUTER, balance).build_transaction({
            "from": address,
            "nonce": w3.eth.get_transaction_count(address),
            "gas": 100000,
            "gasPrice": w3.eth.gas_price,
        })
        signed_approve = w3.eth.account.sign_transaction(approve_txn, PRIVATE_KEY)
        approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        print(f"[TX] Approval sent: {approve_hash.hex()}")
        w3.eth.wait_for_transaction_receipt(approve_hash)
        print("[OK] Approval confirmed.")
    else:
        print("[OK] Already approved.")

    # Step 2: Execute Swap
    print(f"[STEP 2] Swapping {human_balance:.2f} Native USDC → USDC.e via Uniswap V3...")

    router = w3.eth.contract(address=UNISWAP_ROUTER, abi=SWAP_ROUTER_ABI)
    
    # Allow 1% slippage
    min_out = int(balance * 0.99)
    deadline = w3.eth.get_block("latest")["timestamp"] + 300  # 5 min deadline

    swap_params = {
        "tokenIn": NATIVE_USDC,
        "tokenOut": USDC_E,
        "fee": 500,  # 0.05% fee tier
        "recipient": address,
        "deadline": deadline,
        "amountIn": balance,
        "amountOutMinimum": min_out,
        "sqrtPriceLimitX96": 0,
    }

    swap_txn = router.functions.exactInputSingle(swap_params).build_transaction({
        "from": address,
        "nonce": w3.eth.get_transaction_count(address),
        "gas": 300000,
        "gasPrice": w3.eth.gas_price,
        "value": 0,
    })

    signed_swap = w3.eth.account.sign_transaction(swap_txn, PRIVATE_KEY)
    swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
    print(f"[TX] Swap sent: {swap_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(swap_hash)
    if receipt["status"] == 1:
        print("[OK] Swap confirmed!")
    else:
        print("[ERROR] Swap failed!")
        sys.exit(1)

    # Step 3: Verify Final Balance
    usdc_e = w3.eth.contract(address=USDC_E, abi=ERC20_ABI)
    final_balance = usdc_e.functions.balanceOf(address).call()
    final_human = final_balance / (10 ** 6)

    print("=" * 50)
    print(f"[SUCCESS] Funds Activated: ${final_human:.2f} USDC.e ready for trading.")
    print("=" * 50)

if __name__ == "__main__":
    main()
