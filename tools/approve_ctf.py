import os
import time
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv

# Load Environment
load_dotenv("/app/hft/.env")

# Config
RPC_URL = os.getenv("POLYGON_RPC", "https://polygon-bor.publicnode.com")
PK = os.getenv("POLYMARKET_PRIVATE_KEY")
CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

if not PK:
    print("❌ ERROR: Private Key not found!")
    exit(1)

# Connect
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    print("❌ ERROR: Could not connect to RPC")
    exit(1)

account = Account.from_key(PK)
my_addr = account.address
print(f"🔧 Operator: {my_addr}")

# ABI for setApprovalForAll
CTF_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "operator", "type": "address"},
            {"name": "approved", "type": "bool"}
        ],
        "name": "setApprovalForAll",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "operator", "type": "address"}
        ],
        "name": "isApprovedForAll",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    }
]

def approve_ctf():
    ctf = w3.eth.contract(address=CTF_CONTRACT, abi=CTF_ABI)
    
    # Check if already approved
    is_approved = ctf.functions.isApprovedForAll(my_addr, CTF_EXCHANGE).call()
    if is_approved:
        print("✅ ALREADY APPROVED. No action needed.")
        return

    print(f"📝 Approving CTF Exchange ({CTF_EXCHANGE}) on CTF ({CTF_CONTRACT})...")
    
    # Build Transaction
    nonce = w3.eth.get_transaction_count(my_addr)
    gas_price = int(w3.eth.gas_price * 1.5)
    
    tx = ctf.functions.setApprovalForAll(CTF_EXCHANGE, True).build_transaction({
        'from': my_addr,
        'nonce': nonce,
        'gas': 100000,
        'gasPrice': gas_price
    })
    
    # Sign and Send
    signed = w3.eth.account.sign_transaction(tx, PK)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"🚀 Tx Sent: {tx_hash.hex()}")
    print("⏳ Waiting for confirmation...")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status == 1:
        print("✅ APPROVAL SUCCESSFUL!")
    else:
        print("❌ APPROVAL FAILED (Reverted)")

if __name__ == "__main__":
    approve_ctf()
