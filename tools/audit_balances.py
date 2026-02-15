
import os
import json
from web3 import Web3
from dotenv import load_dotenv

# Load env
from os.path import join, dirname
dotenv_path = join(dirname(__file__), '../.env')
load_dotenv(dotenv_path)

# Polygon RPC
RPC_URL = "https://polygon-rpc.com"
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# Credentials
pk = os.getenv("POLYMARKET_PRIVATE_KEY") or os.getenv("PK") or os.getenv("PRIVATE_KEY")
if not pk.startswith("0x"): pk = "0x" + pk
address = w3.eth.account.from_key(pk).address

# USDC on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174" # USDC.e or USDC? 
# The bot uses usdc_contract. Checking contract address...
# Let's just use a generic ERC20 ABI for balance
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    }
]

def audit():
    print(f"--- Wallet Audit: {address} ---")
    
    # MATIC (POL) Balance
    matic_bal = w3.eth.get_balance(address)
    print(f"MATIC/POL: {w3.from_wei(matic_bal, 'ether'):.4f}")
    
    # USDC Balance
    try:
        usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=ERC20_ABI)
        usdc_bal = usdc_contract.functions.balanceOf(address).call()
        decimals = usdc_contract.functions.decimals().call()
        print(f"USDC.e: {usdc_bal / (10**decimals):.2f}")
    except Exception as e:
        print(f"USDC.e Check Failed: {e}")

    # Native USDC (if applicable)
    NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    try:
        usdc_contract = w3.eth.contract(address=NATIVE_USDC, abi=ERC20_ABI)
        usdc_bal = usdc_contract.functions.balanceOf(address).call()
        decimals = usdc_contract.functions.decimals().call()
        print(f"USDC (Native): {usdc_bal / (10**decimals):.2f}")
    except: pass

if __name__ == "__main__":
    audit()
