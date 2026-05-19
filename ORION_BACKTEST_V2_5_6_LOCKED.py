"""
=========================================================================
ORION BACKTEST V2.5.5 LOCKED — full progression from V2.2.2 production
=========================================================================
Backtest on 18 months phase3_daily.pkl (373 days, 2024-09-23 → 2026-03-24)

V2.5.5 HEADLINE RESULT:
  Trades: 933  |  PnL: +Rs 3,72,598 (2 lots × 65)  |  WR: 35.3%
  MaxDD: -1,643 pts  |  Red months: 5/18 (72% positive)

PROGRESSIVE CHANGES FROM LAST STABLE PRODUCTION VERSION (V2.2.2):
=========================================================================

V2.2.2 (live bot in production, parent of all backtests)
  - Single-position bot, V2.2 entry: 1h SMA20/50 regime + 15m StochRSI K
  - HARDSL -35%, fixed % SL, no trail
  - Circuit Breaker 2 losses/day
  - LOT_SIZE=65, 1 lot

V2.3  — cluster level entry foundation
  + Added V3 entry path: cluster G/R levels (PDH/PDL/round_100/PDC/swing pivots/etc.)
    grouped within CLUSTER_RADIUS_PTS=20, Grade A (>=3 sources) and B (>=2 sources)
  + ADX-based regime classifier (TREND/CHOP/TRANSITION using ADX+SMA20 alignment)

V2.4  — exit upgrades
  + BE armor at +15% (later removed)
  + 15m option-premium SMA8(low) trail
  + ATR-based exits

V2.5.0 — backtest framework consolidation (this codebase)
  + Hybrid V2+V3 entry path with V2V3_PRIORITY for same-bar tiebreak
  + Time-ratchet exit (90min initial check; +20 step on each profit hit)
  + V3 cluster scoring + regime-aware target selection

V2.5.1 — entry refinement
  + V2 PE_floor: PE requires K_now >= 25 (V2_K_FLOOR_PE=25)
  + V2 CE: no upper K cap (V2_K_CAP_CE=None) — backtest showed cap hurts
  + V2 priority on V2+V3 same-bar tiebreak (audit confirmed: V2-priority +Rs 52k)

V2.5.2 — flip rule
  + Path A flip (in-trade): elapsed>=30min, peak>=entry+15, close<=entry+10,
    K reversed; flip to opposite side
  + Path B flip (post-close): trigger on K reversal after exit
  + CE->PE: K_now<K_prev AND 25<=K<=80
  + PE->CE: K_now>K_prev AND K>=38
  + Opposite-side only (same-side continuation rejected: -Rs 191k catastrophic)
  + Flips don't count toward circuit breaker
  + +Rs 130k vs no-flip baseline

V2.5.3 — V3 level promotion
  + Promoted singleton V3 levels (PDH/PDL/round_100±200 of PDC/1h swing pivots)
    now standalone Grade B without requiring clustering
  + HARDSL swept and locked at -25% (vs V2.2.2's -35%)
  + Headline: +Rs 3,14,418

V2.5.4 — flip cap (this lock point)
  + MAX_FLIPS_PER_DAY = 3
  + Deep analytics found: flips 1-3 win Rs 131k; flips 4+ lose Rs 21k
  + Pure structural cap, low overfit risk
  + Headline: +Rs 3,23,851 (+Rs 9,433 vs V2.5.3)

V2.5.5 — chop filter
  + CHOP_FILTER_MODE = 'rsi_band'
  + Blocks ALL entries when most recent 1h RSI in [47, 53] (indecision band)
  + Validated on 4 problem date ranges: -Rs 49,168 -> +Rs 1,545 (Rs +50,714)
  + Apr-Jun 2025 (May 2025 catastrophe range): -Rs 25,991 -> +Rs 18,519
  + Filter is principled (signal-based, not calendar)
  + Headline: +Rs 3,72,598 (+Rs 48,747 vs V2.5.4)

V2.5.6 — V3 PDC contamination fix (THIS VERSION)
  + Fix A: Exclude PDC from clustering sources
    (PDC is a reference point, not a tradeable level)
  + Fix B: Require minimum 25pt buffer between G/R and PDC
    (avoid false signals near current price = noise zone)
  Motivated by 2026-05-18 paper trade:
    Bot fired V3 BREAK-PE at R=23658 with PDC=23659.35 (R was AT PDC).
    Entry at 23357 spot (300pts below "R") = late entry at the bottom = -25% HARDSL loss.
  Backtest 18mo: V2.5.5 +Rs 3,72,598 -> V2.5.6 +Rs 3,85,724 (+Rs 13,127, +3.52%)
                 MaxDD -1643 -> -1331 (-19% reduction)
                 WR 35.3% -> 35.7%  Red months 5/18 -> 5/18 (no change)
                 V3 trades 142 -> 123 (-19 bad-level entries removed)
  Headline: +Rs 3,85,724 / 915 trades / WR 35.7% / MaxDD -1,331 / Red 5/18

REJECTED IN THIS PROGRESSION (backtest evidence):
  - SKIP_HOUR_13: -Rs 46k (-14.8%) — counter-intuitive but kills profitable flips
  - SKIP_TUESDAYS: +Rs 56k but calendar-overfit; Chop C replaces with signal
  - ADX<20 standalone filter: -Rs 16k
  - ADX<25 standalone filter: -Rs 34k
  - BE armor at +15%: net negative
  - Same-side flip continuation: -Rs 191k
  - REVERSAL_FLIP_ENABLED=True: 12% WR vs 33% with False
  - CAP at 2 (vs 3): marginal +Rs 1k difference, 3 is more flexible

LOCKED PARAMETERS (V2.5.5):
  LOT_SIZE=65, lots=2
  HARDSL_VALUE=0.25 (-25%)
  CIRCUIT_BREAKER=4 (flips excluded)
  FORCE_CLOSE 15:25, ENTRY_WINDOW 09:45-14:30
  FLIP_ENABLED=True, MAX_FLIPS_PER_DAY=3
  V2_K_FLOOR_PE=25, V2_K_CAP_CE=None
  V2V3_PRIORITY='v2'
  V3_PROMOTE_SINGLETONS=True
  CHOP_FILTER_MODE='rsi_band', CHOP_RSI_LO=47, CHOP_RSI_HI=53

UNDISCUSSED DECISIONS: NONE.
=========================================================================
"""
import pickle
import math
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

# -------------------- Config --------------------
def resolve_dataset_path():
    """Search common Android + desktop paths for phase3_daily.pkl."""
    import os
    filename = "phase3_daily.pkl"
    candidates = [
        f"/storage/emulated/0/Download/backtest_out/{filename}",
        f"/sdcard/Download/backtest_out/{filename}",
        f"/storage/emulated/0/Download/{filename}",
        f"/sdcard/Download/{filename}",
        f"Download/backtest_out/{filename}",
        f"Download/{filename}",
        f"/mnt/user-data/uploads/{filename}",
        filename,
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

LOT_SIZE = 65

# Common risk (V2.5.5 LOCKED defaults — match production spec)
HARDSL_MODE         = 'pct'     # 'pct' or 'abs'
HARDSL_VALUE        = 0.25      # if pct: fraction; LOCKED at -25% (sweep confirmed)
CIRCUIT_BREAKER     = 4         # losses/day to halt (flips excluded from count)
FORCE_CLOSE_BUCKET  = 73        # 15:20-15:25 5m bar; close at its close (15:25)
# Bucket K closes at 9:15 + (K+1)*5 min. Bucket 62 closes at 14:30. Use 62.
ENTRY_WINDOW_END_BKT = 62

# V2.3 entry params
CLUSTER_RADIUS_PTS    = 20
GRADE_A_MIN_SOURCES   = 3
GRADE_B_MIN_SOURCES   = 2
ADX_PERIOD            = 14
ADX_CHOP_MAX          = 20
ADX_TREND_MIN         = 25
SMA_FAST              = 20
SMA_SLOW              = 50
MACD_FAST             = 12
MACD_SLOW             = 26
MACD_SIGNAL           = 9
SWING_LOOKBACK_BARS   = 20
SWING_PIVOT_N         = 3
ROUND_STEP_FINE       = 50
ROUND_STEP_MAJOR      = 100
ROUND_RANGE_PTS       = 300
ATM_STEP              = 100
GAP_THRESHOLD_PCT     = 0.01
GRADE_A_MIN_CLOSE_BEYOND = 15
GRADE_A_MIN_BODY_PCT     = 0.40
GRADE_B_MIN_BODY_PCT     = 0.60
GRADE_B_CLOSE_TOP_PCT    = 0.25
WICK_REJECT_MIN_PCT      = 0.50
WICK_REJECT_CLOSE_DIST   = 10
T1_MIN_PTS, T1_MAX_PTS = 50, 100
T2_MIN_PTS, T2_MAX_PTS = 100, 200

# V2.3 exit (Combo 1)
LOTS_GRADE_A          = 2
LOTS_GRADE_B          = 2
TIGHT_SL_BUFFER_PTS   = 5

# V2.4 exit (Combos 2/3)
BE_TRIGGER_PCT        = 0.15
SMA_TRAIL_PERIOD      = 8
SMA_TRAIL_TF_BARS     = 3       # 3 × 5m = 15m

# V2.4 entry (Combo 3)
ITM_OFFSET            = 100     # CE buys atm-100, PE buys atm+100
MACD_REQUIRE_ALIGN    = True
PREM_GATE_REQUIRE     = True

# Profit lock (NEW — addresses today's lost-profit case)
PROFIT_LOCK_TRIGGER   = 20      # ₹ above entry premium to arm the lock
PROFIT_LOCK_FLOOR     = 10      # ₹ above entry premium where SL is locked (configurable)
PROFIT_LOCK_HARD      = False   # if True, exit at trigger immediately (Design A)
V2V3_PRIORITY         = 'v2'    # 'v2' or 'v3' — who wins same-bar tiebreak
V3_PROMOTE_SINGLETONS = True    # LOCKED True (V2.5.3): PDH/PDL/round_100/swing_pivots standalone Grade B

# V2.5.6 — V3 PDC contamination fix (motivated by 2026-05-18 paper-trade PE loss)
# Fix A: Exclude PDC from being a clustering source (PDC is a reference, not a tradeable level)
# Fix B: Require minimum buffer between G/R selection and PDC (avoid noise-level signals near current price)
V3_EXCLUDE_PDC_FROM_CLUSTERS = True
V3_MIN_BUFFER_FROM_PDC       = 25     # G must be >= PDC + 25; R must be <= PDC - 25

# V2 K-cap entry modification (V2.5.1 — prevents buying exhausted momentum)
# V2 CE: requires K_now <= V2_K_CAP_CE  (None = uncapped — LOCKED at None, no cap)
# V2 PE: requires K_now >= V2_K_FLOOR_PE (LOCKED at 25 — PE_floor=25)
V2_K_CAP_CE           = None
V2_K_FLOOR_PE         = 25

# Flip rule (V2.5.2 — rejection-flip on 15m K reversal, opposite-side only)
FLIP_ENABLED          = True    # LOCKED ON (backtest +₹130k vs OFF)
FLIP_PATH_A_ELAPSED   = 30      # min elapsed required for Path A flip
FLIP_PATH_A_PEAK_MIN  = 15      # peak premium >= entry + this for Path A
FLIP_PATH_A_DROP_MAX  = 10      # current LTP <= entry + this for Path A
FLIP_K_CE_TO_PE_MIN   = 25      # CE->PE flip: K_now >= this (matches PE_floor)
FLIP_K_CE_TO_PE_MAX   = 80      # CE->PE flip: K_now <= this
FLIP_K_PE_TO_CE_MIN   = 38      # PE->CE flip: K_now >= this
# No upper cap on PE->CE side (matches no-CE-cap decision)

# Chop-protection filters (V2.5.4 — patterns found via deep analytics)
MAX_FLIPS_PER_DAY     = 3       # LOCKED at 3 (flips 1-3 win ₹131k; flips 4+ lose ₹21k)
SKIP_HOUR_13          = False   # REJECTED by backtest (-₹46k vs no skip)
SKIP_TUESDAYS         = False   # REJECTED (calendar overfit risk; Chop C replaces)

# Chop detector filter (V2.5.5 — RSI [47,53] indecision band)
# Modes: 'off', 'adx20', 'adx25', 'rsi_band', 'range_tight', 'k_oscillation', 'adx25_range', 'adx20_rsi'
CHOP_FILTER_MODE      = 'rsi_band'  # LOCKED at rsi_band (best filter: +₹48k vs Cap3-only)
CHOP_ADX_THRESHOLD    = 20      # legacy/unused in rsi_band mode
CHOP_RSI_LO           = 47      # LOCKED: block entries if 1h RSI in [47, 53]
CHOP_RSI_HI           = 53      # LOCKED
CHOP_RANGE_PCT_MIN    = 0.4     # legacy/unused in rsi_band mode
CHOP_RANGE_AFTER_BKT  = 12      # legacy/unused in rsi_band mode
CHOP_K_CROSS_MAX      = 4       # legacy/unused in rsi_band mode

# Transaction costs per lot per trade (brokerage + STT + exchange fees estimate)
TRANSACTION_COST_PER_LOT = 50  # Rs per lot, conservative estimate

# Method 2: time-delayed ratchet (NEW)
# V2.5.7: Velvet Rope + Accelerated Ratchet (was 120min/+20 in V2.5.6)
RATCHET_TIME_MIN      = 30      # arm window: 30min (was 120)
RATCHET_INITIAL_PTS   = 15      # velvet rope trigger at entry+15 (was 20)
RATCHET_STEP_PTS      = 20      # each +N move above current SL → SL += N
VELVET_ROPE_BE_OFFSET = 2       # pts above entry for velvet rope SL (entry + this)
PARTIAL_BOOK_PTS      = 20      # pts gain at which 1 lot is booked in partial_* models

# V2.2 entry params
STOCHRSI_LEN          = 14
STOCHRSI_RSI_LEN      = 14
STOCHRSI_K_SMOOTH     = 3
STOCHRSI_CE_LO        = 38      # CE entry: K >= this
STOCHRSI_PE_HI        = 80      # PE entry: K <= this
SMA_FAST_1H_LEN       = 20
SMA_SLOW_1H_LEN       = 50


# -------------------- Bucket / time helpers --------------------
# bkt_to_hour and bkt_to_str removed — confirmed never called anywhere in codebase


# -------------------- Indicator math --------------------
def rsi(close: pd.Series, n=14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def stochrsi_k(close: pd.Series, length=14, rsi_length=14, k=3) -> pd.Series:
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
    atr   = tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    pdi   = 100 * plus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean()  / atr
    ndi   = 100 * minus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr
    dx    = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    adx   = dx.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    return adx, pdi, ndi


# -------------------- Continuous stream builder --------------------
def build_continuous_streams(daily: dict):
    """
    Build continuous cross-day pd.DataFrames for Nifty 5m, 15m, 1h.
    Each row tagged with date+bucket. Indicators computed on continuous stream
    so cross-day continuity is preserved (esp. for MACD/SMA on 1h).
    """
    dates = sorted(daily.keys())
    rec_5m, rec_15m, rec_1h = [], [], []
    for d in dates:
        day = daily[d]
        for b in day['nifty_5m']:
            rec_5m.append({'date': d, 'bucket': b['bucket'], **b})
        for b in day['nifty_15m']:
            rec_15m.append({'date': d, 'bucket': b['bucket'], **b})
        for b in day['nifty_1h']:
            rec_1h.append({'date': d, 'bucket': b['bucket'], **b})
    df5  = pd.DataFrame(rec_5m).reset_index(drop=True)
    df15 = pd.DataFrame(rec_15m).reset_index(drop=True)
    df1h = pd.DataFrame(rec_1h).reset_index(drop=True)

    # Indicators on 1h (V2.3 regime gates)
    df1h['SMA20'] = df1h['close'].rolling(SMA_FAST).mean()
    df1h['SMA50'] = df1h['close'].rolling(SMA_SLOW).mean()
    df1h['SMA20_slope'] = df1h['SMA20'].diff(3)
    df1h['SMA50_slope'] = df1h['SMA50'].diff(3)
    df1h['ADX'], df1h['DI_plus'], df1h['DI_minus'] = adx_di(df1h)
    df1h['MACD_line'], df1h['MACD_sig'] = macd_lines(df1h['close'])
    df1h['RSI'] = rsi(df1h['close'])

    # Indicators on 5m (V2.4 MACD gate uses spot 5m)
    df5['MACD_line'], df5['MACD_sig'] = macd_lines(df5['close'])

    # Indicators on 15m (V2.2 entry uses 15m StochRSI; not directly needed here)
    # but compute for diagnostic
    df15['K'] = stochrsi_k(df15['close'])

    return df5, df15, df1h


# -------------------- Level computation (V2.3) --------------------
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
    pdh, pdl, pdc = float(prior_day_ohlc['H']), float(prior_day_ohlc['L']), float(prior_day_ohlc['C'])
    # V2.5.6 Fix A: optionally exclude PDC from clustering sources.
    # PDC is a reference (today's pivot) not a tradeable level — including it as a
    # source contaminates clusters near current price with false Grade A signals.
    if V3_EXCLUDE_PDC_FROM_CLUSTERS:
        src = [(pdh, 'PDH'), (pdl, 'PDL')]
    else:
        src = [(pdh, 'PDH'), (pdl, 'PDL'), (pdc, 'PDC')]
    src += generate_round_levels(pdc)
    swing_pivots = find_swing_pivots(df1h_prior)
    src += swing_pivots
    src = [s for s in src if abs(s[0] - pdc) <= ROUND_RANGE_PTS]
    clusters = cluster_levels(src)

    # === Analyst-style singleton promotions (V2.5.3 — added) ===
    # Promote strong single-source levels to Grade B if not already part of A/B cluster.
    # Matches how analyst tracks specific recent-action levels (not just round_100).
    if not V3_PROMOTE_SINGLETONS:
        # OLD behavior: return only true clusters
        # V2.5.6 Fix B: respect MIN_BUFFER_FROM_PDC for G/R selection
        buf = V3_MIN_BUFFER_FROM_PDC
        above = [c for c in clusters if c['center'] > pdc + buf and c['grade'] in ('A','B')]
        below = [c for c in clusters if c['center'] < pdc - buf and c['grade'] in ('A','B')]
        above.sort(key=lambda c: (0 if c['grade']=='A' else 1, abs(c['center']-pdc)))
        below.sort(key=lambda c: (0 if c['grade']=='A' else 1, abs(c['center']-pdc)))
        return {'pdh': pdh, 'pdl': pdl, 'pdc': pdc,
                'G': above[0] if above else None,
                'R': below[0] if below else None,
                'all_clusters': clusters}

    PROMOTE_ROUND_100_BAND = 200   # ±pts from PDC for round_100 standalone promotion
    PROMOTE_SWING_BAND     = ROUND_RANGE_PTS
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
    for off in range(-PROMOTE_ROUND_100_BAND, PROMOTE_ROUND_100_BAND + 1, 100):
        base = round(pdc / 100) * 100
        p = float(base + off)
        if not _in_any_AB_cluster(p):
            promoted.append({'center': round(p, 2), 'kinds': ['round_100'], 'count': 1,
                             'grade': 'B', 'promoted': True})
    # 1h swing pivots
    for p, kind in swing_pivots:
        if abs(p - pdc) <= PROMOTE_SWING_BAND and not _in_any_AB_cluster(p):
            promoted.append({'center': round(p, 2), 'kinds': [kind], 'count': 1,
                             'grade': 'B', 'promoted': True})

    all_levels = clusters + promoted

    # V2.5.6 Fix B: respect MIN_BUFFER_FROM_PDC for G/R selection
    buf = V3_MIN_BUFFER_FROM_PDC
    above = [c for c in all_levels if c['center'] > pdc + buf and c['grade'] in ('A','B')]
    below = [c for c in all_levels if c['center'] < pdc - buf and c['grade'] in ('A','B')]
    # Sort: Grade A first, then by distance to PDC
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
    t2 = next((c for c in cand if T2_MIN_PTS <= abs(c-center) <= T2_MAX_PTS and c != t1), None)
    if t2 is None: t2 = (center + T2_MAX_PTS) if direction == 'CE' else (center - T2_MAX_PTS)
    t3 = None
    for c in cand:
        if direction == 'CE' and c > t2: t3 = c; break
        if direction == 'PE' and c < t2: t3 = c; break
    if t3 is None: t3 = (t2 + 100) if direction == 'CE' else (t2 - 100)
    return [round(t1, 2), round(t2, 2), round(t3, 2)]


# -------------------- Regime + candle quality --------------------
def classify_regime(row_1h):
    if pd.isna(row_1h.get('SMA20')) or pd.isna(row_1h.get('SMA50')) \
       or pd.isna(row_1h.get('ADX')):
        return 'INSUFFICIENT'
    c, s20, s50 = row_1h['close'], row_1h['SMA20'], row_1h['SMA50']
    sl20, sl50, adxv = row_1h['SMA20_slope'], row_1h['SMA50_slope'], row_1h['ADX']
    if adxv < ADX_CHOP_MAX: return 'CHOP'
    if c > s20 > s50 and sl20 > 0 and sl50 > 0 and adxv > ADX_TREND_MIN: return 'BULL'
    if c < s20 < s50 and sl20 < 0 and sl50 < 0 and adxv > ADX_TREND_MIN: return 'BEAR'
    return 'TRANSITION'

def regime_allows_trade(regime):
    # sig_dir parameter removed — strategy trades both CE and PE in any non-CHOP regime.
    # Directional filtering (BULL blocks PE, BEAR blocks CE) was evaluated and rejected.
    return regime not in ('CHOP', 'INSUFFICIENT')

def evaluate_candle(bar, level, kind, grade):
    o, h, l, c = bar['open'], bar['high'], bar['low'], bar['close']
    rng = h - l
    if rng <= 0: return False
    body_pct = abs(c - o) / rng
    if kind == 'BREAK_CE':
        beyond = c - level
        if grade == 'A':
            return beyond >= GRADE_A_MIN_CLOSE_BEYOND and body_pct >= GRADE_A_MIN_BODY_PCT
        else:
            return body_pct >= GRADE_B_MIN_BODY_PCT and (c - l)/rng >= 1 - GRADE_B_CLOSE_TOP_PCT
    elif kind == 'BREAK_PE':
        beyond = level - c
        if grade == 'A':
            return beyond >= GRADE_A_MIN_CLOSE_BEYOND and body_pct >= GRADE_A_MIN_BODY_PCT
        else:
            return body_pct >= GRADE_B_MIN_BODY_PCT and (h - c)/rng >= 1 - GRADE_B_CLOSE_TOP_PCT
    return False

def detect_v23_signal(bar, level, level_role):
    o, h, l, c = bar['open'], bar['high'], bar['low'], bar['close']
    L = level['center']
    rng = h - l
    grade = level['grade']
    # Wick rejection
    if rng > 0:
        if level_role == 'G' and h >= L and c < L + WICK_REJECT_CLOSE_DIST:
            wick = h - max(o, c)
            if (wick / rng) >= WICK_REJECT_MIN_PCT and abs(c - L) <= WICK_REJECT_CLOSE_DIST:
                return {'kind': 'REJECT_PE', 'level': L, 'role': level_role, 'grade': grade}
        if level_role == 'R' and l <= L and c > L - WICK_REJECT_CLOSE_DIST:
            wick = min(o, c) - l
            if (wick / rng) >= WICK_REJECT_MIN_PCT and abs(c - L) <= WICK_REJECT_CLOSE_DIST:
                return {'kind': 'REJECT_CE', 'level': L, 'role': level_role, 'grade': grade}
    # Break
    if level_role == 'G' and c > L:
        if evaluate_candle(bar, L, 'BREAK_CE', grade):
            return {'kind': 'BREAK_CE', 'level': L, 'role': level_role, 'grade': grade}
    if level_role == 'R' and c < L:
        if evaluate_candle(bar, L, 'BREAK_PE', grade):
            return {'kind': 'BREAK_PE', 'level': L, 'role': level_role, 'grade': grade}
    return None


# (Framework v0.1 load banner removed — dead module-level print)

def hardsl_floor(entry_premium):
    """Compute HARDSL floor price using current globals HARDSL_MODE/VALUE."""
    if HARDSL_MODE == 'pct':
        return entry_premium * (1 - HARDSL_VALUE)
    elif HARDSL_MODE == 'abs':
        return entry_premium - HARDSL_VALUE
    raise ValueError(f"Unknown HARDSL_MODE: {HARDSL_MODE}")


# -------------------- V2.4 entry detection --------------------
V24_LEVELS_OFFSET = 500   # psy band ± 500
def v24_compute_levels(prior_day_ohlc):
    """V2.4 simple levels: PDC, PDH, PDL, psy-500, psy, psy+500."""
    pdh, pdl, pdc = float(prior_day_ohlc['H']), float(prior_day_ohlc['L']), float(prior_day_ohlc['C'])
    psy = int(round(pdc / V24_LEVELS_OFFSET) * V24_LEVELS_OFFSET)
    lvls = sorted({pdc, pdh, pdl, psy - V24_LEVELS_OFFSET, psy, psy + V24_LEVELS_OFFSET})
    return lvls

def v24_detect_5m_break(bar_5m, levels):
    """5m bar break of any level. Returns (direction, level) or (None, None)."""
    o, h, l, c = bar_5m['open'], bar_5m['high'], bar_5m['low'], bar_5m['close']
    for lvl in levels:
        if l <= lvl and c > lvl and c > o:
            return 'CE', lvl
        if h >= lvl and c < lvl and c < o:
            return 'PE', lvl
    return None, None


# -------------------- Option premium 15m aggregator + SMA8(low) --------------------
def opt_15m_from_5m(opt_5m_bars, upto_5m_bucket):
    """
    Aggregate option 5m bars into 15m bars completed at-or-before upto_5m_bucket
    (inclusive). Returns list of dicts {bkt15, o, h, l, c}.
    15m bucket k aggregates 5m buckets 3k, 3k+1, 3k+2; closes at end of 3k+2.
    """
    by_bkt = {b['bucket']: b for b in opt_5m_bars}
    out = []
    for k15 in range(25):
        end_5m = 3*k15 + 2
        if end_5m > upto_5m_bucket: break
        members = [by_bkt[b] for b in (3*k15, 3*k15+1, 3*k15+2) if b in by_bkt]
        if not members: continue
        out.append({
            'bkt15': k15,
            'o': members[0]['open'],
            'h': max(m['high'] for m in members),
            'l': min(m['low']  for m in members),
            'c': members[-1]['close'],
        })
    return out

def sma_last(values, n):
    if len(values) < n: return None
    return sum(values[-n:]) / n

def compute_vwap_by_bkt(nifty_5m_bars: list) -> dict:
    """Cumulative VWAP per 5m bucket, computed from session open each day."""
    cum_vol = 0.0
    cum_tpv = 0.0
    result = {}
    for bar in sorted(nifty_5m_bars, key=lambda b: b['bucket']):
        tp = (bar['high'] + bar['low'] + bar['close']) / 3.0
        vol = float(bar.get('volume', 1.0))
        cum_tpv += tp * vol
        cum_vol += vol
        result[bar['bucket']] = cum_tpv / cum_vol if cum_vol > 0 else tp
    return result


# -------------------- Trade dataclass --------------------
@dataclass
class Trade:
    day: date
    side: str                     # 'CE' or 'PE'
    grade: str                    # 'A','B' (V2.3 entry) or 'V24' (V2.4 entry)
    entry_bkt: int                # 5m bucket of ENTRY (we enter at this bar's OPEN)
    entry_nifty: float
    entry_premium: float
    strike: int
    trigger_level: float          # the level we broke / cluster center
    targets: list = field(default_factory=list)  # [T1,T2,T3] (Nifty pts) for V2.3 exit
    current_sl_nifty: Optional[float] = None     # for V2.3 exit
    hardsl_premium: float = 0.0                  # -15% floor
    lots: int = 2
    lots_remaining: int = 2
    be_armed: bool = False         # V2.4 exit
    profit_lock_armed: bool = False  # NEW: armed when premium high >= entry + TRIGGER
    profit_lock_price: float = 0.0   # NEW: lock price (entry + FLOOR)
    tr_armed: bool = False           # NEW: time-ratchet armed flag
    tr_sl: float = 0.0               # NEW: time-ratchet SL price (ratchets up)
    t1_hit: bool = False
    t2_hit: bool = False
    peak_prem: float = 0.0
    closed: bool = False
    exits: list = field(default_factory=list)    # [{bkt, reason, nifty, prem, lots}]

    def book(self, bkt, reason, nifty, prem, lots):
        self.exits.append({'bkt': bkt, 'reason': reason, 'nifty': nifty, 'prem': prem, 'lots': lots})
        self.lots_remaining -= lots
        if self.lots_remaining <= 0:
            self.closed = True

    def pnl_nifty_pts(self):
        s = 0.0
        for e in self.exits:
            if self.side == 'CE':
                s += (e['nifty'] - self.entry_nifty) * e['lots']
            else:
                s += (self.entry_nifty - e['nifty']) * e['lots']
        return s

    def pnl_prem_per_lot(self):
        """Average premium pts per single-lot, useful for WR distribution."""
        if not self.exits: return 0.0
        total = sum((e['prem'] - self.entry_premium) * e['lots'] for e in self.exits)
        return total / self.lots

    def pnl_prem_rs(self):
        s = 0.0
        for e in self.exits:
            s += (e['prem'] - self.entry_premium) * e['lots'] * LOT_SIZE
        # Subtract transaction costs: one round-trip per trade (entry + exit), per lot
        s -= TRANSACTION_COST_PER_LOT * self.lots
        return s


# -------------------- Trade simulator --------------------
def simulate_trade(trade: Trade, day_data: dict, exit_model: str,
                   trigger_level_for_15m: Optional[float] = None,
                   k_lookup: Optional[dict] = None,
                   vwap_by_bkt: Optional[dict] = None):
    """
    Walk forward from trade.entry_bkt+1 to FORCE_CLOSE_BUCKET.
    Updates intra-bar (using 5m h/l) and 15m bar (using close-back through level).

    exit_model: 'v23', 'v24', 'sma8only', 'sma8_plock', 'sma8_tratchet'
    k_lookup: dict {bucket_5m: K} for THIS day's Nifty 15m K (used by flip Path A).
              If None, falls back to day_data.get('_k_lookup').
    """
    if k_lookup is None:
        k_lookup = day_data.get('_k_lookup')
    opt_key = (trade.strike, trade.side)
    opt_5m = sorted(day_data['opt_5m'].get(opt_key, []), key=lambda b: b['bucket'])
    if not opt_5m:
        trade.book(trade.entry_bkt, 'NO_OPT_DATA', trade.entry_nifty, trade.entry_premium, trade.lots)
        return trade

    nifty_5m = sorted(day_data['nifty_5m'], key=lambda b: b['bucket'])
    nifty_by_bkt = {b['bucket']: b for b in nifty_5m}
    opt_by_bkt = {b['bucket']: b for b in opt_5m}
    if vwap_by_bkt is None:
        vwap_by_bkt = compute_vwap_by_bkt(nifty_5m)

    for bkt in range(trade.entry_bkt, FORCE_CLOSE_BUCKET + 1):
        if trade.closed: break
        n5 = nifty_by_bkt.get(bkt)
        o5 = opt_by_bkt.get(bkt)
        if n5 is None or o5 is None:
            continue

        # Force close at bucket 73
        if bkt >= FORCE_CLOSE_BUCKET:
            trade.book(bkt, 'FORCE_CLOSE_15_25', n5['close'], o5['close'], trade.lots_remaining)
            break

        # Update peak premium
        trade.peak_prem = max(trade.peak_prem, o5['high'])

        # 1) HARDSL on premium (mode-aware) — uses intra-bar LOW
        if o5['low'] <= trade.hardsl_premium:
            mode_lbl = f"HARDSL_{int(HARDSL_VALUE*100)}pct" if HARDSL_MODE == 'pct' else f"HARDSL_{int(HARDSL_VALUE)}pt"
            trade.book(bkt, mode_lbl, n5['close'], trade.hardsl_premium, trade.lots_remaining)
            break

        # 2) Model-specific updates
        if exit_model == 'v23':
            T = trade.targets
            # 2a. T1 check
            if not trade.t1_hit:
                hit = (trade.side == 'CE' and n5['high'] >= T[0]) or \
                      (trade.side == 'PE' and n5['low']  <= T[0])
                if hit:
                    trade.t1_hit = True
                    if trade.grade == 'B':
                        trade.book(bkt, 'T1_FULL_GRADE_B', T[0], o5['close'], trade.lots_remaining)
                        break
                    else:
                        # Grade A: book 1 lot, runner SL to entry
                        trade.book(bkt, 'T1_PARTIAL_GRADE_A', T[0], o5['close'], 1)
                        trade.current_sl_nifty = trade.entry_nifty
                        if trade.closed: break
            # 2b. Runner section after T1 (Grade A only since B exits at T1)
            if trade.t1_hit and not trade.t2_hit and trade.lots_remaining > 0:
                # T2 check
                hit2 = (trade.side == 'CE' and n5['high'] >= T[1]) or \
                       (trade.side == 'PE' and n5['low']  <= T[1])
                if hit2:
                    trade.t2_hit = True
                    trade.current_sl_nifty = T[0]
                else:
                    # runner SL (still at entry until T2)
                    sl_hit = (trade.side == 'CE' and n5['low']  <= trade.current_sl_nifty) or \
                             (trade.side == 'PE' and n5['high'] >= trade.current_sl_nifty)
                    if sl_hit:
                        trade.book(bkt, 'RUNNER_SL_BE', trade.current_sl_nifty, o5['close'], trade.lots_remaining)
                        break
            # 2c. Post-T2 trail
            if trade.t2_hit:
                # Trail SL (now at T1)
                sl_hit = (trade.side == 'CE' and n5['low']  <= trade.current_sl_nifty) or \
                         (trade.side == 'PE' and n5['high'] >= trade.current_sl_nifty)
                if sl_hit:
                    trade.book(bkt, 'TRAIL_SL_T1', trade.current_sl_nifty, o5['close'], trade.lots_remaining)
                    break
                # T3 check
                hit3 = (trade.side == 'CE' and n5['high'] >= T[2]) or \
                       (trade.side == 'PE' and n5['low']  <= T[2])
                if hit3:
                    trade.book(bkt, 'T3_HIT', T[2], o5['close'], trade.lots_remaining)
                    break

            # 2d. Tight SL: 15m close back through trigger BEFORE T1 hit
            if not trade.t1_hit and trigger_level_for_15m is not None:
                # check at every 15m close (bkt%3 == 2)
                if bkt % 3 == 2:
                    # Use 15m close = this 5m close (since bkt is the last 5m of the 15m)
                    n15c = n5['close']
                    if trade.side == 'CE' and n15c < trigger_level_for_15m - TIGHT_SL_BUFFER_PTS:
                        trade.book(bkt, 'TIGHT_SL_15M_CLOSE', n15c, o5['close'], trade.lots_remaining)
                        break
                    if trade.side == 'PE' and n15c > trigger_level_for_15m + TIGHT_SL_BUFFER_PTS:
                        trade.book(bkt, 'TIGHT_SL_15M_CLOSE', n15c, o5['close'], trade.lots_remaining)
                        break

        elif exit_model == 'v24':
            # 2a. BE arm
            if not trade.be_armed and o5['high'] >= trade.entry_premium * (1 + BE_TRIGGER_PCT):
                trade.be_armed = True
                trade.current_sl_nifty = trade.entry_premium  # store BE on premium
            # 2b. BE scratch
            if trade.be_armed and o5['low'] <= trade.entry_premium:
                trade.book(bkt, 'BE_SCRATCH', n5['close'], trade.entry_premium, trade.lots_remaining)
                break
            # 2c. 15m SMA8(low) trail check on closed 15m bars only
            if bkt % 3 == 2 and bkt >= 3*SMA_TRAIL_PERIOD - 1:
                o15 = opt_15m_from_5m(opt_5m, bkt)
                if len(o15) >= SMA_TRAIL_PERIOD:
                    lows = [b['l'] for b in o15]
                    sma8L = sma_last(lows, SMA_TRAIL_PERIOD)
                    last15c = o15[-1]['c']
                    if sma8L is not None and last15c < sma8L:
                        trade.book(bkt, 'SMA8_LOW_TRAIL', n5['close'], o5['close'], trade.lots_remaining)
                        break

        elif exit_model == 'sma8_tratchet':
            # V2.5.7: VELVET ROPE + ACCELERATED RATCHET + RUNNER STEP TRAIL
            elapsed_min = (bkt - trade.entry_bkt) * 5

            # Step 1: Velvet Rope — immediate protection when premium touches entry+15
            # Arms SL at entry+2 to prevent winners surrendering back to HARDSL
            if (not trade.tr_armed) and o5['high'] >= trade.entry_premium + RATCHET_INITIAL_PTS:
                trade.tr_armed = True
                trade.tr_sl = trade.entry_premium + 2
                if o5['low'] <= trade.tr_sl:
                    trade.book(bkt, 'VELVET_ROPE_BE_SCRATCH', n5['close'], trade.tr_sl, trade.lots_remaining)
                    break

            # Step 2: Ratchet Gate — after 30min + entry+25, promote SL from entry+2 to entry+15
            if trade.tr_armed and trade.tr_sl == (trade.entry_premium + 2) and elapsed_min >= RATCHET_TIME_MIN:
                if o5['high'] >= trade.entry_premium + 25:
                    trade.tr_sl = trade.entry_premium + 15
                    if o5['low'] <= trade.tr_sl:
                        trade.book(bkt, 'RATCHET_GATE_+15', n5['close'], trade.tr_sl, trade.lots_remaining)
                        break

            # Step 3: Runner step trail — ratchet SL up +STEP per +STEP peak
            if trade.tr_armed:
                while o5['high'] >= trade.tr_sl + RATCHET_STEP_PTS:
                    trade.tr_sl += RATCHET_STEP_PTS
                # cap to bar open — SL cannot be placed above a price never traded
                trade.tr_sl = min(trade.tr_sl, o5['open'])
                if o5['low'] <= trade.tr_sl:
                    pts_locked = trade.tr_sl - trade.entry_premium
                    trade.book(bkt, f'OPTIMIZED_RATCHET_+{int(pts_locked)}', n5['close'], trade.tr_sl, trade.lots_remaining)
                    break

            # SMA8 trail
            if bkt % 3 == 2 and bkt >= 3*SMA_TRAIL_PERIOD - 1:
                o15 = opt_15m_from_5m(opt_5m, bkt)
                if len(o15) >= SMA_TRAIL_PERIOD:
                    lows = [b['l'] for b in o15]
                    sma8L = sma_last(lows, SMA_TRAIL_PERIOD)
                    last15c = o15[-1]['c']
                    if sma8L is not None and last15c < sma8L:
                        trade.book(bkt, 'SMA8_LOW_TRAIL', n5['close'], o5['close'], trade.lots_remaining)
                        break

        elif exit_model == 'sma8only':
            # Pure 15m option SMA8(low) trail. No BE, no T1/T2/T3, no other exits.
            # HARDSL (above), force close (above), CB (in run_day) are the only other gates.
            if bkt % 3 == 2 and bkt >= 3*SMA_TRAIL_PERIOD - 1:
                o15 = opt_15m_from_5m(opt_5m, bkt)
                if len(o15) >= SMA_TRAIL_PERIOD:
                    lows = [b['l'] for b in o15]
                    sma8L = sma_last(lows, SMA_TRAIL_PERIOD)
                    last15c = o15[-1]['c']
                    if sma8L is not None and last15c < sma8L:
                        trade.book(bkt, 'SMA8_LOW_TRAIL', n5['close'], o5['close'], trade.lots_remaining)
                        break

        elif exit_model == 'velvet_vwap':
            # Velvet Rope: arm when premium +15
            if (not trade.tr_armed) and o5['high'] >= trade.entry_premium + RATCHET_INITIAL_PTS:
                trade.tr_armed = True
                trade.tr_sl = trade.entry_premium + VELVET_ROPE_BE_OFFSET
                if o5['low'] <= trade.tr_sl:
                    trade.book(bkt, 'VELVET_ROPE_SL', n5['close'], trade.tr_sl, trade.lots_remaining)
                    break
            # SL check
            if trade.tr_armed and o5['low'] <= trade.tr_sl:
                trade.book(bkt, 'VELVET_ROPE_SL', n5['close'], trade.tr_sl, trade.lots_remaining)
                break
            # VWAP trail: exit when Nifty crosses VWAP while in profit
            vwap_now = vwap_by_bkt.get(bkt)
            if vwap_now is not None and o5['close'] >= trade.entry_premium + 10:
                if trade.side == 'CE' and n5['close'] < vwap_now:
                    trade.book(bkt, 'VWAP_TRAIL_EXIT', n5['close'], o5['close'], trade.lots_remaining)
                    break
                elif trade.side == 'PE' and n5['close'] > vwap_now:
                    trade.book(bkt, 'VWAP_TRAIL_EXIT', n5['close'], o5['close'], trade.lots_remaining)
                    break

        elif exit_model == 'velvet_sma5m':
            # Velvet Rope
            if (not trade.tr_armed) and o5['high'] >= trade.entry_premium + RATCHET_INITIAL_PTS:
                trade.tr_armed = True
                trade.tr_sl = trade.entry_premium + VELVET_ROPE_BE_OFFSET
                if o5['low'] <= trade.tr_sl:
                    trade.book(bkt, 'VELVET_ROPE_SL', n5['close'], trade.tr_sl, trade.lots_remaining)
                    break
            if trade.tr_armed and o5['low'] <= trade.tr_sl:
                trade.book(bkt, 'VELVET_ROPE_SL', n5['close'], trade.tr_sl, trade.lots_remaining)
                break
            # 5m SMA8(low) trail: compute on all opt 5m bars up to current
            all_lows_5m = [b['low'] for b in opt_5m if b['bucket'] <= bkt]
            if len(all_lows_5m) >= SMA_TRAIL_PERIOD:
                sma8_5m = sma_last(all_lows_5m, SMA_TRAIL_PERIOD)
                if sma8_5m is not None and o5['close'] < sma8_5m:
                    trade.book(bkt, 'SMA8_5M_TRAIL', n5['close'], o5['close'], trade.lots_remaining)
                    break

        elif exit_model == 'partial_sma15m':
            # Partial booking at +PARTIAL_BOOK_PTS
            if not trade.t1_hit and o5['high'] >= trade.entry_premium + PARTIAL_BOOK_PTS:
                trade.t1_hit = True
                book_price = trade.entry_premium + PARTIAL_BOOK_PTS
                trade.book(bkt, f'PARTIAL_FIXED_+{PARTIAL_BOOK_PTS}', n5['close'], book_price, 1)
                if trade.closed: break
            # Trail remaining with 15m SMA8
            if trade.t1_hit and trade.lots_remaining > 0:
                if bkt % 3 == 2 and bkt >= 3*SMA_TRAIL_PERIOD - 1:
                    o15 = opt_15m_from_5m(opt_5m, bkt)
                    if len(o15) >= SMA_TRAIL_PERIOD:
                        sma8L = sma_last([b['l'] for b in o15], SMA_TRAIL_PERIOD)
                        if sma8L is not None and o15[-1]['c'] < sma8L:
                            trade.book(bkt, 'SMA8_TRAIL_RUNNER', n5['close'], o5['close'], trade.lots_remaining)
                            break
            # Before t1: also trail with 15m SMA8 (pre-partial)
            if not trade.t1_hit:
                if bkt % 3 == 2 and bkt >= 3*SMA_TRAIL_PERIOD - 1:
                    o15 = opt_15m_from_5m(opt_5m, bkt)
                    if len(o15) >= SMA_TRAIL_PERIOD:
                        sma8L = sma_last([b['l'] for b in o15], SMA_TRAIL_PERIOD)
                        if sma8L is not None and o15[-1]['c'] < sma8L:
                            trade.book(bkt, 'SMA8_TRAIL_FULL', n5['close'], o5['close'], trade.lots_remaining)
                            break

        elif exit_model == 'partial_vwap':
            # Partial booking at +PARTIAL_BOOK_PTS
            if not trade.t1_hit and o5['high'] >= trade.entry_premium + PARTIAL_BOOK_PTS:
                trade.t1_hit = True
                book_price = trade.entry_premium + PARTIAL_BOOK_PTS
                trade.book(bkt, f'PARTIAL_FIXED_+{PARTIAL_BOOK_PTS}', n5['close'], book_price, 1)
                if trade.closed: break
            # VWAP trail on runner (and full position before t1)
            vwap_now = vwap_by_bkt.get(bkt)
            if vwap_now is not None and o5['close'] >= trade.entry_premium + 10:
                if trade.side == 'CE' and n5['close'] < vwap_now:
                    trade.book(bkt, 'VWAP_TRAIL_RUNNER', n5['close'], o5['close'], trade.lots_remaining)
                    break
                elif trade.side == 'PE' and n5['close'] > vwap_now:
                    trade.book(bkt, 'VWAP_TRAIL_RUNNER', n5['close'], o5['close'], trade.lots_remaining)
                    break

        elif exit_model == 'vwap_only':
            vwap_now = vwap_by_bkt.get(bkt)
            if vwap_now is not None and o5['close'] >= trade.entry_premium + 10:
                if trade.side == 'CE' and n5['close'] < vwap_now:
                    trade.book(bkt, 'VWAP_EXIT', n5['close'], o5['close'], trade.lots_remaining)
                    break
                elif trade.side == 'PE' and n5['close'] > vwap_now:
                    trade.book(bkt, 'VWAP_EXIT', n5['close'], o5['close'], trade.lots_remaining)
                    break

        elif exit_model == 'velvet_dual':
            # Velvet Rope
            if (not trade.tr_armed) and o5['high'] >= trade.entry_premium + RATCHET_INITIAL_PTS:
                trade.tr_armed = True
                trade.tr_sl = trade.entry_premium + VELVET_ROPE_BE_OFFSET
                if o5['low'] <= trade.tr_sl:
                    trade.book(bkt, 'VELVET_ROPE_SL', n5['close'], trade.tr_sl, trade.lots_remaining)
                    break
            if trade.tr_armed and o5['low'] <= trade.tr_sl:
                trade.book(bkt, 'VELVET_ROPE_SL', n5['close'], trade.tr_sl, trade.lots_remaining)
                break
            # VWAP trail
            vwap_now = vwap_by_bkt.get(bkt)
            if vwap_now is not None and o5['close'] >= trade.entry_premium + 10:
                if trade.side == 'CE' and n5['close'] < vwap_now:
                    trade.book(bkt, 'DUAL_VWAP_EXIT', n5['close'], o5['close'], trade.lots_remaining)
                    break
                elif trade.side == 'PE' and n5['close'] > vwap_now:
                    trade.book(bkt, 'DUAL_VWAP_EXIT', n5['close'], o5['close'], trade.lots_remaining)
                    break
            # 15m SMA8 trail
            if bkt % 3 == 2 and bkt >= 3*SMA_TRAIL_PERIOD - 1:
                o15 = opt_15m_from_5m(opt_5m, bkt)
                if len(o15) >= SMA_TRAIL_PERIOD:
                    sma8L = sma_last([b['l'] for b in o15], SMA_TRAIL_PERIOD)
                    if sma8L is not None and o15[-1]['c'] < sma8L:
                        trade.book(bkt, 'DUAL_SMA8_EXIT', n5['close'], o5['close'], trade.lots_remaining)
                        break

        elif exit_model == 'fixed_be_sma15m':
            # Soft BE: when premium touches +15, lock SL at entry+5
            if (not trade.tr_armed) and o5['high'] >= trade.entry_premium + RATCHET_INITIAL_PTS:
                trade.tr_armed = True
                trade.tr_sl = trade.entry_premium + 5
                if o5['low'] <= trade.tr_sl:
                    trade.book(bkt, 'SOFT_BE_SL', n5['close'], trade.tr_sl, trade.lots_remaining)
                    break
            if trade.tr_armed and o5['low'] <= trade.tr_sl:
                trade.book(bkt, 'SOFT_BE_SL', n5['close'], trade.tr_sl, trade.lots_remaining)
                break
            # Normal 15m SMA8 trail
            if bkt % 3 == 2 and bkt >= 3*SMA_TRAIL_PERIOD - 1:
                o15 = opt_15m_from_5m(opt_5m, bkt)
                if len(o15) >= SMA_TRAIL_PERIOD:
                    sma8L = sma_last([b['l'] for b in o15], SMA_TRAIL_PERIOD)
                    if sma8L is not None and o15[-1]['c'] < sma8L:
                        trade.book(bkt, 'SMA8_TRAIL', n5['close'], o5['close'], trade.lots_remaining)
                        break

        elif exit_model == 'sma8_plock':
            # HARDSL (above) + profit-lock + 15m SMA8(low) trail
            # Profit-lock:
            #   - Arm when intra-bar high >= entry + PROFIT_LOCK_TRIGGER
            #   - If PROFIT_LOCK_HARD: exit immediately at entry + PROFIT_LOCK_TRIGGER on the arming bar
            #   - Else: set SL floor = entry + PROFIT_LOCK_FLOOR. If later bar low <= floor -> exit at floor
            if not trade.profit_lock_armed and o5['high'] >= trade.entry_premium + PROFIT_LOCK_TRIGGER:
                trade.profit_lock_armed = True
                trade.profit_lock_price = trade.entry_premium + PROFIT_LOCK_FLOOR
                if PROFIT_LOCK_HARD:
                    target_price = trade.entry_premium + PROFIT_LOCK_TRIGGER
                    trade.book(bkt, f'PROFIT_TARGET_+{PROFIT_LOCK_TRIGGER}', n5['close'], target_price, trade.lots_remaining)
                    break
            if trade.profit_lock_armed and o5['low'] <= trade.profit_lock_price:
                trade.book(bkt, f'PROFIT_LOCK_+{PROFIT_LOCK_FLOOR}', n5['close'], trade.profit_lock_price, trade.lots_remaining)
                break
            # SMA8 trail
            if bkt % 3 == 2 and bkt >= 3*SMA_TRAIL_PERIOD - 1:
                o15 = opt_15m_from_5m(opt_5m, bkt)
                if len(o15) >= SMA_TRAIL_PERIOD:
                    lows = [b['l'] for b in o15]
                    sma8L = sma_last(lows, SMA_TRAIL_PERIOD)
                    last15c = o15[-1]['c']
                    if sma8L is not None and last15c < sma8L:
                        trade.book(bkt, 'SMA8_LOW_TRAIL', n5['close'], o5['close'], trade.lots_remaining)
                        break

        # 3) FLIP Path A — checked AFTER exit_model so intra-bar HARDSL/Ratchet/Trail
        # get chronological priority. Only fires if trade still open at this 15m close.
        if ((not trade.closed) and FLIP_ENABLED
                and bkt % 3 == 2 and k_lookup is not None):
            elapsed_min = (bkt - trade.entry_bkt) * 5
            if elapsed_min >= FLIP_PATH_A_ELAPSED:
                peak_ok = trade.peak_prem >= trade.entry_premium + FLIP_PATH_A_PEAK_MIN
                drop_ok = o5['close'] <= trade.entry_premium + FLIP_PATH_A_DROP_MAX
                if peak_ok and drop_ok:
                    k_now  = k_lookup.get(bkt)
                    k_prev = k_lookup.get(bkt - 3)
                    if k_now is not None and k_prev is not None:
                        if trade.side == 'CE':
                            opposite_ok = (k_now < k_prev and
                                           FLIP_K_CE_TO_PE_MIN <= k_now <= FLIP_K_CE_TO_PE_MAX)
                            if opposite_ok:
                                trade.book(bkt, 'FLIP_TO_PE', n5['close'], o5['close'], trade.lots_remaining)
                                break
                        else:  # side == 'PE'
                            opposite_ok = (k_now > k_prev and k_now >= FLIP_K_PE_TO_CE_MIN)
                            if opposite_ok:
                                trade.book(bkt, 'FLIP_TO_CE', n5['close'], o5['close'], trade.lots_remaining)
                                break

    if not trade.closed:
        # Final close at last bar
        last_n = nifty_5m[-1]
        last_o = opt_5m[-1]
        trade.book(last_n['bucket'], 'EOD', last_n['close'], last_o['close'], trade.lots_remaining)

    return trade


# -------------------- Strike selection --------------------
def select_strike(spot, side, atm_day, use_delta_shift, opt_5m_dict):
    """
    Returns strike present in opt_5m_dict, or None.
    use_delta_shift=True: CE -> atm - ITM_OFFSET, PE -> atm + ITM_OFFSET
    Otherwise: ATM (round to 100, then snap to nearest available 50-step strike).
    """
    if use_delta_shift:
        if side == 'CE':
            target = atm_day - ITM_OFFSET
        else:
            target = atm_day + ITM_OFFSET
    else:
        # ATM
        target = int(round(spot / ATM_STEP)) * ATM_STEP
    # Snap to nearest strike present in dict
    avail = sorted({k[0] for k in opt_5m_dict.keys() if k[1] == side})
    if not avail: return None
    return min(avail, key=lambda s: abs(s - target))


# (Framework v0.2 load banner removed — dead module-level print)


# -------------------- Flip helpers --------------------
def _check_flip_eligibility(trade: Trade, at_bkt: int, day_data: dict) -> Optional[str]:
    """Returns 'CE' or 'PE' if a flip should be triggered after `trade` exited at `at_bkt`.
    None otherwise."""
    if not FLIP_ENABLED:
        return None
    k_lookup = day_data.get('_k_lookup', {}) or {}
    if not k_lookup:
        return None
    # Find the latest 15m-close key <= at_bkt (in 5m-bucket terms)
    candidates = [k for k in k_lookup.keys() if k <= at_bkt]
    if not candidates:
        return None
    k_at = max(candidates)
    k_prev_5m = k_at - 3
    if k_prev_5m not in k_lookup:
        return None
    k_now = k_lookup[k_at]
    k_prev = k_lookup[k_prev_5m]
    if trade.side == 'CE':
        if k_now < k_prev and FLIP_K_CE_TO_PE_MIN <= k_now <= FLIP_K_CE_TO_PE_MAX:
            return 'PE'
    elif trade.side == 'PE':
        if k_now > k_prev and k_now >= FLIP_K_PE_TO_CE_MIN:
            return 'CE'
    return None

def _try_flip_cascade(last_trade: Trade, day_data: dict, exit_model: str, flips_today: int = 0,
                      vwap_by_bkt: Optional[dict] = None) -> list:
    """Recursively attempt flips after a trade closes.
    Returns list of flip trades created. Each is grade='FLIP'.
    Empty list if no flip eligible.
    """
    if not FLIP_ENABLED or last_trade is None or not last_trade.exits:
        return []
    if MAX_FLIPS_PER_DAY is not None and flips_today >= MAX_FLIPS_PER_DAY:
        return []
    nifty_5m = sorted(day_data['nifty_5m'], key=lambda b: b['bucket'])
    n_by = {b['bucket']: b for b in nifty_5m}
    flip_trades = []
    prev = last_trade
    while True:
        exit_bkt = prev.exits[-1]['bkt']
        next_bkt = exit_bkt + 1
        if next_bkt > FORCE_CLOSE_BUCKET - 2:
            break  # too close to force-close to bother
        flip_side = _check_flip_eligibility(prev, exit_bkt, day_data)
        if flip_side is None:
            break
        if next_bkt not in n_by:
            break
        bar5 = n_by[next_bkt]
        strike = select_strike(bar5['open'], flip_side, day_data['atm'], False, day_data['opt_5m'])
        if strike is None or (strike, flip_side) not in day_data['opt_5m']:
            break
        opt_bars = sorted(day_data['opt_5m'][(strike, flip_side)], key=lambda b: b['bucket'])
        opt_by = {b['bucket']: b for b in opt_bars}
        entry_premium = opt_by.get(next_bkt, {}).get('open')
        if entry_premium is None or entry_premium <= 0:
            break
        flip_t = Trade(
            day=last_trade.day, side=flip_side, grade='FLIP',
            entry_bkt=next_bkt, entry_nifty=bar5['open'],
            entry_premium=entry_premium, strike=strike,
            trigger_level=0, targets=[],
            lots=2, lots_remaining=2,
            hardsl_premium=hardsl_floor(entry_premium),
            peak_prem=entry_premium,
        )
        flip_t = simulate_trade(flip_t, day_data, exit_model, vwap_by_bkt=vwap_by_bkt)
        flip_trades.append(flip_t)
        prev = flip_t
        flips_today += 1
        if MAX_FLIPS_PER_DAY is not None and flips_today >= MAX_FLIPS_PER_DAY:
            break
        # Loop continues — chain another flip if K conditions still favor
    return flip_trades

def _is_flip_related(trade: Trade) -> bool:
    """Returns True if this trade should NOT count toward circuit breaker."""
    if trade.grade == 'FLIP':
        return True
    if trade.exits:
        last_reason = trade.exits[-1].get('reason', '')
        if last_reason.startswith('FLIP_TO_'):
            return True
    return False

def _bkt_in_skip_hour(bkt: int) -> bool:
    """Returns True if bkt falls inside hour 13 (13:00-13:59) and SKIP_HOUR_13 is set."""
    if not SKIP_HOUR_13:
        return False
    abs_min = 9*60 + 15 + bkt * 5
    return (abs_min // 60) == 13

def _day_in_skip_dow(day_obj) -> bool:
    """Returns True if day is a Tuesday and SKIP_TUESDAYS is set."""
    if not SKIP_TUESDAYS:
        return False
    if hasattr(day_obj, 'weekday'):
        return day_obj.weekday() == 1
    if isinstance(day_obj, str):
        from datetime import datetime
        s = day_obj.split('T')[0].split(' ')[0]
        try:
            return datetime.strptime(s, '%Y-%m-%d').weekday() == 1
        except Exception:
            return False
    return False


def _chop_filter_blocks(bkt: int, nifty_by_bkt: dict, n15_by_bkt: dict, v2_ctx) -> bool:
    """Returns True if chop filter blocks entry at this bucket.

    Modes:
      'off'             — no blocking
      'adx20'           — block if latest 1h ADX < 20
      'adx25'           — block if latest 1h ADX < 25
      'rsi_band'        — block if latest 1h RSI in [CHOP_RSI_LO, CHOP_RSI_HI]
      'range_tight'     — block (after CHOP_RANGE_AFTER_BKT) if realized range/open < CHOP_RANGE_PCT_MIN
      'k_oscillation'   — block if today's 15m K has crossed 38/80 >= CHOP_K_CROSS_MAX times
      'adx25_range'     — block if BOTH adx25 AND range_tight conditions met
      'adx20_rsi'       — block if BOTH adx20 AND rsi_band conditions met
    """
    if CHOP_FILTER_MODE == 'off':
        return False

    # Get latest 1h close metrics
    adx_last = None
    rsi_last = None
    if v2_ctx and v2_ctx.get('today_1h') is not None and len(v2_ctx['today_1h']) > 0:
        t1h = v2_ctx['today_1h']
        closed = t1h[t1h['bucket'] + 12 <= bkt + 1]
        if len(closed) > 0:
            cand = closed.iloc[-1]
            adx_v = cand.get('ADX')
            if adx_v is not None and not pd.isna(adx_v):
                adx_last = float(adx_v)
            rsi_v = cand.get('RSI')
            if rsi_v is not None and not pd.isna(rsi_v):
                rsi_last = float(rsi_v)
    if adx_last is None and v2_ctx and v2_ctx.get('last_prior_1h') is not None:
        cand = v2_ctx['last_prior_1h']
        adx_v = cand.get('ADX')
        if adx_v is not None and not pd.isna(adx_v):
            adx_last = float(adx_v)
        rsi_v = cand.get('RSI')
        if rsi_v is not None and not pd.isna(rsi_v):
            rsi_last = float(rsi_v)

    # ADX-only filters
    if CHOP_FILTER_MODE == 'adx20':
        return adx_last is not None and adx_last < 20
    if CHOP_FILTER_MODE == 'adx25':
        return adx_last is not None and adx_last < 25

    # RSI band filter
    if CHOP_FILTER_MODE == 'rsi_band':
        return rsi_last is not None and CHOP_RSI_LO <= rsi_last <= CHOP_RSI_HI

    # Range-tight filter
    if CHOP_FILTER_MODE == 'range_tight':
        if bkt < CHOP_RANGE_AFTER_BKT:
            return False  # need warmup
        return _realized_range_below(bkt, nifty_by_bkt, CHOP_RANGE_PCT_MIN)

    # K oscillation filter
    if CHOP_FILTER_MODE == 'k_oscillation':
        return _k_cross_count_today(bkt, n15_by_bkt) >= CHOP_K_CROSS_MAX

    # Combined: ADX<25 AND tight range
    if CHOP_FILTER_MODE == 'adx25_range':
        adx_low = adx_last is not None and adx_last < 25
        tight   = bkt >= CHOP_RANGE_AFTER_BKT and _realized_range_below(bkt, nifty_by_bkt, CHOP_RANGE_PCT_MIN)
        return adx_low and tight

    # Combined: ADX<20 AND RSI in indecision band
    if CHOP_FILTER_MODE == 'adx20_rsi':
        adx_low = adx_last is not None and adx_last < 20
        rsi_mid = rsi_last is not None and CHOP_RSI_LO <= rsi_last <= CHOP_RSI_HI
        return adx_low and rsi_mid

    return False


def _realized_range_below(bkt: int, nifty_by_bkt: dict, pct_threshold: float) -> bool:
    """Returns True if realized range (high-low so far) / open < pct_threshold/100."""
    bars = [nifty_by_bkt[b] for b in range(bkt + 1) if b in nifty_by_bkt]
    if len(bars) < 2:
        return False
    day_open = bars[0]['open']
    if day_open <= 0:
        return False
    day_high = max(b['high'] for b in bars)
    day_low  = min(b['low']  for b in bars)
    rng_pct = (day_high - day_low) / day_open * 100
    return rng_pct < pct_threshold


def _k_cross_count_today(bkt: int, n15_by_bkt: dict) -> int:
    """Count K crossings of 38 or 80 in today's 15m bars up to current bkt."""
    # n15_by_bkt keys are 15m bucket starts (every 3 5m buckets)
    bars_so_far = []
    for b15, bar in n15_by_bkt.items():
        if b15 <= bkt:
            bars_so_far.append(bar)
    bars_so_far.sort(key=lambda b: b.get('bucket', 0) if isinstance(b, dict) else 0)
    if len(bars_so_far) < 2:
        return 0
    crosses = 0
    prev_K = None
    for bar in bars_so_far:
        K = bar.get('K') if isinstance(bar, dict) else None
        if K is None or (isinstance(K, float) and (K != K)):
            continue
        if prev_K is not None:
            if (prev_K < 38 and K >= 38) or (prev_K >= 38 and K < 38):
                crosses += 1
            if (prev_K < 80 and K >= 80) or (prev_K >= 80 and K < 80):
                crosses += 1
        prev_K = K
    return crosses


# -------------------- Per-day driver --------------------
def run_day(day_date, day_data, df1h_prior_all, entry_model: str, exit_model: str,
            use_delta_shift: bool, optional_filters: dict = None, v2_ctx=None):
    """
    Execute one trading day end-to-end.
    Returns list of completed Trade objects.

    entry_model: 'v23' (cluster Grade A/B) or 'v24' (5m level break + MACD + premSMA8)
    exit_model:  'v23' (T1/T2/T3) or 'v24' (BE/trail/HardSL)
    use_delta_shift: only meaningful for entry_model='v24' (per user spec) or
                     can be tested with v23 entry too. Per user: Combo 3 only.
    optional_filters: {'first30': bool, 'peaktime': bool}
    """
    filters = optional_filters or {}
    trades = []
    daily_losses = 0
    halt = False
    fired_levels = set()
    active = None

    # ---- Prior day OHLC + levels (V2.3 method)
    if df1h_prior_all is None or len(df1h_prior_all) == 0:
        return trades
    pdh = float(df1h_prior_all['high'].iloc[-7:].max())
    pdl = float(df1h_prior_all['low'].iloc[-7:].min())
    pdc = float(df1h_prior_all['close'].iloc[-1])
    levels_v23 = compute_levels_for_day(df1h_prior_all, {'H': pdh, 'L': pdl, 'C': pdc})
    levels_v24_list = v24_compute_levels({'H': pdh, 'L': pdl, 'C': pdc})

    # ---- Regime (V2.3 only): from last closed prior 1h bar
    regime = classify_regime(df1h_prior_all.iloc[-1])
    if entry_model == 'v23' and not regime_allows_trade(regime):
        return trades  # regime blocks, but only for V2.3 entry path    # ---- Today's data
    nifty_5m = sorted(day_data['nifty_5m'], key=lambda b: b['bucket'])
    vwap_by_bkt = compute_vwap_by_bkt(nifty_5m)
    nifty_15m = sorted(day_data['nifty_15m'], key=lambda b: b['bucket'])
    nifty_by_bkt = {b['bucket']: b for b in nifty_5m}
    n15_by_bkt = {b['bucket']: b for b in nifty_15m}
    atm_day = day_data['atm']

    # Gap suppression: V2.3 spec — until 10:15 if |gap|>1%
    today_open = nifty_5m[0]['open']
    gap_pct = (today_open / pdc) - 1
    gap_suppress_until = 12 if abs(gap_pct) > GAP_THRESHOLD_PCT else -1
    # bucket 12 closes at 10:20 (close-time of bucket 11 is 10:15). Use bucket 12 as first allowed.

    # First-30 direction (always computed; used by entry_model='f1' and by F1 overlay filter)
    first30_dir = None
    if 5 in nifty_by_bkt:
        close_945 = nifty_by_bkt[5]['close']
        move_pct = (close_945 - today_open) / today_open
        if abs(move_pct) >= 0.003:
            first30_dir = 'CE' if move_pct > 0 else 'PE'

    # Peak-time filter: skip 10:45 - 13:10
    def peaktime_block(bkt):
        if not filters.get('peaktime'): return False
        # bucket 18 closes 10:45; bucket 47 closes 13:10
        return 18 <= bkt <= 47

    # ---- Iterate 5m buckets in order
    next_allowed_bkt = 0
    for bkt in range(len(nifty_5m)):
        bar5 = nifty_by_bkt.get(bkt)
        if bar5 is None: continue
        if bkt > ENTRY_WINDOW_END_BKT and active is None:
            break  # past entry window, no more entries
        # Hold-out window after a trade closes (one position at a time)
        if bkt < next_allowed_bkt: continue

        # ---- Active trade update happens inside simulate_trade once we ENTER.
        #      Here we just check whether to enter.
        if active is not None:
            continue  # one position at a time; simulate_trade walks the trade to its exit

        if halt: continue
        if bkt < gap_suppress_until: continue
        if peaktime_block(bkt): continue
        if _bkt_in_skip_hour(bkt): continue
        if _day_in_skip_dow(day_date): continue
        if _chop_filter_blocks(bkt, nifty_by_bkt, n15_by_bkt, v2_ctx): continue

        # ---- ENTRY: COMBINED  V2 + V3 (V2V3_PRIORITY decides same-bar tiebreak)
        if entry_model == 'v2_v3':
            if bkt % 3 != 2: continue
            k15_bucket = bkt - 2

            # Pre-compute both signals on this 15m close, then dispatch by priority
            sig_v3 = None
            if regime_allows_trade(regime):
                n15 = n15_by_bkt.get(k15_bucket)
                if n15 is not None:
                    for role, lvl_obj in [('G', levels_v23['G']), ('R', levels_v23['R'])]:
                        if lvl_obj is None or lvl_obj['center'] in fired_levels: continue
                        sig = detect_v23_signal(n15, lvl_obj, role)
                        if sig is None: continue
                        sig_dir_v3 = 'CE' if 'CE' in sig['kind'] else 'PE'
                        sig_v3 = (sig_dir_v3, lvl_obj, sig['grade'])
                        break

            # V2 signal
            sig_v2 = None
            t1h = v2_ctx['today_1h'] if v2_ctx else None
            cand = None
            if t1h is not None and len(t1h) > 0:
                today_closed = t1h[t1h['bucket'] + 12 <= bkt + 1]
                if len(today_closed) > 0:
                    cand = today_closed.iloc[-1]
            if cand is None and v2_ctx and v2_ctx.get('last_prior_1h') is not None:
                cand = v2_ctx['last_prior_1h']
            if cand is not None:
                b1h_close = cand['close']; b1h_sma20 = cand.get('SMA20'); b1h_sma50 = cand.get('SMA50')
                if not (pd.isna(b1h_sma20) or pd.isna(b1h_sma50)):
                    t15 = v2_ctx['today_15m']
                    row_K_now = t15[t15['bucket'] == k15_bucket]
                    if len(row_K_now) > 0 and not pd.isna(row_K_now['K'].iloc[0]):
                        K_now = float(row_K_now['K'].iloc[0])
                        row_K_prev = t15[t15['bucket'] == k15_bucket - 3]
                        K_prev = None
                        if len(row_K_prev) > 0 and not pd.isna(row_K_prev['K'].iloc[0]):
                            K_prev = float(row_K_prev['K'].iloc[0])
                        elif v2_ctx.get('prior_15m_for_K_prev') is not None and not pd.isna(v2_ctx['prior_15m_for_K_prev'].get('K')):
                            K_prev = float(v2_ctx['prior_15m_for_K_prev']['K'])
                        if K_prev is not None:
                            ce_regime = b1h_close > b1h_sma20
                            pe_regime = (b1h_close < b1h_sma20) and (b1h_close < b1h_sma50)
                            sig_ce = ce_regime and (K_now >= STOCHRSI_CE_LO) and (K_now > K_prev)
                            sig_pe = pe_regime and (K_now <= STOCHRSI_PE_HI) and (K_now < K_prev)
                            if V2_K_CAP_CE   is not None: sig_ce = sig_ce and (K_now <= V2_K_CAP_CE)
                            if V2_K_FLOOR_PE is not None: sig_pe = sig_pe and (K_now >= V2_K_FLOOR_PE)
                            if not (sig_ce and sig_pe):
                                if sig_ce: sig_v2 = 'CE'
                                elif sig_pe: sig_v2 = 'PE'

            # Dispatch: priority decides which signal to take if both present
            chosen = None
            if sig_v2 and sig_v3:
                chosen = 'V2' if V2V3_PRIORITY == 'v2' else 'V3'
            elif sig_v2:
                chosen = 'V2'
            elif sig_v3:
                chosen = 'V3'
            if chosen is None: continue

            if chosen == 'V3':
                sig_dir, lvl_obj, grade = sig_v3
                if bkt + 1 not in nifty_by_bkt: continue
                entry_nifty = nifty_by_bkt[bkt + 1]['open']
                strike = select_strike(bar5['close'], sig_dir, atm_day, False, day_data['opt_5m'])
                if strike is None: continue
                if (strike, sig_dir) not in day_data['opt_5m']: continue
                opt_bars = sorted(day_data['opt_5m'][(strike, sig_dir)], key=lambda b: b['bucket'])
                opt_by = {b['bucket']: b for b in opt_bars}
                entry_premium = opt_by.get(bkt + 1, {}).get('open')
                if entry_premium is None or entry_premium <= 0: continue
                targets = compute_targets(lvl_obj, sig_dir, levels_v23['all_clusters'])
                if sig_dir == 'CE' and entry_nifty >= targets[0] - 10: continue
                if sig_dir == 'PE' and entry_nifty <= targets[0] + 10: continue
                t = Trade(
                    day=day_date, side=sig_dir, grade=f'V3_{grade}',
                    entry_bkt=bkt + 1, entry_nifty=entry_nifty,
                    entry_premium=entry_premium, strike=strike,
                    trigger_level=lvl_obj['center'], targets=targets,
                    lots=2, lots_remaining=2,
                    hardsl_premium=hardsl_floor(entry_premium),
                    peak_prem=entry_premium,
                )
                t = simulate_trade(t, day_data, exit_model, vwap_by_bkt=vwap_by_bkt)
                trades.append(t)
                _flips = _try_flip_cascade(t, day_data, exit_model, flips_today=flips_today, vwap_by_bkt=vwap_by_bkt)
                for _ft in _flips: trades.append(_ft)
                flips_today += len(_flips)
                _last = _flips[-1] if _flips else t
                next_allowed_bkt = (_last.exits[-1]['bkt'] + 1) if _last.exits else (bkt + 1)
                fired_levels.add(lvl_obj['center'])
                if (not _is_flip_related(t)) and t.pnl_prem_per_lot() < 0:
                    daily_losses += 1
                    if daily_losses >= CIRCUIT_BREAKER: halt = True
                continue
            else:  # V2
                sig_dir = sig_v2
                strike = select_strike(bar5['close'], sig_dir, atm_day, False, day_data['opt_5m'])
                if strike is None: continue
                if bkt + 1 not in nifty_by_bkt: continue
                entry_nifty = nifty_by_bkt[bkt + 1]['open']
                if (strike, sig_dir) not in day_data['opt_5m']: continue
                opt_bars = sorted(day_data['opt_5m'][(strike, sig_dir)], key=lambda b: b['bucket'])
                opt_by = {b['bucket']: b for b in opt_bars}
                entry_premium = opt_by.get(bkt + 1, {}).get('open')
                if entry_premium is None or entry_premium <= 0: continue
                t = Trade(
                    day=day_date, side=sig_dir, grade='V2',
                    entry_bkt=bkt + 1, entry_nifty=entry_nifty,
                    entry_premium=entry_premium, strike=strike,
                    trigger_level=cand.get('SMA20', 0), targets=[],
                    lots=2, lots_remaining=2,
                    hardsl_premium=hardsl_floor(entry_premium),
                    peak_prem=entry_premium,
                )
                t = simulate_trade(t, day_data, exit_model, vwap_by_bkt=vwap_by_bkt)
                trades.append(t)
                _flips = _try_flip_cascade(t, day_data, exit_model, flips_today=flips_today, vwap_by_bkt=vwap_by_bkt)
                for _ft in _flips: trades.append(_ft)
                flips_today += len(_flips)
                _last = _flips[-1] if _flips else t
                next_allowed_bkt = (_last.exits[-1]['bkt'] + 1) if _last.exits else (bkt + 1)
                if (not _is_flip_related(t)) and t.pnl_prem_per_lot() < 0:
                    daily_losses += 1
                    if daily_losses >= CIRCUIT_BREAKER: halt = True
                continue

        # ---- ENTRY: COMBINED  V3+F1 (priority) OR V2 (fallback). Single position at a time.
        if entry_model == 'v2_v3f1':
            # Both V2 and V3 paths fire at 15m closes
            if bkt % 3 != 2: continue
            k15_bucket = bkt - 2

            # First, try V3+F1 (mandatory F1 alignment + regime gate)
            sig_v3 = None
            if first30_dir is not None and regime_allows_trade(regime):
                n15 = n15_by_bkt.get(k15_bucket)
                if n15 is not None:
                    for role, lvl_obj in [('G', levels_v23['G']), ('R', levels_v23['R'])]:
                        if lvl_obj is None or lvl_obj['center'] in fired_levels: continue
                        sig = detect_v23_signal(n15, lvl_obj, role)
                        if sig is None: continue
                        sig_dir_v3 = 'CE' if 'CE' in sig['kind'] else 'PE'
                        if sig_dir_v3 != first30_dir: continue
                        sig_v3 = (sig_dir_v3, lvl_obj, sig['grade'])
                        break

            if sig_v3:
                sig_dir, lvl_obj, grade = sig_v3
                if bkt + 1 not in nifty_by_bkt: continue
                entry_nifty = nifty_by_bkt[bkt + 1]['open']
                strike = select_strike(bar5['close'], sig_dir, atm_day, False, day_data['opt_5m'])
                if strike is None: continue
                if (strike, sig_dir) not in day_data['opt_5m']: continue
                opt_bars = sorted(day_data['opt_5m'][(strike, sig_dir)], key=lambda b: b['bucket'])
                opt_by = {b['bucket']: b for b in opt_bars}
                entry_premium = opt_by.get(bkt + 1, {}).get('open')
                if entry_premium is None or entry_premium <= 0: continue
                targets = compute_targets(lvl_obj, sig_dir, levels_v23['all_clusters'])
                # Skip if already past T1
                if sig_dir == 'CE' and entry_nifty >= targets[0] - 10: continue
                if sig_dir == 'PE' and entry_nifty <= targets[0] + 10: continue
                t = Trade(
                    day=day_date, side=sig_dir, grade=f'V3F1_{grade}',
                    entry_bkt=bkt + 1, entry_nifty=entry_nifty,
                    entry_premium=entry_premium, strike=strike,
                    trigger_level=lvl_obj['center'], targets=targets,
                    lots=2, lots_remaining=2,
                    hardsl_premium=hardsl_floor(entry_premium),
                    peak_prem=entry_premium,
                )
                t = simulate_trade(t, day_data, exit_model, vwap_by_bkt=vwap_by_bkt)
                trades.append(t)
                _flips = _try_flip_cascade(t, day_data, exit_model, flips_today=flips_today, vwap_by_bkt=vwap_by_bkt)
                for _ft in _flips: trades.append(_ft)
                flips_today += len(_flips)
                _last = _flips[-1] if _flips else t
                next_allowed_bkt = (_last.exits[-1]['bkt'] + 1) if _last.exits else (bkt + 1)
                fired_levels.add(lvl_obj['center'])
                if (not _is_flip_related(t)) and t.pnl_prem_per_lot() < 0:
                    daily_losses += 1
                    if daily_losses >= CIRCUIT_BREAKER: halt = True
                continue

            # Fall through: V2 signal
            t1h = v2_ctx['today_1h'] if v2_ctx else None
            cand = None
            if t1h is not None and len(t1h) > 0:
                today_closed = t1h[t1h['bucket'] + 12 <= bkt + 1]
                if len(today_closed) > 0:
                    cand = today_closed.iloc[-1]
            if cand is None and v2_ctx and v2_ctx.get('last_prior_1h') is not None:
                cand = v2_ctx['last_prior_1h']
            if cand is None: continue
            b1h_close = cand['close']
            b1h_sma20 = cand.get('SMA20')
            b1h_sma50 = cand.get('SMA50')
            if pd.isna(b1h_sma20) or pd.isna(b1h_sma50): continue
            t15 = v2_ctx['today_15m']
            row_K_now = t15[t15['bucket'] == k15_bucket]
            if len(row_K_now) == 0 or pd.isna(row_K_now['K'].iloc[0]): continue
            K_now = float(row_K_now['K'].iloc[0])
            row_K_prev = t15[t15['bucket'] == k15_bucket - 3]
            if len(row_K_prev) == 0 or pd.isna(row_K_prev['K'].iloc[0]):
                if v2_ctx.get('prior_15m_for_K_prev') is not None and not pd.isna(v2_ctx['prior_15m_for_K_prev'].get('K')):
                    K_prev = float(v2_ctx['prior_15m_for_K_prev']['K'])
                else: continue
            else:
                K_prev = float(row_K_prev['K'].iloc[0])
            k_rising  = K_now > K_prev
            k_falling = K_now < K_prev
            ce_regime = b1h_close > b1h_sma20
            pe_regime = (b1h_close < b1h_sma20) and (b1h_close < b1h_sma50)
            sig_ce = ce_regime and (K_now >= STOCHRSI_CE_LO) and k_rising
            sig_pe = pe_regime and (K_now <= STOCHRSI_PE_HI) and k_falling
            if V2_K_CAP_CE   is not None: sig_ce = sig_ce and (K_now <= V2_K_CAP_CE)
            if V2_K_FLOOR_PE is not None: sig_pe = sig_pe and (K_now >= V2_K_FLOOR_PE)
            if sig_ce and sig_pe: continue
            if not (sig_ce or sig_pe): continue
            sig_dir = 'CE' if sig_ce else 'PE'
            strike = select_strike(bar5['close'], sig_dir, atm_day, False, day_data['opt_5m'])
            if strike is None: continue
            if bkt + 1 not in nifty_by_bkt: continue
            entry_nifty = nifty_by_bkt[bkt + 1]['open']
            if (strike, sig_dir) not in day_data['opt_5m']: continue
            opt_bars = sorted(day_data['opt_5m'][(strike, sig_dir)], key=lambda b: b['bucket'])
            opt_by = {b['bucket']: b for b in opt_bars}
            entry_premium = opt_by.get(bkt + 1, {}).get('open')
            if entry_premium is None or entry_premium <= 0: continue
            t = Trade(
                day=day_date, side=sig_dir, grade='V2',
                entry_bkt=bkt + 1, entry_nifty=entry_nifty,
                entry_premium=entry_premium, strike=strike,
                trigger_level=b1h_sma20, targets=[],
                lots=2, lots_remaining=2,
                hardsl_premium=hardsl_floor(entry_premium),
                peak_prem=entry_premium,
            )
            t = simulate_trade(t, day_data, exit_model, vwap_by_bkt=vwap_by_bkt)
            trades.append(t)
            _flips = _try_flip_cascade(t, day_data, exit_model, flips_today=flips_today, vwap_by_bkt=vwap_by_bkt)
            for _ft in _flips: trades.append(_ft)
            flips_today += len(_flips)
            _last = _flips[-1] if _flips else t
            next_allowed_bkt = (_last.exits[-1]['bkt'] + 1) if _last.exits else (bkt + 1)
            if (not _is_flip_related(t)) and t.pnl_prem_per_lot() < 0:
                daily_losses += 1
                if daily_losses >= CIRCUIT_BREAKER: halt = True
            continue

        # ---- ENTRY: F1-as-entry (first-30min directional momentum signal itself)
        if entry_model == 'f1':
            # Fire exactly once per day at the close of 5m bucket 5 (9:45)
            if bkt != 5: continue
            if first30_dir is None: continue  # |move| < 0.3% threshold not met
            sig_dir = first30_dir
            # Enter at next 5m OPEN (bucket 6, which opens 9:45)
            if bkt + 1 not in nifty_by_bkt: continue
            entry_nifty = nifty_by_bkt[bkt + 1]['open']
            strike = select_strike(bar5['close'], sig_dir, atm_day, use_delta_shift, day_data['opt_5m'])
            if strike is None: continue
            if (strike, sig_dir) not in day_data['opt_5m']: continue
            opt_bars = sorted(day_data['opt_5m'][(strike, sig_dir)], key=lambda b: b['bucket'])
            opt_by = {b['bucket']: b for b in opt_bars}
            entry_premium = opt_by.get(bkt + 1, {}).get('open')
            if entry_premium is None or entry_premium <= 0: continue
            t = Trade(
                day=day_date, side=sig_dir, grade='F1',
                entry_bkt=bkt + 1, entry_nifty=entry_nifty,
                entry_premium=entry_premium, strike=strike,
                trigger_level=today_open, targets=[],
                lots=2, lots_remaining=2,
                hardsl_premium=hardsl_floor(entry_premium),
                peak_prem=entry_premium,
            )
            t = simulate_trade(t, day_data, exit_model, vwap_by_bkt=vwap_by_bkt)
            trades.append(t)
            _flips = _try_flip_cascade(t, day_data, exit_model, flips_today=flips_today, vwap_by_bkt=vwap_by_bkt)
            for _ft in _flips: trades.append(_ft)
            flips_today += len(_flips)
            _last = _flips[-1] if _flips else t
            next_allowed_bkt = (_last.exits[-1]['bkt'] + 1) if _last.exits else (bkt + 1)
            if (not _is_flip_related(t)) and t.pnl_prem_per_lot() < 0:
                daily_losses += 1
                if daily_losses >= CIRCUIT_BREAKER:
                    halt = True
            continue

        # ---- ENTRY: V2 (T10/V2.2) path — 1h SMA regime + 15m StochRSI K
        if entry_model == 'v2':
            # Trigger at 15m close: bkt%3==2 in 5m units
            if bkt % 3 != 2: continue
            k15_bucket = bkt - 2   # in 5m units; matches df15 'bucket' column for today

            # Last closed 1h: from today's 1h with bucket+12 <= bkt+1, else prior day's last 1h
            t1h = v2_ctx['today_1h'] if v2_ctx else None
            cand = None
            if t1h is not None and len(t1h) > 0:
                today_closed = t1h[t1h['bucket'] + 12 <= bkt + 1]
                if len(today_closed) > 0:
                    cand = today_closed.iloc[-1]
            if cand is None and v2_ctx and v2_ctx.get('last_prior_1h') is not None:
                cand = v2_ctx['last_prior_1h']
            if cand is None: continue
            b1h_close = cand['close']
            b1h_sma20 = cand.get('SMA20')
            b1h_sma50 = cand.get('SMA50')
            if pd.isna(b1h_sma20) or pd.isna(b1h_sma50): continue

            # Last closed 15m K + K_prev from today's 15m (use the just-closed bar)
            t15 = v2_ctx['today_15m']
            row_K_now = t15[t15['bucket'] == k15_bucket]
            if len(row_K_now) == 0 or pd.isna(row_K_now['K'].iloc[0]): continue
            K_now = float(row_K_now['K'].iloc[0])
            # K_prev: previous 15m bar (bucket k15_bucket - 3)
            row_K_prev = t15[t15['bucket'] == k15_bucket - 3]
            if len(row_K_prev) == 0 or pd.isna(row_K_prev['K'].iloc[0]):
                # Try last prior day's 15m K (cross-day continuity for first bar of day)
                if v2_ctx.get('prior_15m_for_K_prev') is not None and not pd.isna(v2_ctx['prior_15m_for_K_prev'].get('K')):
                    K_prev = float(v2_ctx['prior_15m_for_K_prev']['K'])
                else:
                    continue
            else:
                K_prev = float(row_K_prev['K'].iloc[0])

            k_rising  = K_now > K_prev
            k_falling = K_now < K_prev
            ce_regime = b1h_close > b1h_sma20
            pe_regime = (b1h_close < b1h_sma20) and (b1h_close < b1h_sma50)
            sig_ce = ce_regime and (K_now >= STOCHRSI_CE_LO) and k_rising
            sig_pe = pe_regime and (K_now <= STOCHRSI_PE_HI) and k_falling
            if V2_K_CAP_CE   is not None: sig_ce = sig_ce and (K_now <= V2_K_CAP_CE)
            if V2_K_FLOOR_PE is not None: sig_pe = sig_pe and (K_now >= V2_K_FLOOR_PE)
            if sig_ce and sig_pe: continue
            if not (sig_ce or sig_pe): continue
            sig_dir = 'CE' if sig_ce else 'PE'

            # First-30 filter
            if filters.get('first30'):
                if first30_dir is None: continue
                if sig_dir != first30_dir: continue

            # Pick ATM strike
            strike = select_strike(bar5['close'], sig_dir, atm_day, use_delta_shift, day_data['opt_5m'])
            if strike is None: continue

            # Enter at next 5m OPEN
            if bkt + 1 not in nifty_by_bkt: continue
            entry_nifty = nifty_by_bkt[bkt + 1]['open']
            if (strike, sig_dir) not in day_data['opt_5m']: continue
            opt_bars = sorted(day_data['opt_5m'][(strike, sig_dir)], key=lambda b: b['bucket'])
            opt_by = {b['bucket']: b for b in opt_bars}
            entry_premium = opt_by.get(bkt + 1, {}).get('open')
            if entry_premium is None or entry_premium <= 0: continue

            t = Trade(
                day=day_date, side=sig_dir, grade='V2',
                entry_bkt=bkt + 1, entry_nifty=entry_nifty,
                entry_premium=entry_premium, strike=strike,
                trigger_level=b1h_sma20, targets=[],
                lots=2, lots_remaining=2,
                hardsl_premium=hardsl_floor(entry_premium),
                peak_prem=entry_premium,
            )
            t = simulate_trade(t, day_data, exit_model, vwap_by_bkt=vwap_by_bkt)
            trades.append(t)
            _flips = _try_flip_cascade(t, day_data, exit_model, flips_today=flips_today, vwap_by_bkt=vwap_by_bkt)
            for _ft in _flips: trades.append(_ft)
            flips_today += len(_flips)
            _last = _flips[-1] if _flips else t
            next_allowed_bkt = (_last.exits[-1]['bkt'] + 1) if _last.exits else (bkt + 1)
            if (not _is_flip_related(t)) and t.pnl_prem_per_lot() < 0:
                daily_losses += 1
                if daily_losses >= CIRCUIT_BREAKER:
                    halt = True
            continue

        # ---- ENTRY: V2.4 path
        if entry_model == 'v24':
            # need previous 5m closed (bkt-1 if we're "at the close of bkt-1, decide for bkt open")
            # Realistic: at close of bkt, decide; ENTER at bkt+1 OPEN. So check bar5 (closed at end of bkt).
            sig_dir, lvl = v24_detect_5m_break(bar5, levels_v24_list)
            if sig_dir is None or lvl in fired_levels: continue

            # First-30 filter
            if first30_dir is not None and sig_dir != first30_dir: continue
            # If first30 filter active but no direction set: block
            if filters.get('first30') and first30_dir is None: continue

            # MACD gate (5m spot): use indicator on continuous 5m stream
            # We need the MACD at end of bkt; computed during stream build.
            # Look up via df5_indicators (passed externally — see runner)
            macd_line = bar5.get('MACD_line')
            macd_sig  = bar5.get('MACD_sig')
            if MACD_REQUIRE_ALIGN and macd_line is not None and macd_sig is not None:
                if sig_dir == 'CE' and not (macd_line > macd_sig): continue
                if sig_dir == 'PE' and not (macd_line < macd_sig): continue

            # Pick strike (delta-shift if specified)
            strike = select_strike(bar5['close'], sig_dir, atm_day, use_delta_shift, day_data['opt_5m'])
            if strike is None: continue

            # Premium gate: option current 5m close > option 5m SMA8(low)
            # Use cross-day option SMA? No — daily premium history doesn't persist. We use within-day 5m SMA(8,low).
            # Need at least 8 closed 5m option bars.
            opt_bars = sorted(day_data['opt_5m'][(strike, sig_dir)], key=lambda b: b['bucket'])
            opt_by = {b['bucket']: b for b in opt_bars}
            opt_closed_upto = [opt_by[b] for b in range(bkt+1) if b in opt_by]
            if PREM_GATE_REQUIRE and len(opt_closed_upto) < SMA_TRAIL_PERIOD:
                continue
            if PREM_GATE_REQUIRE:
                lows = [b['low'] for b in opt_closed_upto]
                sma8L = sma_last(lows, SMA_TRAIL_PERIOD)
                if sma8L is None or opt_closed_upto[-1]['close'] <= sma8L:
                    continue

            # Enter at next 5m OPEN (bkt+1)
            if bkt + 1 not in nifty_by_bkt: continue
            entry_nifty = nifty_by_bkt[bkt + 1]['open']
            if (strike, sig_dir) not in day_data['opt_5m']: continue
            entry_premium = opt_by.get(bkt + 1, {}).get('open')
            if entry_premium is None or entry_premium <= 0: continue

            t = Trade(
                day=day_date, side=sig_dir, grade='V24',
                entry_bkt=bkt + 1, entry_nifty=entry_nifty,
                entry_premium=entry_premium, strike=strike,
                trigger_level=lvl, targets=[],
                lots=2, lots_remaining=2,
                hardsl_premium=hardsl_floor(entry_premium),
                peak_prem=entry_premium,
            )
            t = simulate_trade(t, day_data, exit_model, vwap_by_bkt=vwap_by_bkt)
            trades.append(t)
            _flips = _try_flip_cascade(t, day_data, exit_model, flips_today=flips_today, vwap_by_bkt=vwap_by_bkt)
            for _ft in _flips: trades.append(_ft)
            flips_today += len(_flips)
            _last = _flips[-1] if _flips else t
            next_allowed_bkt = (_last.exits[-1]['bkt'] + 1) if _last.exits else (bkt + 1)
            fired_levels.add(lvl)
            # Loss accounting
            if (not _is_flip_related(t)) and t.pnl_prem_per_lot() < 0:
                daily_losses += 1
                if daily_losses >= CIRCUIT_BREAKER:
                    halt = True
            active = None  # no carryover; next iteration scans for next entry
            continue

        # ---- ENTRY: V2.3 path (cluster + Grade A/B, at 15m close)
        else:
            # Detect at 15m close: bkt is closed 5m; new 15m closes at bkt%3==2
            if bkt % 3 != 2: continue
            # n15_by_bkt is keyed by b['bucket'] from day['nifty_15m'], which uses 5m start-bucket (0,3,6...).
            # Use bkt-2 to get the start-bucket of the just-closed 15m bar (bkt=2->0, bkt=5->3, bkt=8->6...).
            # bkt//3 (sequential 0,1,2...) is WRONG here — it misses all n15_by_bkt keys beyond index 0.
            k15 = bkt - 2
            n15 = n15_by_bkt.get(k15)
            if n15 is None: continue

            # First-30 filter: skip if move-direction doesn't match
            if filters.get('first30'):
                if first30_dir is None: continue

            # Opening confirmation: if 15m bar close-time < 9:45 (k15 == 0 closes 9:30; k15 == 1 closes 9:45), require prev close above/below
            # Simplified: skip checking opening-confirmation; spec said k15==0 needs the 09:30 logic but it's noise for backtest
            for role, lvl_obj in [('G', levels_v23['G']), ('R', levels_v23['R'])]:
                if lvl_obj is None or lvl_obj['center'] in fired_levels: continue
                sig = detect_v23_signal(n15, lvl_obj, role)
                if sig is None: continue
                sig_dir = 'CE' if 'CE' in sig['kind'] else 'PE'

                # First-30 filter
                if filters.get('first30') and first30_dir is not None and sig_dir != first30_dir:
                    continue

                # Compute targets
                targets = compute_targets(lvl_obj, sig_dir, levels_v23['all_clusters'])

                # Entry at next 5m OPEN (bkt+1)
                if bkt + 1 not in nifty_by_bkt: continue
                entry_nifty = nifty_by_bkt[bkt + 1]['open']

                # Strike (ATM for V2.3 path; delta-shift if user opts in)
                strike = select_strike(bar5['close'], sig_dir, atm_day, use_delta_shift, day_data['opt_5m'])
                if strike is None: continue
                opt_bars = sorted(day_data['opt_5m'][(strike, sig_dir)], key=lambda b: b['bucket'])
                opt_by = {b['bucket']: b for b in opt_bars}
                entry_premium = opt_by.get(bkt + 1, {}).get('open')
                if entry_premium is None or entry_premium <= 0: continue

                # Skip if already past T1
                if sig_dir == 'CE' and entry_nifty >= targets[0] - 10: continue
                if sig_dir == 'PE' and entry_nifty <= targets[0] + 10: continue

                lots = LOTS_GRADE_A if sig['grade'] == 'A' else LOTS_GRADE_B
                t = Trade(
                    day=day_date, side=sig_dir, grade=sig['grade'],
                    entry_bkt=bkt + 1, entry_nifty=entry_nifty,
                    entry_premium=entry_premium, strike=strike,
                    trigger_level=lvl_obj['center'], targets=targets,
                    lots=lots, lots_remaining=lots,
                    hardsl_premium=hardsl_floor(entry_premium),
                    peak_prem=entry_premium,
                )
                t = simulate_trade(t, day_data, exit_model, trigger_level_for_15m=lvl_obj['center'], vwap_by_bkt=vwap_by_bkt)
                trades.append(t)
                _flips = _try_flip_cascade(t, day_data, exit_model, flips_today=flips_today, vwap_by_bkt=vwap_by_bkt)
                for _ft in _flips: trades.append(_ft)
                flips_today += len(_flips)
                _last = _flips[-1] if _flips else t
                next_allowed_bkt = (_last.exits[-1]['bkt'] + 1) if _last.exits else (bkt + 1)
                fired_levels.add(lvl_obj['center'])
                if (not _is_flip_related(t)) and t.pnl_prem_per_lot() < 0:
                    daily_losses += 1
                    if daily_losses >= CIRCUIT_BREAKER:
                        halt = True
                        break

    return trades


# -------------------- Combo runner --------------------
def run_combo(name, daily, df5_all, df15_all, df1h_all,
              entry_model, exit_model, use_delta_shift,
              optional_filters=None):
    dates = sorted(daily.keys())

    # MACD on 5m (V2.4 entry): map (date, bucket) -> (line, sig)
    macd_5m_map = {}
    for _, row in df5_all.iterrows():
        macd_5m_map[(row['date'], row['bucket'])] = (row['MACD_line'], row['MACD_sig'])

    # V2.2 entry needs: per-date sorted 15m bars (K, K_prev) and 1h bars (SMA20, SMA50)
    # Build per-date lookups; for any date d, also keep last prior 1h row to use before today's first 1h closes.
    df15_sorted = df15_all.sort_values(['date','bucket']).reset_index(drop=True)
    df1h_sorted = df1h_all.sort_values(['date','bucket']).reset_index(drop=True)
    df15_by_date = {d: g.reset_index(drop=True) for d, g in df15_sorted.groupby('date')}
    df1h_by_date = {d: g.reset_index(drop=True) for d, g in df1h_sorted.groupby('date')}

    all_trades = []
    skipped_no_history = 0
    for di, d in enumerate(dates):
        if di == 0: continue
        # need ~5 days history for 1h indicators
        prior_dates = [pd_ for pd_ in dates[:di]]
        if len(prior_dates) < 5:
            skipped_no_history += 1
            continue

        # Slice prior 1h frame for level/regime computation
        df1h_prior = df1h_sorted[df1h_sorted['date'] < d]
        if len(df1h_prior) < 50:
            skipped_no_history += 1
            continue

        day_data = daily[d]

        # Inject MACD into bar5 dicts (mutation on copies)
        nifty_5m_with_macd = []
        for b in day_data['nifty_5m']:
            b2 = dict(b)
            ml, ms = macd_5m_map.get((d, b['bucket']), (None, None))
            b2['MACD_line'] = ml
            b2['MACD_sig']  = ms
            nifty_5m_with_macd.append(b2)
        day_data_aug = dict(day_data)
        day_data_aug['nifty_5m'] = nifty_5m_with_macd

        # Build today's V2 indicator lookups (1h SMA20/50/close ordered, 15m K ordered)
        today_1h = df1h_by_date.get(d, pd.DataFrame()).sort_values('bucket').reset_index(drop=True)
        today_15m = df15_by_date.get(d, pd.DataFrame()).sort_values('bucket').reset_index(drop=True)

        # Build K lookup keyed by 5m bucket (the 5m bucket where the 15m bar closes)
        # 15m bar bucket B closes at 5m bucket B+2.  So if df15 has bucket=k15, key 5m bucket = k15+2.
        k_lookup_5m = {}
        if len(today_15m) > 0 and 'K' in today_15m.columns:
            for _, r in today_15m.iterrows():
                k15 = int(r['bucket'])
                if not pd.isna(r['K']):
                    k_lookup_5m[k15 + 2] = float(r['K'])
        day_data_aug['_k_lookup'] = k_lookup_5m
        # Prior 1h: take all rows before today; use the last one as fallback "last closed 1h" before today's first
        last_prior_1h_row = df1h_sorted[df1h_sorted['date'] < d].iloc[-1] if (df1h_sorted['date'] < d).any() else None
        # Cross-day 15m: same idea
        last_prior_15m_rows = df15_sorted[df15_sorted['date'] < d]

        v2_ctx = {
            'today_1h': today_1h,
            'today_15m': today_15m,
            'last_prior_1h': last_prior_1h_row,
            'prior_15m_for_K_prev': last_prior_15m_rows.iloc[-1] if len(last_prior_15m_rows) else None,
        }

        trades = run_day(d, day_data_aug, df1h_prior, entry_model, exit_model,
                         use_delta_shift, optional_filters, v2_ctx=v2_ctx)
        all_trades.extend(trades)

    return all_trades, skipped_no_history


# -------------------- Stats reporting --------------------
def compute_stats(trades):
    n = len(trades)
    if n == 0:
        return {'n':0, 'pts':0, 'rs':0, 'wr':0, 'avg_win':0, 'avg_loss':0,
                'max_dd':0, 'max_dd_rs':0, 'red_months':0, 'total_months':0,
                'reasons':{}, 'by_grade':{}, 'by_side':{}}
    pts = sum(t.pnl_nifty_pts() for t in trades)
    rs  = sum(t.pnl_prem_rs() for t in trades)
    wins = [t for t in trades if t.pnl_prem_per_lot() > 0]
    losses = [t for t in trades if t.pnl_prem_per_lot() < 0]
    wr = len(wins) / n if n else 0
    avg_w = sum(t.pnl_prem_per_lot() for t in wins) / len(wins) if wins else 0
    avg_l = sum(t.pnl_prem_per_lot() for t in losses) / len(losses) if losses else 0

    # Equity curve by Nifty pts (chronological)
    chrono = sorted(trades, key=lambda t: (t.day, t.entry_bkt))
    cum = 0; peak = 0; max_dd = 0
    cum_rs = 0; peak_rs = 0; max_dd_rs = 0
    for t in chrono:
        cum += t.pnl_nifty_pts()
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)
        cum_rs += t.pnl_prem_rs()
        peak_rs = max(peak_rs, cum_rs)
        max_dd_rs = min(max_dd_rs, cum_rs - peak_rs)

    # Red months
    by_month = defaultdict(float)
    for t in chrono:
        d = t.day
        if isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d").date()
        by_month[(d.year, d.month)] += t.pnl_nifty_pts()
    red = sum(1 for v in by_month.values() if v < 0)

    # Exit reasons
    reasons = defaultdict(int)
    for t in chrono:
        for e in t.exits:
            reasons[e['reason']] += 1

    # By grade / side
    by_grade = defaultdict(lambda: {'n':0, 'pts':0, 'wr_n':0})
    by_side  = defaultdict(lambda: {'n':0, 'pts':0, 'wr_n':0})
    for t in chrono:
        by_grade[t.grade]['n'] += 1
        by_grade[t.grade]['pts'] += t.pnl_nifty_pts()
        by_grade[t.grade]['wr_n'] += (1 if t.pnl_prem_per_lot() > 0 else 0)
        by_side[t.side]['n'] += 1
        by_side[t.side]['pts'] += t.pnl_nifty_pts()
        by_side[t.side]['wr_n'] += (1 if t.pnl_prem_per_lot() > 0 else 0)

    return {
        'n': n, 'pts': pts, 'rs': rs, 'wr': wr,
        'avg_win': avg_w, 'avg_loss': avg_l,
        'max_dd': max_dd, 'max_dd_rs': max_dd_rs,
        'red_months': red, 'total_months': len(by_month),
        'reasons': dict(reasons),
        'by_grade': {k: dict(v) for k, v in by_grade.items()},
        'by_side':  {k: dict(v) for k, v in by_side.items()},
    }

def print_stats(name, s):
    if s['n'] == 0:
        print(f"\n=== {name} ===  ZERO trades.")
        return
    print(f"\n=== {name} ===")
    print(f"  Trades : {s['n']}")
    print(f"  Nifty pts: {s['pts']:+.0f}  |  Net P&L (after costs) Rs: {s['rs']:+,.0f}")
    print(f"  WR     : {s['wr']*100:.1f}%   avg_win={s['avg_win']:+.2f}  avg_loss={s['avg_loss']:+.2f}")
    print(f"  Max DD (Nifty pts): {s['max_dd']:+.0f} pts  |  Max DD (Rs): {s['max_dd_rs']:+,.0f}   red_months={s['red_months']}/{s['total_months']}")
    print(f"  By side: {dict(s['by_side'])}")
    print(f"  By grade: {dict(s['by_grade'])}")
    rs = sorted(s['reasons'].items(), key=lambda x: -x[1])
    print(f"  Top exit reasons: {rs[:6]}")

# (Framework v0.3 load banner removed — dead module-level print)


# -------------------- Main --------------------
def main():
    import time, csv
    t0 = time.time()
    print("\nSearching for phase3_daily.pkl...")
    pkl_path = resolve_dataset_path()
    if not pkl_path:
        print("[FATAL] Could not find phase3_daily.pkl.")
        print("Place it in: /storage/emulated/0/Download/backtest_out/phase3_daily.pkl")
        return
    print(f"Found: {pkl_path}")
    with open(pkl_path, 'rb') as f:
        daily = pickle.load(f)
    df5, df15, df1h = build_continuous_streams(daily)
    print(f"  {len(daily)} days, {len(df5)} 5m bars")

    # Locked common settings
    globals()['HARDSL_MODE']   = 'pct'
    globals()['HARDSL_VALUE']  = 0.25
    globals()['V2V3_PRIORITY'] = 'v2'
    globals()['RATCHET_INITIAL_PTS'] = 15   # V2.5.7: velvet rope trigger
    globals()['RATCHET_STEP_PTS']    = 20
    globals()['RATCHET_TIME_MIN']    = 30   # V2.5.7: 30min gate
    globals()['CIRCUIT_BREAKER']     = 4
    globals()['V2_K_CAP_CE']         = None      # CE cap rejected by data
    globals()['V2_K_FLOOR_PE']       = 25        # PE floor confirmed by data

    # Flip params (already set above; reaffirm for clarity)
    globals()['FLIP_PATH_A_ELAPSED']  = 30
    globals()['FLIP_PATH_A_PEAK_MIN'] = 15
    globals()['FLIP_PATH_A_DROP_MAX'] = 10
    globals()['FLIP_K_CE_TO_PE_MIN']  = 25
    globals()['FLIP_K_CE_TO_PE_MAX']  = 80
    globals()['FLIP_K_PE_TO_CE_MIN']  = 38

    # ==============================================================
    # V2.5.6 LOCKED — single-variant run for headline number
    # ==============================================================
    # All locked parameters are set at module-level defaults above.
    # main() simply runs the backtest with those defaults.
    print("\n" + "="*108)
    print("ORION V2.5.6 LOCKED")
    print("  HARDSL=-25%  CB=4  PE_floor=25  V2-priority  V3-promoted-singletons")
    print("  FLIP_ENABLED=True  MAX_FLIPS_PER_DAY=3")
    print("  CHOP_FILTER_MODE='rsi_band'  band=[47,53]")
    print("  V3_EXCLUDE_PDC_FROM_CLUSTERS=True  V3_MIN_BUFFER_FROM_PDC=25  (V2.5.6 PDC fix)")
    print("="*108)

    trs, _ = run_combo('V2.5.6 LOCKED', daily, df5, df15, df1h,
                       entry_model='v2_v3', exit_model='sma8_tratchet',
                       use_delta_shift=False, optional_filters=None)
    s = compute_stats(trs)
    rm = f"{s['red_months']}/{s['total_months']}" if s['total_months'] else "—"
    print(f"\n{'Variant':<25s} {'Trades':>7} {'NiftyPts':>9} {'Rs':>12} {'WR%':>6} {'avgW':>6} {'avgL':>7} {'MaxDD':>7} {'Red':>6}")
    print("-"*108)
    print(f"{'V2.5.6 LOCKED':<25s} {s['n']:>7d} {s['pts']:+9.0f} {s['rs']:+12,.0f} {s['wr']*100:>6.1f} "
          f"{s['avg_win']:+6.1f} {s['avg_loss']:+7.1f} {s['max_dd']:+7.0f} {rm:>6}")

    csv_path = '/home/claude/v256_locked_result.csv'
    with open(csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['variant','trades','nifty_pts','rs','wr_pct','avg_win','avg_loss','max_dd','red_months','total_months'])
        w.writerow(['V2.5.6 LOCKED', s['n'], round(s['pts']), round(s['rs']),
                    round(s['wr']*100,1), round(s['avg_win'],2), round(s['avg_loss'],2),
                    round(s['max_dd']), s['red_months'], s['total_months']])
    print(f"\nCSV saved: {csv_path}")
    print(f"Runtime: {time.time()-t0:.1f}s")

    # =========================================================================
    # EXIT MODEL GRID COMPARISON (V2.5.7 + New Strategies)
    # =========================================================================
    GRID_MODELS = [
        ('V2.5.6_baseline',  'sma8_tratchet'),   # but we need the old params — skip for now, label separately
        ('V2.5.7_velvet',    'sma8_tratchet'),    # current (already ran above)
        ('velvet_vwap',      'velvet_vwap'),
        ('velvet_sma5m',     'velvet_sma5m'),
        ('velvet_dual',      'velvet_dual'),
        ('partial_sma15m',   'partial_sma15m'),
        ('partial_vwap',     'partial_vwap'),
        ('vwap_only',        'vwap_only'),
        ('fixed_be_sma15m',  'fixed_be_sma15m'),
    ]

    print("\n" + "="*110)
    print("EXIT STRATEGY GRID COMPARISON  |  entry=v2_v3 fixed  |  18-month backtest")
    print(f"{'Model':<22} {'Trades':>7} {'Rs P&L':>11} {'WR%':>6} {'AvgWin':>8} {'AvgLoss':>8} {'MaxDD_Rs':>11} {'RedMo':>7}")
    print("-"*110)

    grid_stats = {}
    # First entry is already computed (trs from main run)
    s_cur = compute_stats(trs)
    grid_stats['V2.5.7_velvet'] = s_cur
    print(f"{'V2.5.7_velvet':<22} {s_cur['n']:>7} {s_cur['rs']:>+11,.0f} {s_cur['wr']*100:>6.1f} {s_cur['avg_win']:>+8.2f} {s_cur['avg_loss']:>+8.2f} {s_cur.get('max_dd_rs', s_cur['max_dd']*100):>+11,.0f} {s_cur['red_months']:>3}/{s_cur['total_months']}")

    for label, em in GRID_MODELS[1:]:  # skip first (already printed)
        try:
            tr_g, _ = run_combo(label, daily, df5, df15, df1h,
                                entry_model='v2_v3', exit_model=em, use_delta_shift=False)
            sg = compute_stats(tr_g)
            grid_stats[label] = sg
            dd_rs = sg.get('max_dd_rs', sg['max_dd'] * 100)
            print(f"{label:<22} {sg['n']:>7} {sg['rs']:>+11,.0f} {sg['wr']*100:>6.1f} {sg['avg_win']:>+8.2f} {sg['avg_loss']:>+8.2f} {dd_rs:>+11,.0f} {sg['red_months']:>3}/{sg['total_months']}")
        except Exception as e:
            print(f"{label:<22} ERROR: {e}")

    print("="*110)
    if grid_stats:
        best_rs  = max(grid_stats, key=lambda k: grid_stats[k]['rs'])
        best_wr  = max(grid_stats, key=lambda k: grid_stats[k]['wr'])
        best_red = min(grid_stats, key=lambda k: grid_stats[k]['red_months'])
        print(f"\n  Best Net P&L    : {best_rs}  →  Rs {grid_stats[best_rs]['rs']:+,.0f}")
        print(f"  Best Win Rate   : {best_wr}  →  {grid_stats[best_wr]['wr']*100:.1f}%")
        print(f"  Fewest Red Months: {best_red}  →  {grid_stats[best_red]['red_months']}/{grid_stats[best_red]['total_months']}")


if __name__ == "__main__":
    main()


