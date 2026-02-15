
import requests
import json

ADDRESS = "0xb22028EA4E841CA321eb917C706C931a94b564AB"
DATA_API_URL = "https://data-api.polymarket.com"

def check_endpoint():
    ep = f"/positions?user={ADDRESS}"
    print(f"Checking {DATA_API_URL + ep}...")
    try:
        resp = requests.get(DATA_API_URL + ep, timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(json.dumps(data, indent=2)[:1000])
        else:
            print(f"Response: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_endpoint()
