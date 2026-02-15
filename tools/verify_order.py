
import os
import sys
import asyncio
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

# Load env
import os
from os.path import join, dirname
dotenv_path = join(dirname(__file__), '../.env')
load_dotenv(dotenv_path)

host = "https://clob.polymarket.com"
# PK is usually mapped to 'PK' or 'PRIVATE_KEY' in env, but ClobClient init checks 'key' arg as PK?
# Wait, ClobClient(key=...) expects the PRIVATE KEY.
# define keys
pk = os.getenv("PK") or os.getenv("PRIVATE_KEY")
key = os.getenv("CLOB_API_KEY") # API Key (L1/L2)
secret = os.getenv("CLOB_SECRET")
passphrase = os.getenv("CLOB_PASSPHRASE")
chain_id = 137

print(f"DEBUG: PK Len: {len(pk) if pk else 0}")
print(f"DEBUG: API Key Len: {len(key) if key else 0}")

# For ClobClient, 'key' argument is the PRIVATE KEY to sign with.
creds = ApiCreds(api_key=key, api_secret=secret, api_passphrase=passphrase)
client = ClobClient(host, key=pk, chain_id=chain_id, creds=creds)

TOKEN_ID = "9150172187999749270028515736853734790361197935118480975845332252523455886710"

def check_status():
    print(f"Checking Order Status for Token: {TOKEN_ID}")
    try:
        # Inspect Client Methods
        print(f"Client Methods: {[m for m in dir(client) if 'order' in m or 'trade' in m]}")
        
        # Check Open Orders (Try no args)
        try:
            open_orders = client.get_orders()
            print(f"All Open Orders: {len(open_orders)}")
            for o in open_orders:
                print(f"Open Order: {o}")
        except Exception as e:
            print(f"get_orders() failed: {e}")

        # Check Recent Trades (Try no args)
        try:
           # Some clients use get_trades_history or get_fills
           # Let's try basic get_trades if listed in dir
           pass
        except: pass
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_status()
