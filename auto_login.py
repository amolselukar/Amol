"""
ORION AUTO-LOGIN  —  Daily Zerodha enctoken refresh via requests (no browser needed).
"""
import re, sys, os, time
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


def auto_login():
    print("🚀 STARTING AUTO-LOGIN (no browser)...")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "X-Kite-Version": "3",
        "Content-Type": "application/x-www-form-urlencoded",
    })

    # Step 1: Password login
    print("1️⃣  Sending user ID + password...")
    try:
        resp = session.post(
            "https://kite.zerodha.com/api/login",
            data={"user_id": KITE_USER_ID, "password": KITE_PASSWORD},
            timeout=15,
        )
        result = resp.json()
        if result.get("status") != "success":
            print(f"❌ Login failed: {result}")
            sys.exit(1)
        request_id = result["data"]["request_id"]
        print(f"✅ Login OK. request_id: {request_id[:8]}...")
    except Exception as e:
        print(f"❌ Login error: {e}")
        sys.exit(1)

    # Step 2: TOTP
    print("2️⃣  Sending TOTP...")
    try:
        totp_code = pyotp.TOTP(KITE_TOTP_SECRET).now()
        resp = session.post(
            "https://kite.zerodha.com/api/twofa",
            data={
                "user_id": KITE_USER_ID,
                "request_id": request_id,
                "twofa_value": totp_code,
                "twofa_type": "totp",
                "skip_totp": "false",
            },
            timeout=15,
        )
        result = resp.json()
        if result.get("status") != "success":
            print(f"❌ 2FA failed: {result}")
            sys.exit(1)
        print("✅ 2FA OK.")
    except Exception as e:
        print(f"❌ 2FA error: {e}")
        sys.exit(1)

    # Step 3: Extract enctoken from cookies
    enctoken = session.cookies.get("enctoken")
    if not enctoken:
        print(f"❌ enctoken not found in cookies. Cookies: {dict(session.cookies)}")
        sys.exit(1)
    print(f"✅ Got enctoken: {enctoken[:8]}...")
    update_credentials_file(enctoken)


def update_credentials_file(enctoken):
    with open(CREDS_PATH, 'r') as f:
        content = f.read()

    if 'KITE_ENCTOKEN' in content:
        patched = re.sub(
            r'(KITE_ENCTOKEN\s*=\s*)["\'].*?["\']',
            f'\\g<1>"{enctoken}"',
            content
        )
    else:
        patched = content.rstrip() + f'\nKITE_ENCTOKEN = "{enctoken}"\n'

    # Remove stale OAuth fields
    patched = re.sub(r'\nKITE_ACCESS_TOKEN\s*=.*', '', patched)
    patched = re.sub(r'\nKITE_USE_ENCTOKEN\s*=.*', '', patched)

    with open(CREDS_PATH, 'w') as f:
        f.write(patched)
    print(f"\n{'='*50}")
    print(f"✅ CREDENTIALS UPDATED! enctoken: {enctoken[:8]}...")
    print(f"{'='*50}")


if __name__ == "__main__":
    auto_login()
