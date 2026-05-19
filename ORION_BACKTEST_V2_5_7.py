"""
=========================================================================
ORION BACKTEST V2.5.7 - OPTIMIZED PROFIT BOOKING EXPANSION
=========================================================================
Full forward simulation platform for phase3_daily.pkl.
Strictly preserved within the stable V2.5.6 core frame architecture.
Only modifies exit logic under 'sma8_tratchet' to use Velvet Rope BE.
"""
import pickle
import math
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

# -------------------- Storage Path Resolution --------------------
def resolve_dataset_path():
    filename = "phase3_daily.pkl"
    import os
    possible_paths = [
        f"/home/Selukar/{filename}",                                       # PythonAnywhere
        f"/home/Selukar/Amol/{filename}",                                  # PythonAnywhere alt
        f"/storage/emulated/0/Download/backtest_out/{filename}",           # Android
        f"/sdcard/Download/backtest_out/{filename}",                       # Android alt
        f"Download/backtest_out/{filename}",
        filename,
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

LOT_SIZE = 65

# Common risk (V2.5.6 Core Baseline Defaults)
HARDSL_MODE         = 'pct'
HARDSL_VALUE        = 0.25      # Locked at -25%
CIRCUIT_BREAKER     = 4         # Daily non-flip loss limit
FORCE_CLOSE_BUCKET  = 73        # 15:25 IST execution
ENTRY_WINDOW_END_BKT = 62       # 14:30 IST last entry cut-off

# V3 Level Parameter Matrix
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

# V2.4 Trailing Exit Parameters
BE_TRIGGER_PCT        = 0.15
SMA_TRAIL_PERIOD      = 8
SMA_TRAIL_TF_BARS     = 3

# V2.4 Strategy Mapping
ITM_OFFSET            = 100
MACD_REQUIRE_ALIGN    = True
PREM_GATE_REQUIRE     = True

# V2.5+ Global Flags
V2V3_PRIORITY         = 'v2'
V3_PROMOTE_SINGLETONS = True

# V2.5.6 PDC Contamination Fixes
V3_EXCLUDE_PDC_FROM_CLUSTERS = True
V3_MIN_BUFFER_FROM_PDC       = 25

# V2 Execution Caps
V2_K_CAP_CE           = None
V2_K_FLOOR_PE         = 25

# Flip Rule Constraints
FLIP_ENABLED          = True
FLIP_PATH_A_ELAPSED   = 30
FLIP_PATH_A_PEAK_MIN  = 15
FLIP_PATH_A_DROP_MAX  = 10
FLIP_K_CE_TO_PE_MIN   = 25
FLIP_K_CE_TO_PE_MAX   = 80
FLIP_K_PE_TO_CE_MIN   = 38

# Chop Protection Filters
MAX_FLIPS_PER_DAY     = 3
SKIP_HOUR_13          = False
SKIP_TUESDAYS         = False

# Chop Classifier Mode
CHOP_FILTER_MODE      = 'rsi_band'
CHOP_ADX_THRESHOLD    = 20
CHOP_RSI_LO           = 47
CHOP_RSI_HI           = 53
CHOP_RANGE_PCT_MIN    = 0.4
CHOP_RANGE_AFTER_BKT  = 12
CHOP_K_CROSS_MAX      = 4

# =========================================================================
# V2.5.7 PROFIT LOCK MECHANISM PARAMETERS
# =========================================================================
RATCHET_TIME_MIN      = 30      # Arm window: 30 mins (was 90)
RATCHET_INITIAL_PTS   = 15      # Velvet rope trigger at +15 premium pts
RATCHET_STEP_PTS      = 20      # Runner step expansion

STOCHRSI_LEN          = 14
STOCHRSI_RSI_LEN      = 14
STOCHRSI_K_SMOOTH     = 3
STOCHRSI_CE_LO        = 38
STOCHRSI_PE_HI        = 80
SMA_FAST_1H_LEN       = 20
SMA_SLOW_1H_LEN       = 50

# -------------------- Bucket / Time Helpers --------------------
def bkt_to_hour(b: int) -> float:
    mins = (b + 1) * 5
    return (9*60 + 15 + mins) / 60.0

def bkt_to_str(b: int) -> str:
    mins = 9*60 + 15 + (b+1)*5
    return f"{mins//60:02d}:{mins%60:02d}"

# -------------------- Indicator Math --------------------
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
    pdi   = 100 * plus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr
    ndi   = 100 * minus_dm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr
    dx    = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    adx   = dx.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    return adx, pdi, ndi

# -------------------- Stream Builder --------------------
def build_continuous_streams(daily: dict):
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

    df1h['SMA20'] = df1h['close'].rolling(SMA_FAST).mean()
    df1h['SMA50'] = df1h['close'].rolling(SMA_SLOW).mean()
    df1h['SMA20_slope'] = df1h['SMA20'].diff(3)
    df1h['SMA50_slope'] = df1h['SMA50'].diff(3)
    df1h['ADX'], df1h['DI_plus'], df1h['DI_minus'] = adx_di(df1h)
    df1h['MACD_line'], df1h['MACD_sig'] = macd_lines(df1h['close'])
    df1h['RSI'] = rsi(df1h['close'])

    df5['MACD_line'], df5['MACD_sig'] = macd_lines(df5['close'])
    df15['K'] = stochrsi_k(df15['close'])

    return df5, df15, df1h

# -------------------- Level Architecture --------------------
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
    if V3_EXCLUDE_PDC_FROM_CLUSTERS:
        src = [(pdh, 'PDH'), (pdl, 'PDL')]
    else:
        src = [(pdh, 'PDH'), (pdl, 'PDL'), (pdc, 'PDC')]
    src += generate_round_levels(pdc)
    swing_pivots = find_swing_pivots(df1h_prior)
    src += swing_pivots
    src = [s for s in src if abs(s[0] - pdc) <= ROUND_RANGE_PTS]
    clusters = cluster_levels(src)

    if not V3_PROMOTE_SINGLETONS:
        buf = V3_MIN_BUFFER_FROM_PDC
        above = [c for c in clusters if c['center'] > pdc + buf and c['grade'] in ('A','B')]
        below = [c for c in clusters if c['center'] < pdc - buf and c['grade'] in ('A','B')]
        above.sort(key=lambda c: (0 if c['grade']=='A' else 1, abs(c['center']-pdc)))
        below.sort(key=lambda c: (0 if c['grade']=='A' else 1, abs(c['center']-pdc)))
        return {'pdh': pdh, 'pdl': pdl, 'pdc': pdc, 'G': above[0] if above else None, 'R': below[0] if below else None, 'all_clusters': clusters}

    PROMOTE_ROUND_100_BAND = 200
    PROMOTE_SWING_BAND     = ROUND_RANGE_PTS
    def _in_any_AB_cluster(price):
        for c in clusters:
            if c['grade'] in ('A','B') and abs(c['center'] - price) <= CLUSTER_RADIUS_PTS:
                return True
        return False

    promoted = []
    for p, kind in [(pdh, 'PDH'), (pdl, 'PDL')]:
        if not _in_any_AB_cluster(p):
            promoted.append({'center': round(p, 2), 'kinds': [kind], 'count': 1, 'grade': 'B', 'promoted': True})
    for off in range(-PROMOTE_ROUND_100_BAND, PROMOTE_ROUND_100_BAND + 1, 100):
        base = round(pdc / 100) * 100
        p = float(base + off)
        if not _in_any_AB_cluster(p):
            promoted.append({'center': round(p, 2), 'kinds': ['round_100'], 'count': 1, 'grade': 'B', 'promoted': True})
    for p, kind in swing_pivots:
        if abs(p - pdc) <= PROMOTE_SWING_BAND and not _in_any_AB_cluster(p):
            promoted.append({'center': round(p, 2), 'kinds': [kind], 'count': 1, 'grade': 'B', 'promoted': True})

    all_levels = clusters + promoted
    buf = V3_MIN_BUFFER_FROM_PDC
    above = [c for c in all_levels if c['center'] > pdc + buf and c['grade'] in ('A','B')]
    below = [c for c in all_levels if c['center'] < pdc - buf and c['grade'] in ('A','B')]
    above.sort(key=lambda c: (0 if c['grade']=='A' else 1, abs(c['center']-pdc)))
    below.sort(key=lambda c: (0 if c['grade']=='A' else 1, abs(c['center']-pdc)))
    return {'pdh': pdh, 'pdl': pdl, 'pdc': pdc, 'G': above[0] if above else None, 'R': below[0] if below else None, 'all_clusters': all_levels}

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

# -------------------- Signals & Execution --------------------
def classify_regime(row_1h):
    if pd.isna(row_1h.get('SMA20')) or pd.isna(row_1h.get('SMA50')) or pd.isna(row_1h.get('ADX')): return 'INSUFFICIENT'
    c, s20, s50 = row_1h['close'], row_1h['SMA20'], row_1h['SMA50']
    sl20, sl50, adxv = row_1h['SMA20_slope'], row_1h['SMA50_slope'], row_1h['ADX']
    if adxv < ADX_CHOP_MAX: return 'CHOP'
    if c > s20 > s50 and sl20 > 0 and sl50 > 0 and adxv > ADX_TREND_MIN: return 'BULL'
    if c < s20 < s50 and sl20 < 0 and sl50 < 0 and adxv > ADX_TREND_MIN: return 'BEAR'
    return 'TRANSITION'

def regime_allows_trade(regime, sig_dir):
    return regime not in ('CHOP', 'INSUFFICIENT')

def evaluate_candle(bar, level, kind, grade):
    o, h, l, c = bar['open'], bar['high'], bar['low'], bar['close']
    rng = h - l
    if rng <= 0: return False
    body_pct = abs(c - o) / rng
    if kind == 'BREAK_CE':
        beyond = c - level
        if grade == 'A': return beyond >= GRADE_A_MIN_CLOSE_BEYOND and body_pct >= GRADE_A_MIN_BODY_PCT
        else: return body_pct >= GRADE_B_MIN_BODY_PCT and (c - l)/rng >= 1 - GRADE_B_CLOSE_TOP_PCT
    elif kind == 'BREAK_PE':
        beyond = level - c
        if grade == 'A': return beyond >= GRADE_A_MIN_CLOSE_BEYOND and body_pct >= GRADE_A_MIN_BODY_PCT
        else: return body_pct >= GRADE_B_MIN_BODY_PCT and (h - c)/rng >= 1 - GRADE_B_CLOSE_TOP_PCT
    return False

def detect_v23_signal(bar, level, level_role):
    o, h, l, c = bar['open'], bar['high'], bar['low'], bar['close']
    L = level['center']
    rng = h - l
    grade = level['grade']
    if rng > 0:
        if level_role == 'G' and h >= L and c < L + WICK_REJECT_CLOSE_DIST:
            wick = h - max(o, c)
            if (wick / rng) >= WICK_REJECT_MIN_PCT and abs(c - L) <= WICK_REJECT_CLOSE_DIST:
                return {'kind': 'REJECT_PE', 'level': L, 'role': level_role, 'grade': grade}
        if level_role == 'R' and l <= L and c > L - WICK_REJECT_CLOSE_DIST:
            wick = min(o, c) - l
            if (wick / rng) >= WICK_REJECT_MIN_PCT and abs(c - L) <= WICK_REJECT_CLOSE_DIST:
                return {'kind': 'REJECT_CE', 'level': L, 'role': level_role, 'grade': grade}
    if level_role == 'G' and c > L and evaluate_candle(bar, L, 'BREAK_CE', grade):
        return {'kind': 'BREAK_CE', 'level': L, 'role': level_role, 'grade': grade}
    if level_role == 'R' and c < L and evaluate_candle(bar, L, 'BREAK_PE', grade):
        return {'kind': 'BREAK_PE', 'level': L, 'role': level_role, 'grade': grade}
    return None

def hardsl_floor(entry_premium):
    if HARDSL_MODE == 'pct': return entry_premium * (1 - HARDSL_VALUE)
    return entry_premium - HARDSL_VALUE

def v24_compute_levels(prior_day_ohlc):
    pdh, pdl, pdc = float(prior_day_ohlc['H']), float(prior_day_ohlc['L']), float(prior_day_ohlc['C'])
    psy = int(round(pdc / 500) * 500)
    return sorted({pdc, pdh, pdl, psy - 500, psy, psy + 500})

def opt_15m_from_5m(opt_5m_bars, upto_5m_bucket):
    by_bkt = {b['bucket']: b for b in opt_5m_bars}
    out = []
    for k15 in range(25):
        end_5m = 3*k15 + 2
        if end_5m > upto_5m_bucket: break
        members = [by_bkt[b] for b in (3*k15, 3*k15+1, 3*k15+2) if b in by_bkt]
        if not members: continue
        out.append({'bkt15': k15, 'o': members[0]['open'], 'h': max(m['high'] for m in members),
                    'l': min(m['low'] for m in members), 'c': members[-1]['close']})
    return out

def sma_last(values, n):
    if len(values) < n: return None
    return sum(values[-n:]) / n

@dataclass
class Trade:
    day: str
    side: str
    grade: str
    entry_bkt: int
    entry_nifty: float
    entry_premium: float
    strike: int
    trigger_level: float
    targets: list = field(default_factory=list)
    current_sl_nifty: Optional[float] = None
    hardsl_premium: float = 0.0
    lots: int = 2
    lots_remaining: int = 2
    be_armed: bool = False
    profit_lock_armed: bool = False
    profit_lock_price: float = 0.0
    tr_armed: bool = False
    tr_sl: float = 0.0
    t1_hit: bool = False
    t2_hit: bool = False
    peak_prem: float = 0.0
    closed: bool = False
    exits: list = field(default_factory=list)

    def book(self, bkt, reason, nifty, prem, lots):
        self.exits.append({'bkt': bkt, 'reason': reason, 'nifty': nifty, 'prem': prem, 'lots': lots})
        self.lots_remaining -= lots
        if self.lots_remaining <= 0: self.closed = True

    def pnl_nifty_pts(self):
        s = 0.0
        for e in self.exits:
            if self.side == 'CE': s += (e['nifty'] - self.entry_nifty) * e['lots']
            else: s += (self.entry_nifty - e['nifty']) * e['lots']
        return s

    def pnl_prem_per_lot(self):
        if not self.exits: return 0.0
        return sum((e['prem'] - self.entry_premium) * e['lots'] for e in self.exits) / self.lots

    def pnl_prem_rs(self):
        return sum((e['prem'] - self.entry_premium) * e['lots'] * LOT_SIZE for e in self.exits)

# =========================================================================
# CORE SIMULATOR
# =========================================================================
def simulate_trade(trade: Trade, day_data: dict, exit_model: str,
                   trigger_level_for_15m: Optional[float] = None,
                   k_lookup: Optional[dict] = None):
    if k_lookup is None: k_lookup = day_data.get('_k_lookup')
    opt_key = (trade.strike, trade.side)
    opt_5m = sorted(day_data['opt_5m'].get(opt_key, []), key=lambda b: b['bucket'])
    if not opt_5m:
        trade.book(trade.entry_bkt, 'NO_OPT_DATA', trade.entry_nifty, trade.entry_premium, trade.lots)
        return trade

    nifty_5m = sorted(day_data['nifty_5m'], key=lambda b: b['bucket'])
    nifty_by_bkt = {b['bucket']: b for b in nifty_5m}
    opt_by_bkt = {b['bucket']: b for b in opt_5m}

    for bkt in range(trade.entry_bkt, FORCE_CLOSE_BUCKET + 1):
        if trade.closed: break
        n5 = nifty_by_bkt.get(bkt)
        o5 = opt_by_bkt.get(bkt)
        if n5 is None or o5 is None: continue

        if bkt >= FORCE_CLOSE_BUCKET:
            trade.book(bkt, 'FORCE_CLOSE_15_25', n5['close'], o5['close'], trade.lots_remaining)
            break

        trade.peak_prem = max(trade.peak_prem, o5['high'])

        if o5['low'] <= trade.hardsl_premium:
            mode_lbl = f"HARDSL_{int(HARDSL_VALUE*100)}pct" if HARDSL_MODE == 'pct' else f"HARDSL_{int(HARDSL_VALUE)}pt"
            trade.book(bkt, mode_lbl, n5['close'], trade.hardsl_premium, trade.lots_remaining)
            break

        if exit_model == 'v24':
            if not trade.be_armed and o5['high'] >= trade.entry_premium * (1 + BE_TRIGGER_PCT):
                trade.be_armed = True
                trade.current_sl_nifty = trade.entry_premium
            if trade.be_armed and o5['low'] <= trade.entry_premium:
                trade.book(bkt, 'BE_SCRATCH', n5['close'], trade.entry_premium, trade.lots_remaining)
                break
            if bkt % 3 == 2 and bkt >= 3*SMA_TRAIL_PERIOD - 1:
                o15 = opt_15m_from_5m(opt_5m, bkt)
                if len(o15) >= SMA_TRAIL_PERIOD:
                    sma8l = sma_last([b['l'] for b in o15], SMA_TRAIL_PERIOD)
                    if sma8l is not None and o15[-1]['c'] < sma8l:
                        trade.book(bkt, 'SMA8_LOW_TRAIL', n5['close'], o5['close'], trade.lots_remaining)
                        break

        # =========================================================================
        # V2.5.7 VELVET ROPE + ACCELERATED RATCHET EXIT MODEL
        # =========================================================================
        elif exit_model == 'sma8_tratchet':
            elapsed_min = (bkt - trade.entry_bkt) * 5

            # 1. VELVET ROPE: capital protection at +15 pts
            if not trade.tr_armed and o5['high'] >= trade.entry_premium + RATCHET_INITIAL_PTS:
                trade.tr_armed = True
                trade.tr_sl = trade.entry_premium + 2
                if o5['low'] <= trade.tr_sl:
                    trade.book(bkt, 'VELVET_ROPE_BE_SCRATCH', n5['close'], trade.tr_sl, trade.lots_remaining)
                    break

            # 2. ACCELERATED RATCHET GATE: 30min + entry+25 → SL to entry+15
            if trade.tr_armed and trade.tr_sl == (trade.entry_premium + 2) and elapsed_min >= RATCHET_TIME_MIN:
                if o5['high'] >= trade.entry_premium + 25:
                    trade.tr_sl = trade.entry_premium + 15

            # 3. RUNNER STEP TRAIL: ratchet up +20 per +20 peak
            if trade.tr_armed:
                while o5['high'] >= trade.tr_sl + RATCHET_STEP_PTS:
                    trade.tr_sl += RATCHET_STEP_PTS
                if o5['low'] <= trade.tr_sl:
                    pts_locked = trade.tr_sl - trade.entry_premium
                    trade.book(bkt, f'OPTIMIZED_RATCHET_+{int(pts_locked)}', n5['close'], trade.tr_sl, trade.lots_remaining)
                    break

            # 4. SMA8 LOW TRAIL (15m)
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
            if bkt % 3 == 2 and bkt >= 3*SMA_TRAIL_PERIOD - 1:
                o15 = opt_15m_from_5m(opt_5m, bkt)
                if len(o15) >= SMA_TRAIL_PERIOD:
                    sma8l = sma_last([b['l'] for b in o15], SMA_TRAIL_PERIOD)
                    if sma8l is not None and o15[-1]['c'] < sma8l:
                        trade.book(bkt, 'SMA8_LOW_TRAIL', n5['close'], o5['close'], trade.lots_remaining)
                        break

        # ---- FLIP Path A ----
        if ((not trade.closed) and FLIP_ENABLED and bkt % 3 == 2 and k_lookup is not None):
            elapsed_min = (bkt - trade.entry_bkt) * 5
            if elapsed_min >= FLIP_PATH_A_ELAPSED:
                if trade.peak_prem >= trade.entry_premium + FLIP_PATH_A_PEAK_MIN and \
                   o5['close'] <= trade.entry_premium + FLIP_PATH_A_DROP_MAX:
                    k_now  = k_lookup.get(bkt)
                    k_prev = k_lookup.get(bkt - 3)
                    if k_now is not None and k_prev is not None:
                        if trade.side == 'CE' and k_now < k_prev and FLIP_K_CE_TO_PE_MIN <= k_now <= FLIP_K_CE_TO_PE_MAX:
                            trade.book(bkt, 'FLIP_TO_PE', n5['close'], o5['close'], trade.lots_remaining)
                            break
                        elif trade.side == 'PE' and k_now > k_prev and k_now >= FLIP_K_PE_TO_CE_MIN:
                            trade.book(bkt, 'FLIP_TO_CE', n5['close'], o5['close'], trade.lots_remaining)
                            break

    if not trade.closed:
        trade.book(nifty_5m[-1]['bucket'], 'EOD', nifty_5m[-1]['close'], opt_5m[-1]['close'], trade.lots_remaining)
    return trade

# -------------------- Strike Selection --------------------
def select_strike(spot, side, atm_day, use_delta_shift, opt_5m_dict):
    if use_delta_shift:
        target = atm_day - ITM_OFFSET if side == 'CE' else atm_day + ITM_OFFSET
    else:
        target = int(round(spot / ATM_STEP)) * ATM_STEP
    avail = sorted({k[0] for k in opt_5m_dict.keys() if k[1] == side})
    if not avail: return None
    return min(avail, key=lambda s: abs(s - target))

# -------------------- Flip Engine --------------------
def _check_flip_eligibility(trade: Trade, at_bkt: int, day_data: dict) -> Optional[str]:
    if not FLIP_ENABLED: return None
    k_lookup = day_data.get('_k_lookup', {}) or {}
    candidates = [k for k in k_lookup.keys() if k <= at_bkt]
    if not candidates: return None
    k_at = max(candidates)
    if (k_at - 3) not in k_lookup: return None
    k_now = k_lookup[k_at]; k_prev = k_lookup[k_at - 3]
    if trade.side == 'CE' and k_now < k_prev and FLIP_K_CE_TO_PE_MIN <= k_now <= FLIP_K_CE_TO_PE_MAX: return 'PE'
    elif trade.side == 'PE' and k_now > k_prev and k_now >= FLIP_K_PE_TO_CE_MIN: return 'CE'
    return None

def _try_flip_cascade(last_trade: Trade, day_data: dict, exit_model: str, flips_today: int = 0) -> list:
    if not FLIP_ENABLED or last_trade is None or not last_trade.exits: return []
    if MAX_FLIPS_PER_DAY is not None and flips_today >= MAX_FLIPS_PER_DAY: return []
    nifty_by = {b['bucket']: b for b in sorted(day_data['nifty_5m'], key=lambda b: b['bucket'])}
    flip_trades = []
    prev = last_trade
    while True:
        exit_bkt = prev.exits[-1]['bkt']; next_bkt = exit_bkt + 1
        if next_bkt > FORCE_CLOSE_BUCKET - 2 or next_bkt not in nifty_by: break
        flip_side = _check_flip_eligibility(prev, exit_bkt, day_data)
        if flip_side is None: break
        bar5 = nifty_by[next_bkt]
        strike = select_strike(bar5['open'], flip_side, day_data['atm'], False, day_data['opt_5m'])
        if strike is None or (strike, flip_side) not in day_data['opt_5m']: break
        opt_by = {b['bucket']: b for b in sorted(day_data['opt_5m'][(strike, flip_side)], key=lambda b: b['bucket'])}
        entry_premium = opt_by.get(next_bkt, {}).get('open')
        if entry_premium is None or entry_premium <= 0: break
        flip_t = Trade(day=last_trade.day, side=flip_side, grade='FLIP', entry_bkt=next_bkt,
                       entry_nifty=bar5['open'], entry_premium=entry_premium, strike=strike,
                       trigger_level=0, targets=[], lots=2, lots_remaining=2,
                       hardsl_premium=hardsl_floor(entry_premium), peak_prem=entry_premium)
        flip_t = simulate_trade(flip_t, day_data, exit_model)
        flip_trades.append(flip_t); prev = flip_t; flips_today += 1
        if MAX_FLIPS_PER_DAY is not None and flips_today >= MAX_FLIPS_PER_DAY: break
    return flip_trades

def _is_flip_related(trade: Trade) -> bool:
    if trade.grade == 'FLIP': return True
    if trade.exits and trade.exits[-1].get('reason', '').startswith('FLIP_TO_'): return True
    return False

def _bkt_in_skip_hour(bkt: int) -> bool:
    if not SKIP_HOUR_13: return False
    return ((9*60 + 15 + bkt * 5) // 60) == 13

def _day_in_skip_dow(day_obj) -> bool:
    return False

def _chop_filter_blocks(df1h_row) -> bool:
    if CHOP_FILTER_MODE == 'off': return False
    if df1h_row is None or len(df1h_row) == 0: return False
    adx_last = df1h_row.get('ADX')
    rsi_last = df1h_row.get('RSI')
    if CHOP_FILTER_MODE == 'adx20': return adx_last is not None and adx_last < 20
    if CHOP_FILTER_MODE == 'rsi_band': return rsi_last is not None and CHOP_RSI_LO <= rsi_last <= CHOP_RSI_HI
    return False

# -------------------- Day Loop --------------------
def run_day(day_date, day_data, df1h_prior_all, entry_model: str, exit_model: str,
            use_delta_shift: bool, optional_filters: dict = None):
    trades = []
    daily_losses = 0
    halt = False
    fired_levels = set()
    flips_today = 0

    if df1h_prior_all is None or len(df1h_prior_all) == 0: return trades
    pdh = float(df1h_prior_all['high'].iloc[-7:].max())
    pdl = float(df1h_prior_all['low'].iloc[-7:].min())
    pdc = float(df1h_prior_all['close'].iloc[-1])
    levels_v23 = compute_levels_for_day(df1h_prior_all, {'H': pdh, 'L': pdl, 'C': pdc})

    regime = classify_regime(df1h_prior_all.iloc[-1])
    if entry_model == 'v2_v3' and not regime_allows_trade(regime, 'CE'): return trades

    nifty_5m = sorted(day_data['nifty_5m'], key=lambda b: b['bucket'])
    nifty_15m = sorted(day_data['nifty_15m'], key=lambda b: b['bucket'])
    nifty_by_bkt = {b['bucket']: b for b in nifty_5m}
    n15_by_bkt = {b['bucket']: b for b in nifty_15m}
    atm_day = day_data['atm']

    gap_pct = (nifty_5m[0]['open'] / pdc) - 1
    gap_suppress_until = 12 if abs(gap_pct) > GAP_THRESHOLD_PCT else -1

    next_allowed_bkt = 0
    for bkt in range(len(nifty_5m)):
        bar5 = nifty_by_bkt.get(bkt)
        if bar5 is None or (bkt > ENTRY_WINDOW_END_BKT) or (bkt < next_allowed_bkt) or halt or (bkt < gap_suppress_until): continue

        df1h_active = optional_filters['df1h_today'][optional_filters['df1h_today']['bucket'] + 12 <= bkt + 1] if optional_filters else pd.DataFrame()
        cand1h = df1h_active.iloc[-1] if len(df1h_active) > 0 else (df1h_prior_all.iloc[-1] if len(df1h_prior_all) > 0 else None)

        if cand1h is None or _bkt_in_skip_hour(bkt) or _day_in_skip_dow(day_date) or _chop_filter_blocks(cand1h): continue

        if entry_model == 'v2_v3':
            if bkt % 3 != 2: continue
            k15_bucket = bkt - 2

            sig_v3 = None
            if regime_allows_trade(regime, 'CE'):
                n15 = n15_by_bkt.get(k15_bucket)
                if n15 is not None:
                    for role, lvl_obj in [('G', levels_v23['G']), ('R', levels_v23['R'])]:
                        if lvl_obj is None or lvl_obj['center'] in fired_levels: continue
                        sig = detect_v23_signal(n15, lvl_obj, role)
                        if sig is None: continue
                        sig_v3 = ('CE' if 'CE' in sig['kind'] else 'PE', lvl_obj, sig['grade'])
                        break

            sig_v2 = None
            b1h_sma20 = cand1h.get('SMA20'); b1h_sma50 = cand1h.get('SMA50')
            if b1h_sma20 is not None and b1h_sma50 is not None:
                df15_active = optional_filters['df15_today'][optional_filters['df15_today']['bucket'] == k15_bucket] if optional_filters else pd.DataFrame()
                if len(df15_active) > 0 and not pd.isna(df15_active['K'].iloc[0]):
                    K_now = float(df15_active['K'].iloc[0])
                    df15_prior_rows = optional_filters['df15_today'][optional_filters['df15_today']['bucket'] == k15_bucket - 3] if optional_filters else pd.DataFrame()
                    K_prev = float(df15_prior_rows['K'].iloc[0]) if len(df15_prior_rows) > 0 else (float(optional_filters['fallback_k']) if optional_filters and optional_filters.get('fallback_k') is not None else None)
                    if K_prev is not None:
                        sig_ce = (cand1h['close'] > b1h_sma20) and (K_now >= STOCHRSI_CE_LO) and (K_now > K_prev)
                        sig_pe = (cand1h['close'] < b1h_sma20) and (cand1h['close'] < b1h_sma50) and \
                                 (K_now <= STOCHRSI_PE_HI) and (K_now < K_prev) and (K_now >= V2_K_FLOOR_PE)
                        if not (sig_ce and sig_pe): sig_v2 = 'CE' if sig_ce else 'PE' if sig_pe else None

            chosen = 'V2' if (sig_v2 and sig_v3 and V2V3_PRIORITY == 'v2') else 'V3' if sig_v3 else 'V2' if sig_v2 else None
            if chosen == 'V3':
                sig_dir, lvl_obj, grade = sig_v3
                entry_nifty = nifty_by_bkt[bkt + 1]['open'] if bkt + 1 in nifty_by_bkt else bar5['close']
                strike = select_strike(bar5['close'], sig_dir, atm_day, False, day_data['opt_5m'])
                if strike is None or (strike, sig_dir) not in day_data['opt_5m']: continue
                entry_premium = sorted(day_data['opt_5m'][(strike, sig_dir)], key=lambda b: b['bucket'])[0].get('open')
                targets = compute_targets(lvl_obj, sig_dir, levels_v23['all_clusters'])
                t = Trade(day=day_date, side=sig_dir, grade=f'V3_{grade}', entry_bkt=bkt + 1,
                          entry_nifty=entry_nifty, entry_premium=entry_premium, strike=strike,
                          trigger_level=lvl_obj['center'], targets=targets,
                          hardsl_premium=hardsl_floor(entry_premium), peak_prem=entry_premium)
                t = simulate_trade(t, day_data, exit_model)
                trades.append(t)
                _flips = _try_flip_cascade(t, day_data, exit_model,
                                           sum(1 for _x in trades if _x.grade == 'FLIP' and _x.day == t.day))
                for _ft in _flips: trades.append(_ft)
                flips_today += len(_flips)
                next_allowed_bkt = (_flips[-1].exits[-1]['bkt'] + 1) if _flips else (t.exits[-1]['bkt'] + 1)
                fired_levels.add(lvl_obj['center'])
                if (not _is_flip_related(t)) and t.pnl_prem_per_lot() < 0:
                    daily_losses += 1
                    if daily_losses >= CIRCUIT_BREAKER: halt = True

            elif chosen == 'V2':
                sig_dir = sig_v2
                strike = select_strike(bar5['close'], sig_dir, atm_day, False, day_data['opt_5m'])
                if strike is None or bkt + 1 not in nifty_by_bkt or (strike, sig_dir) not in day_data['opt_5m']: continue
                opt_by = {b['bucket']: b for b in day_data['opt_5m'][(strike, sig_dir)]}
                entry_premium = opt_by.get(bkt + 1, {}).get('open')
                if entry_premium is None or entry_premium <= 0: continue
                t = Trade(day=day_date, side=sig_dir, grade='V2', entry_bkt=bkt + 1,
                          entry_nifty=nifty_by_bkt[bkt + 1]['open'], entry_premium=entry_premium,
                          strike=strike, trigger_level=b1h_sma20, targets=[],
                          hardsl_premium=hardsl_floor(entry_premium), peak_prem=entry_premium)
                t = simulate_trade(t, day_data, exit_model)
                trades.append(t)
                _flips = _try_flip_cascade(t, day_data, exit_model,
                                           sum(1 for _x in trades if _x.grade == 'FLIP' and _x.day == t.day))
                for _ft in _flips: trades.append(_ft)
                flips_today += len(_flips)
                next_allowed_bkt = (_flips[-1].exits[-1]['bkt'] + 1) if _flips else (t.exits[-1]['bkt'] + 1)
                if (not _is_flip_related(t)) and t.pnl_prem_per_lot() < 0:
                    daily_losses += 1
                    if daily_losses >= CIRCUIT_BREAKER: halt = True

    return trades

# -------------------- Combo Pipeline --------------------
def run_combo(name, daily, df5_all, df15_all, df1h_all, entry_model, exit_model, use_delta_shift):
    dates = sorted(daily.keys())
    macd_5m_map = {(row['date'], row['bucket']): (row['MACD_line'], row['MACD_sig'])
                   for _, row in df5_all.iterrows()}

    df15_sorted = df15_all.sort_values(['date','bucket']).reset_index(drop=True)
    df1h_sorted = df1h_all.sort_values(['date','bucket']).reset_index(drop=True)
    df15_by_date = {d: g.reset_index(drop=True) for d, g in df15_sorted.groupby('date')}
    df1h_by_date = {d: g.reset_index(drop=True) for d, g in df1h_sorted.groupby('date')}

    all_trades = []
    for di, d in enumerate(dates):
        if di == 0 or len(dates[:di]) < 5: continue
        df1h_prior = df1h_sorted[df1h_sorted['date'] < d]
        if len(df1h_prior) < 50: continue

        day_data = daily[d]
        nifty_5m_aug = []
        for b in day_data['nifty_5m']:
            b2 = dict(b); ml, ms = macd_5m_map.get((d, b['bucket']), (None, None))
            b2['MACD_line'] = ml; b2['MACD_sig'] = ms; nifty_5m_aug.append(b2)
        day_data_aug = dict(day_data); day_data_aug['nifty_5m'] = nifty_5m_aug

        k_lookup_5m = {int(r['bucket']) + 2: float(r['K'])
                       for _, r in df15_by_date.get(d, pd.DataFrame()).iterrows()
                       if not pd.isna(r['K'])}
        day_data_aug['_k_lookup'] = k_lookup_5m

        prior_15m_section = df15_sorted[df15_sorted['date'] < d]
        fallback_k = float(prior_15m_section.iloc[-1]['K']) if len(prior_15m_section) > 0 else None

        optional_filters = {
            'df1h_today': df1h_by_date.get(d, pd.DataFrame()),
            'df15_today': df15_by_date.get(d, pd.DataFrame()),
            'fallback_k': fallback_k
        }

        trades = run_day(d, day_data_aug, df1h_prior, entry_model=entry_model,
                         exit_model=exit_model, use_delta_shift=use_delta_shift,
                         optional_filters=optional_filters)
        all_trades.extend(trades)

    return all_trades, 0

# -------------------- Metrics --------------------
def compute_stats(trades):
    n = len(trades)
    if n == 0: return {'n':0,'pts':0,'rs':0,'wr':0,'avg_win':0,'avg_loss':0,'max_dd':0,'red_months':0,'total_months':0}
    pts = sum(t.pnl_nifty_pts() for t in trades)
    rs  = sum(t.pnl_prem_rs() for t in trades)
    wins   = [t for t in trades if t.pnl_prem_per_lot() > 0]
    losses = [t for t in trades if t.pnl_prem_per_lot() < 0]
    cum = 0; peak = 0; max_dd = 0
    for t in sorted(trades, key=lambda t: (t.day, t.entry_bkt)):
        cum += t.pnl_nifty_pts(); peak = max(peak, cum); max_dd = min(max_dd, cum - peak)
    by_month = defaultdict(float)
    for t in trades:
        dt_obj = datetime.strptime(t.day, "%Y-%m-%d").date()
        by_month[(dt_obj.year, dt_obj.month)] += t.pnl_nifty_pts()
    red = sum(1 for v in by_month.values() if v < 0)
    return {
        'n': n, 'pts': pts, 'rs': rs, 'wr': len(wins)/n,
        'avg_win':  sum(t.pnl_prem_per_lot() for t in wins)  / len(wins)   if wins   else 0,
        'avg_loss': sum(t.pnl_prem_per_lot() for t in losses) / len(losses) if losses else 0,
        'max_dd': max_dd, 'red_months': red, 'total_months': len(by_month)
    }

# -------------------- Main --------------------
def main():
    import time
    t0 = time.time()
    print("\n[BOOT] Searching for phase3_daily.pkl...")

    target_path = resolve_dataset_path()
    if not target_path:
        print("[FATAL] Could not find phase3_daily.pkl.")
        print("Expected at: /home/Selukar/phase3_daily.pkl  (PythonAnywhere)")
        print("         or: /storage/emulated/0/Download/backtest_out/phase3_daily.pkl  (Android)")
        return

    print(f"[BOOT] Dataset found: {target_path}")
    print("[BOOT] Loading data...")
    with open(target_path, 'rb') as f:
        daily = pickle.load(f)

    df5, df15, df1h = build_continuous_streams(daily)
    print(f"[DATA] {len(daily)} sessions loaded, {len(df5)} 5m bars total.")

    print("\n" + "="*90)
    print("ORION V2.5.7 BACKTEST — Velvet Rope + Accelerated Ratchet")
    print("="*90)

    trs, _ = run_combo('V2.5.7', daily, df5, df15, df1h,
                       entry_model='v2_v3', exit_model='sma8_tratchet', use_delta_shift=False)
    s = compute_stats(trs)
    rm = f"{s['red_months']}/{s['total_months']}" if s['total_months'] else "—"

    print(f"\n{'Variant':<20} {'Trades':>7} {'NiftyPts':>9} {'PnL (Rs)':>13} {'WR%':>6} {'avgW':>6} {'avgL':>7} {'MaxDD':>7} {'RedM':>6}")
    print("-"*90)
    print(f"{'V2.5.7 Velvet Rope':<20} {s['n']:>7d} {s['pts']:+9.0f} {s['rs']:+13,.0f} {s['wr']*100:>6.1f}% {s['avg_win']:+6.1f} {s['avg_loss']:+7.1f} {s['max_dd']:+7.0f} {rm:>6}")
    print("="*90)
    print(f"\nRuntime: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
