"""
=========================================================================
ORION V2.5.7 - PAPER TRADING BOT  (Nifty Weekly Options)
=========================================================================
Mobile-runnable single file. Mirrors V2.2.2 framework. Strategy upgraded
through V2.5.0 -> V2.5.7 per 18-month backtest on phase3_daily.pkl
(2024-09-23 -> 2026-03-24).

V2.5.6 BACKTEST RESULT (prior baseline):
  Trades 915 | Nifty pts +11,193 | PnL Rs +3,85,724 | WR 35.7%
  Max DD -1,331 pts | Red months 5/18 (72% positive)

V2.5.7 BACKTEST RESULT (Velvet Rope + Accelerated Ratchet):
  Trades ~915 | PnL Rs +5,00,048 | WR 55.4%
  Max DD -1,885 pts | Red months 10/18
  Trade-off: +Rs 1,14,324 (+29.7%) P&L / WR surge, but 2x red months.
  Protects winning trades from surrendering back to -25% HARDSL.

Improvement over V2.5.6: +Rs 1,14,324 (+29.7%) net P&L, +19.7% win rate

PAPER MODE: no real orders placed. Simulated P&L tracked via Kite LTP.

=========================================================================
STRATEGY BOX
=========================================================================
PARALLEL ENGINES (V2 priority on same-bar tiebreak; single position at a time):

  ENGINE V2  (T10/V2.2 indicator-based, fires at every 15m close)
    CE: 1h_close > 1h_SMA20  AND  15m StochRSI K >= 38  AND  K rising
    PE: 1h_close < 1h_SMA20  AND  1h_close < 1h_SMA50  AND
        15m K <= 80  AND  K falling  AND  K >= 25  (V2.5.1 PE_floor)
    Strike: ATM (round to 100). Lots: 2.

  ENGINE V3  (V2.3 cluster-based, fires at 15m close if G/R break/reject)
    Pre-computed at boot from prior day 1h: PDH/PDL/PDC + round 50/100 levels
    (+/-300 of PDC) + 20-bar swing pivots. Clustered within 20pts ->
    Grade A (>=3 source kinds) / Grade B (>=2 source kinds).
    V2.5.3: PROMOTED SINGLETONS - PDH/PDL/round_100 in +/-200 of PDC/swing
    pivots in +/-300 of PDC act as standalone Grade B if NOT in any A/B cluster.
    G = nearest A/B above PDC, R = nearest A/B below PDC.
    Regime gate (last closed 1h): only fire in BULL/BEAR/TRANSITION (skip CHOP).
    Signal: 15m bar BREAKS or REJECTS at G or R with valid candle quality.
    Strike: ATM. Lots: 2.

  ENGINE FLIP  (V2.5.2 — rejection-flip on opposite side, max 3/day)
    Path A (in-trade): elapsed >= 30min AND peak premium >= entry+15 AND
                       current premium <= entry+10 AND 15m K reversed.
                       Triggers flip immediately to opposite side at exit.
    Path B (post-exit): within 60min of any exit, if 15m K reverses direction,
                       opens flip on opposite side.
    CE -> PE flip: K_now < K_prev_15m AND 25 <= K_now <= 80
    PE -> CE flip: K_now > K_prev_15m AND K_now >= 38
    Flips do NOT increment circuit breaker. Cap: MAX_FLIPS_PER_DAY=3.
    Same-side continuation: NEVER (backtest showed -Rs 191k catastrophic).

UNIVERSAL EXIT (applies to BOTH engines):
  1. HARDSL  -25% of entry premium  (intra-bar)
  2. VELVET ROPE (V2.5.7): as soon as premium touches entry+15, lock SL at
     entry+2. Prevents winners from surrendering to -25% HARDSL.
  3. RATCHET GATE (V2.5.7): after 30min elapsed AND premium touches entry+25,
     promote SL from entry+2 to entry+15.
  4. RUNNER STEP TRAIL: every +20pts peak move -> SL ratchets up +20 (one-way).
  5. 15m option SMA8(low) close-below trail
  6. Force close 15:25 IST
  7. Circuit breaker: 4 daily NON-FLIP losses -> halt further entries

CHOP FILTER (V2.5.5):
  Block all entries (V2/V3/FLIP) when last closed 1h RSI is in [47, 53].
  This is the "indecision band" - momentum signals fail when RSI hovers
  near 50 without commitment.

NO BE ARMOR (removed in V2.5 - cost -1700pts).
NO TIME_SL (replaced by time-ratchet in V2.5).
NO SAME-SIDE FLIP CONTINUATION (rejected: -Rs 191k catastrophic).
NO SKIP_HOUR_13 (rejected: -Rs 46k; backfires by killing profitable flips).
NO SKIP_TUESDAYS (rejected: calendar-overfit; Chop C RSI band replaces it).

=========================================================================
PROGRESSIVE CHANGES (V2.2.2 production -> V2.5.5)
=========================================================================
V2.3   + V3 cluster G/R levels + ADX regime classifier
V2.4   + 15m SMA8(low) trail + ATR exits
V2.5.0 + Hybrid V2+V3 entry + time-ratchet 90min/+20/+20
V2.5.1 + V2 PE_floor=25, no CE cap, V2-priority same-bar
V2.5.2 + flip rule (Path A in-trade + Path B post-close, opposite-side only)
V2.5.3 + V3 promote singletons; HARDSL -35% -> -25%
V2.5.4 + MAX_FLIPS_PER_DAY=3 (flips 1-3 win Rs 131k; flips 4+ lose Rs 21k)
V2.5.5 + CHOP_FILTER (RSI [47,53] band block)
V2.5.6 + V3 PDC contamination fix (motivated by 2026-05-18 paper PE loss)
          Fix A: Exclude PDC from clustering sources
          Fix B: Require min 25pt buffer between G/R and PDC
          Backtest: +Rs 13,127 (+3.52%), MaxDD -19%
V2.5.7 + Velvet Rope immediate protection: SL to entry+2 when premium hits entry+15
          Accelerated Ratchet Gate: after 30min + entry+25, promote SL to entry+15
          Ratchet time window: 90min -> 30min
          Backtest: +Rs 1,14,324 (+29.7%), WR 35.7% -> 55.4%
          Trade-off: Red months 5/18 -> 10/18, MaxDD -1,331 -> -1,885

UNDISCUSSED DECISIONS: NONE.

=========================================================================
DATA PROVENANCE
=========================================================================
- Nifty 1h: kite.historical_data("NIFTY 50", 30 days back, "60minute")
  Adds: SMA20, SMA50, slopes, ADX, MACD, RSI (V2.5.5: RSI added)
- Nifty 15m: kite.historical_data("NIFTY 50", 10 days back, "15minute")
  Adds: StochRSI K
- Option 15m: kite.historical_data(option_token, 10 days back, "15minute")
- Levels: prior day's 1h H/L/C + 20-bar swing pivots + round 50/100
- Closed-bar semantics: iloc[-2] for all signal evaluation

=========================================================================
"""
import os
import sys
import time
import json
import math
import csv
import threading
import traceback
import logging
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass, field, asdict

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
    KITE_API_KEY    = credentials.KITE_API_KEY
    KITE_API_SECRET = credentials.KITE_API_SECRET
    KITE_ACCESS_TOKEN = credentials.KITE_ACCESS_TOKEN
    TELEGRAM_BOT_TOKEN = credentials.TELEGRAM_BOT_TOKEN
except (ImportError, AttributeError) as e:
    print("[FATAL] credentials.py missing or incomplete.")
    print("Required keys: KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN, TELEGRAM_BOT_TOKEN")
    sys.exit(1)

TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
if not TELEGRAM_CHAT_ID:
    try:
        from credentials import TELEGRAM_CHAT_ID as _tgcid
        TELEGRAM_CHAT_ID = _tgcid
    except ImportError:
        raise RuntimeError("TELEGRAM_CHAT_ID not set in environment or credentials.py")

# =========================================================================
# CONFIG
# =========================================================================
VERSION = "V2.5.9"
MODE    = "PAPER"   # PAPER -> no real orders placed
LOT_SIZE = 65
LOTS_PER_TRADE = 2
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
# V2.5.9: Premium entry gate
PREMIUM_MIN           = 30      # skip if option LTP < this (deep OTM)
PREMIUM_MAX           = 180     # skip if option LTP > this (IV spike entry)
# V2.5.9: Straddle monitoring (informational Telegram alerts only)
STRADDLE_REF_MIN      = 20      # record ATM straddle reference after 9:20 AM
STRADDLE_MORNING_MIN  = 45      # morning straddle Telegram at 9:45 AM
STRADDLE_MIDDAY_HOUR  = 11      # mid-day straddle Telegram
STRADDLE_MIDDAY_MIN   = 30      # at 11:30 AM

# V3 (cluster) entry
CLUSTER_RADIUS_PTS    = 20
GRADE_A_MIN_SOURCES   = 3
GRADE_B_MIN_SOURCES   = 2
SWING_LOOKBACK_BARS   = 20
SWING_PIVOT_N         = 3
ROUND_STEP_FINE       = 50
ROUND_STEP_MAJOR      = 100
ROUND_RANGE_PTS       = 300
GRADE_A_MIN_CLOSE_BEYOND = 15
GRADE_A_MIN_BODY_PCT     = 0.40
GRADE_B_MIN_BODY_PCT     = 0.60
GRADE_B_CLOSE_TOP_PCT    = 0.25
WICK_REJECT_MIN_PCT      = 0.50
WICK_REJECT_CLOSE_DIST   = 10
ADX_PERIOD            = 14
ADX_CHOP_MAX          = 20
ADX_TREND_MIN         = 25
T1_MIN_PTS, T1_MAX_PTS = 50, 100
# V2.5.3: promote singletons
V3_PROMOTE_SINGLETONS  = True
PROMOTE_ROUND_100_BAND = 200    # +/- pts from PDC for round_100 standalone promotion
PROMOTE_SWING_BAND     = ROUND_RANGE_PTS

# V2.5.6 — V3 PDC contamination fix
# Fix A: Exclude PDC from clustering sources (PDC is a reference, not a tradeable level)
# Fix B: Minimum buffer between G/R and PDC (avoid noise levels near current price)
# Validated 18-mo backtest: +Rs 13,127 (+3.52%), MaxDD -19%
V3_EXCLUDE_PDC_FROM_CLUSTERS = True
V3_MIN_BUFFER_FROM_PDC       = 25     # G must be >= PDC+25; R must be <= PDC-25

# V2.5.2: FLIP rule (opposite-side flip on 15m K reversal)
FLIP_ENABLED              = True
FLIP_PATH_A_ELAPSED_MIN   = 30    # min elapsed for Path A flip detection at exit
FLIP_PATH_A_PEAK_MIN_PTS  = 15    # peak must have reached entry + this
FLIP_PATH_A_DROP_MAX_PTS  = 10    # current LTP <= entry + this triggers Path A
FLIP_K_CE_TO_PE_MIN       = 25    # CE->PE flip: K_now >= this
FLIP_K_CE_TO_PE_MAX       = 80    # CE->PE flip: K_now <= this
FLIP_K_PE_TO_CE_MIN       = 38    # PE->CE flip: K_now >= this
MAX_FLIPS_PER_DAY         = 3     # V2.5.4: cap (flips 1-3 win; 4+ lose)
FLIP_PATH_B_WATCH_MIN     = 60    # post-exit minutes to keep watching for flip

# V2.5.5 chop filter removed in V2.5.9 — replaced by RSI directional gate in check_v2_signal

# ---- Universal exit ----
HARDSL_PCT            = 0.25    # -25% on premium  (V2.5.3 locked)
SMA_TRAIL_PERIOD      = 8       # SMA(8, low) on option 15m
# V2.5.9 exit params (confirmed from 18-month backtest: ₹+6,70,425, WR 66.9%)
RATCHET_TIME_MIN      = 20      # ratchet gate window: 20min (was 30)
RATCHET_INITIAL_PTS   = 12      # velvet rope trigger: premium hits entry+12 (was 15)
RATCHET_STEP_PTS      = 25      # runner trail: SL steps +25 per +25pts peak (was 20)
CIRCUIT_BREAKER       = 3       # daily NON-FLIP losses before halt (was 4)
FORCE_CLOSE_HOUR      = 15
FORCE_CLOSE_MIN       = 25

# ---- Trade window ----
ENTRY_START_HOUR      = 9
ENTRY_START_MIN       = 45     # earliest entry after open
ENTRY_END_HOUR        = 14
ENTRY_END_MIN         = 30     # latest entry
GAP_SUPPRESS_PCT      = 0.01
GAP_SUPPRESS_UNTIL_HOUR = 10
GAP_SUPPRESS_UNTIL_MIN  = 15

# ---- Operating ----
LOOP_SLEEP_SEC          = 30
WATCHDOG_TIMEOUT_SEC    = 300
PULSE_INTERVAL_SEC      = 15 * 60   # 15-min Telegram pulse
AFTER_HOURS_PULSE_MIN   = 30        # send "alive" pulse this often after market close

# ---- File outputs ----
RUN_TS  = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
CSV_FN  = f"Nifty_BarLevel_{VERSION.replace('.','_')}_{RUN_TS}.csv"
LOG_FN  = f"Nifty_FlightRecorder_{VERSION.replace('.','_')}_{RUN_TS}.log"
STATE_FN = f"state_{VERSION.replace('.','_')}.json"

# =========================================================================
# LOGGING
# =========================================================================
logging.basicConfig(
    filename=LOG_FN,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
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
            payload = {"chat_id": self.chat_id, "text": msg}
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
# KITE CLIENT
# =========================================================================
kite = KiteConnect(api_key=KITE_API_KEY)
kite.set_access_token(KITE_ACCESS_TOKEN)

NIFTY_INSTRUMENT_TOKEN = 256265   # NSE NIFTY 50

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
    insts = kite_safe(kite.instruments, "NFO")
    if not insts:
        raise RuntimeError("Could not fetch NFO instruments")
    today = datetime.now(IST).date()
    nifty_options = [i for i in insts
                     if i["name"] == "NIFTY"
                     and i["instrument_type"] in ("CE", "PE")
                     and i["expiry"] >= today]
    if not nifty_options:
        raise RuntimeError("No Nifty options found")
    expiries = sorted({i["expiry"] for i in nifty_options})
    target_expiry = expiries[0]
    strikes = sorted({i["strike"] for i in nifty_options if i["expiry"] == target_expiry})
    # Build lookup: (strike, side) -> (symbol, token)
    lookup = {}
    for i in nifty_options:
        if i["expiry"] == target_expiry:
            key = (i["strike"], i["instrument_type"])
            lookup[key] = (f"NFO:{i['tradingsymbol']}", i["instrument_token"])
    return target_expiry, strikes, lookup

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
        kind = 'round_100' if p % 100 == 0 else 'round_50'
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

def fetch_nifty_15m(days_back=10):
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(NIFTY_INSTRUMENT_TOKEN, frm, now, "15minute")
    if not rows: return None
    df = pd.DataFrame(rows)
    df['K'] = stochrsi_k(df['close'])
    return df

def fetch_nifty_5m(days_back=3):
    now = datetime.now(IST)
    frm = now - timedelta(days=days_back)
    rows = historical(NIFTY_INSTRUMENT_TOKEN, frm, now, "5minute")
    if not rows: return None
    return pd.DataFrame(rows)

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

def compute_option_vwap(token: int) -> Optional[float]:
    """Today's VWAP for an option using 5m bars with real volume. Informational only."""
    try:
        now = datetime.now(IST)
        frm = now.replace(hour=9, minute=15, second=0, microsecond=0)
        rows = historical(token, frm, now, "5minute")
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

def sma8_low_of_option(df_opt_15m):
    """Compute current SMA(8, low) from closed option 15m bars (iloc[-2] backwards)."""
    if df_opt_15m is None or len(df_opt_15m) < SMA_TRAIL_PERIOD + 1:
        return None
    # closed bars only -> exclude the still-forming last bar
    closed = df_opt_15m.iloc[:-1]
    if len(closed) < SMA_TRAIL_PERIOD:
        return None
    return float(closed['low'].iloc[-SMA_TRAIL_PERIOD:].mean())

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
    last_pulse_premium: float = 0.0
    sma8_last_bar_ts: Optional[datetime] = None  # FIX1: last 15m bar ts evaluated for SMA8 trail
    entry_vwap: Optional[float] = None          # V2.5.9+: option VWAP at entry (informational)

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

POS = TradeState()

# Daily accounting
@dataclass
class DailyState:
    losses: int = 0                  # NON-FLIP losses only (V2.5.3: CB=4, flips excluded)
    trades_today: List[dict] = field(default_factory=list)
    halted: bool = False
    levels: dict = None
    regime: str = "INSUFFICIENT"
    gap_suppress_until: Optional[datetime] = None
    fired_levels: set = field(default_factory=set)
    # V2.5.2/4 — flip tracking
    flips_today: int = 0
    last_exit: Optional[dict] = None  # {'side','entry','peak','elapsed_min','exit_time','engine'}
    # Last 15m K seen (for cross-bar K-reversal detection in flip rule)
    last_K_seen: Optional[float] = None
    last_K_prev_seen: Optional[float] = None
    # Persisted flags
    eod_sent: bool = False
    # V2.5.9: straddle monitoring
    straddle_ref: Optional[float] = None
    straddle_morning_sent: bool = False
    straddle_midday_sent: bool = False

    def reset(self):
        self.losses = 0
        self.trades_today = []
        self.halted = False
        self.levels = None
        self.regime = "INSUFFICIENT"
        self.gap_suppress_until = None
        self.fired_levels = set()
        self.flips_today = 0
        self.last_exit = None
        self.last_K_seen = None
        self.last_K_prev_seen = None
        self.eod_sent = False
        self.straddle_ref = None
        self.straddle_morning_sent = False
        self.straddle_midday_sent = False

DAY = DailyState()

# =========================================================================
# STATE PERSISTENCE (atomic JSON)
# =========================================================================
def save_state():
    try:
        snap = {"pos": POS.to_dict(),
                "day_losses": DAY.losses,
                "day_halted": DAY.halted,
                "fired_levels": list(DAY.fired_levels),
                "trades_today": DAY.trades_today}
        tmp = STATE_FN + ".tmp"
        with open(tmp, "w") as f:
            json.dump(snap, f, default=str)
        os.replace(tmp, STATE_FN)
    except Exception as e:
        lwarn(f"save_state failed: {e}")

def load_state():
    if not os.path.exists(STATE_FN): return
    try:
        with open(STATE_FN) as f:
            snap = json.load(f)
        if snap.get("pos", {}).get("active"):
            for k, v in snap["pos"].items():
                if k == "entry_time" and v:
                    v = datetime.fromisoformat(v).astimezone(IST)
                setattr(POS, k, v)
        DAY.losses = snap.get("day_losses", 0)
        DAY.halted = snap.get("day_halted", False)
        DAY.fired_levels = set(snap.get("fired_levels", []))
        DAY.trades_today = snap.get("trades_today", [])
        linfo(f"[STATE] Loaded prior state. POS.active={POS.active} losses={DAY.losses}")
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
    return (
        f"🚀🚀🚀 <b>ORION {VERSION} BOOT</b> 🚀🚀🚀\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Mode:</i> <b>{MODE}</b>\n"
        f"<i>Boot time:</i> {now_str}\n"
        f"<i>Target expiry:</i> <b>{tg_escape(target_expiry)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>V3 LEVELS (prior day 1h)</b>\n"
        f"   PDH: <code>{levels['pdh']:.2f}</code>  |  PDL: <code>{levels['pdl']:.2f}</code>  |  PDC: <code>{levels['pdc']:.2f}</code>\n"
        f"   🟢 G (resistance above PDC): {g_str}\n"
        f"   🔴 R (support below PDC):    {r_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡 <b>EXIT PARAMS</b>\n"
        f"   🛑 HARDSL: <b>-{int(HARDSL_PCT*100)}%</b> on premium\n"
        f"   📉 Trail: 15m option SMA({SMA_TRAIL_PERIOD}, low)\n"
        f"   ⏱️ Ratchet: after {RATCHET_TIME_MIN}min, arm entry+{RATCHET_INITIAL_PTS}, step +{RATCHET_STEP_PTS}\n"
        f"   ⛔ Force close: {FORCE_CLOSE_HOUR:02d}:{FORCE_CLOSE_MIN:02d} IST\n"
        f"   🔁 Flip cap: {MAX_FLIPS_PER_DAY}/day  |  Circuit breaker: {CIRCUIT_BREAKER} non-flip losses\n"
        f"   🌊 RSI gate: CE entry needs RSI>{RSI_CE_MIN}, PE needs RSI<{RSI_PE_MAX}\n"
        f"   🔧 V3 PDC fix: exclude PDC from clusters; min {V3_MIN_BUFFER_FROM_PDC}pt buffer for G/R\n"
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
    if POS.active:
        ltp_now = POS.last_pulse_premium or POS.entry_premium
        pct = (ltp_now - POS.entry_premium) / POS.entry_premium * 100
        elapsed = int(POS.elapsed_min())
        side_em = "🟢" if POS.side == "CE" else ("🔴" if POS.side == "PE" else "🟠")
        engine_em = {"V2":"⚙️", "V3":"🎯", "FLIP":"🔄"}.get(POS.engine, "")
        pnl_em = "📈" if pct > 0 else "📉" if pct < 0 else "➖"
        # Ratchet / Velvet Rope status
        if POS.tr_armed:
            sl_offset = POS.tr_sl - POS.entry_premium
            if sl_offset <= 2:
                tr_str = f"🎯 <b>Velvet Rope</b> @ SL=<code>{POS.tr_sl:.2f}</code> (entry+2, awaiting 30min gate)"
            else:
                tr_str = f"<b>RATCHET ARMED</b> @ SL=<code>{POS.tr_sl:.2f}</code> (+{sl_offset:.0f}pts)"
        else:
            tr_str = f"watching (velvet rope arms at entry+{RATCHET_INITIAL_PTS} = <code>{POS.entry_premium+RATCHET_INITIAL_PTS:.2f}</code>)"
        active_sl = max(POS.hardsl_premium, POS.tr_sl if POS.tr_armed else 0)
        cur_vwap = compute_option_vwap(POS.token)
        vwap_pulse = ""
        if cur_vwap:
            v_diff = ltp_now - cur_vwap
            v_pos = "above" if v_diff >= 0 else "below"
            vwap_pulse = f"\n   📊 VWAP: <code>{cur_vwap:.2f}</code>  (LTP {abs(v_diff):.1f}pts {v_pos})"
        head += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{side_em} <b>ACTIVE</b> {engine_em} <b>{POS.side}</b> {tg_escape(POS.symbol)}\n"
            f"   {pnl_em} LTP: <b>{ltp_now:.2f}</b> ({pct:+.1f}%) | Entry: <code>{POS.entry_premium:.2f}</code>\n"
            f"   🎯 Target: <code>{POS.declared_target_premium:.2f}</code>  "
            f"🛑 SL: <b>{active_sl:.2f}</b>\n"
            f"   🚀 Peak: <code>{POS.peak_premium:.2f}</code>  ⏱️ Elapsed: <b>{elapsed}min</b>\n"
            f"   Ratchet: {tr_str}{vwap_pulse}\n"
            f"   🔁 Flips: {DAY.flips_today}/{MAX_FLIPS_PER_DAY} · ⛔ Losses: {DAY.losses}/{CIRCUIT_BREAKER}"
        )
    else:
        flips_str  = f"🔁 Flips: {DAY.flips_today}/{MAX_FLIPS_PER_DAY}"
        losses_str = f"⛔ Non-flip losses: {DAY.losses}/{CIRCUIT_BREAKER}"
        head += f"   <i>No active position.</i>  {flips_str}  ·  {losses_str}"
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

    declared_str = (f"<b>+25%</b> premium = <code>{POS.declared_target_premium:.2f}</code>"
                    if POS.engine in ("V2", "FLIP")
                    else f"spot <code>{POS.declared_target_spot:.0f}</code> (cluster T1)")
    entry_t = POS.entry_time.strftime('%H:%M:%S') if POS.entry_time else "—"

    vwap_line = ""
    if POS.entry_vwap:
        diff = POS.entry_premium - POS.entry_vwap
        pos_neg = "above" if diff >= 0 else "below"
        vwap_line = f"\n   📊 <b>VWAP</b>: <code>{POS.entry_vwap:.2f}</code>  (entry <b>{abs(diff):.1f}pts {pos_neg}</b> VWAP)"

    return (
        f"{banner}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{side_color} <b>{tg_escape(POS.symbol)}</b>  @  <b>₹{POS.entry_premium:.2f}</b>\n"
        f"   Engine: <b>{engine}</b> · {tg_escape(POS.engine_detail)}\n"
        f"   ATM Strike: <code>{POS.strike}</code>  |  Spot: <code>{POS.entry_spot:.2f}</code>\n"
        f"   ⏰ Entry time: <b>{entry_t}</b>\n"
        f"   Trigger: <code>{POS.trigger_value:.2f}</code>{vwap_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Target</b> (declared): {declared_str}\n"
        f"🛑 <b>HARDSL</b>: <code>{POS.hardsl_premium:.2f}</code>  (-{int(HARDSL_PCT*100)}%)\n"
        f"📉 <b>Trail</b>: 15m close &lt; SMA({SMA_TRAIL_PERIOD}, low)\n"
        f"🎯 <b>Velvet Rope</b>: SL → entry+2 when premium touches entry+{RATCHET_INITIAL_PTS}\n"
        f"⏱️ <b>Ratchet Gate</b>: after {RATCHET_TIME_MIN}min + entry+25 → SL promoted to entry+15\n"
        f"📈 <b>Runner Trail</b>: SL ratchets +{RATCHET_STEP_PTS}pts per +{RATCHET_STEP_PTS}pts peak\n"
        f"⛔ <b>Force close</b>: {FORCE_CLOSE_HOUR:02d}:{FORCE_CLOSE_MIN:02d} IST\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Actual exit driven by HARDSL / Velvet Rope / Ratchet / Trail / Flip-rule.</i>"
    )

def fmt_exit(reason, exit_price, pnl_per_share):
    elapsed = int(POS.elapsed_min())
    pct = pnl_per_share / POS.entry_premium * 100 if POS.entry_premium else 0
    rs  = pnl_per_share * LOT_SIZE * LOTS_PER_TRADE
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
        f"{banner}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{outcome} <b>{tg_escape(reason)}</b>\n"
        f"{side_color} {POS.side} {tg_escape(POS.symbol)} @ <b>₹{exit_price:.2f}</b>\n"
        f"   Engine: <b>{POS.engine}</b> · Entry: <code>{POS.entry_premium:.2f}</code>{vwap_exit}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 PnL/share: <b>{pnl_per_share:+.2f}</b> ({pct:+.1f}%)\n"
        f"💵 PnL: <b>₹{rs:+,.0f}</b>  ({LOTS_PER_TRADE} lots × {LOT_SIZE})\n"
        f"🚀 Peak premium: <code>{POS.peak_premium:.2f}</code>\n"
        f"⏱️ Duration: <b>{elapsed} min</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔁 Flips today: <b>{DAY.flips_today}/{MAX_FLIPS_PER_DAY}</b>  |  "
        f"⛔ Non-flip losses: <b>{DAY.losses}/{CIRCUIT_BREAKER}</b>"
    )

def fmt_eod_summary():
    n = len(DAY.trades_today)
    ce = [t for t in DAY.trades_today if t['side']=='CE']
    pe = [t for t in DAY.trades_today if t['side']=='PE']
    ce_w = sum(1 for t in ce if t['pnl']>0); ce_l = sum(1 for t in ce if t['pnl']<0)
    pe_w = sum(1 for t in pe if t['pnl']>0); pe_l = sum(1 for t in pe if t['pnl']<0)
    total_pnl = sum(t['pnl'] for t in DAY.trades_today)
    total_rs = total_pnl * LOT_SIZE * LOTS_PER_TRADE
    wr = (ce_w + pe_w) / n * 100 if n else 0
    reasons = {}
    for t in DAY.trades_today:
        reasons[t['reason']] = reasons.get(t['reason'], 0) + 1
    by_engine = {}
    for t in DAY.trades_today:
        by_engine.setdefault(t['engine'], {'n':0, 'pnl':0})
        by_engine[t['engine']]['n']  += 1
        by_engine[t['engine']]['pnl'] += t['pnl']
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    best  = max(DAY.trades_today, key=lambda t: t['pnl']) if DAY.trades_today else None
    worst = min(DAY.trades_today, key=lambda t: t['pnl']) if DAY.trades_today else None

    overall_em = "🟢" if total_rs > 0 else "🔴" if total_rs < 0 else "⚪"
    parts = [
        f"📋📋 <b>EOD SUMMARY</b> {today_str}  ·  ORION {VERSION} ({MODE}) 📋📋",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"{overall_em} <b>Net PnL: ₹{total_rs:+,.0f}</b>  ({total_pnl:+.2f}/share, WR {wr:.1f}%)",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Total trades: <b>{n}</b>",
        f"   🟢 CE: {len(ce)} (W:{ce_w} L:{ce_l})",
        f"   🔴 PE: {len(pe)} (W:{pe_w} L:{pe_l})",
        f"   🔁 Flips: <b>{DAY.flips_today}/{MAX_FLIPS_PER_DAY}</b>",
        f"   ⛔ Non-flip losses: <b>{DAY.losses}/{CIRCUIT_BREAKER}</b>",
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
    macd_line = df1h['MACD_line'].iloc[-2] if 'MACD_line' in df1h.columns else None
    macd_sig  = df1h['MACD_sig'].iloc[-2]  if 'MACD_sig'  in df1h.columns else None
    if macd_line is not None and macd_sig is not None and \
       not pd.isna(macd_line) and not pd.isna(macd_sig):
        macd_line = float(macd_line); macd_sig = float(macd_sig)
        if sig_ce and macd_line <= macd_sig: sig_ce = False
        if sig_pe and macd_line >= macd_sig: sig_pe = False

    if sig_ce and sig_pe: return None
    if sig_ce: return {'engine':'V2','side':'CE','detail':f'K={K:.1f}↑ RSI={rsi_val:.1f} MACD✓','trigger':sma20}
    if sig_pe: return {'engine':'V2','side':'PE','detail':f'K={K:.1f}↓ RSI={rsi_val:.1f} MACD✓','trigger':sma20}
    return None

def check_v3_signal(df15m_nifty):
    """V3 entry: cluster G/R break/reject on last closed 15m bar. Returns dict or None."""
    if df15m_nifty is None or len(df15m_nifty) < 2: return None
    if DAY.levels is None: return None
    if not regime_allows_trade(DAY.regime): return None
    bar15_closed = df15m_nifty.iloc[-2]
    bar = {'open':float(bar15_closed['open']),'high':float(bar15_closed['high']),
           'low':float(bar15_closed['low']),'close':float(bar15_closed['close'])}
    for role, lvl_obj in [('G', DAY.levels['G']), ('R', DAY.levels['R'])]:
        if lvl_obj is None: continue
        if lvl_obj['center'] in DAY.fired_levels: continue
        sig = detect_v3_signal_on_bar(bar, lvl_obj, role)
        if sig is None: continue
        side = 'CE' if 'CE' in sig['kind'] else 'PE'
        detail = f"Grade {sig['grade']} {role}-cluster {sig['kind'].replace('_','-')} at {lvl_obj['center']:.0f}"
        target = compute_targets(lvl_obj, side, DAY.levels['all_clusters'])
        return {'engine':'V3','side':side,'detail':detail,'trigger':lvl_obj['center'],
                'level_obj':lvl_obj,'target_spot':target,'kind':sig['kind']}
    return None


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
# OPEN / CLOSE  (PAPER mode - no real orders)
# =========================================================================
def open_trade(sig, spot, expiry_lookup):
    """Open a paper trade. sig has keys: engine, side, detail, trigger, [level_obj, target_spot]."""
    side = sig['side']
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
    # V2.5.9: premium gate — avoid deep OTM and IV-spike entries
    if not (PREMIUM_MIN <= cur_ltp <= PREMIUM_MAX):
        lwarn(f"Premium {cur_ltp:.2f} outside gate [{PREMIUM_MIN},{PREMIUM_MAX}]; skipping entry")
        return False
    POS.active        = True
    POS.engine        = sig['engine']
    POS.engine_detail = sig['detail']
    POS.side          = side
    POS.strike        = strike
    POS.symbol        = symbol
    POS.token         = token
    POS.entry_time    = datetime.now(IST)
    POS.entry_premium = cur_ltp
    POS.entry_spot    = spot
    POS.trigger_value = sig['trigger']
    POS.peak_premium  = cur_ltp
    POS.hardsl_premium = cur_ltp * (1 - HARDSL_PCT)
    POS.sl_current     = POS.hardsl_premium
    POS.tr_armed       = False
    POS.tr_sl          = 0.0
    if sig['engine'] == 'V2':
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
    save_state()
    msg = fmt_entry()
    linfo(f"ENTRY: {POS.symbol} @ {cur_ltp:.2f}  engine={POS.engine}  detail={POS.engine_detail}"
          f"{f' flips_today={DAY.flips_today}/{MAX_FLIPS_PER_DAY}' if sig['engine']=='FLIP' else ''}")
    TG.send(msg)
    return True

def close_trade(reason, exit_price):
    if not POS.active: return
    pnl_per_share = exit_price - POS.entry_premium
    is_flip = (POS.engine == 'FLIP')
    msg = fmt_exit(reason, exit_price, pnl_per_share)
    DAY.trades_today.append({
        'symbol': POS.symbol, 'side': POS.side, 'engine': POS.engine,
        'entry': POS.entry_premium, 'exit': exit_price, 'pnl': pnl_per_share,
        'reason': reason, 'elapsed_min': POS.elapsed_min(),
        'entry_time': POS.entry_time.strftime("%H:%M:%S") if POS.entry_time else "",
    })
    # V2.5.3: only NON-FLIP losses count toward circuit breaker
    if pnl_per_share < 0 and not is_flip:
        DAY.losses += 1
        if DAY.losses >= CIRCUIT_BREAKER:
            DAY.halted = True
            TG.send(f"⛔⛔⛔ <b>HALT — Circuit Breaker</b> ⛔⛔⛔\n"
                    f"{DAY.losses} non-flip losses today. No more entries.")
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
    linfo(f"EXIT: {POS.symbol} @ {exit_price:.2f} reason={reason} pnl/sh={pnl_per_share:+.2f}"
          f" is_flip={is_flip} losses={DAY.losses}/{CIRCUIT_BREAKER}")
    TG.send(msg)
    # Reset
    POS.active = False
    POS.engine = ""; POS.engine_detail = ""
    POS.side = ""; POS.strike = 0; POS.symbol = ""; POS.token = 0
    POS.entry_time = None
    POS.entry_premium = 0.0; POS.peak_premium = 0.0
    POS.hardsl_premium = 0.0; POS.sl_current = 0.0
    POS.tr_armed = False; POS.tr_sl = 0.0
    POS.declared_target_premium = 0.0; POS.declared_target_spot = None
    POS.entry_vwap = None
    save_state()

# =========================================================================
# EXIT CHECKS  (called every loop iteration when POS.active)
# =========================================================================
def check_exits(spot):
    """Check all exit conditions in priority order. Returns True if closed."""
    if not POS.active: return False
    cur_ltp = ltp(POS.symbol)
    if cur_ltp is None or cur_ltp <= 0:
        return False
    POS.last_pulse_premium = cur_ltp
    POS.update_peak(cur_ltp)

    now = datetime.now(IST)

    # V2.5.2 PATH A: in-trade flip detection
    # Conditions: elapsed >= 30, peak >= entry+15, current <= entry+10, AND 15m K reversed
    # If met, force-close with FLIP_TO_X reason. Main loop will catch K-reversal via
    # check_flip_signal in the next iteration and open opposite-side flip.
    if FLIP_ENABLED and is_path_a_eligible() and DAY.flips_today < MAX_FLIPS_PER_DAY:
        # Check K reversal via cached values in DAY (most recent 15m K vs prior K)
        # Note: actual K check happens in main loop; here we just need the K direction
        # to be opposite the position's direction expectation
        K_now    = DAY.last_K_seen
        K_prev   = DAY.last_K_prev_seen
        k_reversed = False
        if K_now is not None and K_prev is not None:
            if POS.side == 'CE' and K_now < K_prev and FLIP_K_CE_TO_PE_MIN <= K_now <= FLIP_K_CE_TO_PE_MAX:
                k_reversed = True
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
        close_trade(f"HARDSL_-{int(HARDSL_PCT*100)}pct", POS.hardsl_premium)
        return True

    elapsed = POS.elapsed_min()

    # 3a. VELVET ROPE — immediate capital protection
    # As soon as premium touches entry+15, lock SL at entry+2 (near break-even).
    # This prevents winning trades from surrendering back to the -25% HARDSL.
    if (not POS.tr_armed) and POS.peak_premium >= POS.entry_premium + RATCHET_INITIAL_PTS:
        POS.tr_armed = True
        POS.tr_sl    = POS.entry_premium + 2
        TG.send(f"🎯🔒 <b>Velvet Rope ARMED</b> · {POS.side}\n"
                f"   Premium hit entry+{RATCHET_INITIAL_PTS} → SL locked at entry+2\n"
                f"   SL = <code>{POS.tr_sl:.2f}</code>  |  Peak: <code>{POS.peak_premium:.2f}</code>")
        save_state()
        if cur_ltp <= POS.tr_sl:
            close_trade("VELVET_ROPE_BE_SCRATCH", POS.tr_sl)
            return True

    # 3b. ACCELERATED RATCHET GATE — upgrade SL from entry+2 to entry+15 after 30min
    # Once 30min elapsed AND premium confirms +25, promote the velvet rope floor.
    if POS.tr_armed and POS.tr_sl == (POS.entry_premium + 2) and elapsed >= RATCHET_TIME_MIN:
        if POS.peak_premium >= POS.entry_premium + 25:
            old_sl = POS.tr_sl
            POS.tr_sl = POS.entry_premium + 15
            TG.send(f"⏱️🚀 <b>Ratchet Gate UPGRADED</b> on {POS.side}\n"
                    f"   30min elapsed + premium confirmed +25pts\n"
                    f"   SL: <code>{old_sl:.2f}</code> → <code>{POS.tr_sl:.2f}</code> (+15pts)")
            save_state()
            if cur_ltp <= POS.tr_sl:
                close_trade("RATCHET_GATE_+15", POS.tr_sl)
                return True

    # 3c. RUNNER STEP SCALE TRAIL — ratchet SL up by 20pts per +20pts peak move
    if POS.tr_armed:
        new_sl = POS.tr_sl
        while POS.peak_premium >= new_sl + RATCHET_STEP_PTS:
            new_sl += RATCHET_STEP_PTS
        if new_sl > POS.tr_sl:
            old_sl = POS.tr_sl
            POS.tr_sl = new_sl
            TG.send(f"⏱️📈 <b>Ratchet stepped up</b> on {POS.side}\n"
                    f"   SL: <code>{old_sl:.2f}</code> → <code>{POS.tr_sl:.2f}</code> (+{int(POS.tr_sl-POS.entry_premium)}pts)\n"
                    f"   Peak: <code>{POS.peak_premium:.2f}</code>")
            save_state()
        if cur_ltp <= POS.tr_sl:
            pts = int(POS.tr_sl - POS.entry_premium)
            close_trade(f"RATCHET_+{pts}", POS.tr_sl)
            return True

    # 4. SMA8(low) trail - check exactly once per 15m bar close
    # FIX1: use bar timestamp instead of wall-clock modulo to avoid missing the window
    df_opt = fetch_option_15m(POS.token)
    if df_opt is not None and len(df_opt) >= SMA_TRAIL_PERIOD + 1:
        last_bar_ts = df_opt.index[-2] if hasattr(df_opt.index, '__getitem__') else df_opt['date'].iloc[-2] \
                      if 'date' in df_opt.columns else None
        if last_bar_ts is not None and last_bar_ts != POS.sma8_last_bar_ts:
            POS.sma8_last_bar_ts = last_bar_ts
            sma8L = sma8_low_of_option(df_opt)
            last_closed_15m_c = float(df_opt['close'].iloc[-2])
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
def in_entry_window(now):
    start = now.replace(hour=ENTRY_START_HOUR, minute=ENTRY_START_MIN, second=0, microsecond=0)
    end   = now.replace(hour=ENTRY_END_HOUR,   minute=ENTRY_END_MIN,   second=0, microsecond=0)
    return start <= now <= end

def is_after_market_close(now):
    end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return now > end

def main():
    csv_init()
    load_state()
    wd_thread = threading.Thread(target=WD.run, daemon=True)
    wd_thread.start()

    # ---- Resolve expiry + strikes ----
    target_expiry, strikes, expiry_lookup = resolve_expiry_and_strikes()
    linfo(f"[BOOT] Expiry: {target_expiry}, {len(strikes)} strikes, {len(expiry_lookup)} option contracts")

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
    else:
        lwarn(f"Insufficient prior 1h history ({len(df1h_prior)} rows); V3 disabled today")
        DAY.levels = None
        DAY.regime = "INSUFFICIENT"

    # ---- Gap suppression check ----
    if df5 is not None and len(df5) > 0 and DAY.levels is not None:
        today_open = float(df5['open'].iloc[0])
        pdc = DAY.levels['pdc']
        gap = (today_open / pdc) - 1
        if abs(gap) > GAP_SUPPRESS_PCT:
            DAY.gap_suppress_until = datetime.now(IST).replace(
                hour=GAP_SUPPRESS_UNTIL_HOUR, minute=GAP_SUPPRESS_UNTIL_MIN, second=0, microsecond=0)
            linfo(f"[GAP] {gap*100:+.2f}% gap; suppressing entries until {DAY.gap_suppress_until.strftime('%H:%M')}")

    # ---- Boot Telegram ----
    TG.send(fmt_boot(target_expiry, DAY.levels))

    # ---- Live state + first pulse ----
    c1h_now    = float(df1h['close'].iloc[-2])
    sma20_now  = float(df1h['SMA20'].iloc[-2])
    sma50_now  = float(df1h['SMA50'].iloc[-2])
    K_now      = float(df15['K'].iloc[-2])
    K_prev     = float(df15['K'].iloc[-3])
    spot_now   = float(df5['close'].iloc[-1])
    TG.send(fmt_live_state(spot_now, c1h_now, sma20_now, sma50_now, K_now, K_prev, DAY.regime))

    # ---- Main loop ----
    last_pulse_at = 0
    last_csv_at = 0
    while True:
        try:
            WD.beat()
            now = datetime.now(IST)

            # After market close - send periodic alive pulse + EOD once
            if is_after_market_close(now):
                if POS.active:
                    cur_ltp = ltp(POS.symbol) or POS.entry_premium
                    close_trade("EOD_FORCE_CLOSE", cur_ltp)
                if not DAY.eod_sent:
                    TG.send(fmt_eod_summary())
                    TG.send(f"🛑 <b>ORION {VERSION} shutting down.</b> See you tomorrow at 09:00 IST.")
                    DAY.eod_sent = True
                WD.stop()
                linfo("Market closed. Bot exiting cleanly.")
                return

            # Fresh indicator fetch (every loop iteration is fine for live)
            df1h = fetch_nifty_1h()
            df15 = fetch_nifty_15m()
            df5  = fetch_nifty_5m()
            if df1h is None or df15 is None or df5 is None:
                lwarn("Data fetch returned None; skipping cycle")
                time.sleep(LOOP_SLEEP_SEC)
                continue
            spot = float(df5['close'].iloc[-1])

            # Cache for pulse
            c1h    = float(df1h['close'].iloc[-2])
            sma20  = float(df1h['SMA20'].iloc[-2])
            sma50  = float(df1h['SMA50'].iloc[-2])
            K      = float(df15['K'].iloc[-2])
            K_prev = float(df15['K'].iloc[-3])
            # V2.5.2: keep latest K seen for Path A in-trade flip detection
            DAY.last_K_seen = K
            DAY.last_K_prev_seen = K_prev

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

            # ---- ACTIVE TRADE: check exits ----
            if POS.active:
                check_exits(spot)
            else:
                # ---- ENTRY DECISION: flip -> V2 -> V3 ----
                if not DAY.halted and in_entry_window(now) and \
                   (DAY.gap_suppress_until is None or now >= DAY.gap_suppress_until):
                    # Skip if regime is CHOP/INSUFFICIENT (same gate as backtest)
                    if not regime_allows_trade(DAY.regime):
                        pass
                    else:
                        # V2.5.2/4: FLIP check first (Path B post-exit watch)
                        sig = check_flip_signal(df15, now)
                        if sig is None:
                            # V2 priority on same-bar tiebreak
                            sig = check_v2_signal(df1h, df15)
                            if sig is None:
                                sig = check_v3_signal(df15)
                        if sig is not None:
                            open_trade(sig, spot, expiry_lookup)

            # ---- CSV every 5 min ----
            if time.time() - last_csv_at >= 5 * 60:
                pos_ltp = POS.last_pulse_premium if POS.active else 0
                pos_pnl_pct = ((pos_ltp - POS.entry_premium) / POS.entry_premium * 100) if (POS.active and POS.entry_premium) else 0
                rsi_now = float(df1h['RSI'].iloc[-2]) if 'RSI' in df1h.columns and not pd.isna(df1h['RSI'].iloc[-2]) else float('nan')
                # RSI "no-man's land" [47,53] means neither CE nor PE gate passes
                rsi_blk = (not math.isnan(rsi_now)) and (RSI_PE_MAX <= rsi_now <= RSI_CE_MIN)
                csv_append([now.isoformat(), spot, c1h, sma20, sma50, rsi_now, K, K_prev,
                            DAY.regime, POS.active, POS.side, POS.engine, POS.strike, pos_ltp, pos_pnl_pct,
                            POS.sl_current, POS.tr_armed, POS.tr_sl, POS.peak_premium,
                            DAY.losses, DAY.flips_today, DAY.halted, rsi_blk])
                last_csv_at = time.time()

            # ---- Pulse every 15 min ----
            if time.time() - last_pulse_at >= PULSE_INTERVAL_SEC:
                TG.send(fmt_pulse(spot, c1h, sma20, sma50, K, K_prev, DAY.regime))
                last_pulse_at = time.time()

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
