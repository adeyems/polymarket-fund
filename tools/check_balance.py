
import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

# Load env
from os.path import join, dirname
dotenv_path = join(dirname(__file__), '../.env')
load_dotenv(dotenv_path)

host = "https://clob.polymarket.com"
pk = os.getenv("POLYMARKET_PRIVATE_KEY") or os.getenv("PK") or os.getenv("PRIVATE_KEY")
key = os.getenv("CLOB_API_KEY") 
secret = os.getenv("CLOB_SECRET")
passphrase = os.getenv("CLOB_PASSPHRASE")
chain_id = 137

def check_balances():
    creds = ApiCreds(api_key=key, api_secret=secret, api_passphrase=passphrase)
    client = ClobClient(host, key=pk, chain_id=chain_id, creds=creds)
    
    print(f"--- Wallet: {client.get_address()} ---")
    try:
        # Check USDC Balance
        print("Fetching USDC balance...")
        # get_balance_allowance typically takes an asset_id or similar. 
        # For USDC on Polygon, it's often the default or needs the contract address.
        # Let's try calling it without args first to see if it defaults.
        try:
            balance = client.get_balance_allowance()
            print(f"USDC Balance/Allowance: {balance}")
        except Exception as e:
            print(f"USDC fetch failed: {e}")
            
    except Exception as e:
        print(f"Error fetching balances: {e}")

if __name__ == "__main__":
    check_balances()
