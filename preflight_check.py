import os
import sys
import time
from dotenv import load_dotenv
from web3 import Web3
from py_clob_client.constants import POLYGON

# Load Environment
load_dotenv()

def print_pass(msg):
    print(f"✅ [PASS] {msg}")

def print_fail(msg):
    print(f"❌ [FAIL] {msg}")
    return False

def print_warn(msg):
    print(f"⚠️ [WARN] {msg}")

def check_credentials():
    print("--- 1. Credential Check ---")
    required = ["POLYMARKET_API_KEY", "POLYMARKET_SECRET", "POLYMARKET_PASSPHRASE", "POLYMARKET_PRIVATE_KEY"]
    missing = []
    for key in required:
        val = os.getenv(key)
        if not val or val.startswith("your_"):
            missing.append(key)
    
    if missing:
        print_fail(f"Missing or Default Env Vars: {missing}")
        return False
    
    print_pass("All Credentials Loaded.")
    return True

def check_gas():
    print("\n--- 2. Gas Audit (POL/MATIC) ---")
    try:
        pk = os.getenv("POLYMARKET_PRIVATE_KEY")
        if not pk: return False
        
        # Connect to Polygon RPC
        rpc_url = "https://polygon-rpc.com"
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        if not w3.is_connected():
            print_fail("Could not connect to Polygon RPC.")
            return False
            
        account = w3.eth.account.from_key(pk)
        balance_wei = w3.eth.get_balance(account.address)
        balance_eth = w3.from_wei(balance_wei, 'ether')
        
        print(f"   Wallet: {account.address}")
        print(f"   Balance: {balance_eth:.4f} POL")
        
        if balance_eth < 2.0:
            print_warn(f"Low Balance! (< 2.0 POL). Transaction failure likely.")
        else:
            print_pass("Gas Balance Sufficient (> 2.0 POL).")
        return True
        
    except Exception as e:
        print_fail(f"Gas Check Error: {e}")
        return False

def check_approvals():
    print("\n--- 3. USDC Approval Check ---")
    try:
        pk = os.getenv("POLYMARKET_PRIVATE_KEY")
        rpc_url = "https://polygon-rpc.com"
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        account = w3.eth.account.from_key(pk)
        
        # Addresses
        USDC_ADDR = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174" # USDC (PoS)
        CTF_EXCHANGE = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045" # Polymarket CTF Exchange (Standard Mainnet Proxy)
        
        # Minimal ABI for Allowance
        abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
                "name": "allowance",
                "outputs": [{"name": "", "type": "uint256"}],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            },
            {
                "constant": False,
                "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "payable": False,
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]
        
        contract = w3.eth.contract(address=USDC_ADDR, abi=abi)
        allowance = contract.functions.allowance(account.address, CTF_EXCHANGE).call()
        allowance_fmt = w3.from_wei(allowance, 'mwei') # USDC has 6 decimals
        
        print(f"   Spender: CTF Exchange ({CTF_EXCHANGE})")
        print(f"   Allowance: ${allowance_fmt:,.2f}")
        
        if allowance_fmt < 100:
            print_warn("Low/No Allowance! You must approve USDC.")
            # Generate Approval Hex
            print(f"   Generating Approval Transaction...")
            # Max Uint256
            max_amt = 115792089237316195423570985008687907853269984665640564039457584007913129639935
            tx = contract.functions.approve(CTF_EXCHANGE, max_amt).build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': 100000,
                'gasPrice': w3.eth.gas_price
            })
            print(f"   Run this to approve: \n   >>> signed_tx = w3.eth.account.sign_transaction({tx}, private_key=...); w3.eth.send_raw_transaction(signed_tx.rawTransaction)")
            return False
        else:
            print_pass("USDC Approved for Trading.")
            return True

    except Exception as e:
        print_fail(f"Approval Check Error: {e}")
        return False

if __name__ == "__main__":
    print("=== PRODUCTION PRE-FLIGHT CHECK ===\n")
    check_credentials()
    check_gas()
    check_approvals()
    print("\n===================================")
