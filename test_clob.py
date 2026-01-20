import os
import time
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON
from dotenv import load_dotenv

load_dotenv()

pk = os.getenv("POLYMARKET_PRIVATE_KEY")
api_key = os.getenv("CLOB_API_KEY")
api_secret = os.getenv("CLOB_SECRET")
api_passphrase = os.getenv("CLOB_PASSPHRASE")

creds_obj = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)

print(f"[{time.strftime('%X')}] Testing ClobClient init...")
try:
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=pk,
        chain_id=POLYGON,
        creds=creds_obj
    )
    print(f"[{time.strftime('%X')}] ✅ ClobClient Init Success.")
    
    print(f"[{time.strftime('%X')}] Testing get_address()...")
    addr = client.get_address()
    print(f"[{time.strftime('%X')}] ✅ Address: {addr}")
except Exception as e:
    print(f"[{time.strftime('%X')}] ❌ Error: {e}")
