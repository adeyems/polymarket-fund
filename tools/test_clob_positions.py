
import os
import sys
import requests
import json
from dotenv import load_dotenv

from py_clob_client.headers.headers import create_level_2_headers
from py_clob_client.signer import Signer
from py_clob_client.clob_types import ApiCreds, RequestArgs

# Load Env
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
env_path = os.path.join(parent_dir, ".env")
load_dotenv(env_path)

PK = os.getenv("POLYMARKET_PRIVATE_KEY") or os.getenv("PK") or os.getenv("PRIVATE_KEY")
KEY = os.getenv("CLOB_API_KEY")
SECRET = os.getenv("CLOB_SECRET")
PASSPHRASE = os.getenv("CLOB_PASSPHRASE")
CHAIN_ID = 137
HOST = "https://clob.polymarket.com"

if not PK:
    print("Error: PK missing in .env")
    sys.exit(1)

def test_endpoint(endpoint):
    print(f"\n--- Testing {endpoint} ---")
    try:
        signer = Signer(PK, CHAIN_ID)
        creds = ApiCreds(KEY, SECRET, PASSPHRASE)
        
        req_args = RequestArgs(
            method="GET",
            request_path=endpoint,
            body=""
        )

        headers = create_level_2_headers(
            signer=signer,
            creds=creds,
            request_args=req_args
        )
        
        url = HOST + endpoint
        resp = requests.get(url, headers=headers)
        
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
             print(f"Response: {resp.text[:500]}")
        else:
             print(f"Response Error: {resp.text[:200]}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_endpoint("/data/trades") 
    test_endpoint("/trades")
