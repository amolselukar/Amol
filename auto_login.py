"""
ORION AUTO-LOGIN  —  Daily Zerodha access_token refresh via requests (no browser).
Steps: internal login → TOTP → OAuth connect/finish → generate_session → access_token
"""
import re, sys, os
import pyotp
import requests
from urllib.parse import urlparse, parse_qs
from kiteconnect import KiteConnect

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
    print(f"[AUTO-LOGIN] credentials.py missing key: {e}")
    sys.exit(1)


def auto_login():
    print("🚀 STARTING AUTO-LOGIN (no browser)...")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "X-Kite-Version": "3",
    })

    # Step 1: Password login via internal API
    print("1️⃣  User ID + password...")
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
    print("✅ Login OK.")

    # Step 2: TOTP
    print("2️⃣  TOTP...")
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
    # Set public_token and user_id cookies — required for OAuth connect flow
    twofa_data = result.get("data", {})
    public_token = twofa_data.get("public_token", "")
    if public_token:
        session.cookies.set("public_token", public_token, domain="kite.zerodha.com")
    session.cookies.set("user_id", KITE_USER_ID, domain="kite.zerodha.com")
    print(f"✅ 2FA OK. Session authenticated. public_token: {public_token[:8] if public_token else 'N/A'}...")

    # Step 3: Complete OAuth with the authenticated session
    print("3️⃣  Completing OAuth flow...")
    kite = KiteConnect(api_key=KITE_API_KEY)
    login_url = kite.login_url()

    # Warm up session with a visit to kite root (picks up CSRF/session cookies)
    session.get("https://kite.zerodha.com", timeout=15)
    session.headers.update({"Referer": "https://kite.zerodha.com/"})

    # Visit connect/login — authenticated session skips the login page
    resp = session.get(login_url, allow_redirects=True, timeout=15)
    print(f"   connect/login → {resp.status_code} final_url={resp.url[:100]}")
    if resp.status_code >= 400:
        print(f"   Error body: {resp.text[:300]}")

    # Check if request_token already in final URL (after all redirects)
    if "request_token=" in resp.url:
        request_token = parse_qs(urlparse(resp.url).query).get("request_token", [None])[0]
    else:
        request_token = _extract_token_from_history(resp)

    if not request_token and resp.status_code == 200:
        # Possibly on the allow/finish page — try submitting
        resp_nr = session.get(login_url, allow_redirects=False, timeout=15)
        request_token = _extract_token(resp_nr)
        loc = resp_nr.headers.get("Location", "")
        if not request_token and loc:
            if loc.startswith("/"):
                loc = "https://kite.zerodha.com" + loc

            resp2 = session.get(loc, allow_redirects=False, timeout=15)
            print(f"   connect/finish → {resp2.status_code} {resp2.headers.get('Location','')[:80]}")
            request_token = _extract_token(resp2)

            if not request_token and resp2.status_code == 200:
                print("   Submitting Allow form...")
                request_token = _submit_allow_form(session, resp2)

    if not request_token:
        print("❌ No redirect from connect/login")
        sys.exit(1)

        resp2 = session.get(loc, allow_redirects=False, timeout=15)
        print(f"   connect/finish → {resp2.status_code} {resp2.headers.get('Location','')[:80]}")
        request_token = _extract_token(resp2)

        if not request_token and resp2.status_code == 200:
            # Allow page HTML — submit the form automatically
            print("   Submitting Allow form...")
            request_token = _submit_allow_form(session, resp2)

    if not request_token:
        print("❌ Could not extract request_token from OAuth flow.")
        sys.exit(1)

    print(f"✅ Got request_token: {request_token[:8]}...")

    # Step 4: Generate access_token
    print("4️⃣  Generating access_token...")
    data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
    access_token = data["access_token"]
    print(f"✅ Got access_token: {access_token[:8]}...")
    update_credentials_file(access_token)


def _extract_token(resp):
    """Extract request_token from Location header."""
    loc = resp.headers.get("Location", "")
    if "request_token=" in loc:
        return parse_qs(urlparse(loc).query).get("request_token", [None])[0]
    return None


def _extract_token_from_history(resp):
    """Check all redirect history for request_token."""
    for r in resp.history:
        loc = r.headers.get("Location", "")
        if "request_token=" in loc:
            return parse_qs(urlparse(loc).query).get("request_token", [None])[0]
    return None


def _submit_allow_form(session, resp):
    """Parse the Allow page and POST the form to get request_token."""
    html = resp.text
    action_m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html, re.IGNORECASE)
    action = action_m.group(1) if action_m else "/connect/finish"
    if action.startswith("/"):
        action = "https://kite.zerodha.com" + action

    # Collect all hidden inputs
    hidden = {}
    for m in re.finditer(r'<input[^>]+>', html, re.IGNORECASE):
        tag = m.group(0)
        if 'hidden' in tag.lower():
            name_m  = re.search(r'name=["\']([^"\']+)["\']', tag)
            value_m = re.search(r'value=["\']([^"\']*)["\']', tag)
            if name_m:
                hidden[name_m.group(1)] = value_m.group(1) if value_m else ""

    submit = session.post(action, data=hidden, allow_redirects=False, timeout=15)
    print(f"   Allow POST → {submit.status_code} {submit.headers.get('Location','')[:80]}")
    return _extract_token(submit)


def update_credentials_file(access_token):
    with open(CREDS_PATH, 'r') as f:
        content = f.read()

    if 'KITE_ACCESS_TOKEN' in content:
        patched = re.sub(
            r'(KITE_ACCESS_TOKEN\s*=\s*)["\'].*?["\']',
            f'\\g<1>"{access_token}"',
            content
        )
    else:
        patched = content.rstrip() + f'\nKITE_ACCESS_TOKEN = "{access_token}"\n'

    patched = re.sub(r'\nKITE_USE_ENCTOKEN\s*=.*', '', patched)
    patched = re.sub(r'\nKITE_ENCTOKEN\s*=.*', '', patched)

    with open(CREDS_PATH, 'w') as f:
        f.write(patched)
    print(f"\n{'='*50}")
    print(f"✅ CREDENTIALS UPDATED! Token: {access_token[:8]}...")
    print(f"{'='*50}")


if __name__ == "__main__":
    auto_login()
