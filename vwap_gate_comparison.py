"""
ORION VWAP Gate Comparison Backtest
Config A: Gate 1 only  — Futures 15m close crosses daily VWAP, body >= 65%
Config B: Gates 1+2+3  — Gate 1 PLUS spot 15m agrees PLUS ATM option LTP agrees
"""
import os, sys, glob
import pandas as pd
import numpy as np
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple

REPO_DIR      = "/home/user/Amol"
FUT15M_CSV    = os.path.join(REPO_DIR, "market_data", "nifty_fut_15m.csv")
OPT_BASE      = os.path.join(REPO_DIR, "option_data", "selukar")

# ── Strategy constants (from ORION_BACKTEST_OFFLINE.py) ─────────────────
LOT_SIZE      = 65
LOTS          = 2
QTY           = LOT_SIZE * LOTS          # 130
HARDSL_PCT    = 0.18
RI            = 12                       # Velvet Rope trigger
VR_SL         = 8
T2_PEAK       = 24
T2_SL         = 12
T3_PEAK       = 36
T3_SL         = 24
RUNNER_STEP   = 25
SMA_TRAIL_BARS= 8
FORCE_CLOSE   = "15:25"
ENTRY_CUTOFF  = "14:45"
PREM_MIN      = 30
PREM_MAX      = 300
BODY_MIN_PCT  = 0.65                     # *** 65% as requested
LIMIT_OFFSET  = 0
CIRCUIT_BREAKER = 3

# ──────────────────────────────────────────────────────────────────────────
def compute_vwap(df: pd.DataFrame) -> pd.Series:
    tp  = (df['high'] + df['low'] + df['close']) / 3
    vol = df['volume'].fillna(1).replace(0, 1)
    return (tp * vol).cumsum() / vol.cumsum()

def atm_strike(spot: float) -> int:
    return int(round(spot / 50) * 50)

def opt_price_at(opt_df: pd.DataFrame, at_time: datetime) -> Optional[float]:
    mask = opt_df['date'] <= at_time
    if not mask.any():
        return None
    return float(opt_df.loc[mask, 'close'].iloc[-1])

def simulate_exit(opt_df: pd.DataFrame, entry_time: datetime,
                  entry_prem: float) -> Tuple[datetime, float, str]:
    hardsl   = entry_prem * (1 - HARDSL_PCT)
    tr_armed = False
    tr_sl    = 0.0
    peak     = entry_prem
    sma_lows: List[float] = []

    # start from first bar AFTER entry_time (per spec: date > signal_time)
    bars = opt_df[opt_df['date'] > entry_time].reset_index(drop=True)
    if bars.empty:
        # fallback: include entry bar
        bars = opt_df[opt_df['date'] >= entry_time].reset_index(drop=True)
    if bars.empty:
        return entry_time, entry_prem, 'NO_DATA'

    for _, bar in bars.iterrows():
        dt = bar['date']
        o, h, l, c = float(bar['open']), float(bar['high']), float(bar['low']), float(bar['close'])
        peak = max(peak, h)
        sma_lows.append(l)

        if dt.strftime('%H:%M') >= FORCE_CLOSE:
            return dt, c, 'FORCE_CLOSE'

        if l <= hardsl:
            return dt, round(hardsl, 2), 'HARDSL_-18pct'

        if not tr_armed and h >= entry_prem + RI:
            tr_armed = True
            tr_sl    = entry_prem + VR_SL
            if l <= tr_sl:
                return dt, round(tr_sl, 2), 'VELVET_ROPE'

        if tr_armed:
            if peak >= entry_prem + T3_PEAK and tr_sl < entry_prem + T3_SL:
                tr_sl = entry_prem + T3_SL
            elif peak >= entry_prem + T2_PEAK and tr_sl < entry_prem + T2_SL:
                tr_sl = entry_prem + T2_SL
            while peak >= tr_sl + RUNNER_STEP:
                tr_sl += RUNNER_STEP
            if l <= tr_sl:
                pts = round(tr_sl - entry_prem, 1)
                return dt, round(tr_sl, 2), f'RATCHET_+{int(pts)}'

        if len(sma_lows) >= SMA_TRAIL_BARS and len(sma_lows) % 3 == 0:
            sma8l = float(np.mean(sma_lows[-SMA_TRAIL_BARS:]))
            if c < sma8l:
                return dt, c, 'SMA8_TRAIL'

    last = bars.iloc[-1]
    return last['date'], float(last['close']), 'EOD'

# ──────────────────────────────────────────────────────────────────────────
def load_fut15m() -> pd.DataFrame:
    df = pd.read_csv(FUT15M_CSV, parse_dates=['date'])
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    df = df.sort_values('date').drop_duplicates('date').reset_index(drop=True)
    print(f"[FUT] {len(df)} bars  {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}")
    return df

def discover_days() -> List[str]:
    days = set()
    if os.path.isdir(OPT_BASE):
        for d in os.listdir(OPT_BASE):
            if d.startswith('20') and os.path.isdir(os.path.join(OPT_BASE, d)):
                days.add(d)
    return sorted(days)

def load_day(day_str: str) -> Optional[dict]:
    ddir = os.path.join(OPT_BASE, day_str)
    if not os.path.isdir(ddir):
        return None
    try:
        p15 = os.path.join(ddir, 'nifty_15m.csv')
        if not os.path.exists(p15):
            return None
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
            return None
        return dict(df15_spot=df15, opt=opt, day=day_str)
    except Exception as e:
        print(f"  [LOAD] {day_str}: {e}")
        return None

# ──────────────────────────────────────────────────────────────────────────
def run_day_both_configs(day_str: str, df_fut15: pd.DataFrame, day_data: dict,
                         day_date: date):
    """
    Returns (trades_A, trades_B, gate_filter_log)
    gate_filter_log = list of dicts per Gate-1 signal showing gate2/gate3 pass/fail
    """
    trades_A = []
    trades_B = []
    gate_log = []   # per-signal gate decisions

    IST_09_15 = datetime(day_date.year, day_date.month, day_date.day, 9, 15)
    IST_15_30 = datetime(day_date.year, day_date.month, day_date.day, 15, 30)

    fut_day = df_fut15[
        (df_fut15['date'] >= IST_09_15) &
        (df_fut15['date'] <= IST_15_30)
    ].reset_index(drop=True)

    if fut_day.empty:
        return trades_A, trades_B, gate_log

    fut_day = fut_day.copy()
    fut_day['vwap'] = compute_vwap(fut_day)

    df15_spot = day_data['df15_spot']
    opt       = day_data['opt']

    # Compute spot 15m VWAP for Gate 2
    # Filter spot bars for THIS day only (9:15 onwards)
    spot_day = df15_spot[df15_spot['date'] >= IST_09_15].copy().reset_index(drop=True)
    if not spot_day.empty:
        spot_day['vwap'] = compute_vwap(spot_day)
    else:
        spot_day = pd.DataFrame()

    # Track state separately for Config A and Config B (circuit breaker etc.)
    state_A = dict(daily_losses=0, halted=False, last_exit_time=None, last_vwap_bar=None)
    state_B = dict(daily_losses=0, halted=False, last_exit_time=None, last_vwap_bar=None)

    for i in range(1, len(fut_day)):
        fbar     = fut_day.iloc[i]
        bar_time = fbar['date']

        if bar_time.strftime('%H:%M') > ENTRY_CUTOFF:
            break

        fo, fh, fl, fc = float(fbar['open']), float(fbar['high']), float(fbar['low']), float(fbar['close'])
        vwap    = float(fbar['vwap'])
        f_range = fh - fl
        if f_range <= 0:
            continue
        body_pct = abs(fc - fo) / f_range

        if body_pct < BODY_MIN_PCT:
            continue

        if fc > vwap:
            signal_dir = 'CE'
        elif fc < vwap:
            signal_dir = 'PE'
        else:
            continue

        # ATM from spot
        spot_at = df15_spot[df15_spot['date'] <= bar_time]
        if spot_at.empty:
            continue
        spot_price = float(spot_at.iloc[-1]['close'])
        atm = atm_strike(spot_price)

        # Find option
        opt_key = (atm, signal_dir)
        if opt_key not in opt:
            found = False
            for adj in (50, -50, 100, -100):
                if (atm + adj, signal_dir) in opt:
                    opt_key = (atm + adj, signal_dir)
                    found = True
                    break
            if not found:
                continue

        opt_df = opt[opt_key]
        strike = opt_key[0]

        ref_price = opt_price_at(opt_df, bar_time)
        if ref_price is None or ref_price <= 0:
            continue
        if not (PREM_MIN <= ref_price <= PREM_MAX):
            continue

        # ── Gate 2: spot 15m VWAP agrees ─────────────────────────────────
        gate2_pass = False
        gate2_detail = "no_spot_vwap_data"
        if not spot_day.empty:
            spot_bars_at = spot_day[spot_day['date'] <= bar_time]
            if not spot_bars_at.empty:
                spot_row = spot_bars_at.iloc[-1]
                spot_close_now = float(spot_row['close'])
                spot_vwap_now  = float(spot_row['vwap'])
                if signal_dir == 'CE' and spot_close_now > spot_vwap_now:
                    gate2_pass = True
                    gate2_detail = f"spot_close={spot_close_now:.1f} > spot_vwap={spot_vwap_now:.1f} [PASS]"
                elif signal_dir == 'PE' and spot_close_now < spot_vwap_now:
                    gate2_pass = True
                    gate2_detail = f"spot_close={spot_close_now:.1f} < spot_vwap={spot_vwap_now:.1f} [PASS]"
                else:
                    gate2_detail = f"spot_close={spot_close_now:.1f} vs spot_vwap={spot_vwap_now:.1f} [{signal_dir} DIR MISMATCH]"

        # ── Gate 3: ATM option price vs option daily VWAP ─────────────────
        gate3_pass = False
        gate3_detail = "no_opt_vwap_data"

        # Build option VWAP for THIS day (9:15 AM bars only)
        opt_day_bars = opt_df[opt_df['date'] >= IST_09_15].copy().reset_index(drop=True)
        if not opt_day_bars.empty:
            opt_day_bars['vwap'] = compute_vwap(opt_day_bars)
            opt_at_sig = opt_day_bars[opt_day_bars['date'] <= bar_time]
            if not opt_at_sig.empty:
                opt_row       = opt_at_sig.iloc[-1]
                opt_ltp_now   = float(opt_row['close'])
                opt_vwap_now  = float(opt_row['vwap'])
                if opt_ltp_now > opt_vwap_now:
                    gate3_pass   = True
                    gate3_detail = f"opt_ltp={opt_ltp_now:.1f} > opt_vwap={opt_vwap_now:.1f} [PASS]"
                elif opt_ltp_now < opt_vwap_now:
                    gate3_detail = f"opt_ltp={opt_ltp_now:.1f} < opt_vwap={opt_vwap_now:.1f} [FAIL — bearish opt for {signal_dir}]"
                    # For PE: option going down means option vwap > ltp; for CE: need ltp > vwap
                    # Actually for both CE and PE: if we're buying, we want option gaining → ltp above its own VWAP
                else:
                    gate3_detail = f"opt_ltp={opt_ltp_now:.1f} == opt_vwap={opt_vwap_now:.1f} [NEUTRAL — FAIL]"

        gate_log.append(dict(
            day      = day_str,
            sig_time = bar_time.strftime('%H:%M'),
            dir      = signal_dir,
            strike   = strike,
            body_pct = round(body_pct, 2),
            fut_close= round(fc, 1),
            fut_vwap = round(vwap, 1),
            gate1    = True,
            gate2    = gate2_pass,
            gate3    = gate3_pass,
            g2_detail= gate2_detail,
            g3_detail= gate3_detail,
            abc_pass = gate2_pass and gate3_pass,
        ))

        # ── Execute trade for Config A (Gate 1 only) ─────────────────────
        if not state_A['halted'] and (
            state_A['last_exit_time'] is None or bar_time > state_A['last_exit_time']
        ) and state_A['last_vwap_bar'] != bar_time:
            fill_price = ref_price  # market entry (LIMIT_OFFSET=0)
            fill_time  = bar_time

            # Exit uses date > signal_time
            exit_opt_df = opt_df[opt_df['date'] > bar_time].reset_index(drop=True)
            if exit_opt_df.empty:
                exit_opt_df = opt_df[opt_df['date'] >= bar_time].reset_index(drop=True)

            exit_time, exit_prem, reason = simulate_exit(opt_df, fill_time, fill_price)
            pnl_pts = round(exit_prem - fill_price, 2)
            pnl_rs  = round(pnl_pts * QTY, 2)

            trades_A.append(dict(
                day=day_str, sig_time=bar_time.strftime('%H:%M'),
                exit_time=exit_time.strftime('%H:%M'), side=signal_dir,
                strike=strike, entry=round(fill_price, 2), exit=round(exit_prem, 2),
                pnl_pts=pnl_pts, pnl_rs=pnl_rs, reason=reason,
            ))
            state_A['last_vwap_bar']  = bar_time
            state_A['last_exit_time'] = exit_time
            if pnl_pts < 0:
                state_A['daily_losses'] += 1
                if state_A['daily_losses'] >= CIRCUIT_BREAKER:
                    state_A['halted'] = True

        # ── Execute trade for Config B (Gates 1+2+3) ─────────────────────
        gates_123_pass = gate2_pass and gate3_pass
        if gates_123_pass and not state_B['halted'] and (
            state_B['last_exit_time'] is None or bar_time > state_B['last_exit_time']
        ) and state_B['last_vwap_bar'] != bar_time:
            fill_price = ref_price
            fill_time  = bar_time

            exit_time, exit_prem, reason = simulate_exit(opt_df, fill_time, fill_price)
            pnl_pts = round(exit_prem - fill_price, 2)
            pnl_rs  = round(pnl_pts * QTY, 2)

            trades_B.append(dict(
                day=day_str, sig_time=bar_time.strftime('%H:%M'),
                exit_time=exit_time.strftime('%H:%M'), side=signal_dir,
                strike=strike, entry=round(fill_price, 2), exit=round(exit_prem, 2),
                pnl_pts=pnl_pts, pnl_rs=pnl_rs, reason=reason,
            ))
            state_B['last_vwap_bar']  = bar_time
            state_B['last_exit_time'] = exit_time
            if pnl_pts < 0:
                state_B['daily_losses'] += 1
                if state_B['daily_losses'] >= CIRCUIT_BREAKER:
                    state_B['halted'] = True

    return trades_A, trades_B, gate_log

# ──────────────────────────────────────────────────────────────────────────
def summarise(label: str, trades: List[dict], days_loaded: List[str]):
    n = len(trades)
    if n == 0:
        print(f"\n  {label}: NO TRADES")
        return
    wins = [t for t in trades if t['pnl_pts'] > 0]
    loss = [t for t in trades if t['pnl_pts'] <= 0]
    wr   = len(wins) / n * 100
    total_pts = sum(t['pnl_pts'] for t in trades)
    total_rs  = sum(t['pnl_rs']  for t in trades)

    # Green days
    day_pnl: Dict[str, float] = {}
    for t in trades:
        day_pnl[t['day']] = day_pnl.get(t['day'], 0) + t['pnl_pts']
    green_days = sum(1 for v in day_pnl.values() if v > 0)

    print(f"\n  {'─'*60}")
    print(f"  {label}")
    print(f"  {'─'*60}")
    print(f"  Trades     : {n}  (W:{len(wins)}  L:{len(loss)})")
    print(f"  Win Rate   : {wr:.1f}%")
    print(f"  Total PnL  : {total_pts:+.1f} pts  |  ₹{total_rs:+,.0f}")
    print(f"  Green Days : {green_days} / {len(days_loaded)}")
    if wins:
        print(f"  Avg Win    : {np.mean([t['pnl_pts'] for t in wins]):+.1f} pts")
    if loss:
        print(f"  Avg Loss   : {np.mean([t['pnl_pts'] for t in loss]):+.1f} pts")

    # By day
    print(f"\n  BY DAY:")
    print(f"  {'DATE':<12} {'#':>3}  {'PNL_PTS':>9}  {'PNL_Rs':>11}  {'WR%':>6}")
    print(f"  {'─'*55}")
    day_groups: Dict[str, List] = {}
    for t in trades:
        day_groups.setdefault(t['day'], []).append(t)
    for d in sorted(day_pnl):
        dtrades  = day_groups.get(d, [])
        dpnl_pts = sum(t['pnl_pts'] for t in dtrades)
        dpnl_rs  = sum(t['pnl_rs']  for t in dtrades)
        dwr      = sum(1 for t in dtrades if t['pnl_pts'] > 0) / len(dtrades) * 100 if dtrades else 0
        flag = 'GREEN' if dpnl_pts > 0 else 'RED  '
        print(f"  [{flag}] {d}  {len(dtrades):>2}  {dpnl_pts:>+9.1f}  Rs{dpnl_rs:>+10,.0f}  {dwr:>5.1f}%")

    # Trade detail
    print(f"\n  TRADE DETAIL:")
    print(f"  {'DATE':<12} {'SIG':>5} {'EXIT':>5}  {'S':>3}  {'STK':>6}  "
          f"{'ENTRY':>7}  {'EXIT_P':>7}  {'PTS':>7}  {'Rs':>9}  REASON")
    print(f"  {'─'*95}")
    for t in trades:
        flag = '+' if t['pnl_pts'] > 0 else '-'
        print(f"  [{flag}] {t['day']:<10} {t['sig_time']:>5} {t['exit_time']:>5}  "
              f"{t['side']:>3}  {t['strike']:>6}  "
              f"{t['entry']:>7.2f}  {t['exit']:>7.2f}  "
              f"{t['pnl_pts']:>+7.2f}  Rs{t['pnl_rs']:>+8,.0f}  {t['reason']}")

# ──────────────────────────────────────────────────────────────────────────
def main():
    sep = '=' * 72
    print(f"\n{sep}")
    print("  ORION VWAP GATE COMPARISON BACKTEST")
    print("  Config A: Gate 1 only  (Fut 15m VWAP cross, body>=65%)")
    print("  Config B: Gates 1+2+3  (+ Spot 15m VWAP + ATM Opt VWAP)")
    print(f"  Exit: trail-after-TP | RI={RI} VR_SL={VR_SL} T2:{T2_PEAK}→{T2_SL} T3:{T3_PEAK}→{T3_SL}")
    print(f"  Qty: {LOTS}lots x {LOT_SIZE} = {QTY}  |  HARDSL={int(HARDSL_PCT*100)}%")
    print(sep)

    df_fut = load_fut15m()
    days   = discover_days()
    print(f"[DAYS] Found {len(days)} days: {days[0]} → {days[-1]}")

    all_A, all_B, all_gate_log = [], [], []
    days_loaded = []

    for day_str in days:
        day_date = datetime.strptime(day_str, '%Y-%m-%d').date()
        day_data = load_day(day_str)
        if day_data is None:
            print(f"  [SKIP] {day_str}: no data")
            continue
        days_loaded.append(day_str)

        trades_A, trades_B, gate_log = run_day_both_configs(
            day_str, df_fut, day_data, day_date)
        all_A.extend(trades_A)
        all_B.extend(trades_B)
        all_gate_log.extend(gate_log)

    print(f"\n  Days loaded: {len(days_loaded)}")

    # ── Results ─────────────────────────────────────────────────────────
    print(f"\n{sep}")
    print("  RESULTS SUMMARY")
    print(sep)
    summarise("CONFIG A — Gate 1 Only", all_A, days_loaded)
    summarise("CONFIG B — Gates 1+2+3", all_B, days_loaded)

    # ── Gate filter analysis ─────────────────────────────────────────────
    print(f"\n{sep}")
    print("  GATE FILTER ANALYSIS (Gate 1 signals → Gate 2 → Gate 3)")
    print(sep)

    total_g1 = len(all_gate_log)
    g2_pass  = sum(1 for g in all_gate_log if g['gate2'])
    g3_pass  = sum(1 for g in all_gate_log if g['gate3'])
    g23_pass = sum(1 for g in all_gate_log if g['gate2'] and g['gate3'])

    print(f"\n  Gate 1 signals total : {total_g1}")
    print(f"  Gate 2 PASS          : {g2_pass} / {total_g1}  ({100*g2_pass/total_g1:.1f}% pass rate)")
    print(f"  Gate 3 PASS          : {g3_pass} / {total_g1}  ({100*g3_pass/total_g1:.1f}% pass rate)")
    print(f"  Gates 2+3 both PASS  : {g23_pass} / {total_g1}  ({100*g23_pass/total_g1:.1f}% pass rate)")
    print(f"  Filtered OUT by G2+G3: {total_g1 - g23_pass} signals")

    # ── Per-day gate breakdown ────────────────────────────────────────────
    print(f"\n  PER-DAY GATE BREAKDOWN:")
    print(f"  {'DATE':<12} {'TIME':>5} {'DIR':>3} {'STK':>6}  {'BODY':>5}  "
          f"{'G1':>3} {'G2':>4} {'G3':>4}  {'RESULT':>7}  GATE DETAILS")
    print(f"  {'─'*105}")

    for g in sorted(all_gate_log, key=lambda x: (x['day'], x['sig_time'])):
        g2s = 'PASS' if g['gate2'] else 'FAIL'
        g3s = 'PASS' if g['gate3'] else 'FAIL'
        res = 'TRADE' if g['abc_pass'] else 'SKIP'
        flag = '+' if g['abc_pass'] else 'x'
        print(f"  [{flag}] {g['day']:<10} {g['sig_time']:>5}  {g['dir']:>2}  {g['strike']:>6}  "
              f"{g['body_pct']:>5.2f}  G1:Y G2:{g2s} G3:{g3s}  {res:>6}")
        print(f"        G2: {g['g2_detail']}")
        print(f"        G3: {g['g3_detail']}")

    # ── Head-to-head delta ───────────────────────────────────────────────
    print(f"\n{sep}")
    print("  HEAD-TO-HEAD COMPARISON")
    print(sep)
    pnl_A = sum(t['pnl_pts'] for t in all_A)
    pnl_B = sum(t['pnl_pts'] for t in all_B)
    wr_A  = (sum(1 for t in all_A if t['pnl_pts'] > 0) / len(all_A) * 100) if all_A else 0
    wr_B  = (sum(1 for t in all_B if t['pnl_pts'] > 0) / len(all_B) * 100) if all_B else 0

    day_pnl_A: Dict[str, float] = {}
    for t in all_A:
        day_pnl_A[t['day']] = day_pnl_A.get(t['day'], 0) + t['pnl_pts']
    day_pnl_B: Dict[str, float] = {}
    for t in all_B:
        day_pnl_B[t['day']] = day_pnl_B.get(t['day'], 0) + t['pnl_pts']

    gd_A = sum(1 for v in day_pnl_A.values() if v > 0)
    gd_B = sum(1 for v in day_pnl_B.values() if v > 0)

    print(f"\n  {'Metric':<25} {'Config A':>12}  {'Config B':>12}")
    print(f"  {'─'*52}")
    print(f"  {'Trades':<25} {len(all_A):>12}  {len(all_B):>12}")
    print(f"  {'Win Rate':<25} {wr_A:>11.1f}%  {wr_B:>11.1f}%")
    print(f"  {'Total PnL (pts)':<25} {pnl_A:>+12.1f}  {pnl_B:>+12.1f}")
    rs_A = sum(t['pnl_rs'] for t in all_A)
    rs_B = sum(t['pnl_rs'] for t in all_B)
    print(f"  {'Total PnL (Rs)':<25} Rs{rs_A:>+10,.0f}  Rs{rs_B:>+10,.0f}")
    print(f"  {'Green Days':<25} {gd_A:>9}/{len(days_loaded)}  {gd_B:>9}/{len(days_loaded)}")
    avg_A = rs_A / len(days_loaded) if days_loaded else 0
    avg_B = rs_B / len(days_loaded) if days_loaded else 0
    print(f"  {'Avg Day PnL (Rs)':<25} Rs{avg_A:>+10,.0f}  Rs{avg_B:>+10,.0f}")
    print(f"\n  Gate 1 signals      : {total_g1}")
    print(f"  Filtered by G2+G3   : {total_g1 - g23_pass}  ({100*(total_g1-g23_pass)/total_g1:.1f}% filtered out)")
    print(f"  PnL delta B-A       : {pnl_B - pnl_A:+.1f} pts  |  Rs{rs_B - rs_A:+,.0f}")
    print(f"\n{sep}\n")

if __name__ == '__main__':
    main()
