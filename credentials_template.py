# =========================================================================
# ORION CREDENTIALS  —  copy this to credentials.py and fill in values
# =========================================================================
# NEVER commit credentials.py to GitHub — it is in .gitignore

# ---- Zerodha Kite Connect (data feed + paper trading) ----
KITE_API_KEY     = "your_api_key_here"
KITE_API_SECRET  = "your_api_secret_here"
KITE_ACCESS_TOKEN = ""          # auto-refreshed daily by auto_login.py

# ---- Zerodha login (for auto_login.py TOTP flow) ----
KITE_USER_ID     = "AB1234"     # your Zerodha client ID
KITE_PASSWORD    = "your_zerodha_password"
KITE_TOTP_SECRET = "BASE32SECRETFROM2FASETUP"  # from Zerodha 2FA → show QR key

# ---- mStock / Mirae Asset (live order execution) ----
# Get API key from: mstock.com → Trading API → Generate Key
MSTOCK_API_KEY     = "your_mstock_api_key"
MSTOCK_USER_ID     = "your_mstock_client_id"   # e.g. M12345
MSTOCK_PASSWORD    = "your_mstock_password"
MSTOCK_TOTP_SECRET = "BASE32SECRETFROM2FASETUP"  # from mStock 2FA setup

# ---- Telegram bot ----
TELEGRAM_BOT_TOKEN = "123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TELEGRAM_CHAT_ID   = "your_chat_id"      # your personal chat ID with the bot

# ---- GitHub PAT (for EOD log push) ----
# Generate at: github.com → Settings → Developer settings → Personal access tokens
GITHUB_PAT = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
