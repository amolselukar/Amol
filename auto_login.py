"""
=========================================================================
ORION AUTO-LOGIN  —  Daily Zerodha Kite token refresh
=========================================================================
Automates the full Zerodha login flow using TOTP (no manual steps).
Writes fresh KITE_ACCESS_TOKEN back into credentials.py.

Run order (called by start_orion.sh before the paper bot):
  1. POST /api/login     → user_id + password
  2. POST /api/twofa     → TOTP code
  3. GET  login_url      → capture request_token from redirect
  4. generate_session()  → exchange for access_token
  5. Patch credentials.py with new token

Prerequisites: pip install kiteconnect pyotp requests
=========================================================================
"""
import sys, os, re, time
import pyotp
import requests
from urllib.parse import urlparse, parse_qs
from kiteconnect import KiteConnect

# ---- Load credentials ----
CREDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'credentials.py')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import credentials as _c
    KITE_API_KEY     = _c.KITE_API_KEY
    KITE_API_SECRET  = _c.KITE_API_SECRET
    KITE_USER_ID     = _c.KITE_USER_ID
    KITE_PASSWORD    = _c.KITE_PASSWORD
    KITE_TOTP_SECRET = _c.KITE_TOTP_SECRET
except AttributeError as e:
    print(f"[AUTO-LOGIN] credentials.py missing required key: {e}")
    print("Required: KITE_API_KEY, KITE_API_SECRET, KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_SECRET")
    sys.exit(1)


def get_fresh_access_token(max_retries=3) -> str:
    kite = KiteConnect(api_key=KITE_API_KEY)
    session = requests.Session()

    for attempt in range(1, max_retries + 1):
        try:
            # Step 1: Login with user_id + password
            resp = session.post("https://kite.zerodha.com/api/login", data={
                "user_id":  KITE_USER_ID,
                "password": KITE_PASSWORD,
            }, timeout=15)
            data = resp.json()
            if data.get("status") != "success":
                raise Exception(f"Login failed: {data.get('message', data)}")
            request_id = data["data"]["request_id"]

            # Step 2: TOTP 2FA
            totp_code = pyotp.TOTP(KITE_TOTP_SECRET).now()
            resp = session.post("https://kite.zerodha.com/api/twofa", data={
                "user_id":     KITE_USER_ID,
                "request_id":  request_id,
                "twofa_value": totp_code,
                "twofa_type":  "totp",
            }, timeout=15)
            data = resp.json()
            if data.get("status") != "success":
                raise Exception(f"2FA failed: {data.get('message', data)}")

            # Step 3: Follow Kite login URL → connect/finish → redirect_url?request_token=
            login_url = kite.login_url()
            resp = session.get(login_url, allow_redirects=False, timeout=15)
            next_url = resp.headers.get("Location", "")

            # Zerodha may route through /connect/finish before issuing request_token
            if "connect/finish" in next_url or ("request_token" not in next_url and next_url):
                try:
                    resp2 = session.get(next_url, allow_redirects=True, timeout=15)
                    # Check final URL and full redirect history for request_token
                    candidates = [resp2.url] + [
                        r.headers.get("Location", "") for r in resp2.history
                    ]
                    request_token = None
                    for url in candidates:
                        p = parse_qs(urlparse(url).query)
                        rt = p.get("request_token", [None])[0]
                        if rt:
                            request_token = rt
                            break
                except requests.exceptions.ConnectionError as ce:
                    # Redirect URL is 127.0.0.1 — request_token is in the failed URL
                    m = re.search(r"request_token=([A-Za-z0-9]+)", str(ce))
                    if m:
                        request_token = m.group(1)
                    else:
                        raise Exception(f"ConnectionError following connect/finish: {ce}")
            else:
                params = parse_qs(urlparse(next_url).query)
                request_token = params.get("request_token", [None])[0]

            if not request_token:
                raise Exception(f"No request_token in redirect: {next_url}")

            # Step 4: Exchange for access token
            sess_data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
            return sess_data["access_token"]

        except Exception as e:
            print(f"[AUTO-LOGIN] Attempt {attempt} failed: {e}")
            if attempt < max_retries:
                time.sleep(5 * attempt)
            else:
                raise


def patch_credentials(access_token: str):
    with open(CREDS_PATH, 'r') as f:
        content = f.read()
    patched = re.sub(
        r'(KITE_ACCESS_TOKEN\s*=\s*)["\'].*?["\']',
        f'\\g<1>"{access_token}"',
        content
    )
    if patched == content:
        # Key not found — append it
        patched = content.rstrip() + f'\nKITE_ACCESS_TOKEN = "{access_token}"\n'
    with open(CREDS_PATH, 'w') as f:
        f.write(patched)


if __name__ == "__main__":
    print("[AUTO-LOGIN] Refreshing Kite access token...")
    try:
        token = get_fresh_access_token()
        patch_credentials(token)
        print(f"[AUTO-LOGIN] SUCCESS — token refreshed: {token[:8]}...")
    except Exception as e:
        print(f"[AUTO-LOGIN] FATAL: {e}")
        sys.exit(1)
