import time
import os
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv("/app/hft/.env")
PK = os.getenv("POLYMARKET_PRIVATE_KEY")

RPC_URL = "https://polygon-bor.publicnode.com"
WMATIC_ADDR = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
USDC_E_ADDR = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
ROUTER_ADDR = "0xE592427A0AEce92De3Edee1F18E0157C05861564" # Uniswap V3

w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not PK:
    print("❌ ERROR: POLYMARKET_PRIVATE_KEY not found in .env")
    exit(1)

account = Account.from_key(PK)
my_addr = account.address

def execute_refuel():
    print(f"⛽ CHECKING RESERVES FOR: {my_addr}")
    
    # 1. Check POL Balance
    pol_wei = w3.eth.get_balance(my_addr)
    pol_bal = pol_wei / 1e18
    print(f"📊 Gas Reserve: {pol_bal:.2f} POL")
    
    # Adjusted to 40 POL swap (User Directive)
    swap_amount_pol = 40
    if pol_bal < (swap_amount_pol + 2):
        print(f"❌ ERROR: Balance ({pol_bal:.2f}) too low to swap {swap_amount_pol} POL safely.")
        return
    
    amount_in = w3.to_wei(swap_amount_pol, 'ether')

    # 2. Wrap POL -> WMATIC (Required for Uniswap)
    print(f"📦 Step 1/3: Wrapping {swap_amount_pol} POL...")
    wmatic = w3.eth.contract(address=WMATIC_ADDR, abi='[{"constant":false,"inputs":[],"name":"deposit","outputs":[],"payable":true,"type":"function"}]')
    
    current_nonce = w3.eth.get_transaction_count(my_addr)
    gas_price = int(w3.eth.gas_price * 1.5) # Speed up
    
    tx1 = wmatic.functions.deposit().build_transaction({
        'from': my_addr, 'nonce': current_nonce,
        'gas': 100000, 'gasPrice': gas_price, 'value': amount_in
    })
    s1 = w3.eth.account.sign_transaction(tx1, PK)
    tx_hash1 = w3.eth.send_raw_transaction(s1.raw_transaction)
    print(f"   Hash: {tx_hash1.hex()}")
    print("   Waiting for confirmation...")
    w3.eth.wait_for_transaction_receipt(tx_hash1, timeout=120)

    # 3. Approve Uniswap
    print("🔓 Step 2/3: Approving Router...")
    wmatic_token = w3.eth.contract(address=WMATIC_ADDR, abi='[{"constant":false,"inputs":[{"name":"guy","type":"address"},{"name":"wad","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"}]')
    
    tx2 = wmatic_token.functions.approve(ROUTER_ADDR, amount_in).build_transaction({
        'from': my_addr, 'nonce': current_nonce + 1,
        'gas': 100000, 'gasPrice': gas_price
    })
    s2 = w3.eth.account.sign_transaction(tx2, PK)
    tx_hash2 = w3.eth.send_raw_transaction(s2.raw_transaction)
    print(f"   Hash: {tx_hash2.hex()}")
    w3.eth.wait_for_transaction_receipt(tx_hash2, timeout=120)

    # 4. Swap WMATIC -> USDC.e
    print("🔄 Step 3/3: Swapping to USDC.e...")
    router_abi = [
        {
            "inputs": [
                {
                    "components": [
                        {"internalType": "address", "name": "tokenIn", "type": "address"},
                        {"internalType": "address", "name": "tokenOut", "type": "address"},
                        {"internalType": "uint24", "name": "fee", "type": "uint24"},
                        {"internalType": "address", "name": "recipient", "type": "address"},
                        {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                        {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                        {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                    ],
                    "internalType": "struct ISwapRouter.ExactInputSingleParams",
                    "name": "params",
                    "type": "tuple"
                }
            ],
            "name": "exactInputSingle",
            "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
            "stateMutability": "payable",
            "type": "function"
        }
    ]
    router = w3.eth.contract(address=ROUTER_ADDR, abi=router_abi)
    
    # Fee 500 = 0.05%
    params = (WMATIC_ADDR, USDC_E_ADDR, 500, my_addr, int(time.time())+600, amount_in, 0, 0)
    
    tx3 = router.functions.exactInputSingle(params).build_transaction({
        'from': my_addr, 'nonce': current_nonce + 2,
        'gas': 350000, 'gasPrice': gas_price
    })
    s3 = w3.eth.account.sign_transaction(tx3, PK)
    tx_hash3 = w3.eth.send_raw_transaction(s3.raw_transaction)
    
    print(f"✅ REFUEL COMPLETE. Tx: {tx_hash3.hex()}")
    print("👉 Checking final balance...")
    time.sleep(5)
    
    # Verify final balance
    usdc_abi = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]
    usdc = w3.eth.contract(address=USDC_E_ADDR, abi=usdc_abi)
    final_bal = usdc.functions.balanceOf(my_addr).call() / 1e6
    print(f"💰 New USDC.e Balance: ${final_bal:.2f}")

if __name__ == "__main__":
    execute_refuel()
