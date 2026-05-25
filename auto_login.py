"""
ORION AUTO-LOGIN  —  Daily Zerodha Kite token refresh
Selenium headless Chrome (original working approach).
"""
import time, sys, os, re
import pyotp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
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
    print("🚀 STARTING AUTO-LOGIN...")

    kite = KiteConnect(api_key=KITE_API_KEY)
    login_url = kite.login_url()

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--window-size=1920,1080")
    options.binary_location = "/usr/bin/chromium"

    try:
        # Prefer system chromedriver (compiled for this machine's Chromium)
        import shutil
        if shutil.which("chromedriver"):
            print(f"✅ Using system chromedriver: {shutil.which('chromedriver')}")
            service = Service(shutil.which("chromedriver"))
        else:
            service = Service(ChromeDriverManager(driver_version="131.0.6778.204").install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.get(login_url)
        print("✅ Browser Started.")
    except Exception as e:
        print(f"❌ Browser Failed: {e}")
        sys.exit(1)

    try:
        wait    = WebDriverWait(driver, 20)
        actions = ActionChains(driver)

        print("1️⃣  Entering User ID...")
        uid = wait.until(EC.visibility_of_element_located((By.ID, "userid")))
        uid.clear()
        uid.send_keys(KITE_USER_ID)
        uid.send_keys(Keys.ENTER)

        print("2️⃣  Entering Password...")
        pwd = wait.until(EC.visibility_of_element_located((By.ID, "password")))
        pwd.clear()
        pwd.send_keys(KITE_PASSWORD)
        try:
            btn = driver.find_element(By.XPATH, "//button[@type='submit']")
            driver.execute_script("arguments[0].click();", btn)
            print("    👉 Clicked Login Button via JS")
        except Exception:
            pwd.send_keys(Keys.ENTER)
            print("    👉 Pressed Enter")

        print("⏳ Waiting 5 seconds for 2FA Page...")
        time.sleep(5)

        print("3️⃣  Handling 2FA...")
        totp = pyotp.TOTP(KITE_TOTP_SECRET)
        token = totp.now()

        try:
            actions.send_keys(token).perform()
            time.sleep(0.5)
            actions.send_keys(Keys.ENTER).perform()
        except Exception:
            pass

        try:
            for i in driver.find_elements(By.TAG_NAME, "input"):
                if i.get_attribute("type") in ["text", "password", "tel"] and i.is_displayed():
                    if i.get_attribute("id") not in ["userid", "password"]:
                        i.clear()
                        i.send_keys(token)
                        i.send_keys(Keys.ENTER)
                        break
        except Exception:
            pass

        print("⏳ Waiting for Token...")
        wait.until(EC.url_contains("request_token="))
        current_url    = driver.current_url
        request_token  = current_url.split("request_token=")[1].split("&")[0]
        print(f"✅ Got request_token: {request_token[:8]}...")
        driver.quit()

        data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        update_credentials_file(data["access_token"])

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        try:
            driver.save_screenshot("debug_autologin.png")
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass
        sys.exit(1)


def update_credentials_file(new_token):
    with open(CREDS_PATH, 'r') as f:
        content = f.read()
    patched = re.sub(
        r'(KITE_ACCESS_TOKEN\s*=\s*)["\'].*?["\']',
        f'\\g<1>"{new_token}"',
        content
    )
    if patched == content:
        patched = content.rstrip() + f'\nKITE_ACCESS_TOKEN = "{new_token}"\n'
    # Clear enctoken flag — this is a proper OAuth token
    patched = re.sub(r'\nKITE_USE_ENCTOKEN\s*=.*', '', patched)
    with open(CREDS_PATH, 'w') as f:
        f.write(patched)
    print(f"\n{'='*50}")
    print(f"✅ CREDENTIALS UPDATED! Token: {new_token[:8]}...")
    print(f"{'='*50}")


if __name__ == "__main__":
    auto_login()
