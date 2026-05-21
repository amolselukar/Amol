"""
=========================================================================
ORION_BACKTEST_REALOPT.py — Backtest on real daily_option_data
=========================================================================
Runs V2.5.8, V2.5.9, V2.5.12 strategies on REAL option OHLCV data
collected by Optiondata.py in /home/Selukar/daily_option_data/

Data format (per day folder):
  nifty_1h.csv   : historical 1h bars back to Feb 2026 (SMA/RSI/MACD)
  nifty_15m.csv  : rolling 15m bars (StochRSI K)
  CE/<strike>.csv : real option OHLCV, columns: tf,date,open,high,low,close,volume
  PE/<strike>.csv : same
  atm_tracker_5m.csv : ATM strike per 5m bar

Pushes results to GitHub automatically via PAT.
=========================================================================
"""
import os, sys, json, glob, subprocess
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Dict, List

DATA_BASE = "/home/Selukar/daily_option_data"
REPO_DIR  = "/home/Selukar/Amol"
OUT_FILE  = f"{REPO_DIR}/realopt_result.txt"
BRANCH    = "claude/general-session-YfHuZ"
LOT_SIZE  = 65

sys.path.insert(0, REPO_DIR)
try:
    from credentials import GITHUB_PAT as _PAT
    GITHUB_PAT = _PAT
except (ImportError, AttributeError):
    GITHUB_PAT = None

# ─── Indicators ───────────────────────────────────────────────────────
def _rsi(close, n=14):
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def _stochrsi_k(close, length=14, rsi_length=14, smooth=3):
    r = _rsi(close, rsi_length)
    lo = r.rolling(length).min(); hi = r.rolling(length).max()
    raw = (r - lo) / (hi - lo).replace(0, np.nan) * 100.0
    return raw.rolling(smooth).mean()

def _macd(close, fast=12, slow=26, sig=9):
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    line = ef - es
    return line, line.ewm(span=sig, adjust=False).mean()

# ─── Version parameters ───────────────────────────────────────────────
VERSIONS = {
    'V2.5.8': dict(
        hardsl=0.25, ri=12, rt=20, rs=25,
        rsi_ce=None, rsi_pe=None, macd=False,
        prem_min=0, prem_max=9999, k_extreme=False,
        tier2_peak=None, tier3_peak=None,
    ),
    'V2.5.9': dict(
        hardsl=0.25, ri=12, rt=20, rs=25,
        rsi_ce=53, rsi_pe=47, macd=True,
        prem_min=30, prem_max=180, k_extreme=True,
        tier2_peak=None, tier3_peak=None,
    ),
    'V2.5.12': dict(
        hardsl=0.18, ri=12, rt=None, rs=25,
        rsi_ce=53, rsi_pe=47, macd=True,
        prem_min=30, prem_max=180, k_extreme=True,
        tier2_peak=24, tier2_sl=12,
        tier3_peak=36, tier3_sl=24,
    ),
}

SMA_FAST, SMA_SLOW = 20, 50
K_EXTREME_BARS = 3
K_OVERSOLD, K_OVERBOUGHT = 25, 75
STOCHRSI_CE_LO, STOCHRSI_PE_HI = 38, 80
V2_K_FLOOR_PE = 25
CIRCUIT_BREAKER = 3
SMA_TRAIL_PERIOD = 8
MARKET_OPEN  = "09:15"
ENTRY_CUTOFF = "14:45"  # last 15m bar for entry
FORCE_CLOSE  = "15:20"

# ─── Load one day's data ──────────────────────────────────────────────
def load_day(day_str):
    ddir = f"{DATA_BASE}/{day_str}"
    if not os.path.exists(ddir):
        return None
    # 1h nifty
    df1h = pd.read_csv(f"{ddir}/nifty_1h.csv", parse_dates=['date'])
    df1h = df1h.sort_values('date').reset_index(drop=True)
    df1h['date'] = df1h['date'].dt.tz_localize(None)
    # 15m nifty
    df15 = pd.read_csv(f"{ddir}/nifty_15m.csv", parse_dates=['date'])
    df15 = df15.sort_values('date').reset_index(drop=True)
    df15['date'] = df15['date'].dt.tz_localize(None)
    # Option OHLCV per strike (5m only)
    opt = {}
    for side in ('CE', 'PE'):
        sdir = f"{ddir}/{side}"
        if not os.path.exists(sdir): continue
        for fp in glob.glob(f"{sdir}/*.csv"):
            strike = int(os.path.basename(fp).replace('.csv',''))
            df = pd.read_csv(fp, parse_dates=['date'])
            df['date'] = df['date'].dt.tz_localize(None)
            df5 = df[df['tf']=='5m'].sort_values('date').reset_index(drop=True)
            if len(df5): opt[(strike, side)] = df5
    # ATM tracker
    atm_df = pd.read_csv(f"{ddir}/atm_tracker_5m.csv", parse_dates=['time'])
    atm_df['time'] = atm_df['time'].dt.tz_localize(None)
    return dict(df1h=df1h, df15=df15, opt=opt, atm_df=atm_df, day=day_str)

# ─── Simulate one trade (version-aware) ──────────────────────────────
def simulate_exit(side, entry_dt, entry_prem, opt_bars_5m, p):
    """
    opt_bars_5m: DataFrame of 5m option bars from entry_dt onwards
    p: version params dict
    Returns: (exit_dt, exit_prem, reason)
    """
    hardsl = entry_prem * (1 - p['hardsl'])
    tr_armed = False
    tr_sl = 0.0
    peak = entry_prem
    bars = opt_bars_5m[opt_bars_5m['date'] >= entry_dt].reset_index(drop=True)
    if bars.empty:
        return entry_dt, entry_prem, 'NO_DATA'
    # Build 15m bars for SMA8(low) trail
    sma8_bars = []

    for _, bar in bars.iterrows():
        dt = bar['date']
        o, h, l, c = bar['open'], bar['high'], bar['low'], bar['close']
        peak = max(peak, h)
        # Accumulate 15m-ish: every 3rd 5m bar
        sma8_bars.append(l)

        # Force close
        if dt.strftime('%H:%M') >= FORCE_CLOSE:
            return dt, c, 'FORCE_CLOSE'

        # HARDSL
        if l <= hardsl:
            return dt, hardsl, f'HARDSL_{int(p["hardsl"]*100)}pct'

        elapsed = (dt - entry_dt).total_seconds() / 60

        # Velvet Rope
        if not tr_armed and h >= entry_prem + p['ri']:
            tr_armed = True
            tr_sl = entry_prem + 2
            if l <= tr_sl:
                return dt, tr_sl, 'VELVET_ROPE'

        if tr_armed:
            # V2.5.12 peak-based ladder (no time gate)
            if p.get('tier2_peak') is not None:
                if peak >= entry_prem + p['tier3_peak'] and tr_sl < entry_prem + p['tier3_sl']:
                    tr_sl = entry_prem + p['tier3_sl']
                elif peak >= entry_prem + p['tier2_peak'] and tr_sl < entry_prem + p['tier2_sl']:
                    tr_sl = entry_prem + p['tier2_sl']
            else:
                # V2.5.8/9: time gate at RT minutes
                if p['rt'] and tr_sl == entry_prem + 2 and elapsed >= p['rt']:
                    if h >= entry_prem + 25:
                        tr_sl = entry_prem + 15

            # Runner step
            while h >= tr_sl + p['rs']:
                tr_sl += p['rs']
            if l <= tr_sl:
                pts = int(tr_sl - entry_prem)
                return dt, tr_sl, f'RATCHET_+{pts}'

        # SMA8(low) trail — check every 3 bars
        if len(sma8_bars) >= SMA_TRAIL_PERIOD and len(sma8_bars) % 3 == 0:
            sma8l = np.mean(sma8_bars[-SMA_TRAIL_PERIOD:])
            if c < sma8l:
                return dt, c, 'SMA8_TRAIL'

    last = bars.iloc[-1]
    return last['date'], last['close'], 'EOD'

# ─── Entry check for one 15m bar ─────────────────────────────────────
def check_entry(bar15_idx, df15_today, df1h_prior, K_series_today, p):
    """Returns ('CE'/'PE'/None, reason_str)"""
    if bar15_idx < 1: return None, "warmup"
    brow = df15_today.iloc[bar15_idx]
    bar_time = brow['date']
    if bar_time.strftime('%H:%M') > ENTRY_CUTOFF: return None, "after_cutoff"

    # 1h: get last closed bar
    bar_date = bar_time.normalize()
    h1_prior = df1h_prior[df1h_prior['date'] < bar_time]
    if len(h1_prior) < SMA_SLOW + 5: return None, "insufficient_1h"
    h1 = h1_prior.iloc[-1]
    s20 = h1.get('SMA20'); s50 = h1.get('SMA50')
    if pd.isna(s20) or pd.isna(s50): return None, "sma_nan"
    rsi_val = h1.get('RSI')
    ml = h1.get('MACD_line'); ms = h1.get('MACD_sig')

    # K at this bar
    if bar15_idx >= len(K_series_today): return None, "K_missing"
    Kn = K_series_today[bar15_idx]
    Kp = K_series_today[bar15_idx - 1] if bar15_idx > 0 else None
    if pd.isna(Kn) or Kp is None or pd.isna(Kp): return None, "K_nan"

    close = brow['close']

    # SMA alignment
    ce_sma = (close > s20) and (s20 > s50)
    pe_sma = (close < s20) and (s20 < s50)

    # K signal
    sig_ce = ce_sma and (Kn >= STOCHRSI_CE_LO) and (Kn > Kp)
    sig_pe = pe_sma and (Kn <= STOCHRSI_PE_HI) and (Kn < Kp) and (Kn >= V2_K_FLOOR_PE)

    # K extreme filter
    if p['k_extreme']:
        if sig_ce:
            recent_K = [K_series_today[max(0, bar15_idx-i)] for i in range(K_EXTREME_BARS)]
            if not any(k < K_OVERSOLD for k in recent_K if not pd.isna(k)):
                sig_ce = False
        if sig_pe:
            recent_K = [K_series_today[max(0, bar15_idx-i)] for i in range(K_EXTREME_BARS)]
            if not any(k > K_OVERBOUGHT for k in recent_K if not pd.isna(k)):
                sig_pe = False

    # RSI gate
    if p['rsi_ce'] and sig_ce and (rsi_val is None or pd.isna(rsi_val) or rsi_val <= p['rsi_ce']):
        sig_ce = False
    if p['rsi_pe'] and sig_pe and (rsi_val is None or pd.isna(rsi_val) or rsi_val >= p['rsi_pe']):
        sig_pe = False

    # MACD
    if p['macd']:
        if sig_ce and (ml is None or ms is None or pd.isna(ml) or pd.isna(ms) or ml <= ms):
            sig_ce = False
        if sig_pe and (ml is None or ms is None or pd.isna(ml) or pd.isna(ms) or ml >= ms):
            sig_pe = False

    side = 'CE' if sig_ce else ('PE' if sig_pe else None)
    rsi_str  = f"{rsi_val:.1f}" if (rsi_val is not None and not pd.isna(rsi_val)) else 'N/A'
    macd_str = ('bull' if (ml is not None and ms is not None and not pd.isna(ml) and ml > ms)
                else 'bear' if (ml is not None and ms is not None and not pd.isna(ml) and ml < ms)
                else 'N/A')
    detail = (f"SMA({'ok' if ce_sma else 'NO'}/{'ok' if pe_sma else 'NO'}) "
              f"K={Kn:.1f}({'↑' if Kn>Kp else '↓'}) RSI={rsi_str} MACD={macd_str}")
    return side, detail

# ─── Run one version on all days ─────────────────────────────────────
def run_version(days_data, version_name):
    p = VERSIONS[version_name]
    trades = []
    for dd in days_data:
        day_str = dd['day']
        df1h = dd['df1h'].copy()
        df15 = dd['df15'].copy()
        opt  = dd['opt']

        # Compute 1h indicators on full series
        df1h['SMA20'] = df1h['close'].rolling(SMA_FAST).mean()
        df1h['SMA50'] = df1h['close'].rolling(SMA_SLOW).mean()
        df1h['RSI']   = _rsi(df1h['close'])
        df1h['MACD_line'], df1h['MACD_sig'] = _macd(df1h['close'])

        # Today's date
        day_date = datetime.strptime(day_str, '%Y-%m-%d').date()
        day_start = datetime(day_date.year, day_date.month, day_date.day, 9, 15)
        day_end   = datetime(day_date.year, day_date.month, day_date.day, 15, 30)

        # Today's 15m bars only
        df15_today = df15[(df15['date'] >= day_start) & (df15['date'] <= day_end)].reset_index(drop=True)
        if df15_today.empty: continue

        # Full K series on rolling 15m (for warmup)
        K_full = _stochrsi_k(df15['close'])
        # Align to today's bars
        today_idx = df15[(df15['date'] >= day_start) & (df15['date'] <= day_end)].index.tolist()
        if not today_idx: continue
        K_today = [K_full.iloc[i] for i in today_idx]

        # 1h prior (for each signal bar: all 1h bars before that 15m bar)
        df1h_avail = df1h[df1h['date'] < day_start].copy()  # use prior day's 1h for entries

        # ATM: use first bar's nifty close rounded to 100
        first_n = df15_today.iloc[0]['close']
        atm = int(round(first_n / 100) * 100)

        daily_losses = 0
        halt = False
        next_entry_after = None

        for i in range(len(df15_today)):
            if halt: break
            brow = df15_today.iloc[i]
            bar_time = brow['date']

            if next_entry_after and bar_time < next_entry_after: continue

            side, detail = check_entry(i, df15_today, df1h, K_today, p)
            if side is None: continue

            # Strike selection: ATM rounded from spot at bar close
            spot = brow['close']
            atm_now = int(round(spot / 100) * 100)
            strike = atm_now  # use ATM

            # Get option bars
            opt_key = (strike, side)
            if opt_key not in opt:
                # Try ±50
                for adj in (50, -50, 100, -100):
                    if (strike+adj, side) in opt:
                        strike = strike+adj; opt_key = (strike, side)
                        break
                else:
                    continue

            opt_bars = opt[opt_key]
            # Entry is at next 5m bar after 15m close
            entry_dt = bar_time + timedelta(minutes=1)
            entry_bars = opt_bars[opt_bars['date'] >= entry_dt].reset_index(drop=True)
            if entry_bars.empty: continue
            entry_prem = entry_bars.iloc[0]['open']
            actual_entry_dt = entry_bars.iloc[0]['date']

            # Premium gate
            if not (p['prem_min'] <= entry_prem <= p['prem_max']): continue

            # Simulate exit
            exit_dt, exit_prem, reason = simulate_exit(
                side, actual_entry_dt, entry_prem, opt_bars, p)

            pnl_pts = exit_prem - entry_prem
            pnl_rs  = pnl_pts * 2 * LOT_SIZE  # 2 lots

            trades.append(dict(
                version=version_name, day=day_str,
                bar_time=bar_time.strftime('%H:%M'),
                side=side, strike=strike,
                entry_prem=round(entry_prem,2),
                exit_prem=round(exit_prem,2),
                pnl_pts=round(pnl_pts,1),
                pnl_rs=round(pnl_rs,0),
                reason=reason, detail=detail,
            ))

            # Circuit breaker
            if pnl_pts < 0:
                daily_losses += 1
                if daily_losses >= CIRCUIT_BREAKER: halt = True
            next_entry_after = exit_dt

    return trades

# ─── Stats ────────────────────────────────────────────────────────────
def print_stats(trades, label, out):
    def w(s=""): out.append(s); print(s)
    if not trades:
        w(f"\n[{label}] NO TRADES FIRED"); return
    total = len(trades)
    wins  = [t for t in trades if t['pnl_pts'] > 0]
    loss  = [t for t in trades if t['pnl_pts'] <= 0]
    pnl   = sum(t['pnl_rs'] for t in trades)
    wr    = len(wins)/total*100
    avg_w = np.mean([t['pnl_pts'] for t in wins]) if wins else 0
    avg_l = np.mean([t['pnl_pts'] for t in loss]) if loss else 0
    w(f"\n{'='*60}")
    w(f"  {label}")
    w(f"{'='*60}")
    w(f"  Trades   : {total}")
    w(f"  PnL (Rs) : ₹{pnl:+,.0f}")
    w(f"  Win Rate : {wr:.1f}%")
    w(f"  Avg Win  : {avg_w:+.1f} pts/lot")
    w(f"  Avg Loss : {avg_l:+.1f} pts/lot")
    w(f"{'='*60}")
    w(f"\n  Trade-by-trade:")
    for t in trades:
        flag = '✅' if t['pnl_pts'] > 0 else '❌'
        w(f"  {flag} {t['day']} {t['bar_time']} {t['side']} {t['strike']} "
          f"entry={t['entry_prem']} exit={t['exit_prem']} "
          f"pnl={t['pnl_pts']:+.1f}pts ({t['reason']})")

# ─── Main ─────────────────────────────────────────────────────────────
def main():
    out = []
    def w(s=""): out.append(s); print(s)

    dates = sorted(d for d in os.listdir(DATA_BASE)
                   if os.path.isdir(f"{DATA_BASE}/{d}") and d.startswith("20"))
    w(f"[REALOPT] Loading {len(dates)} days: {dates[0]} → {dates[-1]}")

    days_data = []
    for d in dates:
        dd = load_day(d)
        if dd: days_data.append(dd)
    w(f"[REALOPT] Loaded {len(days_data)} day datasets")

    all_trades = {}
    for vname in VERSIONS:
        w(f"\n[REALOPT] Running {vname}...")
        trades = run_version(days_data, vname)
        all_trades[vname] = trades
        print_stats(trades, vname, out)

    # Side-by-side comparison
    w(f"\n{'='*60}")
    w(f"  COMPARISON (real option data, {len(dates)} days)")
    w(f"{'='*60}")
    w(f"  {'VERSION':<10} {'TRADES':>7} {'PNL_Rs':>12} {'WIN%':>7} {'AVG_W':>8} {'AVG_L':>8}")
    w(f"  {'-'*55}")
    for vname, trades in all_trades.items():
        if not trades:
            w(f"  {vname:<10} {'0':>7} {'N/A':>12} {'N/A':>7} {'N/A':>8} {'N/A':>8}")
            continue
        pnl  = sum(t['pnl_rs'] for t in trades)
        wins = [t for t in trades if t['pnl_pts'] > 0]
        loss = [t for t in trades if t['pnl_pts'] <= 0]
        wr   = len(wins)/len(trades)*100
        aw   = np.mean([t['pnl_pts'] for t in wins]) if wins else 0
        al   = np.mean([t['pnl_pts'] for t in loss]) if loss else 0
        w(f"  {vname:<10} {len(trades):>7} ₹{pnl:>+10,.0f} {wr:>6.1f}% {aw:>+7.1f} {al:>+7.1f}")
    w(f"{'='*60}")
    w(f"\nNote: Real option OHLCV | 2 lots | {dates[0]}–{dates[-1]}")

    # Write and push
    with open(OUT_FILE, 'w') as f:
        f.write('\n'.join(out))
    print(f"\nResults saved to {OUT_FILE}")

    try:
        subprocess.run(["git", "add", OUT_FILE], cwd=REPO_DIR, check=True)
        r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_DIR)
        if r.returncode != 0:
            subprocess.run(["git", "commit", "-m",
                f"realopt_backtest: V2.5.8/9/12 on {len(dates)} days real option data"],
                cwd=REPO_DIR, check=True)
            remote = f"https://{GITHUB_PAT}@github.com/amolselukar/Amol.git" if GITHUB_PAT else "origin"
            subprocess.run(["git", "push", remote, BRANCH], cwd=REPO_DIR, check=True)
            print("Results pushed to GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Git push failed: {e}")

if __name__ == "__main__":
    main()
