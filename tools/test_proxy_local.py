
import requests
import json

# Proxy URL from core/config.py
PROXY_URL = "REDACTED"
SYS_PROXIES = {"https": PROXY_URL, "http": PROXY_URL}

def test_proxy():
    print(f"Testing Proxy: {PROXY_URL}")
    try:
        # 1. Test IP Check
        print("Checking IP via Proxy...")
        resp = requests.get("https://api.ipify.org?format=json", proxies=SYS_PROXIES, timeout=15)
        if resp.status_code == 200:
            print(f"✅ Proxy IP: {resp.json().get('ip')}")
        else:
            print(f"❌ IP Check Failed: {resp.status_code} - {resp.text}")
            return

        # 2. Test HTTP Access (Generic)
        print("Checking General HTTP Access...")
        resp = requests.get("https://www.google.com", proxies=SYS_PROXIES, timeout=15)
        if resp.status_code == 200:
            print("✅ General Access: SUCCESS")
        else:
            print(f"❌ General Access Failed: {resp.status_code}")

    except Exception as e:
        print(f"❌ Error during proxy test: {e}")

if __name__ == "__main__":
    test_proxy()
