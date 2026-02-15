
import json
import requests
import requests.sessions
from curl_cffi import requests as cffi_requests
from py_clob_client.exceptions import PolyApiException

# Global Configuration (To be injected or imported)
# For now, we allow passing proxy as arg or env
PROXY_URL = None # Defaults

# Minimal Headers for API access
BROWSER_HEADERS = {
    "User-Agent": "curl/7.68.0",
    "Accept": "application/json",
    "Origin": "https://polymarket.com",
    "Referer": "https://polymarket.com/",
}

def patch_requests_library():
    """Phase 1: Monkey-patch standard requests to avoid automated detection."""
    original_request = requests.sessions.Session.request
    
    def patched_request(self, method, url, *args, **kwargs):
        headers = kwargs.get("headers")
        if headers is None:
            headers = {}

        ua = headers.get("User-Agent", "")
        if "User-Agent" not in headers or "python-requests" in ua:
            headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        kwargs["headers"] = headers
        return original_request(self, method, url, *args, **kwargs)

    requests.sessions.Session.request = patched_request
    print("[CONNECTION] Standard `requests` library patched with Browser UA.")

def get_protected_session(proxy_url=None):
    """
    Creates a curl_cffi session with Chrome fingerprinting.
    Used for bypassing Cloudflare 403s on the CLOB.
    """
    proxies = {"https": proxy_url, "http": proxy_url} if proxy_url else None
    return cffi_requests.Session(impersonate="chrome110", proxies=proxies)

def protected_request(session, endpoint: str, method: str, headers=None, data=None):
    """
    Executes a request using the protected session with failover logic.
    Retries directly (no proxy) if 403 Cloudflare block is detected.
    """
    # Merge headers
    final_headers = BROWSER_HEADERS.copy()
    final_headers.update({
        "Content-Type": "application/json",
    })
    if headers:
        final_headers.update(headers)

    try:
        # 1. Prepare Payload
        json_payload = None
        if isinstance(data, str):
            try:
                json_payload = json.loads(data)
            except:
                pass
        else:
            json_payload = data

        # 2. Execute Request (Primary)
        if method == "GET":
            resp = session.get(endpoint, headers=final_headers, timeout=30)
        elif method == "POST":
             resp = session.post(endpoint, headers=final_headers, json=json_payload if json_payload else None, data=data if not json_payload else None, timeout=30)
        elif method == "DELETE":
            resp = session.delete(endpoint, headers=final_headers, json=data, timeout=30)
        elif method == "PUT":
            resp = session.put(endpoint, headers=final_headers, json=data, timeout=30)
        else:
            raise ValueError(f"Unsupported method: {method}")

        # 3. Failover Logic (Cloudflare Block)
        if resp.status_code == 403 and "cloudflare" in resp.text.lower():
            print(f"[RETRY] 🚀 Cloudflare Block via Proxy. Retrying DIRECTly from EC2 IP...")
            # Create fresh session execution without proxy
            direct_session = cffi_requests.Session(impersonate="chrome120")
            if method == "POST":
                 resp = direct_session.post(endpoint, headers=final_headers, json=json_payload if json_payload else None, data=data if not json_payload else None, timeout=30)
            elif method == "GET":
                 resp = direct_session.get(endpoint, headers=final_headers, timeout=30)
            # Add other methods if needed

        # 4. Error Handling
        if resp.status_code not in [200, 201]:
            print(f"[API-ERROR] {method} {endpoint} -> {resp.status_code}: {resp.text[:200]}")
            
            # Mock Exception for PyClobClient compatibility
            class MockResp:
                def __init__(self, status_code, text):
                    self.status_code = status_code
                    self.text = text
            raise PolyApiException(MockResp(resp.status_code, resp.text))

        # 5. Return Parsed
        if method == "POST":
            print(f"[CURL-DEBUG] Success POST to {endpoint}")

        try:
            return resp.json()
        except ValueError:
            return resp.text

    except cffi_requests.RequestsError as e:
        raise PolyApiException(error_msg=f"Request exception: {e}")
    except PolyApiException as pae:
        print(f"[API-FAIL] {method} {endpoint} | Status: {pae.status_code}")
        raise pae

