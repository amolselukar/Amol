"""
=========================================================================
ORION V2.5.20-SENSEX  —  SENSEX port of ORION_PAPER_V2_5_20.py (2026-08-23)
=========================================================================
Full engine set carried over unchanged in LOGIC (BASE/V2/V3/FLIP, VWAP,
FUT5VWAP, ORB, GAPBREAK, EXPIRY + shadow books APEX, T5, EXP12 expiry
engines 1&2 deployed 2026-08-22). Index-specific adaptations only:
  - Instrument: BSE SENSEX (token 265), options/futures on BFO
  - Lot size: 20 (NIFTY=65); Rs = pts x 20
  - Strike spacing 100 (NIFTY 50); round levels fine=100/major=500
  - Weekly expiry: resolved dynamically from BFO instruments at boot ->
    lands on SENSEX's Thursday (NIFTY's is Tuesday); no weekday hardcoding
  - All POINT-denominated thresholds (spot pts + option-premium pts)
    scaled x~3.3 (SENSEX/NIFTY price ratio, 81,500/24,700) and rounded;
    all %%-based params (HARDSL_PCT, bodies, ER, velvet multipliers,
    trails-as-%%) untouched. NONE of the scaled numbers are backtested on
    SENSEX data — this is a paper-mode first cut; forward paper is the test.
  - Separate state/CSV/log/lock/EOD dir; Telegram msgs prefixed "SENSEX |"
  - EXECUTION_BROKER stays "kite_paper". mStock exchange default flipped to
    BFO but UNVERIFIED (mStock BFO symbol format never live-tested) — do
    NOT flip this build to mstock_live without a symbol-format test.
  - next_day_plan_sensex.json does not exist yet -> OI-plan inject inert.
=========================================================================
"""
"""
=========================================================================
ORION V2.5.19 - PAPER TRADING BOT  (Nifty Weekly Options)
=========================================================================
Single-file live paper bot. Evolved from T10 V2.2.2 production baseline.
18-month backtest on phase3_daily.pkl (2024-09-23 -> 2026-03-24).

V2.5.14 BACKTEST RESULT (CURRENT LOCKED VERSION):
  Trades 363 | PnL Rs +6,88,158 | WR 64.5%
  Max DD -1,119 pts | Red months 5/18 (72% positive)
  Params: HARDSL -18%, Trail arms entry+15 SL=peak-5 floor=entry+10, CB=3

V2.5.9 BASELINE (prior to V2.5.12 exit upgrades):
  Trades 357 | PnL Rs +6,70,425 | WR 66.9%
  Max DD -1,485 pts | Red months 8/18

PAPER MODE: no real orders placed. Simulated P&L tracked via Kite LTP.
Bot exits cleanly at 15:30 IST. Logs + CSV pushed to GitHub at EOD.

=========================================================================
STRATEGY BOX  (V2.5.9 — all conditions on last CLOSED bars)
=========================================================================

ENGINE V2  (fires at every 15m close, V2 priority over V3 on same bar):
  CE ENTRY — ALL must be true:
    1. 1h close > SMA20 > SMA50         (full bullish SMA alignment)
    2. 15m K >= 38 AND K rising          (momentum confirming)
    3. K was < 25 in last 3 bars         (K extreme: fresh from oversold)
    4. 1h RSI > 53                       (RSI directional gate — bullish)
    5. 1h MACD_line > MACD_signal        (MACD bullish confirmation)
    6. Option premium 30 <= LTP <= 180   (premium gate: no deep OTM / IV spike)
  PE ENTRY — ALL must be true:
    1. 1h close < SMA20 < SMA50         (full bearish SMA alignment)
    2. 15m K <= 80 AND K falling AND K >= 25  (momentum + PE floor)
    3. K was > 75 in last 3 bars         (K extreme: fresh from overbought)
    4. 1h RSI < 47                       (RSI directional gate — bearish)
    5. 1h MACD_line < MACD_signal        (MACD bearish confirmation)
    6. Option premium 30 <= LTP <= 180   (premium gate)
  Strike: ATM (round to nearest 100). Lots: 2.

ENGINE V3  (cluster G/R break/reject, fires at 15m close):
  Levels computed at boot from prior day 1h:
    PDH, PDL + round 50/100 (±300 of PDC) + 20-bar swing pivots
    Clustered within 20pts -> Grade A (>=3 source kinds) / Grade B (>=2)
  V2.5.3: Promoted singletons: PDH/PDL/round_100(±200 of PDC)/swing pivots
           act as standalone Grade B if NOT already in an A/B cluster
  V2.5.6: PDC excluded from clustering; G/R need >=25pt buffer from PDC
  G = nearest A/B cluster ABOVE PDC+25   R = nearest A/B cluster BELOW PDC-25
  Regime gate: fire only in BULL/BEAR/TRANSITION; skip CHOP/INSUFFICIENT
  Signal: 15m bar breaks or rejects G/R with valid candle body/wick quality

ENGINE FLIP  (opposite-side only, max 3/day, flips excluded from CB):
  Path A (in-trade): elapsed>=30min + peak>=entry+15 + LTP<=entry+10 + K reversed
  Path B (post-exit): within 60min of exit, K reverses direction on 15m
  CE->PE: K falling AND 25 <= K <= 80
  PE->CE: K rising AND K >= 38

UNIVERSAL EXIT (priority order, applies to all engines):
  1. HARDSL      : -18% of entry premium (always armed from entry)
  2. Velvet Rope : peak hits entry+12 -> SL locked at entry+2 immediately
  3. Ladder Tier2: peak hits entry+24 -> SL to entry+12 (immediate, no time gate)
  4. Ladder Tier3: peak hits entry+36 -> SL to entry+24 (immediate)
  5. Runner Trail: SL ratchets +25pts per +25pts peak move (one-way only)
  5. SMA8(low)   : 15m option close < SMA(8, low) trail
  6. Force close : 15:25 IST
  7. Circuit Bkr : 3 non-flip losses/day -> halt all entries

STRADDLE MONITORING (informational only — NOT a trade gate):
  9:20 AM: record ATM straddle as reference
  9:45 AM: morning Telegram — expansion/compression % vs reference
  11:30AM: mid-day Telegram — current straddle vs reference

OPTIONS VWAP (informational only — NOT a trade gate):
  Computed from today's 5m bars with real volume for the active option
  Shown at entry, in each pulse, and at exit for context

=========================================================================
FULL CHANGE HISTORY (V2.2.2 -> V2.5.9) — see CHANGE_HISTORY variable
=========================================================================

=========================================================================
DATA PROVENANCE
=========================================================================
- Nifty 1h : kite.historical_data(256265, 30d back, "60minute")
             Adds: SMA20, SMA50, SMA20_slope, SMA50_slope, ADX, MACD, RSI
- Nifty 15m: kite.historical_data(256265, 10d back, "15minute")
             Adds: StochRSI K
- Nifty 5m : kite.historical_data(256265, 3d back, "5minute") — spot price
- Option 15m: kite.historical_data(opt_token, 10d back, "15minute") — SMA8(low) trail
- Option 5m : kite.historical_data(opt_token, 3d back, "5minute")  — VWAP
- Levels    : prior day 1h H/L/C + 20-bar swing pivots + round 50/100
- Closed-bar semantics: iloc[-2] for ALL signal evaluation (no lookahead)

UNDISCUSSED DECISIONS: NONE.
=========================================================================
"""
import os
import sys
import time
import json
import math
import csv
import subprocess
import threading
import traceback
import logging
import logging.handlers  # 2026-08-29: WatchedFileHandler (see LOGGING block)
import signal
import fcntl
import atexit
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass, field, asdict

# =========================================================================
# SINGLETON LOCK — prevent multiple bot instances running simultaneously
# =========================================================================
_SCRIPT_DIR_LOCK = os.path.dirname(os.path.abspath(__file__))
# V2.5.20: distinct lock filename from V2.5.19's ".orion_singleton.lock" --
# both versions run concurrently on this VM, and sharing one lock file
# would make one of them exit fatally (or, if start_orion.sh's `rm -f`
# deletes the file mid-run, silently defeat the singleton check for both).
_LOCK_FILE = os.path.join(_SCRIPT_DIR_LOCK, ".orion_singleton_sensex.lock")
_lock_fd = None

def _acquire_singleton_lock():
    global _lock_fd
    _lock_fd = open(_LOCK_FILE, 'w')
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        print(f"[FATAL] Another ORION instance is already running (lock: {_LOCK_FILE}). Exiting.")
        sys.exit(1)
    _lock_fd.write(str(os.getpid()))
    _lock_fd.flush()

def _release_singleton_lock():
    global _lock_fd
    if _lock_fd:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
        except Exception:
            pass
        try:
            os.remove(_LOCK_FILE)
        except Exception:
            pass

_acquire_singleton_lock()
atexit.register(_release_singleton_lock)

# ---------- Auto-install missing packages (mobile PythonAnywhere convenience) ----------
def _ensure(pkg, import_name=None):
    name = import_name or pkg
    try:
        __import__(name)
    except ImportError:
        print(f"[AUTO-INSTALL] Installing {pkg}...")
        os.system(f"{sys.executable} -m pip install --user {pkg} >/dev/null 2>&1")

_ensure("pandas")
_ensure("numpy")
_ensure("requests")
_ensure("kiteconnect")
_ensure("pytz")

import pandas as pd
import numpy as np
import requests
import pytz
from kiteconnect import KiteConnect

# ---------- Credentials ----------
try:
    import credentials
    KITE_API_KEY      = credentials.KITE_API_KEY
    KITE_API_SECRET   = credentials.KITE_API_SECRET
    KITE_ACCESS_TOKEN = credentials.KITE_ACCESS_TOKEN
    # 2026-08-26: SENSEX bot got its OWN Telegram bot/chat (OrionSensexv2520_bot)
    # per user — NIFTY and SENSEX signals were untrackable mixed in one chat.
    # NIFTY V2.5.20 keeps TELEGRAM_V2520_BOT_TOKEN unchanged.
    TELEGRAM_BOT_TOKEN = credentials.TELEGRAM_SENSEX_BOT_TOKEN
    UPSTOX_ACCESS_TOKEN = credentials.UPSTOX_ACCESS_TOKEN
except (ImportError, AttributeError) as e:
    print("[FATAL] credentials.py missing or incomplete.")
    print("Required keys: KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN, TELEGRAM_SENSEX_BOT_TOKEN, UPSTOX_ACCESS_TOKEN")
    sys.exit(1)

TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
if not TELEGRAM_CHAT_ID:
    try:
        from credentials import TELEGRAM_SENSEX_CHAT_ID as _tgcid
        TELEGRAM_CHAT_ID = _tgcid
    except ImportError:
        raise RuntimeError("TELEGRAM_CHAT_ID not set in environment or credentials.py")

try:
    from credentials import GITHUB_PAT as _ghpat
    GITHUB_PAT = _ghpat
except (ImportError, AttributeError):
    GITHUB_PAT = None

# ── mStock SDK import ────────────────────────────────────────────────
try:
    from tradingapi_b.mconnect import MConnectB as _SDK
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False

# ── MStockBroker (inlined — no separate mstock_broker.py needed) ─────
class MStockBroker:
    def __init__(self):
        if not _SDK_AVAILABLE:
            raise RuntimeError("mStock SDK not installed. Run: pip install mStock-TradingApi-B")
        _repo = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, _repo)
        try:
            import credentials as _c
            self._api_key  = getattr(_c, 'MSTOCK_API_KEY',  '')
            self._user_id  = getattr(_c, 'MSTOCK_USER_ID',  '')
            self._password = getattr(_c, 'MSTOCK_PASSWORD', '')
            self._totp_sec = getattr(_c, 'MSTOCK_TOTP_SECRET', '')
        except ImportError:
            raise RuntimeError("credentials.py not found")
        if not all([self._api_key, self._user_id, self._password]):
            raise RuntimeError("MSTOCK_API_KEY / MSTOCK_USER_ID / MSTOCK_PASSWORD missing in credentials.py")
        self._client = _SDK(api_key=self._api_key, debug=False, disable_ssl=True)
        self._logged_in = False
        self._sym_token_cache = {}
        self._last_error = ""
        # V2.5.20 (2026-07-20): registry of EVERY order-id this bot process has placed
        # (BUY or SELL, any engine). find_manual_sell() uses it to identify a user's
        # manual square-off by "this SELL is not one of OUR orders" -- replacing the old
        # producttype==INTRADAY heuristic, which wrongly discarded the user's own
        # INTRADAY/MIS manual exits (mis-booked two live exits on 2026-07-20).
        self._bot_order_ids = set()

    @staticmethod
    def _to_dict(resp) -> dict:
        if resp is None: return {}
        if isinstance(resp, dict): return resp
        if hasattr(resp, 'json'):
            try:
                d = resp.json()
                if isinstance(d, list): d = d[0] if d else {}
                return d if isinstance(d, dict) else {}
            except Exception: pass
        if hasattr(resp, '__dict__'): return vars(resp)
        return {}

    def login(self) -> bool:
        try:
            import pyotp
            totp_code = pyotp.TOTP(self._totp_sec).now() if self._totp_sec else ""
        except Exception:
            totp_code = ""
        try:
            raw  = self._client.login(user_id=self._user_id, password=self._password)
            resp = self._to_dict(raw)
            log.info(f"[mstock] login: status={resp.get('status')} msg={resp.get('message')}")
            data = resp.get('data') or {}
            jwt_token     = data.get('jwtToken', '')
            refresh_token = data.get('refreshToken', '')
            if not (resp.get('status') in (True, 'true', 'True') and jwt_token):
                log.error(f"[mstock] Login step-1 failed: {resp}")
                return False
            self._client.set_access_token(jwt_token)
            log.info("[mstock] Initial JWT set.")
            if totp_code and refresh_token:
                raw2 = self._client.verify_totp(_api_key=self._api_key, _request_token=refresh_token, _tOtp=totp_code)
                resp2 = self._to_dict(raw2)
                log.info(f"[mstock] verify_totp: status={resp2.get('status')} msg={resp2.get('message')} data={resp2.get('data')}")
                if resp2.get('status') not in (True, 'true', 'True'):
                    log.error(f"[mstock] verify_totp failed: {resp2}")
                    return False
                final_jwt = (resp2.get('data') or {}).get('jwtToken', '')
                if final_jwt:
                    self._client.set_access_token(final_jwt)
                    log.info("[mstock] Final JWT explicitly set after verify_totp.")
            else:
                log.warning(f"[mstock] Skipping verify_totp (totp={'yes' if totp_code else 'NO'}, refreshToken={'yes' if refresh_token else 'NO'})")
            self._logged_in = True
            log.info("[mstock] Login complete.")
            self._build_token_cache()
            return True
        except Exception as e:
            log.error(f"[mstock] Login failed: {e}")
            return False

    def _build_token_cache(self):
        try:
            import requests as _req
            url = "https://api.mstock.trade/openapi/typeb/instruments/OpenAPIScripMaster"
            r = _req.get(url, timeout=30)
            r.raise_for_status()
            rows = r.json()
            if not isinstance(rows, list): rows = rows.get('data') or []
            log.info(f"[mstock] Instrument master: {len(rows)} records, keys={list(rows[0].keys()) if rows else 'empty'}")
            for row in rows:
                sym = (row.get('name') or row.get('tradingsymbol') or row.get('Trading Symbol') or row.get('TradingSymbol') or row.get('TRADING_SYMBOL') or '')
                tok = str(row.get('token') or row.get('symboltoken') or row.get('symbolToken') or row.get('Token') or row.get('ScripCode') or row.get('SCRIP_CODE') or '')
                if sym and tok: self._sym_token_cache[sym] = tok
            log.info(f"[mstock] Instrument cache: {len(self._sym_token_cache)} symbols")
            nifty_sample = [(s, t) for s, t in self._sym_token_cache.items() if 'SENSEX' in s and 'CE' in s][:5]
            if nifty_sample: log.info(f"[mstock] Sample NIFTY CE: {nifty_sample}")
        except Exception as e:
            log.warning(f"[mstock] Instrument cache failed: {e}")

    def ensure_logged_in(self):
        if not self._logged_in:
            if not self.login(): raise RuntimeError("[mstock] Login required but failed.")

    def get_symbol_token(self, trading_symbol: str, exchange: str = "BFO") -> Optional[str]:
        return self._sym_token_cache.get(trading_symbol)

    def place_order(self, transaction_type: str, trading_symbol: str, quantity: int,
                    order_type: str = "MARKET", price: float = 0.0, exchange: str = "BFO",
                    product: str = "INTRADAY", symbol_token: str = "", tag: str = "ORION") -> Optional[str]:
        self.ensure_logged_in()
        if not symbol_token:
            symbol_token = self.get_symbol_token(trading_symbol, exchange) or ""
            if not symbol_token:
                log.warning(f"[mstock] Could not resolve token for {trading_symbol}.")
        try:
            resp = self._to_dict(self._client.place_order(
                _variety="NORMAL", _tradingsymbol=trading_symbol, _symboltoken=symbol_token,
                _exchange=exchange, _transactiontype=transaction_type, _ordertype=order_type,
                _quantity=str(quantity), _producttype=product,
                _price=str(price) if order_type == "LIMIT" else "0",
                _triggerprice="0", _squareoff="0", _stoploss="0", _trailingStopLoss="",
                _disclosedquantity="0", _duration="DAY", _ordertag=tag
            ))
            log.info(f"[mstock] place_order resp: {resp}")
            errorcode  = str(resp.get('errorcode', '') or '')
            status_str = str(resp.get('status', '')).lower()
            msg_str    = str(resp.get('message', '')).lower()
            if errorcode == 'IA403' or 'ip address' in msg_str:
                if getattr(self, '_ia403_relogin_attempted', False):
                    log.error(f"[mstock] IA403 persists after re-login — likely mStock server-side issue. {resp}")
                    self._last_error = f"IA403: {resp.get('message','')} (persists after re-login with fresh TOTP)"
                    self._ia403_relogin_attempted = False
                    return None
                log.warning(f"[mstock] IA403 received — rebuilding SDK client + fresh TOTP re-login. {resp}")
                self._ia403_relogin_attempted = True
                self._client = _SDK(api_key=self._api_key, debug=False, disable_ssl=True)
                self._logged_in = False
                time.sleep(2)
                if self.login():
                    log.info("[mstock] Fresh client + re-login OK after IA403 — retrying order.")
                    time.sleep(1)
                    result = self.place_order(transaction_type, trading_symbol, quantity,
                                              order_type, price, exchange, product, symbol_token, tag)
                    self._ia403_relogin_attempted = False
                    return result
                self._last_error = f"IA403 + re-login failed: {resp.get('message','')}"
                self._ia403_relogin_attempted = False
                return None
            jwt_expired = any(k in msg_str for k in ('unauthori', 'invalid token', 'session expired', 'not logged', 'token expired'))
            if jwt_expired:
                log.warning(f"[mstock] JWT expired in place_order — re-logging in.")
                self._logged_in = False
                if self.login():
                    log.info("[mstock] Re-login OK — retrying place_order once.")
                    return self.place_order(transaction_type, trading_symbol, quantity,
                                            order_type, price, exchange, product, symbol_token, tag)
                log.error("[mstock] Re-login also failed.")
                self._last_error = f"JWT expiry + re-login failed: {resp.get('message','')}"
                return None
            order_id = ((resp.get('data') or {}).get('orderid') or resp.get('orderid') or resp.get('order_id'))
            if order_id:
                log.info(f"[mstock] {transaction_type} placed: {trading_symbol} qty={quantity} type={order_type} → orderid={order_id}")
                self._last_error = ""
                self._bot_order_ids.add(str(order_id))  # V2.5.20 (2026-07-20): mark as OUR order
                return str(order_id)
            err_msg = resp.get('message') or resp.get('errMsg') or resp.get('error') or str(resp)
            log.error(f"[mstock] No orderid in response: {resp}")
            self._last_error = f"{err_msg}"
            return None
        except Exception as e:
            log.error(f"[mstock] place_order exception: {e}")
            self._last_error = str(e)
            return None

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        self.ensure_logged_in()
        try:
            resp = self._to_dict(self._client.cancel_order(_variety=variety, _orderid=order_id))
            log.info(f"[mstock] cancel_order {order_id}: {resp.get('message','')}")
            return resp.get('status') in ('true', True, 'True', 'success')
        except Exception as e:
            log.error(f"[mstock] cancel_order {order_id}: {e}")
            return False

    def order_status(self, order_id: str) -> Tuple[str, float]:
        self.ensure_logged_in()
        try:
            raw = self._client.get_order_book()
            if hasattr(raw, 'json'): parsed = raw.json()
            elif isinstance(raw, dict): parsed = raw
            else: parsed = {}
            if isinstance(parsed, list): orders = parsed
            else: orders = parsed.get('data') or []
            if not isinstance(orders, list): orders = []
            for o in orders:
                oid = str(o.get('orderid') or o.get('order_id') or o.get('orderId') or o.get('uniqueorderid') or '')
                if oid == str(order_id):
                    raw_status = str(o.get('status') or o.get('orderstatus') or 'UNKNOWN')
                    if raw_status.lower() in ('traded', 'complete', 'trade confirmed'): status = 'COMPLETE'
                    elif raw_status.lower() in ('rejected', 'cancelled', 'canceled'): status = raw_status.upper()
                    else: status = raw_status.upper()
                    fill = float(o.get('averageprice') or o.get('averagePrice') or o.get('fillprice') or 0)
                    return status, fill
        except Exception as e:
            log.error(f"[mstock] order_status {order_id}: {e}")
        return "UNKNOWN", 0.0

    def wait_for_fill(self, order_id: str, timeout_sec: int = 10, poll_sec: float = 0.5) -> Tuple[str, float]:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            status, fill = self.order_status(order_id)
            if status in ("COMPLETE", "REJECTED", "CANCELLED"): return status, fill
            time.sleep(poll_sec)
        log.warning(f"[mstock] wait_for_fill timeout — order {order_id} not confirmed.")
        return "TIMEOUT", 0.0

    def positions(self) -> list:
        self.ensure_logged_in()
        try:
            raw = self._client.get_net_position()
            resp = self._to_dict(raw) if raw is not None else {}
            return resp.get('data') or []
        except Exception as e:
            log.error(f"[mstock] positions(): {e}")
            return []

    def net_qty(self, trading_symbol: str) -> int:
        for p in self.positions():
            sym = p.get('tradingsymbol') or p.get('trading_symbol', '')
            if sym == trading_symbol: return int(p.get('netqty') or p.get('net_qty') or 0)
        return 0

    def verify_closed(self, trading_symbol: str, retries: int = 3, delay_sec: float = 1.0) -> bool:
        """V2.5.20 (2026-07-11 fix): symmetric counterpart to verify_position() for the
        SELL/close side -- confirm a just-placed SELL actually closed the position in the
        broker's real position book before trusting an order-book COMPLETE/fill status. A
        phantom SELL-COMPLETE (same order-book/RMS race as the BUY-side bug) is worse here:
        the bot would believe a position is closed and stop tracking risk on it while it's
        still actually open on the exchange."""
        for attempt in range(retries):
            if self.net_qty(trading_symbol) <= 0:
                return True
            if attempt < retries - 1:
                time.sleep(delay_sec)
        return False

    def verify_position(self, trading_symbol: str, expected_qty: int, retries: int = 3, delay_sec: float = 1.0) -> bool:
        """V2.5.20 (2026-07-11 fix): confirm a just-placed BUY actually shows up in the
        broker's real position book before trusting an order-book COMPLETE/fill status.
        Root-causes the 2026-07-09 NIFTY24000CE incident: order_status() reported
        status=COMPLETE, fill=167.45 for a BUY that was actually RMS-rejected
        (insufficient funds) -- the order book's own status field lagged behind the true
        rejection, and open_trade() had no independent check before recording it as a
        real fill. positions() is the broker's authoritative net-holding source (same one
        used to diagnose this incident manually); polling it a few times with a short
        delay absorbs normal settlement lag without waiting so long the caller stalls."""
        for attempt in range(retries):
            if self.net_qty(trading_symbol) >= expected_qty:
                return True
            if attempt < retries - 1:
                time.sleep(delay_sec)
        return False

    def find_manual_sell(self, trading_symbol: str, exclude_order_ids, min_qty: int = 0):
        """V2.5.20 (2026-07-08, strengthened 2026-07-10): find a COMPLETE SELL order on
        `trading_symbol` that the bot did NOT itself place -- i.e. the user manually
        squared off the position at the broker, at whatever price (market or their own
        fixed/limit price) they chose. Returns (order_id, avg_fill_price, filled_qty) for
        the first match, else None.

        A SELL counts as manual only if its order-id is NOT one of the bot's own, tested
        against BOTH:
        1. exclude_order_ids -- passed by the caller as the UNION of every engine's
           persisted buy_order_id + own_sell_order_ids (restart-proof; also guards the
           2026-07-06 cross-engine failure mode -- one engine's own SELL misread as
           another engine's manual exit).
        2. self._bot_order_ids -- the live in-process registry of every order-id THIS
           process placed via place_order() (BUY or SELL, any engine).
        V2.5.20 (2026-07-20): the old `producttype == 'INTRADAY'` skip was REMOVED. It
        assumed the user's manual exits are always MARGIN/CARRYFORWARD, but the user
        exits INTRADAY/MIS -- so that heuristic silently discarded real manual exits and
        mis-booked two live trades on 2026-07-20. Matching on the actual bot order-id set
        is exact and product-type-agnostic, and does NOT fall back to account-wide
        net_qty (the 2026-07-06 bug that check replaced).
        """
        self.ensure_logged_in()
        try:
            raw = self._client.get_order_book()
            if hasattr(raw, 'json'): parsed = raw.json()
            elif isinstance(raw, dict): parsed = raw
            else: parsed = {}
            orders = parsed if isinstance(parsed, list) else (parsed.get('data') or [])
            if not isinstance(orders, list): orders = []
            for o in orders:
                sym = o.get('tradingsymbol') or o.get('trading_symbol') or ''
                if sym != trading_symbol:
                    continue
                txn = str(o.get('transactiontype') or o.get('transaction_type') or '').upper()
                if txn != 'SELL':
                    continue
                oid = str(o.get('orderid') or o.get('order_id') or o.get('orderId') or o.get('uniqueorderid') or '')
                if not oid or oid in exclude_order_ids or oid in self._bot_order_ids:
                    continue  # one of the bot's own orders (any engine) — never a manual exit
                raw_status = str(o.get('status') or o.get('orderstatus') or '').lower()
                if raw_status not in ('traded', 'complete', 'trade confirmed'):
                    continue
                fill = float(o.get('averageprice') or o.get('averagePrice') or o.get('fillprice') or 0)
                qty = int(o.get('filledshares') or o.get('quantity') or o.get('filledQuantity') or 0)
                if fill <= 0:
                    continue
                if min_qty and qty < min_qty:
                    continue
                return oid, fill, qty
        except Exception as e:
            log.error(f"[mstock] find_manual_sell {trading_symbol}: {e}")
        return None

# ---- mStock broker instance ----
_mstock_broker = None
def _get_mstock():
    return _mstock_broker

def _init_mstock_at_boot():
    global _mstock_broker
    try:
        b = MStockBroker()
        ok = b.login()
        if ok:
            _mstock_broker = b
            linfo("[mstock] Broker initialised and logged in at boot.")
        else:
            lwarn("[mstock] Login returned False at boot — live orders DISABLED.")
            TG.send("🚨 mStock login FAILED at bot startup. Live orders disabled. Check credentials/TOTP.")
    except Exception as e:
        lwarn(f"[mstock] Init failed at boot: {e}. Live orders DISABLED.")
        TG.send(f"🚨 mStock init error at boot: {e}")

# =========================================================================
# STRATEGY BOX + CHANGE HISTORY  (logged to file + sent via Telegram at boot)
# =========================================================================
STRATEGY_BOX = """
+========================================================================+
| ORION V2.5.15 — STRATEGY DESIGN                                        |
| Backtest: 363 trades | PnL Rs +6,88,158 | WR 64.5% | MaxDD -1,119     |
+========================================================================+
| ENGINE V2 (fires every 15m close — regime: BULL/BEAR/TRANSITION only)  |
|   CE: 1h close>SMA20>SMA50 | K>=38 rising | K<25 recently             |
|        RSI>53 | MACD bull | premium 30-180                             |
|   PE: 1h close<SMA20<SMA50 | K<=80 falling K>=25 | K>75 recently      |
|        RSI<47 | MACD bear | premium 30-300                             |
|                                                                         |
| ENGINE V3 (15m G/R cluster break/reject — fires in any regime)         |
|   Grade A (>=3 source kinds) / Grade B (>=2)                           |
|   PDC excluded from clusters; G/R need >=25pt buffer from PDC          |
|   premium 30-180 CE / 30-300 PE                                        |
|                                                                         |
| ENGINE VWAP (triple confirmation — fires in any regime)                 |
|   1. Nifty FUTURES 15m close crosses FUT VWAP, body>=65% (PRIMARY)     |
|   2. Nifty SPOT 15m close same direction above/below spot VWAP         |
|   3. ATM CE/PE LTP also above/below its daily VWAP simultaneously      |
|   premium 30-180 CE / 30-300 PE                                        |
|                                                                         |
| ENGINE FLIP (opposite-side only, max 3/day, excluded from CB)          |
|   Path A (in-trade): elapsed>=30 + peak>=entry+15 + LTP<=entry+10      |
|   Path B (post-exit): K reversal within 60min                          |
|                                                                         |
| UNIVERSAL EXIT (priority order):                                        |
|   1. HARDSL -18%                                                        |
|   2. Continuous trail: arms when peak>=entry+15, SL=peak-5             |
|      floor=entry+10, ratchets up with peak (never down)                |
|   3. VWAP trades: exit when opt 15m close < opt VWAP                  |
|   4. V2/V3/FLIP trades: SMA8(low) trail on 15m                        |
|   5. Force close 15:25  6. CB=3 non-flip losses                        |
|                                                                         |
| INFORMATIONAL (no trade gate): Straddle alerts | Options VWAP          |
+========================================================================+
"""

CHANGE_HISTORY = """
V2.5.20 [2026-09-29] *** V2 -> LOG ONLY (signals logged after all gates, NOT traded) *** (V2_LOG_ONLY)
  User: "shutdown V2 in both indices and do it offline" (NIFTY and SENSEX, same change).
  WHY: 09-29 both bots' V2 bought PE at 13:46/13:51 after the 12:00-13:30 fall was
  already over (15m StochRSI K = RSI14 -> stoch14 -> SMA3 on closed 15m bars confirms
  ~30-45 min late; 1h RSI 30.9 read as "bearish"). NIFTY -400 (breakwatch cut),
  SENSEX -1,000 (50-pt stop). V2 is kept evaluating so it can be studied offline.
  CHANGE: open_trade() returns before staging the position when V2_LOG_ONLY and
  engine == 'V2'. The check sits AFTER every veto/gate and the strike + LTP pick, so
  "[V2] WOULD_ENTER(log-only) <side> <symbol> @ <ltp>" is exactly what V2 would have
  bought; also appended to V2_SHADOW_LOG (~/Amol/v2_shadow/<bot>_v2_shadow.jsonl).
  Gate refusals of V2 are still logged/exported as before (NIFTY block export to the
  SENSEX gate unchanged). V2 no longer holds positions, so FLIP-after-V2 cannot occur.
  PENDING IDEA (user, 09-29, NOT built): V2 allowed only when today's FAST trades form
  an N pattern on V2's side (win(s) -> pullback/SL/opposite -> new same-side FAST
  entry), or "V2 arms, next same-side FAST entry triggers". Decide after watching
  the modified FAST (T10 + 2m renko, same day).
  REVERT: V2_LOG_ONLY = False, or the *_BACKUP_20260929_pre_v2_logonly.py file.
  PROOF: boot "[CHANGELOG] up to date (last entry 2026-09-29)"; first V2 signal =
         "[V2] WOULD_ENTER(log-only)" line and no V2 ENTRY.
  STATUS: applied 2026-09-29 evening, market closed, live from the 09-30 boot.
          NOT boot-proven.
V2.5.20 [2026-09-28] *** PIVOT GATE BASIS FIX: FUT close shifted to spot terms before the pivot distance ***
  WHAT: new fut_pivot_dist(fut_close, df_fut, spot). check_fut5m_vwap_scalp_signal() and
  check_morning_vwap15_signal() now take `spot` and measure the pivot distance from
  (FUT close - live basis), basis = forming FUT bar close - live spot. No spot / no forming
  bar -> old FUT-close distance (fail-safe). Thresholds unchanged (FUT5 65, MORNING 65).
  WHY: user 2026-09-28 ("apply points 1,2"). DAY.pivots are built from SPOT 1h bars
  (compute_classic_pivots on the index token) but the gate compared the FUTURES close to
  them, so it measured basis (NIFTY 3-100 pts, mean ~41 on saved data) instead of pivot
  distance.
  EFFECT (idxopt cache 09-18..09-28, 5m cross + 15m morning candidate bars, body 65-86%):
  gate verdict changes on NIFTY 7 of 23 and SENSEX 2 of 16 candidate bars, all of them
  wrongly-blocked bars that now PASS (other gates still apply). P&L of those extra
  entries NOT simulated -- FUT5VWAP's earlier evidence was produced with the bug.
  REVERT: ORION_SENSEX_V2520_BACKUP_20260928_pre_pivot_basis_fix.py
  PROOF: "[FUT5VWAP]/[MVWAP] Skip ... from a pivot" lines now quote spot-equivalent closes.
  STATUS: applied 2026-09-28 night, NOT boot-proven until 09-29.
V2.5.20 [2026-09-28] *** BREAKWATCH PROFIT GUARD: never cut a trade that is green at the check *** (BREAKWATCH_PROFIT_GUARD)
  WHAT: in _breakwatch_check, a score <= CUT_MAX is NOT cut when POS.last_pulse_premium >
  entry premium; verdict logged as "KEEP(green, profit guard)". SENSEX is log-only, so this only changes
  the logged verdict.
  WHY: user 2026-09-28 ("apply points 1,2"). breakwatch/EXITCUT_REPORT.md, NIFTY cut trades
  on the live engine set: only 2 were green at +5 min -- 09-09 V2 (cut cost -514) and
  09-16 FLIP (cut gained +114) -> guard net about +400. n=2, small but only keeps winners.
  REVERT: BREAKWATCH_PROFIT_GUARD = False, or ORION_SENSEX_V2520_BACKUP_20260928_pre_bw_profit_guard.py
  STATUS: applied 2026-09-28 night, NOT boot-proven until 09-29.
V2.5.20 [2026-09-28] *** EXP12 (shadow): no entry at/after 15:15 + EXP2 band checked on live LTP ***
  WHAT: (1) _exp12_open refuses EXP1/EXP2/EXP2W entries when now >= EXP12_ENTRY_CUTOFF
  (15:15), logged as an EXP12 block. Exits and the 15:28 force close are unchanged.
  (2) EXP2/EXP2W: after ltp(), the 26-66 band is re-checked on the live price paid
  (EXP2_BAND_ON_LTP).
  WHY: user instruction 2026-09-28 ("apply both, as entries after 15:15 are not good").
  5 expiries 08-27..09-24: SENSEX spot is frozen 15:15-15:29 (2 distinct closes out of 15
  minutes, CAS), so the spot-distance gate is blind; EXP2 entries 15:22-15:27 = 11 trades,
  3 wins, Rs-1,034 vs before 15:15 = 2 trades Rs+6,677. The band was tested on the last
  history bar (lagging), then filled at live LTP: 296.50 / 142.00 / 86.80 got through.
  CAVEAT: the cutoff is not backtested on the 20-expiry set (user decision on the live
  sample); the 08-27 15:23 +3,378 winner would have been refused too.
  REVERT: EXP12_ENTRY_CUTOFF = (15, 30); EXP2_BAND_ON_LTP = False; or
          ORION_SENSEX_V2520_BACKUP_20260928_pre_exp12_cutoff_ltpband.py
  PROOF: next expiry 10-01: "[EXP12] ... NOT opened — after entry cutoff" or no entry
         stamped after 15:15 in sensex_exp12_shadow_trades.csv.
  STATUS: applied 2026-09-28 evening, NOT boot-proven until 09-29 09:06.
V2.5.20 [2026-09-28] *** BREAKWATCH 5-MIN CHECK — LOG ONLY ON SENSEX *** (BREAKWATCH_ENABLED, BREAKWATCH_ACT=False)
  User: "yes do it for nifty, log only for sensex".
  WHAT: once per trade, 5 min after the entry minute, ~/Amol/breakwatch_live.py
  scores 6 footprints (24-stock SENSEX basket with approx SENSEX weights: move /
  breadth / top-4 agreement, NIFTY move in trade direction, own progress in
  X=53.6 pts, OI % change at the first OTM strike on the trade's side). Engines
  VWAP ORB GAPBREAK V2 V3 FLIP (not FAST/FUT5VWAP/STOCH, same as NIFTY). This bot
  NEVER exits on it: it logs "[BREAKWATCH] ... -> KEEP | WOULD_CUT(log-only)" and
  appends ~/Amol/breakwatch/live_log.jsonl, to collect forward days.
  WHY LOG ONLY: offline (~/Amol/breakwatch/EXITCUT_REPORT.md, 97 SENSEX trades
  09-01..09-28) the cut at score <= 1 gives +21,521 -> +24,333 but 09-01..09-11
  -1,789 and ex-best-day -868, 9 days better / 9 worse = not robust (SENSEX dips
  first, then goes the original way). The NIFTY bot acts on the same scorer.
  REVERT: BREAKWATCH_ENABLED = False, or
          ORION_SENSEX_V2520_BACKUP_20260928_pre_breakwatch.py
  PROOF: run.log "[BREAKWATCH] ... score s/6 -> KEEP|WOULD_CUT(log-only)" 5 min
         after each entry; no exit reason BREAKWATCH_* can ever appear here.
  STATUS: applied 2026-09-28 evening, live (log only) from the 09-29 boot.
          NOT boot-proven.

V2.5.20 [2026-09-28] *** COUNTER-TREND VETO BASIS FIX: spot vs SPOT VWAP (port of NIFTY 09-14 fix) ***
  WHAT: countertrend_veto() now compares spot with today's SENSEX spot 1m VWAP
  (LAST_DF1M, published each loop right after fetch_nifty_1m) instead of the FUTURES
  5m session VWAP. Same buffer (16), same exempt engines (ORB/GAPBREAK/EXPIRY).
  WHY: user instruction 2026-09-28 ("apply the veto fix also"). Futures sit above spot,
  so CE was vetoed almost always -- FUT5VWAP took 8 of 9 trades as PE. Same bug NIFTY
  fixed 2026-09-14.
  CAVEAT: NOT backtested on SENSEX. 2026-09-15 V3 probe study found 8 CE fills the old
  veto blocked went 0/8 -> this may let losing CE trades through. Watch CE results.
  REVERT: ORION_SENSEX_V2520_BACKUP_20260928_pre_veto_basis_fix.py
  PROOF: first "[VETO] ... SPOT VWAP" line in orion_sensex_run.log.
  STATUS: applied 2026-09-28 evening, NOT boot-proven until 09-29 09:06.
V2.5.20 [2026-09-28] *** TIGHT STOP ON THE LOSING ENGINES: ORB 50 -> 30, FUT5VWAP 80 -> 40 ***
  WHAT: ORB_STOP_PTS 50 -> 30, FUT5_FIX_STOP_PTS 80 -> 40 (option-premium points).
  V3 (26), VWAP, GAPBREAK, EXPIRY, V2, FLIP untouched.
  WHY: user 2026-09-28: range days, big stops; tighten only the losing engines -- a
  genuine move is still picked up by the other engines. Test on the live book
  08-31..09-28 (~/Amol/slcheck/tight_sl_loser_engines.py, real 1m option bars; tighter
  stop fires if a bar low <= entry-S before the live exit, else live result kept):
      ORB      live prior +4,504 / last7 -1,696  ->  stop30 +4,648 / -96
      FUT5VWAP live prior   -560 / last7 -1,677  ->  stop40   +240 / -1,080
  Both better in BOTH periods. Stop 20 fails on ORB prior (+658); V3 at 20 no gain.
  Stopped trades: index ~20-35 pts against in 5 min, own-strike OI up 5-18% in 10 min
  (winners ~0-1%) -- recorded, not used.
  CAVEATS: 38 trades, in-sample; ORB flip timing after an earlier stop not re-simulated;
  paper fills at the stop price.
  REVERT: set the two constants back, or ORION_SENSEX_V2520_BACKUP_20260928_pre_tight_sl_orb_fut5.py
  STATUS: applied 2026-09-28 evening, NOT boot-proven until 09-29 09:06.
V2.5.20 [2026-09-19] *** NIFTY BLOCK GATE: ORB/V3/FUT5VWAP pause while the NIFTY bot is refusing entries ***
  WHAT: open_trade() choke point, after the counter-trend veto: if
  ~/Amol/nifty_blocks.jsonl (written by ORION_PAPER_V2_5_20 nifty_block_export
  for every entry NIFTY's VETO / RENKO / STOCHZONE / STOCH gates refuse) holds
  >= 2 refusals dated today within the last 60 min, ORB / V3 / FUT5VWAP do not
  enter ("[NIFTYGATE] <engine> <side> BLOCKED", TG throttled 15 min). VWAP,
  GAPBREAK, V2, FLIP, EXPIRY untouched. Missing file = gate open.
  WHY: 2026-09-19 day-type study (~/Amol/daytypes/, DAYTYPE_REPLAY_2026-09-19.md).
  SENSEX live book by day type: chop days (open-burst-chop + rotation-range)
  -7,095 on 7 days, 17 stops, all through ORB (-4,696), V3 (-2,156), FUT5VWAP
  (-2,160); trend days +17,456. NIFTY survives the same days because its gates
  refuse those entries one by one. Test on 09-03..09-17 (9 days, 48 SENSEX live
  trades, +3,739): this rule -> +10,859; 13 trades avoided (10 stops, 3 winners),
  10 of the 13 losing ORB/V3/FUT5VWAP trades before 10:30 caught, the 3 midday
  ones (11:00, 12:00, 13:02) pass. Chop-only variants (NEUTRAL-renko blocks
  only) WORSE than no gate; day-level block counts have no relation to the
  SENSEX result -> this is a minute-level gate, not a day switch.
  CAVEATS: in-sample; NIFTY block stream came from replays of the current NIFTY
  code (gates did not exist live on those days), timestamped to 5-min cycles;
  only 2 chop days in the window. 3 winners/9 days is the known cost.
  REVERT: NIFTY_BLOCK_GATE_ENABLED = False, or
          ORION_SENSEX_V2520_BACKUP_20260919_pre_nifty_block_gate.py
  PROOF: first "[NIFTYGATE] ... BLOCKED" in run.log; replay smoke 09-16 with the
         09-16 NIFTY replay blocks: V3 09:46 and FUT5VWAP 10:10 stops not taken.
  STATUS: applied 2026-09-19 (Saturday), NOT boot-proven until 09-21 09:02.

V2.5.20 [2026-09-16] *** TRADEREC: expiry restored from state is a str -> trade row silently lost ***
  WHY: 2026-09-15 the VWAP 23400PE trend-hold (72.20 -> FORCE_CLOSE_15_25 @254.60,
  +182.40/sh = Rs+11,856, the best trade of the month) never reached the trades CSV.
  run.log: "[TRADEREC] could not record trade: unsupported operand type(s) for -:
  'str' and 'datetime.date'". The position had been restored across the 13:56
  restart; state_*.json stores expiry_date as an ISO string and the restore does
  not parse it back, so record_trade()'s dte = exp - today raised and the whole
  row was dropped (record_trade swallows exceptions by design so the exit path
  never breaks). Same failure at 14:12 on the phantom SHUTDOWN_SQUAREOFF.
  CHANGE: record_trade() coerces a str expiry to date before the dte subtraction.
  CSV: the missing 09-15 row was appended by hand from run.log/FlightRecorder
  (entry 10:01:15, exit 15:25:14, mfe 303.20, mae 67.45, spots 23383.1/23172.3);
  backup Nifty_Trades_V2_5_20_BACKUP_20260916_pre_23400PE_fix.csv.
  CHANGE 2 (same day, user: "fix the state restore also"): load_state() now parses
  expiry_date back to a date when restoring a position, so POS.expiry_date is a
  date everywhere again; the record_trade() coercion stays as a belt-and-braces.
  REVERT: remove the isinstance(exp, str) block and the expiry_date elif in
  load_state(). Applies to NIFTY and SENSEX.
  PROOF: next restored-position exit writes its row; no [TRADEREC] warning.

V2.5.20 [2026-09-16] *** EXP1/EXP2 BUYING WINDOW OPENS 14:45, NOT 14:30 (SENSEX ONLY) ***
  WHY: user instruction "change the existing window to 14:45 directly, for
  sensex". Study ~/Amol/expiry_bt/entry_features_sensex.py on 20 SENSEX
  expiries 2026-04-30..09-10, real 1-min premiums, buy-on-signal hold-15:28:
    signals fired 14:30-14:44 : 44 of 100 unique, 9 winners (20%), Rs-15,264
    signals fired 14:45+      : 56,  25 winners (45%),               Rs+25,958
  Mechanism: EXP2 has no trigger beyond premium band + OI15 + distance, so at
  window-open every leg already in band fires at once (inventory, not signal);
  nothing measurable at 14:30 separates the 9 early winners from the 35 losers
  (only the FUTURE spot move does). Full shadow book: Rs+10,882 -> +32,101,
  17 expiries better/unchanged, 3 worse (09-03 -5,844, 07-30 -2,459, 06-25 -911:
  the move started before 14:45; late window still caught part of it on 2 of 3).
  Both halves of the sample improve (first 10: -14,852 -> positive).
  CAVEAT: in-sample on the same 20 expiries as every SENSEX result; no OOS.
  NIFTY NOT CHANGED: same test on 48 NIFTY expiries is WORSE (-3,411 -> -11,326;
  NIFTY early signals are net +7,915, 01-13 +22k came from 14:3x).
  Rejected on the same data today: buy after 30% decay from signal price
  (-4,704), every profit lock/target/ladder, hold past 15:28, tight stops.
  CHANGE: EXP1_WIN_LO and EXP2_WIN_LO (14,30) -> (14,45). Nothing else.
  REVERT: set both back to (14, 30), or restore
          ORION_SENSEX_V2520_BACKUP_20260916_pre_exp12_win1445.py
  PROOF: boot 2026-09-17 09:02 "[CHANGELOG] up to date (last entry 2026-09-16)";
         first behaviour proof = Thu 09-17 expiry, EXP2 why-not lines
         "outside (14, 45)-(15, 25) window" between 14:30 and 14:44.
  STATUS: applied 2026-09-16 17:2x IST, market closed, no bot process running;
          picked up by the 09:02 cron boot. NOT boot-proven, NOT trade-proven.

V2.5.20 [2026-09-11] *** EXPIRY EXITS — NO PRE-15:28 EXIT ON A WINNER ***
  WHY: user instruction "ok now deploy both, restart bots, now", after a two-
  session forensic on the 6 expiry sessions 2026-08-25 .. 2026-09-10 (NIFTY
  08-25/09-01/09-08, SENSEX 08-27/09-03/09-10), every trade re-priced against
  real Upstox expired-instrument 1-min option candles and real index closes.
  Finding: every repairable loss on the expiry books came from a PROFIT-LOCK or
  TRAIL closing a WINNER before the 15:28 force close. Three mechanisms did it:
    * EXP12 EXP2 LADDER_TRAIL_20pct — SENSEX 09-03 76400PE entry 62.70 trailed
      out 104.05 (+Rs827) while 15:28 was 246.50 (+Rs3,676): +Rs2,849 left.
      SENSEX 09-10 74700CE entry 296.50 trailed out 212.70 (-Rs1,676) while
      15:28 was 303.95 (+Rs149): +Rs1,825 left.
    * EXP12 EXP1 trail — NIFTY 08-25 24150CE entry 38.55 trailed out 30.00
      (-Rs556) while 15:28 was 184.60 (+Rs9,493): +Rs10,049 left. (That day the
      trail was TRAIL_10pct; it is now TRAIL_20pct_after_2x — removed as well.)
    * EXPIRY EXPIRY_VELVET_1.7x — SENSEX 09-03 76800PE entry 144.70, peak
      243.15: velvet armed at the 1.5x tier, which sets SL = ENTRY (breakeven),
      and closed the trade at 144.70 for Rs0 at 11:23 IST. A lock that arms
      after a 1.5x run and then protects ZERO profit is never right.

  WHAT (both bots, identical edits):
  (1) EXP12_HOLD_TO_1528 = True — EXP12 positions (EXP1/EXP2/EXP2W) no longer
      take ANY trail exit; the only exit is the existing 15:28 force close
      (EOD_1528). EXP12 legs already carry no stop-loss by design, so that is
      now the whole exit path. Revert = set False.
  (2) EXPIRY_VELVET_ARM_LOCK = False — the 1.5x tier that locked SL at breakeven
      no longer arms. UNCHANGED: T2 (peak>=2.0x -> SL=entry*1.5), T3 (peak>=3.0x
      -> SL=entry*2.0), the beyond-T3 30%-giveback ride trail, and HARDSL_-18pct.
      Revert = set True.

  NOT DEPLOYED, AND WHY — moving EXPIRY_SQOFF 15:15 -> 15:28. The Rs10,050 first
  quoted for the 09-03 velvet trade required a 15:28 square-off. The NIFTY
  live-EXPIRY history REFUTES that: across the 6 NIFTY EXPIRY legs in
  ~/orion_v2520_run.log, squaring off at 15:15 totals -Rs270 vs -Rs9,217 at
  15:28, driven by 08-04 24600PE (+Rs5,353 at 15:15, -Rs2,252 at 15:28 — it
  expired worthless). EXPIRY_SQOFF STAYS 15:15. With sqoff at 15:15 the velvet
  fix is worth +Rs1,549 on the 09-03 trade (222.15 at 15:15), not +Rs10,050.

  ALSO NOT IN THIS CHANGE: the NIFTY 09-08 EXP2 stale entry fill (filled 36.10
  while the 15:15 bar it cited was o30.35 h32.20 c14.60 — Rs36.10 only exists in
  the 15:14 bar). Separate fix, not yet applied.

  EVIDENCE / SIZE over the 6 expiry sessions: (1) touches 3 trades and improves
  all 3 (+Rs2,849 +Rs1,825 +Rs10,049 = +Rs14,723). (2) touches 1 trade
  (+Rs1,549). Total +Rs16,272. Verified: the -18% hard stop on the 09-03
  76800PE was never breached after the velvet exit (low 126.60 vs SL 118.65), so
  the trade really does survive to the square-off; all booked fills sit inside
  the real 1-min bar.

  STATUS / RISK: n = 4 repaired trades on 6 expiry sessions and Rs10,049 of the
  Rs16,272 is ONE NIFTY trade. EXP12 now has NO exit of any kind before 15:28 —
  a winner that round-trips gives it all back. This is NOT a validated edge; it
  is deployed on explicit user instruction. Next step: full-expiry-history replay.
  REVERT: ORION_PAPER_V2_5_20_BACKUP_20260911_pre_expiry_exit_repair.py /
          ORION_SENSEX_V2520_BACKUP_20260911_pre_expiry_exit_repair.py

V2.5.20 [2026-09-02] ORB ENTRY premium floor lowered — user instruction.
  WHAT: ORB_PREM_MIN NIFTY 60.0 -> 20.0, SENSEX 200.0 -> 66.7 (proportional carry
  at the 3.333x port scaling). This is the ENTRY strike-pick floor read by
  check_orb_signal() -> pick_strike_by_premium(). ORB_FLIP_PREM_MIN (added
  earlier today) is unchanged at 20.0 / 66.7.
  EFFECT: pick_strike_by_premium walks 50pt rings outward from ATM and takes the
  FIRST strike whose premium is in band, so a lower floor means ORB now buys a
  strike much CLOSER to ATM and much cheaper (10-expiry replay: entries move from
  ~Rs73-97 to ~Rs20-47).
  MEASURED, and deployed anyway on explicit user instruction: over the same 10
  NIFTY expiries on the bug-fixed engine this scores -Rs1,605 vs -Rs653 for the
  floor-60 config, i.e. Rs952 WORSE. Cause is that the fixed-POINT exits stop
  scaling: the -15pt stop is 19.5% of a Rs76.90 entry but 72.5% of a Rs20.70
  entry. Making the exits percentage-of-premium instead was tested at three
  calibrations and is worse still in both floors (-Rs1,430 / -Rs2,272 / -Rs1,780
  at floor 20). The floor-60 + fixed-point config was the best of all 8 tested
  combinations. n=10 expiry days only — thin sample, NIFTY-only, and ORB runs
  daily, so live forward evidence may differ from the replay.
  REVERT (one line, restores the best-measured config):
    ORION_PAPER_V2_5_20_BACKUP_20260902_035530_pre_entryfloor20.py /
    ORION_SENSEX_V2520_BACKUP_20260902_035530_pre_entryfloor20.py
  STATUS: applied 2026-09-02 ~09:20 IST, bots restarted same minute. NOT
          live-proven. WATCH the ORB entry premium in the next [ORB] Signal /
          ENTRY pair — expect a near-ATM strike at Rs20-50 rather than Rs60-100.
V2.5.20 [2026-09-02] (A) FORMING-BAR FIX — ORB/GAPBREAK could fire off an
  INCOMPLETE 5m bar.  (B) ORB flip-on-stop premium floor lowered.
  --- (A) FORMING-BAR ---
  WHAT: check_orb_signal() and check_gapbreak_signal() both scan
  `for _, b in df5.iterrows()` filtering only on minute-of-day, so df5's LAST
  row — the still-forming bucket — was a valid signal bar. With a 30s loop that
  bucket can hold as little as ONE 1m candle. For ORB this defeats the
  `body > 50% of range` filter entirely: that test exists to demand a decisive
  FIVE-minute bar, and a single 1m candle passes it trivially. For GAPBREAK the
  range-break was tested against an intra-bar tick, not a settled 5m close.
  FIX: both loops skip any bucket whose end time has not passed
  (`if b_min + 5 > _now_min: continue`). Mirrors the two sites that already did
  this correctly — check_fut5m_vwap_scalp_signal() reads iloc[-2] (last CLOSED
  bar) and is_orb_day_chop_killed() drops the forming bar via d15.iloc[:-1].
  FUT5VWAP was checked and is NOT affected.
  EVIDENCE (2026-09-01, reproduced from ~/orion_v2520_run.log): ORB logged
  "[ORB] Signal — close 24026.6 broke OR[24027.8,24082.6] side=PE" at 09:45 and
  entered 24100PE @83.00 at 09:46:34, stopping for -Rs975. 24026.6 is the
  1-MINUTE close at 09:45; the bucket held exactly one candle (body 0.664).
  NEITHER completed 5m bar qualified: 09:40-09:44 closed 24028.35, ABOVE the OR
  low, no break; 09:45-09:49 had body 0.433 < 0.5. That trade should never have
  existed. Loop simulation on 09-01 1m data: BEFORE fires 09:45 off 1 candle
  (PE); AFTER fires 10:55 off 5 candles (CE) — worth +Rs1,170 instead of -Rs975.
  SCALE: replay of the last 10 NIFTY expiries (harness G1-verified against the
  09-01 log) — the bug flips the traded SIDE on 3 of 10 days (07-14, 08-18,
  09-01). Net P&L similar (-Rs2,145 buggy vs -Rs2,018 clean) but only by luck.
  --- (B) FLIP FLOOR ---
  WHAT: new constant ORB_FLIP_PREM_MIN, read by _touch_flip_reentry() for ORB.
  NIFTY 20.0, SENSEX 66.7 (proportional carry at the 3.333x port scaling, same
  convention as the 08-31 GAP_THRESH and lock-arm entries).
  WHY A SEPARATE CONSTANT: ORB_PREM_MIN is read in TWO places — the ENTRY strike
  pick in check_orb_signal() and the FLIP in _touch_flip_reentry(). The replay
  held the ENTRY floor at 60 and varied ONLY the flip floor, so lowering
  ORB_PREM_MIN itself would have deployed an untested combination and changed
  which strike every ORB entry buys. Entry floor is UNCHANGED (60 / 200).
  EVIDENCE: 10 NIFTY expiries. Flip floor 60 -> 20 gains +Rs2,535 on the
  as-is engine and +Rs1,365 on the bug-fixed engine — the gain survives the fix,
  which was the check that mattered. Decomposition: ORB ENTRIES lose -Rs3,315
  (3/10 win); the FLIPS make +Rs3,705 (4/5). The flip carries the engine.
  CAVEATS, stated plainly: n=10 with only 5 flips — CIs include zero. Every
  winner exits at EXACTLY +18 (ORB_LOCK_PTS); the +40 ride trigger never engaged
  once in 10 expiries, so ORB is a +18/-15 coin flip. Left as-is per user
  2026-09-02. Floor 20 is still NET NEGATIVE on the bug-fixed engine (-Rs653):
  this makes ORB less bad, not profitable. Expiry days only; ORB runs daily.
  SENSEX has NO supporting replay — NIFTY-only evidence, carried on convention.
  REVERT: ORION_PAPER_V2_5_20_BACKUP_20260902_034429_pre_formingbar_flipfloor.py /
          ORION_SENSEX_V2520_BACKUP_20260902_034429_pre_formingbar_flipfloor.py
  STATUS: applied 2026-09-02 ~09:15 IST and bots RESTARTED the same minute on
          user instruction (both were flat, 0 trades, market had just opened;
          ORB entry window opens 09:25 so the restart preceded any signal).
          NOT live-proven. VERIFY today: grep "[ORB] Signal" in the run log —
          the quoted close must be a COMPLETED 5m bar close, never a bare 1m
          close mid-bucket; and any flip must show a premium >= the new floor.
V2.5.20 [2026-08-31] GAP_THRESH 75->50 + ORB REGIME GATE OPENED TO CHOP.
  (A) GAP_THRESH_PTS 250.0 -> 166.7 (proportional carry of the NIFTY
  75->50 at this port's 3.333x scaling). User: "it was 75 when nifty shares a lot=75,
  current is 65, so it should be 65, but considering nifty small but sharp
  movement, i am asking u to set it to 50." GAPBREAK stands down for the whole
  day when abs(today_open - prev_close) <= GAP_THRESH_PTS, so this is the gate
  that decides whether GAPBREAK exists at all on a given day. 08-31 gapped
  -58.10 and was skipped under 75; under 50 it would have traded.
  (B) ORB_ALLOWED_REGIMES ('BULL','BEAR','TRANSITION') -> + 'CHOP'. Only
  is_orb_day_sideways_live() reads this constant and only check_orb_signal()
  calls that, so the blast radius is ORB alone. ADX_CHOP_MAX was deliberately
  NOT touched: it feeds classify_regime() -> DAY.regime, which V2 also gates on
  via regime_allows_trade(), so moving it would silently loosen V2 too.
  MEASUREMENT (145 sessions, 2026-01-19..08-31, bot's own classify_regime on
  the same prior-1h bar the live boot uses): ORB stood down on 43/145 = 29.7%
  of sessions, rising to 35.0% over the last 40 and 62.5% since 08-20.
  Spot-excursion outcome of the ORB breakout (entry -> 15:15), by regime:
      regime        n   medMFE  medMAE  med-edge  MFE>=25  win%
      BULL         17     36.9    51.9      +0.5     76%    53%
      BEAR         23     70.2   157.8    -119.0     70%    22%
      TRANSITION   44     78.5    60.9     +39.9     82%    57%
      CHOP         39     71.5    78.6     -17.2     90%    46%
      ALLOWED-now  84     70.3    69.6      -9.9     77%    46%
  CHOP is NOT separable from the days already allowed: same win rate (46% vs
  46%), higher median MFE (71.5 vs 70.3), and it reaches +25 spot points MORE
  often than the allowed set (90% vs 77%). The gate was removing days that look
  like the ones it keeps. Note also that BEAR -- the regime the older notes call
  ORB's edge -- is by far the WORST bucket here (win 22%, edge -119).
  LIMITS: the metric is a SPOT-excursion proxy (max favourable/adverse move to
  15:15), NOT a premium-level ORB P&L replay -- it ignores stop/lock sequencing,
  so a day with large MFE can still have hit the stop first. It says the gate
  does not DISCRIMINATE; it does NOT prove ORB is profitable in CHOP. This
  loosens rather than tightens, so it will increase trade count and drawdown
  exposure. The in-day ORB_CHOP_KILL (>=4 VWAP crosses, ORB_CHOP_MIN_CROSSES=4)
  is UNCHANGED and remains the intraday chop protection.
  SENSEX-SPECIFIC LIMIT: the 145-session measurement above was run on NIFTY
  ONLY. There is NO SENSEX evidence for either change; both are proportional /
  mirrored carry-overs onto a port whose 3.3x scaling was never backtested.
  REVERT: ORION_SENSEX_V2520_BACKUP_20260831_pre_orbgate_gapthresh.py
  STATUS: code applied 2026-08-31 post-close, boot-verified, NOT trade-proven.
V2.5.20 [2026-08-31] ORB/GAPBREAK LOCK-ARM THRESHOLDS LOWERED (80->57.6, 50->26.7).
  WHAT: ORB_LOCK_PTS 80.0 -> 57.6; GAP_LOCK_PTS 50.0 -> 26.7. SENSEX mirror
  of the NIFTY change, scaled proportionally at this port's existing index
  ratios (18 * 80/25 = 57.6; 8 * 50/15 = 26.7). These are the
  lock-FLOOR ARM thresholds in _manage_touch_exit(), not targets: while
  DAY.floor is None the position is exposed to the full stop; once premium
  touches entry+lock the floor arms and the stop is bypassed entirely.
  WHY (user instruction 2026-08-31, after the 08-31 replay): both engines were
  replayed on 08-31 NIFTY using the live functions with a replay-clock ltp()
  override. ORB signalled 09:40 PE 24050 @64.40 (OR 09:15-09:20 =
  [24038.40,24128.70], break bar body 95%); GAPBREAK at a 50pt threshold
  signalled 09:55 PE 24050 @74.45. The 24050PE peaked at 83.30 -- i.e. +18.90
  over the ORB entry and +8.85 over the GAPBREAK entry. Both arms (89.40 /
  89.45) were missed by ~6 premium points, so NEITHER floor armed, both sat
  fully exposed, and both took the full stop at 11:54 on the reversal:
  ORB -15pt/-Rs975, GAPBREAK -30pt/-Rs1950. 18 and 8 sit just under those
  observed peaks and would have armed (82.40 / 82.45 vs peak 83.30).
  EVIDENCE / LIMITS: n=1. ONE day, one trade per engine, replayed not traded --
  neither signal could have been taken live on 08-31 because the bot was dead
  09:15-10:21 IST (see the SCRIPT_DIR hotfix entry above). The thresholds were
  chosen to clear a single observed peak, which is curve-fitting to one sample;
  a 30/60/90-day replay has NOT been run. Lowering the arm also banks smaller
  wins more often and cuts the number of trades that survive to the RIDE stage
  (ORB_RIDE_TRIGGER_PTS 40 / GAP 65 are unchanged), so mean win size should be
  expected to FALL even if win-rate rises. Watch giveback and win-rate over the
  next several ORB/GAPBREAK trades, not one.
  EXTRA LIMIT (SENSEX): the 08-31 replay was run on NIFTY ONLY. No SENSEX
  ORB/GAPBREAK replay supports these numbers; they are a pure proportional
  carry-over of a NIFTY-derived, n=1 result, on a port whose 3.3x scaling was
  itself never backtested.
  REVERT: ORION_SENSEX_V2520_BACKUP_20260831_pre_lock_change.py
  STATUS: code applied 2026-08-31 post-close. NOT live-proven -- bots exited
  cleanly at 15:30 IST and next boot is the 09:02 IST cron on 2026-09-01.
V2.5.20 [2026-08-31] STALE-DATA GUARD THRESHOLD 16 -> 20 MIN (15m + fut15).
  WHAT : in the V2.5.15 stale-data guard, _fresh_limit = now - 16min becomes
         now - _stale_max_min (20). The [STALE] log line now prints the
         constant instead of a hardcoded ">16min". NO entry/exit RULE, no
         engine, no indicator touched -- this only changes when the guard
         declares the frame unusable and blocks entries for one cycle.
  WHY  : a bar's LABEL is its bucket START, so a perfectly current 15m bar is
         already 15 min old by label the instant the next bucket opens. 16 min
         left only ~60s of headroom, and the tick samples the new bucket a few
         seconds BEFORE its first 1m candle exists, so the shim (correctly) has
         no bar to build yet and returns the previous bucket. The guard then
         fired once per bucket, always at :01/:16/:31/:46, always recovering on
         the very next tick. This is a threshold artefact, NOT stale data.
         Supersedes the 08-29 note "Deliberately NOT raising the 16-min stale
         guard": that reasoning assumed the shim would make the forming bar
         available immediately, which it cannot do inside the first ~60s of a
         bucket. 20 = 15 (bar width) + 5 (publish/tick tolerance).
  EVIDENCE: 2026-08-31 live logs, first full day on the resampling shim.
         Nifty 18 [STALE] events, Sensex 18 -- each one blocking entries for a
         cycle. Replayed every one of the 36 against the recorded tick time and
         bar label: bar-label age ranged 16.00-16.45 min, i.e. ALL 36 sat
         inside a 0.45-min band just past the old line. Under 20 min: 0 of 36
         trip. Margin to the new line is 3.55 min.
         The failure this guard exists for is untouched: the 2026-06-12
         incident served bars HOURS in the past (13:30 PE entry into a +68pt
         rally, HARDSL) and is still caught by a wide margin.
  DIAGNOSIS NOTE: the shim itself was verified NOT to be at fault -- a live
         probe at 14:02:04 IST on 08-31 returned the 14:00 15m bar (fresh) and
         1m candles through 14:01, resampling correctly. The bug was only ever
         the guard's threshold.
  SECOND, DEPENDENT CHANGE -- _completed_idx() (REQUIRED, not optional):
         raising the threshold ALONE would have been a net regression, and the
         08-29 note "raising the guard is the WRONG FIX" was right about why.
         The engines read df15['K'].iloc[-2] (and df1h iloc[-2]) assuming
         iloc[-1] is ALWAYS the forming bar. In the boundary window it is not,
         so simply unblocking those cycles would have had the engines evaluate
         a K one bar (15 min) STALE -- silently. Measured: the guard's instant
         refetch, 28ms later, recovered 0 of 18 trips, confirming the forming
         bar is genuinely absent, not merely slow.
         New module-level _completed_idx(df, now, minutes) returns the offset of
         the last COMPLETED bar: -2 when the forming bar is present, -1 in the
         boundary window. Wired into the 2 K/1h read sites (main tick + the
         guard's recovery branch). The boot-time read at the "Live state + first
         pulse" block is left on -2 deliberately (one-shot, pre-market-loop).
         SAFETY PROPERTY: it returns -2 on every tick that today reaches the
         engines, so it CANNOT change any tick that currently produces a trade;
         it only differs inside the window that today is unconditionally
         blocked. Unit-tested 8 cases + a 96-tick sweep: 0 normal ticks return
         anything but -2.
  REVERT: ORION_PAPER_V2_5_20_BACKUP_20260831_pre_stale_threshold.py /
          ORION_SENSEX_V2520_BACKUP_20260831_pre_stale_threshold.py
          (both changes are in these backups -- revert restores 16-min + iloc[-2])
  STATUS: applied 2026-08-31 14:2x IST during market hours. The RUNNING
          processes still hold the old 16-min value (Python loaded the file at
          the 10:21 IST restart) -- this takes effect at the next boot, Tue
          2026-09-01. NOT live-proven. Confirm on 09-01 by grepping the
          FlightRecorder for [STALE]: expect ZERO. If any remain, the cause is
          NOT this threshold and the shim/feed must be re-examined.
V2.5.20 [2026-08-31] HOTFIX: NameError SCRIPT_DIR crashed the bot on every boot.
  The 2026-08-29 trade-recorder addition referenced `SCRIPT_DIR`, but this file
  only ever defines `_SCRIPT_DIR` (underscore). Bot died in <2s on all 50 restart
  attempts this morning and gave up before EOD -- no trades taken 08-31 09:19-10:21
  IST. Fixed TRADES_CSV to use `_SCRIPT_DIR`. Evidence: ~/orion_sensex_run.log,
  attempts 1-50, all identical traceback at line 5855. Revert:
  ORION_SENSEX_V2520_BACKUP_20260831_pre_scriptdir_fix.py. Status: fixed,
  restarted manually intraday 10:21 IST -- pending confirmation of clean boot.
V2.5.20 [2026-08-30] ORB + EXPIRY EXEMPTED FROM THE CROSS-ENGINE CIRCUIT BREAKER.
  User, after the 08-29 changelog review: "no. of trades limit or sl hit
  halting should not be applied to orb and expiry engines. these are
  required." (Also confirmed the 08-29 stacking fix does NOT need to change:
  ORB/EXPIRY were never in _OVERLAP_ENGINES = [BASE, VWAP, FUT5VWAP], so they
  never stacked and nothing there needed touching. EXP12/EXP1/EXP2 shadow book
  already runs with no gates at all, unaffected either way.)
  WHAT: added _halt_exempt = (_base in ("ORB", "EXPIRY")) to the entry gate;
  _entry_allowed now ignores DAY.halted / GLOBAL_HALTED for these two engines
  unconditionally, in both PAPER and LIVE broker modes. Previously the global
  4-loss circuit breaker (any engine's losses, not just its own) set
  DAY.halted=True on every engine including these two, and in LIVE mode that
  fully blocked their new entries (paper mode already happened to be
  permissive via _cb_paper_mode, but only incidentally -- this makes it
  explicit and mode-independent). BASE/VWAP/FUT5VWAP/GAPBREAK are UNCHANGED
  and still halt normally.
  NO BACKTEST -- pure gating change per explicit user instruction, not a
  measured edge claim.
  REVERT: delete the _halt_exempt line and its `or _halt_exempt` use, or
          ORION_SENSEX_V2520_BACKUP_20260830_pre_halt_exempt.py
  STATUS: [USER] live on the next boot, Mon 2026-08-31.

V2.5.20 [2026-08-29] CE_BUY_ENABLED flag added (default True, NO behaviour change).
  Buying a CALL measured EV -1.067 pts over 91 sessions / 262,911 CE option-
  minutes, 95% CI [-2.179,-0.192] -- excludes zero, an ESTABLISHED loser. Puts
  are -0.088 (CI includes zero). Half-sizing was tried first and is a NO-OP:
  every engine is at 1 lot, so max(1, round(1*0.5)) == 1. At 1-lot sizing this
  is binary. Left ENABLED because disabling halves trade count and the user
  wants trades firing, and because the PE-minus-CE difference CI still includes
  zero -- only the CE loss is established, not the asymmetry.
  Set CE_BUY_ENABLED = False to act on it. Flag is declared and documented but
  NOT yet wired into the entry path -- wiring it is the next step if chosen.
  REVERT: *_BACKUP_20260829_pre_ce_halfsize.py
  STATUS: [BT] measured; flag inert by default.

V2.5.20 [2026-08-29] MAKE THE SILENT ENGINES FIRE — ORB regime gate + V3 probe fills.
  User: "i want all engines repaired and trades should be firing."
  Two engines were producing signals that never became trades.
  (1) ORB — was standing down on 27 of 40 live days (TRANSITION 14, CHOP 13) and
      there had been NO BULL/BEAR day since 08-17, so it fired zero times for six
      straight sessions, including 08-27 (NIFTY -187 closing on the low, SENSEX
      -643 on the low) which is the exact one-way trend an opening-range break is
      built for. The gate was also stricter than anything validated: only
      SIDEWAYS-skip was ever backtested; the live proxy collapsed TRANSITION AND
      CHOP into skip and its own comment admits it is "stricter (skip-more)".
      V2's regime_allows_trade() already permits TRANSITION.
      198-session check (spot pts, OR break, live ORB exit params):
        SENSEX BULL +8.71  BEAR +10.52  TRANSITION +3.34  CHOP +1.75
        NIFTY  BULL +1.30  BEAR  -0.88  TRANSITION +0.19  CHOP +2.62
      TRANSITION is positive on both, lower quality than BULL/BEAR but not
      harmful. => ORB_ALLOWED_REGIMES = (BULL, BEAR, TRANSITION); CHOP still out.
      Expected effect: ORB active on ~68% of days instead of ~32%.
  (2) V3 PROBE — the engine committed to a signal, placed a resting limit, then
      never got filled. NIFTY filled 13 of 30 (43%); SENSEX filled 0 of 8.
      Pullback NIFTY 8.0 -> 4.0, SENSEX 26.0 -> 13.0, window 15 -> 25 min.
      Trades a slightly worse entry price for actually being in the trade.
  NOT VALIDATED AS PROFIT. Both are frequency fixes measured in spot points;
  forward paper is the only referee. If ORB's win rate on TRANSITION days comes
  in worse than on BULL/BEAR over a real forward sample, revert first.
  REVERT: ORB_ALLOWED_REGIMES = ('BULL','BEAR'); probe pullback 8.0/26.0,
          window 15; or *_BACKUP_20260829_pre_firing.py
  STATUS: [USER][FWD] live on the next boot, Mon 2026-08-31.

V2.5.20 [2026-08-29] VWAP REPAIR — LEGACY_OVERLAP_SLOTS 4 -> 0 (both bots).
  User: "but also repair vwap".
  WHAT WAS ACTUALLY WRONG (measured, all 165 live trades 07-06..08-28):
  BASE/VWAP/FUT5VWAP each had 5 concurrent position slots and dedup ran per-BAR
  only -- nothing checked whether that strike was already open. Result:
      single positions  n=41  win 46%  mean +0.74pt
      stacked positions n=124 win 48%  mean +0.68pt
  Identical per-trade expectancy => the extra slots add NO EDGE, they only
  multiply size and variance. 24 of 40 stack events finished worse than the
  first slot alone; net cost Rs2,261; the damage is all in the tails (07-23
  stacked 4x into 24000CE -Rs7,248 vs -Rs1,398 for one slot; 08-13 stacked 7x
  -Rs7,213 vs -Rs959). 08-28 bought 24100PE twice 14 minutes apart and stopped
  both: -Rs1,739 instead of -Rs875. It also silently broke the standing 1-LOT
  rule -- VWAP could hold 5 lots at once. SLOT_LIST goes 18 -> 6.
  WHAT I DID **NOT** CHANGE, AND WHY:
   * CLIMAX FILTER (body>=87%) -- a 6-session n=14 sample suggested it was
     vetoing the best bars (79% continuation, +47pt/60m vs 52%/+13pt). RE-TESTED
     on 147 sessions (2025-12-24..2026-08-28, 3,381 15m bars/index): NIFTY shows
     NO difference (+60m +3.74 vetoed vs +4.37 kept, t=-0.14); SENSEX is
     suggestive but NOT significant (+14.27 vs +3.01, t=+0.77). The n=14 result
     was noise. Filter left exactly as is.
   * HARDSL_PCT -- the 08-29 study showed -18% sits inside the option's own
     noise (5 of 7 stops fired on index moves <0.1%), but the ATR-stop backtest
     could not clear G1 (34/53 entries locatable) and its baseline was Rs8,037
     from live, so NO stop change is justified yet. The trade recorder added the
     same day is what will settle it.
  REVERT: ORION_PAPER_V2_5_20_BACKUP_20260829_pre_overlapslots.py
          ORION_SENSEX_V2520_BACKUP_20260829_pre_overlapslots.py
  STATUS: [BT][USER] effective on the next boot, Mon 2026-08-31.

V2.5.20 [2026-08-29] TRADE RECORDER — per-trade CSV with DTE, MFE/MAE, option ATR.
  User: "write its expiry-1 days also, so will know the decay part also."
  WHY: the ENTRY: log line carries NO timestamp, so a closed trade cannot be
  located on the option's 1-minute tape afterwards. Reconstructing entries by
  price-matching failed for 19 of 53 VWAP trades (64%), which is exactly why the
  2026-08-29 ATR-stop backtest could not clear its G1 gate (and its baseline came
  out Rs8,037 away from the live result, because it had to discard the 19 TRAIL
  exits worth +Rs18,807 that it could not model). Bar-level CSVs cannot recover
  this either -- they sample ~5min and hold only ONE position, so with 5 overlap
  slots they produced 32 phantom entries for 3 real trades on 08-26.
  WHAT: Nifty_Trades_V2_5_20.csv / Sensex_Trades_V2_5_20.csv, one row per closed
  trade: entry_ts, exit_ts, held_min, engine+detail, symbol/side/strike,
  expiry, DTE, lots, entry/exit premium, reason, pts, rupees, MFE/MAE premium
  and points, the OPTION's own 14x1min ATR at entry and as % of premium,
  sl_level, entry/exit spot and spot_move.
  DTE answers the decay question: whether a stop was hit by direction or by
  theta as expiry approached. MFE/MAE answers whether a stop cut a real loser
  or ejected a trade that was working.
  EXPIRY IS TAKEN FROM TARGET_EXPIRY_DATE, NOT PARSED from the tradingsymbol:
  a monthly symbol does not encode the day, and "last Thursday" is wrong on both
  exchanges now (NSE weekly = Tuesday, BSE = Thursday) -- an end-to-end test
  decoded NIFTY26AUG as 2026-08-31 when the real expiry was 08-25.
  _expiry_from_symbol() is a weekly-only fallback and returns None for monthly
  rather than guessing.
  RECORDING ONLY -- no entry, exit or sizing behaviour changes. POS gains
  trough_premium (MAE), atr_entry, expiry_date; LAST_SPOT global refreshed each
  pulse in check_exits() so the recorder has a spot at every call site; the whole
  writer is wrapped in try/except so a logging fault can never break an exit.
  VERIFIED end-to-end against the real 2026-08-28 VWAP trade (74.80 -> 61.34,
  -Rs875): every field reproduced, DTE=2, atr_pct=4.36%.
  REVERT: ORION_PAPER_V2_5_20_BACKUP_20260829_pre_traderecorder.py
          ORION_SENSEX_V2520_BACKUP_20260829_pre_traderecorder.py
  STATUS: [USER][FWD] first rows land Mon 2026-08-31. Nothing recoverable for the
  37 days already logged.

V2.5.20 [2026-08-29] FUT5VWAP 3 lots -> 1 lot (BOTH bots), user-directed.
  User: "i want that one engine which takes 3 lots, is it working fine, if not
  reduce to 1 lot."  It is not working fine.
  EVIDENCE (live log 2026-07-06..08-28, orion_v2520_run.log, 155 exits parsed):
    FUT5VWAP  18 trades  14 wins (77.8%)  net -42.88pt  = -Rs8,362 at 3 lots
  The high win rate is an artifact of the exit shape, not edge: wins are capped
  at the +4.00pt LOCK_FLOOR (avg win +5.51pt) while the 4 losses each ran the
  full -30.00pt stop. Break-even win rate at that payoff = 84.5%; actual 77.8%.
  It was the single worst engine in the book by rupees, purely because of the 3x.
  NUANCE, stated so it is not lost: all 4 losses are BEFORE the 08-17 stop
  tightening (30->25pt). Since then only 2 trades have closed (08-25 +4.00,
  08-28 +4.00), both wins. So the 08-17 fix may well work -- but n=2 is not
  evidence, and an unproven engine should not carry triple size. Re-raise to 3
  only after a forward sample large enough to beat the 84.5% break-even bar.
  REVERT: ORION_PAPER_V2_5_20_BACKUP_20260829_pre_fut5_1lot.py
          ORION_SENSEX_V2520_BACKUP_20260829_pre_fut5_1lot.py
  STATUS: [USER][FWD] takes effect on the next boot (Mon 2026-08-31).

=== ORION CHANGE HISTORY (V2.2.2 -> V2.5.9) ===

V2.2.2 [PRODUCTION BASELINE — T10]
  Entry : 1h SMA20/50 regime + 15m StochRSI K (CE>=38 rising, PE<=80 falling)
  Exit  : HARDSL -35%, TIME_SL 210min/-20%, BE +15% -> option SMA8(low) trail
  CB=2, 1 lot, no flip, no V3, no chop filter

V2.3  [+V3 CLUSTER LEVELS]
  + PDH/PDL/round_50/round_100/PDC/1h swing pivots clustered within 20pts
  + Grade A (>=3 source kinds) / Grade B (>=2)
  + ADX regime classifier (BULL/BEAR/CHOP/TRANSITION)

V2.4  [+EXIT UPGRADES]
  + 15m option SMA8(low) trail (KEPT in all future versions)
  + ATR-based exits (REMOVED — not robust enough)
  + BE armor at +15% (REMOVED later — net negative in backtest)

V2.5.0  [HYBRID V2+V3 + TIME-RATCHET]
  + Hybrid V2+V3 entry (V2 priority on same-bar tiebreak)
  + Time-ratchet exit: 90min / +20 step

V2.5.1  [ENTRY REFINEMENT]
  + V2 PE_floor=25 (K>=25 required for PE entry)
  + V2 CE: no upper K cap (cap tested and REJECTED — hurts WR)
  + V2 priority confirmed: +Rs 52k vs V3-priority

V2.5.2  [FLIP RULE +Rs 130k]
  + Path A flip (in-trade): elapsed>=30 + peak>=entry+15 + LTP<=entry+10 + K reversed
  + Path B flip (post-exit): K reversal within 60min
  + Opposite-side only (same-side continuation REJECTED: -Rs 191k CATASTROPHIC)
  + CE->PE: K falling, 25<=K<=80 | PE->CE: K rising, K>=38

V2.5.3  [V3 SINGLETONS + HARDSL LOCKED]
  + Promoted singletons: PDH/PDL/round_100(+-200 PDC)/swing pivots standalone Grade B
  + HARDSL locked at -25% (swept -35% to -15%; -25% optimal)
  + PnL Rs +3,14,418

V2.5.4  [FLIP CAP]
  + MAX_FLIPS_PER_DAY=3 (flips 1-3 win Rs 131k; flips 4+ lose Rs 21k)
  + PnL Rs +3,23,851

V2.5.5  [CHOP FILTER +Rs 49k]
  + RSI [47,53] indecision band blocks ALL entries
  + PnL Rs +3,72,598

V2.5.6  [V3 PDC CONTAMINATION FIX — LOCKED Rs 3,85,724 / WR 35.7%]
  + Exclude PDC from clustering (PDC is reference, not tradeable level)
  + G/R require >=25pt buffer from PDC (motivated by 2026-05-18 bad paper trade)
  + PnL Rs +3,85,724 / MaxDD -1,331 / Red 5/18

V2.5.7  [VELVET ROPE + RATCHET +Rs 1,14,324 / WR 35.7%->55.4%]
  + Velvet Rope: premium hits entry+15 -> SL immediately to entry+2
  + Ratchet Gate: 30min elapsed + entry+25 -> SL to entry+15
  + Runner Trail: +20 per +20pts peak (one-way)
  + Trade-off: Red months 5->10/18, MaxDD -1,331->-1,885

V2.5.8  [K EXTREME + FULL SMA ALIGNMENT]
  + K extreme filter: CE entry only if K<25 recently (3 bars); PE if K>75 recently
  + Full SMA alignment: CE needs close>SMA20>SMA50 (was just close>SMA20)

V2.5.9  [Rs 6,70,425 / WR 66.9% / 357 trades / MaxDD -1,485 / Red 8/18]
  + RSI DIRECTIONAL GATE replaces RSI [47,53] chop filter:
      CE: 1h RSI>53 required | PE: 1h RSI<47 required
  + MACD 1h alignment: CE needs MACD_line>signal; PE needs MACD_line<signal
  + Premium gate: 30<=entry_LTP<=180 (blocks deep OTM and IV-spike entries)
  + Tightened exit params: RI=12 (was 15), RT=20 (was 30), RS=25 (was 20)
  + CB=3 (was 4)
  + Straddle monitoring: informational Telegram at 9:45 and 11:30
  + Options VWAP: informational context at entry/pulse/exit

V2.5.12 [CURRENT LOCKED — Rs 6,88,158 / WR 64.5% / 363 trades / MaxDD -1,119 / Red 5/18]
  SOURCE: VRL (Vishal Rajput) code analysis — peak-based ratchet ladder
  + HARDSL tightened -25% → -18% (faster loss cut, less capital exposed)
  + 20-min time gate REMOVED — purely peak-based ladder (no waiting)
  + Ladder Tier2: peak >= entry+24 → SL = entry+12 (immediate)
  + Ladder Tier3: peak >= entry+36 → SL = entry+24 (immediate)
  + Entry logic UNCHANGED from V2.5.9
  + Validated: real option data (May 4-21 2026, 12 days)
  + Key improvement: MaxDD -1,485 → -1,119 (-25%), Red months 8 → 5

V2.5.12-LIVE [2026-05-29 — FIRST LIVE TRADING SESSION WITH mSTOCK EXECUTION]
  + EXECUTION_BROKER switched from kite_paper → mstock_live
  + mStock Type B API integrated: login → set_access_token → verify_totp (TOTP auto)
  + Instrument master: direct fetch from OpenAPIScripMaster (173k symbols, name field)
  + order_status: mStock returns 'Traded' status (not 'COMPLETE') — mapped correctly
  + place_order: disclosedquantity="0" required (blank causes IA400 rejection)
  + IP 18.212.243.203 (PythonAnywhere) whitelisted in mStock API settings
  + BUY: 15s timeout, cancel-and-check on timeout, abort if not filled
  + SELL: 3 retries × 5s, 🚨 CRITICAL Telegram alert if all fail, POS.active stays True
  + V3 REGIME GATE REMOVED: V3 now fires in CHOP/INSUFFICIENT regime
      Root cause of bug: regime gate wrapped ALL signals including V3;
      V3 uses cluster break/reject as its own confirmation — ADX not needed
      V2 and FLIP remain regime-gated (BULL/BEAR/TRANSITION only)
  + V3 engine: acts on ALL Grade A/B clusters simultaneously (not just nearest)
  + PREMIUM_MAX asymmetric: CE=180 (unchanged), PE=300 (was 180, captures panic moves)
  + VWAP double confirmation engine (new):
      Fires when Nifty 15m bar crosses daily VWAP with body>=50% range
      AND ATM CE/PE LTP is also above/below its daily VWAP simultaneously
      Self-confirming like V3 — no regime gate
  + LOTS_PER_TRADE = 2 (live)

V2.5.13 [VWAP TRAIL EXIT + BOOT SELF-TEST + STABILITY FIXES]
  + VWAP engine trades: trail exit uses option's own VWAP (15m close < option VWAP)
    instead of SMA8(low) trail — holds through pullbacks better on VWAP-confirmed moves
  + V2/V3/FLIP trades: keep original SMA8(low) trail (unchanged)
  + Boot self-test: BUY (LIMIT ₹0.05) + SELL (LIMIT ₹9999) on deep OTM option at startup
    Both must succeed and cancel cleanly or bot aborts — confirms mStock connectivity + IP
  + MStockBroker class inlined into single .py file (no separate mstock_broker.py)
  + IA403 recovery: rebuilds SDK client from scratch on IP mismatch, 3 consecutive → halt
  + Position sync cooldown: 180s → 300s (avoids false MANUAL_EXIT on slow fills)
  + MANUAL_EXIT fix: clears buy_order_id before close_trade to prevent duplicate SELL
  + State file: added date field, resets trades_today/losses on new day boundary
  + VWAP dedup log spam removed (silent return on same-bar re-fire)

V2.5.14 [TIERED PROFIT LOCK LADDER — inspired by VRL]
  + Replaced sparse 3-tier ratchet (Velvet Rope + T2 + T3 + Runner) with 7-tier ladder
  + Ladder: +12→+2, +18→+8, +24→+12, +30→+20, +36→+24, +40→+30, +50→+40
  + More tiers = less profit give-back on sharp reversals
  + Checked every tick (not candle-based) — same as before but tighter protection
  + Unified code: single loop replaces 3 separate sections (3a/3b/3c → 3)
  + VWAP engine upgraded to TRIPLE confirmation:
    Gate 1 (PRIMARY): Nifty FUTURES 15m close crosses futures VWAP, body >= 50%
    Gate 2: Nifty SPOT 15m close same direction above/below spot VWAP
    Gate 3: ATM option LTP above/below option's own VWAP
  + Futures VWAP is now the primary decision criterion — real margin-backed money
  + Nifty FUT token auto-resolved from Kite instruments at boot (no hardcoding)

V2.5.15 [STALE DATA GUARD — 2026-06-12]
  + ROOT CAUSE FOUND: Kite intermittently returned a 15m series ending ~2h in
    the past. Evidence: VWAP entry logged bar=198 at 11:30 but bar=197 at 13:30
    (bar index went BACKWARDS); the 13:30 entry cited a 67% bearish bar +
    FUT 23375 while the live tape was +68 pts off the low in 4 min → bought PE
    into a V-reversal → HARDSL -21.73. Fresh-data replay confirms the signal
    does NOT fire at 13:30 with up-to-date frames. Likely also suppressed valid
    signals (Jun-11 zero-trade day: fresh-data replay finds 4 trades / +35 pts).
  + Guard (active 09:32+): if last 15m bar (spot or futures) is older than
    16 min → instant refetch from Kite; if recovered, continue + Telegram info;
    if still stale → Telegram alert + ENTRIES blocked for that cycle only.
  + EXITS are never blocked on data quality.
  + Telegram alerts rate-limited to 1 per 10 min; log line every cycle.

V2.5.16 [MOMENTUM GATE ON SAME-SIDE STREAKS + SMA8 TODAY-ONLY FIX — 2026-06-17]
  + PROBLEM: in choppy markets the bot ran 3+ rapid same-direction trades —
    first 1-2 win small, the 3rd buys into the reversal and takes the full
    -18% HARDSL, then keeps buying the same side, wiping the day's gains.
    Diagnosis (May+June real-opt data): the persistence is the VWAP engine
    (no regime filter, re-fires same side each 15m bar). The 1st/2nd winners
    exit on the peak ladder (TRAIL_+N); the 3rd dies on HARDSL/VWAP_TRAIL.
  + MOMENTUM GATE: the 3rd+ CONSECUTIVE same-direction entry (any engine) is
    blocked unless spot has moved >= MOM_GATE_PTS (12) WITH the trade over the
    last MOM_GATE_BARS (5) closed 1m bars. 1st/2nd same-side entries untouched.
    Run counted from DAY.trades_today (closed trades). New fetch_nifty_1m() +
    momentum_gate_ok(); fails OPEN if 1m data unavailable; "🚧 Momentum-gate
    BLOCK" Telegram on a block. Backtest (May real-opt): baseline -7.3 pt →
    gate +104.0 pt, 0 winners blocked (blocks only flat-momentum |mv|<=8 chop).
  + SMA8 TODAY-ONLY FIX: sma8_low_of_option() now averages ONLY today's closed
    15m option lows (arms after SMA_TRAIL_MIN_BARS=4 today-bars). Previously it
    averaged 8 bars from a 10-day fetch, mixing yesterday's different-level /
    illiquid lows → false trail exits. NOT removed: backtest showed deleting
    SMA8 costs -66 pt (it is a tighter stop than the -18% HARDSL).
  + Ladder exit, HARDSL, flip logic, stale-data guard all UNCHANGED.
  + start_orion.sh now launches V2.5.16 (90s crash-fallback still → V2.5.14).

V2.5.17 [3 CHOP-BLEED GUARDS — 2026-06-18]
  + CONTEXT: 06-16 (-20.4pt/7trades) and 06-17 (-44.0pt/4trades) were both
    compressed chop days (full range 141pt & 107pt; 06-17 had 9 mean-crosses in
    a 107pt box). The regime classifier stayed BULL all 76 bars both days and
    chop_block fired 0 times, so the breakout engines kept firing into noise.
    See ~/orion_backtest_lab/results/RESULTS.md (2026-06-18 post-mortem).
  + #1 MORNING CHOP GATE (CHOP_GATE_ENABLED): decided ONCE after ~10:30 IST from
    the first-hour (09:15-10:15) FUT bars. Stand aside (block ALL new entries for
    the day) when early efficiency-ratio <= CHOP_ER_MAX (0.25) AND (first-hour
    FUT-VWAP cross-count >= CHOP_VWAP_CROSSES_MIN (3) OR first-hour range <
    CHOP_RANGE_PT_MAX (110pt)). Exits always allowed. Fails OPEN (not enough
    bars yet -> no decision -> trade normally). morning_chop_verdict().
  + #2 VWAP BODY BAND (VWAP_BODY_CLIMAX_PCT): VWAP entry now takes only the
    65-86% body band — existing >=65% min kept, NEW >=87% climax/exhaustion bars
    skipped (climax bars fade). One added guard line in check_vwap_signal().
  + #3 MOMENTUM-FADE GATE (FADE_GATE_ENABLED): for a 3rd+ consecutive same-side
    entry that follows >= FADE_MIN_PRIOR_WINS (2) consecutive same-side WINS,
    inspect 3-min option premiums of BOTH the trend-side and opposite-side ATM
    strikes over the last FADE_OPT_BARS (3) closed bars. Enter ONLY IF the
    trend-side option is NOT decaying AND the opposite-side option IS decaying;
    otherwise skip (momentum has faded / is rotating to the other side). Fails
    OPEN on missing data. fade_gate_ok() + fetch_option_3m(). Complements the
    V2.5.16 spot-move momentum gate (both must pass).
  + All three guards are ADDITIVE; ladder/HARDSL/flip/SMA8/stale-guard UNCHANGED.
  + NOT yet sim-A/B'd — shipped on user direction; 2026-06-18 is paper-only, so
    the live paper session is the first validation. WATCH first CHOP-GATE day +
    first FADE block + that #2 climax-skip doesn't starve VWAP.
  + start_orion.sh now launches V2.5.17 (pkill pattern V2_5_1[567];
    90s crash-fallback still → V2.5.14 archive).

V2.5.18 [SMA8 ENTRY-AWARE FIX + CHOP-GATE RE-ARM — 2026-06-19]
  + CONTEXT: 2026-06-19 (paper) — gap-down day. One V3 PE (24000PE @114) entered
    correctly at 10:15 on a Grade-A R-cluster break, but SMA8_LOW_TRAIL exited it
    31s later at +1.6 (the trail evaluated the 10:00 bar — which CLOSED BEFORE
    entry — against today's lows-avg). Spot then fell 24040->23926 without us;
    morning chop-gate (ER=0.01, range=70pt) then stood aside the rest of the day.
  + FIX A (SMA8 pre-entry bar): the SMA8(low) trail now NEVER acts on a 15m bar
    whose CLOSE time (bar-start + 15m) is <= POS.entry_time. A fresh entry can no
    longer be ejected on price action that happened before it was opened.
  + FIX C (SMA8 arm window): trail arms on bars-SINCE-ENTRY, not bars-of-day.
    sma8_low_of_option() now averages only TODAY's closed bars that closed AFTER
    entry and needs >= SMA_TRAIL_MIN_BARS_SINCE_ENTRY (1) of them. With 1 own bar
    SMA8L == that bar's own low, so close(>=low) can't trigger -> first real
    trigger needs >=2 own bars. SMA_TRAIL_MIN_BARS (4, bars-of-day) is now only
    the fallback when entry_time is unknown (state-load edge). NOT a BE-gate.
  + CHOP-GATE RE-ARM (CHOP_REARM_ENABLED): after a morning stand-aside, release
    the block when a CLOSED FUT 15m bar breaks the recorded first-hour range by
    >= CHOP_REARM_BUFFER_PT (15pt) with body >= CHOP_REARM_BODY_MIN (65%), in the
    regime direction (BULL=>up-break only, BEAR=>down-break only, else either).
    FUT leads spot, so this triggers earlier than a spot-range break. Re-arm is
    one-way for the day (stays live once released); per-trade momentum/fade/CB
    guards still apply. _morning_chop_verdict_impl() stashes FH hi/lo;
    chop_rearm_check() evaluated each cycle while blocked. Logs [CHOPGATE] RE-ARMED.
  + Ladder/HARDSL/flip/VWAP-trail/stale-guard UNCHANGED. SMA8 KEPT (deleting it
    cost -66pt, V2.5.16) — this only changes WHEN it may fire, not whether.
  + NOT yet sim-A/B'd — shipped on user direction 2026-06-19; backtest the
    re-arm thresholds on post-chop trend days before relying on it live.

V2.5.19 [THREE FUT-VWAP ENTRY PATHWAYS — 2026-06-21]
  + Built on user direction 2026-06-21. THREE new VWAP-cross entry pathways.
    NOT yet sim-A/B'd — BACKTEST before flipping start_orion.sh to V2.5.19.
    All three are flag-gated (default ON). Existing V2/V3/FLIP UNCHANGED.

  + FEATURE 1 — FUT 15m VWAP cross + CONFIRMATION CANDLE (all-day).
    VWAP15_CONFIRM_ENABLED. The existing VWAP engine no longer fires on the
    cross bar alone: it now requires the cross bar (iloc[-3], body 65-86% band)
    PLUS the next closed bar (iloc[-2]) to CONFIRM in the same direction —
    same-colour candle that still closes on the same side of FUT-VWAP. Fires in
    either direction, any time in the entry window. Re-entries are governed by
    the existing momentum gate (no extra cap). check_vwap_signal().
    INTERPRETATION: "confirmation candle in same direction" = next 15m candle
    closes same side of its open (same colour) AND same side of VWAP as the
    cross. Confirmation candle has NO body-size requirement (only the cross bar
    does). If wrong, adjust _vwap15_confirm_ok().

  + FEATURE 2 — FUT 5m VWAP cross + S/R distance, FIXED +12 TARGET scalp.
    FUT5_SCALP_ENABLED. New engine 'FUT5VWAP'. On each closed FUT 5m bar that
    CROSSES its session VWAP (bar opens one side, closes the other) with body
    65-86% AND whose close is > FUT5_SCALP_SR_MIN_DIST (20pt) from EVERY one of
    yesterday's classic pivots S1/R1/S2/R2 → buy in the cross direction. Exit is
    a FIXED +FUT5_SCALP_TARGET_PTS (12) option points (HARDSL + 15:25 force-close
    still apply; NO trail/SMA8). One trade per event: deduped on the 5m bar ts,
    so the next entry needs a fresh qualifying cross. check_fut5m_vwap_scalp_signal().
    INTERPRETATION: ">20 points away from s1/r1/s2/r2" = min distance to ALL four
    pivots > 20pt (price in clear space, not hugging a pivot). "cross" = bar
    open & close on opposite sides of VWAP. Pivots = classic floor-trader pivots
    from the prior trading day's H/L/C. If wrong, adjust compute_classic_pivots()
    / check_fut5m_vwap_scalp_signal().

  + FEATURE 3 — MORNING 09:15-10:15 exception (bypasses the 09:45 start gate).
    MORNING_VWAP_ENABLED. Before the normal 09:45 entry start, between
    MORNING_WIN_START (09:15) and MORNING_WIN_END (10:15): if a closed FUT 15m
    bar crosses its VWAP (body 65-86%) AND its close is > MORNING_VWAP_SR_MIN_DIST
    (20pt) from every pivot S1/R1/S2/R2 → buy in the cross direction. Re-entries
    per momentum gate. Uses engine 'VWAP' (so it inherits the VWAP option-VWAP
    trail exit). Runs even when in_entry_window() is False; still respects
    stale-guard, gap-suppress, CB/halt, manual cooldown. check_morning_vwap15_signal().
    INTERPRETATION: this only ADDS the pre-09:45 window; from 09:45 on, the
    normal engines (incl. Feature 1) already run. No confirmation candle is
    required here (spec did not ask for one).

  + Classic pivots computed at boot from prior-day H/L/C → DAY.pivots
    {P,S1,R1,S2,R2}; min_dist_to_pivots() helper. New fetch_nifty_fut_5m().

=========================================================================
BACKFILL 2026-08-29 — V2.5.19 (06-21) -> 2026-08-28
=========================================================================
Reconstructed 2026-08-29 from the dated inline comments at each code site and
the research notes. The banner below had not been updated since V2.5.19
(2026-06-21) while 24 changes went in; an audit on 2026-08-27 confirmed NO
engine was silently removed or disabled, but the history was unreadable from
the top of the file. Enforcement now exists (see CODE_FINGERPRINT / the boot
UNDOCUMENTED-CHANGE check) so this cannot silently recur.

KNOWN GAP, stated plainly: the *_BACKUP_*.py chain jumps from 2026-08-01 to
2026-08-25. The nine changes dated 08-08 through 08-20 have NO pre-change
backup file. They are reconstructable from the inline comments below, but they
cannot be diffed back to their exact prior code. Every change from 08-25 on has
a backup.

STATUS legend: [BT] backtested   [FWD] forward-paper only, no backtest
               [USER] user-directed   [FIX] bug fix   [UNVAL] unvalidated

V2.5.20 [2026-06-23] Same-direction re-entry cooldown.
  WHY: 06-23 a PE won +42 and re-entered PE 33 s later straight into HARDSL.
  The momentum/fade gates only look at the signal, not at how the last trade in
  that direction ended.  [FIX]

V2.5.20 [2026-06-24] VWAP15_CONFIRM_ENABLED = False.
  WHY: user call. The V2.5.19 confirmation candle delayed entries into already-
  declining trends. VWAP now fires on the FUT 15m VWAP cross bar itself.
  RE-REVIEW TRIGGER: if a chop regime returns and VWAP false-starts rise, the
  confirm candle is the first thing to switch back on.  [USER]

V2.5.20 [2026-06-29] Paper-mode order bypass — kite_paper places no real orders.

V2.5.20 [2026-07-06] Rebuilt on the concurrent-backtest architecture; all
  engines run simultaneously with no suppression. Plus two CRITICAL fixes:
  (a) ORB/GAPBREAK stale-data — fetch_nifty_1m/5m returned frames whose last
      bar was days old; a 2-lot PE went in on a close from 07-03. (b) position-
      sync false MANUAL_EXIT.  [FIX]

V2.5.20 [2026-07-07] LOTS_PER_TRADE 2 -> 1 (user instruction). ATM strike
  resolution fix (old round_to_atm(24000)+2000 path).  [USER][FIX]

V2.5.20 [2026-07-08] V2.5.20 given its OWN Telegram bot (was sharing V2.5.19's).
  MANUAL_EXIT detected via the bot's own order-ids, never account-wide net_qty.
  [FIX]

V2.5.20 [2026-07-10 .. 07-14] Broker-integrity hardening after the 07-09
  NIFTY24000CE incident and the 07-14 stranded lots: order-book/RMS race fixes
  on both BUY and SELL, per-position is_paper flag, unconfirmed_fill flag,
  bot order-id registry, orphan-position resume, HALT_NEW_ENTRIES_ON_DATE
  replacing a bare NO_NEW_ENTRIES_TODAY that had been left True since 07-09.
  [FIX]

V2.5.20 [2026-07-12] V2 params from the real-30-day grid search (k_extreme=ON,
  rsi_gate=ON, macd_align=OFF) on 05-15..07-10 — 7 trades / 71.4% WR / +45.96pt.
  CAVEAT RECORDED AT THE TIME: 7-trade sample. MACD gate left in the code behind
  V2_MACD_GATE_ENABLED so it can be flipped back.
  Also: V3 probe entry (limit, replacing market entry, user instruction), V3
  early-entry + fast exit, ORB in-day CHOPPY kill, MOM_GATE_V3 re-enable.
  [BT-weak][USER]

V2.5.20 [2026-07-13] PUT-FLIP QUALITY GATE — V2.5.19 flipped a winning CE to PE
  on a 0.5pt K move (58.9 -> 58.4). Gate requires a real reversal.  [FIX]
V2.5.20 [2026-07-13] *** COUNTER-TREND VETO *** — single choke point for EVERY
  engine. The day's low printed 09:15 and Nifty ran one-way to 24259 while the
  bot kept buying PEs. BIGGEST VALIDATED EDGE TO DATE: +697.9 pts / +Rs45,362
  out-of-sample. Do not weaken without equivalent evidence.  [BT]

V2.5.20 [2026-07-20] EXECUTION_BROKER LIVE -> PAPER, explicit user instruction;
  no real orders since. T5 engine (levels + premium-divergence). APEX engine
  (the user's actual method) — shadow only. 1-minute capture added (Kite
  interval is 'minute', not '1minute'). Unlimited engine overlap in paper.
  [USER]

V2.5.20 [2026-07-24] VWAP/APEX frm>now precession fix.  [FIX]

V2.5.20 [2026-07-26] FUT5VWAP dedup fix (<= not ==; a stale/out-of-order refetch
  reopened a second real position on an already-seen signal, seen 07-24).
  EXPIRY engine — OTM premium-multiplication pop, expiry day only, one shot.
  Expiry-specific velvet-rope/ladder expressed as MULTIPLES not points (user
  instruction: a Rs8 option cannot use a +12pt ladder).  [FIX][USER]

V2.5.20 [2026-07-27] push_logs_to_github(): added `git rebase --autostash`.
  WHY: a dirty tree made plain `git rebase` abort silently, so every push had
  been rejected non-fast-forward since 07-20 (~365 rejects/day/bot).
  *** SIDE EFFECT DISCOVERED 2026-08-27: this is what orphaned the logging
  FileHandler's inode and blanked the FlightRecorder logs. Fixed 08-29 with
  WatchedFileHandler. DO NOT remove --autostash. ***  [FIX]

V2.5.20 [2026-07-29] Counter-trend-veto Telegram dedup (spam fix).  [FIX]

V2.5.20 [2026-08-01] APEX entry filter: APEX_RSI_MIN_DELTA = 5.0 — require a
  decisive RSI turn, not any turn. Re-sim -3,835 -> +234, IN-SAMPLE ONLY.
  [UNVAL]

V2.5.20 [2026-08-08] VWAP same-day loss cap, from the real 3-month simulated
  backtest on Upstox real premiums. Same pass disabled PIVOTBREAK.  [BT]

V2.5.20 [2026-08-09] PIVOTBREAK REMOVED ENTIRELY (code deleted, syntax-clean).
  WHY: kill-switch (08-08) then a full professional rebuild (08-09) both failed;
  losses were structural exit-logic, not day-type. Do not re-add without new
  evidence — see the rebuild trail before trying.  [BT]

V2.5.20 [2026-08-13] V2 per-bar dedup on the closed 15m bar, same convention as
  VWAP/FUT5VWAP. WHY: V2 had NO dedup, so a Kite rate-limit retry stacked 5 V2
  lots on one signal — this is what produced the phantom +Rs8,492 on 08-12 that
  looked like edge and was not. Also fixed a POS.engine comparison against the
  literal 'BASE'.  [FIX]

V2.5.20 [2026-08-16] V2_DAILY_LOSS_CAP = 1. From a real 3-month re-port of V2's
  own logic (05-04..08-06): capping V2 at one loss/day was the only no-trade-
  zone variant that survived; all the others failed.  [BT]

V2.5.20 [2026-08-17] FUT5VWAP min pivot distance 30 -> 25 pt, from a real
  re-port at native 1-min granularity. NOTE: the corrected FUT5VWAP baseline is
  88.9% WR / +Rs53,315 over 380 days — the earlier 94% / +Rs104k figure was a
  same-bar exit-ambiguity BUG and is void.  [BT]

V2.5.20 [2026-08-20] Four VWAP/V2/ORB changes from a real 40-trade backtest on
  the live 07-07..08-20 log:
   (1) VWAP 5m persistence + distance-from-VWAP gate;
   (2) VWAP post-loss same-side cooldown;
   (3) V2 trail scaled to entry premium (arm = entry x 1.15) instead of fixed
       points — V2 entries range from ~Rs73 upward, a fixed +15 is not
       comparable across them;  [USER]
   (4) V2 hard stop fixed at -15 pt, replacing the generic -18% HARDSL;  [USER]
   (5) ORB exit tightened: stop 15 / ride 40 / giveback 20.
  Neither VWAP gate alone made VWAP profitable — they reduce the loss. Expect a
  smaller drawdown, not profit.  [BT]

V2.5.20 [2026-08-22] *** EXPIRY ENGINES 1 & 2 (EXP12) — SHADOW PAPER BOOK ***
  E1 RSI-snap + OI/strike gates: recent 40 expiries 9 trades / 89% WR /
  +Rs18,944 (older 57 dormant, -Rs819).
  E2 cheap-ladder Rs8-16 + spot-through-strike + OI <= +5%, NO stop, trail 20%
  after 40: recent 40 +Rs12,760 (older 57 -Rs4,910).
  User instruction: NO restrictions — no trade-count or SL-count limits.
  SEPARATE BOOK: own lot size, own CSV, EXCLUDED from fmt_eod_summary by
  design. (Reporting confusion this caused was raised 08-27; being fixed in a
  later item.)  [BT][USER]

V2.5.20 [2026-08-25] EXP12 relaxed gates, user override after the 08-25 miss
  (premium out-ran spot, so E2's "Rs8-16 AND spot>=strike in the SAME minute"
  never overlapped): E1 no SL / trail after 2x; entries 14:30-15:25; dist >= -35
  (-115 Sensex) OR crossed within 30 min; E2 band hi 20 (66 Sensex); universe
  re-resolve every 5 min. Replay on 08-25 = +Rs3,416 vs actual 0.
  *** KNOWN REMAINING FLAW (08-27, 2nd confirmation): the universe re-resolves
  only when the MAX-OI strike M moves, and max-OI is sticky while spot is not.
  On 08-27 legs froze at 77500 while Sensex fell to 77182 — nothing near the
  money for two hours. Anchor to SPOT, but re-backtest evaluate_day_e2() first.
  ***  [USER][UNVAL]

V2.5.20 [2026-08-26] *** KITE RETIRED — UPSTOX MIGRATION ***
  All bots moved to Upstox behind a drop-in Kite-compatible shim
  (upstox_kite_shim.py). Long-lived read-only token, no daily login; launchers'
  auto_login removed. Candle/quote/OI parity verified live pre-deploy.
  *** REGRESSION FOUND 08-27: zero [STALE] events in ~37 Kite days, 50 on the
  FIRST Upstox day. CAUSE (corrected 08-29): the shim asks the intraday
  endpoint for 15-MINUTE candles, and that endpoint is built around COMPLETED
  intervals, so the forming bar appears 0-6 min late; Kite returned the partial
  bar from the first tick. Upstox is NOT slower — its 1m/tick data is as fast.
  Wrong endpoint granularity, not a vendor fault. Real fix = fetch 1m and
  resample to 15m in the shim (raising the 16-min guard is the WRONG fix: it
  would let the engines read a 30-45 min old iloc[-2] silently). ***  [FIX]

V2.5.20 [2026-08-26] EXP2W = EXP2 + the user's "was-expensive" SELECTION filter,
  run as a PARALLEL tag beside plain EXP2 — same legs, same data, same exits, so
  the two isolate the filter's effect. In-sample replay: NIFTY -3,308 -> +1,873,
  SENSEX +2,970 -> +2,552, ~60% fewer trades.
  *** LIVE A/B DATA POINT #1 (08-27): EXP2W DECLINED the day's only winner
  (77100PE, afternoon high 46.95 < the Rs130 floor) — cost Rs3,378. n=1, against
  the filter. Do not act on one day. ***  [USER][BT-insample]

V2.5.20 [2026-08-26] SENSEX bot given its own Telegram bot/chat; Nifty chat
  unchanged.  [USER]

V2.5.20-SENSEX [2026-08-23] *** SENSEX PORT CREATED ***
  Port of ORION_PAPER_V2_5_20.py to SENSEX/BFO. Lot size 20, BFO exchange,
  THURSDAY expiry, engine thresholds scaled x3.3 for Sensex's larger point
  scale — the x3.3 scaling is UNBACKTESTED, forward paper is its validation.
  Every entry ABOVE this line dated before 2026-08-23 was inherited from the
  Nifty bot at port time, not applied separately here.
  First live run 08-24 confirmed end-to-end: booted 09:06, traded, +Rs1,271.
  [USER][UNVAL]

V2.5.20 [EXP12 UNIVERSE ANCHORED TO SPOT — 2026-08-29]  (item 4)
  WHAT: EXP12_ANCHOR = 'spot'. _exp12_resolve_m() now returns the strike
  NEAREST SPOT instead of the max-OI strike among ATM+/-4. Max-OI is still
  computed and logged when it diverges, so the failure mode stays visible.
  Set EXP12_ANCHOR='maxoi' to revert the behaviour without touching code.

  WHY: max-OI is sticky, spot is not. 08-25 (Nifty) and 08-27 (Sensex: legs
  frozen at 77500 while spot fell to 77182, >200pt below the lowest leg) both
  left BOTH engines with no near-the-money contract for hours. The 5-minute
  re-resolve added 08-25 only swapped legs when M moved, so it never fired.

  BACKTEST (this gate was NOT skipped — the 08-27 note said re-backtest first):
  40 recent Nifty expiries, real Upstox 1-min premiums.
  *** The existing step12/step16 datasets could NOT answer this: they contain
  ONLY the 3 max-OI-anchored strikes per day, i.e. only the strikes the flawed
  rule already picks. A WIDE 11-strike band was pulled specially
  (exp_wide_universe_data.json) via the Expired Instruments API. ***
    GATE G1 baseline reproduced EXACTLY: max-OI n=26, +Rs12,760 (published)
    A max-OI x3          n=26  WR 46.2%  +Rs12,760  median day  -Rs29
    C spot x3 @14:30     n=29  WR 51.7%  +Rs13,959  median day +Rs111
                         -> 3 days better, 0 WORSE, 21 unchanged
    B spot re-anchored   n=32  WR 53.1%  +Rs18,242  5 better, 1 worse
  Live behaviour sits between C and B (legs re-resolve every 5 min).

  OUT-OF-WINDOW (older 57 expiries 2024-10..2025-11, the regime where E2 is
  known to LOSE). Question was not "does E2 work there" -- it does not -- but
  "does spot anchoring make it WORSE". It does not:
    A max-OI x3  n=40  WR 35.0%  -Rs3,958
    C spot x3    n=43  WR 37.2%  -Rs2,954   (2 days better, 1 worse)
    B re-anchor  n=44  WR 36.4%  -Rs3,162
  CAVEAT, stated rather than buried: this OOS baseline is -Rs3,958 against the
  published -Rs4,910. The Expired-Instruments API returned NO contracts for 1 of
  the 57 days and only 15 of 22 for another, so the OOS run covers 56 days with
  some gaps. Treat the OOS numbers as DIRECTIONAL. The recent-40 window, which
  is what this change is justified on, reproduced its baseline EXACTLY.

  HONEST READING: the in-sample gain is SMALL (+Rs1,199 at equal breadth)
  because max-OI and spot-ATM usually COINCIDE — they differed on only 3 of 24
  traded days. This change is not an edge improvement; it removes a blind spot
  in the tail. Its value is that at equal breadth it was never worse on any of
  the 40 expiries, and the two live misses are exactly the case it fixes.

  REVERT: *_BACKUP_20260829_pre_spot_anchor.py, or EXP12_ANCHOR='maxoi'
  STATUS: applied 2026-08-29. Confirm on the next expiry that the log shows
  "[EXP12] anchor=spot M=..." and that legs track spot.  [BT][USER]

V2.5.20 [EXPIRY REPORTING + INTRADAY BAR FIX — 2026-08-29]
  Four changes, all from the user's 2026-08-27 review. NO entry/exit RULE was
  changed — these are data-plumbing and reporting only.

  (1) SHIM 1-MINUTE RESAMPLING (item 3). upstox_kite_shim.historical_data() now
      builds TODAY's 5m/15m/1h bars from 1-MINUTE intraday instead of asking the
      intraday endpoint for them directly, because that endpoint only emits a
      forming bar 0-6 min late and the engines read iloc[-2] assuming iloc[-1]
      is the forming bar. Deliberately NOT raising the 16-min stale guard —
      that would hide stale indicators instead of surfacing them.
      52/52 instrument-day-interval combos reproduce Upstox's own O/H/L/C/vol/OI
      EXACTLY. See upstox_kite_shim.py CHANGE_HISTORY.  [FIX]

  (2) EXPIRY "WHY / WHY NOT" TELEGRAM at 15:29 (item 5). User: "no message about
      why a trade was not taken". Every EXP12 gate now increments a counter
      (_exp12_block) and records the closest miss (_exp12_near);
      _exp12_eod_report() sends one consolidated per-engine message. On the
      08-27 book this renders as "EXP2: no trade — blocked by spot too far from
      strike x148 ... closest: 77400CE prem 12.30 OK but dist -318", which is
      the universe flaw made visible.  [USER]

  (3) EXP12 TELEGRAM COLOUR + SHADOW TAG (item 7a). Entries/exits were plain
      🎯/⚫ with no green/red, so a +Rs3,378 day on 08-27 read like nothing had
      happened. Now 🟢/🔴 by CE/PE, 🟩/🟥 by result, and a persistent
      "⚫ SHADOW BOOK (not in main PnL)" tag.  [USER]

  (4) SHADOW TOTAL IN THE EOD SUMMARY (item 7b). EXP12 is a separate book (own
      lot size, own CSV) and stays EXCLUDED from Net PnL — but it is now printed
      as its own clearly-labelled block, so 08-27's "Rs0" on a +Rs3,378 day
      cannot recur. The two totals are visible without ever being mixed.  [USER]

  REVERT: *_BACKUP_20260829_pre_changelog_backfill.py (and, for the shim,
          upstox_kite_shim_BACKUP_20260829_pre_1m_resample.py)
  STATUS: applied 2026-08-29 (Sat, market closed). Item (1) is offline-verified
          only and MUST be confirmed against the live feed at the next open:
          [STALE] events should drop to zero. Items (2)-(4) are cosmetic/report
          paths and are proven by rendering tests, but (2) only fires on an
          expiry day — next Nifty expiry Tue 2026-09-01.

V2.5.20 [FLIGHT-RECORDER LOG FIX — 2026-08-29]
  WHAT : logging.basicConfig(filename=LOG_FN) -> logging.handlers.
         WatchedFileHandler(LOG_FN). One handler swap in the LOGGING block;
         added `import logging.handlers`. No engine/strategy code touched.
  WHY  : every Nifty & Sensex FlightRecorder *.log had been BOOT-BANNER-ONLY
         for ~a week (08-20 -> 08-28): 32,891 bytes, last line 8 seconds after
         boot, while the BarLevel CSV ran to 15:25. push_logs_to_github() runs
         `git rebase --autostash` every 5 min; with a dirty tree the autostash
         push/pop deletes and recreates every modified tracked file, including
         the log being written. The plain FileHandler held its fd on the old
         inode, so all later lines went to an orphaned inode. This is why the
         "check the Thursday log" instructions left for EXP2W / EXP12-relax /
         Upstox were all uncheckable. Real record was ~/orion_*_run.log (stdout).
  EVIDENCE : reproduced against a REAL two-bot `git rebase --autostash` cycle
         (scratchpad/wfhtest/repro3.py): FileHandler -> on-disk log holds ONLY
         the boot banner (inode swapped mid-run); WatchedFileHandler -> all
         lines through EOD survive the identical swap. Control that confirms
         the diagnosis in production: stocks_run.log is NOT git-tracked, is
         never touched by the push, and is complete through 15:30 IST on the
         same sessions. csv_append() and the Telegram fallback log open by
         name per write and were never affected.
  NOT DONE : dropping --autostash. It was added 2026-07-27 to fix a different
         failure (365+ push rejects/day since 07-20). Do not remove it.
  REVERT : ORION_PAPER_V2_5_20_BACKUP_20260829_pre_watchedfilehandler.py /
           ORION_SENSEX_V2520_BACKUP_20260829_pre_watchedfilehandler.py
  STATUS : code-applied 2026-08-29 (Sat, market closed). NOT yet proven live —
           confirm on the next session's boot that the FlightRecorder log keeps
           growing past 09:07 and its last line is ~15:25, not ~09:02.

=== REJECTED DECISIONS (DO NOT RE-ADD WITHOUT NEW BACKTEST EVIDENCE) ===
  SKIP_HOUR_13         : -Rs 46k (kills profitable flips in that window)
  SKIP_TUESDAYS        : +Rs 56k but calendar-overfit; RSI gate replaces
  ADX<20 filter        : -Rs 16k
  ADX<25 filter        : -Rs 34k
  BE armor at +15%     : net negative
  Same-side flip       : -Rs 191k CATASTROPHIC
  REVERSAL_FLIP=True   : WR 12% vs 33%
  K cap on CE          : hurts WR (no cap is better)
  V2.5.10 macro SMA50  : -Rs 2.3L vs V2.5.9; lagging filter blocked PE in bear phases
  V2.5.11 straddle halt: straddle expansion days WR 69.8% > normal 66.9%;
                         halting on expansion removed profitable trades (+Rs 2,54,234 phantom)
"""
CODE_FINGERPRINT = "259e938bc349aa6b9f4c4f09b48cb97a74627b8f4a08169a03ea461af18ac9c6"


# =========================================================================
# UNDOCUMENTED-CHANGE GUARD (2026-08-29)
# =========================================================================
# The CHANGE_HISTORY banner above went 24 changes / 10 weeks out of date
# (V2.5.19 06-21 -> 08-27) because nothing ever failed when it wasn't updated.
# This makes that impossible to do SILENTLY.
#
# CODE_FINGERPRINT is a sha256 of this file with two regions excluded: the
# CHANGE_HISTORY literal itself and the CODE_FINGERPRINT line (otherwise
# stamping the hash would change the hash). So it fingerprints the EXECUTABLE
# code only. Edit any logic without re-stamping and the boot check screams on
# Telegram. Deliberately mtime-independent -- git checkout/clone/stash rewrites
# mtimes constantly in this repo, which would make an mtime check cry wolf.
#
# WORKFLOW after ANY code edit:  python3 stamp_changelog.py
# It refuses to stamp unless CHANGE_HISTORY carries an entry for today.
def _orion_code_fingerprint(path=None):
    """sha256 of this file's executable code (CHANGE_HISTORY + stamp excluded)."""
    import hashlib, re as _re
    p = path or os.path.abspath(__file__)
    src = open(p, encoding="utf-8").read()
    src = _re.sub(r'CHANGE_HISTORY = """.*?\n"""\n', "", src, count=1, flags=_re.S)
    src = _re.sub(r'^CODE_FINGERPRINT = ".*?"\n', "", src, count=1, flags=_re.M)
    return hashlib.sha256(src.encode("utf-8")).hexdigest()


def _orion_changelog_newest_date():
    """Newest YYYY-MM-DD appearing in CHANGE_HISTORY."""
    import re as _re
    # Header lines only (e.g. `V2.5.20 [... 2026-08-29]`). Scanning every date in
    # the block reported dates merely MENTIONED in prose as the newest entry.
    h = _re.findall(r"^\S+ \[[^\]]*?(20\d\d-\d\d-\d\d)[^\]]*\]",
                    CHANGE_HISTORY, _re.M)
    if h:
        return sorted(h)[-1]
    d = sorted(set(_re.findall(r"20\d\d-\d\d-\d\d", CHANGE_HISTORY)))
    return d[-1] if d else "none"


def check_changelog_current():
    """Boot check. Returns (ok, message). Never raises -- must not block a boot."""
    try:
        actual = _orion_code_fingerprint()
        if actual == CODE_FINGERPRINT:
            return True, f"[CHANGELOG] up to date (last entry {_orion_changelog_newest_date()})"
        return False, (
            "UNDOCUMENTED CHANGE — this file's code does not match the last "
            f"stamped fingerprint.\nNewest CHANGE_HISTORY entry: {_orion_changelog_newest_date()}\n"
            f"stamped={CODE_FINGERPRINT[:12]} actual={actual[:12]}\n"
            "Someone edited the logic without recording it. Run stamp_changelog.py.")
    except Exception as e:
        return True, f"[CHANGELOG] check skipped ({e})"

# =========================================================================
# CONFIG
# =========================================================================
VERSION = "V2.5.20-SENSEX"
MODE    = "LIVE"    # LIVE  -> real orders via mStock API
# =========================================================================
# V2.5.20 (2026-07-06): rebuilt per the concurrent-backtest architecture (see
# orion_backtest_lab/code/orion_concurrent_engine.py). Five strategies --
# BASE (FLIP+V2+V3), VWAP, FUT5VWAP, ORB (new, opening-range-break), GAPBREAK
# (new, gap-day range-break) -- now run as five FULLY INDEPENDENT positions,
# not a single shared position arbitrated by priority. No flip cap, no
# momentum/fade gate, no same-direction cooldown (the backtest that validated
# this design never modeled those live-only gates -- running them live on top
# would diverge from what was actually tested). Entries close at 15:00 IST
# (was 15:16). FUT5VWAP's exit changed from a fixed +12 target to a
# touch-30-stop + lock-4-and-ride (validated: -25.52 -> +545.25 pts in the
# 439-day combined backtest).
# LIVE since 2026-07-06 (explicit go-ahead): EXECUTION_BROKER="mstock_live",
# LOTS_PER_TRADE=2, real orders on Amol's own mStock account only (not any
# customer mirror). A GLOBAL circuit breaker (CIRCUIT_BREAKER=4 total losses
# across all 5 engines combined, see TOTAL_LOSSES_TODAY) halts all new
# entries for the rest of the day if tripped -- added specifically as the
# real-money safety net before this went live. /live command stays disabled
# (see _cmd_live) so it can't be re-toggled by anyone with Telegram access;
# /paper is still reachable in-process but inbound polling is off (see
# main()), so in practice only a code change / restart flips broker mode.
# =========================================================================

# ---- Execution broker ----
# "kite_paper"   : paper mode, no real orders (current default)
# "mstock_live"  : live orders via mStock API (activate when going live)
EXECUTION_BROKER = "kite_paper"  # 2026-07-20: switched LIVE->PAPER on explicit user instruction (no real orders)
LOT_SIZE = 20
LOTS_PER_TRADE = 1  # reduced from 2 -> 1, explicit user instruction 2026-07-07
# 2026-07-12 (explicit user instruction, effective Monday 2026-07-13 boot):
# per-engine lot sizing -- FUT5VWAP (best-proven engine: +323.55pts/94.1%WR on
# the real 38-day review AND +545.25 on the 439d backtest) trades 3 lots; every
# other engine stays at LOTS_PER_TRADE (1). Keyed by POS.engine at order time
# ('FUT5VWAP' for that slot; BASE slot trades carry 'V2'/'V3'/'FLIP' -> default).
# 2026-08-29: FUT5VWAP cut 3 -> 1 lot on user instruction ("is it working
# fine, if not reduce to 1 lot"). It is not. Live record 07-06..08-28:
#   18 trades, 78% win rate, but net -42.88pt = -Rs8,362 at 3 lots.
# The win rate is misleading -- wins are capped at the +4.00pt LOCK_FLOOR
# while losses ran the full -30.00pt stop, so it needs an 84.5% win rate
# just to break even and is running 77.8%. All 4 losses predate the 08-17
# stop tightening (30->25pt), and only 2 trades have closed since, so the
# fix is UNPROVEN (n=2) -- which is exactly why it should not carry 3x size.
# Revert: *_BACKUP_20260829_pre_fut5_1lot.py
LOTS_PER_ENGINE = {"FUT5VWAP": 1}

# 2026-08-29: CE-side control. Measured over 91 sessions / 262,911 CE
# option-minutes: buying a CALL has EV -1.067 pts, 95% CI [-2.179, -0.192].
# The CI EXCLUDES ZERO, so this is an ESTABLISHED loser -- the single most
# solid statistical result of the 08-29 option study. Buying a PUT is -0.088
# (CI includes zero = roughly break-even). About half of every engine's
# trades are calls, and that half carries the measured loss.
#
# HALF-SIZING WAS TRIED AND IS A NO-OP: every engine is at 1 lot (user rule),
# and max(1, round(1*0.5)) == 1. At 1-lot sizing this is BINARY: trade calls
# or do not. Left ENABLED by default because disabling halves trade count and
# the user explicitly wants trades firing, and because the PE-minus-CE
# difference CI still includes zero -- only the CE loss is established, not
# the asymmetry. Flip the one flag to act on it.
#   CE_BUY_ENABLED = False  -> no CE entries on any engine, both bots
CE_BUY_ENABLED = True

def lots_for(engine: str, side: str = "") -> int:
    return LOTS_PER_ENGINE.get(engine, LOTS_PER_TRADE)
IST = pytz.timezone("Asia/Kolkata")

# ---- Entry params ----
# V2 (T10 indicator) entry
STOCHRSI_LEN          = 14
STOCHRSI_RSI_LEN      = 14
STOCHRSI_K_SMOOTH     = 3
STOCHRSI_CE_LO        = 38      # CE: K >= 38 (rising)
STOCHRSI_PE_HI        = 80      # PE: K <= 80 (falling)
SMA_FAST_1H           = 20
SMA_SLOW_1H           = 50
# V2.5.1: V2 PE floor and CE cap
V2_K_FLOOR_PE         = 25      # PE also requires K_now >= this
V2_K_CAP_CE           = None    # CE cap: None = no upper cap
# V2.5.8: K extreme filter — entry only if K was recently extreme
K_EXTREME_BARS        = 3       # look back this many 15m bars
K_OVERSOLD_THRESH     = 25      # CE: K must have been below this recently
K_OVERBOUGHT_THRESH   = 75      # PE: K must have been above this recently
# V2.5.9: RSI directional gate (replaces old chop filter [47,53] band)
RSI_CE_MIN            = 53      # CE: 1h RSI must be above this
RSI_PE_MAX            = 47      # PE: 1h RSI must be below this
# 2026-07-12: best combo from real-30-day grid search (k_extreme=True, rsi_gate=True,
# macd_align=False -- 7 trades/71.4% win/+45.96pts on 2026-05-15..2026-07-10). MACD
# gate toggled OFF per that result. Applied on user's explicit order despite thin
# 7-trade sample (see memory orion-v2-best-combo-real30d-2026-07-12.md). Flip back to
# True to restore prior MACD-gated behavior.
V2_MACD_GATE_ENABLED  = False
# V2.5.9: Premium entry gate (asymmetric: PE spikes higher during panic moves)
PREMIUM_MIN           = 100      # skip if option LTP < this (deep OTM)
PREMIUM_MAX_CE        = 600     # CE cap: IV spikes are less common on upside
PREMIUM_MAX_PE        = 1000     # PE cap: raised to capture panic/downside moves (was 180)
PREMIUM_MAX           = 600     # legacy alias — not used for entry (use side-specific caps)
# V2.5.14 VWAP triple confirmation engine (FUT primary + SPOT + option)
VWAP_BODY_MIN_PCT     = 0.65    # Backtest-calibrated: 65% body filter cuts whipsaw days (sweep2 ₹98k, 13/14 green)
VWAP_ENGINE_ENABLED   = True    # enable VWAP triple confirmation signal
# 2026-08-08: same-day loss cap, added per real 3-month simulated backtest (Upstox
# real premiums, see memory orion-v2520-step3-daytype-engine-crosstab-2026-08-08.md).
# VWAP has no re-entry throttle -- on whipsaw/"first-1h-move-then-sideways" day-types
# it keeps re-firing on every FUT 15m/VWAP cross and eating a fresh HARDSL_-18pct
# each time (worst case found: 6 re-entries in one session, 5 stopped). The GLOBAL
# circuit breaker (CIRCUIT_BREAKER=4 total losses across ALL engines) doesn't catch
# this reliably -- other engines' wins/losses dilute it, and in paper mode a halt
# only flags entries paper-only rather than blocking them. This is a VWAP-specific
# stop: once VWAP alone has lost this many times today, no further VWAP entries
# (existing open positions still manage exits normally). Day-type-linked, NOT a
# structural fix like PIVOTBREAK's disable or FUT5VWAP's stop:lock ratio.
VWAP_DAILY_LOSS_CAP   = 2

# 2026-08-20: two new VWAP-specific gates, both from a real 40-trade backtest
# on the live 2026-07-07->08-20 log (see memory
# orion-v2520-vwap-live-filters-deployed-2026-08-20). Neither alone made VWAP
# net-profitable in that backtest -- they cut its total loss by ~69% (-Rs11,522
# -> -Rs3,594) by removing whipsaw entries, not by finding a hidden edge. Ship
# with that expectation, watch live, don't assume "fixed".
#
# GATE 1 -- 1-min(-equivalent) persistence + distance filter: the existing
# check_vwap_signal only requires the 15m FUT candle to CLOSE on one side of
# FUT-VWAP with 65-86% body -- it says nothing about whether price actually
# held that side beforehand, so a candle can whipsaw across VWAP intraminute
# and still fire. Using 5m FUT bars (already fetched every cycle, no new API
# calls) as a proxy for finer resolution: require the last VWAP_PERSIST_BARS
# CLOSED 5m bars to all sit on the signal side of the 5m FUT-VWAP, AND the
# latest close to be >= VWAP_DIST_MIN_PTS away from that VWAP (not a marginal
# graze). Fails OPEN (allows the trade) if 5m data is insufficient -- same
# convention as every other gate in this file (momentum_gate_ok etc), so a
# data hiccup never silently blocks all VWAP entries.
VWAP_PERSIST_GATE_ENABLED = True
VWAP_PERSIST_BARS     = 2      # last 2 closed 5m bars = 10 min
VWAP_DIST_MIN_PTS     = 26.0    # FUT close vs FUT-VWAP, points

# GATE 2 -- post-loss same-side cooldown: after a VWAP loss on a side, block a
# VWAP re-entry on that SAME side for this many minutes (existing open
# positions unaffected; opposite-side entries unaffected). Targets the re-fire
# mechanism directly (VWAP has no regime filter and dedups only per-bar, not
# per-loss) -- this is what actually produced the 07-22-style 3-same-side-
# entries-in-3-hours pattern. Separate from the generic, currently-disabled
# SAME_DIR_REENTRY_GUARD (that one fires on ANY exit, not just VWAP losses,
# and is off "for backtest fidelity" -- this one is VWAP-only and loss-only).
VWAP_LOSS_COOLDOWN_ENABLED = True
VWAP_LOSS_COOLDOWN_MIN = 30

# 2026-08-16: V2 same-day loss cap. Real 3mo re-port of V2's own logic (2026-05-04->
# 08-06, see orion-notrade-zone-design-attempts-2026-08-16 memory) found the two
# real loser day-types (trend-burst-then-reversal, first-1h-then-sideways) don't just
# lose once -- V2 gets whipsawed repeatedly on them same-day. Capping at 1 loss/day
# improved the 3mo total from +Rs10,589 to +Rs14,080 (+33%). Small sample (9 multi-
# trade days out of 25 total V2 trades) -- not forward-validated live, watch closely.
V2_DAILY_LOSS_CAP     = 1
V2_LOG_ONLY           = True    # 2026-09-29: V2 signals logged (after all gates), NOT traded -- see CHANGE_HISTORY
V2_SHADOW_LOG         = '/home/selukar_amol123/Amol/v2_shadow/sensex_v2_shadow.jsonl'

# --- V2.5.19 THREE FUT-VWAP ENTRY PATHWAYS (2026-06-21, NOT YET BACKTESTED) ---
# Feature 1: FUT 15m VWAP cross now requires a confirmation candle (same dir)
VWAP15_CONFIRM_ENABLED = False  # 2026-06-24: confirmation candle REMOVED per user — fire on the FUT 15m VWAP cross bar itself (no waiting). Confirm candle was delaying entries into declining trends.
# Feature 2: FUT 5m VWAP cross + S/R distance, fixed +12 option-point target scalp
FUT5_SCALP_ENABLED     = True
FUT5_SCALP_BODY_MIN    = 0.65   # cross bar body >= this fraction of range
FUT5_SCALP_BODY_MAX    = 0.87   # and < this (skip >=87% climax bars, mirrors 15m band)
FUT5_SCALP_SR_MIN_DIST = 65.0   # FUT 5m close must be > this many pts from EVERY pivot S1/R1/S2/R2
FUT5_SCALP_TARGET_PTS  = 40.0   # FIXED target: exit at entry + this many OPTION points (no trail)
# Feature 3: morning 09:15-10:15 exception to the 09:45 entry-start gate
MORNING_VWAP_ENABLED   = True
MORNING_WIN_START_H     = 9
MORNING_WIN_START_M     = 15
MORNING_WIN_END_H       = 10
MORNING_WIN_END_M       = 15
MORNING_VWAP_SR_MIN_DIST = 65.0 # FUT 15m close must be > this many pts from EVERY pivot S1/R1/S2/R2
# V2.5.9: Straddle monitoring (informational Telegram alerts only)
STRADDLE_REF_MIN      = 20      # record ATM straddle reference after 9:20 AM
STRADDLE_MORNING_MIN  = 45      # morning straddle Telegram at 9:45 AM
STRADDLE_MIDDAY_HOUR  = 11      # mid-day straddle Telegram
STRADDLE_MIDDAY_MIN   = 30      # at 11:30 AM

# V3 (cluster) entry
CLUSTER_RADIUS_PTS    = 65
GRADE_A_MIN_SOURCES   = 3
GRADE_B_MIN_SOURCES   = 2
SWING_LOOKBACK_BARS   = 20
SWING_PIVOT_N         = 3
ROUND_STEP_FINE       = 100
ROUND_STEP_MAJOR      = 500
ROUND_RANGE_PTS       = 1000
GRADE_A_MIN_CLOSE_BEYOND = 50
GRADE_A_MIN_BODY_PCT     = 0.40
GRADE_B_MIN_BODY_PCT     = 0.60
GRADE_B_CLOSE_TOP_PCT    = 0.25
WICK_REJECT_MIN_PCT      = 0.50
WICK_REJECT_CLOSE_DIST   = 33
ADX_PERIOD            = 14
ADX_CHOP_MAX          = 20
ADX_TREND_MIN         = 25
T1_MIN_PTS, T1_MAX_PTS = 165, 330
# V2.5.3: promote singletons
V3_PROMOTE_SINGLETONS  = True
PROMOTE_ROUND_100_BAND = 660    # +/- pts from PDC for round_100 standalone promotion
PROMOTE_SWING_BAND     = ROUND_RANGE_PTS

# V2.5.6 — V3 PDC contamination fix
# Fix A: Exclude PDC from clustering sources (PDC is a reference, not a tradeable level)
# Fix B: Minimum buffer between G/R and PDC (avoid noise levels near current price)
# Validated 18-mo backtest: +Rs 13,127 (+3.52%), MaxDD -19%
V3_EXCLUDE_PDC_FROM_CLUSTERS = True
V3_MIN_BUFFER_FROM_PDC       = 80     # G must be >= PDC+25; R must be <= PDC-25

# V2.5.2: FLIP rule (opposite-side flip on 15m K reversal)
FLIP_ENABLED              = True
FLIP_PATH_A_ELAPSED_MIN   = 30    # min elapsed for Path A flip detection at exit
FLIP_PATH_A_PEAK_MIN_PTS  = 50    # peak must have reached entry + this
FLIP_PATH_A_DROP_MAX_PTS  = 33    # current LTP <= entry + this triggers Path A
FLIP_K_CE_TO_PE_MIN       = 25    # CE->PE flip: K_now >= this
FLIP_K_CE_TO_PE_MAX       = 80    # CE->PE flip: K_now <= this
FLIP_K_PE_TO_CE_MIN       = 38    # PE->CE flip: K_now >= this
MAX_FLIPS_PER_DAY         = 10**9  # V2.5.20: no cap on trades, per explicit instruction
FLIP_PATH_B_WATCH_MIN     = 60    # post-exit minutes to keep watching for flip

# ---- 2026-07-13: PUT-FLIP QUALITY GATE (same as V2.5.19) --------------------
# The CE->PE rule accepts ANY K decrement inside a 25-80 band = mid-range noise.
# On 2026-07-13 V2.5.19 flipped a winning CE into a PE on K 58.9 -> 58.4 (a 0.5pt
# tick) at the day's highs; that put died on HARDSL. Measured on 404 real FLIP
# trades / real premiums / 439d (results/flip_trigger_k_analysis.csv):
#     put-flip on |dK| < 2 : n=16,  -89.5 pts, 31% WR
#     put-flip with K > 60 : n=60, -243.0 pts (K80+ bucket 0% WR)
#     put-flip on |dK|>=10 : n=111, +476.8 pts, 55% WR
# Blocking both bad slices: +279.6 pts / Rs +18,175; train +120.7, TEST +158.9.
# Call-side flip is UNCHANGED (no equivalent edge found there).
FLIP_PUT_MIN_DK          = 2.0    # require |K - K_prev| >= this (no noise ticks)
FLIP_PUT_MAX_K           = 60.0   # and K <= this (don't buy puts from mid/high K)


def put_flip_ok(K, K_prev):
    """2026-07-13: quality gate for a CE->PE (put) flip. Returns (ok, reason)."""
    dK = K_prev - K
    if dK < FLIP_PUT_MIN_DK:
        return False, f"K fell only {dK:.1f} (< {FLIP_PUT_MIN_DK:.0f}, noise tick)"
    if K > FLIP_PUT_MAX_K:
        return False, f"K={K:.1f} > {FLIP_PUT_MAX_K:.0f} (too high to buy puts into)"
    return True, f"dK=-{dK:.1f}"


# ---- 2026-07-13: COUNTER-TREND VETO ----------------------------------------
# Nothing in this bot ever refused to buy the side the market was moving AGAINST.
# On 2026-07-13 the day's low printed at 09:15 and Nifty ran one-way to 24259;
# V2.5.19 still bought PE three times. Max favourable excursion after each entry
# was +6.7 / +3.7 / +20.8 spot pts -- no exit rule could have saved them, because
# the PE move was simply never given.
# Measured on 2070 real trades / 439d (results/trend_veto_analysis.csv), by where
# spot sat vs the SESSION VWAP at entry:
#     PE bought ABOVE vwap (fighting an uptrend)  : n=277, -120.7 pts, 32% WR
#     PE bought BELOW vwap (with the trend)       : n=847, +1265.7 pts, 47% WR
#     CE bought ABOVE vwap (with the trend)       : n=708, +1590.0 pts, 49% WR
#     CE bought BELOW vwap (fighting a downtrend) : n=238, -246.0 pts, 31% WR
# Both losing slices show up INDEPENDENTLY at ~31% WR -- a symmetric mechanical
# effect, not a fitted one. Buffer swept 0/5/10/15/20/30: ALL positive in BOTH
# halves of a chronological split (flat surface, not a knife-edge).
#
# BREAKOUT ENGINES ARE EXEMPT. On the concurrent 439d book (3696 trades,
# results/trades_concurrent_full439_regen.csv) the veto is strongly positive on
# the signal engines (BASE +573.6, VWAP +79.3, FUT5VWAP +63.2) but NEGATIVE on
# the breakout engines (ORB -12.6, GAPBREAK -45.7). That is mechanically right:
# ORB/GAPBREAK exist to fire the moment price breaks a range, and a genuine
# breakout often prints while spot is still the "wrong" side of a lagging session
# VWAP. Vetoing them just deletes real breakouts. Applying the veto to BASE/VWAP/
# FUT5VWAP only, on this book: +716.1 pts / Rs +46,547 over 439 days.
# Do NOT add the breakout engines without fresh validation.
COUNTERTREND_VETO_ENABLED = True
COUNTERTREND_VETO_BUFFER  = 16.0   # pts past VWAP before we call it counter-trend
COUNTERTREND_VETO_EXEMPT  = {"ORB", "GAPBREAK", "EXPIRY"}

# 2026-07-29: veto Telegram-alert dedup (ported from V2.5.19 same-day fix). Signal
# checks re-evaluate the same closed bar every LOOP_SLEEP_SEC without a bar dedup,
# so a persisting counter-trend condition re-vetoes and re-sends the identical
# Telegram message every cycle for up to one full bar. Throttle the ALERT only —
# every veto is still linfo'd.
VETO_ALERT_COOLDOWN_MIN = 15.0
_LAST_VETO_ALERT = {}  # (engine, side) -> datetime of last Telegram alert sent

# V2.5.5 chop filter removed in V2.5.9 — replaced by RSI directional gate in check_v2_signal

# ---- Universal exit ----
HARDSL_PCT            = 0.18    # V2.5.12: tightened -25% → -18% (VRL-inspired, confirmed backtest)
SMA_TRAIL_PERIOD      = 8       # SMA(8, low) on option 15m
SMA_TRAIL_MIN_BARS    = 4       # V2.5.16: min TODAY closed 15m bars (FALLBACK when entry_time unknown)
SMA_TRAIL_MIN_BARS_SINCE_ENTRY = 1  # V2.5.18: min of the trade's OWN closed 15m bars before SMA8 may fire
# V2.5.12 exit params: peak-based ladder, no time gate (18-month BT: ₹+6,88,158 WR 64.5% MaxDD -1119)
FIXED_TP_PTS          = 50      # Trail trigger: when LTP >= entry+15, start trailing
TRAIL_STEP_PTS        = 16       # Trail: SL = peak - 5 pts (ratchets up, never down)
TRAIL_FLOOR_PTS       = 33      # Trail floor: SL never below entry + 10 pts
# 2026-08-20: V2-specific trail, scaled to entry premium instead of fixed
# points -- see the usage site (step 3 of check_exits) for the full rationale.
# UNVALIDATED against V2 history (no per-cycle peak log exists for V2).
V2_TRAIL_ARM_PCT       = 0.15   # arm trail once peak >= entry*1.15
V2_TRAIL_STEP_PCT      = 0.05   # trail step, as a fraction of entry premium
V2_TRAIL_FLOOR_PCT     = 0.10   # floor never below entry*1.10
# 2026-08-20 user-directed: fixed-point stop replaces the generic -18% HARDSL
# for V2 only (paired with the trail-arm change above). NOT backtested.
V2_HARDSL_PTS          = 50.0   # V2 stop = entry - 15pt (was entry*(1-0.18))
                                # Backtest (corrected, > filter): ₹96,216 vs ₹68,578 fixed TP
                                # Same trades (64), same WR (82.8%), same 13/14 green days
                                # Manual cross-checked May-07/18/21 — exact match
CIRCUIT_BREAKER       = 4        # V2.5.20 LIVE: halt ALL 5 engines after 4 TOTAL
                                  # bot-driven losses across the combined book (not
                                  # per-engine) -- explicit instruction for going live
                                  # with real money. See TOTAL_LOSSES_TODAY below.
# --- V2.5.16 MOMENTUM GATE -------------------------------------------------
# 3rd+ consecutive same-direction entry requires real momentum, to stop the
# choppy-market "win-win-loss + keep buying same side" bleed. Backtest (May
# real-opt): baseline -7.3pt -> gate +104.0pt, no winners blocked.
MOM_GATE_ENABLED      = False   # V2.5.20: backtest never modeled this gate; disabled for fidelity (was True)
MOM_GATE_MIN_SAMESIDE = 3       # gate kicks in on the 3rd same-side entry & beyond
MOM_GATE_BARS         = 5       # look-back: net spot move over last N closed 1m bars
MOM_GATE_PTS          = 40.0    # require >= this many pts WITH the trade direction
MOM_GATE_V3_ENABLED   = True    # 2026-07-12: V3-only re-enable (diagnosis: blocks the single
                                 # worst trade in the 30-day sample, no downside found). Does
                                 # NOT touch MOM_GATE_ENABLED, which stays False for V2/FLIP.
# --- V2.5.20 V3 EARLY-ENTRY + FAST EXIT (2026-07-12 diagnosis) -------------
# Root cause: V3's BREAK detector on a full 15m-close bar was a literal 50%
# coin flip; the real fix is (a) fire earlier, on the partial bar, and
# (b) exit fast instead of holding. Real 5m/28-day test: 10-min partial-bar
# entry = +8.96pt avg favorable move in 1h vs +2.50pt waiting for full close;
# fast +10/-8pt target/stop flips V3 net loser -> net winner (see
# ~/orion_analysis/v3_level_diagnosis/EARLY_ENTRY_RESULTS.md).
V3_EARLY_ENTRY_ENABLED = True
V3_FAST_EXIT_ENABLED  = True
V3_FAST_TARGET_PTS    = 33.0    # option-premium points, mirrors validated +10pt spot target
V3_FAST_STOP_PTS      = 26.0     # option-premium points, mirrors validated -8pt spot stop
# --- V2.5.20 V3 PROBE ENTRY (2026-07-12 real-option-premium test) ----------
# Real 38-day per-strike option-premium test of the user's probe mechanic
# (not spot proxy): instead of buying V3 at market on signal, place a
# resting LIMIT buy at (signal LTP - V3_PROBE_PULLBACK_PTS); fill only if
# price pulls back to it within the window, then run the same +10/-8 fast
# exit from the fill price. Filled-only result, ALL grades (A+B), n=38:
# +1.67pt avg, 52.6% win, +Rs4,121/38days (50.7% fill rate) -- POSITIVE,
# unlike the confirmation re-entry leg which was a net loser on Grade-B (see
# ~/orion_analysis/v3_level_diagnosis/OPTION_PROBE_REENTRY_RESULTS.md).
# User explicit instruction 2026-07-12: replace the OLD market-entry V3
# logic with this probe entry, Grade A+B both eligible (no A-only
# restriction) -- this REPLACES the plain market-entry path, it does not
# add a separate re-entry leg (that piece stays out, per the test's finding).
V3_PROBE_ENABLED         = True
# 2026-08-29: 26.0 -> 13.0. SENSEX filled 0 of 8 probes live (NIFTY managed
# 13 of 30). A 26pt pullback on SENSEX premiums simply never traded, so every
# V3 signal the engine produced was thrown away. Halved, same as NIFTY's 8->4.
V3_PROBE_PULLBACK_PTS    = 13.0   # limit buy = signal LTP - this
V3_PROBE_FILL_WINDOW_MIN = 25    # limit stays live this long (was 15)
# --- V2.5.17 CHOP-BLEED GUARDS ---------------------------------------------
# #2 VWAP body band: keep the >=65% min (VWAP_BODY_MIN_PCT above); skip climax.
VWAP_BODY_CLIMAX_PCT  = 0.87    # >= this body% = climax/exhaustion bar -> skip (take 65-86% band)
# #1 Morning chop gate: decide once, stand aside for the day if the open is boxed/whippy
CHOP_GATE_ENABLED     = True
CHOP_GATE_DECIDE_MIN  = 75      # minutes after 09:15 to decide (75 = 10:30 IST, ~4 closed 15m bars)
CHOP_FH_END_MIN       = 60      # first-hour window = first 60 min from 09:15 (-> 10:15 IST)
CHOP_ER_MAX           = 0.25    # early efficiency ratio <= this = directionless
CHOP_VWAP_CROSSES_MIN = 3       # >= this many FUT-VWAP crosses in the first hour = whippy
CHOP_RANGE_PT_MAX     = 360.0   # first-hour FUT range < this = compressed (median-chop proxy)
# #1b V2.5.18 chop-gate RE-ARM: release the stand-aside when FUT breaks the recorded
#     first-hour range decisively in the regime direction (FUT leads spot = earlier trigger).
CHOP_REARM_ENABLED    = True
CHOP_REARM_BUFFER_PT  = 50.0    # FUT 15m close must clear FH hi/lo by >= this many pts
CHOP_REARM_BODY_MIN   = 0.65    # decisive break bar: body >= this fraction of bar range
# #3 Momentum-fade gate: 3rd+ same-side entry after >=2 same-side wins must pass a 3m option-decay check
FADE_GATE_ENABLED     = False   # V2.5.20: backtest never modeled this gate; disabled for fidelity (was True)
FADE_MIN_PRIOR_WINS   = 2       # arms only after this many consecutive same-side WINS
FADE_OPT_TF           = "3minute"
FADE_OPT_BARS         = 3       # net option move over last N closed 3m bars
FADE_DECAY_PT         = 0.0     # tolerance band around flat (pts) for "decaying"/"not decaying"
# Same-direction re-entry cooldown (added 2026-06-23). The momentum/fade gates only
# arm on the 3rd+ same-side entry; they let through a near-immediate same-side re-entry
# right after an exit (e.g. 2026-06-23: PE win +42 -> PE re-entry 33s later -> HARDSL).
# This blocks ANY same-side re-entry within N minutes of the last exit on that side,
# regardless of engine or win/loss. FLIP is opposite-side only, so it is never blocked.
SAME_DIR_REENTRY_GUARD       = False  # V2.5.20: backtest never modeled this gate; disabled for fidelity
SAME_DIR_REENTRY_COOLDOWN_MIN = 5
FORCE_CLOSE_HOUR      = 15
FORCE_CLOSE_MIN       = 25

# ---- Trade window ----
ENTRY_START_HOUR      = 9
ENTRY_START_MIN       = 45     # earliest entry after open
ENTRY_END_HOUR        = 15
ENTRY_END_MIN         = 0      # V2.5.20: entries close at 15:00 IST for every strategy (was 15:16)
GAP_SUPPRESS_PCT      = 0.01
GAP_SUPPRESS_UNTIL_HOUR = 10
GAP_SUPPRESS_UNTIL_MIN  = 15

# =========================================================================
# V2.5.20 NEW: ORB (opening-range-break) + GAPBREAK (gap-day range-break)
# strategies, ported verbatim from orion_backtest_lab's validated backtest
# (code/orion_backtest_v2_5_19.py / code/orion_concurrent_engine.py). Both are
# real-premium-only (no synthetic BS fallback), 09:15-anchored, own touch-stop
# + lock-and-ride exit, one same-strike opposite-side flip on stop.
# =========================================================================
ENGINE_LIST = ["BASE", "VWAP", "FUT5VWAP", "ORB", "GAPBREAK", "EXPIRY"]
# 2026-07-20 (paper): unlimited-overlap for the legacy engines. Each engine gets N-1 extra
# POSITION SLOTS that share the engine's day-state (so signal-dedup stops clone-storms and closed
# trades still append to the one shared trades_today list = P&L stays correct). Only the intraday
# re-signalling engines get slots (ORB/GAPBREAK fire once/day). SLOT_LIST drives the exit/entry
# dispatch; ENGINE_LIST (base only) still drives all day-state/PnL loops. ROLLBACK = set to 0.
# 2026-08-29: 4 -> 0. Measured over all 165 live trades: stacked positions have
# the SAME per-trade expectancy as single ones (+0.68pt vs +0.74pt), so the extra
# slots add NO edge -- they only multiply size and variance. 24 of 40 stack events
# ended worse than the first slot alone; net cost Rs2,261; the tails are what did
# the damage (07-23 stacked 4x into 24000CE for -Rs7,248 where one slot lost
# Rs1,398; 08-13 stacked 7x for -Rs7,213 vs -Rs959). Dedup is per-BAR only, so
# nothing ever checked whether that strike was already open -- 08-28 bought
# 24100PE twice 14 min apart and stopped both, -Rs1,739 instead of -Rs875.
# It also quietly broke the standing 1-LOT rule: VWAP could hold 5 lots at once.
# Revert: *_BACKUP_20260829_pre_overlapslots.py
LEGACY_OVERLAP_SLOTS = 0                       # extra concurrent positions per eligible engine
_OVERLAP_ENGINES = ["BASE", "VWAP", "FUT5VWAP"]
SLOT_LIST = []
for _e in ENGINE_LIST:
    SLOT_LIST.append(_e)
    if _e in _OVERLAP_ENGINES:
        SLOT_LIST += [f"{_e}#{_i}" for _i in range(1, LEGACY_OVERLAP_SLOTS + 1)]

ORB_OR_START_MIN     = 555     # 09:15 in minutes-since-midnight
ORB_OR_END_MIN       = 561     # exclusive -> 09:15..09:20 (6 x 1m bars)
ORB_ENTRY_START_H, ORB_ENTRY_START_M = 9, 25
ORB_ENTRY_END_H, ORB_ENTRY_END_M     = 15, 0
ORB_SQOFF_H, ORB_SQOFF_M             = 15, 15
ORB_FLIP_CUTOFF_H, ORB_FLIP_CUTOFF_M = 14, 30
# 2026-08-20 user-directed tightening, triggered by the 08-20 live trade
# (entry 143.20, peak 195.85 = +52.65pt, but ride-trail needs +65 to arm --
# never engaged, floor stayed frozen at the flat +25 lock, gave back the
# whole 27.65pt above it, exited ORB_LOCK_FLOOR @168.20). Not backtested
# against history before shipping -- single live incident + explicit user
# direction. IMPORTANT: floor = max(LOCK_PTS, peak-entry-giveback) -- giveback
# only has an effect once (peak-entry) exceeds (LOCK_PTS+giveback). The first
# version of this change (trigger 40/giveback 35) was VERIFIED WRONG: with
# lock=25, giveback=35 needs peak-entry>60 to do anything, and today's peak
# was only +52.65, so it would have produced the IDENTICAL 168.20 exit -- no
# improvement at all. giveback=20 is the number that actually changes today's
# outcome (would have locked +32.65 instead of +25, exit 175.85 not 168.20).
# Watch the next several ORB trades before trusting these numbers; revert if
# giveback/win-rate gets worse, not just if one trade looks bad.
ORB_STOP_PTS         = 30.0    # 2026-09-28: 50 -> 30 (tight SL on loser engines, see CHANGE_HISTORY); was 30.0 before 50
ORB_LOCK_PTS         = 57.6    # 2026-08-31: was 80.0. Proportional to NIFTY 25->18 at the existing 3.2x index scaling (18 * 80/25).
ORB_RIDE_TRIGGER_PTS = 130.0    # was 65.0 -- so a +52.65pt-type peak now arms the ride
ORB_RIDE_GIVEBACK_PTS= 65.0    # was 50.0 (corrected from an initial 35 that math-checked to zero effect)
ORB_PREM_MIN, ORB_PREM_MAX = 66.7, 1000.0
# 2026-09-02: FLIP-ON-STOP floor ONLY (see the NIFTY file for the full rationale).
# 66.7 = proportional carry of NIFTY's 20.0 at this port's 3.333x scaling. NOTE:
# the replay behind this was NIFTY-ONLY -- there is NO SENSEX evidence for it,
# exactly as with the 08-31 lock-arm carry. Entry floor stays 200.
ORB_FLIP_PREM_MIN = 66.7
ORB_STRIKE_STEP          = 100
ORB_STRIKE_SEARCH_RINGS  = 15
# --- V2.5.20 ORB IN-DAY CHOP KILL (2026-07-12, user go-ahead) --------------
# From the day-type study (orion_backtest_lab/results/inday_adaptive_kill.txt):
# the ONLY adaptive-kill component positive on BOTH the 439-day set (+198.36)
# and the recent real 38-day set (+10.00) is: stand ORB down (new entries AND
# flip re-entries) once the day-so-far confirms CHOPPY at a half-hour
# checkpoint from 10:30. CHOPPY here = day range so far < the p33 range cutoff
# for that time-of-day AND >=4 side-flips of the 15m close vs the session
# cumulative TWAP. Cutoffs are the big-data (2024-09..2026-06) p33 of
# (range-so-far / prev-close)% at each checkpoint -- hardcoded (causal live).
# Sticky: once killed, ORB stays down for the day. Open positions exit
# normally (the kill blocks entries only, matching what was validated).
ORB_CHOP_KILL_ENABLED = True
ORB_CHOP_MIN_CROSSES  = 4
ORB_CHOP_P33_BY_CP = {           # "HH:MM" -> p33 of range-so-far% at that time
    "10:30": 0.46, "11:00": 0.51, "11:30": 0.53, "12:00": 0.55,
    "12:30": 0.57, "13:00": 0.58, "13:30": 0.61, "14:00": 0.64, "14:30": 0.66,
}

GAP_THRESH_PTS       = 166.7  # 2026-08-31: was 250.0. Proportional carry of NIFTY 75->50 at this port's 3.333x scaling (50 * 250/75).
GAP_STOP_PTS         = 100.0
GAP_LOCK_PTS         = 26.7    # 2026-08-31: was 50.0. Proportional to NIFTY 15->8 at the existing 3.333x scaling (8 * 50/15).
GAP_RIDE_TRIGGER_PTS = 215.0
GAP_RIDE_GIVEBACK_PTS= 165.0
GAP_SQOFF_H, GAP_SQOFF_M             = 15, 15
GAP_FLIP_CUTOFF_H, GAP_FLIP_CUTOFF_M = 14, 30
GAP_PREM_MIN, GAP_PREM_MAX = 200.0, 1000.0
GAP_CONFIRM_BARS = 3          # 5m bars to wait for an up-close before confirming entry
GAP_ENTRY_END_H, GAP_ENTRY_END_M = 15, 0

# V2.5.20 validated exit fix for FUT5VWAP (backtest: -25.52 -> +545.25 pts):
# replaces the old fixed +12 target/no-trail with the same touch-stop/lock/ride
# shape as ORB/GAPBREAK (no flip).
FUT5_FIX_STOP_PTS = 40.0   # 2026-09-28: 80 -> 40 (tight SL on loser engines, see CHANGE_HISTORY)
# 2026-08-17: tightened from 30 -> 25pt. Real re-port of FUT5VWAP's own logic at native
# 1-min option-data resolution (no same-bar stop/lock ambiguity), full available window
# 2024-09-30->2026-05-26 (380 days, 252 trades): -25pt gave +Rs56,029 vs -30pt's +Rs53,315
# (+5%); -20/-15/-10pt all tested WORSE than baseline (win rate collapses below -25pt).
# See orion-notrade-zone-design-attempts-2026-08-16 memory for the full sweep.
FUT5_FIX_LOCK_PTS = 13.0
FUT5_RIDE_TRIGGER_PTS = 215.0   # same RIDE_TRIGGER/GIVEBACK the backtest shares across
FUT5_RIDE_GIVEBACK_PTS = 165.0  # ORB/GAPBREAK/FUT5VWAP (orion_concurrent_engine.py globals)
FUT5_SQOFF_H, FUT5_SQOFF_M = 15, 25   # backtest: dt.time(15,25) -- same as generic force-close

# PIVOTBREAK removed 2026-08-09: tried the kill-switch (08-08), a professionally-
# rebuilt exit (confirmed breakout, %-of-premium stop, buffered VWAP-trail), the
# same rebuild opened to all days, and an opposite-side fade -- every version's
# net profit traced back to one outlier trade (2026-05-12, +Rs17,738/+Rs19,441
# depending on variant); excluding it, every variant was net negative. No
# repeatable edge found. See memory orion-v2520-pivotbreak-rebuild-and-vwap-
# directional-bias-2026-08-09.md for the full trail before re-adding this.
TARGET_EXPIRY_DATE = None   # set at boot; datetime.date of the nearest weekly expiry (still used by EXPIRY engine)

# V2.5.20 NEW (2026-07-26): EXPIRY -- OTM premium-multiplication pop, expiry day
# only. Basis: retrospective study of E-1->E premium doubling (full-year real
# bhavcopy, 348 instances, + recent 48-day intraday data). Finding: a >=2x
# premium pop is driven by MONEYNESS CONVERGENCE -- the strike the spot moves
# TOWARD/THROUGH, confirmed by a round-level break, not generic day volatility.
# Winners (>=2x): median distance from strike at close -37.9pt (near/at money),
# 39.8% ended fully ITM, vs losers' -212.5pt / 2.4% ITM. Direction skews PE
# (70 of 98 winners) matching the down-move-heavy expiry-afternoon pattern
# already used by countertrend_veto/PIVOTBREAK's direction studies.
# NOT WALK-FORWARD VALIDATED AS A FORWARD ENTRY RULE (see orion-otm-s13-
# walkforward-negative memory -- naive multiplier-chase strategies failed OOS
# repeatedly in this exact research arc). This is a first live cut, real-time
# translation of the retrospective pattern (level-break detection instead of
# hindsight), not a proven edge -- ships because EXECUTION_BROKER is currently
# "kite_paper" (no real money at risk) so it can accrue real live-tick data for
# validation the same way FUT5VWAP/PIVOTBREAK did before being trusted further.
# SIMPLIFICATION vs the retrospective study: the volume-surge confirmation
# used in the analysis needs live per-strike 5m volume history that isn't
# already fetched anywhere in the hot loop; v1 skips it and trades on the
# round-level break + moneyness-convergence distance alone. Add volume once
# a cheap per-strike 5m-bar cache exists.
EXPIRY_ENABLED = True
EXPIRY_ROUND_STEP = 100.0          # round-level (round-50) cross defines the break
EXPIRY_DIST_MAX = 2               # only strikes within 2 steps of the POST-break ATM qualify
EXPIRY_PREM_MIN, EXPIRY_PREM_MAX = 15.0, 330.0
EXPIRY_ENTRY_START_H, EXPIRY_ENTRY_START_M = 9, 45
EXPIRY_ENTRY_END_H, EXPIRY_ENTRY_END_M = 15, 0
EXPIRY_STRIKE_STEP = 100
EXPIRY_SQOFF_H, EXPIRY_SQOFF_M = 15, 15   # tighter than the generic 15:25 -- matches ORB/GAPBREAK's
                                            # convention of not holding into the last wild 10min
# V2.5.20 (2026-07-26): EXPIRY-specific exit -- velvet-rope/ladder on MULTIPLES
# of entry premium, not the shared BASE/V2/VWAP continuous trail (FIXED_TP_PTS/
# TRAIL_STEP_PTS/TRAIL_FLOOR_PTS are absolute points tuned for Rs100-300
# premiums; EXPIRY entries are cheap OTM Rs5-100, so a fixed +15pt arm would
# rarely even trigger). Also explicitly SKIPS the SMA8(low)/VWAP 15m trail
# (per user instruction 2026-07-26) -- HARDSL_PCT (generic, already %-based)
# + this ladder are the only exit mechanisms.
EXPIRY_VELVET_ARM_MULT   = 1.5   # peak >= entry*1.5 -> lock SL at breakeven (entry*1.0)
EXPIRY_VELVET_T2_MULT    = 2.0   # peak >= entry*2.0 (a double) -> lock SL at entry*1.5
EXPIRY_VELVET_T3_MULT    = 3.0   # peak >= entry*3.0 -> lock SL at entry*2.0 (bank the double)
EXPIRY_VELVET_RIDE_GIVEBACK = 0.30   # beyond T3, continuous trail: SL = peak*(1-0.30), ratchets up only
# 2026-09-11: EXPIRY EXIT REPAIR — the ARM tier above locks SL at ENTRY
# (breakeven), which closed SENSEX 09-03 76800PE (entry 144.70, peak 243.15)
# for Rs0 at 11:23 while 15:15 was 222.15 = +Rs1,549 forgone. A lock that
# arms after a 1.5x run and protects zero profit is never right, so the tier
# no longer arms. T2/T3/ride-trail and HARDSL_-18pct are UNCHANGED, and
# EXPIRY_SQOFF stays 15:15 (15:28 was REFUTED on NIFTY: -Rs270 vs -Rs9,217
# over 6 expiry legs). Revert = True.
EXPIRY_VELVET_ARM_LOCK = False

# ---- V2.5.20 ORB SIDEWAYS-day filter -----------------------------------
# Validated result (see memory orion-daytype-filter-orb-gapbreak-result):
# skipping ORB entirely on days classified SIDEWAYS took ORB from +822.70 to
# +1014.94 pts (avg pts/trade +1.67 -> +3.73) over 439 days. GAPBREAK got
# WORSE under the same filter (+194.30 -> +51.55) and intentionally does NOT
# get it here -- GAPBREAK's whole premise is a gap that can turn an
# otherwise-SIDEWAYS-by-yesterday's-regime day into a real trend day.
#
# LIVE-SAFE APPROXIMATION, NOT an exact port: the backtest's classify_day_type()
# used the FULL day's realized 1-min high/low range plus a whole-dataset 75th-
# percentile cutoff to split CHOPPY/VOLATILE/TRENDING/SIDEWAYS -- both inputs
# are look-ahead (today's day-range isn't known until the day is over) and
# can't be reproduced live. The only causal input available at ORB-decision
# time (09:25+) is the regime computed at boot from the PRIOR day's 1h close
# vs SMA20/50. So live, ORB is treated as "SIDEWAYS today" purely when regime
# is NOT BULL/BEAR -- this collapses the backtest's TRANSITION/CHOPPY/VOLATILE
# buckets into "skip", which is a stricter (skip-more) filter than the exact
# backtest one, so live trade counts/pts won't exactly match +1014.94 -- but
# the validated direction (stand ORB down on non-trending days) is preserved.
# Reference only (NOT applied live): the backtest's own vol_cut was the 75th
# percentile day-range over its 439-day 2024-09-09..2026-06-17 window, computed
# by run_concurrent_full.py's compute_vol_cut():
ORB_SIDEWAYS_VOL_CUT_PTS_REF = 294.35  # reference only, see note above
ORB_ALLOWED_REGIMES = ('BULL', 'BEAR', 'TRANSITION', 'CHOP')   # 2026-08-31; mirrors the NIFTY change. NOTE: measurement was NIFTY-only, no SENSEX evidence. In-day ORB_CHOP_KILL still applies.

# 2026-08-29: ORB now also trades TRANSITION days, not just BULL/BEAR.
# WHY: the gate was standing ORB down on 27 of 40 live days (TRANSITION 14,
# CHOP 13) and there had been no BULL/BEAR day at all since 08-17, so the
# engine fired ZERO times for six straight sessions including 08-27 (NIFTY
# -187 closing on the low, SENSEX -643 on the low) -- exactly the one-way
# trend day an opening-range break exists for.
# The gate was ALSO stricter than what was ever validated: the backtest only
# validated skipping SIDEWAYS days; the live proxy collapsed TRANSITION *and*
# CHOP into 'skip', and the original comment admits it is 'stricter
# (skip-more)'. V2's own regime_allows_trade() permits TRANSITION.
# 198-session check (spot points, opening-range break, live ORB exit params):
#   SENSEX  BULL +8.71  BEAR +10.52  TRANSITION +3.34  CHOP +1.75
#   NIFTY   BULL +1.30  BEAR  -0.88  TRANSITION +0.19  CHOP +2.62
# TRANSITION is positive on both indices -- lower quality than BULL/BEAR, but
# not harmful, and it is the difference between an engine that trades and one
# that does not. CHOP stays excluded. NOT a validated profit claim: measured
# in SPOT points, and forward paper is the only referee.
def is_orb_day_sideways_live():
    """Stand ORB down only on CHOP/INSUFFICIENT (was: anything not BULL/BEAR)."""
    return DAY_STATES["ORB"].regime not in ORB_ALLOWED_REGIMES

# ---- Operating ----
# V2.5.20 loop-mechanics check: the 6 historical() bar fetches (1h/15m/5m spot+fut
# +1m) are shared, not per-engine, so they don't multiply. Per-engine work is
# ltp() in check_exits (up to 5/tick, only for active positions) + fetch_option_15m
# for the SMA8/VWAP trail (BASE/VWAP/V2/V3 only, ORB/GAPBREAK/FUT5VWAP return early
# from the touch-manager without reaching it). Strike-search ltp() calls (up to 31,
# from pick_strike_by_premium's 50pt rings) only happen once per engine per day, at
# signal time -- not every tick. Worst case per tick (all 5 active): ~6 + 5 = 11 API
# calls / 30s -- well inside Kite's quote (1/s) and historical (3/s) rate limits.
LOOP_SLEEP_SEC          = 30
WATCHDOG_TIMEOUT_SEC    = 300
PULSE_INTERVAL_SEC      = 15 * 60   # 15-min Telegram pulse
AFTER_HOURS_PULSE_MIN   = 30        # send "alive" pulse this often after market close

# ---- File outputs ----
RUN_TS  = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
CSV_FN  = f"Sensex_BarLevel_{VERSION.replace('.','_')}_{RUN_TS}.csv"
LOG_FN  = f"Sensex_FlightRecorder_{VERSION.replace('.','_')}_{RUN_TS}.log"
STATE_FN = f"state_{VERSION.replace('.','_')}.json"

# ---- OI Plan (written by Optiondata_1.py + eod_analysis.py) ----
_SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))

# =========================================================================
# 2026-09-19 NIFTY BLOCK GATE (SENSEX ONLY) — read ~/Amol/nifty_blocks.jsonl,
# written by the NIFTY bot for every entry ITS gates refuse. If NIFTY refused
# >= NIFTY_BLOCK_GATE_MIN entries in the last NIFTY_BLOCK_GATE_WINDOW_MIN
# minutes, ORB / V3 / FUT5VWAP may not enter here. Other engines untouched.
# Evidence + revert in CHANGE_HISTORY. Missing/unreadable file = gate open.
# =========================================================================
NIFTY_BLOCK_GATE_ENABLED    = True
NIFTY_BLOCK_GATE_ENGINES    = ("ORB", "V3", "FUT5VWAP")
NIFTY_BLOCK_GATE_WINDOW_MIN = 60
NIFTY_BLOCK_GATE_MIN        = 2
NIFTY_BLOCK_FILE            = os.path.join(_SCRIPT_DIR, "nifty_blocks.jsonl")
def nifty_block_gate(engine, side):
    """(blocked, reason). Counts NIFTY refusals dated today within the window."""
    if not NIFTY_BLOCK_GATE_ENABLED or engine not in NIFTY_BLOCK_GATE_ENGINES: return False, ''
    try:
        if not os.path.exists(NIFTY_BLOCK_FILE): return False, ''
        now = datetime.now(IST); today = now.strftime("%Y-%m-%d"); n = 0; last = None
        with open(NIFTY_BLOCK_FILE) as _f:
            for _ln in _f:
                try: _r = json.loads(_ln)
                except Exception: continue
                _ts = str(_r.get("ts", ""))
                if not _ts.startswith(today): continue
                _t = IST.localize(datetime.strptime(_ts, "%Y-%m-%d %H:%M:%S"))
                if 0 <= (now - _t).total_seconds() <= NIFTY_BLOCK_GATE_WINDOW_MIN * 60:
                    n += 1; last = f"{_r.get('kind','?')} {_r.get('engine','?')} {_r.get('side','?')} @{_ts[11:16]}"
        if n >= NIFTY_BLOCK_GATE_MIN:
            return True, f"NIFTY refused {n} entries in last {NIFTY_BLOCK_GATE_WINDOW_MIN}m (last: {last})"
        return False, ''
    except Exception as _e:
        lwarn(f"[NIFTYGATE] read failed, gate open: {_e}"); return False, ''
OI_PLAN_FILE  = os.path.join(_SCRIPT_DIR, "next_day_plan_sensex.json")  # SENSEX: no EOD OI-plan writer yet -> file absent -> plan None (fails safe)

# =========================================================================
# LOGGING
# =========================================================================
# 2026-08-29 FIX -- FlightRecorder logs were boot-banner-only since ~2026-08-20.
# ROOT CAUSE: push_logs_to_github() runs `git rebase --autostash` every 5 min.
# With a dirty working tree the autostash push/pop DELETES AND RECREATES every
# modified tracked file, including LOG_FN. A plain FileHandler keeps its open fd
# pointing at the now-orphaned inode, so every line written after the first push
# goes into a deleted file and is lost. The BarLevel CSV survived because
# csv_append() reopens by name on every write. CONTROL that confirms this:
# stocks_run.log is NOT git-tracked, is never touched by the push, and is
# complete through 15:30 IST on the very same sessions.
# WatchedFileHandler stats the path before each emit and reopens the file when
# the inode changes, so logging follows the recreated file. Dropping --autostash
# is the wrong fix -- it was added 2026-07-27 to stop a different failure
# (365+ push rejects/day). See orion-flightrecorder-log-inode-bug-2026-08-27.
_log_handler = logging.handlers.WatchedFileHandler(LOG_FN)
_log_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])
log = logging.getLogger("orion")
def linfo(msg):  print(msg); log.info(msg)
def lwarn(msg):  print(f"[WARN] {msg}"); log.warning(msg)
def lerr(msg):   print(f"[ERR ] {msg}"); log.error(msg)

# =========================================================================
# TELEGRAM
# =========================================================================
class TelegramManager:
    """Reliable Telegram delivery with retry + local fallback log."""
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.fallback_fn = f"telegram_fallback_{VERSION.replace('.','_')}_{RUN_TS}.log"
        self.lock = threading.Lock()

    def send(self, msg: str, retries: int = 3, html: bool = True) -> bool:
        """Send Telegram message. By default uses HTML parse_mode for bold/italic/code formatting.
        Set html=False to send raw text (e.g. for messages with characters that would need escaping)."""
        with self.lock:
            payload = {"chat_id": self.chat_id, "text": "\U0001F7E0 SENSEX | " + msg}
            if html:
                payload["parse_mode"] = "HTML"
            for attempt in range(retries):
                try:
                    r = requests.post(self.url, data=payload, timeout=10)
                    if r.status_code == 200:
                        return True
                    lwarn(f"Telegram send returned {r.status_code}: {r.text[:200]}")
                    # If HTML parsing failed, retry without HTML
                    if r.status_code == 400 and html:
                        lwarn("HTML parse failed; retrying as plain text")
                        payload.pop("parse_mode", None)
                        html = False
                except Exception as e:
                    lwarn(f"Telegram send failed attempt {attempt+1}: {e}")
                time.sleep(2 ** attempt)
            # All retries failed - write to local fallback
            try:
                with open(self.fallback_fn, "a") as f:
                    f.write(f"\n--- {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')} ---\n{msg}\n")
                lerr(f"Telegram unreachable; appended to {self.fallback_fn}")
            except Exception as e:
                lerr(f"Could not write fallback: {e}")
            return False


def tg_escape(s) -> str:
    """Escape HTML special chars for safe Telegram HTML mode."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

TG = TelegramManager(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

# Bot-level stop flag and Telegram command offset (used by polling thread)
_bot_stop_flag  = threading.Event()

def _signal_handler(signum, frame):
    print(f"[SIGNAL] Received signal {signum}. Setting stop flag for clean shutdown.")
    _bot_stop_flag.set()

signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)
_tg_cmd_offset  = 0

# =========================================================================
# WATCHDOG
# =========================================================================
class Watchdog:
    """Background thread - alerts via Telegram if main loop stalls > timeout."""
    def __init__(self, timeout_sec):
        self.timeout = timeout_sec
        self.last_beat = time.time()
        self.alive = True
        self.alerted = False

    def beat(self):
        self.last_beat = time.time()
        self.alerted = False

    def stop(self):
        self.alive = False

    def run(self):
        while self.alive:
            time.sleep(30)
            since = time.time() - self.last_beat
            if since > self.timeout and not self.alerted:
                TG.send(f"⚠️ <b>WATCHDOG</b> No heartbeat for {int(since)}s — main loop may be stalled.")
                self.alerted = True

WD = Watchdog(WATCHDOG_TIMEOUT_SEC)

# =========================================================================
# MARKET-DATA CLIENT — Upstox via Kite-compatible shim (2026-08-26).
# Kite retired per user; the shim serves instruments/candles/quotes with the
# long-lived read-only UPSTOX_ACCESS_TOKEN (no daily login). All downstream
# kite.* calls are unchanged. See upstox_kite_shim.py / UPSTOX_REFERENCE.md.
# =========================================================================
from upstox_kite_shim import UpstoxKite
kite = UpstoxKite(UPSTOX_ACCESS_TOKEN)

NIFTY_INSTRUMENT_TOKEN = 265      # BSE SENSEX (index token; var name kept to avoid a 300-line rename)

def kite_safe(fn, *args, retries=3, **kwargs):
    """Wrap any kite call with retry. Returns None on terminal failure."""
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            lwarn(f"Kite call failed ({fn.__name__}) attempt {attempt+1}: {e}")
            time.sleep(2 ** attempt)
    lerr(f"Kite call {fn.__name__} terminal failure")
    return None

def ltp(symbol):
    res = kite_safe(kite.ltp, [symbol])
    if not res: return None
    return res.get(symbol, {}).get("last_price")

def historical(token, frm, to, interval):
    return kite_safe(kite.historical_data, token, frm, to, interval)

# =========================================================================
# EXPIRY RESOLUTION (weekly Nifty options)
# =========================================================================
def resolve_expiry_and_strikes():
    """
    Resolve the nearest weekly Nifty expiry. Returns (target_expiry_date, strikes_set).
    Strikes_set is the set of strikes available for that expiry.
    """
    insts = kite_safe(kite.instruments, "BFO")
    if not insts:
        raise RuntimeError("Could not fetch BFO instruments")
    today = datetime.now(IST).date()
    nifty_options = [i for i in insts
                     if i["name"] == "SENSEX"
                     and i["instrument_type"] in ("CE", "PE")
                     and i["expiry"] >= today]
    if not nifty_options:
        raise RuntimeError("No Nifty options found")
    expiries = sorted({i["expiry"] for i in nifty_options})
    target_expiry = expiries[0]
    strikes = sorted({i["strike"] for i in nifty_options if i["expiry"] == target_expiry})
    # Build lookup: (strike, side) -> (kite_symbol, token)
    # kite_symbol: "NFO:NIFTY2660223500PE" — used for Kite quote calls
    # mStock symbol = strip "NFO:" prefix → "NIFTY2660223500PE" — confirmed working in live test
    lookup = {}
    for i in nifty_options:
        if i["expiry"] == target_expiry:
            key = (i["strike"], i["instrument_type"])
            lookup[key] = (f"BFO:{i['tradingsymbol']}", i["instrument_token"])
    # Resolve nearest Nifty futures token for VWAP confirmation
    nifty_futs = [i for i in insts
                  if i["name"] == "SENSEX"
                  and i["instrument_type"] == "FUT"
                  and i["expiry"] >= today]
    nifty_fut_token = None
    if nifty_futs:
        nearest_fut = sorted(nifty_futs, key=lambda x: x["expiry"])[0]
        nifty_fut_token = nearest_fut["instrument_token"]
        linfo(f"[BOOT] Nifty FUT token: {nifty_fut_token} expiry={nearest_fut['expiry']} sym={nearest_fut['tradingsymbol']}")
    else:
        lwarn("[BOOT] ⚠️ No Nifty FUT found — VWAP engine will skip futures gate")
    return target_expiry, strikes, lookup, nifty_fut_token

# =========================================================================
# INDICATOR MATH
# =========================================================================
def rsi(close: pd.Series, n=14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def stochrsi_k(close: pd.Series, length=STOCHRSI_LEN, rsi_length=STOCHRSI_RSI_LEN, k=STOCHRSI_K_SMOOTH) -> pd.Series:
    r = rsi(close, rsi_length)
    lo = r.rolling(length).min()
    hi = r.rolling(length).max()
    raw = (r - lo) / (hi - lo).replace(0, np.nan) * 100.0
    return raw.rolling(k).mean()

def macd_lines(close: pd.Series, fast=12, slow=26, signal=9):
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    line = ef - es
    sig  = line.ewm(span=signal, adjust=False).mean()
    return line, sig

def adx_di(df: pd.DataFrame, n=14):
    h, l, c = df['high'], df['low'], df['close']
    tr1 = h - l
    tr2 = (h - c.shift(1)).abs()
    tr3 = (l - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    up = h - h.shift(1)
    dn = l.shift(1) - l
    plus_dm  = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    atr = tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    pdi = 100 * plus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr
    ndi = 100 * minus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr
    dx  = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    adx = dx.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    return adx, pdi, ndi

# =========================================================================
# V3 LEVELS / CLUSTERS / REGIME
# =========================================================================
def find_swing_pivots(df1h_prior: pd.DataFrame, lookback=SWING_LOOKBACK_BARS, n=SWING_PIVOT_N):
    pivots = []
    sub = df1h_prior.iloc[-(lookback + 2*n):].copy().reset_index(drop=True)
    if len(sub) < 2*n + 1:
        return pivots
    for i in range(n, len(sub) - n):
        h, l = sub['high'].iloc[i], sub['low'].iloc[i]
        is_h = all(h > sub['high'].iloc[i-k] for k in range(1, n+1)) and \
               all(h > sub['high'].iloc[i+k] for k in range(1, n+1))
        is_l = all(l < sub['low'].iloc[i-k]  for k in range(1, n+1)) and \
               all(l < sub['low'].iloc[i+k]  for k in range(1, n+1))
        if is_h: pivots.append((float(h), 'swing_high'))
        if is_l: pivots.append((float(l), 'swing_low'))
    return pivots

def generate_round_levels(price, rng=ROUND_RANGE_PTS):
    out = set()
    base = round(price / ROUND_STEP_FINE) * ROUND_STEP_FINE
    for off in range(-rng, rng + 1, ROUND_STEP_FINE):
        p = base + off
        kind = 'round_100' if p % 500 == 0 else 'round_50'  # SENSEX: major=500s, fine=100s (labels kept for CSV compat)
        out.add((float(p), kind))
    return list(out)

def cluster_levels(sources, radius=CLUSTER_RADIUS_PTS):
    if not sources: return []
    s = sorted(sources, key=lambda x: x[0])
    clusters, cur = [], [s[0]]
    for p, k in s[1:]:
        if p - cur[-1][0] <= radius:
            cur.append((p, k))
        else:
            clusters.append(cur); cur = [(p, k)]
    clusters.append(cur)
    out = []
    for c in clusters:
        kinds = set(k for _, k in c)
        center = sum(p for p, _ in c) / len(c)
        n = len(kinds)
        grade = 'A' if n >= GRADE_A_MIN_SOURCES else ('B' if n >= GRADE_B_MIN_SOURCES else 'C')
        out.append({'center': round(center, 2), 'kinds': sorted(kinds), 'count': n, 'grade': grade})
    return out

def load_oi_plan() -> Optional[dict]:
    """
    Load next_day_plan.json written by eod_analysis.py.
    Returns plan dict or None if file missing/stale/expiry-day.
    Stale = plan date is not yesterday (would be wrong levels).
    """
    if not os.path.exists(OI_PLAN_FILE):
        return None
    try:
        with open(OI_PLAN_FILE) as f:
            plan = json.load(f)
        plan_date = plan.get("date", "")
        today = datetime.now(IST).date()
        yesterday = today - timedelta(days=1)
        # Accept plan dated yesterday OR today (if run same morning)
        if plan_date not in (str(yesterday), str(today)):
            lwarn(f"[OI Plan] Stale plan ({plan_date}) — ignoring for today's levels")
            return None
        if plan.get("is_expiry_day"):
            linfo("[OI Plan] Expiry day — OI plan loaded for info only, not V3 triggers")
            plan["_info_only"] = True
        return plan
    except Exception as e:
        lwarn(f"[OI Plan] Failed to load: {e}")
        return None


def _inject_oi_walls(levels: dict, plan: Optional[dict]):
    """
    Inject OI wall levels from next_day_plan.json into the V3 cluster list.
    WALL (Grade A from OI) -> injected as Grade A cluster with kind 'OI_WALL'
    SIGNIFICANT (Grade B) -> injected as Grade B cluster with kind 'OI_ZONE'
    Skipped if plan is None, info_only (expiry day), or expiry_caution.
    """
    if plan is None or plan.get("_info_only") or plan.get("expiry_caution"):
        return

    pdc = levels.get("pdc", 0)
    all_clusters = levels.get("all_clusters", [])

    def _already_covered(strike):
        for c in all_clusters:
            if abs(c["center"] - strike) <= 30:  # 30pt merge radius for OI walls
                return True
        return False

    added = []
    for r in plan.get("resistance_levels", []):
        s = float(r["strike"])
        if s <= pdc:
            continue  # resistance must be above PDC
        if _already_covered(s):
            linfo(f"[OI Plan] {s} CE {r['signal']} already in cluster — skipping inject")
            continue
        grade = r.get("grade", "B")
        all_clusters.append({
            "center": s, "kinds": ["OI_WALL" if grade == "A" else "OI_ZONE"],
            "count": 1, "grade": grade,
            "oi_signal": r["signal"], "ce_oi": r.get("ce_oi", 0),
        })
        added.append(f"R {s} [{r['signal']}]")

    for sp in plan.get("support_levels", []):
        s = float(sp["strike"])
        if s >= pdc:
            continue  # support must be below PDC
        if _already_covered(s):
            linfo(f"[OI Plan] {s} PE {sp['signal']} already in cluster — skipping inject")
            continue
        grade = sp.get("grade", "B")
        all_clusters.append({
            "center": s, "kinds": ["OI_WALL" if grade == "A" else "OI_ZONE"],
            "count": 1, "grade": grade,
            "oi_signal": sp["signal"], "pe_oi": sp.get("pe_oi", 0),
        })
        added.append(f"S {s} [{sp['signal']}]")

    if added:
        linfo(f"[OI Plan] Injected {len(added)} OI levels into V3: {added}")
        # Re-evaluate G/R with OI walls included
        buf = V3_MIN_BUFFER_FROM_PDC if V3_EXCLUDE_PDC_FROM_CLUSTERS else 0
        above = [c for c in all_clusters if c["center"] > pdc + buf and c["grade"] in ("A","B")]
        below = [c for c in all_clusters if c["center"] < pdc - buf and c["grade"] in ("A","B")]
        above.sort(key=lambda c: (0 if c["grade"]=="A" else 1, abs(c["center"] - pdc)))
        below.sort(key=lambda c: (0 if c["grade"]=="A" else 1, abs(c["center"] - pdc)))
        levels["G"] = above[0] if above else levels.get("G")
        levels["R"] = below[0] if below else levels.get("R")
        levels["all_clusters"] = all_clusters


def compute_classic_pivots(pdh: float, pdl: float, pdc: float) -> dict:
    """V2.5.19: classic floor-trader pivots from the prior trading day's H/L/C.
    P = (H+L+C)/3 ; R1 = 2P-L ; S1 = 2P-H ; R2 = P+(H-L) ; S2 = P-(H-L).
    Used by Features 2 & 3 for the '>20pt away from S1/R1/S2/R2' clear-space gate."""
    p = (pdh + pdl + pdc) / 3.0
    rng = pdh - pdl
    return {
        'P':  round(p, 2),
        'R1': round(2 * p - pdl, 2),
        'S1': round(2 * p - pdh, 2),
        'R2': round(p + rng, 2),
        'S2': round(p - rng, 2),
    }


def min_dist_to_pivots(price: float) -> Optional[float]:
    """V2.5.19: min absolute distance from price to any of S1/R1/S2/R2.
    Returns None if pivots are unavailable (caller fails OPEN -> no extra block)."""
    piv = DAY.pivots
    if not piv:
        return None
    try:
        return min(abs(price - piv[k]) for k in ('S1', 'R1', 'S2', 'R2'))
    except Exception:
        return None


def fut_pivot_dist(fut_close: float, df_fut, spot) -> Optional[float]:
    """2026-09-28 PIVOT BASIS FIX: DAY.pivots come from SPOT 1h bars, but the
    FUT5VWAP / morning-VWAP gates tested the FUTURES close against them, so the
    gate measured futures basis (NIFTY 3-100 pts) instead of distance to the pivot.
    Now the FUT close is shifted to spot terms with the live basis
    (forming FUT bar close - live spot) before the distance check.
    Missing spot/forming bar -> falls back to the old FUT-close distance."""
    try:
        if spot is not None and float(spot) > 0 and df_fut is not None and len(df_fut) >= 1:
            basis = float(df_fut.iloc[-1]['close']) - float(spot)
            return min_dist_to_pivots(fut_close - basis)
    except Exception:
        pass
    return min_dist_to_pivots(fut_close)


def compute_levels_for_day(df1h_prior: pd.DataFrame, prior_day_ohlc):
    pdh = float(prior_day_ohlc['H'])
    pdl = float(prior_day_ohlc['L'])
    pdc = float(prior_day_ohlc['C'])
    # V2.5.6 Fix A: optionally exclude PDC from clustering sources (PDC is a reference,
    # including it creates false Grade A clusters near current price).
    if V3_EXCLUDE_PDC_FROM_CLUSTERS:
        src = [(pdh, 'PDH'), (pdl, 'PDL')]
    else:
        src = [(pdh, 'PDH'), (pdl, 'PDL'), (pdc, 'PDC')]
    src += generate_round_levels(pdc)
    swing_pivots_list = find_swing_pivots(df1h_prior)
    src += swing_pivots_list
    src = [s for s in src if abs(s[0] - pdc) <= ROUND_RANGE_PTS]
    clusters = cluster_levels(src)

    # V2.5.3: PROMOTE SINGLETONS — PDH/PDL/round_100 in +/-200/swing pivots
    # act as standalone Grade B if NOT in any existing A/B cluster
    if V3_PROMOTE_SINGLETONS:
        def _in_any_AB_cluster(price):
            for c in clusters:
                if c['grade'] in ('A','B') and abs(c['center'] - price) <= CLUSTER_RADIUS_PTS:
                    return True
            return False
        promoted = []
        # PDH, PDL
        for p, kind in [(pdh, 'PDH'), (pdl, 'PDL')]:
            if not _in_any_AB_cluster(p):
                promoted.append({'center': round(p, 2), 'kinds': [kind], 'count': 1,
                                 'grade': 'B', 'promoted': True})
        # Round_100s within band
        base = round(pdc / 100) * 100
        for off in range(-PROMOTE_ROUND_100_BAND, PROMOTE_ROUND_100_BAND + 1, 100):
            p = float(base + off)
            if not _in_any_AB_cluster(p):
                promoted.append({'center': round(p, 2), 'kinds': ['round_100'], 'count': 1,
                                 'grade': 'B', 'promoted': True})
        # 1h swing pivots
        for p, kind in swing_pivots_list:
            if abs(p - pdc) <= PROMOTE_SWING_BAND and not _in_any_AB_cluster(p):
                promoted.append({'center': round(p, 2), 'kinds': [kind], 'count': 1,
                                 'grade': 'B', 'promoted': True})
        all_levels = clusters + promoted
    else:
        all_levels = clusters

    # V2.5.6 Fix B: respect MIN_BUFFER_FROM_PDC for G/R selection
    buf = V3_MIN_BUFFER_FROM_PDC if V3_EXCLUDE_PDC_FROM_CLUSTERS else 0
    above = [c for c in all_levels if c['center'] > pdc + buf and c['grade'] in ('A','B')]
    below = [c for c in all_levels if c['center'] < pdc - buf and c['grade'] in ('A','B')]
    above.sort(key=lambda c: (0 if c['grade']=='A' else 1, abs(c['center']-pdc)))
    below.sort(key=lambda c: (0 if c['grade']=='A' else 1, abs(c['center']-pdc)))
    return {'pdh': pdh, 'pdl': pdl, 'pdc': pdc,
            'G': above[0] if above else None,
            'R': below[0] if below else None,
            'all_clusters': all_levels}

def compute_targets(level, direction, all_clusters):
    center = level['center']
    if direction == 'CE':
        cand = sorted({c['center'] for c in all_clusters if c['center'] > center + T1_MIN_PTS})
    else:
        cand = sorted({c['center'] for c in all_clusters if c['center'] < center - T1_MIN_PTS}, reverse=True)
    t1 = next((c for c in cand if T1_MIN_PTS <= abs(c-center) <= T1_MAX_PTS), None)
    if t1 is None and cand: t1 = cand[0]
    if t1 is None: t1 = (center + T1_MAX_PTS) if direction == 'CE' else (center - T1_MAX_PTS)
    return round(t1, 2)

def classify_regime(row_1h):
    if pd.isna(row_1h.get('SMA20')) or pd.isna(row_1h.get('SMA50')) or pd.isna(row_1h.get('ADX')):
        return 'INSUFFICIENT'
    c, s20, s50 = row_1h['close'], row_1h['SMA20'], row_1h['SMA50']
    sl20, sl50, adxv = row_1h['SMA20_slope'], row_1h['SMA50_slope'], row_1h['ADX']
    if adxv < ADX_CHOP_MAX: return 'CHOP'
    if c > s20 > s50 and sl20 > 0 and sl50 > 0 and adxv > ADX_TREND_MIN: return 'BULL'
    if c < s20 < s50 and sl20 < 0 and sl50 < 0 and adxv > ADX_TREND_MIN: return 'BEAR'
    return 'TRANSITION'

def regime_allows_trade(regime):
    return regime in ('BULL', 'BEAR', 'TRANSITION')

def evaluate_candle(bar, level, kind, grade):
    o, h, l, c = bar['open'], bar['high'], bar['low'], bar['close']
    rng = h - l
    if rng <= 0: return False
    body_pct = abs(c - o) / rng
    if kind == 'BREAK_CE':
        beyond = c - level
        if grade == 'A':
            return beyond >= GRADE_A_MIN_CLOSE_BEYOND and body_pct >= GRADE_A_MIN_BODY_PCT
        return body_pct >= GRADE_B_MIN_BODY_PCT and (c - l)/rng >= 1 - GRADE_B_CLOSE_TOP_PCT
    if kind == 'BREAK_PE':
        beyond = level - c
        if grade == 'A':
            return beyond >= GRADE_A_MIN_CLOSE_BEYOND and body_pct >= GRADE_A_MIN_BODY_PCT
        return body_pct >= GRADE_B_MIN_BODY_PCT and (h - c)/rng >= 1 - GRADE_B_CLOSE_TOP_PCT
    return False

def detect_v3_signal_on_bar(bar15, level_obj, role):
    """Returns dict {'kind', 'level', 'grade', 'role'} or None."""
    o, h, l, c = bar15['open'], bar15['high'], bar15['low'], bar15['close']
    L = level_obj['center']
    rng = h - l
    grade = level_obj['grade']
    # Wick rejection
    if rng > 0:
        if role == 'G' and h >= L and c < L + WICK_REJECT_CLOSE_DIST:
            wick = h - max(o, c)
            if (wick / rng) >= WICK_REJECT_MIN_PCT and abs(c - L) <= WICK_REJECT_CLOSE_DIST:
                return {'kind': 'REJECT_PE', 'level': L, 'role': role, 'grade': grade}
        if role == 'R' and l <= L and c > L - WICK_REJECT_CLOSE_DIST:
            wick = min(o, c) - l
            if (wick / rng) >= WICK_REJECT_MIN_PCT and abs(c - L) <= WICK_REJECT_CLOSE_DIST:
                return {'kind': 'REJECT_CE', 'level': L, 'role': role, 'grade': grade}
    # Break
    if role == 'G' and c > L and evaluate_candle(bar15, L, 'BREAK_CE', grade):
        return {'kind': 'BREAK_CE', 'level': L, 'role': role, 'grade': grade}
    if role == 'R' and c < L and evaluate_candle(bar15, L, 'BREAK_PE', grade):
        return {'kind': 'BREAK_PE', 'level': L, 'role': role, 'grade': grade}
    return None

# =========================================================================
# DATA FETCHERS
# =========================================================================
def fetch_nifty_1h(days_back=30):
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(NIFTY_INSTRUMENT_TOKEN, frm, now, "60minute")
    if not rows: return None
    df = pd.DataFrame(rows)
    df['SMA20'] = df['close'].rolling(SMA_FAST_1H).mean()
    df['SMA50'] = df['close'].rolling(SMA_SLOW_1H).mean()
    df['SMA20_slope'] = df['SMA20'].diff(3)
    df['SMA50_slope'] = df['SMA50'].diff(3)
    df['ADX'], df['DI_plus'], df['DI_minus'] = adx_di(df, ADX_PERIOD)
    df['MACD_line'], df['MACD_sig'] = macd_lines(df['close'])
    df['RSI'] = rsi(df['close'])           # V2.5.5: needed for chop filter
    return df

def _completed_idx(_df, _now, _minutes):
    """Offset of the LAST COMPLETED bar in a start-stamped intraday frame.

    2026-08-31. The engines hardcoded iloc[-2], assuming iloc[-1] is ALWAYS the
    forming bar. That holds only once the feed has published at least one
    1-minute candle of the current bucket. In the first ~60s of a new bucket it
    has not (measured 08-31: 18/18 guard trips, and the instant refetch 28ms
    later recovered 0 of 18), so iloc[-1] IS the last completed bar and iloc[-2]
    is one bar STALE.

    Returns -2 whenever the forming bar is present -- i.e. byte-identical to the
    old hardcoded behaviour on every tick that currently reaches the engines --
    and -1 only inside that boundary window, which today is unconditionally
    blocked by the stale guard. It therefore cannot change any tick that
    currently produces a trade.
    """
    try:
        _ts = _df['date'].iloc[-1]
        if hasattr(_ts, 'to_pydatetime'):
            _ts = _ts.to_pydatetime()
        if _ts.tzinfo is None:
            _ts = IST.localize(_ts)
        _open = _now.replace(hour=9, minute=15, second=0, microsecond=0)
        if _now < _open:
            return -2
        _w = _minutes * 60
        _cur = _open + timedelta(seconds=(int((_now - _open).total_seconds()) // _w) * _w)
        return -2 if _ts >= _cur else -1
    except Exception:
        return -2


def fetch_nifty_15m(days_back=10):
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(NIFTY_INSTRUMENT_TOKEN, frm, now, "15minute")
    if not rows: return None
    df = pd.DataFrame(rows)
    df['K'] = stochrsi_k(df['close'])
    return df

def fetch_nifty_fut_15m(fut_token, days_back=10):
    if fut_token is None: return None
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(fut_token, frm, now, "15minute")
    if not rows: return None
    return pd.DataFrame(rows)

def fetch_nifty_fut_5m(fut_token, days_back=3):
    """V2.5.19: 5-minute Nifty FUTURES bars for the Feature-2 VWAP-cross scalp."""
    if fut_token is None: return None
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(fut_token, frm, now, "5minute")
    if not rows: return None
    return pd.DataFrame(rows)

def fetch_nifty_5m(days_back=3):
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(NIFTY_INSTRUMENT_TOKEN, frm, now, "5minute")
    if not rows: return None
    return pd.DataFrame(rows)

def fetch_nifty_1m(days_back=1):
    """V2.5.16: 1-minute Nifty spot bars for the momentum gate."""
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(NIFTY_INSTRUMENT_TOKEN, frm, now, "minute")
    if not rows: return None
    return pd.DataFrame(rows)

def momentum_gate_ok(sig_side, engine=""):
    """V2.5.16 momentum gate. Allow the 1st/2nd same-direction entry freely;
    from the 3rd consecutive same-side entry onward, require real momentum
    (>= MOM_GATE_PTS net spot move WITH the trade over the last MOM_GATE_BARS
    closed 1m bars). Returns (allowed: bool, info: str).
    Fails OPEN if 1m data is unavailable (never blocks on missing data).
    2026-07-12: gate is active if the global MOM_GATE_ENABLED is True OR this
    is a V3 signal (MOM_GATE_V3_ENABLED) -- V3-only re-enable per diagnosis,
    V2/FLIP untouched."""
    gate_active = MOM_GATE_ENABLED or (engine == 'V3' and MOM_GATE_V3_ENABLED)
    if not gate_active:
        return True, ""
    run = 0
    for t in reversed(DAY.trades_today):
        if t.get('side') == sig_side:
            run += 1
        else:
            break
    prospective = run + 1
    if prospective < MOM_GATE_MIN_SAMESIDE:
        return True, ""
    df1 = fetch_nifty_1m()
    if df1 is None or len(df1) < MOM_GATE_BARS + 2:
        linfo(f"[MOMGATE] 1m data unavailable — allowing #{prospective} {sig_side} by default")
        return True, f"#{prospective} 1m-data-missing"
    closed = df1.iloc[:-1]   # drop the still-forming bar
    mv = float(closed['close'].iloc[-1] - closed['close'].iloc[-1 - MOM_GATE_BARS])
    with_dir = (mv > 0) if sig_side == 'CE' else (mv < 0)
    ok = bool(with_dir and abs(mv) >= MOM_GATE_PTS)
    return ok, f"#{prospective} mv={mv:+.0f}pt thr={MOM_GATE_PTS:.0f}"

def morning_chop_verdict(df15m_fut):
    """V2.5.17 #1: from the first-hour (09:15-10:15) FUT 15m bars, decide whether
    the day is choppy enough to stand aside. Returns (decided, block, reason).
    decided=False => not enough closed bars yet (fail OPEN, keep trading).
    block=True => stand aside for the rest of the day. Exits are unaffected."""
    try:
        return _morning_chop_verdict_impl(df15m_fut)
    except Exception as e:
        lwarn(f"[CHOPGATE] verdict error ({e}) — failing OPEN")
        return False, False, "err"

def chop_rearm_check(df15m_fut):
    """V2.5.18: after a morning chop stand-aside, decide whether to RE-ARM trading.
    Re-arm when a CLOSED FUT 15m bar breaks the recorded first-hour range by
    >= CHOP_REARM_BUFFER_PT with body >= CHOP_REARM_BODY_MIN, in the regime
    direction (BULL=>up break only, BEAR=>down break only, TRANSITION/other=>either).
    FUT leads spot, so this fires earlier than a spot-range break.
    Returns (rearm: bool, reason: str). Fails CLOSED (stay blocked) on any gap."""
    try:
        if not CHOP_REARM_ENABLED:
            return False, "disabled"
        if DAY.chop_fh_high is None or DAY.chop_fh_low is None:
            return False, "no-FH-range"
        if df15m_fut is None or len(df15m_fut) < 2:
            return False, "no-FUT-data"
        df = df15m_fut
        o = float(df['open'].iloc[-2]); h = float(df['high'].iloc[-2])
        l = float(df['low'].iloc[-2]);  c = float(df['close'].iloc[-2])
        rng = h - l
        body = (abs(c - o) / rng) if rng > 0 else 0.0
        if body < CHOP_REARM_BODY_MIN:
            return False, f"body={body:.0%}<{CHOP_REARM_BODY_MIN:.0%}"
        up_break = (c >= DAY.chop_fh_high + CHOP_REARM_BUFFER_PT) and (c > o)
        dn_break = (c <= DAY.chop_fh_low  - CHOP_REARM_BUFFER_PT) and (c < o)
        # honor the regime direction when the regime is decisively trending
        if DAY.regime == 'BULL':
            dn_break = False
        elif DAY.regime == 'BEAR':
            up_break = False
        if up_break:
            return True, (f"FUT {c:.0f} > FH_high {DAY.chop_fh_high:.0f}+{CHOP_REARM_BUFFER_PT:.0f} "
                          f"body={body:.0%} regime={DAY.regime}")
        if dn_break:
            return True, (f"FUT {c:.0f} < FH_low {DAY.chop_fh_low:.0f}-{CHOP_REARM_BUFFER_PT:.0f} "
                          f"body={body:.0%} regime={DAY.regime}")
        return False, (f"no-break (FUT {c:.0f} in FH {DAY.chop_fh_low:.0f}-{DAY.chop_fh_high:.0f}, "
                       f"body={body:.0%})")
    except Exception as e:
        return False, f"err({e})"

def _morning_chop_verdict_impl(df15m_fut):
    now = datetime.now(IST)
    open_t = now.replace(hour=9, minute=15, second=0, microsecond=0)
    # wait until we have the full first hour settled
    if (now - open_t).total_seconds() / 60 < CHOP_GATE_DECIDE_MIN:
        return False, False, "too-early"
    if df15m_fut is None or len(df15m_fut) < 3:
        return False, False, "no-fut-data"
    df = df15m_fut
    if 'date' in df.columns:
        tmask = df['date'].apply(lambda x: (x.date() if hasattr(x, 'date') else x) == now.date())
        today_df = df[tmask]
    else:
        today_df = df
    fh_end = open_t + timedelta(minutes=CHOP_FH_END_MIN)
    def _bar_time(row):
        v = row['date'] if ('date' in today_df.columns) else row.name
        return v
    fh = []
    for _, row in today_df.iterrows():
        bt = _bar_time(row)
        if hasattr(bt, 'tzinfo'):
            try: bt = bt.astimezone(IST)
            except Exception: pass
        if open_t <= bt <= fh_end:
            fh.append(row)
    if len(fh) < 3:
        return False, False, f"fh-bars={len(fh)}"
    closes = [float(r['close']) for r in fh]
    highs  = [float(r['high'])  for r in fh]
    lows   = [float(r['low'])   for r in fh]
    rng = max(highs) - min(lows)
    # V2.5.18: stash the first-hour FUT range so chop_rearm_check() can detect a
    # later decisive break out of it.
    DAY.chop_fh_high = float(max(highs))
    DAY.chop_fh_low  = float(min(lows))
    net = abs(closes[-1] - closes[0])
    path = sum(abs(closes[i] - closes[i-1]) for i in range(1, len(closes)))
    er = (net / path) if path > 0 else 1.0
    # FUT-VWAP cross count: cumulative session VWAP per first-hour bar
    tpv = 0.0; vol = 0.0; crosses = 0; prev_side = None
    for r in fh:
        tp = (float(r['high']) + float(r['low']) + float(r['close'])) / 3
        v = float(r['volume']) if ('volume' in r and not pd.isna(r['volume'])) else 1.0
        tpv += tp * v; vol += v
        vwap = (tpv / vol) if vol > 0 else tp
        side = float(r['close']) >= vwap
        if prev_side is not None and side != prev_side:
            crosses += 1
        prev_side = side
    is_chop = (er <= CHOP_ER_MAX) and (crosses >= CHOP_VWAP_CROSSES_MIN or rng < CHOP_RANGE_PT_MAX)
    reason = f"ER={er:.2f} crosses={crosses} range={rng:.0f}pt"
    return True, bool(is_chop), reason

def fade_gate_ok(sig, spot, expiry_lookup):
    """V2.5.17 #3: for a 3rd+ consecutive same-side entry that follows >= 2
    consecutive same-side WINS, confirm momentum on 3m option premiums. Enter
    ONLY IF the trend-side option is NOT decaying AND the opposite-side option
    IS decaying. Returns (allowed, info). Fails OPEN on missing data."""
    try:
        return _fade_gate_ok_impl(sig, spot, expiry_lookup)
    except Exception as e:
        lwarn(f"[FADEGATE] error ({e}) — failing OPEN")
        return True, "fade-err"

def _fade_gate_ok_impl(sig, spot, expiry_lookup):
    if not FADE_GATE_ENABLED:
        return True, ""
    side = sig['side']
    opp  = 'PE' if side == 'CE' else 'CE'
    # count consecutive same-side trades at the tail, and how many were wins
    run = 0; wins = 0
    for t in reversed(DAY.trades_today):
        if t.get('side') != side:
            break
        run += 1
        if float(t.get('pnl', 0)) > 0:
            wins += 1
        else:
            break   # streak of CONSECUTIVE wins ends at the first non-win
    # arm only on the 3rd+ same-side entry preceded by >= FADE_MIN_PRIOR_WINS wins
    if run < FADE_MIN_PRIOR_WINS or wins < FADE_MIN_PRIOR_WINS:
        return True, ""
    strike = round_to_atm(spot)
    tk_trend = expiry_lookup.get((strike, side), (None, None))[1]
    tk_opp   = expiry_lookup.get((strike, opp),  (None, None))[1]
    if not tk_trend or not tk_opp:
        return True, f"#{run+1} fade-tokens-missing"
    dft = fetch_option_3m(tk_trend); dfo = fetch_option_3m(tk_opp)
    need = FADE_OPT_BARS + 2
    if dft is None or dfo is None or len(dft) < need or len(dfo) < need:
        linfo(f"[FADEGATE] 3m option data unavailable — allowing #{run+1} {side} by default")
        return True, f"#{run+1} fade-data-missing"
    tc = dft['close'].iloc[:-1]; oc = dfo['close'].iloc[:-1]   # drop forming bar
    trend_move = float(tc.iloc[-1] - tc.iloc[-1 - FADE_OPT_BARS])
    opp_move   = float(oc.iloc[-1] - oc.iloc[-1 - FADE_OPT_BARS])
    trend_not_decaying = trend_move >= -FADE_DECAY_PT
    opp_decaying       = opp_move   <=  FADE_DECAY_PT
    ok = bool(trend_not_decaying and opp_decaying)
    return ok, f"#{run+1} {side}{trend_move:+.1f}/{opp}{opp_move:+.1f} (3m×{FADE_OPT_BARS})"

def fetch_option_15m(token, days_back=10):
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(token, frm, now, "15minute")
    if not rows: return None
    return pd.DataFrame(rows)

def fetch_option_5m(token, days_back=3):
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(token, frm, now, "5minute")
    if not rows: return None
    return pd.DataFrame(rows)

def fetch_option_3m(token, days_back=1):
    """V2.5.17 #3: 3-minute option premium bars for the momentum-fade gate."""
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(token, frm, now, FADE_OPT_TF)
    if not rows: return None
    return pd.DataFrame(rows)

def compute_option_vwap(token: int) -> Optional[float]:
    """Today's session VWAP for an option using 15m bars (from 9:15 AM)."""
    try:
        now = datetime.now(IST)
        frm = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if frm >= now:
            return None  # before today's session open — no VWAP yet, avoid a doomed Kite call
        rows = historical(token, frm, now, "15minute")
        if not rows:
            return None
        df = pd.DataFrame(rows)
        if 'volume' not in df.columns or df['volume'].sum() == 0:
            return None
        tp = (df['high'] + df['low'] + df['close']) / 3
        cum_vol = df['volume'].cumsum()
        cum_tpv = (tp * df['volume']).cumsum()
        vwap_series = cum_tpv / cum_vol.replace(0, np.nan)
        val = vwap_series.iloc[-1]
        return float(val) if not pd.isna(val) else None
    except Exception:
        return None

def sma8_low_of_option(df_opt_15m, entry_time=None):
    """SMA(8, low) over the option's CLOSED 15m bars.
    V2.5.16: restricted to the current session (no stale 10-day / illiquid lows).
    V2.5.18 (FIX C): when entry_time is known, average only TODAY's closed bars
    that CLOSED AFTER entry (bar-start + 15m > entry_time) and require at least
    SMA_TRAIL_MIN_BARS_SINCE_ENTRY of them. This arms the trail on the trade's OWN
    bars, not bars-of-day, so a fresh entry is never judged on pre-entry action.
    With 1 own bar SMA8L == that bar's own low (close>=low can't trigger), so the
    first real exit needs >=2 own bars. Falls back to the old bars-of-day gate
    (SMA_TRAIL_MIN_BARS) only when entry_time is None (state-load edge)."""
    if df_opt_15m is None or len(df_opt_15m) < 2:
        return None
    df = df_opt_15m
    if 'date' in df.columns:
        dates = df['date']
    else:
        dates = pd.Series(list(df.index), index=df.index)
    today = datetime.now(IST).date()
    def _d(x):
        return x.date() if hasattr(x, 'date') else x
    mask = dates.apply(_d) == today
    today_df = df[mask.values if hasattr(mask, 'values') else mask]
    # closed bars only -> exclude the still-forming last bar
    closed = today_df.iloc[:-1]
    if entry_time is not None:
        # keep only bars whose CLOSE time (start + 15m) is strictly after entry
        cdates = closed['date'] if 'date' in closed.columns \
                 else pd.Series(list(closed.index), index=closed.index)
        def _closed_after_entry(x):
            bt = x.astimezone(IST) if hasattr(x, 'astimezone') else x
            try:
                return (bt + timedelta(minutes=15)) > entry_time
            except Exception:
                return False
        keep = cdates.apply(_closed_after_entry)
        closed = closed[keep.values if hasattr(keep, 'values') else keep]
        min_bars = SMA_TRAIL_MIN_BARS_SINCE_ENTRY
    else:
        min_bars = SMA_TRAIL_MIN_BARS
    n = len(closed)
    if n < min_bars:
        return None
    k = min(SMA_TRAIL_PERIOD, n)
    return float(closed['low'].iloc[-k:].mean())

# =========================================================================
# STRIKE SELECTION
# =========================================================================
def round_to_atm(spot):
    return int(round(spot / 100) * 100)

# =========================================================================
# TRADE STATE
# =========================================================================
@dataclass
class TradeState:
    active: bool = False
    engine: str = ""              # 'V2' or 'V3'
    engine_detail: str = ""       # e.g. 'StochRSI-CE' / 'Grade A G-cluster BREAK'
    side: str = ""                # 'CE' or 'PE'
    strike: int = 0
    symbol: str = ""
    ms_symbol: str = ""              # mStock format: NIFTY02JUN23500PE (for order placement)
    buy_order_id: str = ""           # mStock order ID from BUY — used for position verification
    token: int = 0
    entry_time: Optional[datetime] = None
    entry_premium: float = 0.0
    entry_spot: float = 0.0
    trigger_value: float = 0.0    # 1h SMA for V2, cluster center for V3
    declared_target_premium: float = 0.0
    declared_target_spot: Optional[float] = None  # V3 only
    hardsl_premium: float = 0.0   # entry * (1 - HARDSL_PCT)
    sl_current: float = 0.0       # currently active SL (starts == hardsl)
    tr_armed: bool = False        # time-ratchet armed
    tr_sl: float = 0.0            # ratchet SL price
    peak_premium: float = 0.0
    trough_premium: float = 0.0   # 2026-08-29: MAE — worst premium seen in-trade
    atr_entry: float = 0.0        # 2026-08-29: 14-bar ATR of the OPTION at entry
    expiry_date: Optional[date] = None   # 2026-08-29: resolved at entry, NOT parsed
    last_pulse_premium: float = 0.0
    sma8_last_bar_ts: Optional[datetime] = None  # FIX1: last 15m bar ts evaluated for SMA8 trail
    entry_vwap: Optional[float] = None          # V2.5.9+: option VWAP at entry (informational)
    is_paper: bool = False        # V2.5.20 (2026-07-14): this position is NOT held at the
        # broker -- either we're in kite_paper mode, or a live BUY genuinely failed and we
        # fell back to paper. Drives the PAPER banner in fmt_entry/fmt_exit. Before this
        # existed, a paper-fallback exit rendered byte-identically to a broker-confirmed
        # one, which is how 3 orphaned real lots on 2026-07-14 looked like clean exits.
    unconfirmed_fill: bool = False  # V2.5.20 (2026-07-14): broker said COMPLETE with a real
        # fill price, but the position book had not shown the holding yet when we checked.
        # The position is treated as REAL (we own it until proven otherwise) -- this flag
        # only marks that entry was never positively confirmed, for alerting.
    own_sell_order_ids: List[str] = field(default_factory=list)  # V2.5.20 (2026-07-08):
        # every SELL order_id the bot ITSELF has placed for this open position (via
        # close_trade()'s live-SELL attempts, appended even on a failed/timed-out
        # attempt). Used to tell a bot-driven SELL apart from a MANUAL exit the user
        # placed directly at the broker -- see find_manual_sell() and close_trade().

    def to_dict(self):
        d = asdict(self)
        if d.get('entry_time') is not None:
            d['entry_time'] = d['entry_time'].isoformat()
        return d

    def elapsed_min(self):
        if not self.entry_time: return 0
        return (datetime.now(IST) - self.entry_time).total_seconds() / 60.0

    def update_peak(self, current_ltp):
        if current_ltp is not None and current_ltp > self.peak_premium:
            self.peak_premium = current_ltp

POS = TradeState()   # module-global "currently active engine" pointer -- rebound
                      # to POSITIONS[name] before every per-engine call (see
                      # switch_engine() near DAY_STATES below). Every existing
                      # function (check_exits, open_trade, close_trade, Telegram
                      # formatters, CSV logging) reads/writes POS/DAY by module-
                      # global name lookup, so they transparently operate on
                      # whichever engine is currently switched in -- this reuses
                      # all the tested broker/order/exit code unmodified instead
                      # of rewriting 200+ call sites by hand.
POSITIONS = {name: TradeState() for name in SLOT_LIST}   # one independent position per slot

# Daily accounting
@dataclass
class DailyState:
    losses: int = 0                  # NON-FLIP losses only (V2.5.3: CB=4, flips excluded)
    # 2026-08-16: V2-specific same-day loss cap (see V2_DAILY_LOSS_CAP). Separate from
    # `losses` above because that field is shared across V2/V3/FLIP (all use the BASE
    # slot) -- a V3 or FLIP loss must not count against V2's own cap, and vice versa.
    # Backtest basis: real 3mo re-port of V2 logic (2026-05-04->08-06, see
    # orion-notrade-zone-design-attempts-2026-08-16 memory) found capping V2 at 1 loss/day
    # improved the 3-month total from +Rs10,589 to +Rs14,080 (+33%) -- small sample (9
    # multi-trade days), not forward-validated live yet, watch closely.
    v2_losses_today: int = 0
    trades_today: List[dict] = field(default_factory=list)
    halted: bool = False
    levels: dict = None
    regime: str = "INSUFFICIENT"
    gap_suppress_until: Optional[datetime] = None
    fired_levels: set = field(default_factory=set)
    # V2.5.2/4 — flip tracking
    flips_today: int = 0
    last_exit: Optional[dict] = None  # {'side','entry','peak','elapsed_min','exit_time','engine'}
    # Same-direction re-entry cooldown (separate from last_exit, which FLIP consumes/clears)
    last_exit_side: str = ""
    last_exit_at: Optional[datetime] = None
    # Last 15m K seen (for cross-bar K-reversal detection in flip rule)
    last_K_seen: Optional[float] = None
    last_K_prev_seen: Optional[float] = None
    # Persisted flags
    eod_sent: bool = False
    # V2.5.9: straddle monitoring
    straddle_ref: Optional[float] = None
    straddle_morning_sent: bool = False
    straddle_midday_sent: bool = False
    # VWAP bar dedup: store last bar timestamp that fired VWAP entry
    last_vwap_bar_time: Optional[object] = None
    # 2026-08-20: VWAP-specific post-loss cooldown (see VWAP_LOSS_COOLDOWN_MIN) --
    # backtest on the live 24-session log showed VWAP re-firing the same side
    # right after getting stopped out on it (whipsaw re-entry, no regime filter).
    # Blocks a same-side VWAP re-entry for a cooldown window after a VWAP loss
    # on that side. Separate from the generic (currently-disabled) last_exit_side
    # so it doesn't interact with SAME_DIR_REENTRY_GUARD or other engines.
    vwap_last_loss_side: str = ""
    vwap_last_loss_at: Optional[datetime] = None
    # Post-manual-exit cooldown: no re-entry for 5 min after manual close
    manual_exit_cooldown_until: Optional[datetime] = None
    # IA403 consecutive failure tracking — halt after 3, alert on first
    ia403_consecutive: int = 0
    ia403_halted: bool = False
    # V2.5.17 #1: morning chop gate (decided once, then stands aside all day)
    chop_gate_decided: bool = False
    chop_gate_block: bool = False
    chop_gate_reason: str = ""
    # V2.5.18: first-hour FUT range captured at chop verdict (for the re-arm break check)
    chop_fh_high: Optional[float] = None
    chop_fh_low: Optional[float] = None
    # V2.5.19: classic floor-trader pivots from prior day H/L/C {P,S1,R1,S2,R2}
    pivots: dict = None
    # V2.5.19: dedup bar timestamps for the two new FUT-VWAP pathways
    last_fut5_scalp_bar_time: Optional[object] = None
    last_morning_vwap_bar_time: Optional[object] = None
    # 2026-08-13 fix: V2 had no per-bar dedup (unlike VWAP/FUT5VWAP), so an
    # unchanged K/RSI/MACD signal re-fired into every free BASE overlap slot
    # tick after tick until all 5 filled -- see orion-v2520-0812-duplicate-
    # entry-bug memory (5x-stacked V2 lots, both 2026-08-12 and 2026-08-13).
    last_v2_bar_time: Optional[object] = None
    # V2.5.20-fix (2026-07-12): pending V3 probe order (limit buy at signal
    # LTP - V3_PROBE_PULLBACK_PTS), see _place_v3_probe/_manage_v3_probe.
    v3_probe: Optional[dict] = None

    def reset(self):
        self.losses = 0
        self.v2_losses_today = 0
        self.trades_today = []
        self.halted = False
        self.levels = None
        self.regime = "INSUFFICIENT"
        self.gap_suppress_until = None
        self.fired_levels = set()
        self.flips_today = 0
        self.last_exit = None
        self.last_exit_side = ""
        self.last_exit_at = None
        self.last_K_seen = None
        self.last_K_prev_seen = None
        self.eod_sent = False
        self.straddle_ref = None
        self.straddle_morning_sent = False
        self.straddle_midday_sent = False
        self.last_vwap_bar_time = None
        self.vwap_last_loss_side = ""
        self.vwap_last_loss_at = None
        self.manual_exit_cooldown_until = None
        self.ia403_consecutive = 0
        self.ia403_halted = False
        self.chop_gate_decided = False
        self.chop_gate_block = False
        self.chop_gate_reason = ""
        self.chop_fh_high = None
        self.chop_fh_low = None
        self.pivots = None
        self.last_fut5_scalp_bar_time = None
        self.last_morning_vwap_bar_time = None
        self.last_v2_bar_time = None
        self.v3_probe = None

DAY = DailyState()
DAY_STATES = {name: DailyState() for name in ENGINE_LIST}
# overlap slots SHARE their base engine's DailyState (same object) — so signal-dedup + per-day
# counters + regime are shared, and closed trades append to the ONE shared trades_today list.
for _slot in SLOT_LIST:
    if _slot not in DAY_STATES:
        DAY_STATES[_slot] = DAY_STATES[_slot.split("#")[0]]
# ORB/GAPBREAK-only per-day signal state, kept separate from DailyState (which
# is shaped around BASE/VWAP/FUT5VWAP) but set as plain extra attributes on
# their own DailyState instance -- dataclass instances allow this fine.
for _n in ("ORB", "GAPBREAK"):
    DAY_STATES[_n].orb_fired = False
    DAY_STATES[_n].orb_chop_killed = False   # V2.5.20 2026-07-12: in-day CHOPPY kill (sticky/day)
    DAY_STATES[_n].orb_chop_last_cp = ""     # last checkpoint already evaluated ("HH:MM")
    DAY_STATES[_n].orb_sig = None          # {'bar_end','side','spot'} or None, set once/day
    DAY_STATES[_n].gap_fired = False
    DAY_STATES[_n].gap_sig = None          # {'t','side','spot','gap'} or None
    DAY_STATES[_n].gap_pending = None      # confirm-entry wait state
    DAY_STATES[_n].prev_close = None       # yesterday's last spot close (for gap calc)
    DAY_STATES[_n].floor = None            # touch-stop lock floor once armed
    DAY_STATES[_n].is_flip = False         # True on the flip leg (no further flip allowed)
# V2.5.20: FUT5VWAP also uses the shared touch-stop/lock/ride manager (validated
# exit fix) -- needs the same floor/is_flip scratch fields; is_flip stays True
# always (FUT5VWAP never flips on stop, matching the backtest's no-op flip_cb).
DAY_STATES["FUT5VWAP"].floor = None
DAY_STATES["FUT5VWAP"].is_flip = True

# V2.5.20 NEW (2026-07-26): EXPIRY one-shot-per-day scratch state. Uses the
# GENERIC %-HARDSL + continuous-trail exit (does NOT set floor/is_flip/
# hardsl_premium=-1e9 in open_trade -- falls through to the same default path
# BASE/V2/VWAP use), so no floor/is_flip fields needed here.
DAY_STATES["EXPIRY"].expiry_fired = False
DAY_STATES["EXPIRY"].expiry_last_bar_time = None   # dedup, same <= convention as FUT5VWAP fix

# V2.5.20 LIVE: cross-engine circuit breaker. Each engine's own DAY.losses/
# DAY.halted (from the pre-existing per-engine CB code) still tracks its own
# count for reporting, but the actual trip decision now uses this GLOBAL
# total across all 5 engines combined -- 4 bot-driven losses anywhere in the
# combined book halts every engine's new entries, not just the one that hit 4.
TOTAL_LOSSES_TODAY = 0
GLOBAL_HALTED = False

# ---- MANUAL HALT (self-expiring) -------------------------------------------
# 2026-07-13 INCIDENT: this used to be a bare `NO_NEW_ENTRIES_TODAY = True`, set
# on 2026-07-09 as a ONE-DAY halt and then never flipped back. It gates
# _entry_allowed, which gates _common_ok, which EVERY one of the 6 engines checks
# before evaluating -- so all six returned silently, logging nothing, while
# [INDICATORS]/[SIGNAL] kept printing and the bot LOOKED alive. V2.5.20 took zero
# trades on 07-10 and 07-13. On 07-13 alone that cost a shadow-verified ORB CE
# (fired 09:35, +105.7 spot pts in favour) and GAPBREAK CE (09:50, +66.2).
#
# It is now a DATE, not a bool: the halt applies only ON that date and expires by
# itself. A stale halt can no longer survive the day it was set for. Set to a
# date string "YYYY-MM-DD" to halt that day; None = no halt.
HALT_NEW_ENTRIES_ON_DATE = None   # e.g. "2026-07-09"


def no_new_entries_today() -> bool:
    """True only if a manual halt was set for TODAY. Self-expiring by design --
    see the incident note above; never re-introduce a bare boolean here."""
    if not HALT_NEW_ENTRIES_ON_DATE:
        return False
    return datetime.now(IST).strftime("%Y-%m-%d") == HALT_NEW_ENTRIES_ON_DATE


def switch_engine(name):
    """Rebind the module-global POS/DAY to this engine's own state before
    calling any of the (unmodified) shared exit/entry/order/Telegram code --
    every such function reads POS/DAY by module-global name, so this makes
    them operate on the correct engine's independent position transparently."""
    global POS, DAY
    POS = POSITIONS[name]
    DAY = DAY_STATES[name]

# =========================================================================
# STATE PERSISTENCE (atomic JSON)
# =========================================================================
def save_state():
    # V2.5.20: snapshot ALL 5 engines' POS/DAY, not just whichever is currently
    # bound -- a crash/redeploy mid-day must be able to restore every engine's
    # open position and trade history independently, or restart-recovery would
    # silently drop up to 4 of the 5 concurrent positions.
    try:
        engines_snap = {}
        for _name in ENGINE_LIST:
            _pos = POSITIONS[_name]
            _day = DAY_STATES[_name]
            engines_snap[_name] = {
                "pos": _pos.to_dict(),
                "day_losses": _day.losses,
                "day_halted": _day.halted,
                "fired_levels": list(_day.fired_levels),
                "trades_today": _day.trades_today,
                "flips_today": _day.flips_today,
            }
            # V2.5.20: ORB/GAPBREAK/FUT5VWAP one-shot-per-day scratch state was
            # NOT persisted before -- it lived only in the in-memory DailyState,
            # so any mid-day crash/restart silently reset orb_fired/gap_fired
            # back to False, letting a one-shot engine re-evaluate (and
            # potentially re-enter) a signal it had already used up for the
            # day. Persisting these closes that gap; see
            # orion-v2520-restart-persistence-fix memory for the full writeup.
            if _name in ("ORB", "GAPBREAK", "FUT5VWAP"):
                engines_snap[_name]["orb_fired"]   = getattr(_day, "orb_fired", False)
                engines_snap[_name]["gap_fired"]   = getattr(_day, "gap_fired", False)
                engines_snap[_name]["gap_sig"]     = getattr(_day, "gap_sig", None)
                engines_snap[_name]["gap_pending"] = getattr(_day, "gap_pending", None)
                engines_snap[_name]["prev_close"]  = getattr(_day, "prev_close", None)
                engines_snap[_name]["floor"]       = getattr(_day, "floor", None)
                engines_snap[_name]["is_flip"]     = getattr(_day, "is_flip", False)
            if _name == "EXPIRY":
                engines_snap[_name]["expiry_fired"] = getattr(_day, "expiry_fired", False)
            if _name == "BASE":
                engines_snap[_name]["v2_losses_today"] = getattr(_day, "v2_losses_today", 0)
        snap = {"date": datetime.now(IST).strftime("%Y-%m-%d"), "engines": engines_snap,
                "total_losses_today": TOTAL_LOSSES_TODAY, "global_halted": GLOBAL_HALTED}
        tmp = STATE_FN + ".tmp"
        with open(tmp, "w") as f:
            json.dump(snap, f, default=str)
        os.replace(tmp, STATE_FN)
    except Exception as e:
        lwarn(f"save_state failed: {e}")

def load_state():
    # V2.5.20: restore ALL 5 engines' POS/DAY from the "engines" snapshot.
    if not os.path.exists(STATE_FN): return
    try:
        with open(STATE_FN) as f:
            snap = json.load(f)
        engines_snap = snap.get("engines", {})
        _snap_date = snap.get("date", "")
        _today_str = datetime.now(IST).strftime("%Y-%m-%d")
        _is_new_day = bool(_snap_date) and _snap_date != _today_str
        global TOTAL_LOSSES_TODAY, GLOBAL_HALTED
        TOTAL_LOSSES_TODAY = 0 if _is_new_day else snap.get("total_losses_today", 0)
        # Deliberate restart mid-day = manual reset, same policy as the
        # pre-existing per-engine halted reset below.
        GLOBAL_HALTED = False
        if TOTAL_LOSSES_TODAY >= CIRCUIT_BREAKER:
            linfo(f"[STATE] Global circuit breaker was tripped (total_losses={TOTAL_LOSSES_TODAY}) — RESET on bot restart.")
            TOTAL_LOSSES_TODAY = 0
        for _name in ENGINE_LIST:
            esnap = engines_snap.get(_name)
            if not esnap:
                continue
            _pos = POSITIONS[_name]
            _day = DAY_STATES[_name]
            _esnap_pos = esnap.get("pos", {})
            if _esnap_pos.get("active"):
                # V2.5.20 (2026-07-14 fix): RESUME an active position with no
                # buy_order_id as a PAPER position -- do not discard it.
                #
                # The previous guard DELETED any active position that had no
                # buy_order_id while in mstock_live mode. That silently destroyed
                # every paper-fallback trade across a restart: the position vanished
                # from state, check_exits() never saw it again, and no exit card was
                # ever sent. That is exactly what stranded the 2026-07-14 GAPBREAK
                # PE (entry 87.15, buy_order_id="") -- the bot restarted and the
                # trade simply ceased to exist, with no square-off on Telegram.
                #
                # The guard's real concern -- never fire a REAL SELL for something
                # never actually bought -- is already fully handled in close_trade(),
                # which gates its live-SELL block on `POS.buy_order_id` being set.
                # So resuming a paper position is safe: it gets stops, trail, force
                # close and a Telegram exit card, but never touches the broker.
                #
                # But NEVER carry a position across a day boundary: the option it
                # names has almost certainly expired (the stranded 2026-07-14 lot was
                # a same-day-expiry PE), so "resuming" it on a later date would mean
                # managing a dead contract. A stale one is dropped loudly, not
                # silently -- the old code's failure mode was the silence.
                if _is_new_day:
                    lwarn(f"[STATE][{_name}] Dropping STALE position "
                          f"{_esnap_pos.get('symbol')} carried over from {_snap_date} "
                          f"— contract is from a previous session, not resuming it.")
                    TG.send(f"⚠️ <b>Stale position dropped at boot</b>\n"
                            f"[{_name}] {_esnap_pos.get('symbol')} @ "
                            f"₹{_esnap_pos.get('entry_premium', 0):.2f} was still marked open "
                            f"from {_snap_date}.\n"
                            f"It was NOT resumed (contract is from a previous session). "
                            f"If a real lot is still at your broker, square it off manually.")
                else:
                    if EXECUTION_BROKER == "mstock_live" and not _esnap_pos.get("buy_order_id"):
                        _esnap_pos = dict(_esnap_pos)
                        _esnap_pos["is_paper"] = True
                        linfo(f"[STATE][{_name}] Resuming PAPER position "
                              f"{_esnap_pos.get('symbol')} (no buy_order_id) — will be "
                              f"exited and reported as PAPER; no real SELL will be sent.")
                    for k, v in _esnap_pos.items():
                        if k == "entry_time" and v:
                            v = datetime.fromisoformat(v).astimezone(IST)
                        elif k == "expiry_date" and isinstance(v, str):
                            # 2026-09-16: json.dump(default=str) wrote the date as 'YYYY-MM-DD';
                            # parse it back or record_trade()'s dte subtraction raises (09-15 lost row)
                            try: v = datetime.strptime(v[:10], "%Y-%m-%d").date() if v else None
                            except Exception: v = None
                        setattr(_pos, k, v)
            _day.losses = esnap.get("day_losses", 0)
            _day.halted = esnap.get("day_halted", False)
            _day.fired_levels = set(esnap.get("fired_levels", []))
            _day.trades_today = esnap.get("trades_today", [])
            _day.flips_today = esnap.get("flips_today", 0)
            if _name in ("ORB", "GAPBREAK", "FUT5VWAP") and not _is_new_day:
                # Restore the one-shot-per-day scratch state so a mid-day
                # crash/restart can't accidentally re-arm an engine that
                # already used (or correctly stood down) its one signal for
                # today. gap_sig/gap_pending carry a pandas Timestamp that
                # json.dump(default=str) stringified -- parse it back so
                # later `df5['date'] > pend['last_bar_time']` comparisons
                # still work against the live dataframe's datetime column.
                _day.orb_fired = esnap.get("orb_fired", False)
                _day.gap_fired = esnap.get("gap_fired", False)
                _gap_sig = esnap.get("gap_sig")
                if _gap_sig and _gap_sig.get("bar_time"):
                    _gap_sig["bar_time"] = pd.Timestamp(_gap_sig["bar_time"])
                _day.gap_sig = _gap_sig
                _gap_pending = esnap.get("gap_pending")
                if _gap_pending and _gap_pending.get("last_bar_time"):
                    _gap_pending["last_bar_time"] = pd.Timestamp(_gap_pending["last_bar_time"])
                _day.gap_pending = _gap_pending
                _day.prev_close = esnap.get("prev_close")
                _day.floor = esnap.get("floor")
                _day.is_flip = esnap.get("is_flip", False)
                linfo(f"[STATE][{_name}] Restored one-shot state: orb_fired={_day.orb_fired} "
                      f"gap_fired={_day.gap_fired}")
            if _name == "EXPIRY" and not _is_new_day:
                _day.expiry_fired = esnap.get("expiry_fired", False)
                linfo(f"[STATE][{_name}] Restored one-shot state: expiry_fired={_day.expiry_fired}")
            if _name == "BASE" and not _is_new_day:
                _day.v2_losses_today = esnap.get("v2_losses_today", 0)
            if _is_new_day:
                linfo(f"[STATE][{_name}] State from {_snap_date} — resetting trades_today for {_today_str}")
                _day.trades_today = []
                _day.losses = 0
                _day.flips_today = 0
                if _name in ("ORB", "GAPBREAK"):
                    # New day: DAY_STATES[_name] was just freshly constructed
                    # (orb_fired/gap_fired default False already) -- explicitly
                    # documenting that we deliberately do NOT restore yesterday's
                    # fired state here, unlike the not-a-new-day branch above.
                    _day.orb_fired = False
                    _day.gap_fired = False
                    _day.gap_sig = None
                    _day.gap_pending = None
                    _day.orb_chop_killed = False
                    _day.orb_chop_last_cp = ""
                if _name == "EXPIRY":
                    _day.expiry_fired = False
                if _name == "BASE":
                    _day.v2_losses_today = 0
                    _day.expiry_last_bar_time = None
            # Reset circuit breaker on every fresh bot start — deliberate restart = manual reset
            if _day.halted:
                linfo(f"[STATE][{_name}] Circuit breaker was halted (losses={_day.losses}) — RESET on bot restart.")
                _day.halted = False
                _day.losses = 0
            linfo(f"[STATE][{_name}] Loaded prior state. active={_pos.active} losses={_day.losses}")
    except Exception as e:
        lwarn(f"load_state failed: {e}")

# =========================================================================
# CSV BAR CAPTURE  (every 5 min)
# =========================================================================
CSV_HEADER = ["ts","spot","1h_close","1h_sma20","1h_sma50","1h_rsi","15m_K","15m_K_prev",
              "regime","pos_active","pos_side","pos_engine","pos_strike","pos_ltp","pos_pnl_pct",
              "pos_sl","tr_armed","tr_sl","peak_prem","day_losses","flips_today","halted","chop_block"]
def csv_init():
    if not os.path.exists(CSV_FN):
        with open(CSV_FN, "w", newline="") as f:
            csv.writer(f).writerow(CSV_HEADER)

def csv_append(row):
    try:
        with open(CSV_FN, "a", newline="") as f:
            csv.writer(f).writerow(row)
    except Exception as e:
        lwarn(f"csv_append failed: {e}")

# =========================================================================
# =========================================================================
# TELEGRAM FORMATTERS  (V2.5.5 — HTML/emoji enhanced for visual differentiation)
# =========================================================================

def fmt_boot(target_expiry, levels):
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    g_str = (f"<code>{levels['G']['center']:.0f}</code> (Grade {levels['G']['grade']})"
             if levels and levels['G'] else "—")
    r_str = (f"<code>{levels['R']['center']:.0f}</code> (Grade {levels['R']['grade']})"
             if levels and levels['R'] else "—")

    # Build full A+B cluster list for display
    cluster_lines = ""
    if levels:
        pdc = levels.get('pdc', 0)
        buf = V3_MIN_BUFFER_FROM_PDC
        ab_above = sorted(
            [c for c in levels.get('all_clusters', []) if c['center'] > pdc + buf and c['grade'] in ('A','B')],
            key=lambda c: c['center']
        )
        ab_below = sorted(
            [c for c in levels.get('all_clusters', []) if c['center'] < pdc - buf and c['grade'] in ('A','B')],
            key=lambda c: c['center'], reverse=True
        )
        if ab_above:
            parts = " | ".join(f"<code>{c['center']:.0f}</code>[{c['grade']}]" for c in ab_above[:6])
            cluster_lines += f"   ↑ Above: {parts}\n"
        if ab_below:
            parts = " | ".join(f"<code>{c['center']:.0f}</code>[{c['grade']}]" for c in ab_below[:6])
            cluster_lines += f"   ↓ Below: {parts}\n"

    return (
        f"🚀🚀🚀 <b>ORION {VERSION} BOOT</b> 🚀🚀🚀\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Mode:</i> <b>{MODE}</b>\n"
        f"<i>Boot time:</i> {now_str}\n"
        f"<i>Target expiry:</i> <b>{tg_escape(target_expiry)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>V3 LEVELS (prior day 1h)</b>\n"
        f"   PDH: <code>{levels['pdh']:.2f}</code>  |  PDL: <code>{levels['pdl']:.2f}</code>  |  PDC: <code>{levels['pdc']:.2f}</code>\n"
        f"   🟢 G (nearest above PDC): {g_str}\n"
        f"   🔴 R (nearest below PDC): {r_str}\n"
        f"{cluster_lines}"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 <b>V2 ENTRY CONDITIONS</b>\n"
        f"   🟢 CE: 1h close&gt;SMA20&gt;SMA50 | K&gt;={STOCHRSI_CE_LO} rising | K&lt;{K_OVERSOLD_THRESH} recently | RSI&gt;{RSI_CE_MIN} | MACD bull | prem {PREMIUM_MIN}-{PREMIUM_MAX}\n"
        f"   🔴 PE: 1h close&lt;SMA20&lt;SMA50 | K&lt;={STOCHRSI_PE_HI} falling K&gt;={V2_K_FLOOR_PE} | K&gt;{K_OVERBOUGHT_THRESH} recently | RSI&lt;{RSI_PE_MAX} | MACD bear | prem {PREMIUM_MIN}-{PREMIUM_MAX}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡 <b>EXIT PARAMS</b>\n"
        f"   🛑 HARDSL: <b>-{int(HARDSL_PCT*100)}%</b> on premium\n"
        f"   🎯 Trail: arms at entry+{FIXED_TP_PTS}, SL=peak−{TRAIL_STEP_PTS} (floor +{TRAIL_FLOOR_PTS})\n"
        f"   📉 SMA Trail: 15m option SMA({SMA_TRAIL_PERIOD}, low)\n"
        f"   ⛔ Force close: {FORCE_CLOSE_HOUR:02d}:{FORCE_CLOSE_MIN:02d} IST\n"
        f"   🔁 Flip cap: {MAX_FLIPS_PER_DAY}/day  |  Circuit breaker: {CIRCUIT_BREAKER} non-flip losses TOTAL across all {len(ENGINE_LIST)} engines\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>CSV:</i> <code>{tg_escape(CSV_FN)}</code>\n"
        f"<i>Log:</i> <code>{tg_escape(LOG_FN)}</code>"
    )

def fmt_live_state(spot, c1h, sma20, sma50, K, K_prev, regime):
    k_arrow = "↗️" if (K is not None and K_prev is not None and K > K_prev) else \
              ("↘️" if (K is not None and K_prev is not None and K < K_prev) else "→")
    regime_em = {"BULL":"🟢","BEAR":"🔴","CHOP":"🟡","TRANSITION":"🔵"}.get(regime, "⚪")
    return (
        f"📡 <b>LIVE STATE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"   Spot: <b>{spot:.2f}</b>\n"
        f"   1h close: <code>{c1h:.2f}</code>  SMA20: <code>{sma20:.2f}</code>  SMA50: <code>{sma50:.2f}</code>\n"
        f"   15m K: <b>{K:.2f}</b> {k_arrow} (prev {K_prev:.2f})\n"
        f"   {regime_em} Regime: <b>{regime}</b>"
    )

def fmt_pulse(spot, c1h, sma20, sma50, K, K_prev, regime):
    now_str = datetime.now(IST).strftime("%H:%M")
    k_rise = K is not None and K_prev is not None and K > K_prev
    k_fall = K is not None and K_prev is not None and K < K_prev
    k_arrow = "↗️" if k_rise else "↘️" if k_fall else "→"
    # Regime emoji
    regime_em = {"BULL":"🟢","BEAR":"🔴","CHOP":"🟡","TRANSITION":"🔵"}.get(regime, "⚪")
    # Subdued pulse header
    head = (
        f"💓 <i>Pulse · {now_str}</i>  |  Nifty <b>{spot:.1f}</b>\n"
        f"   {regime_em} Regime: <b>{regime}</b>\n"
        f"   1h: {c1h:.2f}  SMA20: {sma20:.2f}  SMA50: {sma50:.2f}\n"
        f"   15m K: <b>{K:.1f}</b> {k_arrow} (prev {K_prev:.1f})\n"
    )
    # V2.5.20: up to 5 independent engines can each hold a position at once --
    # show one ACTIVE block per engine that's active, plus a one-line summary
    # for each idle one. Iterating switch_engine() here mutates the module-
    # global POS/DAY as a side effect (restored by the caller afterward, same
    # convention as the main loop's per-engine dispatch).
    any_active = False
    for _name in ENGINE_LIST:
        switch_engine(_name)
        if not POS.active:
            continue
        any_active = True
        ltp_now = POS.last_pulse_premium or POS.entry_premium
        pct = (ltp_now - POS.entry_premium) / POS.entry_premium * 100
        elapsed = int(POS.elapsed_min())
        side_em = "🟢" if POS.side == "CE" else ("🔴" if POS.side == "PE" else "🟠")
        engine_em = {"V2":"⚙️", "V3":"🎯", "FLIP":"🔄", "VWAP":"📈", "FUT5VWAP":"⏱️",
                     "ORB":"🌅", "GAPBREAK":"🧨", "EXPIRY":"💥"}.get(POS.engine, "")
        pnl_em = "📈" if pct > 0 else "📉" if pct < 0 else "➖"
        if POS.tr_armed:
            pts_locked = round(POS.tr_sl - POS.entry_premium, 1)
            tr_str = f"🎯 <b>TRAIL</b> SL=<code>{POS.tr_sl:.2f}</code> (+{pts_locked:.0f}pts locked)"
        elif POS.engine in ('ORB', 'GAPBREAK', 'FUT5VWAP'):
            tr_str = f"touch-stop/lock (floor={DAY.floor})"
        else:
            tp_price = POS.entry_premium + FIXED_TP_PTS
            tr_str = f"watching — trail arms at <code>{tp_price:.2f}</code> (entry+{FIXED_TP_PTS})"
        active_sl = max(POS.hardsl_premium, POS.tr_sl if POS.tr_armed else 0)
        cur_vwap = compute_option_vwap(POS.token)
        vwap_pulse = ""
        if cur_vwap:
            v_diff = ltp_now - cur_vwap
            v_pos = "above" if v_diff >= 0 else "below"
            vwap_pulse = f"\n   📊 VWAP: <code>{cur_vwap:.2f}</code>  (LTP {abs(v_diff):.1f}pts {v_pos})"
        head += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{side_em} <b>ACTIVE [{_name}]</b> {engine_em} <b>{POS.side}</b> {tg_escape(POS.symbol)}\n"
            f"   {pnl_em} LTP: <b>{ltp_now:.2f}</b> ({pct:+.1f}%) | Entry: <code>{POS.entry_premium:.2f}</code>\n"
            f"   🎯 Target: <code>{POS.declared_target_premium:.2f}</code>  "
            f"🛑 SL: <b>{active_sl:.2f}</b>\n"
            f"   🚀 Peak: <code>{POS.peak_premium:.2f}</code>  ⏱️ Elapsed: <b>{elapsed}min</b>\n"
            f"   Ratchet: {tr_str}{vwap_pulse}\n"
            f"   🔁 Flips: {DAY.flips_today}/{MAX_FLIPS_PER_DAY} · ⛔ Losses: {DAY.losses}/{CIRCUIT_BREAKER}"
        )
    if not any_active:
        switch_engine("BASE")
        flips_str  = f"🔁 Flips: {DAY.flips_today}/{MAX_FLIPS_PER_DAY}"
        losses_str = f"⛔ Non-flip losses: {DAY.losses}/{CIRCUIT_BREAKER}"
        head += f"   <i>No active position (any engine).</i>  {flips_str}  ·  {losses_str}"
        if DAY.halted:
            head += "\n   🛑 <b>HALTED by circuit breaker</b>"
    return head

def fmt_entry():
    """V2.5.5: visual differentiation via emojis and HTML formatting.
    - CE buys: GREEN markers (🟢 🍏)
    - PE buys: RED markers (🔴 🍎)
    - FLIP buys: ORANGE/cycling markers (🔄 🟠)
    """
    side = POS.side
    engine = POS.engine
    if engine == 'FLIP':
        banner = "🔄🔄🔄 <b>FLIP TRADE</b> 🔄🔄🔄"
        side_color = "🟠"
    elif side == 'CE':
        banner = "🟢🟢🟢 <b>BUY CE (Bullish)</b> 🟢🟢🟢"
        side_color = "🟢"
    else:  # PE
        banner = "🔴🔴🔴 <b>BUY PE (Bearish)</b> 🔴🔴🔴"
        side_color = "🔴"

    if POS.engine in ("V2", "FLIP"):
        declared_str = f"<b>+25%</b> premium = <code>{POS.declared_target_premium:.2f}</code>"
    elif POS.engine == "VWAP":
        declared_str = "VWAP trail — no fixed target"
    elif POS.engine == "FUT5VWAP":
        declared_str = (f"touch-stop <b>-{int(FUT5_FIX_STOP_PTS)}pt</b> / lock "
                        f"<b>+{int(FUT5_FIX_LOCK_PTS)}pt</b> / ride+{int(FUT5_RIDE_TRIGGER_PTS)}−{int(FUT5_RIDE_GIVEBACK_PTS)} "
                        f"(no flip)")
    elif POS.engine == "ORB":
        declared_str = (f"touch-stop <b>-{int(ORB_STOP_PTS)}pt</b> / lock "
                        f"<b>+{int(ORB_LOCK_PTS)}pt</b> / ride+{int(ORB_RIDE_TRIGGER_PTS)}−{int(ORB_RIDE_GIVEBACK_PTS)} "
                        f"(1 flip on stop)")
    elif POS.engine == "GAPBREAK":
        declared_str = (f"touch-stop <b>-{int(GAP_STOP_PTS)}pt</b> / lock "
                        f"<b>+{int(GAP_LOCK_PTS)}pt</b> / ride+{int(GAP_RIDE_TRIGGER_PTS)}−{int(GAP_RIDE_GIVEBACK_PTS)} "
                        f"(1 flip on stop)")
    elif POS.declared_target_spot:
        declared_str = f"spot <code>{POS.declared_target_spot:.0f}</code> (cluster T1)"
    else:
        declared_str = "—"
    entry_t = POS.entry_time.strftime('%H:%M:%S') if POS.entry_time else "—"

    vwap_line = ""
    if POS.entry_vwap:
        diff = POS.entry_premium - POS.entry_vwap
        pos_neg = "above" if diff >= 0 else "below"
        vwap_line = f"\n   📊 <b>VWAP</b>: <code>{POS.entry_vwap:.2f}</code>  (entry <b>{abs(diff):.1f}pts {pos_neg}</b> VWAP)"

    return (
        f"🆕 <b>{VERSION}</b> · <b>[{engine}]</b>\n"
        f"{_exec_banner()}"
        f"{banner}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{side_color} <b>{tg_escape(POS.symbol)}</b>  @  <b>₹{POS.entry_premium:.2f}</b>\n"
        f"   Engine: <b>{engine}</b> · {tg_escape(POS.engine_detail)}\n"
        f"   ATM Strike: <code>{POS.strike}</code>  |  Spot: <code>{POS.entry_spot:.2f}</code>\n"
        f"   ⏰ Entry time: <b>{entry_t}</b>\n"
        f"   Trigger: <code>{POS.trigger_value:.2f}</code>{vwap_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Target</b> (declared): {declared_str}\n"
        + (
            f"⛔ <b>Square-off</b>: "
            f"{(ORB_SQOFF_H if POS.engine=='ORB' else GAP_SQOFF_H if POS.engine=='GAPBREAK' else FUT5_SQOFF_H):02d}:"
            f"{(ORB_SQOFF_M if POS.engine=='ORB' else GAP_SQOFF_M if POS.engine=='GAPBREAK' else FUT5_SQOFF_M):02d} IST\n"
            if POS.engine in ('ORB', 'GAPBREAK', 'FUT5VWAP') else
            (
            f"🛑 <b>HARDSL</b>: <code>{POS.hardsl_premium:.2f}</code>  (-{int(V2_HARDSL_PTS)}pt)\n"
            f"🎯 <b>Trail trigger</b>: entry+{POS.entry_premium*V2_TRAIL_ARM_PCT:.1f} = <code>{POS.entry_premium * (1+V2_TRAIL_ARM_PCT):.2f}</code>\n"
            f"📈 <b>Trail</b>: SL = peak−{POS.entry_premium*V2_TRAIL_STEP_PCT:.1f}  (floor entry+{POS.entry_premium*V2_TRAIL_FLOOR_PCT:.1f}=<code>{POS.entry_premium*(1+V2_TRAIL_FLOOR_PCT):.2f}</code>)\n"
            f"⛔ <b>Force close</b>: {FORCE_CLOSE_HOUR:02d}:{FORCE_CLOSE_MIN:02d} IST\n"
            if POS.engine == 'V2' else
            f"🛑 <b>HARDSL</b>: <code>{POS.hardsl_premium:.2f}</code>  (-{int(HARDSL_PCT*100)}%)\n"
            f"🎯 <b>Trail trigger</b>: entry+{FIXED_TP_PTS} = <code>{POS.entry_premium + FIXED_TP_PTS:.2f}</code>\n"
            f"📈 <b>Trail</b>: SL = peak−{TRAIL_STEP_PTS}  (floor entry+{TRAIL_FLOOR_PTS}=<code>{POS.entry_premium+TRAIL_FLOOR_PTS:.2f}</code>)\n"
            f"⛔ <b>Force close</b>: {FORCE_CLOSE_HOUR:02d}:{FORCE_CLOSE_MIN:02d} IST\n"
            )
        ) +
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Actual exit driven by HARDSL / Fixed TP / Trail / Flip-rule.</i>"
    )

def _exec_banner():
    """V2.5.20 (2026-07-14): every Telegram entry/exit card must say, unambiguously,
    whether real money is at the broker. Before this, fmt_exit() looked at neither
    EXECUTION_BROKER nor buy_order_id, so a paper-fallback exit rendered byte-identically
    to a broker-confirmed one -- the reason 3 orphaned real lots on 2026-07-14 read as
    clean ✅ WIN exits on the phone while they sat unmanaged at the exchange."""
    if POS.is_paper:
        return ("📄📄 <b>PAPER — NO REAL ORDER</b> 📄📄\n"
                "<i>Nothing is held at the broker. This P&amp;L is simulated.</i>\n")
    if POS.unconfirmed_fill:
        return ("🚨 <b>LIVE — FILL UNCONFIRMED BY POSITION BOOK</b> 🚨\n"
                "<i>Managed as a real position. Verify at your broker.</i>\n")
    return "💰 <b>LIVE — REAL ORDER AT BROKER</b>\n"


def fmt_exit(reason, exit_price, pnl_per_share):
    elapsed = int(POS.elapsed_min())
    pct = pnl_per_share / POS.entry_premium * 100 if POS.entry_premium else 0
    rs  = pnl_per_share * LOT_SIZE * lots_for(POS.engine)
    # Cumulative day PnL including this trade (called before append, so add current pnl)
    day_total_rs = (sum(t['pnl'] * lots_for(t.get('engine','')) for t in DAY.trades_today)
                    + pnl_per_share * lots_for(POS.engine)) * LOT_SIZE
    n_trades = len(DAY.trades_today) + 1
    day_em = "🟢" if day_total_rs > 0 else "🔴" if day_total_rs < 0 else "⚪"
    # V2.5.20 (2026-07-14 fix): the line above is only THIS ENGINE's day PnL (DAY is
    # rebound per-engine by switch_engine), but it was labelled just "day PnL". With 6
    # engines trading concurrently no exit card ever showed the real number, so the
    # figure on the phone never matched the account. Add the true all-engine total.
    all_rs = (sum(t['pnl'] * lots_for(t.get('engine', ''))
                  for _n in ENGINE_LIST for t in DAY_STATES[_n].trades_today)
              + pnl_per_share * lots_for(POS.engine)) * LOT_SIZE
    all_n = sum(len(DAY_STATES[_n].trades_today) for _n in ENGINE_LIST) + 1
    all_em = "🟢" if all_rs > 0 else "🔴" if all_rs < 0 else "⚪"
    # Visual outcome marker
    if pnl_per_share > 0:
        banner = "✅✅ <b>EXIT — WIN</b> ✅✅"
        outcome = "🟢"
    elif pnl_per_share < 0:
        banner = "❌❌ <b>EXIT — LOSS</b> ❌❌"
        outcome = "🔴"
    else:
        banner = "⚪ <b>EXIT — FLAT</b> ⚪"
        outcome = "⚪"
    side_color = "🟢" if POS.side == "CE" else "🔴"
    vwap_exit = ""
    if POS.entry_vwap:
        e_diff = POS.entry_premium - POS.entry_vwap
        x_diff = exit_price - POS.entry_vwap
        vwap_exit = (f"\n   📊 VWAP: <code>{POS.entry_vwap:.2f}</code>  "
                     f"(entry {e_diff:+.1f} / exit {x_diff:+.1f} vs VWAP)")
    return (
        f"🆕 <b>{VERSION}</b> · <b>[{POS.engine}]</b>\n"
        f"{_exec_banner()}"
        f"{banner}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{outcome} <b>{tg_escape(reason)}</b>\n"
        f"{side_color} {POS.side} {tg_escape(POS.symbol)} @ <b>₹{exit_price:.2f}</b>\n"
        f"   Engine: <b>{POS.engine}</b> · Entry: <code>{POS.entry_premium:.2f}</code>{vwap_exit}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 PnL/share: <b>{pnl_per_share:+.2f}</b> ({pct:+.1f}%)\n"
        f"💵 PnL: <b>₹{rs:+,.0f}</b>  ({lots_for(POS.engine)} lots × {LOT_SIZE})\n"
        f"🚀 Peak premium: <code>{POS.peak_premium:.2f}</code>\n"
        f"⏱️ Duration: <b>{elapsed} min</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{day_em} [{POS.engine}] engine day PnL: <b>₹{day_total_rs:+,.0f}</b> ({n_trades} trade{'s' if n_trades != 1 else ''})\n"
        f"{all_em} <b>ALL ENGINES day PnL: ₹{all_rs:+,.0f}</b> ({all_n} trade{'s' if all_n != 1 else ''})\n"
        f"🔁 Flips today: <b>{DAY.flips_today}/{MAX_FLIPS_PER_DAY}</b>  |  "
        f"⛔ Non-flip losses: <b>{DAY.losses}/{CIRCUIT_BREAKER}</b>"
    )

def fmt_eod_summary():
    # V2.5.20: aggregate across all 5 independent engines -- each has its OWN
    # DAY_STATES.trades_today; a single-engine view here would silently drop
    # the other 4 engines' entire day from the report. Every trade dict already
    # carries its own 'engine' tag (set in close_trade from POS.engine at close
    # time), so combining the 5 lists and grouping by that tag is safe.
    all_trades = []
    flips_total = 0
    losses_total = 0
    for _name in ENGINE_LIST:
        all_trades.extend(DAY_STATES[_name].trades_today)
        flips_total  += DAY_STATES[_name].flips_today
        losses_total += DAY_STATES[_name].losses

    n = len(all_trades)
    ce = [t for t in all_trades if t['side']=='CE']
    pe = [t for t in all_trades if t['side']=='PE']
    ce_w = sum(1 for t in ce if t['pnl']>0); ce_l = sum(1 for t in ce if t['pnl']<0)
    pe_w = sum(1 for t in pe if t['pnl']>0); pe_l = sum(1 for t in pe if t['pnl']<0)
    total_pnl = sum(t['pnl'] for t in all_trades)
    total_rs = sum(t['pnl'] * lots_for(t.get('engine','')) for t in all_trades) * LOT_SIZE
    wr = (ce_w + pe_w) / n * 100 if n else 0
    reasons = {}
    for t in all_trades:
        reasons[t['reason']] = reasons.get(t['reason'], 0) + 1
    by_engine = {}
    for t in all_trades:
        by_engine.setdefault(t['engine'], {'n':0, 'pnl':0})
        by_engine[t['engine']]['n']  += 1
        by_engine[t['engine']]['pnl'] += t['pnl']
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    best  = max(all_trades, key=lambda t: t['pnl']) if all_trades else None
    worst = min(all_trades, key=lambda t: t['pnl']) if all_trades else None

    overall_em = "🟢" if total_rs > 0 else "🔴" if total_rs < 0 else "⚪"
    parts = [
        f"📋📋 <b>EOD SUMMARY</b> {today_str}  ·  ORION {VERSION} ({MODE}) 📋📋",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"{overall_em} <b>Net PnL: ₹{total_rs:+,.0f}</b>  ({total_pnl:+.2f}/share, WR {wr:.1f}%)",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Total trades ({len(ENGINE_LIST)} engines): <b>{n}</b>",
        f"   🟢 CE: {len(ce)} (W:{ce_w} L:{ce_l})",
        f"   🔴 PE: {len(pe)} (W:{pe_w} L:{pe_l})",
        f"   🔁 Flips: <b>{flips_total}/{MAX_FLIPS_PER_DAY}</b> (per-engine cap; effectively unlimited)",
        f"   ⛔ Non-flip losses: <b>{losses_total}/{CIRCUIT_BREAKER}</b> total across all engines"
        + (" — <b>HALTED today</b>" if GLOBAL_HALTED else ""),
    ]
    if best is not None:
        parts.append(f"🏆 Best:  <code>{tg_escape(best['symbol'])}</code> {best['pnl']/best['entry']*100:+.1f}% [{best['engine']}]")
    if worst is not None and worst is not best:
        parts.append(f"💀 Worst: <code>{tg_escape(worst['symbol'])}</code> {worst['pnl']/worst['entry']*100:+.1f}% [{worst['engine']}]")
    if by_engine:
        eng_str = ", ".join(f"<b>{k}</b>={v['n']}/{v['pnl']:+.1f}" for k,v in by_engine.items())
        parts.append(f"⚙️ By engine: {eng_str}")
    if reasons:
        r_str = ", ".join(f"<i>{tg_escape(k)}</i>:{v}" for k,v in sorted(reasons.items(), key=lambda x:-x[1]))
        parts.append(f"🚪 Exit reasons: {r_str}")
    # 2026-08-29: EXP12 is a SEPARATE paper book (own lot size, own CSV) and is
    # deliberately excluded from Net PnL above. It used to be omitted entirely,
    # so 08-27 reported Rs0 on a day EXP2 made +Rs3,378. Show it, clearly
    # labelled, so the two totals are visible without ever being mixed.
    if EXP12_DAY_TRADES or EXP12_DAY_RS:
        _sh = "🟩" if EXP12_DAY_RS > 0 else "🟥" if EXP12_DAY_RS < 0 else "⬜"
        _sbrk = ", ".join(f"{k}={v[1]}tr/₹{v[0]:+,.0f}"
                          for k, v in sorted(EXP12_ENG_RS.items())) or "-"
        parts.append("━━━━━━━━━━━━━━━━━━━━━━")
        parts.append(f"⚫ <b>SHADOW BOOK (EXP12)</b> — <i>separate, NOT in Net PnL above</i>")
        parts.append(f"   {_sh} ₹{EXP12_DAY_RS:+,.0f} over {EXP12_DAY_TRADES} trade(s), lot {EXP12_LOT}")
        parts.append(f"   {_sbrk}")
    parts.append("━━━━━━━━━━━━━━━━━━━━━━")
    parts.append(f"<i>CSV:</i> <code>{tg_escape(CSV_FN)}</code>")
    parts.append(f"<i>Log:</i> <code>{tg_escape(LOG_FN)}</code>")
    return "\n".join(parts)

# =========================================================================
# ENTRY HELPERS (V2.5.9)
# =========================================================================
def k_was_extreme_live(side: str, df15m, bars_back: int = K_EXTREME_BARS) -> bool:
    """V2.5.8: return True if K was recently extreme — CE: K<25 recently, PE: K>75 recently."""
    if df15m is None or len(df15m) < bars_back + 2:
        return False
    for i in range(bars_back + 1):
        idx = -2 - i
        if abs(idx) > len(df15m):
            break
        k_val = df15m['K'].iloc[idx]
        if pd.isna(k_val):
            continue
        k_val = float(k_val)
        if side == 'CE' and k_val < K_OVERSOLD_THRESH:
            return True
        if side == 'PE' and k_val > K_OVERBOUGHT_THRESH:
            return True
    return False

def fetch_atm_straddle(expiry_lookup, spot) -> tuple:
    """Return (ce_ltp, pe_ltp, total_straddle) for ATM strike, or (None, None, None)."""
    atm = round_to_atm(spot)
    ce_key = (atm, 'CE')
    pe_key = (atm, 'PE')
    if ce_key not in expiry_lookup or pe_key not in expiry_lookup:
        return None, None, None
    ce_sym, _ = expiry_lookup[ce_key]
    pe_sym, _ = expiry_lookup[pe_key]
    ce_ltp = ltp(ce_sym)
    pe_ltp = ltp(pe_sym)
    if ce_ltp is None or pe_ltp is None or ce_ltp <= 0 or pe_ltp <= 0:
        return None, None, None
    return ce_ltp, pe_ltp, ce_ltp + pe_ltp

# =========================================================================
# ENTRY DECISION
# =========================================================================

def check_v2_signal(df1h, df15m):
    """V2 entry with all V2.5.8/V2.5.9 improvements. Uses iloc[-2] closed bars."""
    if df1h is None or df15m is None: return None
    if len(df1h) < SMA_SLOW_1H + 1 or len(df15m) < STOCHRSI_LEN + STOCHRSI_RSI_LEN + 2:
        return None
    c1h   = float(df1h['close'].iloc[-2])
    sma20 = float(df1h['SMA20'].iloc[-2])
    sma50 = float(df1h['SMA50'].iloc[-2])
    if pd.isna(sma20) or pd.isna(sma50): return None
    K      = float(df15m['K'].iloc[-2])
    K_prev = float(df15m['K'].iloc[-3])
    if pd.isna(K) or pd.isna(K_prev): return None

    # 2026-08-13 fix: dedup on the closed 15m bar, same convention as VWAP/
    # FUT5VWAP -- without this, an unchanged K/RSI/MACD reading kept re-firing
    # every tick and stacked multiple lots into BASE's overlap slots (5x on
    # both 2026-08-12 and 2026-08-13, see orion-v2520-0812-duplicate-entry-bug
    # memory). One V2 entry per qualifying bar.
    bar_time = df15m.iloc[-2].name
    if DAY.last_v2_bar_time is not None and bar_time == DAY.last_v2_bar_time:
        return None

    # V2.5.8: full SMA alignment (SMA20 must be above SMA50 for CE, below for PE)
    ce_regime = (c1h > sma20) and (sma20 > sma50)
    pe_regime = (c1h < sma20) and (sma20 < sma50)

    sig_ce = ce_regime and (K >= STOCHRSI_CE_LO) and (K > K_prev)
    if sig_ce and V2_K_CAP_CE is not None and K > V2_K_CAP_CE:
        sig_ce = False
    sig_pe = pe_regime and (K <= STOCHRSI_PE_HI) and (K < K_prev) and (K >= V2_K_FLOOR_PE)

    # V2.5.8: K extreme filter — entry only after K was recently oversold/overbought
    if sig_ce and not k_was_extreme_live('CE', df15m): sig_ce = False
    if sig_pe and not k_was_extreme_live('PE', df15m): sig_pe = False

    # V2.5.9: RSI directional gate — CE needs RSI>53, PE needs RSI<47
    rsi_val = df1h['RSI'].iloc[-2] if 'RSI' in df1h.columns else None
    if rsi_val is not None and not pd.isna(rsi_val):
        rsi_val = float(rsi_val)
        if sig_ce and rsi_val <= RSI_CE_MIN: sig_ce = False
        if sig_pe and rsi_val >= RSI_PE_MAX: sig_pe = False

    # V2.5.9: MACD 1h alignment — CE needs MACD_line>signal, PE needs MACD_line<signal
    # 2026-07-12: gated off by V2_MACD_GATE_ENABLED, see constant definition above.
    if V2_MACD_GATE_ENABLED:
        macd_line = df1h['MACD_line'].iloc[-2] if 'MACD_line' in df1h.columns else None
        macd_sig  = df1h['MACD_sig'].iloc[-2]  if 'MACD_sig'  in df1h.columns else None
        if macd_line is not None and macd_sig is not None and \
           not pd.isna(macd_line) and not pd.isna(macd_sig):
            macd_line = float(macd_line); macd_sig = float(macd_sig)
            if sig_ce and macd_line <= macd_sig: sig_ce = False
            if sig_pe and macd_line >= macd_sig: sig_pe = False

    if sig_ce and sig_pe: return None
    if sig_ce:
        DAY.last_v2_bar_time = bar_time
        return {'engine':'V2','side':'CE','detail':f'K={K:.1f}↑ RSI={rsi_val:.1f} MACD✓','trigger':sma20}
    if sig_pe:
        DAY.last_v2_bar_time = bar_time
        return {'engine':'V2','side':'PE','detail':f'K={K:.1f}↓ RSI={rsi_val:.1f} MACD✓','trigger':sma20}
    return None

def check_v3_signal(df15m_nifty):
    """V3 entry: any Grade A/B cluster break/reject on last closed 15m bar.
    Checks ALL clusters (not just nearest G/R), Grade A priority then nearest to price.
    """
    if df15m_nifty is None or len(df15m_nifty) < 2: return None
    if DAY.levels is None: return None
    bar15_closed = df15m_nifty.iloc[-2]
    bar = {'open': float(bar15_closed['open']), 'high': float(bar15_closed['high']),
           'low':  float(bar15_closed['low']),  'close': float(bar15_closed['close'])}
    pdc = DAY.levels['pdc']
    buf = V3_MIN_BUFFER_FROM_PDC
    bar_close = bar['close']

    # All Grade A/B clusters with PDC buffer — assign role by position relative to PDC
    candidates = []
    for c in DAY.levels.get('all_clusters', []):
        if c['grade'] not in ('A', 'B'): continue
        if c['center'] in DAY.fired_levels: continue
        if c['center'] > pdc + buf:
            candidates.append((c, 'G'))   # resistance above PDC
        elif c['center'] < pdc - buf:
            candidates.append((c, 'R'))   # support below PDC

    # Grade A before B; within same grade, nearest to current bar close first
    candidates.sort(key=lambda x: (0 if x[0]['grade'] == 'A' else 1, abs(x[0]['center'] - bar_close)))

    for lvl_obj, role in candidates:
        sig = detect_v3_signal_on_bar(bar, lvl_obj, role)
        if sig is None: continue
        side = 'CE' if 'CE' in sig['kind'] else 'PE'
        detail = f"Grade {sig['grade']} {role}-cluster {sig['kind'].replace('_','-')} at {lvl_obj['center']:.0f}"
        target = compute_targets(lvl_obj, side, DAY.levels['all_clusters'])
        return {'engine': 'V3', 'side': side, 'detail': detail, 'trigger': lvl_obj['center'],
                'level_obj': lvl_obj, 'target_spot': target, 'kind': sig['kind']}
    return None


def check_v3_signal_early(df5m_nifty):
    """V2.5.20-fix (2026-07-12): early V3 entry on a PARTIAL 15m candle, built
    from the first two CLOSED 5m sub-bars (10-min mark into the 15m block),
    instead of waiting for the full 15m close. Real 5m/28-day test: +8.96pt
    avg favorable move in the first hour vs +2.50pt for the full-close wait
    (see ~/orion_analysis/v3_level_diagnosis/EARLY_ENTRY_RESULTS.md).
    Dedup against the normal check_v3_signal() is automatic: both share
    DAY.fired_levels, added on open_trade -- whichever fires first on a level
    blocks the other from re-firing on the same level.
    Only matches while EXACTLY the first two 5m sub-bars of a 15m block
    (aligned to :00/:15/:30/:45) are closed; once the 3rd sub-bar closes this
    naturally stops matching and the full-bar check takes over."""
    if not V3_EARLY_ENTRY_ENABLED: return None
    if df5m_nifty is None or len(df5m_nifty) < 3 or DAY.levels is None: return None
    if 'date' not in df5m_nifty.columns: return None
    b1 = df5m_nifty.iloc[-3]   # 1st closed 5m sub-bar of the current 15m block
    b2 = df5m_nifty.iloc[-2]   # 2nd closed 5m sub-bar (most recent closed 5m bar)
    t1, t2 = b1['date'], b2['date']
    if hasattr(t1, 'to_pydatetime'): t1 = t1.to_pydatetime()
    if hasattr(t2, 'to_pydatetime'): t2 = t2.to_pydatetime()
    if t1.minute % 15 != 0: return None
    if (t2 - t1) != timedelta(minutes=5): return None

    bar = {'open': float(b1['open']),
           'high': max(float(b1['high']), float(b2['high'])),
           'low':  min(float(b1['low']),  float(b2['low'])),
           'close': float(b2['close'])}
    pdc = DAY.levels['pdc']
    buf = V3_MIN_BUFFER_FROM_PDC
    bar_close = bar['close']

    candidates = []
    for c in DAY.levels.get('all_clusters', []):
        if c['grade'] not in ('A', 'B'): continue
        if c['center'] in DAY.fired_levels: continue
        if c['center'] > pdc + buf:
            candidates.append((c, 'G'))
        elif c['center'] < pdc - buf:
            candidates.append((c, 'R'))
    candidates.sort(key=lambda x: (0 if x[0]['grade'] == 'A' else 1, abs(x[0]['center'] - bar_close)))

    for lvl_obj, role in candidates:
        sig = detect_v3_signal_on_bar(bar, lvl_obj, role)
        if sig is None: continue
        side = 'CE' if 'CE' in sig['kind'] else 'PE'
        detail = (f"EARLY(10m) Grade {sig['grade']} {role}-cluster "
                  f"{sig['kind'].replace('_','-')} at {lvl_obj['center']:.0f}")
        target = compute_targets(lvl_obj, side, DAY.levels['all_clusters'])
        return {'engine': 'V3', 'side': side, 'detail': detail, 'trigger': lvl_obj['center'],
                'level_obj': lvl_obj, 'target_spot': target, 'kind': sig['kind']}
    return None


# ================= T5 ENGINE (levels + premium-divergence, 65%-win method) — 2026-07-20 =================
# The method_backtest_1m T5 config: spot near a level + option recently CHEAP vs own VWAP + near base +
# breakout that clears its base by >=3pt + the OTHER side decaying >=12pt + own MA(3>6) confirm + range
# position. 3m bars. Exit = Part-5 (session-pivot R1 target clamped / stop beyond base / VWAP-giveback /
# theta timeout). Backtest: 60d 43tr 65%win +Rs20,358 ; 30d 27tr 63% +Rs13,403. Independent separate-PnL
# paper book — UNLIMITED overlapping positions, both sides, no gates/veto/limits. Forward paper = OOS.
# (drop_exp / expiry-day skip NOT yet wired — TODO.)
T5_ENABLED = True
T5_LEVEL_TOL = 12.0
T5_BASE_TOL = 20.0
T5_DECAY_MIN = 40.0
T5_BO_MIN = 10.0
T5_CHEAP_LB = 4
T5_FAST, T5_SLOW = 3, 6
T5_MIN_MOVE, T5_TGT_CAP = 65.0, 200.0
T5_GIVEBACK = 50.0
T5_TIMEOUT_MIN = 60
T5_LOT = 20
T5_STEP_SECS = 20
T5_BOOK = []
T5_DAY_PTS = 0.0; T5_DAY_TRADES = 0
_T5_ENTRY_BAR = {'CE': None, 'PE': None}
_T5_LAST_STEP = 0.0; _T5_LAST_LOG = 0.0
T5_TRADES_CSV = os.path.expanduser('~/Amol/sensex_t5_shadow_trades.csv')

def _t5_bars3m(token):
    """Today's 3m option bars (resampled from completed 1m). None if short."""
    d = _apex_opt_bars(token)
    if d is None: return None
    g = d.set_index('date').resample('3min')
    r = pd.DataFrame({'open': g['open'].first(), 'high': g['high'].max(), 'low': g['low'].min(),
                      'close': g['close'].last(), 'volume': g['volume'].sum()}).dropna(subset=['close']).reset_index()
    if len(r) < T5_SLOW + 2: return None
    return r

def _t5_levels(spot):
    lv = []
    piv = DAY.pivots
    if piv: lv += [piv[k] for k in ('P', 'R1', 'S1', 'R2', 'S2') if k in piv]
    try:
        if DAY.levels:
            for k in ('pdh', 'pdl'):
                v = DAY.levels.get(k)
                if v: lv.append(float(v))
    except Exception:
        pass
    base = int(spot // 100) * 100
    lv += [base - 100, base, base + 100, base + 200]
    return lv

def _t5_record(p, exit_px, pts, reason, now):
    global T5_DAY_TRADES
    T5_DAY_TRADES += 1; rs = pts * T5_LOT
    try:
        newfile = not os.path.exists(T5_TRADES_CSV)
        with open(T5_TRADES_CSV, 'a') as fh:
            if newfile:
                fh.write("date,side,strike,entry_time,exit_time,entry,exit,pts,rupees,reason\n")
            fh.write(f"{now.date()},{p['side']},{p['strike']},{p['entry_time'].strftime('%H:%M:%S')},"
                     f"{now.strftime('%H:%M:%S')},{p['entry']:.2f},{exit_px:.2f},{pts:+.1f},{rs:+.0f},{reason}\n")
    except Exception as e:
        lwarn(f"[T5] csv write failed: {e}")
    linfo(f"[T5] EXIT {p['side']} {p['strike']} {p['entry']:.1f}->{exit_px:.1f} {pts:+.1f}pt Rs{rs:+.0f} "
          f"[{reason}] | day {T5_DAY_PTS:+.1f}pt Rs{T5_DAY_PTS*T5_LOT:+.0f}")
    TG.send(f"🟣 <b>T5 exit ⚫V20-paper</b> {p['side']} {p['strike']}\n"
            f"   {p['entry']:.1f}→{exit_px:.1f} = <b>{pts:+.1f}pt / ₹{rs:+,.0f}</b> [{reason}]\n"
            f"   Day: {T5_DAY_PTS:+.1f}pt / ₹{T5_DAY_PTS*T5_LOT:+,.0f}  open={len(T5_BOOK)}")

def t5_step(spot, expiry_lookup, df15):
    """T5 engine: independent separate-PnL book (unlimited overlap). Entry = level + cheap + near-base +
    breakout>=3 + other decaying>=12 + MA confirm + range-pos; exit = Part-5. FAILS CLOSED."""
    global T5_DAY_PTS, _T5_LAST_STEP, _T5_LAST_LOG
    if not T5_ENABLED or spot is None or spot <= 0: return
    if time.time() - _T5_LAST_STEP < T5_STEP_SECS: return
    _T5_LAST_STEP = time.time()
    now = datetime.now(IST)
    force = now.hour > 15 or (now.hour == 15 and now.minute >= 25)
    strike = round_to_atm(spot)
    # ---- EXITS (Part-5) ----
    for p in list(T5_BOOK):
        cur = ltp(p['symbol'])
        if cur is None or cur <= 0: continue
        cur = float(cur); p['peak'] = max(p['peak'], cur); reason = None
        if force:
            reason = 'FORCE_1525'
        elif cur <= p['stop']:
            reason = 'stop'
        elif cur >= p['target']:
            reason = 'target'
        elif (now - p['entry_time']).total_seconds() >= T5_TIMEOUT_MIN * 60:
            reason = 'timeout'
        else:
            b = _t5_bars3m(p['token'])
            if b is not None:
                vw = _apex_vwap(b)
                if p['peak'] - p['entry'] >= T5_GIVEBACK and float(b['close'].iloc[-1]) < float(vw.iloc[-1]):
                    reason = 'giveback'
        if reason:
            pts = cur - p['entry']; T5_DAY_PTS += pts
            _t5_record(p, cur, pts, reason, now); T5_BOOK.remove(p)
    # ---- ENTRIES ----
    if not force:
        levels = _t5_levels(spot)
        if min(abs(spot - l) for l in levels) <= T5_LEVEL_TOL:
            try:
                today = now.date()
                m = df15['date'].apply(lambda x: (x.date() if hasattr(x, 'date') else x) == today)
                td = df15[m]; dhi = float(td['high'].max()); dlo = float(td['low'].min())
            except Exception:
                dhi = dlo = 0.0
            if dhi > dlo:
                pos = (spot - dlo) / (dhi - dlo)
                tk = {s: expiry_lookup.get((strike, s), (None, None))[1] for s in ('CE', 'PE')}
                if tk['CE'] and tk['PE']:
                    bars = {s: _t5_bars3m(tk[s]) for s in ('CE', 'PE')}
                    if bars['CE'] is not None and bars['PE'] is not None:
                        for side, other, want in (('CE', 'PE', pos < 0.45), ('PE', 'CE', pos > 0.55)):
                            if not want: continue
                            b = bars[side]; bo = bars[other]
                            c = b['close']; vw = _apex_vwap(b)
                            maf = c.rolling(T5_FAST).mean().iloc[-1]; mas = c.rolling(T5_SLOW).mean().iloc[-1]
                            prem = float(c.iloc[-1]); vwap = float(vw.iloc[-1])
                            if any(pd.isna(x) for x in (maf, mas)): continue
                            recent_cheap = float(c.iloc[max(0, len(c)-1-T5_CHEAP_LB):len(c)-1].min()) < vwap
                            near_base = prem <= vwap + T5_BASE_TOL
                            base_hi = float(b['high'].iloc[max(0, len(b)-4):len(b)-1].max())
                            prev = float(c.iloc[-2])
                            breakout = prem > base_hi and prev <= base_hi and (prem - base_hi) >= T5_BO_MIN
                            other_drop = float(bo['close'].iloc[-4] - bo['close'].iloc[-1])
                            decaying = other_drop > T5_DECAY_MIN
                            ma_ok = maf > mas
                            bts = str(b['date'].iloc[-1])
                            if recent_cheap and near_base and breakout and decaying and ma_ok and _T5_ENTRY_BAR[side] != bts:
                                sym = expiry_lookup.get((strike, side), (None, None))[0]; e = ltp(sym)
                                if e is None or e <= 0: continue
                                e = float(e)
                                H = float(b['high'].max()); L = float(b['low'].min()); P = (H + L + e) / 3
                                R1 = 2*P - L; R2 = P + (H - L)
                                tgt = R1 if R1 >= e + T5_MIN_MOVE else R2
                                tgt = min(max(tgt, e + T5_MIN_MOVE), e + T5_TGT_CAP)
                                base_low = float(b['low'].iloc[max(0, len(b)-6):len(b)].min())
                                stop = e - float(np.clip(e - base_low, 8, 18))
                                _T5_ENTRY_BAR[side] = bts
                                T5_BOOK.append({'side': side, 'symbol': sym, 'token': tk[side], 'entry': e,
                                                'entry_time': now, 'peak': e, 'target': tgt, 'stop': stop, 'strike': strike})
                                linfo(f"[T5] ENTRY {side} {strike} @ {e:.1f} tgt{tgt:.1f} stp{stop:.1f} (bo+{prem-base_hi:.1f} {other}dec-{other_drop:.1f}) open={len(T5_BOOK)}")
                                TG.send(f"🟣 <b>T5 entry ⚫V20-paper</b> {side} {strike} @ {e:.1f}  tgt {tgt:.1f}  open={len(T5_BOOK)}")
    if time.time() - _T5_LAST_LOG >= 300:
        _T5_LAST_LOG = time.time()
        unreal = 0.0
        for p in T5_BOOK:
            cc = ltp(p['symbol'])
            if cc: unreal += (float(cc) - p['entry'])
        linfo(f"[T5] open={len(T5_BOOK)} trades={T5_DAY_TRADES} realized={T5_DAY_PTS:+.1f}pt/Rs{T5_DAY_PTS*T5_LOT:+.0f} "
              f"unreal={unreal:+.1f}pt/Rs{unreal*T5_LOT:+.0f}")


# ================= APEX ENGINE (the user's ACTUAL method) — 2026-07-20 =================
# Levels + spot RSI(1m) turning through 38/50/62 + option RSI energy-cycle + divergence,
# with a RIDE-TO-EXHAUSTION exit (trail that locks breakeven+ and lets winners run; exit when the
# option's own fast MA rolls under the slow MA). Backtest 60d in-sample +Rs7,761 (+Rs129/day) once
# the exit was fixed (method_real_backtest.py). Runs as an INDEPENDENT separate-PnL paper book, same
# design as the old ROUTER (unlimited overlapping, no gates/veto/limits). Forward paper is the OOS test.
APEX_ENABLED = True
APEX_LEVEL_TOL = 12.0
APEX_RSI_LEVELS = (38, 50, 62)
APEX_RSI_MIN_DELTA = 5.0    # 2026-08-01 entry-filter fix: require a decisive turn, not any
                            # single-bar crossing of 38/50/62 (autopsy of the 34 real shadow
                            # trades: weak-turn entries were disproportionately losers)
APEX_OPT_FAST, APEX_OPT_SLOW = 5, 13
APEX_WIN = 4                 # the setup may BUILD over this many 1m bars (not one bar)
APEX_ARM, APEX_GIVE = 40.0, 40.0
APEX_STOP_MIN, APEX_STOP_MAX = 33.0, 80.0
APEX_LOT = 20
APEX_STEP_SECS = 15          # throttle heavy data-fetch to bound Kite API load
APEX_BOOK = []
APEX_DAY_PTS = 0.0; APEX_DAY_TRADES = 0
_APEX_ENTRY_BAR = {'CE': None, 'PE': None}
_APEX_LAST_STEP = 0.0; _APEX_LAST_LOG = 0.0
APEX_TRADES_CSV = os.path.expanduser('~/Amol/apex_shadow_v2520_trades.csv')

# self-contained helpers (so this identical block runs in both V2519 and V2520)
def _apex_rsi(c, n=14):
    d = c.diff(); ru = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    rd = (-d).clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100/(1 + ru/rd.replace(0, np.nan))).fillna(50)

def _apex_opt_bars(token):
    """Today's completed 1m option bars (drops the forming bar). None if short."""
    try:
        now = datetime.now(IST); frm = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if frm >= now: return None  # before session open — avoid a doomed Kite call
        rows = historical(token, frm, now, "minute")
        if not rows: return None
        d = pd.DataFrame(rows).dropna(subset=['close'])
        if 'date' not in d.columns or len(d) < 8: return None
        return d.iloc[:-1].reset_index(drop=True)
    except Exception:
        return None

def _apex_vwap(b):
    tp = (b['high'] + b['low'] + b['close']) / 3; v = b['volume'].replace(0, np.nan)
    return ((tp * v).cumsum() / v.cumsum()).ffill().fillna(b['close'])

def _apex_spot_1m():
    try:
        now = datetime.now(IST); frm = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if frm >= now: return None  # before session open — avoid a doomed Kite call
        rows = historical(NIFTY_INSTRUMENT_TOKEN, frm, now, "minute")
        if not rows: return None
        d = pd.DataFrame(rows)
        if 'close' not in d.columns or len(d) < 20: return None
        d['rsi'] = _apex_rsi(d['close']).values
        return d
    except Exception:
        return None

def _apex_strong_levels():
    """2026-08-01 entry-filter fix: classic pivots (P/R1/S1/R2/S2) ONLY -- PDH/PDL dropped.
    Autopsy of the 34 real APEX shadow trades (V2520, 2026-07-20..31) found entries
    triggered near PDH/PDL were the dominant loss source (17/34 trades, -62.6pt combined)
    while entries near P/S1/S2/R1 were ~breakeven-positive on their own (17/34, +3.6pt) --
    same 34-trade window, same entries, only the level type differs. PDH/PDL are the most
    widely-watched, most-faded levels (everyone's stop/target sits there); the derived
    pivots are less telegraphed. Small sample (n=34) -- forward-validate before trusting
    fully, but this is the single cleanest, most structurally-interpretable split found."""
    piv = DAY.pivots
    lv = []
    if piv:
        lv += [piv[k] for k in ('P', 'R1', 'S1', 'R2', 'S2') if k in piv]
    return lv

def _apex_spot_trigger(sp1, levels, spot):
    """(ce_ok, pe_ok): spot recently at a strong level AND spot RSI(1m) turned up/down through
    one of 38/50/62 within the recent window, WITH a minimum-strength turn (APEX_RSI_MIN_DELTA)
    -- not just any single-bar crossing. 2026-08-01: the magnitude requirement was added after
    the same autopsy found weak/marginal turns (small net RSI change across the window)
    disproportionately became losers; the setup building, not one-bar simultaneity."""
    C = sp1['close'].values; R = sp1['rsi'].values; n = len(C)
    if n < APEX_WIN + 2: return False, False
    near = any(min(abs(float(C[k]) - l) for l in levels) <= APEX_LEVEL_TOL
               for k in range(max(0, n - 1 - APEX_WIN), n))
    if not near: return False, False
    win_lo = max(0, n - 1 - APEX_WIN)
    rsi_delta = R[n - 1] - R[win_lo]
    if np.isnan(rsi_delta): return False, False
    up = dn = False
    for k in range(max(1, n - APEX_WIN), n):
        rp, rn = R[k-1], R[k]
        if np.isnan(rp): continue
        if any(rp < L <= rn for L in APEX_RSI_LEVELS) and rn > rp: up = True
        if any(rn < L <= rp for L in APEX_RSI_LEVELS) and rn < rp: dn = True
    if up and rsi_delta < APEX_RSI_MIN_DELTA: up = False
    if dn and rsi_delta > -APEX_RSI_MIN_DELTA: dn = False
    return up, dn

def _apex_record(p, exit_px, pts, reason, now):
    global APEX_DAY_TRADES
    APEX_DAY_TRADES += 1; rs = pts * APEX_LOT
    try:
        newfile = not os.path.exists(APEX_TRADES_CSV)
        with open(APEX_TRADES_CSV, 'a') as fh:
            if newfile:
                fh.write("date,side,strike,entry_time,exit_time,entry,exit,pts,rupees,reason\n")
            fh.write(f"{now.date()},{p['side']},{p['strike']},{p['entry_time'].strftime('%H:%M:%S')},"
                     f"{now.strftime('%H:%M:%S')},{p['entry']:.2f},{exit_px:.2f},{pts:+.1f},{rs:+.0f},{reason}\n")
    except Exception as e:
        lwarn(f"[APEX] csv write failed: {e}")
    linfo(f"[APEX] EXIT {p['side']} {p['strike']} {p['entry']:.1f}->{exit_px:.1f} {pts:+.1f}pt "
          f"Rs{rs:+.0f} [{reason}] | day {APEX_DAY_PTS:+.1f}pt Rs{APEX_DAY_PTS*APEX_LOT:+.0f}")
    TG.send(f"🎯 <b>APEX exit ⚫V20-shadow</b> {p['side']} {p['strike']}\n"
            f"   {p['entry']:.1f}→{exit_px:.1f} = <b>{pts:+.1f}pt / ₹{rs:+,.0f}</b> [{reason}]\n"
            f"   Day: {APEX_DAY_PTS:+.1f}pt / ₹{APEX_DAY_PTS*APEX_LOT:+,.0f}  open={len(APEX_BOOK)}")

def apex_step(spot, expiry_lookup):
    """APEX engine: independent separate-PnL paper book of the user's actual method. Runs every cycle
    (throttled). Entry = levels + spot-RSI-turn + option energy-cycle + divergence; exit = ride-to-
    exhaustion trail + option MA rollover, or 15:25 force-close. FAILS CLOSED on missing data."""
    global APEX_DAY_PTS, _APEX_LAST_STEP, _APEX_LAST_LOG
    if not APEX_ENABLED or spot is None or spot <= 0: return
    if time.time() - _APEX_LAST_STEP < APEX_STEP_SECS: return
    _APEX_LAST_STEP = time.time()
    now = datetime.now(IST)
    force = now.hour > 15 or (now.hour == 15 and now.minute >= 25)
    strike = round_to_atm(spot)
    # ---- EXITS (ride-to-exhaustion) ----
    for p in list(APEX_BOOK):
        cur = ltp(p['symbol'])
        if cur is None or cur <= 0: continue
        cur = float(cur); p['peak'] = max(p['peak'], cur); reason = None
        if force:
            reason = 'FORCE_1525'
        else:
            if not p['armed'] and p['peak'] >= p['entry'] + APEX_ARM: p['armed'] = True
            if p['armed']:
                nt = max(p['entry'] + 2.0, p['peak'] - APEX_GIVE)
                if nt > p['trail']: p['trail'] = nt
            if cur <= p['trail']:
                reason = 'trail' if p['armed'] else 'stop'
            else:
                b = _apex_opt_bars(p['token'])
                if b is not None and len(b) >= APEX_OPT_SLOW + 1:
                    maf = b['close'].rolling(APEX_OPT_FAST).mean().iloc[-1]
                    mas = b['close'].rolling(APEX_OPT_SLOW).mean().iloc[-1]
                    if not (pd.isna(maf) or pd.isna(mas)) and maf < mas:
                        reason = 'exhaust'
        if reason:
            pts = cur - p['entry']; APEX_DAY_PTS += pts
            _apex_record(p, cur, pts, reason, now); APEX_BOOK.remove(p)
    # ---- ENTRIES ----
    if not force:
        sp1 = _apex_spot_1m(); levels = _apex_strong_levels()
        if sp1 is not None and levels:
            ce_ok, pe_ok = _apex_spot_trigger(sp1, levels, spot)
            for side, other, trig in (('CE', 'PE', ce_ok), ('PE', 'CE', pe_ok)):
                if not trig: continue
                tk = expiry_lookup.get((strike, side), (None, None))
                tko = expiry_lookup.get((strike, other), (None, None))
                if not tk[1] or not tko[1]: continue
                b = _apex_opt_bars(tk[1]); bo = _apex_opt_bars(tko[1])
                if b is None or bo is None or len(b) < APEX_OPT_SLOW + 2 or len(bo) < 4: continue
                r = _apex_rsi(b['close']).reset_index(drop=True); i = len(r) - 1
                maf = b['close'].rolling(APEX_OPT_FAST).mean().iloc[-1]
                mas = b['close'].rolling(APEX_OPT_SLOW).mean().iloc[-1]
                vw = _apex_vwap(b).reset_index(drop=True)
                if any(pd.isna(x) for x in (maf, mas, r.iloc[i], vw.iloc[i])): continue
                energy = (r.iloc[i] > r.iloc[i-1]) and (r.iloc[i] >= 38) and bool((r.iloc[max(0, i-6):i] < 38).any())
                turn = maf > mas
                cheap = bool((b['close'].iloc[max(0, i-4):i] < vw.iloc[max(0, i-4):i]).any())
                other_drop = float(bo['close'].iloc[-4] - bo['close'].iloc[-1])
                diverge = other_drop > 20
                bts = str(b['date'].iloc[-1])
                if energy and turn and cheap and diverge and _APEX_ENTRY_BAR[side] != bts:
                    sym = tk[0]; cur = ltp(sym)
                    if cur is None or cur <= 0: continue
                    cur = float(cur)
                    base_low = float(b['low'].iloc[max(0, len(b)-11):len(b)-1].min())
                    stop_depth = float(np.clip(cur - base_low, APEX_STOP_MIN, APEX_STOP_MAX))
                    _APEX_ENTRY_BAR[side] = bts
                    APEX_BOOK.append({'side': side, 'symbol': sym, 'token': tk[1], 'entry': cur,
                                      'entry_time': now, 'peak': cur, 'armed': False,
                                      'trail': cur - stop_depth, 'strike': strike})
                    linfo(f"[APEX] ENTRY {side} {strike} @ {cur:.1f} (level+RSI-turn+energy+diverge) open={len(APEX_BOOK)}")
                    TG.send(f"🎯 <b>APEX entry ⚫V20-shadow</b> {side} {strike} @ {cur:.1f}  open={len(APEX_BOOK)}")
    # ---- throttled summary ----
    if time.time() - _APEX_LAST_LOG >= 300:
        _APEX_LAST_LOG = time.time()
        unreal = 0.0
        for p in APEX_BOOK:
            c = ltp(p['symbol'])
            if c: unreal += (float(c) - p['entry'])
        linfo(f"[APEX] open={len(APEX_BOOK)} trades={APEX_DAY_TRADES} "
              f"realized={APEX_DAY_PTS:+.1f}pt/Rs{APEX_DAY_PTS*APEX_LOT:+.0f} "
              f"unreal={unreal:+.1f}pt/Rs{unreal*APEX_LOT:+.0f}")


# =========================================================================
# EXPIRY ENGINES 1 & 2 — SHADOW PAPER BOOK (deployed 2026-08-22)
# Engine 1 (EXP1) = RSI-snap confluence: option decays, 3m RSI(7) pins <15
#   then crosses 40; gates = OI15<=+5% AND spot through strike AND prem<=100,
#   plus >=1 of {snap-bar>=15%, breadth>=3 within 6min}. Exit 10% giveback
#   trail on 3m closes. Backtest recent 40 expiries: 9tr 8W +Rs18,944.
# Engine 2 (EXP2) = cheap-ladder: 14:30-15:10 buy any leg at Rs8-16 with
#   spot through strike + OI15<=+5%. NO stop (premium = max risk); trail arms
#   at Rs40 then 20% giveback. Backtest recent 40: 26tr +Rs12,760.
# Independent separate-PnL paper book (APEX/T5 pattern): LTP/bars paper fills
# ONLY — never touches the real-money order flow. Forward paper = the OOS.
# Research code/results: ~/Amol/expiry_engine.py (Engines 1&2, same params).
# Live deviations from backtest spec (documented, unavoidable):
#  - universe (major-OI strike M +/-50) resolved ~13:20 IST from live quote
#    OI snapshot (backtest used the 14:30 OI snapshot)
#  - entries fill at live LTP on the step after the signal bar completes
# =========================================================================
EXP12_ENABLED = True
EXP12_STEP_SECS = 60
EXP12_LOT = 20
EXP12_FORCE_H, EXP12_FORCE_M = 15, 28
EXP12_TRADES_CSV = os.path.expanduser('~/Amol/sensex_exp12_shadow_trades.csv')
# 2026-08-22 user instruction: NO restrictions — no trade-count/SL-count
# caps, no regime/time/premium gates. Bot-level gates never applied to this
# book anyway. Removed vs backtest spec: Engine 1's Rs100 premium cap,
# one-trade-per-leg-per-day dedup (unlimited re-entries; only an OPEN
# position on the same leg+engine blocks), windows widened to 13:00-15:20.
# Kept (these ARE the signal, not gates): RSI-snap shape, OI15<=+5%,
# spot-through-strike, E2's Rs8-16 cheap band, the trails.
# 2026-08-25 user instruction after Tue 08-25 NIFTY miss (premium out-ran
# spot, E2 never fired; see memory orion-exp12-0825-miss-premium-outran-spot):
#  1. E1: 10% trail REMOVED — no SL on expiry day; 20% trail arms only after
#     premium doubles (2x entry), else ride to the 15:28 force exit.
#  2. Entry window now 14:30-15:25 both engines (was 13:00-15:20); engine
#     still boots 13:20 to warm data + resolve universe; force exit 15:28.
#  3. Spot-through-strike relaxed: dist >= -EXP12_DIST_RELAX (spot within
#     115 pts below strike; NIFTY uses 35, x3.3 scaling) OR spot crossed the
#     strike within the last EXP12_CROSS_LOOKBACK_MIN minutes.
#  4. E2 cheap band widened: hi 53 -> 66 (NIFTY 16 -> 20).
#  5. Universe re-resolves every EXP12_RERESOLVE_SECS: if max-OI strike M
#     migrates, legs rebuilt (open/pending legs kept for exits).
# Revert = restore ORION_SENSEX_V2520_BACKUP_20260825_pre_exp12_relax.py
EXP1_RSI_FLOOR, EXP1_RSI_LOOK = 15.0, 20
EXP1_WIN_LO, EXP1_WIN_HI = (14, 45), (15, 25)   # 2026-09-16: was (14,30); 14:30-14:44 signals 9/44 win Rs-15,264 over 20 expiries. Revert: (14, 30) or ORION_SENSEX_V2520_BACKUP_20260916_pre_exp12_win1445.py
EXP1_ARM_X, EXP1_OI15_MAX, EXP1_SNAP_MIN = 2.0, 5.0, 15.0
EXP1_BRD_MIN, EXP1_BRD_TOL_MIN = 3, 6
EXP1_PENDING_TTL_MIN = 7
EXP2_PREM_LO, EXP2_PREM_HI = 26.0, 66.0
EXP2_WIN_LO, EXP2_WIN_HI = (14, 45), (15, 25)   # 2026-09-16: was (14,30); see EXP1_WIN_LO comment + CHANGE_HISTORY 2026-09-16
EXP2_ARM, EXP2_GB, EXP2_OI15_MAX = 130.0, 0.80, 5.0
# 2026-09-11: EXPIRY EXIT REPAIR — EXP12 takes NO trail exit any more;
# every position rides to the 15:28 force close (EOD_1528). Measured on the
# 6 expiries 08-25..09-10: the 3 trail exits that fired cost +Rs14,723 in
# aggregate vs holding to 15:28, and all 3 improved. EXP12 legs carry no
# stop-loss by design, so 15:28 is now the whole exit path. Revert = False.
EXP12_HOLD_TO_1528 = True
EXP12_DIST_RELAX = 115.0
EXP12_CROSS_LOOKBACK_MIN = 30
EXP12_RERESOLVE_SECS = 300
# 2026-08-26: EXP2W = EXP2 + the user's "was-expensive" SELECTION filter, run
# as a PARALLEL tag alongside plain EXP2 on the same legs, same data, same
# exits. EXP2 vs EXP2W on the same day isolates the filter's effect (user:
# "if any chance we have both to be tested thursday, so will come to know the
# difference asap"). Definition copied from ~/Amol/decay_rebound_study.py:
# the option's afternoon high (13:00 -> the bar before entry) must have
# reached EXP2W_WASEXP_MIN, and the premium must come DOWN into the band
# (previous bar close above the band high). Shadow paper only.
# Revert = restore ORION_SENSEX_V2520_BACKUP_20260826_pre_exp2w.py
EXP2W_ENABLED = True
EXP2W_WASEXP_MIN = 130.0
EXP2W_AFT_FROM = '13:00'

EXP12_BOOK = []
EXP12_DAY_RS = 0.0
EXP12_DAY_TRADES = 0
EXP12_ENG_RS = {}   # eng -> [rupees, trades]; EXP2 vs EXP2W comparison
_EXP12_LEGS = None
_EXP12_M = None
_EXP12_TRIG = {}
_EXP12_LAST_STEP = 0.0
_EXP12_LAST_LOG = 0.0
_EXP12_SPOT_HIST = []
_EXP12_LAST_RESOLVE = 0.0

def _exp12_hist_oi(token):
    """Today's completed 1m bars WITH OI: [(HH:MM, close, oi)]. None if short."""
    try:
        now = datetime.now(IST); frm = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if frm >= now: return None
        rows = kite_safe(kite.historical_data, token, frm, now, "minute", False, True)
        if not rows or len(rows) < 10: return None
        out = []
        for r in rows[:-1]:
            c = r.get('close'); oi = r.get('oi')
            if c is None or c <= 0: continue
            out.append((r['date'].strftime('%H:%M'), float(c), float(oi) if oi else None))
        return out if len(out) >= 10 else None
    except Exception:
        return None

def _exp12_bars3(ser):
    out, cur, last = [], None, None
    for t, c, oi in ser:
        key = (int(t[:2]) * 60 + int(t[3:5])) // 3
        if key != cur:
            if last is not None: out.append(last)
            cur = key
        last = (t, c)
    if last is not None: out.append(last)
    return out

def _exp12_rsi7(closes):
    n = len(closes); rs = [None] * n
    if n < 8: return rs
    g = l = 0.0
    for i in range(1, 8):
        d = closes[i] - closes[i-1]; g += max(d, 0); l += max(-d, 0)
    ag, al = g / 7.0, l / 7.0
    rs[7] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(8, n):
        d = closes[i] - closes[i-1]
        ag = (ag * 6 + max(d, 0)) / 7.0; al = (al * 6 + max(-d, 0)) / 7.0
        rs[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return rs

def _exp12_oi15(ser, t0):
    m0 = int(t0[:2]) * 60 + int(t0[3:5]); t15 = f"{(m0-15)//60:02d}:{(m0-15)%60:02d}"
    oi_now = None
    for t, c, oi in reversed(ser):
        if t <= t0 and oi:
            oi_now = oi; break
    oi_prev = None
    for t, c, oi in reversed(ser):
        if t <= t15 and oi:
            oi_prev = oi; break
    if not (oi_now and oi_prev): return None
    return (oi_now - oi_prev) / oi_prev * 100.0

def _exp12_in_win(t0, lo, hi):
    m = int(t0[:2]) * 60 + int(t0[3:5])
    return lo[0] * 60 + lo[1] <= m <= hi[0] * 60 + hi[1]

def _exp12_dist_ok(st, sd, spot, now):
    """2026-08-25 relaxed spot-vs-strike gate: pass if spot is within
    EXP12_DIST_RELAX pts below the strike NOW, or crossed the strike at any
    step in the last EXP12_CROSS_LOOKBACK_MIN minutes. Returns (ok, dist)."""
    dist = (spot - st) if sd == 'CE' else (st - spot)
    if dist >= -EXP12_DIST_RELAX:
        return True, dist
    cutoff = now - timedelta(minutes=EXP12_CROSS_LOOKBACK_MIN)
    for t, s in reversed(_EXP12_SPOT_HIST):
        if t < cutoff: break
        d2 = (s - st) if sd == 'CE' else (st - s)
        if d2 >= 0:
            return True, dist
    return False, dist

# 2026-08-29 (item 4): the EXP12 universe used to be anchored to the MAX-OI
# strike. Max-OI is sticky; spot is not -- so on 08-25 (Nifty) and 08-27
# (Sensex, legs frozen at 77500 while spot fell to 77182) neither engine had a
# single near-the-money contract for hours. Now anchored to SPOT.
# BACKTEST that justified this (40 recent Nifty expiries, real Upstox 1-min
# premiums, a WIDE strike band pulled specially because the old dataset held
# ONLY the max-OI strikes and could not answer the question):
#   gate G1 -- max-OI baseline reproduced EXACTLY: n=26, +Rs12,760
#   same breadth, spot anchor : n=29, +Rs13,959, 3 days better, 0 WORSE, 21 same
#   spot re-anchored each 5min: n=32, +Rs18,242, 5 better, 1 worse
# The in-sample gain is SMALL because max-OI and spot-ATM usually coincide --
# they differed on only 3 of 24 traded days. The point is the tail: when they
# diverge the old rule goes blind for hours, which is exactly what both live
# misses were. Never worse on any of the 40 expiries at equal breadth.
EXP12_ANCHOR = 'spot'      # 'spot' | 'maxoi' -- set 'maxoi' to revert behaviour

def _exp12_resolve_m(spot, expiry_lookup):
    """Anchor strike M for the EXP12 leg universe.
    EXP12_ANCHOR='spot'  -> the strike nearest spot (default since 2026-08-29)
    EXP12_ANCHOR='maxoi' -> legacy max-OI strike among ATM+/-4
    Max-OI is still computed either way so the log shows the divergence that
    caused the 08-25 / 08-27 misses."""
    atm = round_to_atm(spot)
    syms = {}
    for st in [atm + k * 100 for k in range(-4, 5)]:
        for sd in ('CE', 'PE'):
            if (st, sd) in expiry_lookup:
                syms[(st, sd)] = expiry_lookup[(st, sd)][0]
    q = kite_safe(kite.quote, list(syms.values())) or {}
    oi_tot = {}
    for (st, sd), sym in syms.items():
        oi = (q.get(sym) or {}).get('oi') or 0
        oi_tot[st] = oi_tot.get(st, 0) + oi
    m_oi = max(oi_tot, key=oi_tot.get) if (oi_tot and max(oi_tot.values()) > 0) else None
    if EXP12_ANCHOR == 'spot':
        if m_oi is not None and m_oi != atm:
            linfo(f"[EXP12] anchor=spot M={atm} (max-OI would be {m_oi}, "
                  f"diverged by {m_oi - atm:+d}) spot={spot:.1f}")
        return atm
    return m_oi

def _exp12_build_legs(m, expiry_lookup, keep_keys=()):
    legs = []
    for st in (m - 100, m, m + 100):
        for sd in ('CE', 'PE'):
            if (st, sd) in expiry_lookup:
                sym, tok = expiry_lookup[(st, sd)]
                legs.append((st, sd, sym, tok))
    for (st, sd) in keep_keys:
        if not any((s, d) == (st, sd) for s, d, _, _ in legs) \
                and (st, sd) in expiry_lookup:
            sym, tok = expiry_lookup[(st, sd)]
            legs.append((st, sd, sym, tok))
    return legs

def _exp12_closed3(b3, now):
    """Drop the last 3-min bar if its window is still forming — a partial bar
    must never trigger or exit (replay-test 2026-08-22: a partial-bar trigger
    fired with wrong features and blocked the real signal for 7 minutes)."""
    if b3 and (int(b3[-1][0][:2]) * 60 + int(b3[-1][0][3:5])) // 3 == \
              (now.hour * 60 + now.minute) // 3:
        return b3[:-1]
    return b3

# --- 2026-08-29 (item 5): decline accounting for the expiry-day EOD report ----
# User, 2026-08-27: "no message about why a trade was not taken". Decline
# reasons only ever reached linfo(), and the FlightRecorder log was blanked, so
# the agreed "we will check at EOD" had nothing to check. Every EXP12 gate now
# increments a counter; _exp12_eod_report() renders them once at 15:29.
EXP12_BLOCKS = {}          # eng -> {reason: count}
EXP12_NEAR = {}            # eng -> (rank, text)   most-nearly-qualifying leg
EXP12_EOD_SENT = False

def _exp12_block(eng, reason):
    EXP12_BLOCKS.setdefault(eng, {})
    EXP12_BLOCKS[eng][reason] = EXP12_BLOCKS[eng].get(reason, 0) + 1

def _exp12_near(eng, rank, text):
    """Keep the single closest miss per engine (higher rank = got further)."""
    cur = EXP12_NEAR.get(eng)
    if cur is None or rank > cur[0]:
        EXP12_NEAR[eng] = (rank, text)

def _exp12_eod_report():
    """One consolidated Telegram at 15:29 on expiry days: per engine, either the
    trade taken or the specific gate that blocked it."""
    engines = ('EXP1', 'EXP2', 'EXP2W') if EXP2W_ENABLED else ('EXP1', 'EXP2')
    L = [f"🎯 <b>EXPIRY ENGINES — why / why not</b>  ⚫ SHADOW BOOK",
         f"━━━━━━━━━━━━━━━━━━━━━━",
         f"Universe M={_EXP12_M} legs=" + (", ".join(
             f"{s}{d}" for s, d, _sym, _t in _EXP12_LEGS) or "-")]
    for eng in engines:
        rs, n = EXP12_ENG_RS.get(eng, [0.0, 0])
        if n:
            em = "🟩" if rs > 0 else "🟥" if rs < 0 else "⬜"
            L.append(f"{em} <b>{eng}</b>: {n} trade(s), ₹{rs:+,.0f}")
        else:
            blocks = EXP12_BLOCKS.get(eng, {})
            if blocks:
                top = ", ".join(f"{tg_escape(k)}×{v}" for k, v in
                                sorted(blocks.items(), key=lambda x: -x[1])[:4])
                L.append(f"⚫ <b>{eng}</b>: no trade — blocked by {top}")
            else:
                L.append(f"⚫ <b>{eng}</b>: no trade — no qualifying leg at all")
            near = EXP12_NEAR.get(eng)
            if near:
                L.append(f"     closest: {tg_escape(near[1])}")
    L.append("━━━━━━━━━━━━━━━━━━━━━━")
    L.append(f"EXP12 day total: <b>₹{EXP12_DAY_RS:+,.0f}</b> "
             f"({EXP12_DAY_TRADES} trades, lot {EXP12_LOT}) — "
             f"<i>separate book, NOT in the EOD Net PnL</i>")
    return "\n".join(L)


def _exp12_record(p, exit_px, reason, now):
    global EXP12_DAY_RS, EXP12_DAY_TRADES
    rs = (exit_px - p['entry']) * EXP12_LOT
    EXP12_DAY_RS += rs; EXP12_DAY_TRADES += 1
    e = EXP12_ENG_RS.setdefault(p['eng'], [0.0, 0])
    e[0] += rs; e[1] += 1
    try:
        newfile = not os.path.exists(EXP12_TRADES_CSV)
        with open(EXP12_TRADES_CSV, 'a') as fh:
            if newfile:
                fh.write("date,engine,strike,side,entry_time,exit_time,entry,exit,rupees,reason\n")
            fh.write(f"{now.date()},{p['eng']},{p['strike']},{p['side']},"
                     f"{p['entry_time'].strftime('%H:%M:%S')},{now.strftime('%H:%M:%S')},"
                     f"{p['entry']:.2f},{exit_px:.2f},{rs:+.0f},{reason}\n")
    except Exception as e:
        lwarn(f"[EXP12] csv write failed: {e}")
    linfo(f"[EXP12] {p['eng']} EXIT {p['strike']}{p['side']} {p['entry']:.2f}->{exit_px:.2f} "
          f"Rs{rs:+.0f} [{reason}] | day Rs{EXP12_DAY_RS:+.0f}")
    # 2026-08-29: colour-coded by side + a persistent SHADOW tag. These used to
    # be plain 🎯/⚫ with no green/red, so they read as ordinary text next to the
    # main-book messages -- which is why a +Rs3,378 EXP2 day on 08-27 looked
    # like nothing had happened. See fmt_eod_summary()'s shadow line too.
    _em = "🟢" if p['side'] == 'CE' else "🔴"
    _res = "🟩" if rs > 0 else "🟥" if rs < 0 else "⬜"
    TG.send(f"{_em} <b>{p['eng']} EXIT</b> ⚫ <b>SHADOW BOOK</b> (not in main PnL)\n"
            f"   {p['strike']}{p['side']}  {p['entry']:.2f}→{exit_px:.2f}\n"
            f"   {_res} <b>₹{rs:+,.0f}</b> [{reason}]  ·  lot {EXP12_LOT}\n"
            f"   EXP12 day: ₹{EXP12_DAY_RS:+,.0f}  open={len(EXP12_BOOK)}")

# 2026-09-28: no new EXP1/EXP2/EXP2W entry at or after 15:15 IST. SENSEX spot is frozen
# 15:15-15:29 (closing auction) so the spot-distance gate is blind; live 08-27..09-24: EXP2
# entries 15:22-15:27 = 11 tr, 3 wins, Rs-1,034 vs before 15:15 2 tr Rs+6,677. Revert: (15, 30).
EXP12_ENTRY_CUTOFF = (15, 15)
# 2026-09-28: EXP2 premium band is re-checked on the LIVE LTP actually paid (the band test on
# the last history bar let 296.50 / 142.00 / 86.80 fills through). Revert: False.
EXP2_BAND_ON_LTP = True


def _exp12_open(eng, strike, side, symbol, entry, now, note):
    if (now.hour, now.minute) >= EXP12_ENTRY_CUTOFF:
        _exp12_block(eng, f'no entry after {EXP12_ENTRY_CUTOFF[0]}:{EXP12_ENTRY_CUTOFF[1]:02d}')
        linfo(f"[EXP12] {eng} {strike}{side} @ {entry:.2f} NOT opened — after entry cutoff")
        return
    EXP12_BOOK.append({'eng': eng, 'strike': strike, 'side': side, 'symbol': symbol,
                       'entry': float(entry), 'entry_time': now})
    linfo(f"[EXP12] {eng} ENTRY {strike}{side} @ {entry:.2f} ({note})")
    _em = "🟢" if side == 'CE' else "🔴"
    TG.send(f"{_em} <b>{eng} ENTRY</b> ⚫ <b>SHADOW BOOK</b> (not in main PnL)\n"
            f"   {strike}{side} @ ₹{entry:.2f}  ·  lot {EXP12_LOT}\n   {note}")

def _exp12_was_expensive(ser, t0, prev_c):
    """User's selection filter (decay_rebound_study.py): the option's afternoon
    high (EXP2W_AFT_FROM .. the bar before t0) reached EXP2W_WASEXP_MIN, and the
    premium came DOWN into the band. Returns (ok, afternoon_high, why)."""
    past = [c for t, c, _oi in ser if EXP2W_AFT_FROM <= t < t0]
    hi = max(past) if past else 0.0
    if hi < EXP2W_WASEXP_MIN:
        return False, hi, f"afthi {hi:.2f} < {EXP2W_WASEXP_MIN:.0f}"
    if prev_c is None or prev_c <= EXP2_PREM_HI:
        return False, hi, "not a decay INTO the band"
    return True, hi, ""


def exp12_step(spot, expiry_lookup):
    """EXPIRY ENGINES 1&2 shadow book. Expiry day only, 13:20+. FAILS CLOSED."""
    global _EXP12_LEGS, _EXP12_M, _EXP12_LAST_STEP, _EXP12_LAST_LOG, _EXP12_LAST_RESOLVE
    if not EXP12_ENABLED or spot is None or spot <= 0: return
    if TARGET_EXPIRY_DATE is None: return
    _exp_d = TARGET_EXPIRY_DATE.date() if isinstance(TARGET_EXPIRY_DATE, datetime) else TARGET_EXPIRY_DATE
    now = datetime.now(IST)
    if now.date() != _exp_d: return
    if now.hour < 13 or (now.hour == 13 and now.minute < 20): return
    if time.time() - _EXP12_LAST_STEP < EXP12_STEP_SECS: return
    _EXP12_LAST_STEP = time.time()
    force = (now.hour * 60 + now.minute) >= EXP12_FORCE_H * 60 + EXP12_FORCE_M

    _EXP12_SPOT_HIST.append((now, float(spot)))
    del _EXP12_SPOT_HIST[:max(0, len(_EXP12_SPOT_HIST) - 120)]

    if _EXP12_LEGS is None:
        m = _exp12_resolve_m(spot, expiry_lookup)
        if m is None:
            lwarn("[EXP12] no OI in quotes — will retry next step")
            _EXP12_LAST_STEP = 0.0
            return
        _EXP12_M = m
        _EXP12_LEGS = _exp12_build_legs(m, expiry_lookup)
        _EXP12_LAST_RESOLVE = time.time()
        linfo(f"[EXP12] universe resolved: M={_EXP12_M} "
              f"legs={[(s, d) for s, d, _, _ in _EXP12_LEGS]}")
    elif time.time() - _EXP12_LAST_RESOLVE >= EXP12_RERESOLVE_SECS:
        _EXP12_LAST_RESOLVE = time.time()
        m = _exp12_resolve_m(spot, expiry_lookup)
        if m is not None and m != _EXP12_M:
            keep = {(p['strike'], p['side']) for p in EXP12_BOOK}
            keep |= {k for k, v in _EXP12_TRIG.items() if v['state'] == 'pending'}
            _EXP12_M = m
            _EXP12_LEGS = _exp12_build_legs(m, expiry_lookup, keep)
            linfo(f"[EXP12] universe RE-resolved: M={_EXP12_M} "
                  f"legs={[(s, d) for s, d, _, _ in _EXP12_LEGS]}")

    series = {}
    for st, sd, sym, tok in _EXP12_LEGS:
        ser = _exp12_hist_oi(tok)
        if ser:
            series[(st, sd)] = ser

    def _open_pos(eng, key):
        return any(p['eng'] == eng and (p['strike'], p['side']) == key
                   for p in EXP12_BOOK)

    # ---- ENGINE 1: trigger detection (re-triggers allowed after exit) ----
    for st, sd, sym, tok in _EXP12_LEGS:
        key = (st, sd)
        prev = _EXP12_TRIG.get(key)
        if prev is not None and prev['state'] == 'pending': continue
        if _open_pos('EXP1', key): continue
        after_t = prev['t'] if prev is not None else None
        ser = series.get(key)
        if not ser: continue
        b3 = _exp12_closed3(_exp12_bars3(ser), now)
        if len(b3) < 25: continue
        closes = [c for _, c in b3]; times = [t for t, _ in b3]
        rs = _exp12_rsi7(closes)
        for i in range(1, len(b3)):
            if after_t is not None and times[i] <= after_t: continue
            if not _exp12_in_win(times[i], EXP1_WIN_LO, EXP1_WIN_HI): continue
            if rs[i] is None or rs[i-1] is None: continue
            if rs[i-1] < 40 <= rs[i]:
                prior = [r for r in rs[max(0, i - EXP1_RSI_LOOK):i] if r is not None]
                if not prior or min(prior) >= EXP1_RSI_FLOOR: continue
                snap = (closes[i] - closes[i-1]) / closes[i-1] * 100
                oic = _exp12_oi15(ser, times[i])
                dist = (spot - st) if sd == 'CE' else (st - spot)
                _EXP12_TRIG[key] = {'t': times[i], 'ref': closes[i], 'snap': snap,
                                    'oic': oic, 'dist': dist, 'state': 'pending',
                                    'seen': now}
                linfo(f"[EXP12] EXP1 trigger {st}{sd} @{times[i]} ref={closes[i]:.2f} "
                      f"snap={snap:+.1f}% oi15={'?' if oic is None else round(oic, 1)} "
                      f"dist={dist:+.0f}")
                break

    # ---- ENGINE 1: pending trigger -> paper trade (breadth can fill in) ----
    trig_minutes = {k: int(v['t'][:2]) * 60 + int(v['t'][3:5]) for k, v in _EXP12_TRIG.items()}
    for key, tg in list(_EXP12_TRIG.items()):
        if tg['state'] != 'pending': continue
        m0 = trig_minutes[key]
        brd = sum(1 for m2 in trig_minutes.values() if abs(m2 - m0) <= EXP1_BRD_TOL_MIN)
        dok, _cur_dist = _exp12_dist_ok(key[0], key[1], spot, now)
        ok_gates = (tg['oic'] is not None and tg['oic'] <= EXP1_OI15_MAX and dok)
        ok_extra = (tg['snap'] >= EXP1_SNAP_MIN) or (brd >= EXP1_BRD_MIN)
        if ok_gates and ok_extra:
            st, sd = key
            sym = next(s3 for s2, d2, s3, _ in _EXP12_LEGS if (s2, d2) == key)
            px = ltp(sym)
            if px and float(px) > 0:
                tg['state'] = 'done'
                _exp12_open('EXP1', st, sd, sym, float(px), now,
                            f"RSI-snap @{tg['t']} ref={tg['ref']:.2f} "
                            f"snap={tg['snap']:+.0f}% brd={brd}")
            continue
        if (now - tg['seen']).total_seconds() / 60.0 > EXP1_PENDING_TTL_MIN:
            tg['state'] = 'expired'
            _exp12_block('EXP1', 'gates' if not ok_gates else 'snap/breadth')
            _exp12_near('EXP1', 2, f"{key[0]}{key[1]} triggered @{tg['t']} but "
                                   f"gates={ok_gates} extra={ok_extra}")
            linfo(f"[EXP12] EXP1 trigger {key[0]}{key[1]} expired "
                  f"(gates={ok_gates} extra={ok_extra})")

    # ---- ENGINE 2: cheap-ladder entries (re-entries allowed after exit) ----
    for st, sd, sym, tok in _EXP12_LEGS:
        key = (st, sd)
        need2 = not _open_pos('EXP2', key)
        need2w = EXP2W_ENABLED and not _open_pos('EXP2W', key)
        if not (need2 or need2w): continue
        ser = series.get(key)
        if not ser:
            _exp12_block('EXP2', 'no OI/price series'); continue
        t0, c0, _oi = ser[-1]
        if not _exp12_in_win(t0, EXP2_WIN_LO, EXP2_WIN_HI):
            _exp12_block('EXP2', f'outside {EXP2_WIN_LO}-{EXP2_WIN_HI} window'); continue
        if not (EXP2_PREM_LO <= c0 <= EXP2_PREM_HI):
            _exp12_block('EXP2', f'premium outside {EXP2_PREM_LO}-{EXP2_PREM_HI}')
            _exp12_near('EXP2', 1, f'{st}{sd} premium {c0:.2f}'); continue
        dok, dist = _exp12_dist_ok(st, sd, spot, now)
        if not dok:
            _exp12_block('EXP2', 'spot too far from strike')
            _exp12_near('EXP2', 2, f'{st}{sd} prem {c0:.2f} OK but dist {dist:+.0f}'); continue
        oic = _exp12_oi15(ser, t0)
        if oic is None or oic > EXP2_OI15_MAX:
            _exp12_block('EXP2', f'OI15 > {EXP2_OI15_MAX}%')
            _exp12_near('EXP2', 3, f'{st}{sd} prem {c0:.2f} dist {dist:+.0f} OK but '
                                   f'oi15={"?" if oic is None else round(oic,1)}%'); continue
        px = ltp(sym)
        if not px or float(px) <= 0:
            _exp12_block('EXP2', 'no LTP'); continue
        if EXP2_BAND_ON_LTP and not (EXP2_PREM_LO <= float(px) <= EXP2_PREM_HI):
            _exp12_block('EXP2', f'live LTP outside {EXP2_PREM_LO}-{EXP2_PREM_HI}')
            _exp12_near('EXP2', 1, f'{st}{sd} bar {c0:.2f} but LTP {float(px):.2f}'); continue
        if need2:
            _exp12_open('EXP2', st, sd, sym, float(px), now,
                        f"cheap-ladder bar@{t0}={c0:.2f} dist={dist:+.0f} oi15={oic:+.1f}%")
        if need2w:
            prev_c = ser[-2][1] if len(ser) >= 2 else None
            wok, afthi, why = _exp12_was_expensive(ser, t0, prev_c)
            if wok:
                _exp12_open('EXP2W', st, sd, sym, float(px), now,
                            f"was-expensive afthi={afthi:.2f} bar@{t0}={c0:.2f} "
                            f"dist={dist:+.0f} oi15={oic:+.1f}%")
            elif need2:
                _exp12_block('EXP2W', 'was-expensive filter')
                _exp12_near('EXP2W', 3, f'{st}{sd} {why}')
                linfo(f"[EXP12] EXP2W declined {st}{sd} @{t0} ({why}) "
                      f"— EXP2 took it")

    # ---- exits (sequential re-walk from entry with FRESH local peak) ----
    for p in list(EXP12_BOOK):
        key = (p['strike'], p['side'])
        ser = series.get(key)
        reason = None; exit_px = None
        if force:
            cur = ltp(p['symbol'])
            if cur is None and ser:
                cur = ser[-1][1]
            if cur:
                exit_px = float(cur); reason = 'EOD_1528'
        elif ser and not EXP12_HOLD_TO_1528:   # 2026-09-11: see EXP12_HOLD_TO_1528
            entry_hhmm = p['entry_time'].strftime('%H:%M')
            if p['eng'] == 'EXP1':
                # 2026-08-25: no SL; 20% trail arms only after 2x entry
                peak = p['entry']
                for t, c in _exp12_closed3(_exp12_bars3(ser), now):
                    if t <= entry_hhmm: continue
                    peak = max(peak, c)
                    if peak >= EXP1_ARM_X * p['entry'] and c <= EXP2_GB * peak:
                        exit_px = c; reason = 'TRAIL_20pct_after_2x'; break
            else:
                peak = p['entry']
                for t, c, _oi in ser:
                    if t <= entry_hhmm: continue
                    peak = max(peak, c)
                    if peak >= EXP2_ARM and c <= EXP2_GB * peak:
                        exit_px = c; reason = 'LADDER_TRAIL_20pct'; break
        if reason and exit_px is not None:
            EXP12_BOOK.remove(p)
            _exp12_record(p, float(exit_px), reason, now)

    # 2026-08-29 (item 5): one consolidated "why / why not" Telegram at 15:29,
    # after the 15:28 force-close has booked any trade, before the bot exits.
    # Guarded by EXP12_EOD_SENT so the 30s loop cannot repeat it.
    global EXP12_EOD_SENT
    if not EXP12_EOD_SENT and (now.hour, now.minute) >= (15, 29):
        EXP12_EOD_SENT = True
        try:
            TG.send(_exp12_eod_report())
            linfo("[EXP12] EOD why/why-not report sent")
        except Exception as _e:
            lwarn(f"[EXP12] EOD report failed: {_e}")

    if time.time() - _EXP12_LAST_LOG >= 300:
        _EXP12_LAST_LOG = time.time()
        _brk = " ".join(f"{k}:{v[1]}tr/Rs{v[0]:+.0f}"
                        for k, v in sorted(EXP12_ENG_RS.items())) or "none"
        _opn = " ".join(f"{p['eng']}:{p['strike']}{p['side']}" for p in EXP12_BOOK) or "-"
        linfo(f"[EXP12] M={_EXP12_M} open={len(EXP12_BOOK)}[{_opn}] "
              f"trades={EXP12_DAY_TRADES} realized=Rs{EXP12_DAY_RS:+.0f} "
              f"triggers={len(_EXP12_TRIG)} | by-engine {_brk}")


def compute_nifty_vwap_today(df15m):
    """Compute today's session VWAP from 15m Nifty spot bars already in memory."""
    try:
        today = datetime.now(IST).date()
        if 'date' in df15m.columns:
            mask = df15m['date'].apply(
                lambda x: (x.date() if hasattr(x, 'date') else x) == today)
        else:
            mask = pd.Series([True] * len(df15m), index=df15m.index)
        today_df = df15m[mask]
        if len(today_df) < 1:
            return None
        tp  = (today_df['high'] + today_df['low'] + today_df['close']) / 3
        vol = today_df['volume'] if 'volume' in today_df.columns else pd.Series(
            [1] * len(today_df), index=today_df.index)
        vol_sum = vol.sum()
        if vol_sum == 0:
            return float(tp.mean())
        return float((tp * vol).sum() / vol_sum)
    except Exception:
        return None


# 2026-07-13: latest FUT 5m frame, refreshed once per main-loop cycle. open_trade()
# is called from many places (incl. the 3 breakout engines' direct calls) and does
# not receive the dataframes, so the veto reads the futures session VWAP from here
# rather than re-fetching (stays inside Kite's historical rate limit).
LAST_FUT5M = None
LAST_DF1M = None   # 2026-09-28: SENSEX spot 1m frame for the veto basis fix (ported from NIFTY 09-14)


def countertrend_veto(side, spot, engine=""):
    """2026-07-13 COUNTER-TREND VETO (see constants block for the 439d evidence).

    Refuse to buy the side the market is currently moving AGAINST:
      PE (puts)  blocked when spot > futures session VWAP + buffer
      CE (calls) blocked when spot < futures session VWAP - buffer

    Breakout engines (COUNTERTREND_VETO_EXEMPT) are skipped -- validated NEGATIVE
    for them; see the constants block.

    Returns (blocked: bool, reason: str). FAILS OPEN -- if futures data or the VWAP
    is unavailable we allow the trade rather than silently starving every engine.
    That failure mode is exactly what the stale NO_NEW_ENTRIES_TODAY flag did to
    this bot for four sessions; a filter must never be able to mute the book by
    accident.
    """
    if not COUNTERTREND_VETO_ENABLED:
        return False, ""
    if engine in COUNTERTREND_VETO_EXEMPT:
        return False, ""
    # 2026-09-28 BASIS FIX (ported from the NIFTY bot's 2026-09-14 fix): this compared
    # SPOT against the FUTURES session VWAP. SENSEX futures trade above spot, so spot
    # looked "below VWAP" almost always and CE was vetoed (FUT5VWAP 8/9 PE). Compare
    # like with like: spot vs today's spot 1m typical-price VWAP.
    if LAST_DF1M is None or len(LAST_DF1M) == 0:
        return False, ""
    vwap = compute_nifty_vwap_today(LAST_DF1M)
    if vwap is None or spot is None or spot <= 0:
        return False, ""
    buf = COUNTERTREND_VETO_BUFFER
    if side == 'PE' and spot > vwap + buf:
        return True, (f"PE into an UPtrend: spot {spot:.1f} is {spot - vwap:+.1f} "
                      f"above SPOT VWAP {vwap:.1f} (buffer {buf:.0f})")
    if side == 'CE' and spot < vwap - buf:
        return True, (f"CE into a DOWNtrend: spot {spot:.1f} is {spot - vwap:+.1f} "
                      f"below SPOT VWAP {vwap:.1f} (buffer {buf:.0f})")
    return False, ""


def vwap_persistence_gate(df5m_fut, side):
    """2026-08-20 GATE 1 (see VWAP_PERSIST_GATE_ENABLED above). Returns
    (ok: bool, info: str). Fails OPEN (ok=True) on insufficient data."""
    if not VWAP_PERSIST_GATE_ENABLED:
        return True, ""
    if df5m_fut is None or len(df5m_fut) < VWAP_PERSIST_BARS + 2:
        return True, "5m-data-missing"
    fut5_vwap = compute_nifty_vwap_today(df5m_fut)
    if fut5_vwap is None:
        return True, "vwap-unavailable"
    closed = df5m_fut.iloc[:-1]   # drop the still-forming bar, same convention as elsewhere
    if len(closed) < VWAP_PERSIST_BARS:
        return True, "insufficient-closed-bars"
    last_n = closed.iloc[-VWAP_PERSIST_BARS:]
    cur_close = float(last_n['close'].iloc[-1])
    dist = cur_close - fut5_vwap
    if side == 'CE':
        persist_ok = bool((last_n['close'] > fut5_vwap).all())
        dist_ok = dist >= VWAP_DIST_MIN_PTS
    else:
        persist_ok = bool((last_n['close'] < fut5_vwap).all())
        dist_ok = dist <= -VWAP_DIST_MIN_PTS
    ok = persist_ok and dist_ok
    return ok, f"dist={dist:+.1f}pt persist={persist_ok} (last {VWAP_PERSIST_BARS}x5m vs FUTvwap={fut5_vwap:.1f})"


def vwap_loss_cooldown_ok(side):
    """2026-08-20 GATE 2 (see VWAP_LOSS_COOLDOWN_MIN above). Returns
    (ok: bool, info: str). No cooldown recorded yet => always ok."""
    if not VWAP_LOSS_COOLDOWN_ENABLED:
        return True, ""
    if DAY.vwap_last_loss_at is None or DAY.vwap_last_loss_side != side:
        return True, ""
    age_min = (datetime.now(IST) - DAY.vwap_last_loss_at).total_seconds() / 60.0
    if age_min < VWAP_LOSS_COOLDOWN_MIN:
        return False, f"{age_min:.1f}min since last VWAP {side} loss (cooldown {VWAP_LOSS_COOLDOWN_MIN}min)"
    return True, ""


def check_vwap_signal(df15m_nifty, expiry_lookup, spot, df15m_fut=None, df5m_fut=None):
    """
    VWAP entry — Gate 1 only (backtest-validated).
    Nifty Futures 15m close crosses daily VWAP, body >= VWAP_BODY_MIN_PCT (65%).
    Fires regardless of regime (self-confirming).
    Backtest: 14 days May 2026, 64 trades, WR 82.8%, Rs 96,216 (trail exit, > filter).
    Gates 2+3 (spot VWAP, option VWAP) removed — backtest showed they cost Rs 54,168.
    2026-08-20: two new gates layered on top (persistence+distance, post-loss
    cooldown) — see VWAP_PERSIST_GATE_ENABLED / VWAP_LOSS_COOLDOWN_ENABLED above.
    """
    if not VWAP_ENGINE_ENABLED: return None

    # V2.5.19 FEATURE 1: require a confirmation candle after the 65-86% cross bar.
    if VWAP15_CONFIRM_ENABLED:
        return _check_vwap_signal_confirm(df15m_fut)

    if df15m_fut is None or len(df15m_fut) < 3: return None
    fut_vwap = compute_nifty_vwap_today(df15m_fut)
    if fut_vwap is None: return None

    fut_bar = df15m_fut.iloc[-2]
    bar_time = fut_bar.name
    fo = float(fut_bar['open']); fh = float(fut_bar['high'])
    fl = float(fut_bar['low']);  fc = float(fut_bar['close'])
    f_rng = fh - fl
    if f_rng <= 0: return None
    f_body_pct = abs(fc - fo) / f_rng
    if f_body_pct < VWAP_BODY_MIN_PCT: return None
    # V2.5.17 #2: take only the 65-86% body band — skip >=87% climax/exhaustion bars (they fade)
    if f_body_pct >= VWAP_BODY_CLIMAX_PCT:
        linfo(f"[VWAP] Climax skip — body={f_body_pct:.0%} >= {VWAP_BODY_CLIMAX_PCT:.0%}")
        return None

    # Dedup: block re-fire on same 15m bar
    if DAY.last_vwap_bar_time is not None and bar_time == DAY.last_vwap_bar_time:
        return None

    fut_bullish = fc > fut_vwap
    fut_bearish = fc < fut_vwap
    if not fut_bullish and not fut_bearish: return None
    side = 'CE' if fut_bullish else 'PE'

    # 2026-08-20 GATE 2: post-loss same-side cooldown (checked first, cheaper)
    _cd_ok, _cd_info = vwap_loss_cooldown_ok(side)
    if not _cd_ok:
        linfo(f"[VWAP] Cooldown BLOCK — {side} {_cd_info}")
        return None

    # 2026-08-20 GATE 1: 5m persistence + distance-from-VWAP filter
    _pg_ok, _pg_info = vwap_persistence_gate(df5m_fut, side)
    if not _pg_ok:
        linfo(f"[VWAP] Persistence-gate BLOCK — {side} {_pg_info}")
        return None

    detail = (f"FUT VWAP {fc:.0f}{'>' if fut_bullish else '<'}{fut_vwap:.0f} "
              f"body={f_body_pct:.0%} | bar={bar_time}")
    DAY.last_vwap_bar_time = bar_time
    linfo(f"[VWAP] Signal — FUT {fc:.0f}{'>' if fut_bullish else '<'}{fut_vwap:.0f} "
          f"body={f_body_pct:.0%} side={side} | persist_gate={_pg_info}")
    return {
        'engine': 'VWAP', 'side': side, 'detail': detail,
        'trigger': fut_vwap, 'level_obj': None,
        'target_spot': None, 'kind': f'BREAK_{side}'
    }


def _check_vwap_signal_confirm(df15m_fut):
    """V2.5.19 FEATURE 1: FUT 15m VWAP cross + confirmation candle.
    Cross bar  = iloc[-3]: body in the 65-86% band, closes on one side of FUT-VWAP.
    Confirm bar= iloc[-2]: same-colour candle (close vs open same sign as the cross
                 direction) AND still closes on the SAME side of FUT-VWAP.
    Fires once per confirm bar (deduped). Direction = the cross side. Re-entries are
    handled downstream by the momentum gate."""
    if df15m_fut is None or len(df15m_fut) < 4:
        return None
    fut_vwap = compute_nifty_vwap_today(df15m_fut)
    if fut_vwap is None:
        return None

    cross = df15m_fut.iloc[-3]
    conf  = df15m_fut.iloc[-2]
    conf_time = conf.name

    co = float(cross['open']); ch = float(cross['high'])
    cl = float(cross['low']);  cc = float(cross['close'])
    c_rng = ch - cl
    if c_rng <= 0:
        return None
    c_body_pct = abs(cc - co) / c_rng
    if c_body_pct < VWAP_BODY_MIN_PCT or c_body_pct >= VWAP_BODY_CLIMAX_PCT:
        return None

    cross_bullish = cc > fut_vwap
    cross_bearish = cc < fut_vwap
    if not cross_bullish and not cross_bearish:
        return None

    xo = float(conf['open']); xc = float(conf['close'])
    if cross_bullish:
        confirmed = (xc > xo) and (xc > fut_vwap)
    else:
        confirmed = (xc < xo) and (xc < fut_vwap)
    if not confirmed:
        return None

    # Dedup on the confirmation bar
    if DAY.last_vwap_bar_time is not None and conf_time == DAY.last_vwap_bar_time:
        return None

    side = 'CE' if cross_bullish else 'PE'
    detail = (f"FUT VWAP cross {cc:.0f}{'>' if cross_bullish else '<'}{fut_vwap:.0f} "
              f"body={c_body_pct:.0%} +confirm | bar={conf_time}")
    DAY.last_vwap_bar_time = conf_time
    linfo(f"[VWAP] Signal (confirmed) — cross {cc:.0f}{'>' if cross_bullish else '<'}"
          f"{fut_vwap:.0f} body={c_body_pct:.0%} confirm={xc:.0f} side={side}")
    return {
        'engine': 'VWAP', 'side': side, 'detail': detail,
        'trigger': fut_vwap, 'level_obj': None,
        'target_spot': None, 'kind': f'BREAK_{side}'
    }


def check_fut5m_vwap_scalp_signal(df5m_fut, spot=None):
    """V2.5.19 FEATURE 2: FUT 5m VWAP cross + S/R distance -> fixed +12 scalp.
    Latest closed FUT 5m bar (iloc[-2]) must:
      - CROSS its session VWAP: open on one side, close on the other,
      - have body in the 65-86% band,
      - close > FUT5_SCALP_SR_MIN_DIST pts from EVERY pivot S1/R1/S2/R2.
    Direction = close side of VWAP. One trade per qualifying bar (deduped).
    Engine 'FUT5VWAP' uses a FIXED +FUT5_SCALP_TARGET_PTS exit (set in open_trade)."""
    if not FUT5_SCALP_ENABLED:
        return None
    if df5m_fut is None or len(df5m_fut) < 3:
        return None
    fut_vwap = compute_nifty_vwap_today(df5m_fut)
    if fut_vwap is None:
        return None

    bar = df5m_fut.iloc[-2]
    bar_time = bar.name
    bo = float(bar['open']); bh = float(bar['high'])
    bl = float(bar['low']);  bc = float(bar['close'])
    rng = bh - bl
    if rng <= 0:
        return None
    body_pct = abs(bc - bo) / rng
    if body_pct < FUT5_SCALP_BODY_MIN or body_pct >= FUT5_SCALP_BODY_MAX:
        return None

    # True cross: open and close on opposite sides of VWAP
    if bo >= fut_vwap and bc > fut_vwap:
        return None  # stayed above
    if bo <= fut_vwap and bc < fut_vwap:
        return None  # stayed below
    up_cross   = (bo <= fut_vwap < bc)
    down_cross = (bo >= fut_vwap > bc)
    if not up_cross and not down_cross:
        return None

    # Dedup: one trade per qualifying 5m bar (no re-entry until next such event).
    # 2026-07-26 fix: was `==`-only, so a stale/out-of-order refetch serving an
    # OLDER bar_time after a newer one had already fired slipped through and
    # opened a second real position on the same already-seen signal (2026-07-24:
    # bar=224 fired, then bar=223 fired 4min later, doubling a -30pt stop to
    # -Rs11,700 at 3-lot sizing). `<=` treats any non-advancing bar as already-seen.
    if DAY.last_fut5_scalp_bar_time is not None and bar_time <= DAY.last_fut5_scalp_bar_time:
        return None

    # S/R clear-space gate: close must be > MIN_DIST from EVERY pivot
    mind = fut_pivot_dist(bc, df5m_fut, spot)   # 2026-09-28 pivot basis fix
    if mind is not None and mind <= FUT5_SCALP_SR_MIN_DIST:
        linfo(f"[FUT5VWAP] Skip — close {bc:.0f} only {mind:.0f}pt from a pivot "
              f"(need >{FUT5_SCALP_SR_MIN_DIST:.0f})")
        return None

    side = 'CE' if up_cross else 'PE'
    detail = (f"FUT5 VWAP cross {bc:.0f}{'>' if up_cross else '<'}{fut_vwap:.0f} "
              f"body={body_pct:.0%} pivΔ={mind:.0f}pt | bar={bar_time}"
              if mind is not None else
              f"FUT5 VWAP cross {bc:.0f}{'>' if up_cross else '<'}{fut_vwap:.0f} "
              f"body={body_pct:.0%} piv=NA | bar={bar_time}")
    DAY.last_fut5_scalp_bar_time = bar_time
    linfo(f"[FUT5VWAP] Signal — {bc:.0f}{'>' if up_cross else '<'}{fut_vwap:.0f} "
          f"body={body_pct:.0%} side={side} (fixed +{FUT5_SCALP_TARGET_PTS:.0f}pt target)")
    return {
        'engine': 'FUT5VWAP', 'side': side, 'detail': detail,
        'trigger': fut_vwap, 'level_obj': None,
        'target_spot': None, 'kind': f'BREAK_{side}'
    }


def orb_chop_kill_check(df5, df15, now):
    """V2.5.20 (2026-07-12): in-day CHOPPY kill for ORB -- the only adaptive-kill
    component that validated on BOTH datasets (see constants block above
    ORB_CHOP_KILL_ENABLED). Evaluates the LATEST due half-hour checkpoint once;
    sets DAY.orb_chop_killed sticky-True when the day-so-far is CHOPPY
    (range-so-far%% < that checkpoint's p33 cutoff AND >= ORB_CHOP_MIN_CROSSES
    side-flips of the 15m close vs the session cumulative TWAP). Uses spot 5m
    for range and spot 15m closed bars for crosses; prev-close reference = PDC
    from DAY.levels. Entries-only kill: an open ORB position exits normally."""
    if not ORB_CHOP_KILL_ENABLED or DAY.orb_chop_killed:
        return DAY.orb_chop_killed
    # latest checkpoint at/before now
    due = None
    now_hm = now.strftime("%H:%M")
    for cp in sorted(ORB_CHOP_P33_BY_CP):
        if cp <= now_hm:
            due = cp
    if due is None or due == DAY.orb_chop_last_cp:
        return False
    DAY.orb_chop_last_cp = due
    try:
        pdc = (DAY.levels or {}).get('pdc')
        if not pdc or df5 is None or len(df5) == 0 or 'date' not in df5.columns:
            return False
        today = now.date()
        d5 = df5[df5['date'].dt.date == today]
        if len(d5) < 4:
            return False
        rng_pct = 100.0 * (float(d5['high'].max()) - float(d5['low'].min())) / pdc
        if rng_pct >= ORB_CHOP_P33_BY_CP[due]:
            return False   # decent range so far -> not CHOPPY, ORB stays live
        if df15 is None or len(df15) == 0 or 'date' not in df15.columns:
            return False
        d15 = df15[df15['date'].dt.date == today]
        # closed bars only: drop the forming bar (live fetch keeps it as last row)
        if len(d15) >= 2:
            d15 = d15.iloc[:-1]
        if len(d15) < 4:
            return False
        closes = d15['close'].astype(float).tolist()
        tps = ((d15['high'] + d15['low'] + d15['close']) / 3).astype(float).tolist()
        crosses, prev_side, cum = 0, None, []
        for i, c in enumerate(closes):
            cum.append(tps[i])
            vw = sum(cum) / len(cum)
            side = c >= vw
            if prev_side is not None and side != prev_side:
                crosses += 1
            prev_side = side
        if crosses >= ORB_CHOP_MIN_CROSSES:
            DAY.orb_chop_killed = True
            linfo(f"[ORB] CHOP-KILL @{due} — range-so-far {rng_pct:.2f}% < p33 "
                  f"{ORB_CHOP_P33_BY_CP[due]:.2f}% and {crosses} TWAP flips >= "
                  f"{ORB_CHOP_MIN_CROSSES}. ORB entries+flips OFF for the day.")
            TG.send(f"🟡 <b>ORB chop-kill</b> — day confirmed CHOPPY at {due} "
                    f"(range {rng_pct:.2f}%, {crosses} whipsaws).\n"
                    f"   No new ORB entries or flips today (validated: +198.4pts/439d, +10/38d).")
    except Exception as e:
        lwarn(f"[ORB] chop-kill check failed at {due}: {e}")
    return DAY.orb_chop_killed


def check_orb_signal(df1m, df5, expiry_lookup):
    """V2.5.20 live ORB (opening-range-break). Ported from orb_signal_for_day()
    in orion_backtest_v2_5_19.py -- that function's day5.iterrows() scan already
    returns at the FIRST qualifying bar (it's causal, just run against a fully
    materialized offline dataframe there); this is the same scan run
    incrementally against live 5m bars as they close, so it's a faithful port,
    not an approximation.

    First 6x1m spot bars 09:15:00-09:20:59 -> opening-range high/low. Then the
    first 5m bar in 09:25-15:00 that closes outside the OR with body > 50% of
    its own range fires the signal (side = break direction). Fires at most once
    per day (mirrors orb.fired in the backtest -- once fired, ORB takes no
    further signals that day, win or lose, until the flip-on-stop mechanism in
    check_exits takes over). Gated by the SIDEWAYS-day filter (ORB only, see
    is_orb_day_sideways_live() above the constants block)."""
    if DAY.orb_fired:
        return None
    if is_orb_day_sideways_live():
        DAY.orb_fired = True   # stand down for the whole day (SIDEWAYS filter)
        linfo("[ORB] Stood down for the day — SIDEWAYS-regime filter")
        return None
    if df1m is None or len(df1m) == 0 or df5 is None or len(df5) == 0:
        return None
    if 'date' not in df1m.columns or 'date' not in df5.columns:
        return None
    # V2.5.20 CRITICAL FIX (2026-07-06): fetch_nifty_1m()/fetch_nifty_5m() return
    # 1-3 CALENDAR DAYS of history (needed elsewhere), not just today. The old
    # code below filtered candidate bars by TIME-OF-DAY only (hour*60+minute),
    # never by DATE -- so a prior day's bar that happens to fall in the same
    # minute-of-day window and happens to close outside today's freshly-computed
    # OR was indistinguishable from a genuine live breakout. This fired a real
    # 2-lot PE trade on 2026-07-06 using a close from 2026-07-03 (3 days stale),
    # because df5.iterrows() hits that earlier calendar day's row first in
    # chronological order and returns on it immediately. Restricting both
    # dataframes to today's date before any minute-of-day filtering closes
    # this. See orion-v2520-stale-data-signal-bug memory for the full incident.
    _now_ist = datetime.now(IST)
    today = _now_ist.date()
    _now_min = _now_ist.hour * 60 + _now_ist.minute
    df1m = df1m[df1m['date'].dt.date == today]
    df5  = df5[df5['date'].dt.date == today]
    if len(df1m) == 0 or len(df5) == 0:
        return None
    mins1 = df1m['date'].dt.hour * 60 + df1m['date'].dt.minute
    orx = df1m[(mins1 >= ORB_OR_START_MIN) & (mins1 < ORB_OR_END_MIN)]
    if len(orx) < 6:
        return None   # opening range not fully formed yet
    orh, orl = float(orx['high'].max()), float(orx['low'].min())
    entry_start_min = ORB_ENTRY_START_H * 60 + ORB_ENTRY_START_M
    entry_end_min   = ORB_ENTRY_END_H * 60 + ORB_ENTRY_END_M
    for _, b in df5.iterrows():
        bt = b['date']
        b_min = bt.hour * 60 + bt.minute
        # V2.5.20 2026-09-02 FORMING-BAR FIX -- a 5m bucket may only fire a signal
        # once it is COMPLETE. upstox_kite_shim._bucket_start anchors buckets at
        # SESSION_OPEN=(9,15), and df5's LAST row is the still-forming bucket. With
        # a 30s loop that bucket can hold as little as ONE 1m candle -- which passes
        # the `body > 50% of range` filter trivially, defeating the whole point of
        # that filter (it exists to demand a decisive FIVE-minute bar).
        # EVIDENCE (2026-09-01, reproduced from run.log): ORB fired at 09:45 with
        # "close 24026.6" -- that is the 1-MINUTE close at 09:45, off a bucket
        # holding one candle (body 0.664). NEITHER completed 5m bar qualified that
        # morning: 09:40-09:44 closed 24028.35 (ABOVE the OR low 24027.8, no break)
        # and 09:45-09:49 had body 0.433 (< 0.5). That -Rs975 ORB_STOP was a trade
        # that should never have existed. Replay over 10 NIFTY expiries: the bug
        # flips the traded SIDE on 3 of 10 days (07-14, 08-18, 09-01).
        # Mirrors the two places that already get this right:
        # check_fut5m_vwap_scalp_signal() reads iloc[-2] (last CLOSED bar), and
        # is_orb_day_chop_killed() drops the forming bar via d15.iloc[:-1].
        if b_min + 5 > _now_min:
            continue   # bucket still forming -- not a valid signal bar yet
        if b_min < entry_start_min or b_min > entry_end_min:
            continue
        o, h, l, c = float(b['open']), float(b['high']), float(b['low']), float(b['close'])
        rng = h - l
        if rng <= 0 or abs(c - o) / rng <= 0.5:
            continue
        if c > orh:
            side = 'CE'
        elif c < orl:
            side = 'PE'
        else:
            continue
        DAY.orb_fired = True
        linfo(f"[ORB] Signal — close {c:.1f} broke OR[{orl:.1f},{orh:.1f}] side={side}")
        picked = pick_strike_by_premium(c, side, expiry_lookup, ORB_PREM_MIN, ORB_PREM_MAX,
                                         ORB_STRIKE_STEP, ORB_STRIKE_SEARCH_RINGS)
        if picked is None:
            linfo("[ORB] No tradeable strike in premium band — no-op for the day")
            return None
        strike, symbol, token, prem = picked
        return {
            'engine': 'ORB', 'side': side,
            'detail': f'ORB break {c:.0f} vs OR[{orl:.0f},{orh:.0f}]',
            'trigger': 0.0, 'level_obj': None, 'target_spot': None,
            'kind': f'ORB_{side}', 'is_flip': False,
            '_strike': strike, '_symbol': symbol, '_token': token, '_premium': prem,
        }
    return None  # no breach yet this tick — try again next tick


def check_gapbreak_signal(df5, expiry_lookup):
    """V2.5.20 live GAPBREAK (gap-day range-break). Ported from
    gapbreak_signal_for_day() + the confirm-entry wait state in
    orion_concurrent_engine.py's run_day_concurrent(). NO day-type filter here
    (the SIDEWAYS filter validated for ORB made GAPBREAK worse -- see
    orion-daytype-filter-orb-gapbreak-result memory)."""
    if DAY.gap_fired:
        return None
    if DAY.prev_close is None or df5 is None or len(df5) == 0 or 'date' not in df5.columns:
        return None
    # V2.5.20 CRITICAL FIX (2026-07-06): same bug as check_orb_signal -- df5
    # (from fetch_nifty_5m(days_back=3)) holds multiple calendar days, but
    # every scan below only checked TIME-OF-DAY, never DATE. Left unfixed,
    # `df5['open'].iloc[0]` below reads a PRIOR DAY's opening price as
    # "today_open" (corrupting the gap calc from the very first line), the
    # first-30m range would blend multiple days' mornings together, and the
    # confirm-entry scan could match a stale prior-day bar exactly like the
    # real ORB incident this fix addresses. See
    # orion-v2520-stale-data-signal-bug memory.
    _now_ist = datetime.now(IST)
    today = _now_ist.date()
    _now_min = _now_ist.hour * 60 + _now_ist.minute
    df5 = df5[df5['date'].dt.date == today]
    if len(df5) == 0:
        return None

    # ---- Stage 1: detect the break (gap -> first-30m range -> break) --------
    if DAY.gap_sig is None:
        today_open = float(df5['open'].iloc[0])
        gap = today_open - DAY.prev_close
        if abs(gap) <= GAP_THRESH_PTS:
            DAY.gap_fired = True   # not a gap day — stand down for the day
            return None
        f6 = df5[(df5['date'].dt.hour * 60 + df5['date'].dt.minute) < (9 * 60 + 45)]
        if len(f6) == 0:
            return None   # first-30m range not formed yet
        h30, l30 = float(f6['high'].max()), float(f6['low'].min())
        for _, b in df5.iterrows():
            bt = b['date']
            b_min = bt.hour * 60 + bt.minute
            # V2.5.20 2026-09-02 FORMING-BAR FIX -- same defect as check_orb_signal
            # (see the full evidence block there). GAPBREAK scans df5 the same way
            # and so could also fire off a partially-formed 5m bucket. Unlike ORB
            # this engine has no body filter, but a forming bucket's CLOSE is just
            # the latest 1m close, so the range-break test was being applied to an
            # intra-bar tick rather than a settled 5m close.
            if b_min + 5 > _now_min:
                continue   # bucket still forming -- not a valid signal bar yet
            if b_min < 9 * 60 + 45 or b_min > 15 * 60:
                continue
            c = float(b['close'])
            if c > h30:
                side = 'CE'
            elif c < l30:
                side = 'PE'
            else:
                continue
            DAY.gap_sig = {'side': side, 'spot': c, 'gap': gap, 'bar_time': bt}
            linfo(f"[GAPBREAK] Range-break detected — close {c:.1f} broke "
                  f"[{l30:.1f},{h30:.1f}] side={side} (gap={gap:+.1f})")
            break
        if DAY.gap_sig is None:
            return None

    # ---- Stage 2: confirm-entry — wait up to GAP_CONFIRM_BARS 5m bars for a
    # close beyond the PREVIOUS confirm-check bar's close before actually
    # entering (ported from the pend["prev_close"]/n_checked state machine). --
    gs = DAY.gap_sig
    if DAY.gap_pending is None:
        DAY.gap_pending = {'side': gs['side'], 'ref_close': gs['spot'], 'n_checked': 0,
                            'last_bar_time': gs['bar_time']}
    pend = DAY.gap_pending
    # Only advance the confirm state machine on a NEW closed 5m bar past the break bar.
    later = df5[df5['date'] > pend['last_bar_time']]
    if len(later) == 0:
        return None
    b = later.iloc[0]
    bclose = float(b['close'])
    pend['last_bar_time'] = b['date']
    pend['n_checked'] += 1
    if bclose > pend['ref_close'] and (b['date'].hour * 60 + b['date'].minute) <= 15 * 60:
        DAY.gap_fired = True
        side = pend['side']
        linfo(f"[GAPBREAK] Confirmed — bar close {bclose:.1f} > ref {pend['ref_close']:.1f}")
        picked = pick_strike_by_premium(bclose, side, expiry_lookup, GAP_PREM_MIN, GAP_PREM_MAX,
                                         ORB_STRIKE_STEP, ORB_STRIKE_SEARCH_RINGS)
        DAY.gap_pending = None
        if picked is None:
            linfo("[GAPBREAK] No tradeable strike in premium band — no-op for the day")
            return None
        strike, symbol, token, prem = picked
        return {
            'engine': 'GAPBREAK', 'side': side,
            'detail': f'GAP break confirmed, gap={gs["gap"]:+.0f}',
            'trigger': 0.0, 'level_obj': None, 'target_spot': None,
            'kind': f'GAP_{side}', 'is_flip': False,
            '_strike': strike, '_symbol': symbol, '_token': token, '_premium': prem,
        }
    elif pend['n_checked'] >= GAP_CONFIRM_BARS:
        DAY.gap_fired = True   # no up-bar within GAP_CONFIRM_BARS -- skip today
        DAY.gap_pending = None
        linfo(f"[GAPBREAK] No confirm within {GAP_CONFIRM_BARS} bars — skipping for the day")
        return None
    else:
        pend['ref_close'] = bclose   # backtest: pend["prev_close"] = bclose (rolling ref)
        return None


def check_expiry_signal(df5, expiry_lookup):
    """V2.5.20 NEW (2026-07-26) -- EXPIRY: OTM premium-multiplication pop,
    real expiry day only. See the EXPIRY_ENABLED constants-block comment for
    the full retrospective basis and the explicit "not walk-forward validated
    as a forward entry rule" caveat -- this is a first live cut to start
    accruing real tick data, not a proven edge; ships because
    EXECUTION_BROKER is currently paper-only (no real money at risk).

    Live translation of the retrospective finding: a >=2x pop happens when
    the spot move brings a specific OTM strike into MONEYNESS CONVERGENCE
    (near/through the money), triggered by a round-level break. Detects: the
    latest closed spot 5m bar crosses a round-50 level (open and close on
    opposite sides of a round-50, matching ORB's decisive-candle convention:
    body >= 50% of the bar's own range) -- direction of the cross gives the
    side (down-cross -> PE, up-cross -> CE). Picks the nearest tradeable
    strike (premium in [EXPIRY_PREM_MIN,EXPIRY_PREM_MAX]) within
    EXPIRY_DIST_MAX rings of the POST-break ATM -- i.e. a strike already at
    or very near the money after this exact break, not a random OTM strike.

    SIMPLIFICATION: the retrospective study's volume-surge confirmation
    (winners: 4.6x E-day/E-1 volume ratio vs losers' 1.74x) is NOT checked
    live -- no per-strike 5m volume history is cached anywhere in the hot
    loop yet. Trades on the level-break + moneyness-distance alone.

    Fires at most once per day (ORB/GAPBREAK convention)."""
    if not EXPIRY_ENABLED or DAY.expiry_fired:
        return None
    if TARGET_EXPIRY_DATE is None:
        return None
    _exp_d = TARGET_EXPIRY_DATE.date() if isinstance(TARGET_EXPIRY_DATE, datetime) else TARGET_EXPIRY_DATE
    if datetime.now(IST).date() != _exp_d:
        return None   # real expiry day only -- never assumed
    now = datetime.now(IST)
    entry_start_min = EXPIRY_ENTRY_START_H * 60 + EXPIRY_ENTRY_START_M
    entry_end_min   = EXPIRY_ENTRY_END_H * 60 + EXPIRY_ENTRY_END_M
    now_min = now.hour * 60 + now.minute
    if now_min < entry_start_min or now_min > entry_end_min:
        return None
    if df5 is None or len(df5) == 0 or 'date' not in df5.columns:
        return None
    today = now.date()
    df5 = df5[df5['date'].dt.date == today]
    if len(df5) < 2:
        return None
    bar = df5.iloc[-2]   # latest CLOSED 5m bar
    bar_time = bar['date']
    # Dedup: same <=-not-== convention as the 2026-07-26 FUT5VWAP fix -- a
    # stale/out-of-order refetch serving an older bar after a newer one had
    # already been seen must not re-trigger.
    if DAY.expiry_last_bar_time is not None and bar_time <= DAY.expiry_last_bar_time:
        return None
    DAY.expiry_last_bar_time = bar_time
    o, h, l, c = float(bar['open']), float(bar['high']), float(bar['low']), float(bar['close'])
    rng = h - l
    if rng <= 0 or abs(c - o) / rng < 0.5:
        return None   # not a decisive candle
    o_zone, c_zone = int(o // EXPIRY_ROUND_STEP), int(c // EXPIRY_ROUND_STEP)
    if o_zone == c_zone:
        return None   # did not cross a round-50 level this bar
    side = 'PE' if c < o else 'CE' if c > o else None
    if side is None:
        return None
    DAY.expiry_fired = True
    linfo(f"[EXPIRY] Signal — round-level cross {o:.0f}->{c:.0f} (zone {o_zone}->{c_zone}) "
          f"side={side} at {bar_time}")
    picked = pick_strike_by_premium(c, side, expiry_lookup, EXPIRY_PREM_MIN, EXPIRY_PREM_MAX,
                                     EXPIRY_STRIKE_STEP, EXPIRY_DIST_MAX)
    if picked is None:
        linfo("[EXPIRY] No tradeable near-ATM strike in premium band — no-op for the day")
        return None
    strike, symbol, token, prem = picked
    return {
        'engine': 'EXPIRY', 'side': side,
        'detail': f'Expiry-day round-level break {o:.0f}->{c:.0f}, near-ATM convergence',
        'trigger': 0.0, 'level_obj': None, 'target_spot': None,
        'kind': f'EXPIRY_{side}', 'is_flip': False,
        '_strike': strike, '_symbol': symbol, '_token': token, '_premium': prem,
    }


def check_morning_vwap15_signal(df15m_fut, spot=None):
    """V2.5.19 FEATURE 3: 09:15-10:15 exception to the 09:45 start gate.
    Latest closed FUT 15m bar (iloc[-2]) crosses its session VWAP with body in the
    65-86% band AND close > MORNING_VWAP_SR_MIN_DIST pts from EVERY pivot
    S1/R1/S2/R2 -> buy in the cross direction. Engine 'VWAP' (inherits the VWAP
    option-VWAP trail). One trade per qualifying bar (deduped); re-entries via the
    momentum gate. Caller restricts this to the morning window."""
    if not MORNING_VWAP_ENABLED:
        return None
    if df15m_fut is None or len(df15m_fut) < 3:
        return None
    fut_vwap = compute_nifty_vwap_today(df15m_fut)
    if fut_vwap is None:
        return None

    bar = df15m_fut.iloc[-2]
    bar_time = bar.name
    bo = float(bar['open']); bh = float(bar['high'])
    bl = float(bar['low']);  bc = float(bar['close'])
    rng = bh - bl
    if rng <= 0:
        return None
    body_pct = abs(bc - bo) / rng
    if body_pct < VWAP_BODY_MIN_PCT or body_pct >= VWAP_BODY_CLIMAX_PCT:
        return None

    bullish = bc > fut_vwap
    bearish = bc < fut_vwap
    if not bullish and not bearish:
        return None

    if DAY.last_morning_vwap_bar_time is not None and bar_time == DAY.last_morning_vwap_bar_time:
        return None

    mind = fut_pivot_dist(bc, df15m_fut, spot)   # 2026-09-28 pivot basis fix
    if mind is not None and mind <= MORNING_VWAP_SR_MIN_DIST:
        linfo(f"[MVWAP] Skip — close {bc:.0f} only {mind:.0f}pt from a pivot "
              f"(need >{MORNING_VWAP_SR_MIN_DIST:.0f})")
        return None

    side = 'CE' if bullish else 'PE'
    detail = (f"MORNING FUT VWAP {bc:.0f}{'>' if bullish else '<'}{fut_vwap:.0f} "
              f"body={body_pct:.0%} pivΔ={mind:.0f}pt | bar={bar_time}"
              if mind is not None else
              f"MORNING FUT VWAP {bc:.0f}{'>' if bullish else '<'}{fut_vwap:.0f} "
              f"body={body_pct:.0%} piv=NA | bar={bar_time}")
    DAY.last_morning_vwap_bar_time = bar_time
    # Share the VWAP dedup so the 09:45+ engine won't immediately re-fire the same bar
    DAY.last_vwap_bar_time = bar_time
    linfo(f"[MVWAP] Signal — {bc:.0f}{'>' if bullish else '<'}{fut_vwap:.0f} "
          f"body={body_pct:.0%} side={side} (morning exception)")
    return {
        'engine': 'VWAP', 'side': side, 'detail': detail,
        'trigger': fut_vwap, 'level_obj': None,
        'target_spot': None, 'kind': f'BREAK_{side}'
    }


def check_flip_signal(df15m, now):
    """V2.5.2: opposite-side flip on 15m K reversal.
    Looks at most recent closed 15m K vs previous closed K.
    Returns sig dict if flip should fire, None otherwise.

    Path A (in-trade): handled at exit time via close_trade -> immediate flip check
                       (this same function is called right after close).
    Path B (post-exit): each subsequent 15m close within FLIP_PATH_B_WATCH_MIN.
    """
    if not FLIP_ENABLED:
        return None
    if DAY.last_exit is None:
        return None
    if DAY.flips_today >= MAX_FLIPS_PER_DAY:
        return None
    # Path B watch window expired?
    age_min = (now - DAY.last_exit['exit_time']).total_seconds() / 60.0
    if age_min > FLIP_PATH_B_WATCH_MIN:
        DAY.last_exit = None
        return None
    # Read K and K_prev from latest closed 15m bar
    if df15m is None or len(df15m) < 3:
        return None
    K      = df15m['K'].iloc[-2]
    K_prev = df15m['K'].iloc[-3]
    if pd.isna(K) or pd.isna(K_prev):
        return None
    K      = float(K)
    K_prev = float(K_prev)
    last_side = DAY.last_exit['side']
    # CE -> PE flip: K falling within band [25, 80]
    if last_side == 'CE' and K < K_prev and FLIP_K_CE_TO_PE_MIN <= K <= FLIP_K_CE_TO_PE_MAX:
        # 2026-07-13 PUT-FLIP QUALITY GATE (see put_flip_ok / constants block)
        _pf_ok, _pf_why = put_flip_ok(K, K_prev)
        if not _pf_ok:
            linfo(f"[FLIP] PUT-flip BLOCKED — {_pf_why} (K={K:.1f} prev={K_prev:.1f})")
            return None
        return {'engine':'FLIP', 'side':'PE',
                'detail': f'FLIP CE->PE K={K:.1f} (prev {K_prev:.1f}) age={age_min:.0f}min',
                'trigger': 0.0}
    # PE -> CE flip: K rising, K >= 38
    if last_side == 'PE' and K > K_prev and K >= FLIP_K_PE_TO_CE_MIN:
        return {'engine':'FLIP', 'side':'CE',
                'detail': f'FLIP PE->CE K={K:.1f} (prev {K_prev:.1f}) age={age_min:.0f}min',
                'trigger': 0.0}
    return None


def is_path_a_eligible() -> bool:
    """V2.5.2 Path A: check if just-closed POS meets Path A criteria.
    Called inside main-loop right BEFORE close_trade so POS is still active.
    Returns True if Path A flip should fire immediately after close.

    Conditions:
      elapsed >= FLIP_PATH_A_ELAPSED_MIN AND
      peak_premium >= entry + FLIP_PATH_A_PEAK_MIN_PTS AND
      current_LTP <= entry + FLIP_PATH_A_DROP_MAX_PTS
    (K reversal will be checked by check_flip_signal afterwards.)
    """
    if not FLIP_ENABLED: return False
    if not POS.active:   return False
    if POS.entry_premium <= 0: return False
    elapsed = POS.elapsed_min()
    if elapsed < FLIP_PATH_A_ELAPSED_MIN: return False
    peak_above = POS.peak_premium - POS.entry_premium
    if peak_above < FLIP_PATH_A_PEAK_MIN_PTS: return False
    cur = POS.last_pulse_premium if POS.last_pulse_premium > 0 else POS.peak_premium
    cur_above = cur - POS.entry_premium
    return cur_above <= FLIP_PATH_A_DROP_MAX_PTS

# =========================================================================
# OPEN / CLOSE
# PAPER mode (EXECUTION_BROKER="kite_paper")  : no real orders, LTP-based P&L
# LIVE  mode (EXECUTION_BROKER="mstock_live") : real market order via mStock
# =========================================================================
def _mstock_option_symbol(symbol_kite: str) -> str:
    """
    Convert Kite option symbol to mStock trading symbol.
    Kite stores symbols as 'NFO:NIFTY2660223600PE' for quote calls.
    mStock expects plain symbol without exchange prefix: 'NIFTY2660223600PE'.
    """
    for prefix in ('BFO:', 'NFO:', 'NSE:', 'BSE:', 'MCX:'):
        if symbol_kite.startswith(prefix):
            return symbol_kite[len(prefix):]
    return symbol_kite

def pick_strike_by_premium(spot, side, expiry_lookup, pmin, pmax, step=50, rings=15):
    """V2.5.20: nearest strike (50pt rings outward from ATM) with a real, live
    premium in [pmin,pmax] -- used by ORB/GAPBREAK instead of round_to_atm.
    Ported from orion_backtest_lab's pick_strike_by_premium/orb_pick_strike."""
    atm = round_to_atm(spot)
    for k in range(0, rings + 1):
        offsets = [0] if k == 0 else [-k * step, k * step]
        best = None
        for off in offsets:
            cand = atm + off
            key = (cand, side)
            if key not in expiry_lookup:
                continue
            symbol, token = expiry_lookup[key]
            prem = ltp(symbol)
            if prem is None or prem <= 0:
                continue
            if pmin <= prem <= pmax:
                dist = abs(cand - spot)
                if best is None or dist < best[0]:
                    best = (dist, cand, symbol, token, prem)
        if best is not None:
            return best[1], best[2], best[3], best[4]   # strike, symbol, token, premium
    return None


def open_trade(sig, spot, expiry_lookup, paper_only=False,
                strike_override=None, symbol_override=None,
                token_override=None, premium_override=None):
    """Open a trade. paper_only=True means CB hit in live mode — log as paper, no real orders.
    V2.5.20: ORB/GAPBREAK pass strike_override/symbol_override/token_override/
    premium_override (from pick_strike_by_premium) instead of round_to_atm."""
    side = sig['side']
    # 2026-07-13 COUNTER-TREND VETO — single choke point for every engine. The 3
    # breakout engines call open_trade() directly (bypassing _apply_entry_gates_
    # and_open), so gating here is the ONLY place that covers all 6; they are
    # exempted inside countertrend_veto() itself, not by skipping this call.
    _ct_blocked, _ct_reason = countertrend_veto(side, spot, sig.get('engine', ''))
    if _ct_blocked:
        linfo(f"[VETO] {sig.get('engine','?')} {side} BLOCKED — {_ct_reason}")
        # 2026-07-29: throttle the Telegram alert (see VETO_ALERT_COOLDOWN_MIN) —
        # the same bar re-fires this veto every cycle until the bar rolls over.
        _veto_key = (sig.get('engine', '?'), side)
        _now_ist = datetime.now(IST)
        _last_alert = _LAST_VETO_ALERT.get(_veto_key)
        if _last_alert is None or (_now_ist - _last_alert).total_seconds() / 60.0 >= VETO_ALERT_COOLDOWN_MIN:
            TG.send(f"🚫 <b>Counter-trend veto</b>\n"
                    f"   {sig.get('engine','?')} {side} not taken — {_ct_reason}")
            _LAST_VETO_ALERT[_veto_key] = _now_ist
        return False
    # 2026-09-19 NIFTY BLOCK GATE -- same choke point, same alert throttle. ORB/V3/FUT5VWAP only.
    _nb_blocked, _nb_reason = nifty_block_gate(sig.get('engine', ''), side)
    if _nb_blocked:
        linfo(f"[NIFTYGATE] {sig.get('engine','?')} {side} BLOCKED — {_nb_reason}")
        _nb_key = ('NIFTYGATE', sig.get('engine', '?'), side)
        _now_ist = datetime.now(IST)
        _last_alert = _LAST_VETO_ALERT.get(_nb_key)
        if _last_alert is None or (_now_ist - _last_alert).total_seconds() / 60.0 >= VETO_ALERT_COOLDOWN_MIN:
            TG.send(f"🛑 <b>NIFTY block gate</b>\n"
                    f"   {sig.get('engine','?')} {side} not taken — {_nb_reason}")
            _LAST_VETO_ALERT[_nb_key] = _now_ist
        return False
    if strike_override is not None:
        strike, symbol, token, cur_ltp = strike_override, symbol_override, token_override, premium_override
    else:
        strike = round_to_atm(spot)
        key = (strike, side)
        if key not in expiry_lookup:
            lwarn(f"Strike {strike} {side} not in expiry lookup; skipping entry")
            return False
        symbol, token = expiry_lookup[key]
        cur_ltp = ltp(symbol)
        if cur_ltp is None or cur_ltp <= 0:
            lwarn(f"Cannot fetch LTP for {symbol}; skipping entry")
            return False
        # Premium gate: asymmetric — PE cap raised to 300 to capture panic/downside moves
        prem_max = PREMIUM_MAX_PE if side == 'PE' else PREMIUM_MAX_CE
        if not (PREMIUM_MIN <= cur_ltp <= prem_max):
            lwarn(f"Premium {cur_ltp:.2f} outside gate [{PREMIUM_MIN},{prem_max}] ({side}); skipping entry")
            return False
    # 2026-09-29 V2 LOG-ONLY (user: "shutdown V2 in both indices and do it offline").
    # Placed AFTER every gate and the strike/LTP pick, so the log is exactly what V2
    # would have bought. No position is opened. Kill switch: V2_LOG_ONLY = False.
    if V2_LOG_ONLY and sig.get('engine', '') == 'V2':
        linfo(f"[V2] WOULD_ENTER(log-only) {side} {symbol} @ {cur_ltp:.2f} spot={spot} | {sig.get('detail','')}")
        try:
            import json as _j
            with open(V2_SHADOW_LOG, 'a') as _f:
                _f.write(_j.dumps({'ts': datetime.now(IST).isoformat(), 'bot': 'SENSEX', 'side': side, 'symbol': symbol,
                                   'strike': strike, 'ltp': cur_ltp, 'spot': spot, 'detail': sig.get('detail', '')}) + "\n")
        except Exception as _e:
            lwarn(f"[V2] shadow log write failed: {_e}")
        return False
    # Stage fields before confirming order (do not set POS.active yet for live mode)
    POS.engine        = sig['engine']
    POS.engine_detail = sig['detail']
    POS.side          = side
    POS.strike        = strike
    POS.symbol        = symbol
    POS.ms_symbol     = _mstock_option_symbol(symbol)  # strip NFO: → NIFTY2660223500PE (proven format)
    POS.token         = token
    POS.entry_time    = datetime.now(IST)
    POS.entry_premium = cur_ltp
    POS.entry_spot    = spot
    POS.trigger_value = sig['trigger']
    POS.peak_premium  = cur_ltp
    POS.hardsl_premium = cur_ltp * (1 - HARDSL_PCT)
    POS.sl_current     = POS.hardsl_premium
    POS.trough_premium = cur_ltp
    # 2026-08-29: the OPTION's own 14x1min ATR at entry. Recorded, not acted on.
    # The 08-29 study found -18%% sits INSIDE the option's normal 60-min range
    # (5 of 7 stops fired on index moves under 0.1%%), but the ATR-stop backtest
    # could not clear G1, so this is logged to answer the question forward.
    POS.atr_entry = _option_atr(POS.token)
    # Take the expiry the bot ACTUALLY resolved. Parsing it back out of the
    # tradingsymbol is unsafe for monthly contracts: the day is not encoded,
    # and 'last Thursday' is wrong on both exchanges now (NSE weekly expiry
    # is Tuesday, BSE Thursday) -- a test decoded NIFTY26AUG as 08-31 when
    # the real August expiry was 08-25.
    POS.expiry_date = (TARGET_EXPIRY_DATE.date()
                       if isinstance(TARGET_EXPIRY_DATE, datetime)
                       else TARGET_EXPIRY_DATE)
    POS.tr_armed       = False
    POS.tr_sl          = 0.0
    if sig['engine'] in ('ORB', 'GAPBREAK'):
        # V2.5.20: touch-stop/lock/ride engines -- own fields, not %-HARDSL/trail-arm.
        POS.hardsl_premium = -1e9   # never trip the generic %-HARDSL check
        DAY.floor = None
        DAY.is_flip = sig.get('is_flip', False)
        POS.declared_target_premium = cur_ltp + (ORB_LOCK_PTS if sig['engine'] == 'ORB' else GAP_LOCK_PTS)
        POS.declared_target_spot = None
    elif sig['engine'] == 'FUT5VWAP':
        # V2.5.20: touch-stop/lock/ride exit fix (validated) -- own fields, not
        # %-HARDSL/trail-arm. is_flip is always True: FUT5VWAP never flips on
        # stop (matches the backtest's no-op flip_cb for this engine).
        POS.hardsl_premium = -1e9
        DAY.floor = None
        DAY.is_flip = True
        POS.declared_target_premium = cur_ltp + FUT5_FIX_LOCK_PTS
        POS.declared_target_spot = None
    elif sig['engine'] == 'V2':
        # 2026-08-20 user-directed: fixed -15pt stop replaces the generic
        # -18% HARDSL for V2 specifically (paired with the same-day trail-arm
        # scaling to entry premium, see V2_TRAIL_ARM_PCT). NOT backtested --
        # V2 has no per-cycle peak/loss-path log to validate against (same
        # caveat as the trail-arm change). On V2's cheap end (~Rs73, the
        # 08-13 cluster) -15pt is TIGHTER than -18% (~-13.1pt) would have
        # been; on the expensive end (~Rs171, 07-23 cluster) -15pt is LOOSER
        # than -18% (~-30.8pt) would have been -- opposite tradeoff direction
        # from the trail-arm change, watch both together.
        POS.hardsl_premium = cur_ltp - V2_HARDSL_PTS
        POS.sl_current = POS.hardsl_premium
        POS.declared_target_premium = cur_ltp * 1.25
        POS.declared_target_spot = None
    elif sig['engine'] == 'FLIP':
        POS.declared_target_premium = cur_ltp * 1.25
        POS.declared_target_spot = None
        DAY.flips_today += 1  # V2.5.4 counter (capped at MAX_FLIPS_PER_DAY)
        DAY.last_exit = None  # consume the watch — flip just fired
    else:
        POS.declared_target_premium = 0.0
        POS.declared_target_spot = sig.get('target_spot')
        if sig.get('level_obj') is not None:
            DAY.fired_levels.add(sig['level_obj']['center'])
    # V2.5.9+: compute option VWAP for informational context
    POS.entry_vwap = compute_option_vwap(token)

    # ---- Live execution via mStock ----
    # V2.5.20 (2026-07-10 fix): a real BUY order that FAILS at the broker level (rejected,
    # no fill, timeout) no longer aborts the trade -- it falls back to a PAPER-tracked
    # position instead. User directive: the strategy should keep running (and its exit
    # still fire normally later via the ordinary check_exits/close_trade path, which
    # already skips any live SELL when POS.buy_order_id is empty) even when no real money
    # went in, so performance is still tracked and Telegram still reports a normal
    # entry+exit pair -- just clearly tagged as paper. This directly targets the incident
    # where a BUY silently "failed" (insufficient funds -- funds were tied up by the
    # user's own manual trade the same window) but the signal/trade was otherwise valid;
    # previously this just vanished with an alert and no further tracking.
    # Only genuine INFRA problems (broker completely unreachable, or an active IA403
    # halt already in effect) still hard-abort -- those aren't a per-order failure, they
    # mean we have no reliable way to even simulate a fill right now.
    # V2.5.20 (2026-07-14): default to "not held at the broker" and let a confirmed live
    # BUY clear it. Fail-safe direction: a real position mislabelled paper is a reporting
    # bug; a paper position mislabelled real is only ever a rejected SELL.
    POS.is_paper = True
    POS.unconfirmed_fill = False

    if paper_only:
        linfo(f"[PAPER-FALLBACK] CB hit — logging as paper trade (no real order): {POS.ms_symbol}")
    elif EXECUTION_BROKER == "mstock_live":
        # tg_escape: engine detail strings embed '<'/'>' (e.g. "24170<24175" from the
        # VWAP/FUT5VWAP cross), which Telegram HTML parse_mode reads as tags → 400
        # "Unsupported start tag" and a plain-text-fallback resend. Escape once here
        # since _sig_info is only ever inserted into <i>...</i> HTML alerts below.
        _sig_info = tg_escape(f"Engine:{sig['engine']} | {sig.get('detail','')}")
        broker = _get_mstock()
        if not broker:
            lwarn("[mstock] Broker unavailable — BUY aborted, no position opened.")
            TG.send(f"⚠️ mStock broker unavailable. BUY aborted.\n"
                    f"<i>{_sig_info}</i>")
            POS.engine = ""; POS.side = ""; POS.symbol = ""; POS.ms_symbol = ""; POS.token = 0
            POS.entry_time = None; POS.entry_premium = 0.0; POS.peak_premium = 0.0
            POS.hardsl_premium = 0.0; POS.sl_current = 0.0
            return False
        # IA403 halt — stop spamming orders if mStock keeps rejecting
        if DAY.ia403_halted:
            lwarn("[mstock] IA403 halt active — skipping BUY. Restart bot or wait for daily reset.")
            POS.engine = ""; POS.side = ""; POS.symbol = ""; POS.ms_symbol = ""; POS.token = 0
            POS.entry_time = None; POS.entry_premium = 0.0; POS.peak_premium = 0.0
            POS.hardsl_premium = 0.0; POS.sl_current = 0.0
            return False
        ms_sym = POS.ms_symbol  # NIFTY2660223500PE — Kite compact format, confirmed working
        qty = lots_for(POS.engine) * LOT_SIZE
        _live_buy_ok = False
        oid = broker.place_order("BUY", ms_sym, qty, "MARKET")
        if not oid:
            _err = getattr(broker, '_last_error', '') or 'no orderid returned'
            lwarn(f"[mstock] BUY place_order returned None — falling back to PAPER. err={_err}")
            _is_ip_err = 'IA403' in _err or 'ip' in _err.lower() or 'whitelist' in _err.lower()
            if _is_ip_err:
                DAY.ia403_consecutive += 1
                if DAY.ia403_consecutive == 1:
                    TG.send(f"🚫 <b>ORDER BLOCKED — IA403 (1st)</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"⚠️ mStock IA403 — likely session/token issue (Type B has no secondary IP).\n"
                            f"📋 Signal: {ms_sym}\n"
                            f"📄 Falling back to PAPER — no real order, but signal is now tracked as a paper trade.\n"
                            f"<code>{_err}</code>\n"
                            f"<i>{_sig_info}</i>")
                if DAY.ia403_consecutive >= 3:
                    DAY.ia403_halted = True
                    TG.send(f"⛔⛔⛔ <b>IA403 HALT — 3 consecutive failures</b> ⛔⛔⛔\n"
                            f"mStock keeps rejecting orders. Bot will NOT retry until restarted.\n"
                            f"Check mStock portal / session / token.\n"
                            f"<code>{_err}</code>")
                    lwarn(f"[mstock] IA403 halt triggered after {DAY.ia403_consecutive} consecutive failures.")
                else:
                    lwarn(f"[mstock] IA403 count: {DAY.ia403_consecutive}/3")
            elif 'FUND LIMIT INSUFFICIENT' in _err.upper() or 'INSUFFICIENT FUND' in _err.upper():
                # No halt, no consecutive-failure counter -- a funds shortfall is not a
                # broker/session problem, so signals must keep firing normally on every
                # subsequent bar/event, exactly like a filled trade would.
                TG.send(f"💸 <b>TRADE SIGNAL FIRED — REAL ORDER FAILED (INSUFFICIENT FUNDS)</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📋 Signal: {ms_sym}  (qty {qty})\n"
                        f"📄 No real order — not enough margin. Continuing as a PAPER trade so the "
                        f"exit is still tracked normally.\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"<code>{_err}</code>\n"
                        f"<i>{_sig_info}</i>\n"
                        f"<i>Bot continues; every future signal will still fire and alert normally.</i>")
                lwarn(f"[mstock] BUY failed — insufficient funds ({ms_sym}). Falling back to PAPER.")
            else:
                DAY.ia403_consecutive = 0  # non-IA403 error resets the counter
                TG.send(f"🚫 <b>ORDER FAILED — API/BROKER ISSUE</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚠️ This is a <b>broker-side issue</b>, NOT a market signal failure.\n"
                        f"📋 Signal fired: {ms_sym}\n"
                        f"📄 Falling back to PAPER — no real order.\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"<code>Error: {_err}</code>\n"
                        f"<i>{_sig_info}</i>")
        else:
            status, fill = broker.wait_for_fill(oid, timeout_sec=15)
            if status == "TIMEOUT":
                broker.cancel_order(oid)
                time.sleep(2)
                status2, fill2 = broker.order_status(oid)
                if status2 == "COMPLETE" and fill2 and fill2 > 0:
                    fill = fill2; status = "COMPLETE"
                else:
                    lwarn(f"[mstock] BUY timeout, order cancelled — falling back to PAPER ({ms_sym}).")
                    TG.send(f"⏱️ <b>ORDER TIMEOUT — CANCELLED</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"⚠️ This is an <b>exchange/latency issue</b>, NOT a market signal failure.\n"
                            f"📋 Signal fired: {ms_sym}\n"
                            f"📄 Order sent but timed out before fill — cancelled. Falling back to PAPER.\n"
                            f"<i>{_sig_info}</i>")
            if status == "COMPLETE" and fill and fill > 0:
                # V2.5.20 (2026-07-14 fix): a COMPLETE status carrying a real fill price is
                # treated as a REAL position, ALWAYS. The position book is polled only to
                # CONFIRM it, never to veto it.
                #
                # This reverses the 2026-07-11 logic, which took "not in the position book
                # after 3 one-second polls" as proof of an RMS rejection and silently
                # downgraded the trade to paper (clearing buy_order_id, which also disables
                # close_trade()'s live SELL). On 2026-07-14 mStock's position book simply
                # lagged the fill by more than 3s, so that guard fired on three genuinely
                # filled orders and abandoned 3 real lots of NIFTY2671424100PE -- no stop, no
                # trail, no force-close, while Telegram printed clean paper exits for them.
                #
                # The asymmetry matters: if we wrongly believe we own a position, the worst
                # case is a SELL the broker rejects -- loud, visible, and already reconciled
                # by close_trade()'s MANUAL_EXIT_APPROX path. If we wrongly believe we DON'T,
                # we walk away from real money with no risk management at all. Only genuine
                # rejection evidence (place_order returned None, status REJECTED/CANCELLED,
                # or no fill price) may route to paper -- and that is handled in the branches
                # below, not here.
                _live_buy_ok = True
                DAY.ia403_consecutive = 0  # successful order resets IA403 counter
                POS.entry_premium  = fill
                if POS.hardsl_premium == -1e9:
                    pass  # ORB/GAPBREAK/FUT5VWAP -- own stop, never recompute here
                elif POS.engine == 'V2':
                    POS.hardsl_premium = fill - V2_HARDSL_PTS   # re-anchor fixed-pt stop to actual fill
                else:
                    POS.hardsl_premium = fill * (1 - HARDSL_PCT)
                POS.sl_current     = POS.hardsl_premium
                POS.peak_premium   = fill
                POS.buy_order_id   = oid
                POS.own_sell_order_ids = []  # fresh position — clear any stale IDs from a prior trade
                POS.is_paper = False

                # Confirmation only. Poll the position book with a realistic settlement
                # window (was 3x1s -- too tight for mStock, which is what caused the bug).
                if broker.verify_position(ms_sym, qty, retries=10, delay_sec=2.0):
                    POS.unconfirmed_fill = False
                    linfo(f"[mstock] BUY filled + position CONFIRMED: {ms_sym} qty={qty} "
                          f"fill={fill:.2f} order={oid}")
                else:
                    POS.unconfirmed_fill = True
                    lwarn(f"[mstock] BUY {ms_sym} COMPLETE (fill={fill:.2f}, order={oid}) but the "
                          f"position book still does not show it after 20s. Treating it as a REAL "
                          f"position and managing it normally — NOT downgrading to paper.")
                    TG.send(f"🚨 <b>UNCONFIRMED FILL — TREATING AS REAL</b> 🚨\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"📋 {ms_sym}  |  order={oid}  |  fill=₹{fill:.2f}\n"
                            f"⚠️ mStock reported this BUY <b>COMPLETE</b> but the position book "
                            f"has not shown the holding after 20s.\n"
                            f"✅ The bot is treating it as a <b>REAL open position</b> and will "
                            f"stop/trail/exit it normally.\n"
                            f"👉 <b>Please check your broker position book.</b> If the lot is NOT "
                            f"there, the exit SELL will simply be rejected — harmless.\n"
                            f"<i>{_sig_info}</i>")
            elif status != "TIMEOUT":  # TIMEOUT branch above already sent its own alert
                lwarn(f"[mstock] BUY rejected/no fill (status={status}) — falling back to PAPER.")
                TG.send(f"🚫 <b>ORDER REJECTED — NO FILL</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚠️ This is a <b>broker/exchange rejection</b>, NOT a market signal failure.\n"
                        f"📋 Signal fired: {ms_sym}  |  Status: {status}\n"
                        f"📄 Falling back to PAPER — no real order.\n"
                        f"<i>{_sig_info}</i>")
        if not _live_buy_ok:
            # Paper fallback: keep the already-staged entry_premium/hardsl_premium/peak
            # (set from cur_ltp before this block ran) as the simulated fill. No real
            # order id, so close_trade()'s live-SELL block is skipped automatically.
            # V2.5.20 (2026-07-14): reached ONLY on real rejection evidence now -- a
            # COMPLETE+fill order is never routed here (see the fill branch above).
            POS.buy_order_id = ""
            POS.is_paper = True   # makes the PAPER banner appear on entry AND exit
            linfo(f"[PAPER-FALLBACK] Real BUY failed for {POS.ms_symbol} — continuing as a "
                  f"PAPER trade (simulated fill {POS.entry_premium:.2f}) so its exit is still tracked.")

    # Position confirmed (paper or live fill) — mark active
    POS.active = True
    save_state()

    msg = fmt_entry()
    linfo(f"ENTRY: {POS.symbol} @ {POS.entry_premium:.2f}  engine={POS.engine}  "
          f"detail={POS.engine_detail}"
          f"{f' flips_today={DAY.flips_today}/{MAX_FLIPS_PER_DAY}' if sig['engine']=='FLIP' else ''}")
    TG.send(msg)
    return True

# Throttle for the "SELL blocked — position still open" CRITICAL Telegram so a genuine
# funding block can't spam hundreds of alerts (07-17: 246 rejections in 45 min). One alert
# per minute; episodes are minutes/hours apart so this also fires immediately for a new one.
_last_funding_alert_ts = 0.0

def _is_margin_reject(err: str) -> bool:
    """RMS rejected the order on funds/margin (MA200). On a SELL to CLOSE a long we believe
    we hold, this means the broker priced it as a FRESH NAKED SHORT — i.e. it sees no long to
    net against. Strong evidence the position was already closed outside the bot."""
    u = (err or "").upper()
    return any(s in u for s in ("FUND LIMIT INSUFFICIENT", "MA200", "SPAN & EXPOSURE"))


# ---------------------------------------------------------------------------
# 2026-08-29 TRADE RECORDER — one row per closed trade.
# WHY: the ENTRY: log line carries NO timestamp, so a closed trade cannot be
# located on the option's minute tape afterwards. Reconstructing entries by
# price-matching failed for 19 of 53 VWAP trades (64%), which is why the
# 2026-08-29 ATR-stop backtest could not clear its G1 gate. This file makes
# every future trade exactly replayable, and records the three things that
# analysis kept needing and not having: DTE (decay), MFE/MAE (was the stop
# right), and the option's own ATR at entry (is the stop inside the noise).
# ---------------------------------------------------------------------------
# Last spot the exit-checker saw. close_trade() is reached from several call
# sites that do not carry spot, so the recorder reads this instead. Refreshed
# every pulse in check_exits(), i.e. seconds old at worst.
LAST_SPOT = 0.0

# 2026-08-31 FIX: was `SCRIPT_DIR` (undefined) — the file only defines `_SCRIPT_DIR`.
# This NameError killed the bot on every boot attempt (50x) before EOD.
TRADES_CSV = os.path.join(_SCRIPT_DIR, "Sensex_Trades_V2_5_20.csv")
_TRADE_COLS = ["entry_ts","exit_ts","held_min","market","engine","engine_detail",
               "symbol","side","strike","expiry","dte","lots","lot_size",
               "entry_prem","exit_prem","reason","pts","rupees",
               "mfe_prem","mae_prem","mfe_pts","mae_pts","atr_entry","atr_pct",
               "sl_level","entry_spot","exit_spot","spot_move"]

def _expiry_from_symbol(sym):
    """NFO:NIFTY2690124300PE -> date(2026,9,1);  ...26AUG24000PE -> monthly expiry."""
    try:
        MON={'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
             'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
        b=sym.split(':')[-1]
        for u in ("NIFTY","SENSEX","BANKNIFTY"):
            if b.startswith(u): b=b[len(u):]; break
        b=b[:-2]                       # drop CE/PE
        yy=2000+int(b[:2]); b=b[2:]
        m=re.match(r"^([A-Z]{3})", b)
        if m: return None      # monthly: day not encoded -- do NOT guess
        mm=b[0]; dd=int(b[1:3])
        mon=int(mm) if mm.isdigit() else {'O':10,'N':11,'D':12}[mm]
        return date(yy,mon,dd)
    except Exception:
        return None


def _option_atr(token, n=14):
    """14-bar ATR of the option's own 1-minute candles. Best-effort: any failure
    returns 0.0 and is simply recorded as unknown -- never blocks an entry."""
    try:
        if not token: return 0.0
        rows = kite.historical_data(token,
                                    datetime.now(IST).date(), datetime.now(IST).date(),
                                    "minute")
        if not rows or len(rows) < n + 1: return 0.0
        r = rows[-(n+1):]
        tr = [max(r[i]["high"]-r[i]["low"],
                  abs(r[i]["high"]-r[i-1]["close"]),
                  abs(r[i]["low"] -r[i-1]["close"])) for i in range(1, len(r))]
        return sum(tr)/len(tr)
    except Exception:
        return 0.0

def record_trade(reason, exit_price, pnl_per_share, exit_spot=None):
    """Append one closed trade. Never allowed to break the exit path."""
    try:
        now_ = datetime.now(IST)
        exp  = POS.expiry_date or _expiry_from_symbol(POS.symbol)
        if isinstance(exp, str):   # 2026-09-16: expiry restored from state_*.json is a STRING -> 'str - date' TypeError silently dropped the 09-15 23400PE +Rs11,856 row
            try: exp = datetime.strptime(exp[:10], '%Y-%m-%d').date()
            except Exception: exp = None
        dte  = (exp - now_.date()).days if exp else ""
        lots = lots_for(POS.engine)
        mfe  = (POS.peak_premium   or POS.entry_premium) - POS.entry_premium
        mae  = (POS.trough_premium or POS.entry_premium) - POS.entry_premium
        row = {
            "entry_ts": POS.entry_time.strftime("%Y-%m-%d %H:%M:%S") if POS.entry_time else "",
            "exit_ts":  now_.strftime("%Y-%m-%d %H:%M:%S"),
            "held_min": round(POS.elapsed_min(),1),
            "market": "SENSEX", "engine": POS.engine, "engine_detail": str(POS.engine_detail).replace(",",";"),
            "symbol": POS.symbol, "side": POS.side, "strike": POS.strike,
            "expiry": exp.isoformat() if exp else "", "dte": dte,
            "lots": lots, "lot_size": LOT_SIZE,
            "entry_prem": round(POS.entry_premium,2), "exit_prem": round(exit_price,2),
            "reason": reason, "pts": round(pnl_per_share,2),
            "rupees": round(pnl_per_share*LOT_SIZE*lots),
            "mfe_prem": round(POS.peak_premium or 0,2), "mae_prem": round(POS.trough_premium or 0,2),
            "mfe_pts": round(mfe,2), "mae_pts": round(mae,2),
            "atr_entry": round(POS.atr_entry,2),
            "atr_pct": round(POS.atr_entry/POS.entry_premium*100,2) if POS.entry_premium else "",
            "sl_level": round(POS.sl_current,2),
            "entry_spot": round(POS.entry_spot,2) if POS.entry_spot else "",
            "exit_spot": round(exit_spot,2) if exit_spot else "",
            "spot_move": round(exit_spot-POS.entry_spot,2) if (exit_spot and POS.entry_spot) else "",
        }
        newf = not os.path.exists(TRADES_CSV)
        with open(TRADES_CSV,"a") as fh:
            if newf: fh.write(",".join(_TRADE_COLS)+"\n")
            fh.write(",".join(str(row.get(k,"")) for k in _TRADE_COLS)+"\n")
    except Exception as e:
        lwarn(f"[TRADEREC] could not record trade: {e}")

def close_trade(reason, exit_price):
    global _last_funding_alert_ts
    if not POS.active: return
    # ---- Live execution via mStock — retry SELL 3×, keep position open if all fail ----
    # Skip mStock SELL if this is a paper-fallback trade (no buy_order_id means no real position),
    # and ALSO skip it for reason=='MANUAL_EXIT' (V2.5.20, 2026-07-08 fix): a MANUAL_EXIT
    # means the user has ALREADY sold this position directly at the broker (found via
    # find_manual_sell() in the position-sync loop, using ITS real fill price as
    # exit_price). Placing another SELL here would try to sell a position that no
    # longer exists.
    #
    # V2.5.20 (2026-07-10 fix): moved this block to the TOP of close_trade() so it can
    # mutate `reason`/`exit_price` in place BEFORE any bookkeeping (trades_today, CB,
    # cooldown) runs -- previously this block ran AFTER bookkeeping had already recorded
    # the trade under the original reason, so there was no safe way to correct it once a
    # REJECTED sell revealed the position was already gone. Also: a REJECTED sell (broker
    # says "no such holding") is now distinguished from a merely slow/unfilled one -- it is
    # the single unambiguous broker-side signal that this position was already closed
    # outside the bot (manual square-off the sync loop's day-scoped order-book lookup
    # can't see -- e.g. crossed midnight -- or the broker's own INTRADAY EOD force-square-
    # off). Previously this was retried 3x like a normal fill failure, then gave up with
    # POS.active stuck True forever and a false CRITICAL alert every cycle after (that's
    # what produced 17 accumulated own_sell_order_ids on the stuck 2026-07-09 FUT5VWAP
    # position). Now: on REJECTED, fall through and reconcile as MANUAL_EXIT_APPROX using
    # current LTP as the exit price -- NOT the real fill price (we have no way to know
    # that once the order book no longer shows it), so PnL here is an ESTIMATE. Flagged
    # clearly via reason string + Telegram message so it's never confused with a
    # broker-confirmed fill.
    if EXECUTION_BROKER == "mstock_live" and POS.buy_order_id and reason != 'MANUAL_EXIT':
        broker = _get_mstock()
        if not broker:
            lwarn("[mstock] Broker unavailable on SELL — position still OPEN on exchange!")
            TG.send(f"🚨 CRITICAL: mStock broker unavailable on SELL for {POS.symbol}. "
                    f"Position still open on exchange! MANUAL ACTION REQUIRED.")
            return  # keep POS.active=True so next loop retries exit
        ms_sym = POS.ms_symbol or _mstock_option_symbol(POS.symbol)
        qty = lots_for(POS.engine) * LOT_SIZE
        sell_filled = False
        sell_rejected = False
        for attempt in range(1, 4):
            oid = broker.place_order("SELL", ms_sym, qty, "MARKET")
            if oid:
                # Record immediately (before wait_for_fill) so find_manual_sell()
                # never misattributes THIS bot-driven SELL as a manual exit, even
                # if the process crashes before the fill confirmation below.
                POS.own_sell_order_ids.append(oid)
                save_state()
                status, fill = broker.wait_for_fill(oid, timeout_sec=15)
                if status == "COMPLETE" and fill and fill > 0:
                    # V2.5.20 (2026-07-11 fix): same order-book/RMS race as the BUY-side fix
                    # (see MStockBroker.verify_position()) -- confirm the position actually
                    # closed in the broker's real position book before trusting it.
                    if broker.verify_closed(ms_sym):
                        exit_price = fill
                        linfo(f"[mstock] SELL filled: {ms_sym} qty={qty} fill={fill:.2f} order={oid}")
                        sell_filled = True
                        break
                    else:
                        lwarn(f"[mstock] SELL reported COMPLETE (fill={fill:.2f}, order={oid}) but "
                              f"position STILL SHOWS OPEN in broker's book — treating as unconfirmed "
                              f"(order-book/RMS race), retrying rather than trusting it.")
                        # fall through to attempt<3 retry below; do NOT set sell_filled
                if status == "REJECTED":
                    lwarn(f"[mstock] SELL REJECTED for {ms_sym} (order {oid}) — no real holding to "
                          f"sell. Position was almost certainly already closed elsewhere (manual "
                          f"exit or broker EOD square-off). Reconciling instead of blind-retrying.")
                    sell_rejected = True
                    break
                lwarn(f"[mstock] SELL attempt {attempt}/3: status={status}. Retrying in 5s...")
            else:
                # place_order returned None -- inspect the real RMS reason (was invisible
                # for 10 days: only "returned None" was logged, never the actual error).
                _err = getattr(broker, '_last_error', '') or 'no orderid returned'
                if _is_margin_reject(_err):
                    # RMS priced our square-off as a fresh naked short => it sees no long.
                    # Confirm against the authoritative position book before concluding the
                    # position was closed outside the bot (manual exit). verify_closed polls
                    # net_qty a few times so a transient book read can't false-trigger this.
                    if broker.verify_closed(ms_sym):
                        lwarn(f"[mstock] SELL rejected on margin (RMS: {_err}) AND broker net "
                              f"position for {ms_sym} is flat — position was already closed "
                              f"outside the bot (manual exit). Reconciling instead of retrying.")
                        sell_rejected = True
                        break
                    # net_qty still shows a real long => genuine funding block, NOT a manual
                    # exit. Fall through to keep retrying (handled in the elif below).
                    lwarn(f"[mstock] SELL attempt {attempt}/3: MARGIN REJECT but position still "
                          f"OPEN in book. RMS: {_err}. Retrying in 5s...")
                else:
                    lwarn(f"[mstock] SELL attempt {attempt}/3: place_order returned None. "
                          f"RMS: {_err}. Retrying in 5s...")
            if attempt < 3:
                time.sleep(5)
        if sell_rejected:
            # Prefer your REAL manual-sell fill from the order book; fall back to LTP only if
            # it isn't found there (e.g. you exited INTRADAY, which find_manual_sell skips).
            exclude_ids = [POS.buy_order_id] + list(POS.own_sell_order_ids)
            manual = broker.find_manual_sell(ms_sym, exclude_ids)
            if manual:
                m_oid, m_fill, m_qty = manual
                lwarn(f"[mstock] Reconciled {ms_sym} to your manual SELL order {m_oid} "
                      f"@ ₹{m_fill:.2f} (qty={m_qty}).")
                TG.send(f"✅ <b>{ms_sym} — detected your manual exit @ ₹{m_fill:.2f}.</b>\n"
                        f"The bot's own square-off was rejected because the position was already "
                        f"closed; reconciled to your real fill.")
                reason = 'MANUAL_EXIT'
                exit_price = m_fill
            else:
                approx_price = ltp(POS.symbol) or POS.entry_premium
                lwarn(f"[mstock] Reconciling {ms_sym} as MANUAL_EXIT_APPROX using LTP≈₹{approx_price:.2f} "
                      f"(position confirmed flat at broker, but no manual SELL visible in the order "
                      f"book to read the real fill price from).")
                TG.send(f"⚠️ <b>{ms_sym} — closed outside the bot, real fill not in order book.</b>\n"
                        f"Reconciling with APPROX exit ₹{approx_price:.2f} (current LTP, not the real "
                        f"fill — actual PnL may differ slightly).")
                reason = 'MANUAL_EXIT_APPROX'
                exit_price = approx_price
        elif not sell_filled:
            # Genuine funding block: position IS still open at the broker but RMS won't let us
            # square it off (net>0 confirmed above). Retrying every cycle is correct (funds may
            # free up) but the CRITICAL alert is throttled to once/min so it can't spam.
            _err = getattr(broker, '_last_error', '') or 'unknown'
            lwarn(f"[mstock] SELL FAILED after 3 attempts — position still OPEN on exchange! "
                  f"({ms_sym}) RMS: {_err}")
            now_ts = time.time()
            if now_ts - _last_funding_alert_ts >= 60:
                _last_funding_alert_ts = now_ts
                TG.send(f"🚨 CRITICAL: mStock SELL for {ms_sym} REJECTED — position still OPEN "
                        f"on exchange. MANUAL SQUARE-OFF REQUIRED.\nRMS: {_err}")
            return  # keep POS.active=True — main loop will keep trying to exit

    pnl_per_share = exit_price - POS.entry_premium
    is_flip = (POS.engine == 'FLIP')
    msg = fmt_exit(reason, exit_price, pnl_per_share)
    DAY.trades_today.append({
        'symbol': POS.symbol, 'side': POS.side, 'engine': POS.engine,
        'entry': POS.entry_premium, 'exit': exit_price, 'pnl': pnl_per_share,
        'reason': reason, 'elapsed_min': POS.elapsed_min(),
        'entry_time': POS.entry_time.strftime("%H:%M:%S") if POS.entry_time else "",
    })
    # NON-FLIP, NON-MANUAL losses count toward circuit breaker.
    # MANUAL_EXIT(_APPROX) = user closed on broker — not a signal failure, excluded from CB.
    is_manual = reason in ('MANUAL_EXIT', 'MANUAL_EXIT_APPROX')
    if is_manual:
        # Set 5-min cooldown before bot re-enters after a manual close
        DAY.manual_exit_cooldown_until = datetime.now(IST) + timedelta(minutes=5)
        linfo(f"[MANUAL_EXIT] CB not incremented (user-initiated). Cooldown until {DAY.manual_exit_cooldown_until.strftime('%H:%M:%S')} IST")
    if pnl_per_share < 0 and not is_flip and not is_manual:
        global TOTAL_LOSSES_TODAY, GLOBAL_HALTED
        DAY.losses += 1
        if POS.engine == 'V2':
            DAY.v2_losses_today += 1
        if POS.engine == 'VWAP':
            DAY.vwap_last_loss_side = POS.side
            DAY.vwap_last_loss_at = datetime.now(IST)
        TOTAL_LOSSES_TODAY += 1
        linfo(f"[CB] {POS.engine} loss (own count {DAY.losses}) — "
              f"TOTAL across all engines={TOTAL_LOSSES_TODAY}/{CIRCUIT_BREAKER} (reason={reason})")
        if TOTAL_LOSSES_TODAY >= CIRCUIT_BREAKER and not GLOBAL_HALTED:
            GLOBAL_HALTED = True
            for _name in ENGINE_LIST:
                DAY_STATES[_name].halted = True
            if EXECUTION_BROKER == "mstock_live":
                TG.send(f"⛔⛔⛔ <b>HALT — Circuit Breaker (LIVE HALTED)</b> ⛔⛔⛔\n"
                        f"{TOTAL_LOSSES_TODAY} bot-driven losses across ALL engines combined.\n"
                        f"<b>All {len(ENGINE_LIST)} engines' new entries STOPPED for the rest of today.</b>\n"
                        f"Open positions (if any) will still be managed to exit normally.")
                linfo(f"[CB] GLOBAL circuit breaker hit ({TOTAL_LOSSES_TODAY} total losses) — halting all engines' new entries")
            else:
                TG.send(f"⚠️ <b>Circuit Breaker reached ({TOTAL_LOSSES_TODAY} total losses across all engines)</b>\n"
                        f"PAPER mode — NOT halted, paper trading continues for full-day visibility.")
    # V2.5.2: record last_exit info for flip detection (Path A check immediately, Path B over time)
    DAY.last_exit = {
        'side': POS.side,
        'entry': POS.entry_premium,
        'peak': POS.peak_premium,
        'elapsed_min': POS.elapsed_min(),
        'exit_time': datetime.now(IST),
        'exit_price': exit_price,
        'engine': POS.engine,
    }
    # Same-direction re-entry cooldown source (NOT cleared by the flip mechanism)
    DAY.last_exit_side = POS.side
    DAY.last_exit_at = datetime.now(IST)

    record_trade(reason, exit_price, pnl_per_share, exit_spot=LAST_SPOT)
    linfo(f"EXIT: {POS.symbol} @ {exit_price:.2f} reason={reason} pnl/sh={pnl_per_share:+.2f}"
          f" is_flip={is_flip} losses={DAY.losses}/{CIRCUIT_BREAKER}")
    TG.send(msg)
    # Reset
    POS.active = False
    POS.engine = ""; POS.engine_detail = ""
    POS.side = ""; POS.strike = 0; POS.symbol = ""; POS.token = 0
    POS.ms_symbol = ""; POS.buy_order_id = ""; POS.own_sell_order_ids = []
    POS.is_paper = False; POS.unconfirmed_fill = False
    POS.entry_time = None
    POS.entry_premium = 0.0; POS.peak_premium = 0.0
    POS.hardsl_premium = 0.0; POS.sl_current = 0.0
    POS.tr_armed = False; POS.tr_sl = 0.0
    POS.declared_target_premium = 0.0; POS.declared_target_spot = None
    POS.entry_vwap = None
    save_state()

def _apply_entry_gates_and_open(sig, spot, expiry_lookup, paper_only,
                                 strike_override=None, symbol_override=None,
                                 token_override=None, premium_override=None):
    """V2.5.19: shared momentum/fade-gate + open path used by BOTH the normal
    engine chain and the Feature-3 morning exception. Returns True if a trade opened.
    V2.5.20-fix: optional overrides let a filled V3 probe (_manage_v3_probe) open
    at its exact limit fill price instead of re-fetching a fresh market LTP."""
    if sig is None:
        return False
    # Same-direction re-entry cooldown: block a near-immediate same-side re-entry right
    # after an exit on that side (the momentum/fade gates only arm on the 3rd+ same-side
    # entry, so they let this through — see 2026-06-23 PE+42 -> PE HARDSL 33s later).
    if SAME_DIR_REENTRY_GUARD and DAY.last_exit_at is not None and \
       sig['side'] == DAY.last_exit_side:
        _cd_age = (datetime.now(IST) - DAY.last_exit_at).total_seconds() / 60.0
        if _cd_age < SAME_DIR_REENTRY_COOLDOWN_MIN:
            linfo(f"[REENTRY_CD] BLOCKED {sig['engine']} {sig['side']} — same-side re-entry "
                  f"{_cd_age:.1f}min after last {DAY.last_exit_side} exit "
                  f"(cooldown {SAME_DIR_REENTRY_COOLDOWN_MIN}min)")
            TG.send(f"🚧 <b>Same-direction cooldown BLOCK</b> · {sig['side']} ({sig['engine']})\n"
                    f"   Only {_cd_age:.1f}min since last {DAY.last_exit_side} exit "
                    f"(min {SAME_DIR_REENTRY_COOLDOWN_MIN}min)\n"
                    f"   Avoids immediate same-side re-entry after an exit (2026-06-23)")
            return False
    _mg_ok, _mg_info = momentum_gate_ok(sig['side'], sig['engine'])
    _fg_ok, _fg_info = (fade_gate_ok(sig, spot, expiry_lookup) if _mg_ok else (True, ""))
    if not _mg_ok:
        linfo(f"[MOMGATE] BLOCKED {sig['engine']} {sig['side']} {_mg_info} "
              f"— 3rd+ same-direction entry without momentum")
        TG.send(f"🚧 <b>Momentum-gate BLOCK</b> · {sig['side']} ({sig['engine']})\n"
                f"   3rd+ same-direction entry · momentum {_mg_info}\n"
                f"   Skipped to avoid choppy same-side re-entry (V2.5.16)")
        return False
    if not _fg_ok:
        linfo(f"[FADEGATE] BLOCKED {sig['engine']} {sig['side']} {_fg_info} "
              f"— momentum fading after same-side wins")
        TG.send(f"🚧 <b>Momentum-fade BLOCK</b> · {sig['side']} ({sig['engine']})\n"
                f"   After same-side wins, 3m option momentum faded · {_fg_info}\n"
                f"   Trend not holding / opposite not decaying (V2.5.17)")
        return False
    open_trade(sig, spot, expiry_lookup, paper_only=paper_only,
               strike_override=strike_override, symbol_override=symbol_override,
               token_override=token_override, premium_override=premium_override)
    return True


def _place_v3_probe(sig, spot, expiry_lookup):
    """V2.5.20-fix (2026-07-12 probe/re-entry test): instead of buying V3 at
    market on signal, place an anticipatory LIMIT buy at (signal LTP -
    V3_PROBE_PULLBACK_PTS). Real 38-day option-premium test: filled-only
    +1.67pt avg / 52.6% win, all grades combined (see
    ~/orion_analysis/v3_level_diagnosis/OPTION_PROBE_REENTRY_RESULTS.md).
    Applies to Grade A and B alike -- explicit user instruction 2026-07-12,
    no grade restriction. Marks the level fired immediately (same-day dedup),
    matching the validated test's fired_probe convention, regardless of
    whether the probe ultimately fills."""
    side = sig['side']
    strike = round_to_atm(spot)
    key = (strike, side)
    if key not in expiry_lookup:
        lwarn(f"[V3PROBE] Strike {strike} {side} not in expiry lookup; skipping probe")
        return False
    symbol, token = expiry_lookup[key]
    signal_ltp = ltp(symbol)
    if signal_ltp is None or signal_ltp <= 0:
        lwarn(f"[V3PROBE] Cannot fetch LTP for {symbol}; skipping probe")
        return False
    prem_max = PREMIUM_MAX_PE if side == 'PE' else PREMIUM_MAX_CE
    if not (PREMIUM_MIN <= signal_ltp <= prem_max):
        lwarn(f"[V3PROBE] Premium {signal_ltp:.2f} outside gate [{PREMIUM_MIN},{prem_max}] ({side}); skipping probe")
        return False
    limit_price = signal_ltp - V3_PROBE_PULLBACK_PTS
    if limit_price <= 0:
        return False
    if sig.get('level_obj') is not None:
        DAY.fired_levels.add(sig['level_obj']['center'])
    DAY.v3_probe = {
        'sig': sig, 'side': side, 'strike': strike, 'symbol': symbol, 'token': token,
        'signal_ltp': signal_ltp, 'limit_price': limit_price,
        'placed_at': datetime.now(IST),
        'deadline': datetime.now(IST) + timedelta(minutes=V3_PROBE_FILL_WINDOW_MIN),
    }
    linfo(f"[V3PROBE] PLACED {side} {symbol} limit={limit_price:.2f} "
          f"(LTP={signal_ltp:.2f} - {V3_PROBE_PULLBACK_PTS:.0f}) "
          f"window={V3_PROBE_FILL_WINDOW_MIN}min — {sig['detail']}")
    TG.send(f"🎯 <b>V3 PROBE placed</b> · {side} {symbol}\n"
            f"   Limit {limit_price:.2f} (LTP {signal_ltp:.2f} − {V3_PROBE_PULLBACK_PTS:.0f} pts)\n"
            f"   {tg_escape(sig['detail'])}\n"
            f"   Fills within {V3_PROBE_FILL_WINDOW_MIN}min or cancels (V2.5.20 probe-entry)")
    return True


def _manage_v3_probe(now, spot, expiry_lookup, paper_only):
    """Poll a pending V3 probe every loop tick: fill on LTP touch, else expire
    at the window deadline. Live LTP polling (LOOP_SLEEP_SEC apart) substitutes
    for the offline test's 5m-bar-low touch check -- comparable precision since
    the fill window is 15min / ~30 ticks."""
    probe = DAY.v3_probe
    if probe is None:
        return
    if now >= probe['deadline']:
        linfo(f"[V3PROBE] EXPIRED unfilled {probe['side']} {probe['symbol']} limit={probe['limit_price']:.2f}")
        TG.send(f"⌛ <b>V3 probe expired unfilled</b> · {probe['side']} {probe['symbol']}\n"
                f"   Limit {probe['limit_price']:.2f} never touched in {V3_PROBE_FILL_WINDOW_MIN}min")
        DAY.v3_probe = None
        return
    cur_ltp = ltp(probe['symbol'])
    if cur_ltp is None or cur_ltp <= 0:
        return
    if cur_ltp <= probe['limit_price']:
        linfo(f"[V3PROBE] FILLED {probe['side']} {probe['symbol']} @ {probe['limit_price']:.2f} "
              f"(LTP touched {cur_ltp:.2f})")
        sig = probe['sig']
        DAY.v3_probe = None
        _apply_entry_gates_and_open(sig, spot, expiry_lookup, paper_only,
                                     strike_override=probe['strike'], symbol_override=probe['symbol'],
                                     token_override=probe['token'], premium_override=probe['limit_price'])


def in_morning_vwap_window(now):
    """V2.5.19 FEATURE 3: True inside the 09:15-10:15 morning exception window."""
    start = now.replace(hour=MORNING_WIN_START_H, minute=MORNING_WIN_START_M,
                        second=0, microsecond=0)
    end   = now.replace(hour=MORNING_WIN_END_H, minute=MORNING_WIN_END_M,
                        second=0, microsecond=0)
    return start <= now <= end


# =========================================================================
# V2.5.20 TOUCH-STOP/LOCK/RIDE EXIT MANAGER  (ORB, GAPBREAK, FUT5VWAP)
# =========================================================================
def _touch_flip_reentry(engine, flip_side, flip_strike, spot, expiry_lookup):
    """One same-strike opposite-side flip on ORB/GAPBREAK stop (ported from
    manage_touch()'s flip_cb in orion_concurrent_engine.py). Never called for
    FUT5VWAP -- that engine opens with DAY.is_flip=True, which the caller's
    allow_flip logic already respects (backtest: FUT5VWAP's flip_cb is a no-op
    and its flip_cutoff_t is dt.time(0,0), i.e. never)."""
    # V2.5.20 2026-07-12: ORB chop-kill also blocks the flip-on-stop re-entry
    # (the kill was validated against ALL post-kill ORB entries incl. flips).
    if engine == 'ORB' and getattr(DAY, 'orb_chop_killed', False):
        linfo("[ORB] Flip re-entry blocked — chop-kill active for the day")
        return
    key = (flip_strike, flip_side)
    if key not in expiry_lookup:
        return
    symbol, token = expiry_lookup[key]
    prem = ltp(symbol)
    pmin, pmax = (ORB_FLIP_PREM_MIN, ORB_PREM_MAX) if engine == 'ORB' else (GAP_PREM_MIN, GAP_PREM_MAX)
    if prem is None or prem <= 0 or not (pmin <= prem <= pmax):
        return
    sig = {'engine': engine, 'side': flip_side, 'detail': f'{engine} flip-on-stop',
           'trigger': 0.0, 'level_obj': None, 'target_spot': None,
           'kind': f'FLIP_{flip_side}', 'is_flip': True}
    open_trade(sig, spot, expiry_lookup, strike_override=flip_strike,
               symbol_override=symbol, token_override=token, premium_override=prem)


def _manage_touch_exit(cur_ltp, now, spot, expiry_lookup, stop_pts, lock_pts,
                        ride_trigger, ride_giveback, sqoff_h, sqoff_m,
                        flip_cutoff_h, flip_cutoff_m, allow_flip):
    """Shared touch-stop/lock-floor/ride exit manager for ORB/GAPBREAK/FUT5VWAP
    (V2.5.20), ported from manage_touch() in orion_concurrent_engine.py.

    LIVE FIDELITY NOTE: the backtest checks stop/lock/ride against each 5m
    bar's actual intrabar LOW and HIGH (so a touch-and-recover within one bar
    is caught exactly). Live, only LTP is available once per loop iteration
    (LOOP_SLEEP_SEC apart) -- LTP polled every tick substitutes for bar
    low/high here. This means a stop or lock level that is briefly touched
    and recovers BETWEEN two polls can be missed; precision is coarser than
    the backtest's 5m-bar-low/high precision, especially in fast moves.
    Also, arming the lock floor and breaching it in the "same bar" (the
    backtest's same-tick arm+check-breach collapse) can't happen live since a
    single LTP reading can't be both a high and a subsequent low -- arming
    and breach-checking are naturally split across separate ticks live.

    Returns True if the position was closed this call."""
    ep = POS.entry_premium
    engine = POS.engine

    # 1. STOP
    if DAY.floor is None and cur_ltp <= ep - stop_pts:
        exit_price = ep - stop_pts
        do_flip = allow_flip and (not DAY.is_flip) and \
                  (now.hour < flip_cutoff_h or (now.hour == flip_cutoff_h and now.minute <= flip_cutoff_m))
        flip_side = 'PE' if POS.side == 'CE' else 'CE'
        flip_strike = POS.strike
        close_trade(f"{engine}_STOP", exit_price)
        if do_flip:
            _touch_flip_reentry(engine, flip_side, flip_strike, spot, expiry_lookup)
        return True

    # 2. LOCK — arm the floor once premium reaches entry+lock_pts
    if DAY.floor is None:
        if cur_ltp >= ep + lock_pts:
            DAY.floor = lock_pts
    else:
        # 3. RIDE — once peak clears ride_trigger, floor trails at peak-giveback
        if (POS.peak_premium - ep) >= ride_trigger:
            DAY.floor = max(DAY.floor, POS.peak_premium - ep - ride_giveback)
        if cur_ltp <= ep + DAY.floor:
            close_trade(f"{engine}_LOCK_FLOOR", ep + DAY.floor)
            return True

    # 4. Square-off
    if now.hour > sqoff_h or (now.hour == sqoff_h and now.minute >= sqoff_m):
        close_trade(f"{engine}_SQUARE_OFF", cur_ltp)
        return True
    return False


def _manage_expiry_trail(cur_ltp, now):
    """EXPIRY exit (V2.5.20 NEW, 2026-07-26): velvet-rope/ladder on MULTIPLES
    of entry premium -- entries are cheap OTM (Rs5-100), so the shared
    BASE/V2/VWAP continuous trail (absolute points: arm at entry+15) would
    rarely even arm. Deliberately does NOT use the shared step-3/step-4
    blocks in check_exits (per user instruction 2026-07-26: no SMA8(low)
    trail on this engine) -- HARDSL_PCT (checked by the caller before this
    is reached, already %-based so left as-is) + this ladder are the only
    exits, plus a 15:15 square-off (tighter than the generic 15:25, matching
    ORB/GAPBREAK -- don't hold an expiry-gamma position into the last 10min).

    Ladder (peak-based, ratchets up only, mirrors POS.tr_armed/tr_sl so the
    existing Telegram "TRAIL ARMED" display works unchanged):
      peak >= entry*1.5 -> SL = entry*1.0   (velvet rope: lock breakeven)
      peak >= entry*2.0 -> SL = entry*1.5   (locked a double reached +50%)
      peak >= entry*3.0 -> SL = entry*2.0   (bank the double once tripled)
      beyond that: SL = peak*0.70, continuous trail, lets the fat-tail
      winners (the study saw up to 7.5x) keep running instead of capping."""
    if now.hour > EXPIRY_SQOFF_H or (now.hour == EXPIRY_SQOFF_H and now.minute >= EXPIRY_SQOFF_M):
        close_trade("EXPIRY_SQUARE_OFF", cur_ltp)
        return True

    ep, pk = POS.entry_premium, POS.peak_premium
    mult_pk = pk / ep if ep else 0.0
    floor = None
    if mult_pk >= EXPIRY_VELVET_T3_MULT:
        floor = max(ep * (EXPIRY_VELVET_T3_MULT - 1.0), pk * (1.0 - EXPIRY_VELVET_RIDE_GIVEBACK))
    elif mult_pk >= EXPIRY_VELVET_T2_MULT:
        floor = ep * (EXPIRY_VELVET_T2_MULT - 0.5)
    elif EXPIRY_VELVET_ARM_LOCK and mult_pk >= EXPIRY_VELVET_ARM_MULT:
        floor = ep * 1.0   # 2026-09-11: off by default, see EXPIRY_VELVET_ARM_LOCK

    if floor is not None:
        if not POS.tr_armed:
            POS.tr_armed = True
            TG.send(f"🎯 <b>EXPIRY velvet-rope ARMED</b> · {POS.side}\n"
                    f"   Peak {pk:.2f} ({mult_pk:.2f}x entry) → SL locked at <code>{floor:.2f}</code>")
        if floor > POS.tr_sl:
            POS.tr_sl = floor
            save_state()
        if cur_ltp <= POS.tr_sl:
            close_trade(f"EXPIRY_VELVET_{mult_pk:.1f}x", POS.tr_sl)
            return True
    return False


# =========================================================================
# EXIT CHECKS  (called every loop iteration when POS.active)
# =========================================================================
# =========================================================================
# 2026-09-28 BREAKWATCH — 5-minute participant check on every open trade
# (NIFTY bot: ACTS, exits when score <= BREAKWATCH_CUT_MAX; SENSEX bot: LOG ONLY).
# Scorer = ~/Amol/breakwatch_live.py (shared, pure logic; offline-verified to
# reproduce the study score on all 186 live trades 09-01..09-28). Five minutes
# after the entry minute t0 it scores 6 footprints: heavyweight basket / breadth
# / top-4 agreement, the other index, own-index progress, and OI added by sellers
# at the first OTM strike on the trade's side. Evidence + revert in CHANGE_HISTORY.
# A data source returning nothing -> retried for BREAKWATCH_WINDOW_S, then NO action (never cuts blind).
# =========================================================================
BREAKWATCH_ENABLED  = True
BREAKWATCH_ACT      = False    # LOG ONLY on SENSEX (user 2026-09-28)
BREAKWATCH_CUT_MAX  = 1
BREAKWATCH_PROFIT_GUARD = True   # 2026-09-28: no cut while LTP > entry (see _breakwatch_check)
BREAKWATCH_INDEX    = "SENSEX"
BREAKWATCH_ENGINES  = ("VWAP", "ORB", "GAPBREAK", "V2", "V3", "FLIP")
# 2026-09-28 (same evening, user): NOT applied to FAST / FUT5VWAP / STOCH.
# FAST = 1m option-momentum scalp with its own 15-pt trail (never cut in the study);
# STOCH = deliberate counter-trend scalp, scores low by construction; FUT5VWAP = user call.
BREAKWATCH_WINDOW_S = 180
BREAKWATCH_LOG      = os.path.join(_SCRIPT_DIR, "breakwatch", "live_log.jsonl")
_BW_DONE  = set()
_BW_CACHE = {}

def _breakwatch_check(now, expiry_lookup):
    """Evaluate the open POS once, 5 min after its entry minute. Returns the score
    dict only when the position must be CUT (BREAKWATCH_ACT and score <= CUT_MAX)."""
    if not BREAKWATCH_ENABLED or POS.engine not in BREAKWATCH_ENGINES or POS.entry_time is None:
        return None
    et = POS.entry_time
    if et.tzinfo is None:
        et = IST.localize(et) if hasattr(IST, "localize") else et.replace(tzinfo=IST)
    et = et.astimezone(IST)
    key = (POS.symbol, et.isoformat())
    if key in _BW_DONE:
        return None
    due = et.replace(second=0, microsecond=0) + timedelta(minutes=5, seconds=15)
    if now < due:
        return None
    last = now >= due + timedelta(seconds=BREAKWATCH_WINDOW_S)
    t0 = et.hour * 60 + et.minute
    try:
        import breakwatch_live as _BW
        frm = now.replace(hour=9, minute=0, second=0, microsecond=0)
        stamp = now.strftime("%H%M")
        def gb(k, oi):
            ck = (k, oi)
            if ck not in _BW_CACHE or _BW_CACHE[ck][0] != stamp:
                rows = kite_safe(kite.historical_data, k, frm, now, "minute", oi=oi, retries=1) or []
                _BW_CACHE[ck] = (stamp, _BW.bars_from_rows(rows, now.date()))
            return _BW_CACHE[ck][1]
        def okey(strike, sd):
            if not expiry_lookup:
                return None
            v = expiry_lookup.get((float(strike), sd)) or expiry_lookup.get((int(strike), sd))
            return v[1] if v else None
        res = _BW.score_trade(BREAKWATCH_INDEX, POS.side, t0, gb, okey)
    except LookupError as e:
        if last:
            _BW_DONE.add(key)
            lwarn(f"[BREAKWATCH] {POS.engine} {POS.symbol} window missed, no action: {e}")
        return None
    except Exception as e:
        _BW_DONE.add(key)
        lwarn(f"[BREAKWATCH] {POS.engine} {POS.symbol} error, no action: {e}")
        return None
    if res["fetch_fail"] and not last:
        return None   # a data source returned nothing -> retry next tick
    _BW_DONE.add(key)
    # features that are None because their window starts before 09:15 count as
    # not-genuine, exactly as in the study; an API failure (fetch_fail) never cuts.
    cut = (not res["fetch_fail"]) and res["score"] <= BREAKWATCH_CUT_MAX
    # 2026-09-28 PROFIT GUARD: never cut a trade that is green at the check (LTP > entry).
    # Study (EXITCUT_REPORT, live engine set): only 2 cuts were green at +5 min
    # (09-09 V2 cut cost -514, 09-16 FLIP cut gained +114) -> guard net about +400.
    _bw_ltp = POS.last_pulse_premium
    green = bool(BREAKWATCH_PROFIT_GUARD and cut and _bw_ltp and POS.entry_premium
                 and float(_bw_ltp) > float(POS.entry_premium))
    if green:
        cut = False
    act = cut and BREAKWATCH_ACT
    verdict = "CUT" if act else ("WOULD_CUT(log-only)" if cut else
               ("KEEP(green, profit guard)" if green else ("KEEP" if not res["fetch_fail"] else "NO_ACTION(data fetch failed)")))
    linfo(f"[BREAKWATCH] {POS.engine} {POS.side} {POS.symbol} entry {et:%H:%M} "
          f"score {res['score']}/{res['n']} -> {verdict} | {res['feats']} missing={res['missing']} fetch_fail={res['fetch_fail']}")
    try:
        os.makedirs(os.path.dirname(BREAKWATCH_LOG), exist_ok=True)
        with open(BREAKWATCH_LOG, "a") as fh:
            fh.write(json.dumps({"ts": now.isoformat(), "index": BREAKWATCH_INDEX, "engine": POS.engine,
                                 "side": POS.side, "symbol": POS.symbol, "entry": et.isoformat(),
                                 "entry_premium": POS.entry_premium, "ltp": POS.last_pulse_premium,
                                 "score": res["score"], "verdict": verdict, "feats": res["feats"],
                                 "missing": res["missing"], "fetch_fail": res["fetch_fail"]}) + "\n")
    except Exception as e:
        lwarn(f"[BREAKWATCH] log write failed: {e}")
    return res if act else None


def check_exits(spot, expiry_lookup=None):
    """Check all exit conditions in priority order. Returns True if closed."""
    global LAST_SPOT
    if spot: LAST_SPOT = spot
    if not POS.active: return False
    cur_ltp = ltp(POS.symbol)
    if cur_ltp is None or cur_ltp <= 0:
        return False
    POS.last_pulse_premium = cur_ltp
    POS.update_peak(cur_ltp)
    # 2026-08-29: MAE tracker. Without it we cannot tell a stop that cut a
    # genuine loser from one that ejected a trade which then recovered.
    if POS.trough_premium <= 0 or cur_ltp < POS.trough_premium:
        POS.trough_premium = cur_ltp

    now = datetime.now(IST)

    # V2.5.2 PATH A: in-trade flip detection
    # Conditions: elapsed >= 30, peak >= entry+15, current <= entry+10, AND 15m K reversed
    # If met, force-close with FLIP_TO_X reason. Main loop will catch K-reversal via
    # check_flip_signal in the next iteration and open opposite-side flip.
    # 2026-08-13 fix: this compared POS.engine to the literal string 'BASE',
    # but open_trade() always sets POS.engine to the specific sub-engine that
    # fired (V2/FLIP/V3) -- 'BASE' is only the SLOT name used by switch_engine().
    # That made Path A dead code since the V2.5.20 multi-engine refactor: it
    # could never fire for any real position. Path A belongs to the BASE slot
    # (the only slot check_flip_signal's re-entry applies to), so check
    # membership in that slot's engines instead of an impossible exact match.
    if POS.engine in ('V2', 'FLIP', 'V3') and FLIP_ENABLED and is_path_a_eligible() and DAY.flips_today < MAX_FLIPS_PER_DAY:
        # Check K reversal via cached values in DAY (most recent 15m K vs prior K)
        # Note: actual K check happens in main loop; here we just need the K direction
        # to be opposite the position's direction expectation
        K_now    = DAY.last_K_seen
        K_prev   = DAY.last_K_prev_seen
        k_reversed = False
        if K_now is not None and K_prev is not None:
            if POS.side == 'CE' and K_now < K_prev and FLIP_K_CE_TO_PE_MIN <= K_now <= FLIP_K_CE_TO_PE_MAX:
                # 2026-07-13: this Path-A branch force-closes the CE *in order to*
                # flip into a PE. check_flip_signal now refuses low-quality put
                # flips, so without the same gate here we would close a live CE for
                # a flip that never arrives. Gate both, or gate neither.
                k_reversed = put_flip_ok(K_now, K_prev)[0]
            elif POS.side == 'PE' and K_now > K_prev and K_now >= FLIP_K_PE_TO_CE_MIN:
                k_reversed = True
        if k_reversed:
            new_side = 'PE' if POS.side == 'CE' else 'CE'
            close_trade(f"FLIP_TO_{new_side}_PathA", cur_ltp)
            return True

    # 1. Force close 15:25
    if now.hour > FORCE_CLOSE_HOUR or (now.hour == FORCE_CLOSE_HOUR and now.minute >= FORCE_CLOSE_MIN):
        close_trade("FORCE_CLOSE_15_25", cur_ltp)
        return True

    # 2. HARDSL
    if cur_ltp <= POS.hardsl_premium:
        _hsl_reason = f"V2_HARDSL_-{int(V2_HARDSL_PTS)}pt" if POS.engine == 'V2' \
                      else f"HARDSL_-{int(HARDSL_PCT*100)}pct"
        close_trade(_hsl_reason, POS.hardsl_premium)
        return True

    # 2b-pre. 2026-09-28 BREAKWATCH: once, 5 min after entry (see _breakwatch_check).
    # NIFTY acts (score <= BREAKWATCH_CUT_MAX -> exit now); SENSEX only logs.
    _bw = _breakwatch_check(now, expiry_lookup)
    if _bw is not None:
        close_trade(f"BREAKWATCH_CUT_s{_bw['score']}", cur_ltp)
        return True

    elapsed = POS.elapsed_min()

    # 2a. V2.5.20-fix (2026-07-12): V3 fast target/stop (option-premium points).
    # Diagnosis found V3 held-to-close was net negative on every entry style
    # tested; a fast +10/-8pt target/stop flipped it to net positive on real
    # 5m/28-day data. FORCE_CLOSE (1) and HARDSL (2) above still apply as
    # safety nets exactly like the other fixed-exit engines (ORB/GAPBREAK).
    if POS.engine == 'V3' and V3_FAST_EXIT_ENABLED:
        ep = POS.entry_premium
        if cur_ltp >= ep + V3_FAST_TARGET_PTS:
            close_trade("V3_FAST_TARGET", ep + V3_FAST_TARGET_PTS)
            return True
        if cur_ltp <= ep - V3_FAST_STOP_PTS:
            close_trade("V3_FAST_STOP", ep - V3_FAST_STOP_PTS)
            return True

    # 2b. V2.5.20: ORB/GAPBREAK/FUT5VWAP all use the touch-stop/lock/ride manager
    # (FUT5VWAP: validated exit fix, replaces the old fixed +12 target/no-trail --
    # see FUT5_FIX_STOP_PTS/FUT5_FIX_LOCK_PTS and orion-6engine-combined-result).
    # HARDSL (above, disabled for these 3 via hardsl_premium=-1e9) and the generic
    # 15:25 force-close (above) still apply as a safety net; each engine also has
    # its OWN square-off inside _manage_touch_exit (ORB/GAP 15:15, FUT5VWAP 15:25).
    if POS.engine == 'ORB':
        return _manage_touch_exit(cur_ltp, now, spot, expiry_lookup,
                                   ORB_STOP_PTS, ORB_LOCK_PTS,
                                   ORB_RIDE_TRIGGER_PTS, ORB_RIDE_GIVEBACK_PTS,
                                   ORB_SQOFF_H, ORB_SQOFF_M,
                                   ORB_FLIP_CUTOFF_H, ORB_FLIP_CUTOFF_M,
                                   allow_flip=True)
    if POS.engine == 'GAPBREAK':
        return _manage_touch_exit(cur_ltp, now, spot, expiry_lookup,
                                   GAP_STOP_PTS, GAP_LOCK_PTS,
                                   GAP_RIDE_TRIGGER_PTS, GAP_RIDE_GIVEBACK_PTS,
                                   GAP_SQOFF_H, GAP_SQOFF_M,
                                   GAP_FLIP_CUTOFF_H, GAP_FLIP_CUTOFF_M,
                                   allow_flip=True)
    if POS.engine == 'FUT5VWAP':
        return _manage_touch_exit(cur_ltp, now, spot, expiry_lookup,
                                   FUT5_FIX_STOP_PTS, FUT5_FIX_LOCK_PTS,
                                   FUT5_RIDE_TRIGGER_PTS, FUT5_RIDE_GIVEBACK_PTS,
                                   FUT5_SQOFF_H, FUT5_SQOFF_M,
                                   0, 0, allow_flip=False)
    if POS.engine == 'EXPIRY':
        # V2.5.20 (2026-07-26, explicit user instruction): own velvet-rope
        # ladder, bypasses steps 3/4 below entirely -- no shared point-based
        # continuous trail, no SMA8(low)/VWAP 15m trail on this engine.
        return _manage_expiry_trail(cur_ltp, now)

    # 3. TRAIL AFTER TP TRIGGER
    # Phase 1 (below entry+15): only HARDSL protects, let position breathe
    # Phase 2 (once peak >= entry+15): arm trail, SL = peak - 5 (floor = entry+10)
    # 2026-08-20: V2-specific override -- V2's entries range from ~Rs73 (08-13
    # cluster) to ~Rs170 (07-23 cluster), and the FIXED_TP_PTS=15 arm threshold
    # is a much bigger % move on the cheap end (~20%) than the -18% HARDSL
    # needs to lose, so cheap-premium V2 trades rarely get a chance to trail
    # before HARDSL fires first (same asymmetry EXPIRY was given its own
    # multiplicative ladder for on 2026-07-26, see EXPIRY_VELVET_* above --
    # applying the same scaled-to-entry-premium principle here, not touching
    # the shared FIXED_TP_PTS/TRAIL_STEP_PTS/TRAIL_FLOOR_PTS other engines use).
    # UNVALIDATED against V2's own history: V2 has no per-cycle [STATE] log
    # (unlike ORB/VWAP), so its actual intraday peak trajectory isn't
    # reconstructable from past sessions -- this is a structural fix by
    # analogy to EXPIRY's precedent, not a backtested one. Watch live.
    ep = POS.entry_premium
    pk = POS.peak_premium
    if POS.engine == 'V2':
        _tp_pts    = ep * V2_TRAIL_ARM_PCT
        _step_pts  = ep * V2_TRAIL_STEP_PCT
        _floor_pts = ep * V2_TRAIL_FLOOR_PCT
    else:
        _tp_pts, _step_pts, _floor_pts = FIXED_TP_PTS, TRAIL_STEP_PTS, TRAIL_FLOOR_PTS

    if not POS.tr_armed and pk >= ep + _tp_pts:
        # TP level first reached — arm the trail
        POS.tr_armed = True
        POS.tr_sl    = max(ep + _floor_pts, pk - _step_pts)
        TG.send(f"🎯 <b>Trail ARMED</b> · {POS.side}\n"
                f"   Peak reached entry+{_tp_pts:.1f} → trailing (SL = peak−{_step_pts:.1f})\n"
                f"   Peak: <code>{pk:.2f}</code>  Trail SL: <code>{POS.tr_sl:.2f}</code>  "
                f"(floor: entry+{_floor_pts:.1f}=<code>{ep+_floor_pts:.2f}</code>)")
        save_state()

    if POS.tr_armed:
        # Ratchet trail SL up as peak rises (never down)
        new_sl = max(ep + _floor_pts, pk - _step_pts)
        if new_sl > POS.tr_sl:
            old_sl = POS.tr_sl
            POS.tr_sl = new_sl
            linfo(f"[TRAIL] SL ratcheted {old_sl:.2f} → {POS.tr_sl:.2f}  (peak={pk:.2f})")
            save_state()
        if cur_ltp <= POS.tr_sl:
            pts = round(POS.tr_sl - ep, 1)
            close_trade(f"TRAIL_+{pts:.0f}", POS.tr_sl)
            return True

    # 4. Trail exit — VWAP engine uses option VWAP trail; others use SMA8(low)
    df_opt = fetch_option_15m(POS.token)
    if df_opt is not None and len(df_opt) >= SMA_TRAIL_PERIOD + 1:
        last_bar_ts = df_opt.index[-2] if hasattr(df_opt.index, '__getitem__') else df_opt['date'].iloc[-2] \
                      if 'date' in df_opt.columns else None
        if last_bar_ts is not None and last_bar_ts != POS.sma8_last_bar_ts:
            POS.sma8_last_bar_ts = last_bar_ts
            last_closed_15m_c = float(df_opt['close'].iloc[-2])

            if POS.engine == "VWAP":
                # VWAP engine: exit only if option 15m close drops below its own VWAP
                # This holds through pullbacks as long as the trend is intact
                # FIX (2026-07-08): same pre-entry-bar guard as SMA8 trail's FIX A —
                # never judge the trade on a 15m bar that CLOSED before entry. Without
                # this, a mid-bar entry immediately evaluates the stale PRE-entry bar's
                # close vs VWAP on the very first poll and can eject in <60s regardless
                # of what happens after entry (observed 2026-07-07: both V19 and V20
                # VWAP trades exited 32-33s after entry on this stale bar).
                _bar_closed_pre_entry = False
                if POS.entry_time is not None and 'date' in df_opt.columns:
                    try:
                        _bt = df_opt['date'].iloc[-2]
                        if hasattr(_bt, 'astimezone'):
                            _bt = _bt.astimezone(IST)
                        _bar_closed_pre_entry = (_bt + timedelta(minutes=15)) <= POS.entry_time
                    except Exception:
                        _bar_closed_pre_entry = False
                opt_vwap = compute_option_vwap(POS.token)
                if not _bar_closed_pre_entry and opt_vwap is not None and last_closed_15m_c < opt_vwap:
                    linfo(f"[VWAP_TRAIL] Option 15m close {last_closed_15m_c:.2f} < VWAP {opt_vwap:.2f} — exiting")
                    close_trade("VWAP_TRAIL", cur_ltp)
                    return True
            else:
                # Non-VWAP engines: SMA8(low) trail.
                # V2.5.18 FIX A: never act on a 15m bar that CLOSED before entry
                # (bar-start + 15m <= entry_time). The 31s pre-entry eject of
                # 2026-06-19 came from judging the trade on the pre-entry 10:00 bar.
                # NOTE: last_bar_ts above is the integer row-index (dedup key); the
                # actual bar START time lives in the 'date' column.
                _bar_closed_pre_entry = False
                if POS.entry_time is not None and 'date' in df_opt.columns:
                    try:
                        _bt = df_opt['date'].iloc[-2]
                        if hasattr(_bt, 'astimezone'):
                            _bt = _bt.astimezone(IST)
                        _bar_closed_pre_entry = (_bt + timedelta(minutes=15)) <= POS.entry_time
                    except Exception:
                        _bar_closed_pre_entry = False
                if not _bar_closed_pre_entry:
                    sma8L = sma8_low_of_option(df_opt, POS.entry_time)
                    if sma8L is not None and last_closed_15m_c < sma8L:
                        close_trade("SMA8_LOW_TRAIL", cur_ltp)
                        return True

    return False

# =========================================================================
# WARMUP UNTIL READY
# =========================================================================
def warmup_until_ready(max_attempts=20):
    for attempt in range(max_attempts):
        df1h = fetch_nifty_1h()
        df15 = fetch_nifty_15m()
        df5  = fetch_nifty_5m()
        ok = (df1h is not None and len(df1h) >= SMA_SLOW_1H + 1 and
              df15 is not None and len(df15) >= STOCHRSI_LEN + STOCHRSI_RSI_LEN + 2 and
              df5  is not None and len(df5)  >= 5 and
              not pd.isna(df1h['SMA50'].iloc[-2]) and
              not pd.isna(df15['K'].iloc[-2]))
        if ok:
            return df1h, df15, df5
        lwarn(f"Warmup attempt {attempt+1}/{max_attempts}: data not ready yet.")
        time.sleep(15)
    raise RuntimeError("Warmup failed - market data unhealthy")

# =========================================================================
# MAIN
# =========================================================================
def push_logs_to_github(label="periodic"):
    """Push today's log + CSV to GitHub so they're readable remotely."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    branch = "claude/general-session-YfHuZ"
    # V2.5.20 runs concurrently with V2.5.19 in the same repo_dir; both call
    # this on their own periodic/EOD schedule. Concurrent `git add/commit/
    # push` from two processes in one working tree races on .git/index.lock
    # and can interleave commits. Serialize with a cross-process flock so
    # only one version's push runs at a time (the other just waits its turn).
    _git_lock_path = os.path.join(repo_dir, ".git_push.lock")
    _git_lock_fd = open(_git_lock_path, 'w')
    try:
        fcntl.flock(_git_lock_fd, fcntl.LOCK_EX)
    except Exception:
        pass
    try:
        subprocess.run(["git", "add", "-f", LOG_FN, CSV_FN],
                       cwd=repo_dir, check=True, capture_output=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"],
                                cwd=repo_dir)
        if result.returncode == 0:
            linfo(f"[{label}] No log changes to commit.")
            return
        subprocess.run(["git", "commit", "-m", f"Log {label} {today} ({VERSION})"],
                       cwd=repo_dir, check=True, capture_output=True)
        if GITHUB_PAT:
            remote = f"https://{GITHUB_PAT}@github.com/amolselukar/Amol.git"
        else:
            remote = "origin"
        # Fetch remote so we know its state, then rebase our log commit on top.
        # --autostash: the repo_dir working tree almost always has OTHER
        # unrelated files modified (other date-stamped log/CSV files the bots
        # touch) that were never staged by the `git add -f` above -- a plain
        # `git rebase` refuses to run against a dirty tree and aborts with no
        # exception raised (returncode ignored), silently leaving HEAD un-
        # rebased so the push below always failed non-fast-forward. Found
        # 2026-07-27: this had been failing on every single cycle since
        # 2026-07-20 (last successful push), ~365+ rejects/day/bot.
        fetch_r = subprocess.run(["git", "fetch", remote, branch],
                       cwd=repo_dir, capture_output=True)
        if fetch_r.returncode != 0:
            lwarn(f"[{label}] git fetch failed: {fetch_r.stderr.decode(errors='replace')}")
            return
        rebase_r = subprocess.run(["git", "rebase", "--autostash", "FETCH_HEAD"],
                       cwd=repo_dir, capture_output=True)
        if rebase_r.returncode != 0:
            lwarn(f"[{label}] git rebase failed, aborting rebase: "
                  f"{rebase_r.stderr.decode(errors='replace')}")
            subprocess.run(["git", "rebase", "--abort"], cwd=repo_dir, capture_output=True)
            return
        subprocess.run(["git", "push", remote, f"HEAD:{branch}"],
                       cwd=repo_dir, check=True, capture_output=True)
        linfo(f"[{label}] Logs pushed to GitHub: {LOG_FN}, {CSV_FN}")
        if label == "EOD":
            TG.send(f"📤 <b>Logs pushed to GitHub</b>\n"
                    f"   <code>{LOG_FN}</code>\n"
                    f"   <code>{CSV_FN}</code>")
    except subprocess.CalledProcessError as e:
        lwarn(f"[{label}] Git push failed: {e.stderr.decode() if e.stderr else e}")
    except Exception as e:
        lwarn(f"[{label}] push_logs_to_github error: {e}")
    finally:
        try:
            fcntl.flock(_git_lock_fd, fcntl.LOCK_UN)
            _git_lock_fd.close()
        except Exception:
            pass

def in_entry_window(now):
    start = now.replace(hour=ENTRY_START_HOUR, minute=ENTRY_START_MIN, second=0, microsecond=0)
    end   = now.replace(hour=ENTRY_END_HOUR,   minute=ENTRY_END_MIN,   second=0, microsecond=0)
    return start <= now <= end

def is_after_market_close(now):
    end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return now > end

# =========================================================================
# TELEGRAM COMMAND HANDLERS  (/status /pnl /stop /help)
# =========================================================================
def _cmd_status():
    # V2.5.20: up to 5 engines can each hold a position at once -- report each
    # active one, not just whichever engine POS happened to be bound to.
    blocks = []
    for _name in ENGINE_LIST:
        switch_engine(_name)
        if not POS.active:
            continue
        cur = ltp(POS.symbol)
        unreal = ((cur - POS.entry_premium) * lots_for(POS.engine) * LOT_SIZE) if cur else 0
        unreal_ps = (cur - POS.entry_premium) if cur else 0
        active_sl = POS.tr_sl if POS.tr_armed else POS.sl_current
        blocks.append(
            f"  Engine : <b>{_name}</b>  ({POS.side})\n"
            f"  Symbol : <code>{POS.symbol}</code>\n"
            f"  Entry  : ₹{POS.entry_premium:.2f}  @  {POS.entry_time.strftime('%H:%M') if POS.entry_time else '-'}\n"
            f"  LTP    : ₹{cur:.2f}\n"
            f"  Unreal : {unreal_ps:+.2f}/sh  (₹{unreal:+.0f} total)\n"
            f"  SL now : ₹{active_sl:.2f}  |  Peak: ₹{POS.peak_premium:.2f}\n"
            f"  Elapsed: {POS.elapsed_min():.0f} min"
        )
    switch_engine("BASE")
    if not blocks:
        TG.send("No active position right now (any engine).")
        return
    TG.send("📊 <b>LIVE POSITIONS</b>\n━━━━━━━━━━━━━━━━━\n" + "\n━━━━━━━━━━━━━━━━━\n".join(blocks))

def _cmd_pnl():
    # V2.5.20: aggregate closed+open PnL across all 5 engines.
    closed_pnl = 0.0
    n_closed = 0
    losses_total = 0
    open_pnl = 0.0
    open_lines = []
    for _name in ENGINE_LIST:
        switch_engine(_name)
        closed_pnl += sum(t['pnl'] * lots_for(t.get('engine','')) for t in DAY.trades_today) * LOT_SIZE
        n_closed += len(DAY.trades_today)
        losses_total += DAY.losses
        if POS.active:
            cur = ltp(POS.symbol)
            if cur:
                pnl = (cur - POS.entry_premium) * lots_for(POS.engine) * LOT_SIZE
                open_pnl += pnl
                open_lines.append(f"    [{_name}] ₹{pnl:+.0f}")
    switch_engine("BASE")
    total = closed_pnl + open_pnl
    open_str = ("\n" + "\n".join(open_lines)) if open_lines else ""
    TG.send(
        f"💰 <b>TODAY'S P&amp;L ({len(ENGINE_LIST)} engines)</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"  Closed trades : {n_closed}  |  ₹{closed_pnl:+.0f}\n"
        f"  Open P&amp;L      : ₹{open_pnl:+.0f}{open_str}\n"
        f"  Total         : ₹{total:+.0f}\n"
        f"  Non-flip losses: {losses_total}/{CIRCUIT_BREAKER} total"
        + (" — HALTED today" if GLOBAL_HALTED else "")
    )

def _cmd_stop():
    # V2.5.20: close every engine's open position before shutting down.
    TG.send("🛑 <b>Stop command received.</b> Closing any open positions and shutting down...")
    for _name in ENGINE_LIST:
        switch_engine(_name)
        if POS.active:
            cur = ltp(POS.symbol) or POS.entry_premium
            close_trade("TG_STOP", cur)
    switch_engine("BASE")
    _bot_stop_flag.set()

def _cmd_trades():
    # V2.5.20: combine all 5 engines' trade logs, most-recent-first isn't tracked
    # per-engine so just group by engine in ENGINE_LIST order.
    all_trades = []
    for _name in ENGINE_LIST:
        for t in DAY_STATES[_name].trades_today:
            all_trades.append(t)
    if not all_trades:
        TG.send("📋 No trades taken today yet (any engine).")
        return
    lines = [f"📋 <b>TRADES TODAY ({len(all_trades)}, all engines)</b>\n━━━━━━━━━━━━━━━━━"]
    for i, t in enumerate(all_trades, 1):
        side  = t.get('side', '?')
        eng   = t.get('engine', '?')
        entry = t.get('entry', 0)
        pnl   = t.get('pnl', 0) * lots_for(t.get('engine','')) * LOT_SIZE
        reason = t.get('reason', '?')
        lines.append(f"  {i}. {side} [{eng}]  entry ₹{entry:.0f}  PnL ₹{pnl:+.0f}  ({reason})")
    TG.send("\n".join(lines))

def _cmd_live():
    # V2.5.20: deliberately disabled regardless of current EXECUTION_BROKER --
    # this is now a LIVE build (mstock_live, 2 lots, real money on Amol's own
    # account) with a global 4-loss circuit breaker as its safety net. The
    # command stays refused so broker mode can only change via a code edit +
    # restart, never by anyone with Telegram access flipping it live/paper on
    # a whim mid-session. (Unreachable in practice: inbound command polling is
    # off, see main() -- kept here in case polling is ever re-enabled.)
    TG.send(f"⛔ <b>/live is disabled in {VERSION}.</b> Broker mode is fixed at "
            f"boot ({EXECUTION_BROKER}) and can only be changed via code + restart, "
            f"not by Telegram command.")

def _cmd_paper():
    # V2.5.20 (2026-07-14 fix): flipping to paper must never orphan a position that
    # is already open. Previously this only reassigned EXECUTION_BROKER, so any live
    # position still open at that moment kept its buy_order_id and stayed real, while
    # the user reasonably believed the bot had gone fully simulated. Now we say
    # exactly what is still open and what will happen to it.
    global EXECUTION_BROKER
    EXECUTION_BROKER = "kite_paper"
    still_open = []
    for _name in ENGINE_LIST:
        switch_engine(_name)
        if POS.active:
            still_open.append(
                f"  • [{_name}] {POS.symbol} @ ₹{POS.entry_premium:.2f} — "
                f"{'PAPER (simulated exit)' if POS.is_paper else 'LIVE, REAL LOT AT BROKER (exit will send a real SELL)'}"
            )
    switch_engine("BASE")
    msg = "📄 <b>Switched to PAPER mode.</b> No <i>new</i> real orders will be placed.\n"
    if still_open:
        msg += ("━━━━━━━━━━━━━━━━━━━━━━\n"
                "⚠️ <b>These positions are ALREADY OPEN and are still being managed:</b>\n"
                + "\n".join(still_open) + "\n"
                "They will be stopped/trailed/force-closed as normal and you will get an "
                "exit card for each. Switching to paper does <b>not</b> abandon them.")
    else:
        msg += "No positions currently open."
    TG.send(msg)

def _tg_poll_commands():
    """Background thread: poll Telegram getUpdates every 3 seconds for bot commands."""
    global _tg_cmd_offset
    poll_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    # V2.5.20 (2026-07-10 fix): discard any BACKLOG of updates queued before this thread
    # started -- this polling was disabled for a long time (see main()), so Telegram had
    # accumulated old unacknowledged messages (incl. a stale /stop from prior testing).
    # _tg_cmd_offset resets to 0 every process restart (it's in-memory only, never
    # persisted), so without this skip, the very first getUpdates call after any restart
    # replays that ENTIRE backlog from scratch -- which is exactly what happened: the bot
    # booted, immediately replayed an old /stop, shut down, and the supervisor's restart
    # loop hit the identical backlog again every ~20s, an infinite crash loop. Fix: on
    # thread start, fetch current updates once WITHOUT acting on them, just to advance
    # _tg_cmd_offset past everything already queued -- only messages that arrive AFTER
    # this point are ever processed.
    try:
        r0 = requests.get(poll_url, params={"offset": _tg_cmd_offset, "timeout": 0}, timeout=6)
        if r0.status_code == 200:
            _backlog = r0.json().get("result", [])
            if _backlog:
                _tg_cmd_offset = _backlog[-1]["update_id"] + 1
                lwarn(f"[telegram] Discarded {len(_backlog)} backlog update(s) on poll-thread "
                      f"start (offset now {_tg_cmd_offset}) — only new messages will be acted on.")
    except Exception as e:
        lwarn(f"[telegram] Backlog-skip check failed: {e} — proceeding with offset={_tg_cmd_offset}.")
    while not _bot_stop_flag.is_set():
        try:
            r = requests.get(poll_url,
                             params={"offset": _tg_cmd_offset, "timeout": 2},
                             timeout=6)
            if r.status_code == 200:
                for upd in r.json().get("result", []):
                    _tg_cmd_offset = upd["update_id"] + 1
                    msg  = upd.get("message", {})
                    text = (msg.get("text") or "").strip().lower()
                    cid  = str(msg.get("chat", {}).get("id", ""))
                    if cid != str(TELEGRAM_CHAT_ID):
                        continue  # ignore messages from other chats
                    if text in ("/status", "/pos"):
                        _cmd_status()
                    elif text == "/pnl":
                        _cmd_pnl()
                    elif text == "/trades":
                        _cmd_trades()
                    elif text == "/stop":
                        _cmd_stop()
                    elif text == "/live":
                        _cmd_live()
                    elif text == "/paper":
                        _cmd_paper()
                    elif text == "/help":
                        TG.send("🤖 <b>ORION commands</b>\n"
                                "/status  — live position details\n"
                                "/pnl     — today's P&amp;L summary\n"
                                "/trades  — list all trades today\n"
                                "/live    — switch to LIVE mode (real mStock orders)\n"
                                "/paper   — switch to PAPER mode (no real orders)\n"
                                "/stop    — close position &amp; shut down bot\n"
                                "/help    — this message")
        except Exception:
            pass
        time.sleep(3)


# =========================================================================
# EOD DATA CAPTURE (integrated from Optiondata_1.py)
# =========================================================================
EOD_ATM_STEP        = 100
EOD_LADDER_STEP     = 100
EOD_ITM_OTM_COUNT   = 2
# 1m added 2026-07-20 (Kite interval is 'minute', NOT '1minute'): collect 1-minute
# CE/PE/spot/fut so both bots' logic can be simulated on 1m bars.
EOD_NIFTY_DAYS_BACK = {'minute': 2, '5minute': 7, '15minute': 15, '60minute': 90}
EOD_OPTION_DAYS_BACK= {'minute': 2, '5minute': 7, '15minute': 10, '60minute': 30}
EOD_TIMEFRAMES      = ['minute', '5minute', '15minute', '60minute']
EOD_TF_LABELS       = {'minute': '1m', '5minute': '5m', '15minute': '15m', '60minute': '1h'}
EOD_RATE_LIMIT      = 0.4
EOD_OUT_ROOT        = "daily_option_data_sensex"
EOD_OI_SURVEY_RADIUS= 2000
EOD_OI_SURVEY_STEP  = 100
EOD_FUT_DAYS_BACK   = {'minute': 2, '5minute': 7, '15minute': 15, '60minute': 90}


def _eod_add_vwap(df, target_date):
    """Add session VWAP column (computed per-day from 9:15 AM) to a DataFrame with date/close/volume."""
    df = df.copy()
    df['_dt'] = pd.to_datetime(df['date'])
    df['_date'] = df['_dt'].dt.date
    df['vwap'] = float('nan')
    typical = (df['high'] + df['low'] + df['close']) / 3
    for d in df['_date'].unique():
        mask = (df['_date'] == d) & (df['_dt'].dt.hour * 60 + df['_dt'].dt.minute >= 9 * 60 + 15)
        if mask.sum() == 0:
            continue
        cum_tp_vol = (typical[mask] * df.loc[mask, 'volume']).cumsum()
        cum_vol = df.loc[mask, 'volume'].cumsum()
        df.loc[mask, 'vwap'] = (cum_tp_vol / cum_vol.replace(0, float('nan'))).values
    df.drop(columns=['_dt', '_date'], inplace=True)
    return df


def _eod_round_atm(price):
    return int(round(price / EOD_ATM_STEP)) * EOD_ATM_STEP


def _eod_fetch_nifty_tf(target_date, interval, days_back):
    end = datetime.combine(target_date, datetime.min.time()).replace(hour=15, minute=35)
    start = end - timedelta(days=days_back)
    end_ist = IST.localize(end)
    start_ist = IST.localize(start)
    recs = historical(NIFTY_INSTRUMENT_TOKEN, start_ist, end_ist, interval)
    if not recs:
        return pd.DataFrame(), "EMPTY"
    df = pd.DataFrame(recs)[['date', 'open', 'high', 'low', 'close', 'volume']]
    return df, None


def _eod_fetch_option_tf(token, target_date, interval, days_back):
    end = datetime.combine(target_date, datetime.min.time()).replace(hour=15, minute=35)
    start = end - timedelta(days=days_back)
    end_ist = IST.localize(end)
    start_ist = IST.localize(start)
    recs = historical(token, start_ist, end_ist, interval)
    if not recs:
        return pd.DataFrame(), "EMPTY"
    df = pd.DataFrame(recs)[['date', 'open', 'high', 'low', 'close', 'volume']]
    return df, None


def _eod_fetch_fut_tf(fut_token, target_date, interval, days_back):
    end = datetime.combine(target_date, datetime.min.time()).replace(hour=15, minute=35)
    start = end - timedelta(days=days_back)
    end_ist = IST.localize(end)
    start_ist = IST.localize(start)
    recs = historical(fut_token, start_ist, end_ist, interval)
    if not recs:
        return pd.DataFrame(), "EMPTY"
    df = pd.DataFrame(recs)[['date', 'open', 'high', 'low', 'close', 'volume']]
    return df, None


def _eod_build_atm_tracker(nifty_5m_df, target_date):
    df = nifty_5m_df.copy()
    df['date_only'] = pd.to_datetime(df['date']).dt.date
    df = df[df['date_only'] == target_date].drop(columns=['date_only'])
    rows = []
    for _, bar in df.iterrows():
        nc = float(bar['close'])
        atm = _eod_round_atm(nc)
        rows.append({
            'time': bar['date'], 'nifty_close': nc, 'atm_strike': atm,
            'ce_itm2': atm - 2*EOD_LADDER_STEP, 'ce_itm1': atm - EOD_LADDER_STEP,
            'ce_atm': atm, 'ce_otm1': atm + EOD_LADDER_STEP, 'ce_otm2': atm + 2*EOD_LADDER_STEP,
            'pe_itm2': atm + 2*EOD_LADDER_STEP, 'pe_itm1': atm + EOD_LADDER_STEP,
            'pe_atm': atm, 'pe_otm1': atm - EOD_LADDER_STEP, 'pe_otm2': atm - 2*EOD_LADDER_STEP,
        })
    return pd.DataFrame(rows)


def _eod_collect_strikes(tracker_df):
    ce_cols = ['ce_itm2', 'ce_itm1', 'ce_atm', 'ce_otm1', 'ce_otm2']
    pe_cols = ['pe_itm2', 'pe_itm1', 'pe_atm', 'pe_otm1', 'pe_otm2']
    ce_strikes, pe_strikes = set(), set()
    for c in ce_cols:
        ce_strikes.update(int(s) for s in tracker_df[c].unique())
    for c in pe_cols:
        pe_strikes.update(int(s) for s in tracker_df[c].unique())
    return sorted(ce_strikes), sorted(pe_strikes)


def _eod_fetch_oi_survey(nifty_master, expiry, eod_atm, ce_vol_map, pe_vol_map):
    survey_strikes = list(range(
        eod_atm - EOD_OI_SURVEY_RADIUS,
        eod_atm + EOD_OI_SURVEY_RADIUS + EOD_OI_SURVEY_STEP,
        EOD_OI_SURVEY_STEP
    ))
    weekly_master = nifty_master[nifty_master['expiry'] == expiry]
    sym_to_info = {}
    for _, row in weekly_master.iterrows():
        s = int(row['strike'])
        if s in survey_strikes:
            side = row['instrument_type']
            sym = row['tradingsymbol']
            sym_to_info[f"BFO:{sym}"] = (s, side)
    if not sym_to_info:
        return {}
    all_quotes = {}
    syms = list(sym_to_info.keys())
    for i in range(0, len(syms), 200):
        batch = syms[i:i+200]
        try:
            q = kite.quote(batch)
            all_quotes.update(q)
            time.sleep(EOD_RATE_LIMIT)
        except Exception as e:
            linfo(f"[EOD OI] quote() error: {e}")
    strikes_data = {}
    for sym, (strike, side) in sym_to_info.items():
        key = str(strike)
        if key not in strikes_data:
            strikes_data[key] = {"CE": {}, "PE": {}}
        q = all_quotes.get(sym, {})
        oi = q.get("oi", 0) or 0
        lt = q.get("last_price", 0) or 0
        vol = q.get("volume", 0) or 0
        if side == "CE" and strike in ce_vol_map:
            vol = ce_vol_map[strike]
        elif side == "PE" and strike in pe_vol_map:
            vol = pe_vol_map[strike]
        strikes_data[key][side] = {"oi": oi, "ltp": lt, "volume": vol}
    return strikes_data


def validate_captured_data(day_dir, target_date):
    """Validate captured data has all required components for backtesting."""
    issues = []
    required_nifty = ["nifty_5m.csv", "nifty_15m.csv", "nifty_1h.csv"]
    for fn in required_nifty:
        fp = os.path.join(day_dir, fn)
        if not os.path.exists(fp):
            issues.append(f"Missing {fn}")
        else:
            df = pd.read_csv(fp)
            if len(df) == 0:
                issues.append(f"{fn} is empty")
            today_bars = df[pd.to_datetime(df['date']).dt.date == target_date] if 'date' in df.columns else df
            if len(today_bars) == 0:
                issues.append(f"{fn} has no bars for {target_date}")
    tracker_fp = os.path.join(day_dir, "atm_tracker_5m.csv")
    if not os.path.exists(tracker_fp):
        issues.append("Missing atm_tracker_5m.csv")
    ce_dir = os.path.join(day_dir, "CE")
    pe_dir = os.path.join(day_dir, "PE")
    ce_count = len([f for f in os.listdir(ce_dir) if f.endswith('.csv')]) if os.path.isdir(ce_dir) else 0
    pe_count = len([f for f in os.listdir(pe_dir) if f.endswith('.csv')]) if os.path.isdir(pe_dir) else 0
    if ce_count == 0:
        issues.append("No CE strike CSVs")
    if pe_count == 0:
        issues.append("No PE strike CSVs")
    # Check option CSVs have all 3 timeframes
    for side_dir, side in [(ce_dir, "CE"), (pe_dir, "PE")]:
        if not os.path.isdir(side_dir):
            continue
        for fn in os.listdir(side_dir):
            if not fn.endswith('.csv'):
                continue
            fp = os.path.join(side_dir, fn)
            df = pd.read_csv(fp)
            if 'tf' in df.columns:
                tfs = set(df['tf'].unique())
                missing_tf = {'5m', '15m', '1h'} - tfs
                if missing_tf:
                    issues.append(f"{side}/{fn} missing timeframes: {missing_tf}")
            if 'vwap' not in df.columns:
                issues.append(f"{side}/{fn} missing VWAP column")
    # Check Nifty spot VWAP
    for fn in required_nifty:
        fp = os.path.join(day_dir, fn)
        if os.path.exists(fp):
            df = pd.read_csv(fp)
            if 'vwap' not in df.columns:
                issues.append(f"{fn} missing VWAP column")
    # Check futures files
    fut_files = ["nifty_fut_5m.csv", "nifty_fut_15m.csv", "nifty_fut_1h.csv"]
    for fn in fut_files:
        fp = os.path.join(day_dir, fn)
        if not os.path.exists(fp):
            issues.append(f"Missing {fn}")
        elif 'vwap' not in pd.read_csv(fp).columns:
            issues.append(f"{fn} missing VWAP column")
    oi_fp = os.path.join(day_dir, "_oi_survey.json")
    if not os.path.exists(oi_fp):
        issues.append("Missing _oi_survey.json")
    return issues


def run_eod_data_capture():
    """Run full EOD data capture after trading stops. Uses the bot's existing kite connection."""
    target_date = datetime.now(IST).date()
    if target_date.weekday() >= 5:
        linfo(f"[EOD DATA] {target_date} is weekend. Skipping.")
        TG.send(f"📊 EOD data capture skipped — {target_date.strftime('%A')} (weekend)")
        return

    TG.send(
        f"📊 <b>ORION {VERSION} — Stopping trading, starting EOD data capture</b>\n"
        f"   Date: {target_date}\n"
        f"   Collecting: Nifty 5m/15m/1h + ATM option strikes CE/PE + OI survey"
    )
    linfo(f"[EOD DATA] Starting data capture for {target_date}")

    try:
        # Load NFO master
        inst_df = pd.DataFrame(kite.instruments("BFO"))
        nifty_master = inst_df[inst_df['name'] == 'NIFTY'].copy()
        nifty_master['expiry'] = pd.to_datetime(nifty_master['expiry']).dt.date
        expiries = sorted(set(nifty_master['expiry']))
        expiry = next((e for e in expiries if e >= target_date), None)
        monthly_expiry = next((e for e in expiries if e >= target_date and e.day >= 24), None)
        if expiry is None:
            TG.send("⚠️ EOD data capture: no expiry found. Aborting.")
            return

        # Resolve nearest Nifty futures token
        all_insts = inst_df
        nifty_futs = all_insts[(all_insts['name'] == 'NIFTY') &
                               (all_insts['instrument_type'] == 'FUT')]
        nifty_futs = nifty_futs[pd.to_datetime(nifty_futs['expiry']).dt.date >= target_date]
        fut_token = None
        if len(nifty_futs) > 0:
            nearest = nifty_futs.sort_values('expiry').iloc[0]
            fut_token = int(nearest['instrument_token'])
            linfo(f"[EOD DATA] Futures token: {fut_token} ({nearest['tradingsymbol']})")

        # Fetch Nifty multi-TF
        nifty_data = {}
        for tf in EOD_TIMEFRAMES:
            df, err = _eod_fetch_nifty_tf(target_date, tf, EOD_NIFTY_DAYS_BACK[tf])
            if err or df.empty:
                linfo(f"[EOD DATA] Nifty {EOD_TF_LABELS[tf]} failed: {err or 'EMPTY'}")
                TG.send(f"⚠️ EOD data: Nifty {EOD_TF_LABELS[tf]} fetch failed")
                return
            nifty_data[tf] = df
            time.sleep(EOD_RATE_LIMIT)

        nifty_5m = nifty_data['5minute']
        nifty_5m_today = nifty_5m[pd.to_datetime(nifty_5m['date']).dt.date == target_date]
        if nifty_5m_today.empty:
            TG.send("⚠️ EOD data: No 5m bars for today — holiday?")
            return
        eod_close = float(nifty_5m_today['close'].iloc[-1])
        eod_atm = _eod_round_atm(eod_close)

        # Fetch Nifty futures multi-TF
        fut_data = {}
        if fut_token:
            for tf in EOD_TIMEFRAMES:
                df, err = _eod_fetch_fut_tf(fut_token, target_date, tf, EOD_FUT_DAYS_BACK[tf])
                if err or df.empty:
                    linfo(f"[EOD DATA] Futures {EOD_TF_LABELS[tf]} failed: {err or 'EMPTY'}")
                else:
                    fut_data[tf] = df
                time.sleep(EOD_RATE_LIMIT)

        # Build ATM tracker
        tracker = _eod_build_atm_tracker(nifty_5m, target_date)
        ce_strikes, pe_strikes = _eod_collect_strikes(tracker)
        linfo(f"[EOD DATA] ATM tracker: {len(tracker)} rows, CE={ce_strikes}, PE={pe_strikes}")

        # Resolve tokens
        weekly_master = nifty_master[nifty_master['expiry'] == expiry]
        contract_lookup = {}
        for _, row in weekly_master.iterrows():
            key = (int(row['strike']), row['instrument_type'])
            contract_lookup[key] = (int(row['instrument_token']), row['tradingsymbol'])

        # Output dirs
        day_dir = os.path.join(EOD_OUT_ROOT, str(target_date))
        ce_dir = os.path.join(day_dir, "CE")
        pe_dir = os.path.join(day_dir, "PE")
        for d in [ce_dir, pe_dir]:
            os.makedirs(d, exist_ok=True)

        # Save Nifty spot CSVs with VWAP + tracker
        for tf in EOD_TIMEFRAMES:
            df_with_vwap = _eod_add_vwap(nifty_data[tf], target_date)
            out = os.path.join(day_dir, f"nifty_{EOD_TF_LABELS[tf]}.csv")
            df_with_vwap.to_csv(out, index=False)

        # Save Nifty futures CSVs with VWAP
        if fut_data:
            for tf in EOD_TIMEFRAMES:
                if tf in fut_data:
                    df_with_vwap = _eod_add_vwap(fut_data[tf], target_date)
                    out = os.path.join(day_dir, f"nifty_fut_{EOD_TF_LABELS[tf]}.csv")
                    df_with_vwap.to_csv(out, index=False)
            linfo(f"[EOD DATA] Saved futures CSVs: {[EOD_TF_LABELS[tf] for tf in fut_data]}")

        tracker.to_csv(os.path.join(day_dir, "atm_tracker_5m.csv"), index=False)

        # Fetch option strikes
        fetch_log = []
        ce_vol_map, pe_vol_map = {}, {}

        for side, strikes_list in [('CE', ce_strikes), ('PE', pe_strikes)]:
            side_dir = ce_dir if side == 'CE' else pe_dir
            for strike in strikes_list:
                key = (strike, side)
                if key not in contract_lookup:
                    for tf in EOD_TIMEFRAMES:
                        fetch_log.append({'side': side, 'strike': strike,
                                          'tf': EOD_TF_LABELS[tf], 'status': 'NO_TOKEN', 'bars': 0})
                    continue
                token, tsym = contract_lookup[key]
                all_dfs = []
                total_vol_5m = 0
                for tf in EOD_TIMEFRAMES:
                    df, err = _eod_fetch_option_tf(token, target_date, tf, EOD_OPTION_DAYS_BACK[tf])
                    tf_label = EOD_TF_LABELS[tf]
                    if err or df.empty:
                        fetch_log.append({'side': side, 'strike': strike,
                                          'tf': tf_label, 'status': err or 'EMPTY', 'bars': 0})
                        time.sleep(EOD_RATE_LIMIT)
                        continue
                    df = df.copy()
                    df['tf'] = tf_label
                    if tf == '5minute':
                        today_mask = pd.to_datetime(df['date']).dt.date == target_date
                        total_vol_5m = int(df.loc[today_mask, 'volume'].sum())
                    all_dfs.append(df)
                    fetch_log.append({'side': side, 'strike': strike,
                                      'tf': tf_label, 'status': 'OK', 'bars': len(df)})
                    time.sleep(EOD_RATE_LIMIT)
                if all_dfs:
                    combined = pd.concat(all_dfs, ignore_index=True)
                    combined = combined[['tf', 'date', 'open', 'high', 'low', 'close', 'volume']]
                    # Add VWAP per timeframe group
                    vwap_parts = []
                    for tf_label in combined['tf'].unique():
                        tf_slice = combined[combined['tf'] == tf_label].copy()
                        tf_slice = _eod_add_vwap(tf_slice, target_date)
                        vwap_parts.append(tf_slice)
                    combined = pd.concat(vwap_parts, ignore_index=True)
                    combined.to_csv(os.path.join(side_dir, f"{strike}.csv"), index=False)
                    if side == 'CE':
                        ce_vol_map[strike] = total_vol_5m
                    else:
                        pe_vol_map[strike] = total_vol_5m

        # OI Survey
        survey_data = _eod_fetch_oi_survey(nifty_master, expiry, eod_atm, ce_vol_map, pe_vol_map)
        oi_survey = {
            "date": str(target_date), "expiry": str(expiry),
            "monthly_expiry": str(monthly_expiry) if monthly_expiry else "",
            "atm": eod_atm, "eod_nifty_close": eod_close,
            "survey_radius": EOD_OI_SURVEY_RADIUS, "survey_step": EOD_OI_SURVEY_STEP,
            "strikes": survey_data,
        }
        with open(os.path.join(day_dir, "_oi_survey.json"), "w") as f:
            json.dump(oi_survey, f, indent=2)

        # Save metadata
        ok_count = sum(1 for r in fetch_log if r['status'] == 'OK')
        fail_count = len(fetch_log) - ok_count
        total_bars = sum(r['bars'] for r in fetch_log)
        meta = {
            'capture_script_version': f'ORION_INTEGRATED_{VERSION}',
            'target_date': str(target_date), 'target_expiry': str(expiry),
            'monthly_expiry': str(monthly_expiry),
            'eod_atm': eod_atm, 'eod_nifty_close': eod_close,
            'timeframes': [EOD_TF_LABELS[tf] for tf in EOD_TIMEFRAMES],
            'ce_strikes_fetched': ce_strikes, 'pe_strikes_fetched': pe_strikes,
            'oi_survey_strikes': sorted(int(k) for k in survey_data.keys()),
            'fetch_log': fetch_log,
        }
        with open(os.path.join(day_dir, "_meta.json"), 'w') as f:
            json.dump(meta, f, indent=2, default=str)

        # Validate
        issues = validate_captured_data(day_dir, target_date)
        if issues:
            issue_txt = "\n".join(f"  - {i}" for i in issues)
            TG.send(
                f"⚠️ <b>EOD data captured with issues</b>\n"
                f"   Folder: <code>{day_dir}</code>\n"
                f"   Fetches: {ok_count} OK / {fail_count} failed / {total_bars:,} bars\n"
                f"   Issues:\n<pre>{issue_txt}</pre>"
            )
            linfo(f"[EOD DATA] Completed with issues: {issues}")
        else:
            TG.send(
                f"✅ <b>EOD data capture COMPLETE — all validated</b>\n"
                f"   Folder: <code>{day_dir}</code>\n"
                f"   Date: {target_date} | Expiry: {expiry}\n"
                f"   Nifty EOD: {eod_close:.2f} | ATM: {eod_atm}\n"
                f"   CE strikes: {len(ce_strikes)} | PE strikes: {len(pe_strikes)}\n"
                f"   Option fetches: {ok_count} OK / {fail_count} failed / {total_bars:,} bars\n"
                f"   OI survey: {len(survey_data)} strikes\n"
                f"   Futures: {len(fut_data)} TFs ✓ | VWAP (spot+fut+options) ✓\n"
                f"   Timeframes: 5m, 15m, 1h ✓"
            )
            linfo(f"[EOD DATA] Capture complete. Folder: {day_dir}, {ok_count} OK, {total_bars} bars")

    except Exception as e:
        tb = traceback.format_exc()
        lerr(f"[EOD DATA] Exception: {e}\n{tb}")
        TG.send(f"⚠️ <b>EOD data capture FAILED</b>\n<code>{str(e)[:500]}</code>")


def main():
    csv_init()
    load_state()
    wd_thread = threading.Thread(target=WD.run, daemon=True)
    wd_thread.start()
    # V2.5.20: inbound Telegram command polling enabled 2026-07-10. Uses its
    # own bot token (TELEGRAM_V2520_BOT_TOKEN) distinct from V2.5.19's, so
    # getUpdates offsets don't collide even though both post to the same
    # chat ID. /live stays hard-disabled in _cmd_live() regardless; only
    # /paper, /status, /pnl, /trades, /stop, /help are actually reachable.
    tg_cmd_thread = threading.Thread(target=_tg_poll_commands, daemon=True)
    tg_cmd_thread.start()

    # ---- Resolve expiry + strikes ----
    target_expiry, strikes, expiry_lookup, _nifty_fut_token = resolve_expiry_and_strikes()
    # V2.5.20 (2026-07-12): expose the resolved expiry to check_expiry_signal's
    # real-expiry-day gate.
    global TARGET_EXPIRY_DATE
    TARGET_EXPIRY_DATE = target_expiry
    NIFTY_FUT_TOKEN = _nifty_fut_token
    linfo(f"[BOOT] Expiry: {target_expiry}, {len(strikes)} strikes, {len(expiry_lookup)} option contracts")

    # ---- Init mStock broker at boot (not lazily) ----
    # PAPER MODE BYPASS (2026-06-29): in kite_paper we place no real orders, so
    # mStock is not needed. Skip login + self-test entirely to avoid the failing
    # broker check ("Error Occured...") aborting/alerting and to guarantee the
    # bot runs in paper regardless of mStock token/IP state.
    if EXECUTION_BROKER == "mstock_live":
        _init_mstock_at_boot()
    else:
        linfo("[BOOT] PAPER mode (kite_paper) — mStock init + self-test SKIPPED (bypassed).")

    # ---- mStock execution self-test at boot (live mode only) ----
    if EXECUTION_BROKER == "mstock_live" and _mstock_broker:
        linfo("[BOOT] Running mStock execution self-test (LIMIT order + cancel)...")
        _test_passed = False
        try:
            # V2.5.20 FIX (2026-07-07): the old `round_to_atm(24000) + 2000`
            # hardcoded a stale reference spot -- as spot drifts week to week
            # the computed strike can fall outside the day's actual ~100-strike
            # expiry_lookup range, tripping the naive fallback symbol string
            # below (which doesn't match mStock's own weekly-option naming and
            # gets rejected with a generic errorcode, not a clear "bad symbol"
            # message). Pick the deepest available CE strike that's GUARANTEED
            # to be a real, resolvable contract instead -- same symbol path
            # (expiry_lookup -> _mstock_option_symbol) that real live trades
            # already use successfully.
            _ce_strikes = sorted(s for (s, _side) in expiry_lookup if _side == 'CE')
            _test_expiry = target_expiry
            if _ce_strikes:
                _test_strike = _ce_strikes[-1]  # deepest available CE — won't fill at 0.05
                _test_sym_key = (_test_strike, 'CE')
                _test_kite_sym, _ = expiry_lookup[_test_sym_key]
                _test_ms_sym = _mstock_option_symbol(_test_kite_sym)
            else:
                _test_strike = round_to_atm(24000) + 2000
                _test_ms_sym = f"NIFTY{_test_expiry.strftime('%y%b').upper()}{_test_strike}CE"
                lwarn("[BOOT] mStock self-test: no CE strikes in expiry_lookup — falling back "
                      "to the old (unreliable) hardcoded-symbol construction.")
            _test_oid = _mstock_broker.place_order(
                "BUY", _test_ms_sym, LOT_SIZE, "LIMIT", price=0.05, tag="ORION_TEST"
            )
            if _test_oid:
                linfo(f"[BOOT] ✅ mStock test BUY placed: {_test_ms_sym} oid={_test_oid}")
                _mstock_broker.cancel_order(_test_oid)
                linfo(f"[BOOT] ✅ mStock test BUY cancelled. BUY VERIFIED.")
                _test_passed = True
            else:
                _err = getattr(_mstock_broker, '_last_error', '') or 'unknown'
                lwarn(f"[BOOT] ❌ mStock test BUY FAILED: {_err}")
        except Exception as _te:
            lwarn(f"[BOOT] ❌ mStock self-test exception: {_te}")
        if not _test_passed:
            _msg = ("⚠️ mStock self-test FAILED (IP/credentials issue).\n"
                    f"Error: {getattr(_mstock_broker, '_last_error', 'unknown')}\n"
                    f"Mode: {EXECUTION_BROKER} — "
                    + ("⛔ ABORTING." if EXECUTION_BROKER == "mstock_live" else "Bot continues in PAPER mode."))
            TG.send(_msg)
            linfo(f"[BOOT] {_msg}")
            if EXECUTION_BROKER == "mstock_live":
                linfo("[BOOT] Exiting. Fix mStock and restart manually.")
                sys.exit(1)
        else:
            TG.send(f"✅ mStock self-test PASSED — order execution verified at boot. Mode: {EXECUTION_BROKER}")

    # ---- Warmup ----
    df1h, df15, df5 = warmup_until_ready()

    # ---- Compute V3 daily levels & regime ----
    # Prior day OHLC from df5 (today's first bar's open vs yesterday's last close from 1h)
    # Simpler: use df1h's prior session H/L/C
    today = datetime.now(IST).date()
    df1h_today    = df1h[df1h['date'].apply(lambda x: x.date() if hasattr(x,'date') else x) == today] \
                    if 'date' in df1h.columns else df1h[df1h.index.date == today] if hasattr(df1h.index,'date') else pd.DataFrame()
    # If df1h has a 'date' field that's a datetime, prior session = df1h before today's first bar
    if hasattr(df1h['date'].iloc[0], 'date'):
        prior_mask = df1h['date'].apply(lambda x: x.date()) < today
    else:
        prior_mask = df1h.index.date < today
    df1h_prior = df1h[prior_mask].reset_index(drop=True)
    if len(df1h_prior) >= 7:
        pdh = float(df1h_prior['high'].iloc[-7:].max())
        pdl = float(df1h_prior['low'].iloc[-7:].min())
        pdc = float(df1h_prior['close'].iloc[-1])
        DAY.levels = compute_levels_for_day(df1h_prior, {'H':pdh,'L':pdl,'C':pdc})
        DAY.regime = classify_regime(df1h_prior.iloc[-1])
        # V2.5.19: classic floor-trader pivots for Features 2 & 3 S/R clear-space gate
        DAY.pivots = compute_classic_pivots(pdh, pdl, pdc)
        linfo(f"[PIVOTS] P={DAY.pivots['P']:.0f} "
              f"R1={DAY.pivots['R1']:.0f} R2={DAY.pivots['R2']:.0f} "
              f"S1={DAY.pivots['S1']:.0f} S2={DAY.pivots['S2']:.0f}")

        # ---- Load OI plan + inject walls into V3 ----
        oi_plan = load_oi_plan()
        if oi_plan:
            _inject_oi_walls(DAY.levels, oi_plan)
            exp_flag = ""
            if oi_plan.get("is_expiry_day"):
                exp_flag = " | EXPIRY DAY"
            elif oi_plan.get("expiry_caution"):
                exp_flag = f" | T-{oi_plan.get('days_to_expiry','?')} expiry caution"
            plan_msg = (
                f"<b>OI Plan for today</b>{exp_flag}\n"
                f"ATM:{oi_plan.get('atm')} PCR:{oi_plan.get('pcr')} "
                f"Bias:<b>{oi_plan.get('bias')}</b> MaxPain:{oi_plan.get('max_pain')}\n"
            )
            res = [f"{r['strike']}[{r['signal']}]" for r in oi_plan.get("resistance_levels", [])[:3]]
            sup = [f"{s['strike']}[{s['signal']}]" for s in oi_plan.get("support_levels", [])[:3]]
            if res:
                plan_msg += f"Resistance: {' | '.join(res)}\n"
            if sup:
                plan_msg += f"Support: {' | '.join(sup)}\n"
            if oi_plan.get("_info_only") or oi_plan.get("expiry_caution"):
                plan_msg += "OI levels: INFORMATIONAL only (expiry caution)\n"
            else:
                plan_msg += f"V3 OI R={oi_plan.get('v3_resistance',[])} S={oi_plan.get('v3_support',[])}\n"
            # Always show price-action clusters if available in plan
            pc = oi_plan.get("price_clusters")
            if pc:
                plan_msg += (
                    f"<b>Price Levels (PDH/PDL/round/swing):</b>\n"
                    f"PDH:{pc.get('pdh')} PDL:{pc.get('pdl')} PDC:{pc.get('pdc')}\n"
                )
                above = pc.get("clusters_above", [])[:5]
                below = pc.get("clusters_below", [])[:5]
                if above:
                    plan_msg += "R: " + " | ".join(f"{c['center']:.0f}[{c['grade']}]" for c in above) + "\n"
                if below:
                    plan_msg += "S: " + " | ".join(f"{c['center']:.0f}[{c['grade']}]" for c in below) + "\n"
            TG.send(plan_msg)
            linfo(f"[OI Plan] PCR={oi_plan.get('pcr')} bias={oi_plan.get('bias')} "
                  f"max_pain={oi_plan.get('max_pain')} expiry_caution={oi_plan.get('expiry_caution')}")
        else:
            linfo("[OI Plan] No valid plan found — running without OI levels (normal mode)")
    else:
        lwarn(f"Insufficient prior 1h history ({len(df1h_prior)} rows); V3 disabled today")
        DAY.levels = None
        DAY.regime = "INSUFFICIENT"
        DAY.pivots = None  # V2.5.19: pivot-distance gates fail OPEN when unavailable

    # ---- Gap suppression check ----
    if df5 is not None and len(df5) > 0 and DAY.levels is not None:
        today_open = float(df5['open'].iloc[0])
        pdc = DAY.levels['pdc']
        gap = (today_open / pdc) - 1
        if abs(gap) > GAP_SUPPRESS_PCT:
            DAY.gap_suppress_until = datetime.now(IST).replace(
                hour=GAP_SUPPRESS_UNTIL_HOUR, minute=GAP_SUPPRESS_UNTIL_MIN, second=0, microsecond=0)
            linfo(f"[GAP] {gap*100:+.2f}% gap; suppressing entries until {DAY.gap_suppress_until.strftime('%H:%M')}")

    # ---- V2.5.20: propagate shared day-level facts (computed once above into the
    # lone module DAY) into all 5 engines' own DAY_STATES, since each engine now
    # reads its OWN DAY via switch_engine() ----
    for _name in ENGINE_LIST:
        DAY_STATES[_name].levels = DAY.levels
        DAY_STATES[_name].regime = DAY.regime
        DAY_STATES[_name].pivots = DAY.pivots
        DAY_STATES[_name].gap_suppress_until = DAY.gap_suppress_until
    # GAPBREAK's own prev-close (yesterday's last spot close) -- reuse pdc (prior
    # 1h close), which is the same underlying day-close value used for V3 levels.
    if DAY.levels is not None:
        DAY_STATES["GAPBREAK"].prev_close = DAY.levels['pdc']
    linfo(f"[V2.5.20] {len(ENGINE_LIST)} independent engines armed: {', '.join(ENGINE_LIST)} "
          f"(regime={DAY.regime}, gap_suppress_until="
          f"{DAY.gap_suppress_until.strftime('%H:%M') if DAY.gap_suppress_until else 'n/a'})")

    # ---- Log strategy box + change history to file (full detail, no length limit) ----
    for line in STRATEGY_BOX.splitlines():
        linfo(line)
    for line in CHANGE_HISTORY.splitlines():
        linfo(line)

    # ---- Boot Telegram ----
    TG.send(fmt_boot(target_expiry, DAY.levels))
    # 2026-08-29: send the TAIL, not the head. This used to send CHANGE_HISTORY
    # [:3800] -- the OLDEST 3800 chars (V2.2.2-era) -- so the one thing the boot
    # message could never tell you was what changed recently.
    _ch_safe = CHANGE_HISTORY[-3800:].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    TG.send(f"<b>📋 CHANGE HISTORY (most recent) — ORION {VERSION}</b>\n<pre>{_ch_safe}</pre>")
    # 2026-08-29: undocumented-change guard -- see check_changelog_current().
    _cl_ok, _cl_msg = check_changelog_current()
    if _cl_ok:
        linfo(_cl_msg)
    else:
        lwarn(f"[CHANGELOG] {_cl_msg}")
        TG.send("<b>⚠️ UNDOCUMENTED CHANGE</b>\n<pre>"
                + _cl_msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                + "</pre>")

    # ---- Live state + first pulse ----
    c1h_now    = float(df1h['close'].iloc[-2])
    sma20_now  = float(df1h['SMA20'].iloc[-2])
    sma50_now  = float(df1h['SMA50'].iloc[-2])
    K_now      = float(df15['K'].iloc[-2])
    K_prev     = float(df15['K'].iloc[-3])
    spot_now   = float(df5['close'].iloc[-1])
    TG.send(fmt_live_state(spot_now, c1h_now, sma20_now, sma50_now, K_now, K_prev, DAY.regime))

    # ---- Push boot log to GitHub so remote monitoring can see startup ----
    push_logs_to_github(label="boot")

    # ---- Main loop ----
    last_pulse_at   = 0
    last_csv_at     = 0
    last_pos_sync   = 0
    last_log_push   = time.time()   # push logs every 30 min for remote monitoring
    while True:
        try:
            # Check if /stop command was received via Telegram
            if _bot_stop_flag.is_set():
                linfo("Bot stop flag set (Telegram /stop or SIGTERM). Exiting.")
                # V2.5.20 (2026-07-14 fix): square off EVERY open position before
                # exiting. Previously this returned immediately, so a SIGTERM/stop
                # with a position open left it with no exit and no Telegram card --
                # the position just froze in state_V2_5_20.json. Paper positions are
                # closed in simulation (close_trade skips the live SELL when there is
                # no buy_order_id); live ones get a real SELL.
                for _name in ENGINE_LIST:
                    switch_engine(_name)
                    if POS.active:
                        _cur = ltp(POS.symbol) or POS.entry_premium
                        linfo(f"[SHUTDOWN][{_name}] Closing open position "
                              f"{POS.symbol} @ {_cur:.2f} before exit "
                              f"({'PAPER' if POS.is_paper else 'LIVE'}).")
                        close_trade("SHUTDOWN_SQUAREOFF", _cur)
                switch_engine("BASE")
                TG.send(fmt_eod_summary())
                WD.stop()
                return

            WD.beat()
            now = datetime.now(IST)

            # After market close - force close, EOD summary, data capture, then exit
            # V2.5.20: force-close EVERY engine's position (up to 5 independent
            # positions can be open at once); eod_sent is tracked on BASE's own
            # DAY_STATES as the shared once-a-day dedup flag (same "BASE = shared
            # scratch" convention used elsewhere in this build).
            if is_after_market_close(now):
                for _name in ENGINE_LIST:
                    switch_engine(_name)
                    if POS.active:
                        cur_ltp = ltp(POS.symbol) or POS.entry_premium
                        close_trade("EOD_FORCE_CLOSE", cur_ltp)
                switch_engine("BASE")
                if not DAY.eod_sent:
                    TG.send(fmt_eod_summary())
                    DAY.eod_sent = True
                    push_logs_to_github()
                    # V2.5.20: EOD data capture is intentionally skipped here.
                    # It writes to the SAME shared daily_option_data/<date>/
                    # directory as V2.5.19 (not version-scoped), and V2.5.19
                    # already runs it every day -- running it twice
                    # concurrently would race on identical output files for
                    # no additional data.
                    # run_eod_data_capture()
                    push_logs_to_github(label="EOD")
                    TG.send(f"🛑 <b>ORION {VERSION} shutting down.</b> See you tomorrow at 09:00 IST.")
                WD.stop()
                linfo("Market closed. Bot exiting cleanly.")
                return

            # Fresh indicator fetch (every loop iteration is fine for live)
            df1h = fetch_nifty_1h()
            df15 = fetch_nifty_15m()
            df5  = fetch_nifty_5m()
            df15_fut = fetch_nifty_fut_15m(NIFTY_FUT_TOKEN)
            df5_fut  = fetch_nifty_fut_5m(NIFTY_FUT_TOKEN)   # V2.5.19 FEATURE 2
            # 2026-07-13: publish the FUT 5m frame for countertrend_veto(), which
            # runs inside open_trade() and has no access to the loop's dataframes.
            global LAST_FUT5M
            LAST_FUT5M = df5_fut
            df1m     = fetch_nifty_1m()                      # V2.5.20: ORB opening-range
            global LAST_DF1M
            LAST_DF1M = df1m                                 # 2026-09-28: veto basis fix
            if df1h is None or df15 is None or df5 is None:
                lwarn("Data fetch returned None; skipping cycle")
                time.sleep(LOOP_SLEEP_SEC)
                continue
            spot = float(df5['close'].iloc[-1])

            # V2.5.20: bind the module-global POS/DAY to BASE's own state for all
            # the shared, non-per-engine bookkeeping below (stale-data guard,
            # straddle Telegram, position-sync) -- deterministic scratch binding,
            # same convention the stale-data guard below already uses explicitly
            # via DAY_STATES["BASE"]. Without this, DAY/POS would be left pointing
            # at whichever engine the per-engine dispatch loop (below) last
            # switched to on the PREVIOUS iteration (GAPBREAK), silently breaking
            # straddle_ref/straddle_morning_sent/etc (never propagated to all 5
            # DAY_STATES, unlike levels/regime/pivots/gap_suppress_until).
            switch_engine("BASE")

            # ---- V2.5.15 STALE DATA GUARD (2026-06-12) ----
            # Kite intermittently returns 15m frames ending hours in the past
            # (observed: bar index going backwards intraday). Acting on a stale
            # frame caused the Jun-12 13:30 PE entry into a +68pt rally (HARDSL).
            # If last bar older than 16 min: refetch once instantly; if still
            # stale: Telegram alert + block ENTRIES this cycle. Exits unaffected.
            stale_entry_block = False
            if now.hour > 9 or (now.hour == 9 and now.minute >= 32):
                try:
                    # 2026-08-31: 16 -> 20 min. A bar's LABEL is its bucket
                    # START, so a perfectly current 15m bar is already 15 min
                    # old by label the instant the next bucket opens. 16 left
                    # only ~60s of headroom, and the tick samples the new
                    # bucket a few seconds before its first 1m candle exists,
                    # so the guard fired once per bucket (08-31: 18 blocked
                    # cycles on each of Nifty and Sensex, always at :01/:16/
                    # :31/:46, always recovering on the next tick). 20 = 15
                    # (bar width) + 5 (publish/tick tolerance). The failure
                    # this guard exists for -- Jun-12, bars HOURS in the past
                    # -- is far outside 20 min and is still caught.
                    _stale_max_min = 20
                    _fresh_limit = now - timedelta(minutes=_stale_max_min)
                    def _last_bar_ts(_df):
                        if _df is None or len(_df) == 0 or 'date' not in _df.columns:
                            return None
                        _ts = _df['date'].iloc[-1]
                        if hasattr(_ts, 'to_pydatetime'):
                            _ts = _ts.to_pydatetime()
                        if _ts.tzinfo is None:
                            _ts = IST.localize(_ts)
                        return _ts
                    for _name in ("15m", "fut15"):
                        _df = df15 if _name == "15m" else df15_fut
                        _ts = _last_bar_ts(_df)
                        if _ts is None or _ts >= _fresh_limit:
                            continue
                        lwarn(f"[STALE] {_name} last bar {_ts.strftime('%H:%M')} "
                              f"(>{_stale_max_min}min old) — instant refetch")
                        _df2 = fetch_nifty_15m() if _name == "15m" \
                               else fetch_nifty_fut_15m(NIFTY_FUT_TOKEN)
                        _ts2 = _last_bar_ts(_df2)
                        # V2.5.20: use BASE's DAY_STATES as the shared scratch object
                        # for this pre-per-engine-loop bookkeeping (arbitrary but
                        # consistent choice -- `DAY` itself isn't reliably bound to
                        # anything meaningful at this point in the tick).
                        _shared_day = DAY_STATES["BASE"]
                        _can_tg = (not hasattr(_shared_day, 'stale_tg_at')) or \
                                  (time.time() - _shared_day.stale_tg_at > 600)
                        if _ts2 is not None and _ts2 >= _fresh_limit:
                            if _name == "15m":
                                df15 = _df2
                                _ir = _completed_idx(df15, now, 15)
                                K      = float(df15['K'].iloc[_ir])
                                K_prev = float(df15['K'].iloc[_ir - 1])
                                _shared_day.last_K_seen = K
                                _shared_day.last_K_prev_seen = K_prev
                            else:
                                df15_fut = _df2
                            linfo(f"[STALE] {_name} recovered on refetch "
                                  f"(last bar {_ts2.strftime('%H:%M')})")
                            if _can_tg:
                                _shared_day.stale_tg_at = time.time()
                                TG.send(f"⚠️ Stale {_name} data (last bar "
                                        f"{_ts.strftime('%H:%M')}) — recovered on "
                                        f"instant refetch. Trading normally.")
                        else:
                            stale_entry_block = True
                            lwarn(f"[STALE] {_name} STILL stale after refetch — "
                                  f"entries blocked this cycle")
                            if _can_tg:
                                _shared_day.stale_tg_at = time.time()
                                TG.send(f"🚨 <b>STALE DATA</b> {_name}: last bar "
                                        f"{_ts.strftime('%H:%M')}, refetch failed. "
                                        f"Entries blocked; exits unaffected.")
                except Exception as _se:
                    lwarn(f"[STALE] guard error: {_se}")

            # Cache for pulse
            # 2026-08-31: index via _completed_idx instead of a hardcoded -2, so
            # the first ~60s of a new bucket (forming bar not yet published)
            # reads the LAST COMPLETED bar rather than the one before it.
            # Returns -2 -- i.e. unchanged -- on every other tick.
            _i15 = _completed_idx(df15, now, 15)
            _i1h = _completed_idx(df1h, now, 60)
            c1h    = float(df1h['close'].iloc[_i1h])
            sma20  = float(df1h['SMA20'].iloc[_i1h])
            sma50  = float(df1h['SMA50'].iloc[_i1h])
            K      = float(df15['K'].iloc[_i15])
            K_prev = float(df15['K'].iloc[_i15 - 1])
            # V2.5.2: keep latest K seen for Path A in-trade flip detection.
            # V2.5.20: FLIP is scoped to the BASE engine only (matches the backtest's
            # documented simplification) -- write directly to BASE's own DAY_STATES,
            # not the ambiguous shared `DAY` (which at this point in the loop hasn't
            # been switched to any engine yet).
            DAY_STATES["BASE"].last_K_seen = K
            DAY_STATES["BASE"].last_K_prev_seen = K_prev

            # V2.5.9: record straddle reference after 9:20 AM (once per day)
            if DAY.straddle_ref is None and now.hour == 9 and now.minute >= STRADDLE_REF_MIN:
                _, _, s_ref = fetch_atm_straddle(expiry_lookup, spot)
                if s_ref:
                    DAY.straddle_ref = s_ref
                    linfo(f"[STRADDLE] Reference: ₹{s_ref:.1f} at {now.strftime('%H:%M')}")

            # V2.5.9: morning straddle Telegram at 9:45 AM
            if not DAY.straddle_morning_sent and now.hour == 9 and now.minute >= STRADDLE_MORNING_MIN:
                ce_s, pe_s, s_now = fetch_atm_straddle(expiry_lookup, spot)
                if s_now:
                    if DAY.straddle_ref and DAY.straddle_ref > 0:
                        pct = (s_now - DAY.straddle_ref) / DAY.straddle_ref * 100
                        direction = "📈 EXPANDING" if pct > 4 else ("📉 COMPRESSING" if pct < -4 else "↔️ STABLE")
                        iv_note = "High IV day — seller's market. Buyers face IV crush risk." if pct > 6 else "Normal IV — buyer entries valid."
                        TG.send(
                            f"📊 <b>STRADDLE MORNING CHECK · {now.strftime('%H:%M')}</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"   ATM: <code>{round_to_atm(spot)}</code>  |  Spot: <b>{spot:.0f}</b>\n"
                            f"   CE ₹{ce_s:.1f}  +  PE ₹{pe_s:.1f}  = <b>₹{s_now:.1f}</b>\n"
                            f"   Open ref: ₹{DAY.straddle_ref:.1f}  →  {direction} <b>{pct:+.1f}%</b>\n"
                            f"   <i>{iv_note}</i>"
                        )
                    else:
                        TG.send(f"📊 <b>STRADDLE 9:45AM</b>: CE ₹{ce_s:.1f} + PE ₹{pe_s:.1f} = <b>₹{s_now:.1f}</b>")
                    DAY.straddle_morning_sent = True

            # V2.5.9: mid-day straddle Telegram at 11:30 AM
            if not DAY.straddle_midday_sent and now.hour == STRADDLE_MIDDAY_HOUR and now.minute >= STRADDLE_MIDDAY_MIN:
                ce_s, pe_s, s_now = fetch_atm_straddle(expiry_lookup, spot)
                if s_now:
                    ref_str = f"₹{DAY.straddle_ref:.1f}" if DAY.straddle_ref else "N/A"
                    pct_str = f"{(s_now - DAY.straddle_ref) / DAY.straddle_ref * 100:+.1f}%" if DAY.straddle_ref else ""
                    TG.send(
                        f"📊 <b>STRADDLE MID-DAY · {now.strftime('%H:%M')}</b>\n"
                        f"   ATM: <code>{round_to_atm(spot)}</code>  |  Spot: <b>{spot:.0f}</b>\n"
                        f"   CE ₹{ce_s:.1f}  +  PE ₹{pe_s:.1f}  = <b>₹{s_now:.1f}</b>\n"
                        f"   vs Open: {ref_str}  {pct_str}"
                    )
                    DAY.straddle_midday_sent = True

            # ---- Position sync: detect manual exit on mStock (every 60 sec) ----
            # V2.5.20 (2026-07-08): verify using the bot's own BUY order_id, never
            # blind account-wide net_qty (see the incident writeup this replaces,
            # kept below); skip sync for the first 5 min after entry (exchange
            # settlement delay).
            if EXECUTION_BROKER == "mstock_live" and time.time() - last_pos_sync >= 60:
                last_pos_sync = time.time()
                # V2.5.20 (2026-07-20): union of EVERY engine's persisted buy/sell order-ids
                # (restart-proof: after a restart the broker's in-process registry is empty,
                # but these ids are reloaded from state) — so find_manual_sell never mistakes
                # one engine's own SELL for another engine's manual exit.
                _all_bot_ids = set()
                for _e in ENGINE_LIST:
                    switch_engine(_e)
                    if POS.buy_order_id:
                        _all_bot_ids.add(str(POS.buy_order_id))
                    _all_bot_ids.update(str(x) for x in POS.own_sell_order_ids)
                for _sync_name in ENGINE_LIST:
                    switch_engine(_sync_name)
                    if not POS.active or not POS.buy_order_id:
                        continue
                    _entry_age_sec = (datetime.now(IST) - POS.entry_time).total_seconds() if POS.entry_time else 999
                    if _entry_age_sec < 300:
                        continue  # skip sync within 5 min of entry — exchange needs time to reflect
                    try:
                        broker = _get_mstock()
                        if broker:
                            _status, _fill = broker.order_status(POS.buy_order_id)
                            if _status == "CANCELLED":
                                lwarn(f"[sync][{_sync_name}] BUY order {POS.buy_order_id} was CANCELLED — position never opened")
                                cur_ltp = ltp(POS.symbol) or POS.entry_premium
                                POS.buy_order_id = ""  # clear so close_trade won't place a SELL
                                close_trade("MANUAL_EXIT", cur_ltp)
                            elif _status == "COMPLETE":
                                # V2.5.20 (2026-07-08): detect a MANUAL exit the user placed
                                # directly at the broker (fixed/limit OR market price), and
                                # reconcile state+PnL using the REAL fill price -- never a
                                # guessed/current LTP. Cross-engine safe: excludes the UNION of
                                # every engine's buy/sell order-ids (_all_bot_ids) + the broker's
                                # in-process registry, so another engine's own trade on the same
                                # symbol is never misattributed here (see the 2026-07-06 net_qty
                                # incident below -- that failure mode is why this checks specific
                                # bot order-ids, not raw account-wide net_qty). V2.5.20 2026-07-20:
                                # no longer keys off producttype==INTRADAY (that skipped the
                                # user's own INTRADAY/MIS manual exits).
                                ms_sym = POS.ms_symbol or _mstock_option_symbol(POS.symbol)
                                _own_ids = _all_bot_ids | set(POS.own_sell_order_ids) | {POS.buy_order_id}
                                _qty = lots_for(POS.engine) * LOT_SIZE
                                _match = broker.find_manual_sell(ms_sym, _own_ids, min_qty=_qty)
                                if _match:
                                    _oid, _fill_px, _fill_qty = _match
                                    lwarn(f"[sync][{_sync_name}] Manual SELL detected on {ms_sym}: "
                                          f"order={_oid} fill={_fill_px:.2f} qty={_fill_qty} "
                                          f"(not one of this engine's own orders) — reconciling as MANUAL_EXIT")
                                    POS.own_sell_order_ids.append(_oid)  # never re-match this order again
                                    close_trade("MANUAL_EXIT", _fill_px)
                            # V2.5.20 CRITICAL FIX (2026-07-06): the old "elif COMPLETE:
                            # net = broker.net_qty(ms_sym); if net==0: manual exit" branch
                            # was REMOVED here (replaced by the find_manual_sell() branch
                            # above). broker.net_qty() returns the ACCOUNT-WIDE net position
                            # for that trading symbol -- it has no way to attribute quantity to
                            # a specific engine's own order. This build runs 5 engines that can
                            # independently BUY the SAME option symbol at the same time; that
                            # account-wide net can pass through zero from totally unrelated
                            # activity (another engine's own close, or any other order on the
                            # same symbol) while THIS engine's own lot is still genuinely open
                            # at the broker. That false read already closed two real live
                            # positions internally on 2026-07-06 (V3 and ORB, both still open
                            # at the broker with real money, both then untracked by the bot)
                            # purely because something else happened to trade the same symbol
                            # around the same time. See orion-v2520-position-sync-bug memory
                            # for the full incident, and orion-user-sentence-2026-07-08-
                            # manual-exit-fix for why find_manual_sell() replaces it instead of
                            # just leaving manual-exit detection off.
                    except Exception as e:
                        lwarn(f"[sync][{_sync_name}] position sync error: {e}")
                switch_engine("BASE")  # restore the shared scratch binding used below

            # ---- V2.5.20: per-engine independent exit/entry dispatch ----------
            # Each of the 5 engines (BASE/VWAP/FUT5VWAP/ORB/GAPBREAK) manages its
            # OWN position every tick -- no shared single-POS priority cascade,
            # no cross-engine mutual exclusion (see orion-concurrent-strategies-
            # architecture memory). switch_engine() rebinds POS/DAY so all the
            # existing (unmodified) check_exits/open_trade/Telegram code below
            # transparently operates on whichever engine is currently active.
            _entry_attempted = set()   # overlap: only the FIRST free slot per base engine attempts an entry each cycle
            for _name in SLOT_LIST:
                switch_engine(_name)
                _base = _name.split("#")[0]   # slot "VWAP#2" dispatches VWAP's signal/exit

                if POS.active:
                    check_exits(spot, expiry_lookup)
                    continue

                # slots share the base's signal-dedup; let only one free slot/base try to open per cycle
                if _base in _entry_attempted:
                    continue
                _entry_attempted.add(_base)

                _manual_cooling = (DAY.manual_exit_cooldown_until is not None and
                                   now < DAY.manual_exit_cooldown_until)
                # CB halt: in PAPER keep trading (paper-only, for full-day visibility);
                # in LIVE the halt fully stops entries (real-money safety). Customers
                # always stop at CB — enforced separately in signal_relay.py.
                # CIRCUIT_BREAKER=4 is now a GLOBAL cross-engine total (see
                # TOTAL_LOSSES_TODAY / close_trade()) -- when it trips, DAY.halted
                # is set True on every engine's DAY_STATES entry, so this per-engine
                # check (after switch_engine above) transparently reflects the
                # global halt for whichever engine is currently active.
                _cb_paper_mode = (DAY.halted and EXECUTION_BROKER == "kite_paper")
                # 2026-08-30, user explicit instruction: ORB and EXPIRY must never be
                # stopped by the cross-engine circuit breaker (or by any other engine's
                # loss count) -- they keep taking their normal signals regardless of
                # GLOBAL_HALTED / broker mode. See CHANGE_HISTORY.
                _halt_exempt = _base in ("ORB", "EXPIRY")
                _entry_allowed = (not DAY.halted or _cb_paper_mode or _halt_exempt) and not stale_entry_block and not no_new_entries_today()
                # V2.5.20 (2026-07-11, user explicit direct order): gap-suppress-until-10:15
                # REMOVED entirely, for ALL engines, not just GAPBREAK. Previously this
                # blocked every engine's entries until 10:15 IST on a big-gap day (see
                # GAP_SUPPRESS_PCT below, still computed/logged for visibility but no longer
                # used to gate anything). User's explicit instruction: no engine should be
                # suppressed from trading a gap day.
                _common_ok = _entry_allowed and not _manual_cooling

                if _base == "BASE":
                    if not (_common_ok and in_entry_window(now)):
                        continue
                    # V2.5.17 #1: morning chop gate — decide once, then stand aside all
                    # day. Scoped to BASE only (matches the backtest's
                    # orion_concurrent_engine.py, where chop_is_chop only gates BASE).
                    if CHOP_GATE_ENABLED and not DAY.chop_gate_decided:
                        _cg_dec, _cg_block, _cg_reason = morning_chop_verdict(df15_fut)
                        if _cg_dec:
                            DAY.chop_gate_decided = True
                            DAY.chop_gate_block = _cg_block
                            DAY.chop_gate_reason = _cg_reason
                            if _cg_block:
                                linfo(f"[CHOPGATE] STAND ASIDE for the day — {_cg_reason}")
                                TG.send(f"🟡 <b>Chop-gate: standing aside today</b>\n"
                                        f"   First hour {_cg_reason}\n"
                                        f"   No new entries; exits still active (V2.5.17)")
                            else:
                                linfo(f"[CHOPGATE] Clear to trade — {_cg_reason}")
                    # V2.5.18: while standing aside, re-arm if FUT breaks the first-hour
                    # range decisively in the regime direction (FUT leads spot).
                    if CHOP_GATE_ENABLED and DAY.chop_gate_block:
                        _ra_ok, _ra_reason = chop_rearm_check(df15_fut)
                        if _ra_ok:
                            DAY.chop_gate_block = False
                            DAY.chop_gate_reason = f"RE-ARMED: {_ra_reason}"
                            linfo(f"[CHOPGATE] RE-ARMED — {_ra_reason}")
                            TG.send(f"🟢 <b>Chop-gate RE-ARMED</b>\n"
                                    f"   {_ra_reason}\n"
                                    f"   Trend broke out of the first-hour range — entries live again (V2.5.18)")
                    if CHOP_GATE_ENABLED and DAY.chop_gate_block:
                        continue  # entries suppressed for the day; exits handled above
                    # V2.5.20-fix (2026-07-12): manage any pending V3 probe first --
                    # while a probe limit order is resting, BASE's one position slot
                    # is reserved for it; don't evaluate new signals until it either
                    # fills or expires.
                    if DAY.v3_probe is not None:
                        _manage_v3_probe(now, spot, expiry_lookup, _cb_paper_mode)
                        continue
                    sig = None
                    # FLIP + V2 require BULL/BEAR/TRANSITION regime
                    if regime_allows_trade(DAY.regime):
                        sig = check_flip_signal(df15, now)
                        # 2026-08-16: V2_DAILY_LOSS_CAP -- see constant definition for the
                        # backtest basis. FLIP is unaffected (checked above, independent of
                        # this cap); only V2's own fresh entries are capped.
                        if sig is None and DAY.v2_losses_today < V2_DAILY_LOSS_CAP:
                            sig = check_v2_signal(df1h, df15)
                    # V3 fires on cluster break/reject regardless of regime.
                    # V2.5.20-fix (2026-07-12): try the early 10-min partial-bar
                    # trigger first (validated: catches the move sooner without
                    # a coin-flip false-positive cost); fall back to the normal
                    # full-15m-close check if the early one doesn't fire.
                    if sig is None:
                        sig = check_v3_signal_early(df5)
                    if sig is None:
                        sig = check_v3_signal(df15)
                    # V2.5.20-fix (2026-07-12): V3 entries now go through the probe
                    # mechanism (limit buy at LTP-8, fills within 15min) instead of
                    # buying at market -- real-premium-validated positive result,
                    # Grade A+B both eligible, no grade restriction (user instruction).
                    if sig is not None and sig['engine'] == 'V3' and V3_PROBE_ENABLED:
                        _place_v3_probe(sig, spot, expiry_lookup)
                    else:
                        _apply_entry_gates_and_open(sig, spot, expiry_lookup, _cb_paper_mode)

                elif _base == "VWAP":
                    # V2.5.19 FEATURE 3: 09:15-10:15 morning exception — fires BEFORE
                    # the normal 09:45 start gate opens the regular VWAP cross check.
                    if _common_ok and MORNING_VWAP_ENABLED and not in_entry_window(now) \
                       and in_morning_vwap_window(now) \
                       and DAY_STATES["VWAP"].losses < VWAP_DAILY_LOSS_CAP:
                        _msig = check_morning_vwap15_signal(df15_fut, spot)
                        _apply_entry_gates_and_open(_msig, spot, expiry_lookup, _cb_paper_mode)
                        continue
                    if not (_common_ok and in_entry_window(now)):
                        continue
                    # 2026-08-08: VWAP-specific same-day loss cap -- see VWAP_DAILY_LOSS_CAP.
                    if DAY_STATES["VWAP"].losses >= VWAP_DAILY_LOSS_CAP:
                        continue
                    sig = check_vwap_signal(df15, expiry_lookup, spot, df15_fut, df5_fut)
                    _apply_entry_gates_and_open(sig, spot, expiry_lookup, _cb_paper_mode)

                elif _base == "FUT5VWAP":
                    if not (_common_ok and in_entry_window(now)):
                        continue
                    sig = check_fut5m_vwap_scalp_signal(df5_fut, spot)
                    _apply_entry_gates_and_open(sig, spot, expiry_lookup, _cb_paper_mode)

                elif _base == "ORB":
                    # V2.5.20 NEW. Per the backtest ("independent, bypasses every
                    # gate as originally validated") ORB does NOT go through
                    # regime/chop-gate/momentum-fade gates (already disabled anyway
                    # via *_ENABLED=False) or _apply_entry_gates_and_open -- it opens
                    # directly via open_trade with its own pre-picked strike/premium.
                    # Still respects _common_ok (CB-halt/gap-suppress/manual-cooldown)
                    # and its own 09:25-15:00 window (enforced inside check_orb_signal).
                    if not _common_ok:
                        continue
                    # V2.5.20 2026-07-12: in-day CHOPPY kill (see orb_chop_kill_check)
                    if orb_chop_kill_check(df5, df15, now):
                        continue
                    sig = check_orb_signal(df1m, df5, expiry_lookup)
                    if sig is not None:
                        open_trade(sig, spot, expiry_lookup, paper_only=_cb_paper_mode,
                                   strike_override=sig['_strike'], symbol_override=sig['_symbol'],
                                   token_override=sig['_token'], premium_override=sig['_premium'])

                elif _base == "GAPBREAK":
                    # V2.5.20 NEW. No day-type filter (see is_orb_day_sideways_live's
                    # docstring -- the filter helps ORB but hurts GAPBREAK).
                    # Root cause found 2026-07-11: gap_suppress_until (10:15 IST) blocked
                    # this whole engine from even being evaluated until 10:15 -- on
                    # 2026-07-10 the real breakout bar closed at 09:45 (24208.35, 0.35pt
                    # above the first-30m range high), exactly when this scan starts, but
                    # the gate meant the function was never called until price had already
                    # consolidated past it. gap_suppress_until removed globally (see
                    # _common_ok above) per explicit user instruction -- no special-case
                    # needed here anymore.
                    if not _common_ok:
                        continue
                    sig = check_gapbreak_signal(df5, expiry_lookup)
                    if sig is not None:
                        open_trade(sig, spot, expiry_lookup, paper_only=_cb_paper_mode,
                                   strike_override=sig['_strike'], symbol_override=sig['_symbol'],
                                   token_override=sig['_token'], premium_override=sig['_premium'])

                elif _base == "EXPIRY":
                    # V2.5.20 NEW (2026-07-26). Real-expiry-day-only, one-shot
                    # (see check_expiry_signal's own date/time gating). NOT
                    # walk-forward validated as a forward entry rule -- ships
                    # paper-only to start accruing real data. Bypasses regime/
                    # chop-gate like the other breakout engines; still
                    # respects _common_ok (CB-halt/manual-cooldown).
                    if not _common_ok:
                        continue
                    sig = check_expiry_signal(df5, expiry_lookup)
                    if sig is not None:
                        open_trade(sig, spot, expiry_lookup, paper_only=_cb_paper_mode,
                                   strike_override=sig['_strike'], symbol_override=sig['_symbol'],
                                   token_override=sig['_token'], premium_override=sig['_premium'])

            # ---- APEX independent separate-PnL SHADOW book (the user's actual method):
            # runs EVERY cycle, LTP-based paper fills only (never touches V2520's real-money
            # order flow), separate PnL. Deployed 2026-07-20 alongside the 5 live engines. ----
            switch_engine("BASE")   # bind DAY.pivots/levels (market-wide) before APEX/T5
            try:
                apex_step(spot, expiry_lookup)
            except Exception as _ae:
                lwarn(f"[APEX] step error: {_ae}")
            try:
                t5_step(spot, expiry_lookup, df15)
            except Exception as _te:
                lwarn(f"[T5] step error: {_te}")
            # ---- EXPIRY ENGINES 1&2 shadow book (2026-08-22): expiry-day
            # afternoons only, LTP/bars paper fills, separate PnL, no gates ----
            try:
                exp12_step(spot, expiry_lookup)
            except Exception as _xe:
                lwarn(f"[EXP12] step error: {_xe}")

            # ---- CSV + INDICATORS + SIGNAL log every 5 min ----
            # V2.5.20: with 5 independent positions possible at once, [INDICATORS]/
            # [SIGNAL] stay market-wide (unchanged), but [STATE] + the CSV row are
            # now written ONCE PER ENGINE (was: once, implicitly whichever engine
            # happened to be bound to the single old POS/DAY).
            if time.time() - last_csv_at >= 5 * 60:
                rsi_now  = float(df1h['RSI'].iloc[-2])       if 'RSI'       in df1h.columns and not pd.isna(df1h['RSI'].iloc[-2])       else float('nan')
                macd_l   = float(df1h['MACD_line'].iloc[-2]) if 'MACD_line' in df1h.columns and not pd.isna(df1h['MACD_line'].iloc[-2]) else float('nan')
                macd_s   = float(df1h['MACD_sig'].iloc[-2])  if 'MACD_sig'  in df1h.columns and not pd.isna(df1h['MACD_sig'].iloc[-2])  else float('nan')
                rsi_blk  = (not math.isnan(rsi_now)) and (RSI_PE_MAX <= rsi_now <= RSI_CE_MIN)
                ce_reg   = (c1h > sma20) and (sma20 > sma50)
                pe_reg   = (c1h < sma20) and (sma20 < sma50)
                k_extr_ce = k_was_extreme_live('CE', df15)
                k_extr_pe = k_was_extreme_live('PE', df15)
                k_dir    = '↑' if K > K_prev else '↓'
                macd_dir = 'bull' if (not math.isnan(macd_l) and not math.isnan(macd_s) and macd_l > macd_s) else 'bear'

                # [INDICATORS] — mirrors T10 V2.2.2 style (market-wide, not per-engine)
                _any_active = any(POSITIONS[n].active for n in ENGINE_LIST)
                linfo(
                    f"[INDICATORS] spot={spot:.1f} | "
                    f"1h: close={c1h:.1f} sma20={sma20:.1f} sma50={sma50:.1f} "
                    f"rsi={rsi_now:.1f} macd={macd_l:.2f}/{macd_s:.2f}({macd_dir}) | "
                    f"15m: K={K:.1f}{k_dir}(prev {K_prev:.1f}) | "
                    f"regime={'CE-eligible' if ce_reg else 'PE-eligible' if pe_reg else 'NEUTRAL'} "
                    f"any_active={_any_active}"
                )

                # [SIGNAL] — show each V2 CE/PE filter check individually
                ce_k_ok    = K >= STOCHRSI_CE_LO and K > K_prev
                ce_rsi_ok  = not math.isnan(rsi_now) and rsi_now > RSI_CE_MIN
                ce_macd_ok = not math.isnan(macd_l) and macd_l > macd_s
                pe_k_ok    = K <= STOCHRSI_PE_HI and K < K_prev and K >= V2_K_FLOOR_PE
                pe_rsi_ok  = not math.isnan(rsi_now) and rsi_now < RSI_PE_MAX
                pe_macd_ok = not math.isnan(macd_l) and macd_l < macd_s
                ce_macd_req = ce_macd_ok if V2_MACD_GATE_ENABLED else True
                pe_macd_req = pe_macd_ok if V2_MACD_GATE_ENABLED else True
                linfo(
                    f"[SIGNAL] "
                    f"CE: reg={ce_reg} K={ce_k_ok}(K={K:.1f}>={STOCHRSI_CE_LO},rising) "
                    f"Kextr={k_extr_ce} RSI={ce_rsi_ok}({rsi_now:.1f}>{RSI_CE_MIN}) "
                    f"MACD={ce_macd_ok}{'(gate off)' if not V2_MACD_GATE_ENABLED else ''} => {'PASS' if (ce_reg and ce_k_ok and k_extr_ce and ce_rsi_ok and ce_macd_req) else 'BLOCK'} | "
                    f"PE: reg={pe_reg} K={pe_k_ok}(K={K:.1f}<={STOCHRSI_PE_HI},falling) "
                    f"Kextr={k_extr_pe} RSI={pe_rsi_ok}({rsi_now:.1f}<{RSI_PE_MAX}) "
                    f"MACD={pe_macd_ok}{'(gate off)' if not V2_MACD_GATE_ENABLED else ''} => {'PASS' if (pe_reg and pe_k_ok and k_extr_pe and pe_rsi_ok and pe_macd_req) else 'BLOCK'}"
                )

                # [STATE] + CSV row — once per engine
                for _name in ENGINE_LIST:
                    switch_engine(_name)
                    pos_ltp = POS.last_pulse_premium if POS.active else 0
                    pos_pnl_pct = ((pos_ltp - POS.entry_premium) / POS.entry_premium * 100) if (POS.active and POS.entry_premium) else 0
                    if POS.active:
                        elapsed = int(POS.elapsed_min())
                        active_sl = max(POS.hardsl_premium, POS.tr_sl if POS.tr_armed else 0)
                        linfo(
                            f"[STATE][{_name}] {POS.side} {POS.symbol} ltp={pos_ltp:.2f} "
                            f"entry={POS.entry_premium:.2f} pnl={pos_ltp-POS.entry_premium:+.2f}({pos_pnl_pct:+.1f}%) "
                            f"sl={active_sl:.2f} peak={POS.peak_premium:.2f} "
                            f"tr_armed={POS.tr_armed} elapsed={elapsed}min"
                        )
                    csv_append([now.isoformat(), spot, c1h, sma20, sma50, rsi_now, K, K_prev,
                                DAY.regime, POS.active, POS.side, _name, POS.strike, pos_ltp, pos_pnl_pct,
                                POS.sl_current, POS.tr_armed, POS.tr_sl, POS.peak_premium,
                                DAY.losses, DAY.flips_today, DAY.halted, (rsi_blk or DAY.chop_gate_block)])
                switch_engine("BASE")  # restore the shared scratch binding
                last_csv_at = time.time()

            # ---- Pulse every 15 min ----
            if time.time() - last_pulse_at >= PULSE_INTERVAL_SEC:
                TG.send(fmt_pulse(spot, c1h, sma20, sma50, K, K_prev, DAY.regime))
                last_pulse_at = time.time()

            # ---- Push logs to GitHub every 5 min for remote monitoring ----
            if time.time() - last_log_push >= 5 * 60:
                push_logs_to_github(label="periodic")
                last_log_push = time.time()

            time.sleep(LOOP_SLEEP_SEC)

        except KeyboardInterrupt:
            linfo("Interrupted by user. Sending EOD summary and exiting.")
            try:
                TG.send("🛑 <b>Bot stopped by user.</b>")
                TG.send(fmt_eod_summary())
            except Exception:
                pass
            WD.stop()
            return
        except Exception as e:
            tb = traceback.format_exc()
            lerr(f"Main loop exception: {e}\n{tb}")
            TG.send(f"⚠️ <b>ERROR</b> Main loop: <code>{tg_escape(e)}</code>\n<i>(see log for traceback)</i>")
            time.sleep(LOOP_SLEEP_SEC)

if __name__ == "__main__":
    main()
