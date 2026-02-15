#!/usr/bin/env python3
"""
Deposit Native USDC from EOA to Polymarket Proxy Wallet
This fixes the "not enough balance / allowance" error by moving funds
to where the Matching Engine expects them.
"""
import os
import sys
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
RPC_URLS = [
    "https://1rpc.io/matic",
    "https://polygon-rpc.com",
    "https://rpc-mainnet.maticvigil.com"
]
NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
]

def connect_web3():
    for rpc in RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.is_connected():
                print(f"[CONNECTED] {rpc}")
                return w3
        except Exception as e:
            print(f"[FAILED] {rpc}: {e}")
    raise Exception("All RPCs failed")

def fix_proxy_funding():
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not pk:
        print("[ERROR] POLYMARKET_PRIVATE_KEY not found")
        return

    w3 = connect_web3()
    account = Account.from_key(pk)
    eoa_address = account.address

    print(f"[OPERATOR] EOA: {eoa_address}")

    # 1. Derive the Proxy Address using py_clob_client
    from py_clob_client.client import ClobClient
    from py_clob_client.constants import POLYGON

    # Initialize client to get proxy address
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=pk,
        chain_id=POLYGON
    )

    # Get the proxy/collateral address
    try:
        proxy_address = client.get_address()  # This returns the proxy address
        print(f"[PROXY] Polymarket Proxy Address: {proxy_address}")
    except Exception as e:
        print(f"[ERROR] Could not get proxy address: {e}")
        # Try alternative method
        try:
            # Some versions use different method names
            proxy_address = client.get_collateral_address()
            print(f"[PROXY] Collateral Address: {proxy_address}")
        except:
            print("[ERROR] Cannot derive proxy address. Check py_clob_client version.")
            return

    if proxy_address.lower() == eoa_address.lower():
        print("[INFO] Proxy address equals EOA - this account uses EOA mode directly")
        print("[INFO] The issue may be elsewhere. Check if funds are approved for the exchange contracts.")
        return

    # 2. Check balances
    usdc = w3.eth.contract(address=Web3.to_checksum_address(NATIVE_USDC), abi=ERC20_ABI)

    eoa_balance_wei = usdc.functions.balanceOf(eoa_address).call()
    eoa_balance = eoa_balance_wei / 1e6

    proxy_balance_wei = usdc.functions.balanceOf(proxy_address).call()
    proxy_balance = proxy_balance_wei / 1e6

    print(f"[EOA BALANCE] ${eoa_balance:.6f} Native USDC")
    print(f"[PROXY BALANCE] ${proxy_balance:.6f} Native USDC")

    if eoa_balance < 0.5:
        print("[ERROR] Less than $0.50 in EOA. Not enough to transfer.")
        return

    # Keep $0.10 in EOA for potential future gas/fees
    transfer_amount_wei = eoa_balance_wei - 100000  # Keep 0.10 USDC
    transfer_amount = transfer_amount_wei / 1e6

    print(f"[TRANSFER] Moving ${transfer_amount:.6f} USDC to Proxy...")

    # 3. Execute transfer
    tx = usdc.functions.transfer(
        Web3.to_checksum_address(proxy_address),
        transfer_amount_wei
    ).build_transaction({
        'from': eoa_address,
        'nonce': w3.eth.get_transaction_count(eoa_address),
        'gas': 100000,
        'gasPrice': int(w3.eth.gas_price * 1.5)  # 50% boost for speed
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

    print(f"[TX] {tx_hash.hex()}")
    print("[WAITING] Confirming transaction...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt['status'] == 1:
        print("[SUCCESS] Deposit complete!")

        # Verify new balances
        new_eoa = usdc.functions.balanceOf(eoa_address).call() / 1e6
        new_proxy = usdc.functions.balanceOf(proxy_address).call() / 1e6

        print(f"[NEW EOA BALANCE] ${new_eoa:.6f}")
        print(f"[NEW PROXY BALANCE] ${new_proxy:.6f}")
        print("")
        print("=" * 50)
        print(f"PROXY ADDRESS FOR BOT CONFIG: {proxy_address}")
        print("=" * 50)
        print("")
        print("Next: Update market_maker.py with:")
        print(f"  signature_type=1  (or 2 for PolyProxy)")
        print(f"  funder=\"{proxy_address}\"")
    else:
        print("[ERROR] Transaction failed")
        print(f"Receipt: {receipt}")

if __name__ == "__main__":
    fix_proxy_funding()
