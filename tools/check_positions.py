
import os
import sys
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

# Load env safely
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
env_path = os.path.join(parent_dir, ".env")
load_dotenv(env_path)

host = "https://clob.polymarket.com"
key = os.getenv("CLOB_API_KEY") 
secret = os.getenv("CLOB_SECRET")
passphrase = os.getenv("CLOB_PASSPHRASE")
pk = os.getenv("POLYMARKET_PRIVATE_KEY") or os.getenv("PK") or os.getenv("PRIVATE_KEY")
chain_id = 137

if not key or not pk:
    print("Error: Missing Keys")
    sys.exit(1)

creds = ApiCreds(api_key=key, api_secret=secret, api_passphrase=passphrase)
client = ClobClient(host, key=pk, chain_id=chain_id, creds=creds)

print("Fetching Positions...")
try:
    # Get positions - Note: py_clob_client might use different method names
    # Common ones: get_positions, get_account_positions?
    # Inspecting client...
    positions = client.get_positions()
    print("--- POSITIONS ---")
    active_pos = [p for p in positions if float(p.get('size', 0)) > 0]
    for p in active_pos:
        print(f"Asset: {p.get('asset')} | Size: {p.get('size')}")
        
    if not active_pos:
        print("No active positions found.")
        
    print("\n--- BALANCE ---")
    # Balance might need web3, but let's check what ClobClient offers
    # client.get_balance() might not exist or return collateral
    try:
        collat = client.get_collateral_balance()
        print(f"Collateral: {collat}")
    except:
        print("Could not fetch collateral via CLOB.")

except Exception as e:
    print(f"Error: {e}")
