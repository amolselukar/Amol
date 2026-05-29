#!/usr/bin/env python3
"""
test_mstock_order.py  —  mStock live order round-trip test.
Fires 1-lot ATM CE BUY at market, waits 5 seconds, then SELL at market.
Run at 9:16am IST when market is open.

Usage:
    python3 test_mstock_order.py
"""
import sys, os, time
from datetime import datetime, timedelta
import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IST = pytz.timezone('Asia/Kolkata')
LOT_SIZE = 65   # Nifty lot size (current)
TEST_LOTS = 1   # only 1 lot for test

# ── Load credentials ──────────────────────────────────────────────────
try:
    import credentials as _c
    KITE_API_KEY      = _c.KITE_API_KEY
    KITE_ACCESS_TOKEN = _c.KITE_ACCESS_TOKEN
except (ImportError, AttributeError) as e:
    print(f"[FATAL] credentials.py missing: {e}")
    sys.exit(1)

# ── Kite for spot price + instrument lookup ───────────────────────────
from kiteconnect import KiteConnect
kite = KiteConnect(api_key=KITE_API_KEY)
kite.set_access_token(KITE_ACCESS_TOKEN)

NIFTY_TOKEN = 256265

def get_spot():
    try:
        q = kite.quote([f"NSE:NIFTY 50"])
        return float(q["NSE:NIFTY 50"]["last_price"])
    except Exception as e:
        print(f"[ERROR] Could not fetch Nifty spot: {e}")
        sys.exit(1)

def round_atm(price):
    return int(round(price / 100) * 100)

def resolve_atm_ce_symbol():
    """Find nearest weekly expiry and ATM CE symbol from Kite instrument list."""
    today = datetime.now(IST).date()
    try:
        instruments = kite.instruments("NFO")
    except Exception as e:
        print(f"[ERROR] Cannot fetch NFO instruments: {e}")
        sys.exit(1)
    nifty_opts = [i for i in instruments
                  if i["name"] == "NIFTY"
                  and i["instrument_type"] == "CE"
                  and i["expiry"] >= today]
    if not nifty_opts:
        print("[ERROR] No NIFTY CE instruments found")
        sys.exit(1)
    expiries = sorted({i["expiry"] for i in nifty_opts})
    target_expiry = expiries[0]
    print(f"[INFO] Target expiry: {target_expiry}")

    spot = get_spot()
    atm  = round_atm(spot)
    print(f"[INFO] Nifty spot: {spot:.2f}  ATM: {atm}")

    match = next((i for i in nifty_opts
                  if i["expiry"] == target_expiry and int(i["strike"]) == atm), None)
    if match is None:
        print(f"[ERROR] ATM CE {atm} not found for expiry {target_expiry}")
        sys.exit(1)
    symbol = match["tradingsymbol"]
    token  = match["instrument_token"]
    print(f"[INFO] Symbol: {symbol}  token: {token}")
    return symbol, token, atm

# ── mStock broker ─────────────────────────────────────────────────────
try:
    from mstock_broker import MStockBroker
    from tradingapi_b.mconnect import MConnectB as _SDK
except ImportError as e:
    print(f"[FATAL] import failed: {e}")
    sys.exit(1)

import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S')

# Inspect SDK methods so we know what's actually available
print("\n=== MConnectB available methods ===")
sdk_methods = [m for m in dir(_SDK) if not m.startswith('__')]
for m in sdk_methods:
    print(f"  {m}")
print("===================================\n")

# Also inspect login() signature
import inspect
try:
    sig = inspect.signature(_SDK.login)
    print(f"login() signature: {sig}\n")
except Exception as e:
    print(f"Could not inspect login: {e}\n")

try:
    broker = MStockBroker()
    ok = broker.login()
    if not ok:
        print("[FATAL] mStock login failed")
        sys.exit(1)
    print("[OK] mStock logged in")
except RuntimeError as e:
    print(f"[FATAL] mStock init failed: {e}")
    sys.exit(1)

# ── Resolve symbol ────────────────────────────────────────────────────
symbol, token, atm = resolve_atm_ce_symbol()
qty = TEST_LOTS * LOT_SIZE

# ── Check LTP before placing ──────────────────────────────────────────
try:
    q = kite.quote([f"NFO:{symbol}"])
    ltp = q[f"NFO:{symbol}"]["last_price"]
    print(f"[INFO] {symbol} LTP: {ltp:.2f}  qty to trade: {qty}")
except Exception as e:
    print(f"[WARN] Could not fetch option LTP: {e} — proceeding anyway")

print("\n" + "="*50)
print(f"PLACING BUY MARKET ORDER: {symbol} qty={qty}")
print("="*50)

# ── BUY ───────────────────────────────────────────────────────────────
buy_oid = broker.place_order("BUY", symbol, qty, "MARKET")
if buy_oid is None:
    print("[FATAL] BUY place_order returned None — order NOT placed")
    sys.exit(1)
print(f"[OK] BUY placed. order_id={buy_oid}")

# Dump raw order book to see actual field names
import time as _t; _t.sleep(2)
try:
    _raw = broker._client.get_order_book()
    _parsed = _raw.json() if hasattr(_raw, 'json') else _raw
    _orders = _parsed if isinstance(_parsed, list) else (_parsed.get('data') or [])
    print(f"[DEBUG] Order book: {len(_orders)} orders")
    if _orders:
        print(f"[DEBUG] Order fields: {list(_orders[0].keys())}")
        for _o in _orders[:3]:
            print(f"[DEBUG] Order sample: {_o}")
except Exception as _e:
    print(f"[DEBUG] Order book fetch failed: {_e}")

print("[...] Waiting for BUY fill (up to 10s)...")
status, fill = broker.wait_for_fill(buy_oid, timeout_sec=10)
print(f"[BUY] status={status}  fill_price={fill:.2f}")

if status != "COMPLETE":
    print(f"[ERROR] BUY not filled (status={status}). Attempting SELL anyway for safety.")

# ── Wait 5 seconds ────────────────────────────────────────────────────
print("\n[...] Holding for 5 seconds...")
time.sleep(5)

# ── SELL ──────────────────────────────────────────────────────────────
print("\n" + "="*50)
print(f"PLACING SELL MARKET ORDER: {symbol} qty={qty}")
print("="*50)

sell_oid = broker.place_order("SELL", symbol, qty, "MARKET")
if sell_oid is None:
    print("[FATAL] SELL place_order returned None — MANUAL EXIT REQUIRED!")
    sys.exit(1)
print(f"[OK] SELL placed. order_id={sell_oid}")

print("[...] Waiting for SELL fill (up to 10s)...")
status_s, fill_s = broker.wait_for_fill(sell_oid, timeout_sec=10)
print(f"[SELL] status={status_s}  fill_price={fill_s:.2f}")

# ── Summary ───────────────────────────────────────────────────────────
print("\n" + "="*50)
print("TEST SUMMARY")
print("="*50)
print(f"  Symbol  : {symbol}")
print(f"  Qty     : {qty} ({TEST_LOTS} lot)")
print(f"  BUY     : order={buy_oid}  fill={fill:.2f}")
print(f"  SELL    : order={sell_oid}  fill={fill_s:.2f}")
if fill > 0 and fill_s > 0:
    pnl = (fill_s - fill) * qty
    print(f"  P&L     : ₹{pnl:+.2f}")
print(f"  Result  : {'PASS ✅' if status_s == 'COMPLETE' else 'CHECK MANUALLY ⚠️'}")
