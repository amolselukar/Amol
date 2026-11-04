#!/usr/bin/env python3
"""
upstox_login.py — regenerate the Upstox OAuth2 access token.

Reconstructed 2026-11-04 to replace the login helpers lost in a disk cleanup
(upstox_auto_login.py / upstox_login_start.py / upstox_login_finish.py were
never tracked in git and had no backup).

Context (see upstox_kite_shim.py docstring): the bots authenticate to the
Upstox v2 read-only data API with a long-lived access token stored in
credentials.py as UPSTOX_ACCESS_TOKEN. The token is valid for the trading day
it is generated (Upstox invalidates at ~03:30 IST daily); the "extended" token
is a separate Upstox product. This helper runs the standard OAuth2 code flow
and writes the new token back into credentials.py.

Usage:
    python3 upstox_login.py            # interactive: open URL, paste redirect
    python3 upstox_login.py --print    # just print token, do NOT touch creds

The authorization step (mobile + PIN + TOTP) is done by you in the browser —
Upstox does not expose a supported pure-API path for that, so this helper
deliberately keeps a manual paste step rather than scraping Upstox's internal
login endpoints (which break without notice).
"""
import sys
import re
import urllib.parse as _up

import requests

import credentials as c

_AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
_CRED_PATH = c.__file__


def _authorize_url() -> str:
    q = {
        "response_type": "code",
        "client_id": c.UPSTOX_API_KEY,
        "redirect_uri": c.UPSTOX_REDIRECT_URI,
    }
    return f"{_AUTH_URL}?{_up.urlencode(q)}"


def _extract_code(pasted: str) -> str:
    """Accept either a bare code or the full redirect URL and pull out ?code=."""
    pasted = pasted.strip()
    if "code=" in pasted:
        qs = _up.urlparse(pasted).query or pasted.split("?", 1)[-1]
        code = _up.parse_qs(qs).get("code", [""])[0]
        if code:
            return code
    return pasted  # assume they pasted the bare code


def _exchange(code: str) -> dict:
    resp = requests.post(
        _TOKEN_URL,
        headers={
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "code": code,
            "client_id": c.UPSTOX_API_KEY,
            "client_secret": c.UPSTOX_API_SECRET,
            "redirect_uri": c.UPSTOX_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _write_token(token: str) -> None:
    """Replace the UPSTOX_ACCESS_TOKEN assignment in credentials.py in place."""
    with open(_CRED_PATH, "r") as f:
        src = f.read()
    new_line = f'UPSTOX_ACCESS_TOKEN = "{token}"'
    patt = re.compile(r'^UPSTOX_ACCESS_TOKEN\s*=.*$', re.MULTILINE)
    if patt.search(src):
        src = patt.sub(new_line, src, count=1)
    else:
        src = src.rstrip("\n") + "\n" + new_line + "\n"
    with open(_CRED_PATH, "w") as f:
        f.write(src)
    print(f"[OK] UPSTOX_ACCESS_TOKEN updated in {_CRED_PATH}")


def main() -> int:
    print("1) Open this URL in a browser and log in (mobile + PIN + TOTP):\n")
    print("   " + _authorize_url() + "\n")
    print("2) After login you are redirected to your redirect URI with ?code=...")
    pasted = input("   Paste the full redirect URL (or just the code): ")
    code = _extract_code(pasted)
    if not code:
        print("[ERR] no authorization code found", file=sys.stderr)
        return 1

    data = _exchange(code)
    token = data.get("access_token")
    if not token:
        print(f"[ERR] token exchange failed: {data}", file=sys.stderr)
        return 1

    print(f"\n[OK] access_token obtained (user: {data.get('user_id', '?')})")
    if "--print" in sys.argv:
        print(token)
    else:
        _write_token(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
