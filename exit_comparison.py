"""
==========================================================================
exit_comparison.py  —  ORION Exit Strategy Comparison (May 2026)
==========================================================================
Compares three exit configs for V2/V3/FLIP engine trades:

  Config A (current) : SMA8(low) trail on 15m option bars
  Config B (proposed): VWAP trail — exit when 5m close < option daily VWAP
  Config C (control) : NO secondary trail — only trail-after-TP + HARDSL

Entry logic is IDENTICAL to ORION_BACKTEST_OFFLINE.py:
  - Nifty Futures 15m bar body >= 65% of range
  - Bar closes ABOVE daily fut VWAP → CE signal
  - Bar closes BELOW daily fut VWAP → PE signal
  - LIMIT_OFFSET=0 → market entry at ref_price

Trail-after-TP (SAME for ALL configs):
  - HARDSL: entry * (1 - 0.18)  always armed
  - Trail arm  : when peak >= entry + 15
  - Trail SL   : max(entry+10, peak-5), ratchets up, never down
  - Exit when bar.low <= hardsl → HARDSL
  - Exit when bar.low <= tr_sl (if armed) → TRAIL exit

Secondary trail (DIFFERS):
  Config A: 15m bar close < SMA8(low of last 8 15m bars) → SMA8_TRAIL
  Config B: 5m  bar close < option daily VWAP            → VWAP_TRAIL
  Config C: disabled

Data: option_data/selukar/<date>/CE|PE/<strike>.csv (5m bars)
      market_data/nifty_fut_15m.csv
==========================================================================
"""
import os, sys, glob
import pandas as pd
import numpy as np
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Paths ──────────────────────────────────────────────────────────────
FUT15M_CSV = os.path.join(REPO_DIR, 'market_data', 'nifty_fut_15m.csv')
OPT_BASES  = [
    os.path.join(REPO_DIR, 'option_data', 'selukar'),
    os.path.join(REPO_DIR, 'option_data', 'amol'),
]

# ── Constants (same as ORION_BACKTEST_OFFLINE) ─────────────────────────
LOT_SIZE        = 65
LOTS            = 2
HARDSL_PCT      = 0.18
FORCE_CLOSE     = "15:25"
ENTRY_CUTOFF    = "14:45"
PREM_MIN        = 30
PREM_MAX        = 300
BODY_MIN_PCT    = 0.65      # upgraded from 0.50 per spec
LIMIT_OFFSET    = 0
CIRCUIT_BREAKER = 3
SMA_TRAIL_BARS  = 8

# Trail-after-TP params (same for all configs)
TRAIL_ARM_ABOVE   = 15   # arm when peak >= entry + 15
TRAIL_SL_OFFSET   = 5    # tr_sl = peak - 5
TRAIL_SL_MIN_PROF = 10   # tr_sl >= entry + 10


# ══════════════════════════════════════════════════════════════════════
#  DATA LOADING
# ══════════════════════════════════════════════════════════════════════

def load_fut15m() -> pd.DataFrame:
    if not os.path.exists(FUT15M_CSV):
        sys.exit(f"[ERROR] Futures data not found: {FUT15M_CSV}")
    df = pd.read_csv(FUT15M_CSV, parse_dates=['date'])
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    df = df.sort_values('date').drop_duplicates('date').reset_index(drop=True)
    print(f"[FUT] Loaded {len(df)} bars  {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}")
    return df


def compute_fut_vwap(df_day: pd.DataFrame) -> pd.Series:
    tp  = (df_day['high'] + df_day['low'] + df_day['close']) / 3
    vol = df_day['volume'].fillna(1).replace(0, 1)
    return ((tp * vol).cumsum() / vol.cumsum()).reset_index(drop=True)


def compute_opt_vwap_series(opt5m: pd.DataFrame) -> pd.DataFrame:
    """
    Return a copy of opt5m with a 'vwap' column (cumulative daily VWAP
    computed from 9:15 AM using typical price × volume).
    """
    df = opt5m.copy()
    tp  = (df['high'] + df['low'] + df['close']) / 3
    vol = df['volume'].fillna(1).replace(0, 1)
    df['vwap'] = (tp * vol).cumsum() / vol.cumsum()
    return df


def discover_days() -> List[str]:
    days = set()
    for base in OPT_BASES:
        if not os.path.isdir(base):
            continue
        for d in os.listdir(base):
            if d.startswith('20') and os.path.isdir(os.path.join(base, d)):
                days.add(d)
    return sorted(days)


def load_day_options(day_str: str) -> Optional[dict]:
    """
    Returns dict with:
      df15_spot  : spot 15m DataFrame
      opt        : {(strike, side): 5m DataFrame}
      opt_vwap   : {(strike, side): 5m DataFrame with vwap column}
    """
    for base in OPT_BASES:
        ddir = os.path.join(base, day_str)
        if not os.path.isdir(ddir):
            continue
        try:
            p15 = os.path.join(ddir, 'nifty_15m.csv')
            if not os.path.exists(p15):
                continue
            df15 = pd.read_csv(p15, parse_dates=['date'])
            df15['date'] = pd.to_datetime(df15['date']).dt.tz_localize(None)
            df15 = df15.sort_values('date').drop_duplicates('date').reset_index(drop=True)

            opt       = {}
            opt_vwap  = {}

            for side in ('CE', 'PE'):
                sdir = os.path.join(ddir, side)
                if not os.path.isdir(sdir):
                    continue
                for fp in glob.glob(os.path.join(sdir, '*.csv')):
                    try:
                        strike = int(os.path.basename(fp).replace('.csv', ''))
                        df5 = pd.read_csv(fp, parse_dates=['date'])
                        df5['date'] = pd.to_datetime(df5['date']).dt.tz_localize(None)
                        if 'tf' in df5.columns:
                            df5 = df5[df5['tf'] == '5m']
                        df5 = df5.sort_values('date').drop_duplicates('date').reset_index(drop=True)
                        if not df5.empty:
                            # filter to current day only (some files contain multi-day data)
                            day_date = datetime.strptime(day_str, '%Y-%m-%d').date()
                            df5 = df5[df5['date'].dt.date == day_date].reset_index(drop=True)
                        if not df5.empty:
                            opt[(strike, side)]      = df5
                            opt_vwap[(strike, side)] = compute_opt_vwap_series(df5)
                    except Exception:
                        pass

            if not opt:
                continue
            return dict(df15_spot=df15, opt=opt, opt_vwap=opt_vwap, source=base, day=day_str)
        except Exception as e:
            print(f"  [LOAD] {day_str} in {base}: {e}")
            continue
    return None


# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════

def atm_strike(spot: float) -> int:
    return int(round(spot / 50) * 50)


def opt_price_at(opt_df: pd.DataFrame, at_time: datetime) -> Optional[float]:
    mask = opt_df['date'] <= at_time
    if not mask.any():
        return None
    return float(opt_df.loc[mask, 'close'].iloc[-1])


# ══════════════════════════════════════════════════════════════════════
#  EXIT SIMULATION (3 configs)
# ══════════════════════════════════════════════════════════════════════

def simulate_exit_A(opt5m: pd.DataFrame, entry_time: datetime,
                    entry_prem: float) -> Tuple[datetime, float, str]:
    """
    Config A: SMA8(low) secondary trail on 5m bars.
    Uses 5m bars directly (each 5m bar is checked).
    SMA8 check: only when len(seen_lows) >= 8 and len(seen_lows) % 3 == 0
    (matches original V2.5.12 logic adapted to 5m bars; or alternatively
     we use every bar once we have 8 lows).
    """
    hardsl   = entry_prem * (1 - HARDSL_PCT)
    tr_armed = False
    tr_sl    = 0.0
    peak     = entry_prem
    sma_lows: List[float] = []

    bars = opt5m[opt5m['date'] >= entry_time].reset_index(drop=True)
    if bars.empty:
        return entry_time, entry_prem, 'NO_DATA'

    for _, bar in bars.iterrows():
        dt = bar['date']
        h  = float(bar['high'])
        l  = float(bar['low'])
        c  = float(bar['close'])

        peak = max(peak, h)
        sma_lows.append(l)

        if dt.strftime('%H:%M') >= FORCE_CLOSE:
            return dt, c, 'FORCE_CLOSE'

        # HARDSL always first
        if l <= hardsl:
            return dt, round(hardsl, 2), 'HARDSL_-18pct'

        # Trail-after-TP
        if not tr_armed and peak >= entry_prem + TRAIL_ARM_ABOVE:
            tr_armed = True
            tr_sl    = max(entry_prem + TRAIL_SL_MIN_PROF,
                           peak - TRAIL_SL_OFFSET)

        if tr_armed:
            # ratchet up, never down
            new_sl = max(entry_prem + TRAIL_SL_MIN_PROF, peak - TRAIL_SL_OFFSET)
            tr_sl  = max(tr_sl, new_sl)
            if l <= tr_sl:
                pts = round(tr_sl - entry_prem, 1)
                return dt, round(tr_sl, 2), f'TRAIL_+{int(pts)}'

        # Config A secondary trail: SMA8(low) — check every bar once ≥ 8 lows
        if len(sma_lows) >= SMA_TRAIL_BARS:
            sma8l = float(np.mean(sma_lows[-SMA_TRAIL_BARS:]))
            if c < sma8l:
                return dt, c, 'SMA8_TRAIL'

    last = bars.iloc[-1]
    return last['date'], float(last['close']), 'EOD'


def simulate_exit_B(opt5m: pd.DataFrame, opt5m_vwap: pd.DataFrame,
                    entry_time: datetime,
                    entry_prem: float) -> Tuple[datetime, float, str]:
    """
    Config B: VWAP trail.
    Secondary exit: when 5m bar close < option daily VWAP at that bar.
    Only fires BEFORE trail-after-TP arms (i.e. peak < entry + TRAIL_ARM_ABOVE).
    """
    hardsl   = entry_prem * (1 - HARDSL_PCT)
    tr_armed = False
    tr_sl    = 0.0
    peak     = entry_prem

    bars      = opt5m[opt5m['date'] >= entry_time].reset_index(drop=True)
    bars_vwap = opt5m_vwap[opt5m_vwap['date'] >= entry_time].reset_index(drop=True)

    if bars.empty:
        return entry_time, entry_prem, 'NO_DATA'

    for idx in range(len(bars)):
        bar = bars.iloc[idx]
        dt  = bar['date']
        h   = float(bar['high'])
        l   = float(bar['low'])
        c   = float(bar['close'])

        peak = max(peak, h)

        if dt.strftime('%H:%M') >= FORCE_CLOSE:
            return dt, c, 'FORCE_CLOSE'

        # HARDSL always first
        if l <= hardsl:
            return dt, round(hardsl, 2), 'HARDSL_-18pct'

        # Trail-after-TP
        if not tr_armed and peak >= entry_prem + TRAIL_ARM_ABOVE:
            tr_armed = True
            tr_sl    = max(entry_prem + TRAIL_SL_MIN_PROF,
                           peak - TRAIL_SL_OFFSET)

        if tr_armed:
            new_sl = max(entry_prem + TRAIL_SL_MIN_PROF, peak - TRAIL_SL_OFFSET)
            tr_sl  = max(tr_sl, new_sl)
            if l <= tr_sl:
                pts = round(tr_sl - entry_prem, 1)
                return dt, round(tr_sl, 2), f'TRAIL_+{int(pts)}'

        # Config B secondary trail: VWAP — only before trail arms
        if not tr_armed:
            vwap_val = None
            if idx < len(bars_vwap):
                vwap_val = float(bars_vwap.iloc[idx]['vwap'])
            if vwap_val is not None and c < vwap_val:
                return dt, c, 'VWAP_TRAIL'

    last = bars.iloc[-1]
    return last['date'], float(last['close']), 'EOD'


def simulate_exit_C(opt5m: pd.DataFrame, entry_time: datetime,
                    entry_prem: float) -> Tuple[datetime, float, str]:
    """
    Config C: NO secondary trail.
    Only HARDSL + trail-after-TP + force close.
    """
    hardsl   = entry_prem * (1 - HARDSL_PCT)
    tr_armed = False
    tr_sl    = 0.0
    peak     = entry_prem

    bars = opt5m[opt5m['date'] >= entry_time].reset_index(drop=True)
    if bars.empty:
        return entry_time, entry_prem, 'NO_DATA'

    for _, bar in bars.iterrows():
        dt = bar['date']
        h  = float(bar['high'])
        l  = float(bar['low'])
        c  = float(bar['close'])

        peak = max(peak, h)

        if dt.strftime('%H:%M') >= FORCE_CLOSE:
            return dt, c, 'FORCE_CLOSE'

        if l <= hardsl:
            return dt, round(hardsl, 2), 'HARDSL_-18pct'

        if not tr_armed and peak >= entry_prem + TRAIL_ARM_ABOVE:
            tr_armed = True
            tr_sl    = max(entry_prem + TRAIL_SL_MIN_PROF,
                           peak - TRAIL_SL_OFFSET)

        if tr_armed:
            new_sl = max(entry_prem + TRAIL_SL_MIN_PROF, peak - TRAIL_SL_OFFSET)
            tr_sl  = max(tr_sl, new_sl)
            if l <= tr_sl:
                pts = round(tr_sl - entry_prem, 1)
                return dt, round(tr_sl, 2), f'TRAIL_+{int(pts)}'

    last = bars.iloc[-1]
    return last['date'], float(last['close']), 'EOD'


# ══════════════════════════════════════════════════════════════════════
#  DAY RUNNER
# ══════════════════════════════════════════════════════════════════════

def run_day(day_str: str, df_fut15: pd.DataFrame, day_opt: dict,
            day_date: date) -> Tuple[List[dict], List[str]]:
    """Run all 3 configs on the same entry signals for one day."""
    trades = []
    notes  = []

    IST_09_15 = datetime(day_date.year, day_date.month, day_date.day, 9, 15)
    IST_15_30 = datetime(day_date.year, day_date.month, day_date.day, 15, 30)

    fut_day = df_fut15[
        (df_fut15['date'] >= IST_09_15) &
        (df_fut15['date'] <= IST_15_30)
    ].reset_index(drop=True)

    if fut_day.empty:
        notes.append(f"  {day_str}: NO futures 15m data")
        return trades, notes

    fut_day = fut_day.copy()
    fut_day['vwap'] = compute_fut_vwap(fut_day)

    df15_spot  = day_opt['df15_spot']
    opt        = day_opt['opt']
    opt_vwap   = day_opt['opt_vwap']

    # Per-config circuit breaker state
    cb_losses = {'A': 0, 'B': 0, 'C': 0}
    halted    = {'A': False, 'B': False, 'C': False}
    last_exit = {'A': None,  'B': None,  'C': None}
    last_vwap_bar = None   # signal dedup (same for all, entry is shared)

    for i in range(1, len(fut_day)):
        fbar     = fut_day.iloc[i]
        bar_time = fbar['date']

        if bar_time.strftime('%H:%M') > ENTRY_CUTOFF:
            break

        # All 3 halted → stop
        if all(halted.values()):
            break

        # Signal dedup — skip if bar already processed
        if last_vwap_bar == bar_time:
            continue

        fo, fh, fl, fc = (float(fbar['open']), float(fbar['high']),
                          float(fbar['low']),  float(fbar['close']))
        vwap    = float(fbar['vwap'])
        f_range = fh - fl
        if f_range <= 0:
            continue
        body_pct = abs(fc - fo) / f_range
        if body_pct < BODY_MIN_PCT:
            continue

        if fc > vwap:
            side = 'CE'
        elif fc < vwap:
            side = 'PE'
        else:
            continue

        # ATM from spot
        spot_at = df15_spot[df15_spot['date'] <= bar_time]
        if spot_at.empty:
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: no spot bar — skip")
            continue
        spot_price = float(spot_at.iloc[-1]['close'])
        atm = atm_strike(spot_price)

        opt_key = (atm, side)
        if opt_key not in opt:
            found = False
            for adj in (50, -50, 100, -100):
                if (atm + adj, side) in opt:
                    opt_key = (atm + adj, side)
                    found = True
                    break
            if not found:
                notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                              f"no option for ATM {atm} {side} — skip")
                continue

        opt_df      = opt[opt_key]
        opt_df_vwap = opt_vwap[opt_key]
        strike      = opt_key[0]

        ref_price = opt_price_at(opt_df, bar_time)
        if ref_price is None or ref_price <= 0:
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                         f"{strike}{side} no price — skip")
            continue

        if not (PREM_MIN <= ref_price <= PREM_MAX):
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                         f"{side} {strike} ref={ref_price:.1f} outside "
                         f"[{PREM_MIN},{PREM_MAX}] — skip")
            continue

        # Market entry (LIMIT_OFFSET=0)
        fill_price = round(ref_price, 2)
        fill_time  = bar_time

        last_vwap_bar = bar_time

        # ── Run all 3 configs ─────────────────────────────────────────
        results = {}
        if not halted['A']:
            if last_exit['A'] is None or fill_time > last_exit['A']:
                et_A, ep_A, rs_A = simulate_exit_A(opt_df, fill_time, fill_price)
                results['A'] = (et_A, ep_A, rs_A)
        if not halted['B']:
            if last_exit['B'] is None or fill_time > last_exit['B']:
                et_B, ep_B, rs_B = simulate_exit_B(opt_df, opt_df_vwap, fill_time, fill_price)
                results['B'] = (et_B, ep_B, rs_B)
        if not halted['C']:
            if last_exit['C'] is None or fill_time > last_exit['C']:
                et_C, ep_C, rs_C = simulate_exit_C(opt_df, fill_time, fill_price)
                results['C'] = (et_C, ep_C, rs_C)

        if not results:
            continue

        for cfg, (exit_time, exit_prem, reason) in results.items():
            pnl_pts = round(exit_prem - fill_price, 2)
            pnl_rs  = round(pnl_pts * LOT_SIZE * LOTS, 2)
            trades.append(dict(
                config    = cfg,
                day       = day_str,
                sig_time  = bar_time.strftime('%H:%M'),
                exit_time = exit_time.strftime('%H:%M'),
                side      = side,
                strike    = strike,
                entry     = fill_price,
                exit      = round(exit_prem, 2),
                pnl_pts   = pnl_pts,
                pnl_rs    = pnl_rs,
                reason    = reason,
                body_pct  = round(body_pct, 2),
            ))
            last_exit[cfg] = exit_time
            if pnl_pts < 0:
                cb_losses[cfg] += 1
                if cb_losses[cfg] >= CIRCUIT_BREAKER:
                    halted[cfg] = True
                    notes.append(f"  {day_str} cfg={cfg}: CIRCUIT BREAKER after "
                                 f"{cb_losses[cfg]} losses")

    return trades, notes


# ══════════════════════════════════════════════════════════════════════
#  REPORTING
# ══════════════════════════════════════════════════════════════════════

def print_config_summary(cfg_label: str, cfg_desc: str,
                         trades: List[dict], days_loaded: List[str]):
    sep = '─' * 70
    print(f"\n{'═'*70}")
    print(f"  CONFIG {cfg_label}: {cfg_desc}")
    print(f"{'═'*70}")

    if not trades:
        print("  NO TRADES")
        return

    wins  = [t for t in trades if t['pnl_pts'] > 0]
    loss  = [t for t in trades if t['pnl_pts'] <= 0]
    total_pts = sum(t['pnl_pts'] for t in trades)
    total_rs  = sum(t['pnl_rs']  for t in trades)
    wr = len(wins) / len(trades) * 100

    print(f"\n  Total trades : {len(trades)}  (W:{len(wins)}  L:{len(loss)})")
    print(f"  Win rate     : {wr:.1f}%")
    print(f"  Total PnL    : {total_pts:+.1f} pts  |  Rs {total_rs:+,.0f}")
    if wins:
        print(f"  Avg win      : {np.mean([t['pnl_pts'] for t in wins]):+.1f} pts")
    if loss:
        print(f"  Avg loss     : {np.mean([t['pnl_pts'] for t in loss]):+.1f} pts")

    # Green days
    day_groups: Dict[str, List] = {}
    for t in trades:
        day_groups.setdefault(t['day'], []).append(t)
    green_days = sum(1 for d, dtrades in day_groups.items()
                     if sum(t['pnl_pts'] for t in dtrades) > 0)
    print(f"  Green days   : {green_days}/{len(days_loaded)}")
    avg_per_day = total_rs / len(days_loaded) if days_loaded else 0
    print(f"  Avg day PnL  : Rs {avg_per_day:+,.0f}")

    # Exit reason breakdown
    reasons: Dict = {}
    for t in trades:
        r = t['reason']
        reasons.setdefault(r, {'n': 0, 'pnl': 0, 'wins': 0})
        reasons[r]['n']    += 1
        reasons[r]['pnl']  += t['pnl_pts']
        if t['pnl_pts'] > 0:
            reasons[r]['wins'] += 1
    print(f"\n  EXIT REASON BREAKDOWN:")
    print(f"  {'Reason':<22}  {'N':>4}  {'Wins':>5}  {'PnL_pts':>10}  {'PnL_Rs':>12}")
    print(f"  {sep}")
    for r, v in sorted(reasons.items(), key=lambda x: -x[1]['pnl']):
        print(f"  {r:<22}  {v['n']:>4}  {v['wins']:>5}  "
              f"{v['pnl']:>+10.1f}  Rs {v['pnl']*LOT_SIZE*LOTS:>+10,.0f}")

    # Per-day PnL
    print(f"\n  PER-DAY PnL:")
    print(f"  {'Date':<12}  {'#':>3}  {'W':>3}  {'PnL_pts':>10}  {'PnL_Rs':>12}  {'WR%':>6}")
    print(f"  {sep}")
    for d in sorted(day_groups):
        dtrades  = day_groups[d]
        dpnl_pts = sum(t['pnl_pts'] for t in dtrades)
        dpnl_rs  = sum(t['pnl_rs']  for t in dtrades)
        dw       = sum(1 for t in dtrades if t['pnl_pts'] > 0)
        dwr      = dw / len(dtrades) * 100
        flag     = 'GRN' if dpnl_pts > 0 else 'RED'
        print(f"  [{flag}] {d:<10}  {len(dtrades):>3}  {dw:>3}  "
              f"{dpnl_pts:>+10.1f}  Rs {dpnl_rs:>+10,.0f}  {dwr:>6.1f}%")

    # Trade-by-trade
    print(f"\n  TRADE-BY-TRADE:")
    print(f"  {'Date':<12} {'SIG':>5} {'EXIT':>5}  {'S':>2}  "
          f"{'STK':>6}  {'ENTRY':>7}  {'EXIT_P':>7}  {'PTS':>7}  {'Rs':>9}  REASON")
    print(f"  {sep}")
    for t in trades:
        flag = '+' if t['pnl_pts'] > 0 else '-'
        print(f"  [{flag}] {t['day']:<10} {t['sig_time']:>5} {t['exit_time']:>5}  "
              f"{t['side']:>2}  {t['strike']:>6}  {t['entry']:>7.2f}  "
              f"{t['exit']:>7.2f}  {t['pnl_pts']:>+7.2f}  Rs {t['pnl_rs']:>+8,.0f}  {t['reason']}")


def print_comparison_table(cfg_stats: dict, days_loaded: List[str]):
    print(f"\n{'='*70}")
    print(f"  SIDE-BY-SIDE COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"  {'Metric':<25}  {'Config A':>14}  {'Config B':>14}  {'Config C':>14}")
    print(f"  {'─'*70}")
    metrics = [
        ('Total trades',      'trades'),
        ('Win rate %',        'wr'),
        ('Total PnL (pts)',   'total_pts'),
        ('Total PnL (Rs)',    'total_rs'),
        ('Avg win (pts)',     'avg_win'),
        ('Avg loss (pts)',    'avg_loss'),
        ('Green days',        'green_days'),
        ('Avg day PnL (Rs)',  'avg_day_rs'),
    ]
    for label, key in metrics:
        vals = [cfg_stats.get(c, {}).get(key, 'N/A') for c in ('A', 'B', 'C')]
        def fmt(v):
            if isinstance(v, float):
                if abs(v) > 100:
                    return f"{v:+,.0f}"
                return f"{v:+.1f}"
            return str(v)
        print(f"  {label:<25}  {fmt(vals[0]):>14}  {fmt(vals[1]):>14}  {fmt(vals[2]):>14}")
    print(f"  {'─'*70}")
    print(f"\n  Config A: SMA8(low) trail (current)")
    print(f"  Config B: Option VWAP trail (proposed)")
    print(f"  Config C: No secondary trail (control — trail-after-TP + HARDSL only)")
    print(f"{'='*70}")


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    print('=' * 70)
    print('  ORION EXIT STRATEGY COMPARISON — May 2026')
    print(f'  BODY_MIN_PCT={BODY_MIN_PCT:.0%}  LIMIT_OFFSET={LIMIT_OFFSET}')
    print(f'  Trail arm: peak >= entry+{TRAIL_ARM_ABOVE}  |  Trail SL: peak-{TRAIL_SL_OFFSET} (min +{TRAIL_SL_MIN_PROF})')
    print('=' * 70)

    df_fut15 = load_fut15m()

    all_days = discover_days()
    if not all_days:
        sys.exit(f"[ERROR] No option data days found in {OPT_BASES}")
    print(f"[DATA] {len(all_days)} option days: {all_days[0]} → {all_days[-1]}")

    all_trades:  List[dict] = []
    all_notes:   List[str]  = []
    days_loaded: List[str]  = []

    for day_str in all_days:
        day_date  = datetime.strptime(day_str, '%Y-%m-%d').date()
        IST_09_15 = datetime(day_date.year, day_date.month, day_date.day, 9, 15)
        IST_15_30 = datetime(day_date.year, day_date.month, day_date.day, 15, 30)

        if df_fut15[(df_fut15['date'] >= IST_09_15) &
                    (df_fut15['date'] <= IST_15_30)].empty:
            all_notes.append(f"  {day_str}: No futures data — skipped")
            continue

        day_opt = load_day_options(day_str)
        if day_opt is None:
            all_notes.append(f"  {day_str}: No option data — skipped")
            continue

        print(f"  Processing {day_str} ...")
        days_loaded.append(day_str)
        trades, notes = run_day(day_str, df_fut15, day_opt, day_date)
        all_trades.extend(trades)
        all_notes.extend(notes)

    print(f"\n[DONE] {len(days_loaded)} days processed, "
          f"{len(all_trades)} trade-records (3 configs × signals)")

    # Split by config
    cfg_descs = {
        'A': 'SMA8(low) trail — 5m bars (current)',
        'B': 'Option VWAP trail — exit 5m close < daily VWAP',
        'C': 'No secondary trail — trail-after-TP + HARDSL only',
    }

    cfg_stats: dict = {}
    for cfg in ('A', 'B', 'C'):
        cfg_trades = [t for t in all_trades if t['config'] == cfg]
        print_config_summary(cfg, cfg_descs[cfg], cfg_trades, days_loaded)

        if cfg_trades:
            wins  = [t for t in cfg_trades if t['pnl_pts'] > 0]
            loss  = [t for t in cfg_trades if t['pnl_pts'] <= 0]
            day_groups = {}
            for t in cfg_trades:
                day_groups.setdefault(t['day'], []).append(t)
            green_days = sum(1 for d, dt in day_groups.items()
                             if sum(t['pnl_pts'] for t in dt) > 0)
            total_rs = sum(t['pnl_rs'] for t in cfg_trades)
            cfg_stats[cfg] = dict(
                trades    = len(cfg_trades),
                wr        = len(wins) / len(cfg_trades) * 100,
                total_pts = sum(t['pnl_pts'] for t in cfg_trades),
                total_rs  = total_rs,
                avg_win   = np.mean([t['pnl_pts'] for t in wins]) if wins else 0,
                avg_loss  = np.mean([t['pnl_pts'] for t in loss]) if loss else 0,
                green_days= green_days,
                avg_day_rs= total_rs / len(days_loaded) if days_loaded else 0,
            )

    print_comparison_table(cfg_stats, days_loaded)

    if all_notes:
        print(f"\n  SKIPPED SIGNALS / NOTES:")
        for n in all_notes:
            print(n)

    # Save to file
    import io, builtins
    # (results already printed to stdout — save a copy)
    out_path = os.path.join(REPO_DIR, 'exit_comparison_result.txt')
    print(f"\n[INFO] Results above. Script saved to: /home/user/Amol/exit_comparison.py")
    print(f"[INFO] To save output: python exit_comparison.py > exit_comparison_result.txt")


if __name__ == '__main__':
    main()
