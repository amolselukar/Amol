"""
ORION AUTO-LOGIN  —  Daily Zerodha Kite token refresh.
Uses Firefox (geckodriver) instead of Chrome to avoid segfault on PythonAnywhere.
Auto-downloads Firefox and geckodriver if not present.
"""
import time, sys, os, re
import pyotp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
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


def _find_geckodriver():
    import shutil
    gd = shutil.which("geckodriver")
    if gd:
        print(f"✅ System geckodriver: {gd}")
        return gd
    for path in ["/usr/local/bin/geckodriver", "/usr/bin/geckodriver",
                 os.path.expanduser("~/.local/bin/geckodriver")]:
        if os.path.isfile(path):
            print(f"✅ geckodriver: {path}")
            return path
    return None


def _download_geckodriver():
    import urllib.request, tarfile, stat
    url      = "https://github.com/mozilla/geckodriver/releases/download/v0.35.0/geckodriver-v0.35.0-linux64.tar.gz"
    dest_dir = os.path.expanduser("~/.local/bin")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "geckodriver")
    print("⬇️  Downloading geckodriver v0.35.0...")
    urllib.request.urlretrieve(url, "/tmp/geckodriver.tar.gz")
    with tarfile.open("/tmp/geckodriver.tar.gz") as tar:
        tar.extract("geckodriver", dest_dir)
    os.chmod(dest, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
    print(f"✅ geckodriver → {dest}")
    return dest


def _find_firefox():
    import shutil
    for fb in [shutil.which("firefox"), shutil.which("firefox-esr"),
               "/usr/bin/firefox", "/usr/bin/firefox-esr",
               os.path.expanduser("~/firefox/firefox")]:
        if fb and os.path.isfile(fb):
            print(f"✅ Firefox: {fb}")
            return fb
    return None


def _download_firefox():
    import urllib.request, tarfile, stat
    binary = os.path.expanduser("~/firefox/firefox")
    if os.path.isfile(binary):
        print(f"✅ Firefox already at {binary}")
        return binary
    url = "https://download.mozilla.org/?product=firefox-latest&os=linux64&lang=en-US"
    tgz = "/tmp/firefox_latest.tar"
    print("⬇️  Downloading Firefox (~80MB)...")
    urllib.request.urlretrieve(url, tgz)
    print("📦 Extracting Firefox...")
    with tarfile.open(tgz, "r:*") as tar:
        tar.extractall(os.path.expanduser("~"))
    os.chmod(binary, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
    print(f"✅ Firefox → {binary}")
    return binary


def auto_login():
    print("🚀 STARTING AUTO-LOGIN (Firefox)...")

    kite      = KiteConnect(api_key=KITE_API_KEY)
    login_url = kite.login_url()

    gd_path = _find_geckodriver() or _download_geckodriver()
    fb_path = _find_firefox()     or _download_firefox()

    options = FirefoxOptions()
    options.add_argument("--headless")
    options.binary_location = fb_path
    options.set_preference("browser.tabs.remote.autostart",   False)
    options.set_preference("browser.tabs.remote.autostart.2", False)

    try:
        service = FirefoxService(executable_path=gd_path)
        driver  = webdriver.Firefox(service=service, options=options)
        driver.get(login_url)
        print("✅ Browser started.")
    except Exception as e:
        print(f"❌ Browser failed: {e}")
        sys.exit(1)

    try:
        wait = WebDriverWait(driver, 20)

        def js_set(el_id, val):
            driver.execute_script("""
                var el = document.getElementById(arguments[0]);
                var setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(el, arguments[1]);
                el.dispatchEvent(new Event('input',  {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
            """, el_id, val)

        print("1️⃣  Entering User ID...")
        wait.until(EC.visibility_of_element_located((By.ID, "userid")))
        js_set("userid", KITE_USER_ID)
        time.sleep(0.5)
        driver.execute_script("document.querySelector('button[type=\"submit\"]').click();")

        print("2️⃣  Entering Password...")
        wait.until(EC.visibility_of_element_located((By.ID, "password")))
        js_set("password", KITE_PASSWORD)
        time.sleep(0.5)
        driver.execute_script("document.querySelector('button[type=\"submit\"]').click();")

        print("⏳ Waiting for 2FA page...")
        time.sleep(4)

        print("3️⃣  Entering TOTP...")
        token = pyotp.TOTP(KITE_TOTP_SECRET).now()
        totp_entered = False
        try:
            for inp in driver.find_elements(By.TAG_NAME, "input"):
                t = inp.get_attribute("type") or ""
                if t in ["text", "tel", "number", "password"] and inp.is_displayed():
                    if inp.get_attribute("id") not in ["userid", "password"]:
                        inp.clear()
                        inp.send_keys(token)
                        totp_entered = True
                        break
        except Exception:
            pass
        if not totp_entered:
            # Fallback: JS inject into first non-login input
            driver.execute_script(f"""
                var inputs = document.querySelectorAll('input');
                for(var i=0;i<inputs.length;i++){{
                    var id=inputs[i].id;
                    if(id!=='userid' && id!=='password' && inputs[i].offsetParent!==null){{
                        var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                        setter.call(inputs[i],'{token}');
                        inputs[i].dispatchEvent(new Event('input',{{bubbles:true}}));
                        inputs[i].dispatchEvent(new Event('change',{{bubbles:true}}));
                        break;
                    }}
                }}
            """)
        time.sleep(0.5)
        # Click Continue/Submit button
        driver.execute_script("document.querySelector('button[type=\"submit\"]').click();")

        print("⏳ Waiting for request_token...")
        wait.until(EC.url_contains("request_token="))
        current_url   = driver.current_url
        request_token = current_url.split("request_token=")[1].split("&")[0]
        print(f"✅ Got request_token: {request_token[:8]}...")
        driver.quit()

        data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        update_credentials_file(data["access_token"])

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        try:
            driver.save_screenshot("/tmp/debug_autologin.png")
            print("📸 Screenshot: /tmp/debug_autologin.png")
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
    patched = re.sub(r'\nKITE_USE_ENCTOKEN\s*=.*', '', patched)
    patched = re.sub(r'\nKITE_ENCTOKEN\s*=.*',     '', patched)
    with open(CREDS_PATH, 'w') as f:
        f.write(patched)
    print(f"\n{'='*50}")
    print(f"✅ CREDENTIALS UPDATED! Token: {new_token[:8]}...")
    print(f"{'='*50}")


if __name__ == "__main__":
    auto_login()
