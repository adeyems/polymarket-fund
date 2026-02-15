
import os
import sys
import time
from web3 import Web3
from dotenv import load_dotenv

load_dotenv("/app/hft/.env")

# CONFIGURATION
# USDC.e (Bridged) on Polygon
TOKEN_ADDRESS = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
# Polymarket CTF Adapter (Potential Spender)
SPENDER_ADDRESS = Web3.to_checksum_address("0xdF9C8619E424a564F7c20c0A03901b0467773C33")

# RPCs
RPC_URLS = [
    "https://1rpc.io/matic",
    "https://rpc-mainnet.maticvigil.com",
    "https://polygon-rpc.com" 
]

# ABI for ERC20 Approve and Allowance
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    }
]

def connect_web3():
    for url in RPC_URLS:
        try:
            print(f"[CONNECT] Trying {url}...")
            w3 = Web3(Web3.HTTPProvider(url))
            if w3.is_connected():
                # Test call
                w3.eth.block_number
                print(f"[CONNECT] Success: {url}")
                return w3
        except Exception as e:
            print(f"[WARN] Failed {url}: {e}")
    return None

def main():
    w3 = connect_web3()
    if not w3:
        print("[ERROR] All RPCs failed - Upgrade Infrastructure")
        sys.exit(1)
        
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not private_key:
        print("[ERROR] POLYMARKET_PRIVATE_KEY not found in .env")
        sys.exit(1)
        
    account = w3.eth.account.from_key(private_key)
    my_address = account.address
    print(f"[APPROVE] Wallet: {my_address}")
    
    # Initialize Contract
    token_contract = w3.eth.contract(address=TOKEN_ADDRESS, abi=ERC20_ABI)
    
    # Check Balance
    try:
        balance = token_contract.functions.balanceOf(my_address).call()
        print(f"[INFO] USDC.e Balance: {balance / 1e6}")
    except Exception as e:
        print(f"[ERROR] Failed to fetch balance: {e}")
        sys.exit(1)
    
    # Check Allowance
    try:
        current_allowance = token_contract.functions.allowance(my_address, SPENDER_ADDRESS).call()
        print(f"[INFO] Current Allowance: {current_allowance}")
    except Exception as e:
        print(f"[ERROR] Failed to fetch allowance: {e}")
        sys.exit(1)
    
    if current_allowance > (2**255):
        print("[SUCCESS] Allowance already infinite. No action needed.")
        sys.exit(0)
        
    # Build Approve Transaction
    print("[ACTION] Approving Max Uint256...")
    max_amount = 2**256 - 1
    
    # Get nonce
    nonce = w3.eth.get_transaction_count(my_address)
    
    # Build txn
    print(f"[GAS] Base Price: {w3.eth.gas_price}")
    boosted_gas = int(w3.eth.gas_price * 2.0)
    print(f"[GAS] Boosted Price: {boosted_gas}")
    
    tx = token_contract.functions.approve(SPENDER_ADDRESS, max_amount).build_transaction({
        'chainId': 137, # Polygon Mainnet
        'gas': 150000,
        'gasPrice': boosted_gas,
        'nonce': nonce,
    })
    
    # Sign txn
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    
    # Send txn
    try:
        raw_tx = getattr(signed_tx, 'rawTransaction', None) or getattr(signed_tx, 'raw_transaction', None)
        if not raw_tx:
            raise ValueError("Could not find rawTransaction or raw_transaction on signed object")
            
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        print(f"[BROADCAST] Tx Hash: {w3.to_hex(tx_hash)}")
    except Exception as e:
        print(f"[ERROR] Failed to broadcast transaction: {e}")
        sys.exit(1)
        
    print("[WAIT] Waiting for confirmation (15s)...")
    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        
        if receipt.status == 1:
            print("[SUCCESS] Transaction Confirmed!")
            # Verify
            new_allowance = token_contract.functions.allowance(my_address, SPENDER_ADDRESS).call()
            print(f"[VERIFY] New Allowance: {new_allowance}")
        else:
            print("[ERROR] Transaction Failed/Reverted")
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Helper failed while waiting for receipt: {e}")
        # Even if wait fails, check allowance one last time
        time.sleep(5)
        new_allowance = token_contract.functions.allowance(my_address, SPENDER_ADDRESS).call()
        print(f"[VERIFY] New Allowance (Post-Timeout): {new_allowance}")

if __name__ == "__main__":
    main()
