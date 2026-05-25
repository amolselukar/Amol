"""
=========================================================================
ORION AUTO-LOGIN  —  Daily Zerodha Kite token refresh
=========================================================================
Uses requests-based login + TOTP. Extracts enctoken from session cookies
after successful 2FA (no Selenium/Chrome needed, no OAuth connect flow).
Saves enctoken as KITE_ACCESS_TOKEN in credentials.py.
=========================================================================
"""
import sys, os, re, time
import pyotp
import requests

CREDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'credentials.py')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import credentials as _c
    KITE_USER_ID     = _c.KITE_USER_ID
    KITE_PASSWORD    = _c.KITE_PASSWORD
    KITE_TOTP_SECRET = _c.KITE_TOTP_SECRET
except AttributeError as e:
    print(f"[AUTO-LOGIN] credentials.py missing key: {e}")
    sys.exit(1)


def get_fresh_access_token(max_retries=3) -> str:
    for attempt in range(1, max_retries + 1):
        try:
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            })

            # Step 1: Login
            resp = session.post("https://kite.zerodha.com/api/login", data={
                "user_id":  KITE_USER_ID,
                "password": KITE_PASSWORD,
            }, timeout=15)
            data = resp.json()
            if data.get("status") != "success":
                raise Exception(f"Login failed: {data.get('message', data)}")
            request_id = data["data"]["request_id"]
            print(f"[AUTO-LOGIN] Login OK")

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
            print(f"[AUTO-LOGIN] 2FA OK")

            # Step 3: Extract enctoken from cookies
            enctoken = session.cookies.get("enctoken")
            if not enctoken:
                raise Exception(f"enctoken not in cookies. Got: {list(session.cookies.keys())}")
            print(f"[AUTO-LOGIN] enctoken extracted: {enctoken[:12]}...")

            # Step 4: Quick verify — profile call with enctoken
            vresp = requests.get(
                "https://api.kite.trade/user/profile",
                headers={
                    "Authorization": f"enctoken {enctoken}",
                    "X-Kite-Version": "3",
                }, timeout=10)
            if vresp.status_code == 200:
                name = vresp.json().get("data", {}).get("user_name", "")
                print(f"[AUTO-LOGIN] Token verified — user: {name}")
            else:
                print(f"[AUTO-LOGIN] Verify returned {vresp.status_code} — proceeding anyway")

            return enctoken

        except Exception as e:
            print(f"[AUTO-LOGIN] Attempt {attempt} failed: {e}")
            if attempt < max_retries:
                time.sleep(5 * attempt)
            else:
                raise


def patch_credentials(token: str):
    with open(CREDS_PATH, 'r') as f:
        content = f.read()
    patched = re.sub(
        r'(KITE_ACCESS_TOKEN\s*=\s*)["\'].*?["\']',
        f'\\g<1>"{token}"',
        content
    )
    if patched == content:
        patched = content.rstrip() + f'\nKITE_ACCESS_TOKEN = "{token}"\n'
    with open(CREDS_PATH, 'w') as f:
        f.write(patched)


if __name__ == "__main__":
    print("[AUTO-LOGIN] Refreshing Kite access token...")
    try:
        token = get_fresh_access_token()
        patch_credentials(token)
        print(f"[AUTO-LOGIN] SUCCESS — token saved: {token[:12]}...")
    except Exception as e:
        print(f"[AUTO-LOGIN] FATAL: {e}")
        sys.exit(1)
