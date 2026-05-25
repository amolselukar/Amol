"""
=========================================================================
ORION AUTO-LOGIN  —  Daily Zerodha Kite token refresh
=========================================================================
Primary: Selenium headless Chrome (proven working approach).
Fallback: requests login+2FA to get enctoken (for kite.zerodha.com root).
=========================================================================
"""
import sys, os, re, time
import pyotp
import requests
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


def get_token_via_selenium() -> str:
    """Headless Chrome OAuth flow — returns proper access_token."""
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager

    kite = KiteConnect(api_key=KITE_API_KEY)
    login_url = kite.login_url()

    options = Options()
    options.add_argument("--headless=old")        # old headless pipeline — most stable on PA
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.binary_location = "/usr/bin/chromium"

    service = Service(ChromeDriverManager(driver_version="131.0.6778.204").install())
    driver = webdriver.Chrome(service=service, options=options)
    print("[AUTO-LOGIN] Browser started.")

    try:
        driver.get(login_url)
        wait = WebDriverWait(driver, 20)
        actions = ActionChains(driver)

        print("[AUTO-LOGIN] Entering user ID...")
        uid = wait.until(EC.visibility_of_element_located((By.ID, "userid")))
        uid.clear()
        uid.send_keys(KITE_USER_ID)
        uid.send_keys(Keys.ENTER)

        print("[AUTO-LOGIN] Entering password...")
        pwd = wait.until(EC.visibility_of_element_located((By.ID, "password")))
        pwd.clear()
        pwd.send_keys(KITE_PASSWORD)
        try:
            btn = driver.find_element(By.XPATH, "//button[@type='submit']")
            driver.execute_script("arguments[0].click();", btn)
        except Exception:
            pwd.send_keys(Keys.ENTER)

        time.sleep(5)

        print("[AUTO-LOGIN] Entering TOTP...")
        totp_code = pyotp.TOTP(KITE_TOTP_SECRET).now()
        try:
            actions.send_keys(totp_code).perform()
            time.sleep(0.5)
            actions.send_keys(Keys.ENTER).perform()
        except Exception:
            pass
        try:
            for i in driver.find_elements(By.TAG_NAME, "input"):
                if i.get_attribute("type") in ["text", "tel"] and i.is_displayed():
                    if i.get_attribute("id") not in ["userid", "password"]:
                        i.clear(); i.send_keys(totp_code); i.send_keys(Keys.ENTER)
                        break
        except Exception:
            pass

        print("[AUTO-LOGIN] Waiting for redirect...")
        wait.until(EC.url_contains("request_token="))
        request_token = driver.current_url.split("request_token=")[1].split("&")[0]
        print(f"[AUTO-LOGIN] Got request_token={request_token[:8]}...")
    finally:
        driver.quit()

    sess_data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
    return sess_data["access_token"]


def get_token_via_requests() -> str:
    """Requests-based login — returns enctoken (works with kite.zerodha.com root)."""
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    resp = session.post("https://kite.zerodha.com/api/login",
                        data={"user_id": KITE_USER_ID, "password": KITE_PASSWORD}, timeout=15)
    data = resp.json()
    if data.get("status") != "success":
        raise Exception(f"Login failed: {data.get('message', data)}")
    request_id = data["data"]["request_id"]

    totp_code = pyotp.TOTP(KITE_TOTP_SECRET).now()
    resp = session.post("https://kite.zerodha.com/api/twofa",
                        data={"user_id": KITE_USER_ID, "request_id": request_id,
                              "twofa_value": totp_code, "twofa_type": "totp"}, timeout=15)
    data = resp.json()
    if data.get("status") != "success":
        raise Exception(f"2FA failed: {data.get('message', data)}")

    enctoken = session.cookies.get("enctoken")
    if not enctoken:
        raise Exception(f"enctoken not in cookies: {list(session.cookies.keys())}")
    return enctoken


def patch_credentials(token: str, is_enctoken: bool = False):
    with open(CREDS_PATH, 'r') as f:
        content = f.read()
    # Save access token
    patched = re.sub(r'(KITE_ACCESS_TOKEN\s*=\s*)["\'].*?["\']',
                     f'\\g<1>"{token}"', content)
    if patched == content:
        patched = content.rstrip() + f'\nKITE_ACCESS_TOKEN = "{token}"\n'
    # Save flag indicating token type
    if re.search(r'KITE_USE_ENCTOKEN\s*=', patched):
        patched = re.sub(r'(KITE_USE_ENCTOKEN\s*=\s*).*',
                         f'\\g<1>{str(is_enctoken)}', patched)
    else:
        patched = patched.rstrip() + f'\nKITE_USE_ENCTOKEN = {str(is_enctoken)}\n'
    with open(CREDS_PATH, 'w') as f:
        f.write(patched)


if __name__ == "__main__":
    print("[AUTO-LOGIN] Refreshing Kite access token...")
    token = None
    is_enctoken = False

    # Try Selenium first (gives proper OAuth access_token)
    try:
        token = get_token_via_selenium()
        is_enctoken = False
        print(f"[AUTO-LOGIN] Selenium OK — access_token: {token[:8]}...")
    except Exception as e:
        print(f"[AUTO-LOGIN] Selenium failed: {e}")
        print("[AUTO-LOGIN] Falling back to requests (enctoken)...")
        try:
            token = get_token_via_requests()
            is_enctoken = True
            print(f"[AUTO-LOGIN] Requests OK — enctoken: {token[:12]}...")
        except Exception as e2:
            print(f"[AUTO-LOGIN] FATAL: {e2}")
            sys.exit(1)

    patch_credentials(token, is_enctoken)
    print(f"[AUTO-LOGIN] SUCCESS — token saved (enctoken={is_enctoken})")
