# =========================================================================
# ORION CREDENTIALS  —  copy this to credentials.py and fill in values
# =========================================================================
# NEVER commit credentials.py to GitHub — it is in .gitignore

# ---- Zerodha Kite Connect (from kite.trade/connect) ----
KITE_API_KEY     = "your_api_key_here"
KITE_API_SECRET  = "your_api_secret_here"
KITE_ACCESS_TOKEN = ""          # auto-refreshed daily by auto_login.py

# ---- Zerodha login (for auto_login.py TOTP flow) ----
KITE_USER_ID     = "AB1234"     # your Zerodha client ID
KITE_PASSWORD    = "your_zerodha_password"
KITE_TOTP_SECRET = "BASE32SECRETFROM2FASETUP"  # from Zerodha 2FA → show QR key

# ---- Telegram bot ----
TELEGRAM_BOT_TOKEN = "123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TELEGRAM_CHAT_ID   = "your_chat_id"      # your personal chat ID with the bot
