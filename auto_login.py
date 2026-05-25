"""
=========================================================================
ORION AUTO-LOGIN  —  Daily Zerodha Kite token refresh
=========================================================================
Uses Selenium + headless Chromium (same approach that was working before).
Reads credentials from credentials.py, writes token back to credentials.py.
=========================================================================
"""
import sys, os, re, time
import pyotp
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


def get_fresh_access_token() -> str:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options

    kite = KiteConnect(api_key=KITE_API_KEY)
    login_url = kite.login_url()

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.binary_location = "/usr/bin/chromium"

    # Try ChromeDriverManager first, fall back to system chromedriver
    driver = None
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"[AUTO-LOGIN] ChromeDriverManager failed ({e}), trying system chromedriver...")
        try:
            driver = webdriver.Chrome(options=options)
        except Exception as e2:
            raise Exception(f"Could not start Chrome: {e2}")

    print("[AUTO-LOGIN] Browser started.")
    try:
        driver.get(login_url)
        wait = WebDriverWait(driver, 20)
        actions = ActionChains(driver)

        # Step 1: User ID
        print("[AUTO-LOGIN] Entering user ID...")
        uid = wait.until(EC.visibility_of_element_located((By.ID, "userid")))
        uid.clear()
        uid.send_keys(KITE_USER_ID)
        uid.send_keys(Keys.ENTER)

        # Step 2: Password
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

        # Step 3: TOTP
        print("[AUTO-LOGIN] Entering TOTP...")
        totp_code = pyotp.TOTP(KITE_TOTP_SECRET).now()
        try:
            actions.send_keys(totp_code).perform()
            time.sleep(0.5)
            actions.send_keys(Keys.ENTER).perform()
        except Exception:
            pass
        try:
            inputs = driver.find_elements(By.TAG_NAME, "input")
            for i in inputs:
                if i.get_attribute("type") in ["text", "password", "tel"] and i.is_displayed():
                    if i.get_attribute("id") not in ["userid", "password"]:
                        i.clear()
                        i.send_keys(totp_code)
                        i.send_keys(Keys.ENTER)
                        break
        except Exception:
            pass

        # Step 4: Wait for redirect with request_token
        print("[AUTO-LOGIN] Waiting for request_token redirect...")
        wait.until(EC.url_contains("request_token="))
        current_url = driver.current_url
        request_token = current_url.split("request_token=")[1].split("&")[0]
        print(f"[AUTO-LOGIN] Got request_token={request_token[:8]}...")

    finally:
        driver.quit()

    sess_data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
    return sess_data["access_token"]


def patch_credentials(access_token: str):
    with open(CREDS_PATH, 'r') as f:
        content = f.read()
    patched = re.sub(
        r'(KITE_ACCESS_TOKEN\s*=\s*)["\'].*?["\']',
        f'\\g<1>"{access_token}"',
        content
    )
    if patched == content:
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
