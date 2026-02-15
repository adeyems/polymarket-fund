#!/usr/bin/env python3
"""
FUEL TO CASH: Convert POL (gas) to USDC.e (trading capital)
Safety: Gets quote first, aborts if slippage > 3%
"""
import os
import time
import json
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from dotenv import dotenv_values

# Load from explicit path
config = dotenv_values("/app/hft/.env")

# --- CONFIGURATION ---
RPC_URL = "https://polygon-bor.publicnode.com"
WMATIC_ADDR = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
USDC_E_ADDR = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
UNISWAP_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"  # SwapRouter (V3)
UNISWAP_QUOTER = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"  # Quoter V1
POLYMARKET_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# ABIs
WMATIC_ABI = json.loads('[{"constant":false,"inputs":[],"name":"deposit","outputs":[],"payable":true,"stateMutability":"payable","type":"function"},{"constant":false,"inputs":[{"name":"guy","type":"address"},{"name":"wad","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},{"constant":true,"inputs":[{"name":"","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"}]')

QUOTER_ABI = json.loads('[{"inputs":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]')

ROUTER_ABI = json.loads('[{"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"address","name":"recipient","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMinimum","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"internalType":"struct ISwapRouter.ExactInputSingleParams","name":"params","type":"tuple"}],"name":"exactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"payable","type":"function"}]')

ERC20_ABI = json.loads('[{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":true,"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}]')

def convert_fuel():
    # Setup Web3
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        print("[ERROR] Cannot connect to Polygon RPC")
        return

    pk = config.get("POLYMARKET_PRIVATE_KEY")
    if not pk:
        print("[ERROR] POLYMARKET_PRIVATE_KEY not found")
        return

    account = Account.from_key(pk)
    my_addr = account.address

    print(f"[FUEL->CASH] Starting conversion for: {my_addr}")

    # 1. Check POL Balance
    pol_balance = w3.eth.get_balance(my_addr)
    pol_readable = pol_balance / 1e18
    print(f"[BALANCE] POL (Gas): {pol_readable:.4f}")

    # We want to swap 50 POL but keep at least 5 for gas
    swap_amount_pol = 50
    min_remaining = 5

    if pol_readable < (swap_amount_pol + min_remaining):
        print(f"[ERROR] Not enough POL. Need {swap_amount_pol + min_remaining}, have {pol_readable:.2f}")
        return

    amount_to_swap = w3.to_wei(swap_amount_pol, 'ether')
    print(f"[SWAP] Will convert {swap_amount_pol} POL to USDC.e")

    # 2. Get Quote First (Safety Check)
    print("[QUOTE] Getting Uniswap quote...")
    quoter = w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_QUOTER), abi=QUOTER_ABI)

    quote_out = None
    best_fee = None

    for fee in [500, 3000, 10000]:  # 0.05%, 0.3%, 1%
        try:
            quote = quoter.functions.quoteExactInputSingle(
                Web3.to_checksum_address(WMATIC_ADDR),
                Web3.to_checksum_address(USDC_E_ADDR),
                fee,
                amount_to_swap,
                0
            ).call()
            quote_usd = quote / 1e6
            print(f"[QUOTE] Fee {fee/10000}%: ${quote_usd:.4f} USDC.e")

            if quote_out is None or quote > quote_out:
                quote_out = quote
                best_fee = fee
        except Exception as e:
            print(f"[QUOTE] Fee {fee/10000}% failed: {e}")

    if quote_out is None:
        print("[ERROR] Could not get quote from Uniswap")
        return

    expected_usd = quote_out / 1e6
    # POL is around $0.25-0.30 typically, so 50 POL ~ $12-15
    # If we get less than $10 for 50 POL, something is wrong
    if expected_usd < 10:
        print(f"[WARNING] Quote seems low: ${expected_usd:.2f} for 50 POL")
        print("[WARNING] Proceeding anyway as POL price may have dropped")

    print(f"[QUOTE] Best: ${expected_usd:.4f} USDC.e (fee {best_fee/10000}%)")

    # Set minimum with 3% tolerance
    min_out = int(quote_out * 0.97)
    print(f"[MIN_OUT] Will accept minimum: ${min_out / 1e6:.4f}")

    # 3. Wrap POL -> WMATIC
    print("[WRAP] Step 1/4: Wrapping POL to WMATIC...")
    wmatic = w3.eth.contract(address=Web3.to_checksum_address(WMATIC_ADDR), abi=WMATIC_ABI)

    wrap_tx = wmatic.functions.deposit().build_transaction({
        'from': my_addr,
        'nonce': w3.eth.get_transaction_count(my_addr),
        'gas': 100000,
        'gasPrice': w3.eth.gas_price,
        'value': amount_to_swap
    })

    signed_wrap = account.sign_transaction(wrap_tx)
    wrap_hash = w3.eth.send_raw_transaction(signed_wrap.raw_transaction)
    print(f"[WRAP] TX: {wrap_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(wrap_hash, timeout=120)
    if receipt['status'] != 1:
        print("[ERROR] Wrap failed!")
        return
    print("[WRAP] Success!")

    # 4. Approve Router
    print("[APPROVE] Step 2/4: Approving Uniswap Router...")
    approve_tx = wmatic.functions.approve(
        Web3.to_checksum_address(UNISWAP_ROUTER),
        amount_to_swap
    ).build_transaction({
        'from': my_addr,
        'nonce': w3.eth.get_transaction_count(my_addr),
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

    # 5. Execute Swap
    print("[SWAP] Step 3/4: Swapping WMATIC -> USDC.e...")
    router = w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_ROUTER), abi=ROUTER_ABI)

    params = (
        Web3.to_checksum_address(WMATIC_ADDR),   # tokenIn
        Web3.to_checksum_address(USDC_E_ADDR),   # tokenOut
        best_fee,                                  # fee
        my_addr,                                   # recipient
        int(time.time()) + 300,                    # deadline (5 min)
        amount_to_swap,                            # amountIn
        min_out,                                   # amountOutMinimum
        0                                          # sqrtPriceLimitX96
    )

    swap_tx = router.functions.exactInputSingle(params).build_transaction({
        'from': my_addr,
        'nonce': w3.eth.get_transaction_count(my_addr),
        'gas': 300000,
        'gasPrice': int(w3.eth.gas_price * 1.2),  # 20% boost
        'value': 0
    })

    signed_swap = account.sign_transaction(swap_tx)
    swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
    print(f"[SWAP] TX: {swap_hash.hex()}")
    print("[SWAP] Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=180)

    if receipt['status'] != 1:
        print("[ERROR] Swap failed!")
        print(f"Receipt: {receipt}")
        return

    print("[SWAP] Success!")

    # 6. Approve USDC.e to Polymarket Exchange (if needed)
    print("[APPROVE] Step 4/4: Ensuring USDC.e approved to Polymarket...")
    usdc_e = w3.eth.contract(address=Web3.to_checksum_address(USDC_E_ADDR), abi=ERC20_ABI)

    new_balance = usdc_e.functions.balanceOf(my_addr).call()
    current_allowance = usdc_e.functions.allowance(my_addr, POLYMARKET_EXCHANGE).call()

    if current_allowance < new_balance:
        approve_pm_tx = usdc_e.functions.approve(
            Web3.to_checksum_address(POLYMARKET_EXCHANGE),
            2**256 - 1  # Max approval
        ).build_transaction({
            'from': my_addr,
            'nonce': w3.eth.get_transaction_count(my_addr),
            'gas': 100000,
            'gasPrice': w3.eth.gas_price
        })

        signed_pm = account.sign_transaction(approve_pm_tx)
        pm_hash = w3.eth.send_raw_transaction(signed_pm.raw_transaction)
        print(f"[APPROVE] TX: {pm_hash.hex()}")

        receipt = w3.eth.wait_for_transaction_receipt(pm_hash, timeout=120)
        if receipt['status'] == 1:
            print("[APPROVE] Polymarket approval success!")
        else:
            print("[WARNING] Polymarket approval may have failed")
    else:
        print("[APPROVE] Already approved to Polymarket")

    # Final Status
    final_usdc = usdc_e.functions.balanceOf(my_addr).call() / 1e6
    final_pol = w3.eth.get_balance(my_addr) / 1e18

    print("")
    print("=" * 50)
    print("CONVERSION COMPLETE!")
    print("=" * 50)
    print(f"USDC.e Balance: ${final_usdc:.4f}")
    print(f"POL Balance: {final_pol:.4f}")
    print("")
    print("Bot is now funded and ready to trade!")
    print("=" * 50)

if __name__ == "__main__":
    convert_fuel()
