
import requests
import json

ADDRESS = "0xb22028EA4E841CA321eb917C706C931a94b564AB"
GAMMA_URL = "https://gamma-api.polymarket.com"

def check_endpoints():
    endpoints = [
        f"/portfolio/{ADDRESS}",
        f"/wallets/{ADDRESS}/portfolio",
        f"/positions?maker_address={ADDRESS}",
        f"/users/{ADDRESS}/portfolio",
        # Check markets to see if there's any user specific field
        "/markets?limit=1"
    ]
    
    for ep in endpoints:
        print(f"Checking {ep}...")
        try:
            resp = requests.get(GAMMA_URL + ep, timeout=5)
            if resp.status_code == 200:
                print(f"✅ SUCCESS: {ep}")
                print(json.dumps(resp.json(), indent=2)[:500])
            else:
                print(f"❌ FAIL: {ep} -> {resp.status_code}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    check_endpoints()
