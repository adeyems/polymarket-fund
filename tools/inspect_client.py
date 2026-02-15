from py_clob_client.client import ClobClient
import os
from dotenv import load_dotenv

load_dotenv("/app/hft/.env")

host = "https://clob.polymarket.com"
key = os.getenv("POLYMARKET_PRIVATE_KEY")
chain_id = 137

client = ClobClient(host, key=key, chain_id=chain_id, signature_type=1)

print("Client attributes:", dir(client))

# diligent search for session or http client
if hasattr(client, "session"):
    print("Found client.session:", client.session.headers)
elif hasattr(client, "http_client"):
    print("Found client.http_client:", dir(client.http_client))
    if hasattr(client.http_client, "session"):
        print("Found client.http_client.session:", client.http_client.session.headers)
