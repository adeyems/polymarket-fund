import requests
import sys

BASE_URL = "http://127.0.0.1:8002"

def test_http():
    print(f"Testing HTTP Endpoints on {BASE_URL}...")
    errors = 0

    # 1. Health
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=2)
        if resp.status_code == 200:
            print(f"✅ /health OK: {resp.json()}")
        else:
            print(f"❌ /health FAILED: {resp.status_code}")
            errors += 1
    except Exception as e:
        print(f"❌ /health EXCEPTION: {e}")
        errors += 1

    # 2. Docs (Redirect check)
    try:
        resp = requests.get(f"{BASE_URL}/docs", timeout=2)
        if resp.status_code == 200:
            print("✅ /docs OK (Swagger UI Reachable)")
        else:
            print(f"❌ /docs FAILED: {resp.status_code}")
            errors += 1
    except Exception as e:
        print(f"❌ /docs EXCEPTION: {e}")
        errors += 1

    if errors == 0:
        print("\nAll HTTP checks passed.")
    else:
        print(f"\n{errors} checks FAILED.")
        sys.exit(1)

if __name__ == "__main__":
    test_http()
