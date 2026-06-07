"""
==========================================================================
ORION_BACKTEST_SWEEP.py
==========================================================================
Multi-strategy backtest sweep across 12 strategy variants.
Reads pre-fetched data:
  Nifty Futures 15m  → market_data/nifty_fut_15m.csv
  Option 5m data     → option_data/selukar/<day>/CE|PE/<strike>.csv
  Spot 15m           → option_data/selukar/<day>/nifty_15m.csv

12 strategies:
  EXIT VARIANTS  : BASELINE, NO_VR, FIXED_TP10, FIXED_TP15,
                   TIGHT_HARDSL, VR_RAISED
  ENTRY FILTERS  : NO_EARLY, OR_FILTER, VWAP_FLIP, BODY_STRICT
  COMBINATIONS   : COMBO_A, COMBO_B
==========================================================================
"""
import os, sys, glob, io, builtins, subprocess
import pandas as pd
import numpy as np
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple

REPO_DIR   = os.path.dirname(os.path.abspath(__file__))
FUT15M_CSV = os.path.join(REPO_DIR, 'market_data', 'nifty_fut_15m.csv')
OPT_BASES  = [
    os.path.join(REPO_DIR, 'option_data', 'selukar'),
    os.path.join(REPO_DIR, 'option_data', 'amol'),
]

# ── Global constants (shared across all strategies) ────────────────────
LOT_SIZE        = 65
LOTS            = 2
FORCE_CLOSE     = "15:25"
ENTRY_CUTOFF    = "14:45"
PREM_MIN        = 30
PREM_MAX        = 300
CIRCUIT_BREAKER = 3
SMA_TRAIL_BARS  = 8
RUNNER_STEP     = 25

# ── 12-strategy configs ────────────────────────────────────────────────
STRATEGIES = [
    # --- EXIT VARIANTS ---
    dict(
        name         = "BASELINE",
        # Exit
        hardsl_pct   = 0.18,
        ri           = 12,
        vr_sl        = 8,           # 0 = VR disabled
        t2_peak      = 24, t2_sl   = 12,
        t3_peak      = 36, t3_sl   = 24,
        runner_step  = 25,
        sma_trail    = True,
        fixed_tp     = 0,           # 0 = disabled
        # Entry filters
        skip_before  = None,        # e.g. "10:00" or None
        or_filter    = 0,           # 0 = disabled; pts threshold
        vwap_flip    = False,
        body_min     = 0.50,
    ),
    dict(
        name         = "NO_VR",
        hardsl_pct   = 0.18,
        ri           = 0,           # ri=0 ⟹ VR never triggers
        vr_sl        = 0,
        t2_peak      = 24, t2_sl   = 12,
        t3_peak      = 36, t3_sl   = 24,
        runner_step  = 25,
        sma_trail    = True,
        fixed_tp     = 0,
        skip_before  = None,
        or_filter    = 0,
        vwap_flip    = False,
        body_min     = 0.50,
    ),
    dict(
        name         = "FIXED_TP10",
        hardsl_pct   = 0.18,
        ri           = 0,
        vr_sl        = 0,
        t2_peak      = 9999, t2_sl = 9999,   # effectively disabled
        t3_peak      = 9999, t3_sl = 9999,
        runner_step  = 999999,
        sma_trail    = False,
        fixed_tp     = 10,
        skip_before  = None,
        or_filter    = 0,
        vwap_flip    = False,
        body_min     = 0.50,
    ),
    dict(
        name         = "FIXED_TP15",
        hardsl_pct   = 0.18,
        ri           = 0,
        vr_sl        = 0,
        t2_peak      = 9999, t2_sl = 9999,
        t3_peak      = 9999, t3_sl = 9999,
        runner_step  = 999999,
        sma_trail    = False,
        fixed_tp     = 15,
        skip_before  = None,
        or_filter    = 0,
        vwap_flip    = False,
        body_min     = 0.50,
    ),
    dict(
        name         = "TIGHT_HARDSL",
        hardsl_pct   = 0.13,        # tighter stop
        ri           = 12,
        vr_sl        = 8,
        t2_peak      = 24, t2_sl   = 12,
        t3_peak      = 36, t3_sl   = 24,
        runner_step  = 25,
        sma_trail    = True,
        fixed_tp     = 0,
        skip_before  = None,
        or_filter    = 0,
        vwap_flip    = False,
        body_min     = 0.50,
    ),
    dict(
        name         = "VR_RAISED",
        hardsl_pct   = 0.18,
        ri           = 18,          # raised velvet-rope trigger
        vr_sl        = 10,
        t2_peak      = 24, t2_sl   = 12,
        t3_peak      = 36, t3_sl   = 24,
        runner_step  = 25,
        sma_trail    = True,
        fixed_tp     = 0,
        skip_before  = None,
        or_filter    = 0,
        vwap_flip    = False,
        body_min     = 0.50,
    ),
    # --- ENTRY FILTERS (baseline exit) ---
    dict(
        name         = "NO_EARLY",
        hardsl_pct   = 0.18,
        ri           = 12, vr_sl   = 8,
        t2_peak      = 24, t2_sl   = 12,
        t3_peak      = 36, t3_sl   = 24,
        runner_step  = 25,
        sma_trail    = True,
        fixed_tp     = 0,
        skip_before  = "10:00",     # skip signals before 10:00
        or_filter    = 0,
        vwap_flip    = False,
        body_min     = 0.50,
    ),
    dict(
        name         = "OR_FILTER",
        hardsl_pct   = 0.18,
        ri           = 12, vr_sl   = 8,
        t2_peak      = 24, t2_sl   = 12,
        t3_peak      = 36, t3_sl   = 24,
        runner_step  = 25,
        sma_trail    = True,
        fixed_tp     = 0,
        skip_before  = None,
        or_filter    = 150,         # skip day if OR > 150 pts
        vwap_flip    = False,
        body_min     = 0.50,
    ),
    dict(
        name         = "VWAP_FLIP",
        hardsl_pct   = 0.18,
        ri           = 12, vr_sl   = 8,
        t2_peak      = 24, t2_sl   = 12,
        t3_peak      = 36, t3_sl   = 24,
        runner_step  = 25,
        sma_trail    = True,
        fixed_tp     = 0,
        skip_before  = None,
        or_filter    = 0,
        vwap_flip    = True,        # skip if first-3-bar VWAP side flipped
        body_min     = 0.50,
    ),
    dict(
        name         = "BODY_STRICT",
        hardsl_pct   = 0.18,
        ri           = 12, vr_sl   = 8,
        t2_peak      = 24, t2_sl   = 12,
        t3_peak      = 36, t3_sl   = 24,
        runner_step  = 25,
        sma_trail    = True,
        fixed_tp     = 0,
        skip_before  = None,
        or_filter    = 0,
        vwap_flip    = False,
        body_min     = 0.65,        # stricter body filter
    ),
    # --- COMBINATIONS ---
    dict(
        name         = "COMBO_A",
        hardsl_pct   = 0.13,        # tight SL
        ri           = 12, vr_sl   = 8,
        t2_peak      = 24, t2_sl   = 12,
        t3_peak      = 36, t3_sl   = 24,
        runner_step  = 25,
        sma_trail    = True,
        fixed_tp     = 0,
        skip_before  = "10:00",     # no early trades
        or_filter    = 0,
        vwap_flip    = False,
        body_min     = 0.50,
    ),
    dict(
        name         = "COMBO_B",
        hardsl_pct   = 0.18,
        ri           = 18, vr_sl   = 10,  # VR_RAISED
        t2_peak      = 24, t2_sl   = 12,
        t3_peak      = 36, t3_sl   = 24,
        runner_step  = 25,
        sma_trail    = True,
        fixed_tp     = 0,
        skip_before  = None,
        or_filter    = 150,         # skip high-volatility open days
        vwap_flip    = False,
        body_min     = 0.50,
    ),
]

# ══════════════════════════════════════════════════════════════════════════
# DATA LOADING (once)
# ══════════════════════════════════════════════════════════════════════════

def load_fut15m() -> pd.DataFrame:
    if not os.path.exists(FUT15M_CSV):
        print(f"[ERROR] Futures data not found: {FUT15M_CSV}")
        sys.exit(1)
    df = pd.read_csv(FUT15M_CSV, parse_dates=['date'])
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    df = df.sort_values('date').drop_duplicates('date').reset_index(drop=True)
    print(f"[FUT] Loaded {len(df)} bars  "
          f"{df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}")
    return df


def compute_fut_vwap(df_day: pd.DataFrame) -> pd.Series:
    tp  = (df_day['high'] + df_day['low'] + df_day['close']) / 3
    vol = df_day['volume'].fillna(1).replace(0, 1)
    return ((tp * vol).cumsum() / vol.cumsum()).reset_index(drop=True)


def discover_days() -> List[str]:
    days = set()
    for base in OPT_BASES:
        if not os.path.isdir(base):
            continue
        for d in os.listdir(base):
            dpath = os.path.join(base, d)
            if d.startswith('20') and os.path.isdir(dpath):
                days.add(d)
    return sorted(days)


def load_day_options(day_str: str) -> Optional[dict]:
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
            df15 = df15.sort_values('date').reset_index(drop=True)

            opt = {}
            for side in ('CE', 'PE'):
                sdir = os.path.join(ddir, side)
                if not os.path.isdir(sdir):
                    continue
                for fp in glob.glob(os.path.join(sdir, '*.csv')):
                    try:
                        strike = int(os.path.basename(fp).replace('.csv', ''))
                        dfopt  = pd.read_csv(fp, parse_dates=['date'])
                        dfopt['date'] = pd.to_datetime(dfopt['date']).dt.tz_localize(None)
                        if 'tf' in dfopt.columns:
                            dfopt = dfopt[dfopt['tf'] == '5m']
                        dfopt = dfopt.sort_values('date').reset_index(drop=True)
                        if not dfopt.empty:
                            opt[(strike, side)] = dfopt
                    except Exception:
                        pass

            if not opt:
                continue
            return dict(df15_spot=df15, opt=opt, source=base, day=day_str)
        except Exception as e:
            print(f"  [LOAD] {day_str} in {base}: {e}")
            continue
    return None


def atm_strike(spot: float) -> int:
    return int(round(spot / 50) * 50)


def opt_price_at(opt_df: pd.DataFrame, at_time: datetime) -> Optional[float]:
    mask = opt_df['date'] <= at_time
    if not mask.any():
        return None
    return float(opt_df.loc[mask, 'close'].iloc[-1])


# ══════════════════════════════════════════════════════════════════════════
# EXIT SIMULATION (config-driven)
# ══════════════════════════════════════════════════════════════════════════

def simulate_exit(opt_df: pd.DataFrame, entry_time: datetime,
                  entry_prem: float, cfg: dict) -> Tuple[datetime, float, str]:
    """
    cfg keys used:
      hardsl_pct  – fraction below entry (0.18 → -18%)
      ri          – velvet rope trigger (0 = VR disabled)
      vr_sl       – SL after VR arm (entry + vr_sl)
      t2_peak, t2_sl
      t3_peak, t3_sl
      runner_step – runner ratchet step
      sma_trail   – bool; SMA8(low) every 3-bar trail
      fixed_tp    – 0=disabled; pts above entry to take profit
    """
    hardsl_pct  = cfg['hardsl_pct']
    ri          = cfg['ri']
    vr_sl       = cfg['vr_sl']
    t2_peak     = cfg['t2_peak']
    t2_sl       = cfg['t2_sl']
    t3_peak     = cfg['t3_peak']
    t3_sl_val   = cfg['t3_sl']
    runner_step = cfg['runner_step']
    sma_trail   = cfg['sma_trail']
    fixed_tp    = cfg['fixed_tp']

    hardsl   = entry_prem * (1 - hardsl_pct)
    tr_armed = False
    tr_sl    = 0.0
    peak     = entry_prem
    sma_lows: List[float] = []

    bars = opt_df[opt_df['date'] >= entry_time].reset_index(drop=True)
    if bars.empty:
        return entry_time, entry_prem, 'NO_DATA'

    for _, bar in bars.iterrows():
        dt = bar['date']
        o, h, l, c = (float(bar['open']), float(bar['high']),
                      float(bar['low']),  float(bar['close']))

        peak = max(peak, h)
        sma_lows.append(l)

        # Force close
        if dt.strftime('%H:%M') >= FORCE_CLOSE:
            return dt, c, 'FORCE_CLOSE'

        # Fixed take-profit (checked before SL so a big gap doesn't skip it)
        if fixed_tp > 0 and h >= entry_prem + fixed_tp:
            tp_price = entry_prem + fixed_tp
            return dt, round(tp_price, 2), f'FIXED_TP+{fixed_tp}'

        # Hard SL
        if l <= hardsl:
            return dt, round(hardsl, 2), f'HARDSL_{int(hardsl_pct*100)}pct'

        # Velvet Rope
        if ri > 0 and not tr_armed and h >= entry_prem + ri:
            tr_armed = True
            tr_sl    = entry_prem + vr_sl
            if l <= tr_sl:
                return dt, round(tr_sl, 2), 'VELVET_ROPE'

        # Ladder + Runner (only when VR armed or ri==0 with no VR)
        if tr_armed or ri == 0:
            if not tr_armed:
                # ri==0 means no VR — we still want ratchet from the start
                # initialise tr_sl at -∞ so ladder can activate
                tr_armed = True
                tr_sl    = hardsl   # SL starts at hard-SL level

            # T3
            if peak >= entry_prem + t3_peak and tr_sl < entry_prem + t3_sl_val:
                tr_sl = entry_prem + t3_sl_val
            # T2
            elif peak >= entry_prem + t2_peak and tr_sl < entry_prem + t2_sl:
                tr_sl = entry_prem + t2_sl
            # Runner
            while peak >= tr_sl + runner_step:
                tr_sl += runner_step

            if l <= tr_sl and tr_sl > hardsl:
                pts = round(tr_sl - entry_prem, 1)
                tag = f'RATCHET_{int(pts):+d}' if pts != 0 else 'RATCHET'
                return dt, round(tr_sl, 2), tag

        # SMA8 trail (every 3rd bar, close < SMA8 of lows)
        if sma_trail and len(sma_lows) >= SMA_TRAIL_BARS and len(sma_lows) % 3 == 0:
            sma8l = float(np.mean(sma_lows[-SMA_TRAIL_BARS:]))
            if c < sma8l:
                return dt, c, 'SMA8_TRAIL'

    last = bars.iloc[-1]
    return last['date'], float(last['close']), 'EOD'


# ══════════════════════════════════════════════════════════════════════════
# DAY RUNNER (config-driven)
# ══════════════════════════════════════════════════════════════════════════

def run_day(day_str: str, df_fut15: pd.DataFrame, day_opt: dict,
            day_date: date, cfg: dict) -> Tuple[List[dict], List[str]]:
    """
    Entry filter config keys:
      skip_before  – "HH:MM" string or None
      or_filter    – 0=disabled; skip day if opening-range > or_filter pts
      vwap_flip    – bool; skip day if VWAP side flipped in first 3 bars
      body_min     – minimum body% (e.g. 0.50)
    """
    skip_before = cfg.get('skip_before', None)
    or_filter   = cfg.get('or_filter', 0)
    vwap_flip   = cfg.get('vwap_flip', False)
    body_min    = cfg.get('body_min', 0.50)

    trades: List[dict] = []
    notes:  List[str]  = []

    IST_09_15 = datetime(day_date.year, day_date.month, day_date.day, 9, 15)
    IST_15_30 = datetime(day_date.year, day_date.month, day_date.day, 15, 30)

    fut_day = df_fut15[
        (df_fut15['date'] >= IST_09_15) &
        (df_fut15['date'] <= IST_15_30)
    ].reset_index(drop=True)

    if fut_day.empty:
        return trades, notes

    fut_day = fut_day.copy()
    fut_day['vwap'] = compute_fut_vwap(fut_day)

    # ── Opening range filter ───────────────────────────────────────────
    if or_filter > 0:
        or_bars = fut_day[fut_day['date'].dt.strftime('%H:%M').isin(
            ['09:15', '09:30', '09:45']
        )]
        if not or_bars.empty:
            or_range = float(or_bars['high'].max()) - float(or_bars['low'].min())
            if or_range > or_filter:
                notes.append(f"  {day_str}: OR_FILTER skipped (OR={or_range:.0f} > {or_filter})")
                return trades, notes

    # ── VWAP flip filter (first 3 bars) ───────────────────────────────
    if vwap_flip:
        first3 = fut_day.head(3)
        if len(first3) >= 2:
            sides = []
            for _, row in first3.iterrows():
                if float(row['close']) > float(row['vwap']):
                    sides.append('above')
                else:
                    sides.append('below')
            if len(set(sides)) > 1:
                notes.append(f"  {day_str}: VWAP_FLIP skipped (sides={sides})")
                return trades, notes

    df15_spot = day_opt['df15_spot']
    opt        = day_opt['opt']

    daily_losses     = 0
    halted           = False
    last_exit_time: Optional[datetime] = None
    last_vwap_bar:  Optional[datetime] = None

    for i in range(1, len(fut_day)):
        if halted:
            break

        fbar     = fut_day.iloc[i]
        bar_time = fbar['date']

        if bar_time.strftime('%H:%M') > ENTRY_CUTOFF:
            break
        if skip_before and bar_time.strftime('%H:%M') < skip_before:
            continue
        if last_exit_time and bar_time <= last_exit_time:
            continue
        if last_vwap_bar == bar_time:
            continue

        fo, fh, fl, fc = (float(fbar['open']), float(fbar['high']),
                          float(fbar['low']),  float(fbar['close']))
        vwap    = float(fbar['vwap'])
        f_range = fh - fl
        if f_range <= 0:
            continue
        body_pct = abs(fc - fo) / f_range

        if body_pct <= body_min:
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
            continue
        spot_price = float(spot_at.iloc[-1]['close'])
        atm = atm_strike(spot_price)

        # Find option
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
                             f"no option {atm}{side} — skip")
                continue

        opt_df = opt[opt_key]
        strike = opt_key[0]

        ref_price = opt_price_at(opt_df, bar_time)
        if ref_price is None or ref_price <= 0:
            continue
        if not (PREM_MIN <= ref_price <= PREM_MAX):
            continue

        # Market entry
        fill_price = round(ref_price, 2)
        fill_time  = bar_time

        last_vwap_bar = bar_time

        exit_time, exit_prem, reason = simulate_exit(opt_df, fill_time, fill_price, cfg)

        pnl_pts = round(exit_prem - fill_price, 2)
        pnl_rs  = round(pnl_pts * LOT_SIZE * LOTS, 2)

        trades.append(dict(
            day       = day_str,
            sig_time  = bar_time.strftime('%H:%M'),
            exit_time = exit_time.strftime('%H:%M'),
            side      = side,
            strike    = strike,
            entry     = round(fill_price, 2),
            exit      = round(exit_prem, 2),
            pnl_pts   = pnl_pts,
            pnl_rs    = pnl_rs,
            reason    = reason,
        ))

        last_exit_time = exit_time
        if pnl_pts < 0:
            daily_losses += 1
            if daily_losses >= CIRCUIT_BREAKER:
                halted = True
                notes.append(f"  {day_str}: CIRCUIT BREAKER — halted after {daily_losses} losses")

    return trades, notes


# ══════════════════════════════════════════════════════════════════════════
# STRATEGY RUNNER
# ══════════════════════════════════════════════════════════════════════════

def run_strategy(cfg: dict, df_fut15: pd.DataFrame,
                 day_data: Dict[str, dict], all_days: List[str]) -> dict:
    """Run one strategy config across all days, return aggregated result."""
    all_trades: List[dict] = []
    all_notes:  List[str]  = []
    days_used:  List[str]  = []

    for day_str in all_days:
        if day_str not in day_data:
            continue
        day_date = datetime.strptime(day_str, '%Y-%m-%d').date()
        IST_09_15 = datetime(day_date.year, day_date.month, day_date.day, 9, 15)
        IST_15_30 = datetime(day_date.year, day_date.month, day_date.day, 15, 30)
        if df_fut15[(df_fut15['date'] >= IST_09_15) & (df_fut15['date'] <= IST_15_30)].empty:
            continue
        days_used.append(day_str)
        trades, notes = run_day(day_str, df_fut15, day_data[day_str], day_date, cfg)
        all_trades.extend(trades)
        all_notes.extend(notes)

    return dict(
        cfg    = cfg,
        trades = all_trades,
        notes  = all_notes,
        days   = days_used,
    )


# ══════════════════════════════════════════════════════════════════════════
# METRICS CALCULATOR
# ══════════════════════════════════════════════════════════════════════════

def calc_metrics(result: dict, total_days: int) -> dict:
    trades = result['trades']
    days   = result['days']

    n = len(trades)
    if n == 0:
        return dict(
            name=result['cfg']['name'], trades=0, wr=0.0,
            total_pts=0.0, total_rs=0.0, avg_win=0.0, avg_loss=0.0,
            green_days=0, total_days=total_days, worst_day_rs=0.0,
            day_pnl={},
        )

    wins  = [t for t in trades if t['pnl_pts'] > 0]
    losses= [t for t in trades if t['pnl_pts'] <= 0]
    total_pts = sum(t['pnl_pts'] for t in trades)
    total_rs  = sum(t['pnl_rs']  for t in trades)
    wr   = len(wins) / n * 100 if n else 0
    avgw = np.mean([t['pnl_pts'] for t in wins])  if wins   else 0.0
    avgl = np.mean([t['pnl_pts'] for t in losses]) if losses else 0.0

    # Day-level
    day_pnl: Dict[str, float] = {}
    for t in trades:
        day_pnl[t['day']] = day_pnl.get(t['day'], 0.0) + t['pnl_rs']

    green_days  = sum(1 for v in day_pnl.values() if v > 0)
    worst_day   = min(day_pnl.values()) if day_pnl else 0.0

    return dict(
        name=result['cfg']['name'],
        trades=n,
        wr=round(wr, 1),
        total_pts=round(total_pts, 1),
        total_rs=round(total_rs, 0),
        avg_win=round(avgw, 1),
        avg_loss=round(avgl, 1),
        green_days=green_days,
        total_days=total_days,
        worst_day_rs=round(worst_day, 0),
        day_pnl=day_pnl,
    )


# ══════════════════════════════════════════════════════════════════════════
# REPORTING
# ══════════════════════════════════════════════════════════════════════════

def print_comparison_table(metrics_list: List[dict]):
    sep = '=' * 110
    print(f"\n{sep}")
    print("  STRATEGY COMPARISON TABLE  (LOT_SIZE=65, LOTS=2, CB=3/day)")
    print(sep)
    hdr = (f"  {'STRATEGY':<14} {'TRADES':>6} {'WR%':>6} {'PnL_Pts':>9} "
           f"{'PnL_Rs':>11} {'AvgW':>7} {'AvgL':>7} "
           f"{'GreenDays':>10} {'WorstDay_Rs':>12}")
    print(hdr)
    print(f"  {'-'*105}")

    # Sort by total_rs descending
    for m in sorted(metrics_list, key=lambda x: -x['total_rs']):
        flag = '✅' if m['total_rs'] >= 0 else '❌'
        print(
            f"  {flag} {m['name']:<13} {m['trades']:>6} {m['wr']:>6.1f} "
            f"{m['total_pts']:>+9.1f} "
            f"₹{m['total_rs']:>+10,.0f} "
            f"{m['avg_win']:>+7.1f} {m['avg_loss']:>+7.1f} "
            f"{m['green_days']:>4}/{m['total_days']:<5} "
            f"₹{m['worst_day_rs']:>+11,.0f}"
        )
    print(sep)


def print_per_day(results_map: Dict[str, dict], metrics_list: List[dict],
                  all_days: List[str], top_n: int = 4):
    """Print per-day breakdown for the top_n strategies by PnL."""
    ranked = sorted(metrics_list, key=lambda x: -x['total_rs'])[:top_n]
    top_names = [m['name'] for m in ranked]

    print(f"\n{'='*90}")
    print(f"  PER-DAY BREAKDOWN — Top {top_n} strategies")
    print(f"{'='*90}")

    for name in top_names:
        result = results_map[name]
        m      = next(mx for mx in metrics_list if mx['name'] == name)
        trades = result['trades']

        # day pnl
        day_pnl_rs:  Dict[str, float] = {}
        day_pnl_pts: Dict[str, float] = {}
        day_trades:  Dict[str, int]   = {}
        for t in trades:
            d = t['day']
            day_pnl_rs[d]  = day_pnl_rs.get(d, 0.0)  + t['pnl_rs']
            day_pnl_pts[d] = day_pnl_pts.get(d, 0.0) + t['pnl_pts']
            day_trades[d]  = day_trades.get(d, 0)     + 1

        print(f"\n  ── {name}  "
              f"[{m['trades']} trades | WR={m['wr']}% | PnL=₹{m['total_rs']:+,.0f}]")
        print(f"  {'DATE':<12} {'#':>4} {'PTS':>9} {'Rs':>12}  TRADES")
        print(f"  {'-'*60}")

        for d in all_days:
            if d not in day_pnl_rs:
                print(f"       {d:<10}    —         —            —")
                continue
            flag = '✅' if day_pnl_rs[d] >= 0 else '❌'
            day_t = [t for t in trades if t['day'] == d]
            tsum  = '  '.join(f"{t['side']}@{t['entry']:.0f}→{t['exit']:.0f}"
                              f"({t['pnl_pts']:+.0f},{t['reason'][:6]})"
                              for t in day_t)
            print(f"  {flag} {d:<10} {day_trades[d]:>4} {day_pnl_pts[d]:>+9.1f} "
                  f"₹{day_pnl_rs[d]:>+10,.0f}  {tsum}")


def print_exit_reason_breakdown(results_map: Dict[str, dict], metrics_list: List[dict], top_n: int = 4):
    ranked = sorted(metrics_list, key=lambda x: -x['total_rs'])[:top_n]
    print(f"\n{'='*70}")
    print(f"  EXIT REASON BREAKDOWN — Top {top_n} strategies")
    print(f"{'='*70}")
    for m in ranked:
        name   = m['name']
        trades = results_map[name]['trades']
        reasons: Dict[str, dict] = {}
        for t in trades:
            r = t['reason']
            reasons.setdefault(r, {'n': 0, 'pts': 0.0})
            reasons[r]['n']   += 1
            reasons[r]['pts'] += t['pnl_pts']
        print(f"\n  {name}:")
        for r, v in sorted(reasons.items(), key=lambda x: -x[1]['pts']):
            print(f"    {r:<25} n={v['n']:>3}  pts={v['pts']:>+8.1f}")


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    # Capture output to file too
    buf = io.StringIO()
    _orig_print = builtins.print
    def _tee(*args, **kwargs):
        _orig_print(*args, **kwargs)
        kw2 = {k: v for k, v in kwargs.items() if k not in ('file',)}
        _orig_print(*args, file=buf, **kw2)
    builtins.print = _tee

    print("=" * 72)
    print("  ORION BACKTEST SWEEP  — 12 strategies × all available days")
    print("=" * 72)

    # Load futures once
    df_fut15 = load_fut15m()

    # Discover days
    all_days = discover_days()
    if not all_days:
        print(f"[ERROR] No option data found in {OPT_BASES}")
        sys.exit(1)
    print(f"[DATA] {len(all_days)} option days: {all_days[0]} → {all_days[-1]}")

    # Load all day option data once
    day_data: Dict[str, dict] = {}
    for day_str in all_days:
        day_date = datetime.strptime(day_str, '%Y-%m-%d').date()
        IST_09_15 = datetime(day_date.year, day_date.month, day_date.day, 9, 15)
        IST_15_30 = datetime(day_date.year, day_date.month, day_date.day, 15, 30)
        if df_fut15[(df_fut15['date'] >= IST_09_15) & (df_fut15['date'] <= IST_15_30)].empty:
            print(f"  {day_str}: No futures data — skip")
            continue
        dd = load_day_options(day_str)
        if dd is None:
            print(f"  {day_str}: No option data — skip")
            continue
        day_data[day_str] = dd
        print(f"  {day_str}: loaded  "
              f"({len(dd['opt'])} option series)")

    valid_days = sorted(day_data.keys())
    print(f"\n[SWEEP] {len(valid_days)} valid days.  "
          f"Running {len(STRATEGIES)} strategies ...\n")

    # Run all strategies
    results_map: Dict[str, dict] = {}
    metrics_list: List[dict]     = []

    for cfg in STRATEGIES:
        print(f"  Running {cfg['name']} ...")
        res = run_strategy(cfg, df_fut15, day_data, valid_days)
        results_map[cfg['name']] = res
        m = calc_metrics(res, len(valid_days))
        metrics_list.append(m)
        print(f"    → {m['trades']} trades  WR={m['wr']}%  "
              f"PnL=₹{m['total_rs']:+,.0f}")

    # ── Print comparison table
    print_comparison_table(metrics_list)

    # ── Per-day breakdown for top 4
    print_per_day(results_map, metrics_list, valid_days, top_n=4)

    # ── Exit reason breakdown for top 4
    print_exit_reason_breakdown(results_map, metrics_list, top_n=4)

    # ── Restore print and save to file
    builtins.print = _orig_print

    out_path = os.path.join(REPO_DIR, 'sweep_result.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(buf.getvalue())
    _orig_print(f"\n[SAVED] {out_path}")

    # ── Git commit + push
    branch = 'claude/general-session-YfHuZ'
    try:
        subprocess.run(['git', 'add',
                        os.path.join(REPO_DIR, 'ORION_BACKTEST_SWEEP.py'),
                        out_path],
                       cwd=REPO_DIR, check=True)
        r = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=REPO_DIR)
        if r.returncode != 0:
            subprocess.run(
                ['git', 'commit', '-m',
                 f'feat: add ORION_BACKTEST_SWEEP.py — 12-strategy sweep '
                 f'({len(valid_days)} days)'],
                cwd=REPO_DIR, check=True)
            try:
                import credentials as _c
                pat = getattr(_c, 'GITHUB_PAT', None)
                remote = (f"https://{pat}@github.com/amolselukar/Amol.git"
                          if pat else "origin")
            except Exception:
                remote = "origin"
            subprocess.run(['git', 'push', '-u', remote, branch],
                           cwd=REPO_DIR, check=True)
            _orig_print("[GITHUB] Pushed results.")
        else:
            _orig_print("[GITHUB] No changes to push.")
    except subprocess.CalledProcessError as e:
        _orig_print(f"[GITHUB] Git step failed: {e}")


if __name__ == '__main__':
    main()
