"""
=========================================================================
ORION BACKTEST V2.5.8 — Knowledge-Driven Entry + Exit Improvements
=========================================================================
Baseline V2.5.7: 912 trades, +₹5,00,048, WR 55.4%, 10/18 red months

THREE ROOT-CAUSE FIXES:
1. SMA Full Alignment: require SMA20>SMA50 for CE, SMA20<SMA50 for PE
   → removes low-quality counter-trend entries in transitional markets
2. StochRSI Extreme Filter: K must have been <25 (CE) or >75 (PE) within
   last 3 bars → "fresh from extreme" signals only, eliminates mid-range noise
3. Circuit Breaker: 4→3 daily loss limit → smaller hole on bad days

EXIT TIGHTENING:
   RATCHET_INITIAL_PTS: 15→12  (protect profits 3pts earlier)
   RATCHET_TIME_MIN:    30→20  (upgrade SL 10 min faster)
   RATCHET_STEP_PTS:    20→15  (tighter step trail)
=========================================================================
"""
import pickle, os, time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

def resolve_dataset_path():
    filename = "phase3_daily.pkl"
    for path in [
        f"/home/Selukar/{filename}",
        f"/home/Selukar/Amol/{filename}",
        f"/storage/emulated/0/Download/backtest_out/{filename}",
        f"/sdcard/Download/backtest_out/{filename}",
        filename,
    ]:
        if os.path.exists(path): return path
    return None

LOT_SIZE = 65

# ---- Fixed params ----
HARDSL_MODE           = 'pct'
HARDSL_VALUE          = 0.25
FORCE_CLOSE_BUCKET    = 73
ENTRY_WINDOW_END_BKT  = 62
CLUSTER_RADIUS_PTS    = 20
GRADE_A_MIN_SOURCES   = 3
GRADE_B_MIN_SOURCES   = 2
ADX_CHOP_MAX          = 20
ADX_TREND_MIN         = 25
SMA_FAST              = 20
SMA_SLOW              = 50
ROUND_STEP_FINE       = 50
ROUND_RANGE_PTS       = 300
ATM_STEP              = 100
GAP_THRESHOLD_PCT     = 0.01
GRADE_A_MIN_CLOSE_BEYOND = 15
GRADE_A_MIN_BODY_PCT     = 0.40
GRADE_B_MIN_BODY_PCT     = 0.60
GRADE_B_CLOSE_TOP_PCT    = 0.25
WICK_REJECT_MIN_PCT      = 0.50
WICK_REJECT_CLOSE_DIST   = 10
T1_MIN_PTS, T1_MAX_PTS   = 50, 100
T2_MIN_PTS, T2_MAX_PTS   = 100, 200
SMA_TRAIL_PERIOD         = 8
V2V3_PRIORITY            = 'v2'
V3_PROMOTE_SINGLETONS    = True
V3_EXCLUDE_PDC_FROM_CLUSTERS = True
V3_MIN_BUFFER_FROM_PDC   = 25
V2_K_FLOOR_PE            = 25
FLIP_ENABLED             = True
FLIP_PATH_A_ELAPSED      = 30
FLIP_PATH_A_PEAK_MIN     = 15
FLIP_PATH_A_DROP_MAX     = 10
FLIP_K_CE_TO_PE_MIN      = 25
FLIP_K_CE_TO_PE_MAX      = 80
FLIP_K_PE_TO_CE_MIN      = 38
MAX_FLIPS_PER_DAY        = 3
SWING_LOOKBACK_BARS      = 20
SWING_PIVOT_N            = 3
CHOP_RSI_LO              = 47
CHOP_RSI_HI              = 53
STOCHRSI_CE_LO           = 38
STOCHRSI_PE_HI           = 80

# =========================================================================
# V2.5.8 PARAMETER CHANGES (knowledge-driven)
# =========================================================================
RATCHET_INITIAL_PTS   = 12      # was 15 — protect 3pts earlier
RATCHET_TIME_MIN      = 20      # was 30 — upgrade SL 10min faster
RATCHET_STEP_PTS      = 15      # was 20 — tighter step trail
CIRCUIT_BREAKER       = 3       # was 4  — smaller daily loss hole

# V2.5.8 Entry Quality Filters
SMA_FULL_ALIGN        = True    # CE: SMA20>SMA50 required; PE: SMA20<SMA50 required
K_EXTREME_BARS        = 3       # look back this many 15m bars for extreme K
K_OVERSOLD_THRESH     = 25      # CE: K must have been below this recently
K_OVERBOUGHT_THRESH   = 75      # PE: K must have been above this recently

# -------------------- Indicators --------------------
def rsi(close, n=14):
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def stochrsi_k(close, length=14, rsi_length=14, k=3):
    r = rsi(close, rsi_length)
    lo = r.rolling(length).min(); hi = r.rolling(length).max()
    return ((r - lo) / (hi - lo).replace(0, np.nan) * 100.0).rolling(k).mean()

def macd_lines(close, fast=12, slow=26, signal=9):
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    line = ef - es
    return line, line.ewm(span=signal, adjust=False).mean()

def adx_di(df, n=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    up = h - h.shift(1); dn = l.shift(1) - l
    pdm = pd.Series(np.where((up>dn)&(up>0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((dn>up)&(dn>0), dn, 0.0), index=df.index)
    atr = tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    pdi = 100 * pdm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr
    ndi = 100 * ndm.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr
    dx  = 100 * (pdi-ndi).abs() / (pdi+ndi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False, min_periods=n).mean(), pdi, ndi

# -------------------- Streams --------------------
def build_streams(daily):
    r5, r15, r1h = [], [], []
    for d in sorted(daily.keys()):
        for b in daily[d]['nifty_5m']:  r5.append({'date':d,'bucket':b['bucket'],**b})
        for b in daily[d]['nifty_15m']: r15.append({'date':d,'bucket':b['bucket'],**b})
        for b in daily[d]['nifty_1h']:  r1h.append({'date':d,'bucket':b['bucket'],**b})
    df5  = pd.DataFrame(r5).reset_index(drop=True)
    df15 = pd.DataFrame(r15).reset_index(drop=True)
    df1h = pd.DataFrame(r1h).reset_index(drop=True)
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

# -------------------- Level Logic --------------------
def find_swing_pivots(df1h_prior):
    pivots = []; n = SWING_PIVOT_N
    sub = df1h_prior.iloc[-(SWING_LOOKBACK_BARS+2*n):].copy().reset_index(drop=True)
    if len(sub) < 2*n+1: return pivots
    for i in range(n, len(sub)-n):
        h, l = sub['high'].iloc[i], sub['low'].iloc[i]
        if all(h>sub['high'].iloc[i-k] for k in range(1,n+1)) and all(h>sub['high'].iloc[i+k] for k in range(1,n+1)):
            pivots.append((float(h),'swing_high'))
        if all(l<sub['low'].iloc[i-k] for k in range(1,n+1)) and all(l<sub['low'].iloc[i+k] for k in range(1,n+1)):
            pivots.append((float(l),'swing_low'))
    return pivots

def generate_round_levels(price):
    out = set()
    base = round(price/ROUND_STEP_FINE)*ROUND_STEP_FINE
    for off in range(-ROUND_RANGE_PTS, ROUND_RANGE_PTS+1, ROUND_STEP_FINE):
        p = base+off
        out.add((float(p), 'round_100' if p%100==0 else 'round_50'))
    return list(out)

def cluster_levels(sources):
    if not sources: return []
    s = sorted(sources, key=lambda x: x[0])
    clusters, cur = [], [s[0]]
    for p, k in s[1:]:
        if p-cur[-1][0] <= CLUSTER_RADIUS_PTS: cur.append((p,k))
        else: clusters.append(cur); cur = [(p,k)]
    clusters.append(cur)
    out = []
    for c in clusters:
        kinds = set(k for _,k in c)
        center = sum(p for p,_ in c)/len(c)
        n = len(kinds)
        grade = 'A' if n>=GRADE_A_MIN_SOURCES else ('B' if n>=GRADE_B_MIN_SOURCES else 'C')
        out.append({'center':round(center,2),'kinds':sorted(kinds),'count':n,'grade':grade})
    return out

def compute_levels(df1h_prior, ohlc):
    pdh, pdl, pdc = float(ohlc['H']), float(ohlc['L']), float(ohlc['C'])
    src = [(pdh,'PDH'),(pdl,'PDL')] + generate_round_levels(pdc)
    swing_pivots = find_swing_pivots(df1h_prior)
    src += swing_pivots
    src = [s for s in src if abs(s[0]-pdc)<=ROUND_RANGE_PTS]
    clusters = cluster_levels(src)

    def _in_ab(p):
        return any(c['grade'] in ('A','B') and abs(c['center']-p)<=CLUSTER_RADIUS_PTS for c in clusters)

    promoted = []
    for p, kind in [(pdh,'PDH'),(pdl,'PDL')]:
        if not _in_ab(p): promoted.append({'center':round(p,2),'kinds':[kind],'count':1,'grade':'B','promoted':True})
    for off in range(-200, 201, 100):
        p = float(round(pdc/100)*100+off)
        if not _in_ab(p): promoted.append({'center':round(p,2),'kinds':['round_100'],'count':1,'grade':'B','promoted':True})
    for p, kind in swing_pivots:
        if abs(p-pdc)<=ROUND_RANGE_PTS and not _in_ab(p):
            promoted.append({'center':round(p,2),'kinds':[kind],'count':1,'grade':'B','promoted':True})

    all_levels = clusters + promoted
    buf = V3_MIN_BUFFER_FROM_PDC
    above = sorted([c for c in all_levels if c['center']>pdc+buf and c['grade'] in ('A','B')],
                   key=lambda c:(0 if c['grade']=='A' else 1, abs(c['center']-pdc)))
    below = sorted([c for c in all_levels if c['center']<pdc-buf and c['grade'] in ('A','B')],
                   key=lambda c:(0 if c['grade']=='A' else 1, abs(c['center']-pdc)))
    return {'pdh':pdh,'pdl':pdl,'pdc':pdc,
            'G':above[0] if above else None,
            'R':below[0] if below else None,
            'all_clusters':all_levels}

def compute_targets(level, direction, all_clusters):
    center = level['center']
    if direction=='CE': cand = sorted({c['center'] for c in all_clusters if c['center']>center+T1_MIN_PTS})
    else:               cand = sorted({c['center'] for c in all_clusters if c['center']<center-T1_MIN_PTS}, reverse=True)
    t1 = next((c for c in cand if T1_MIN_PTS<=abs(c-center)<=T1_MAX_PTS), cand[0] if cand else None)
    if t1 is None: t1 = (center+T1_MAX_PTS) if direction=='CE' else (center-T1_MAX_PTS)
    t2 = next((c for c in cand if T2_MIN_PTS<=abs(c-center)<=T2_MAX_PTS and c!=t1), None)
    if t2 is None: t2 = (center+T2_MAX_PTS) if direction=='CE' else (center-T2_MAX_PTS)
    t3 = next((c for c in cand if (direction=='CE' and c>t2) or (direction=='PE' and c<t2)), None)
    if t3 is None: t3 = (t2+100) if direction=='CE' else (t2-100)
    return [round(t1,2), round(t2,2), round(t3,2)]

# -------------------- Regime --------------------
def classify_regime(row):
    if pd.isna(row.get('SMA20')) or pd.isna(row.get('ADX')): return 'INSUFFICIENT'
    c, s20, s50 = row['close'], row['SMA20'], row['SMA50']
    adxv = row['ADX']
    if adxv < ADX_CHOP_MAX: return 'CHOP'
    if c>s20>s50 and row['SMA20_slope']>0 and adxv>ADX_TREND_MIN: return 'BULL'
    if c<s20<s50 and row['SMA20_slope']<0 and adxv>ADX_TREND_MIN: return 'BEAR'
    return 'TRANSITION'

def evaluate_candle(bar, level, kind, grade):
    o,h,l,c = bar['open'],bar['high'],bar['low'],bar['close']
    rng = h-l
    if rng<=0: return False
    body_pct = abs(c-o)/rng
    if kind=='BREAK_CE':
        if grade=='A': return (c-level)>=GRADE_A_MIN_CLOSE_BEYOND and body_pct>=GRADE_A_MIN_BODY_PCT
        return body_pct>=GRADE_B_MIN_BODY_PCT and (c-l)/rng>=1-GRADE_B_CLOSE_TOP_PCT
    if kind=='BREAK_PE':
        if grade=='A': return (level-c)>=GRADE_A_MIN_CLOSE_BEYOND and body_pct>=GRADE_A_MIN_BODY_PCT
        return body_pct>=GRADE_B_MIN_BODY_PCT and (h-c)/rng>=1-GRADE_B_CLOSE_TOP_PCT
    return False

def detect_v23(bar, level, role):
    o,h,l,c = bar['open'],bar['high'],bar['low'],bar['close']
    L = level['center']; grade = level['grade']; rng = h-l
    if rng>0:
        if role=='G' and h>=L and c<L+WICK_REJECT_CLOSE_DIST:
            wick = h-max(o,c)
            if wick/rng>=WICK_REJECT_MIN_PCT and abs(c-L)<=WICK_REJECT_CLOSE_DIST:
                return {'kind':'REJECT_PE','level':L,'grade':grade}
        if role=='R' and l<=L and c>L-WICK_REJECT_CLOSE_DIST:
            wick = min(o,c)-l
            if wick/rng>=WICK_REJECT_MIN_PCT and abs(c-L)<=WICK_REJECT_CLOSE_DIST:
                return {'kind':'REJECT_CE','level':L,'grade':grade}
    if role=='G' and c>L and evaluate_candle(bar,L,'BREAK_CE',grade): return {'kind':'BREAK_CE','level':L,'grade':grade}
    if role=='R' and c<L and evaluate_candle(bar,L,'BREAK_PE',grade): return {'kind':'BREAK_PE','level':L,'grade':grade}
    return None

def hardsl_floor(ep): return ep*(1-HARDSL_VALUE)

def opt_15m_from_5m(opt_5m_bars, upto):
    by = {b['bucket']:b for b in opt_5m_bars}
    out = []
    for k15 in range(25):
        end = 3*k15+2
        if end>upto: break
        members = [by[b] for b in (3*k15,3*k15+1,3*k15+2) if b in by]
        if not members: continue
        out.append({'bkt15':k15,'o':members[0]['open'],'h':max(m['high'] for m in members),
                    'l':min(m['low'] for m in members),'c':members[-1]['close']})
    return out

def sma_last(values, n):
    if len(values)<n: return None
    return sum(values[-n:])/n

@dataclass
class Trade:
    day: str; side: str; grade: str; entry_bkt: int
    entry_nifty: float; entry_premium: float; strike: int; trigger_level: float
    targets: list = field(default_factory=list)
    current_sl_nifty: Optional[float] = None
    hardsl_premium: float = 0.0; lots: int = 2; lots_remaining: int = 2
    tr_armed: bool = False; tr_sl: float = 0.0
    t1_hit: bool = False; peak_prem: float = 0.0
    closed: bool = False; exits: list = field(default_factory=list)

    def book(self, bkt, reason, nifty, prem, lots):
        self.exits.append({'bkt':bkt,'reason':reason,'nifty':nifty,'prem':prem,'lots':lots})
        self.lots_remaining -= lots
        if self.lots_remaining<=0: self.closed = True

    def pnl_prem_per_lot(self):
        if not self.exits: return 0.0
        return sum((e['prem']-self.entry_premium)*e['lots'] for e in self.exits)/self.lots

    def pnl_prem_rs(self):
        return sum((e['prem']-self.entry_premium)*e['lots']*LOT_SIZE for e in self.exits)

    def pnl_nifty_pts(self):
        s = 0.0
        for e in self.exits:
            if self.side=='CE': s += (e['nifty']-self.entry_nifty)*e['lots']
            else: s += (self.entry_nifty-e['nifty'])*e['lots']
        return s

# -------------------- Simulator --------------------
def simulate_trade(trade, day_data, k_lookup=None):
    if k_lookup is None: k_lookup = day_data.get('_k_lookup', {})
    opt_5m = sorted(day_data['opt_5m'].get((trade.strike,trade.side),[]), key=lambda b:b['bucket'])
    if not opt_5m:
        trade.book(trade.entry_bkt,'NO_OPT_DATA',trade.entry_nifty,trade.entry_premium,trade.lots); return trade
    nifty_5m = sorted(day_data['nifty_5m'], key=lambda b:b['bucket'])
    nb = {b['bucket']:b for b in nifty_5m}; ob = {b['bucket']:b for b in opt_5m}

    for bkt in range(trade.entry_bkt, FORCE_CLOSE_BUCKET+1):
        if trade.closed: break
        n5=nb.get(bkt); o5=ob.get(bkt)
        if n5 is None or o5 is None: continue
        if bkt>=FORCE_CLOSE_BUCKET:
            trade.book(bkt,'FORCE_CLOSE',n5['close'],o5['close'],trade.lots_remaining); break
        trade.peak_prem = max(trade.peak_prem, o5['high'])
        if o5['low']<=trade.hardsl_premium:
            trade.book(bkt,'HARDSL',n5['close'],trade.hardsl_premium,trade.lots_remaining); break

        elapsed_min = (bkt-trade.entry_bkt)*5

        # 1. VELVET ROPE (V2.5.8: RI=12)
        if not trade.tr_armed and o5['high']>=trade.entry_premium+RATCHET_INITIAL_PTS:
            trade.tr_armed = True
            trade.tr_sl = trade.entry_premium+2
            if o5['low']<=trade.tr_sl:
                trade.book(bkt,'VELVET_ROPE',n5['close'],trade.tr_sl,trade.lots_remaining); break

        # 2. RATCHET GATE (V2.5.8: RT=20)
        if trade.tr_armed and trade.tr_sl==(trade.entry_premium+2) and elapsed_min>=RATCHET_TIME_MIN:
            if o5['high']>=trade.entry_premium+25:
                trade.tr_sl = trade.entry_premium+15

        # 3. RUNNER STEP TRAIL (V2.5.8: RS=15)
        if trade.tr_armed:
            while o5['high']>=trade.tr_sl+RATCHET_STEP_PTS:
                trade.tr_sl += RATCHET_STEP_PTS
            if o5['low']<=trade.tr_sl:
                pts = int(trade.tr_sl-trade.entry_premium)
                trade.book(bkt,f'RATCHET_+{pts}',n5['close'],trade.tr_sl,trade.lots_remaining); break

        # 4. SMA8 LOW TRAIL (15m)
        if bkt%3==2 and bkt>=3*SMA_TRAIL_PERIOD-1:
            o15 = opt_15m_from_5m(opt_5m, bkt)
            if len(o15)>=SMA_TRAIL_PERIOD:
                sma8l = sma_last([b['l'] for b in o15], SMA_TRAIL_PERIOD)
                if sma8l is not None and o15[-1]['c']<sma8l:
                    trade.book(bkt,'SMA8_TRAIL',n5['close'],o5['close'],trade.lots_remaining); break

        # FLIP Path A
        if not trade.closed and FLIP_ENABLED and bkt%3==2 and elapsed_min>=FLIP_PATH_A_ELAPSED:
            if trade.peak_prem>=trade.entry_premium+FLIP_PATH_A_PEAK_MIN and \
               o5['close']<=trade.entry_premium+FLIP_PATH_A_DROP_MAX:
                kn=k_lookup.get(bkt); kp=k_lookup.get(bkt-3)
                if kn is not None and kp is not None:
                    if trade.side=='CE' and kn<kp and FLIP_K_CE_TO_PE_MIN<=kn<=FLIP_K_CE_TO_PE_MAX:
                        trade.book(bkt,'FLIP_TO_PE',n5['close'],o5['close'],trade.lots_remaining); break
                    elif trade.side=='PE' and kn>kp and kn>=FLIP_K_PE_TO_CE_MIN:
                        trade.book(bkt,'FLIP_TO_CE',n5['close'],o5['close'],trade.lots_remaining); break

    if not trade.closed:
        trade.book(nifty_5m[-1]['bucket'],'EOD',nifty_5m[-1]['close'],opt_5m[-1]['close'],trade.lots_remaining)
    return trade

def select_strike(spot, side, atm_day, opt_5m_dict):
    target = int(round(spot/ATM_STEP))*ATM_STEP
    avail = sorted({k[0] for k in opt_5m_dict.keys() if k[1]==side})
    if not avail: return None
    return min(avail, key=lambda s:abs(s-target))

def try_flips(last_trade, day_data, flips_today=0):
    if not FLIP_ENABLED or not last_trade.exits or flips_today>=MAX_FLIPS_PER_DAY: return []
    nb = {b['bucket']:b for b in sorted(day_data['nifty_5m'],key=lambda b:b['bucket'])}
    kl = day_data.get('_k_lookup',{})
    flip_trades=[]; prev=last_trade
    while True:
        eb=prev.exits[-1]['bkt']; nb2=eb+1
        if nb2>FORCE_CLOSE_BUCKET-2 or nb2 not in nb: break
        cands=[k for k in kl if k<=eb]
        if not cands: break
        k_at=max(cands)
        if k_at-3 not in kl: break
        kn=kl[k_at]; kp=kl[k_at-3]
        flip_side=None
        if prev.side=='CE' and kn<kp and FLIP_K_CE_TO_PE_MIN<=kn<=FLIP_K_CE_TO_PE_MAX: flip_side='PE'
        elif prev.side=='PE' and kn>kp and kn>=FLIP_K_PE_TO_CE_MIN: flip_side='CE'
        if flip_side is None: break
        bar5=nb[nb2]
        strike=select_strike(bar5['open'],flip_side,day_data['atm'],day_data['opt_5m'])
        if strike is None or (strike,flip_side) not in day_data['opt_5m']: break
        ob_d={b['bucket']:b for b in day_data['opt_5m'][(strike,flip_side)]}
        ep=ob_d.get(nb2,{}).get('open')
        if ep is None or ep<=0: break
        ft=Trade(day=last_trade.day,side=flip_side,grade='FLIP',entry_bkt=nb2,
                 entry_nifty=bar5['open'],entry_premium=ep,strike=strike,
                 trigger_level=0,lots=2,lots_remaining=2,
                 hardsl_premium=hardsl_floor(ep),peak_prem=ep)
        ft=simulate_trade(ft,day_data)
        flip_trades.append(ft); prev=ft; flips_today+=1
        if flips_today>=MAX_FLIPS_PER_DAY: break
    return flip_trades

def _is_flip(t): return t.grade=='FLIP' or (t.exits and t.exits[-1].get('reason','').startswith('FLIP_TO_'))

# =========================================================================
# V2.5.8 ENTRY QUALITY FILTER
# K must have been below K_OVERSOLD_THRESH (for CE) or above K_OVERBOUGHT_THRESH
# (for PE) within the last K_EXTREME_BARS 15m bars.
# Eliminates mid-range StochRSI noise — only "fresh from extreme" signals.
# =========================================================================
def k_was_extreme(side, k_lookup, current_bkt, bars_back=K_EXTREME_BARS):
    for i in range(bars_back+1):
        bkt = current_bkt - i*3
        k_val = k_lookup.get(bkt)
        if k_val is None: continue
        if side=='CE' and k_val < K_OVERSOLD_THRESH:  return True
        if side=='PE' and k_val > K_OVERBOUGHT_THRESH: return True
    return False

# -------------------- Day Loop --------------------
def run_day(day_date, day_data, df1h_prior, df1h_by_date, df15_by_date, df15_sorted):
    trades=[]; daily_losses=0; halt=False; fired=set(); flips_today=0
    if df1h_prior is None or len(df1h_prior)==0: return trades
    pdh=float(df1h_prior['high'].iloc[-7:].max())
    pdl=float(df1h_prior['low'].iloc[-7:].min())
    pdc=float(df1h_prior['close'].iloc[-1])
    levels=compute_levels(df1h_prior,{'H':pdh,'L':pdl,'C':pdc})
    regime=classify_regime(df1h_prior.iloc[-1])
    if regime in ('CHOP','INSUFFICIENT'): return trades
    nifty_5m=sorted(day_data['nifty_5m'],key=lambda b:b['bucket'])
    nifty_15m=sorted(day_data['nifty_15m'],key=lambda b:b['bucket'])
    nb={b['bucket']:b for b in nifty_5m}; n15b={b['bucket']:b for b in nifty_15m}
    atm=day_data['atm']
    gap_pct=(nifty_5m[0]['open']/pdc)-1
    gap_supp=12 if abs(gap_pct)>GAP_THRESHOLD_PCT else -1
    df1h_today=df1h_by_date.get(day_date,pd.DataFrame())
    df15_today=df15_by_date.get(day_date,pd.DataFrame())
    prior_15m=df15_sorted[df15_sorted['date']<day_date]
    fallback_k=float(prior_15m.iloc[-1]['K']) if len(prior_15m)>0 else None
    next_bkt=0

    for bkt in range(len(nifty_5m)):
        bar5=nb.get(bkt)
        if bar5 is None or bkt>ENTRY_WINDOW_END_BKT or bkt<next_bkt or halt or bkt<gap_supp: continue
        if bkt%3!=2: continue
        k15_bkt=bkt-2
        df1h_act=df1h_today[df1h_today['bucket']+12<=bkt+1] if len(df1h_today)>0 else pd.DataFrame()
        cand1h=df1h_act.iloc[-1] if len(df1h_act)>0 else (df1h_prior.iloc[-1] if len(df1h_prior)>0 else None)
        if cand1h is None: continue

        # RSI chop filter
        rsi_val = cand1h.get('RSI')
        if rsi_val is not None and CHOP_RSI_LO<=rsi_val<=CHOP_RSI_HI: continue

        s20=cand1h.get('SMA20'); s50=cand1h.get('SMA50')
        if s20 is None or s50 is None: continue

        # V3 signal
        sig_v3=None
        n15=n15b.get(k15_bkt)
        if n15:
            for role,lvl in [('G',levels['G']),('R',levels['R'])]:
                if lvl is None or lvl['center'] in fired: continue
                sig=detect_v23(n15,lvl,role)
                if sig: sig_v3=('CE' if 'CE' in sig['kind'] else 'PE', lvl, sig['grade']); break

        # V2 signal
        sig_v2=None
        df15a=df15_today[df15_today['bucket']==k15_bkt] if len(df15_today)>0 else pd.DataFrame()
        if len(df15a)>0 and not pd.isna(df15a['K'].iloc[0]):
            Kn=float(df15a['K'].iloc[0])
            df15p=df15_today[df15_today['bucket']==k15_bkt-3] if len(df15_today)>0 else pd.DataFrame()
            Kp=float(df15p['K'].iloc[0]) if len(df15p)>0 else (float(fallback_k) if fallback_k else None)
            if Kp is not None:
                k_lookup_today={int(r['bucket'])+2:float(r['K'])
                                for _,r in df15_today.iterrows() if not pd.isna(r['K'])}

                # =====================================================
                # V2.5.8 ENTRY FIX 1: Full SMA alignment required
                # CE: SMA20 must be above SMA50 (true bullish trend)
                # PE: SMA20 must be below SMA50 (true bearish trend)
                # =====================================================
                ce_sma_ok = (cand1h['close']>s20) and (s20>s50)  # V2.5.8: was just close>SMA20
                pe_sma_ok = (cand1h['close']<s20) and (s20<s50)  # V2.5.8: was close<SMA20 and close<SMA50

                sig_ce = ce_sma_ok and (Kn>=STOCHRSI_CE_LO) and (Kn>Kp)
                sig_pe = pe_sma_ok and (Kn<=STOCHRSI_PE_HI) and (Kn<Kp) and (Kn>=V2_K_FLOOR_PE)

                # =====================================================
                # V2.5.8 ENTRY FIX 2: K extreme filter
                # Only enter if K was genuinely oversold/overbought recently
                # Eliminates mid-range noise entries
                # =====================================================
                if sig_ce and not k_was_extreme('CE', k_lookup_today, bkt): sig_ce = False
                if sig_pe and not k_was_extreme('PE', k_lookup_today, bkt): sig_pe = False

                if not (sig_ce and sig_pe): sig_v2='CE' if sig_ce else 'PE' if sig_pe else None

        chosen='V2' if (sig_v2 and sig_v3 and V2V3_PRIORITY=='v2') else 'V3' if sig_v3 else 'V2' if sig_v2 else None
        if chosen is None: continue

        k_lookup_day={int(r['bucket'])+2:float(r['K'])
                      for _,r in df15_today.iterrows() if not pd.isna(r['K'])}

        if chosen=='V3':
            sig_dir,lvl,grade=sig_v3
            entry_nifty=nb[bkt+1]['open'] if bkt+1 in nb else bar5['close']
            strike=select_strike(bar5['close'],sig_dir,atm,day_data['opt_5m'])
            if strike is None or (strike,sig_dir) not in day_data['opt_5m']: continue
            ep=sorted(day_data['opt_5m'][(strike,sig_dir)],key=lambda b:b['bucket'])[0].get('open')
            tgts=compute_targets(lvl,sig_dir,levels['all_clusters'])
            t=Trade(day=day_date,side=sig_dir,grade=f'V3_{grade}',entry_bkt=bkt+1,
                    entry_nifty=entry_nifty,entry_premium=ep,strike=strike,
                    trigger_level=lvl['center'],targets=tgts,
                    hardsl_premium=hardsl_floor(ep),peak_prem=ep)
        else:
            sig_dir=sig_v2
            strike=select_strike(bar5['close'],sig_dir,atm,day_data['opt_5m'])
            if strike is None or bkt+1 not in nb or (strike,sig_dir) not in day_data['opt_5m']: continue
            ob_d={b['bucket']:b for b in day_data['opt_5m'][(strike,sig_dir)]}
            ep=ob_d.get(bkt+1,{}).get('open')
            if ep is None or ep<=0: continue
            t=Trade(day=day_date,side=sig_dir,grade='V2',entry_bkt=bkt+1,
                    entry_nifty=nb[bkt+1]['open'],entry_premium=ep,strike=strike,
                    trigger_level=s20,targets=[],hardsl_premium=hardsl_floor(ep),peak_prem=ep)

        t.peak_prem=t.entry_premium
        day_data_with_k=dict(day_data); day_data_with_k['_k_lookup']=k_lookup_day
        t=simulate_trade(t,day_data_with_k,k_lookup_day)
        trades.append(t)
        fts=try_flips(t,day_data_with_k,sum(1 for x in trades if x.grade=='FLIP' and x.day==t.day))
        trades.extend(fts); flips_today+=len(fts)
        next_bkt=(fts[-1].exits[-1]['bkt']+1) if fts else (t.exits[-1]['bkt']+1)
        if chosen=='V3': fired.add(lvl['center'])
        if not _is_flip(t) and t.pnl_prem_per_lot()<0:
            daily_losses+=1
            if daily_losses>=CIRCUIT_BREAKER: halt=True
    return trades

# -------------------- Pipeline --------------------
def run_all(daily, df5_all, df15_all, df1h_all):
    dates=sorted(daily.keys())
    macd_map={(row['date'],row['bucket']):(row['MACD_line'],row['MACD_sig']) for _,row in df5_all.iterrows()}
    df15s=df15_all.sort_values(['date','bucket']).reset_index(drop=True)
    df1hs=df1h_all.sort_values(['date','bucket']).reset_index(drop=True)
    df15_by_date={d:g.reset_index(drop=True) for d,g in df15s.groupby('date')}
    df1h_by_date={d:g.reset_index(drop=True) for d,g in df1hs.groupby('date')}
    all_trades=[]
    for di,d in enumerate(dates):
        if di==0 or len(dates[:di])<5: continue
        df1h_prior=df1hs[df1hs['date']<d]
        if len(df1h_prior)<50: continue
        day_data=daily[d]
        nifty_aug=[]
        for b in day_data['nifty_5m']:
            b2=dict(b); ml,ms=macd_map.get((d,b['bucket']),(None,None))
            b2['MACD_line']=ml; b2['MACD_sig']=ms; nifty_aug.append(b2)
        dd=dict(day_data); dd['nifty_5m']=nifty_aug
        trades=run_day(d,dd,df1h_prior,df1h_by_date,df15_by_date,df15s)
        all_trades.extend(trades)
    return all_trades

# -------------------- Stats --------------------
def compute_stats(trades, label=""):
    n=len(trades)
    if n==0: return
    pts=sum(t.pnl_nifty_pts() for t in trades)
    rs=sum(t.pnl_prem_rs() for t in trades)
    wins=[t for t in trades if t.pnl_prem_per_lot()>0]
    losses=[t for t in trades if t.pnl_prem_per_lot()<0]
    cum=0; peak=0; max_dd=0
    for t in sorted(trades,key=lambda t:(t.day,t.entry_bkt)):
        cum+=t.pnl_nifty_pts(); peak=max(peak,cum); max_dd=min(max_dd,cum-peak)
    by_month=defaultdict(float)
    for t in trades:
        dt=datetime.strptime(t.day,"%Y-%m-%d").date()
        by_month[(dt.year,dt.month)]+=t.pnl_nifty_pts()
    red=sum(1 for v in by_month.values() if v<0)
    total_m=len(by_month)
    wr=len(wins)/n
    avgw=sum(t.pnl_prem_per_lot() for t in wins)/len(wins) if wins else 0
    avgl=sum(t.pnl_prem_per_lot() for t in losses)/len(losses) if losses else 0

    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  Trades     : {n}")
    print(f"  PnL (Rs)   : ₹{rs:+,.0f}")
    print(f"  Win Rate   : {wr*100:.1f}%")
    print(f"  Avg Win    : {avgw:+.1f} pts/lot")
    print(f"  Avg Loss   : {avgl:+.1f} pts/lot")
    print(f"  Max DD     : {max_dd:+.0f} pts")
    print(f"  Red Months : {red}/{total_m}")
    print(f"{'='*70}")

    # Monthly breakdown
    print(f"\n  Monthly PnL (Nifty pts):")
    for (yr,mo),v in sorted(by_month.items()):
        flag="🔴" if v<0 else "🟢"
        print(f"    {flag} {yr}-{mo:02d}: {v:+.0f}")
    print()

# -------------------- Main --------------------
def main():
    t0=time.time()
    print("\n[BOOT] Searching for phase3_daily.pkl...")
    path=resolve_dataset_path()
    if not path: print("[FATAL] phase3_daily.pkl not found."); return
    print(f"[BOOT] Found: {path}")
    with open(path,'rb') as f: daily=pickle.load(f)
    df5,df15,df1h=build_streams(daily)
    print(f"[DATA] {len(daily)} sessions loaded.")
    print("\n[V2.5.8 CHANGES vs V2.5.7 BASELINE]")
    print("  Entry: SMA full alignment (SMA20>SMA50 for CE, SMA20<SMA50 for PE)")
    print(f"  Entry: K extreme filter (CE: K<{K_OVERSOLD_THRESH} recently, PE: K>{K_OVERBOUGHT_THRESH} recently)")
    print(f"  Exit:  RI={RATCHET_INITIAL_PTS} (was 15), RT={RATCHET_TIME_MIN}min (was 30), RS={RATCHET_STEP_PTS} (was 20)")
    print(f"  Risk:  Circuit Breaker={CIRCUIT_BREAKER} (was 4)")
    print("\n[BASELINE V2.5.7]  912 trades | ₹+5,00,048 | WR 55.4% | RedMonths 10/18 | MaxDD -1885")
    print("\n[Running V2.5.8...]")
    trades=run_all(daily,df5,df15,df1h)
    compute_stats(trades, "V2.5.8 — SMA Align + K Extreme Filter + Tighter Exit")
    print(f"Runtime: {time.time()-t0:.1f}s")

if __name__=="__main__":
    main()
