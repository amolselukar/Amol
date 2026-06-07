"""
==========================================================================
ORION_BACKTEST_OFFLINE.py
==========================================================================
Offline version — no Kite API needed. Reads pre-fetched data:
  Nifty Futures 15m  → market_data/nifty_fut_15m.csv
  Option 5m data     → option_data/selukar/<day>/CE|PE/<strike>.csv
                       option_data/amol/<day>/CE|PE/<strike>.csv
  Spot 15m           → option_data/selukar/<day>/nifty_15m.csv

Entry logic:
  - Nifty Futures 15m bar body > 50% of range
  - Bar closes ABOVE daily VWAP → CE signal
  - Bar closes BELOW daily VWAP → PE signal
  - LIMIT_OFFSET=0  → MARKET ENTRY at ref_price (no pullback exists per data analysis)

Exit logic : V2.5.12
  HARDSL -18% | Velvet Rope (peak+RI → SL entry+VR_SL)
  Ladder T2 (peak+24→SL+12) | Ladder T3 (peak+36→SL+24)
  Runner +25/+25 | SMA8(low) trail | Force close 15:25
==========================================================================
"""
import os, sys, glob
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Tuple

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_DIR)

# Local data paths (populated by FETCH_MARKET_DATA.py + option data upload)
FUT15M_CSV  = os.path.join(REPO_DIR, 'market_data', 'nifty_fut_15m.csv')
OPT_BASES   = [
    os.path.join(REPO_DIR, 'option_data', 'selukar'),
    os.path.join(REPO_DIR, 'option_data', 'amol'),
]

# ── Strategy constants ─────────────────────────────────────────────────
LOT_SIZE        = 65
LOTS            = 2
HARDSL_PCT      = 0.18
RI              = 12            # Velvet Rope trigger
VR_SL           = 8             # SL after VR: entry + VR_SL (tuned: was 2, sweep shows 8 optimal)
T2_PEAK         = 24
T2_SL           = 12
T3_PEAK         = 36
T3_SL           = 24
RUNNER_STEP     = 25
SMA_TRAIL_BARS  = 8
FORCE_CLOSE     = "15:25"
ENTRY_CUTOFF    = "14:45"
PREM_MIN        = 30
PREM_MAX        = 300
BODY_MIN_PCT    = 0.50
LIMIT_OFFSET    = 0             # 0 = market entry (data shows B1 pullback ≈ 0)
LIMIT_WINDOW_BARS = 1           # bars to wait if using limit; not used when OFFSET=0
CIRCUIT_BREAKER = 3

# ── Load Nifty Futures 15m (pre-fetched) ──────────────────────────────
def load_fut15m() -> pd.DataFrame:
    if not os.path.exists(FUT15M_CSV):
        print(f"[ERROR] Futures data not found: {FUT15M_CSV}")
        print("  Run FETCH_MARKET_DATA.py on PythonAnywhere first.")
        sys.exit(1)
    df = pd.read_csv(FUT15M_CSV, parse_dates=['date'])
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    df = df.sort_values('date').drop_duplicates('date').reset_index(drop=True)
    print(f"[FUT] Loaded {len(df)} bars from {df['date'].iloc[0].date()} to {df['date'].iloc[-1].date()}")
    return df

# ── Compute rolling session VWAP ──────────────────────────────────────
def compute_fut_vwap(df_day: pd.DataFrame) -> pd.Series:
    tp  = (df_day['high'] + df_day['low'] + df_day['close']) / 3
    vol = df_day['volume'].fillna(1).replace(0, 1)
    cum_tpv = (tp * vol).cumsum()
    cum_vol = vol.cumsum()
    return (cum_tpv / cum_vol).reset_index(drop=True)

# ── Discover all available days ────────────────────────────────────────
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

# ── Load one day's option data ─────────────────────────────────────────
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
                        dfopt = pd.read_csv(fp, parse_dates=['date'])
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

# ── ATM strike ─────────────────────────────────────────────────────────
def atm_strike(spot: float) -> int:
    return int(round(spot / 50) * 50)

# ── Option price at or before a given time ─────────────────────────────
def opt_price_at(opt_df: pd.DataFrame, at_time: datetime) -> Optional[float]:
    mask = opt_df['date'] <= at_time
    if not mask.any():
        return None
    return float(opt_df.loc[mask, 'close'].iloc[-1])

# ── Entry fill logic ───────────────────────────────────────────────────
def get_fill(opt_df: pd.DataFrame, signal_time: datetime,
             ref_price: float) -> Tuple[Optional[float], Optional[datetime]]:
    """
    With LIMIT_OFFSET=0: buy at market (ref_price) immediately at signal_time.
    With LIMIT_OFFSET>0: look for low <= ref_price-LIMIT_OFFSET in next bars.
    """
    if LIMIT_OFFSET == 0:
        # Market entry — fill at ref_price at signal_time
        return round(ref_price, 2), signal_time

    limit = ref_price - LIMIT_OFFSET
    future = opt_df[opt_df['date'] > signal_time].reset_index(drop=True)
    for i in range(min(LIMIT_WINDOW_BARS, len(future))):
        bar = future.iloc[i]
        if float(bar['low']) <= limit:
            return round(limit, 2), bar['date']
    return None, None

# ── V2.5.12 exit simulation ────────────────────────────────────────────
def simulate_exit(opt_df: pd.DataFrame, entry_time: datetime,
                  entry_prem: float) -> Tuple[datetime, float, str]:
    hardsl   = entry_prem * (1 - HARDSL_PCT)
    tr_armed = False
    tr_sl    = 0.0
    peak     = entry_prem
    sma_lows: List[float] = []

    # Start from first bar AFTER entry_time (or at entry_time if market entry)
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

# ── Run backtest for one day ───────────────────────────────────────────
def run_day(day_str: str, df_fut15: pd.DataFrame, day_opt: dict,
            day_date: date) -> Tuple[List[dict], List[str]]:
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
        if last_exit_time and bar_time <= last_exit_time:
            continue
        if last_vwap_bar == bar_time:
            continue

        fo, fh, fl, fc = float(fbar['open']), float(fbar['high']), float(fbar['low']), float(fbar['close'])
        vwap    = float(fbar['vwap'])
        f_range = fh - fl
        if f_range <= 0:
            continue
        body_pct = abs(fc - fo) / f_range

        if body_pct <= BODY_MIN_PCT:
            continue

        if fc > vwap:
            side = 'CE'
        elif fc < vwap:
            side = 'PE'
        else:
            continue

        # ATM from spot at signal time
        spot_at = df15_spot[df15_spot['date'] <= bar_time]
        if spot_at.empty:
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: no spot bar yet — skip")
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
                             f"no option for ATM {atm} {side} — skip")
                continue

        opt_df = opt[opt_key]
        strike = opt_key[0]

        ref_price = opt_price_at(opt_df, bar_time)
        if ref_price is None or ref_price <= 0:
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                         f"{strike}{side} no price at signal — skip")
            continue

        if not (PREM_MIN <= ref_price <= PREM_MAX):
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                         f"{side} {strike} ref={ref_price:.1f} outside [{PREM_MIN},{PREM_MAX}] — skip")
            continue

        fill_price, fill_time = get_fill(opt_df, bar_time, ref_price)

        if fill_price is None:
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                         f"{side} {strike} limit not filled — ORDER EXPIRED")
            continue

        last_vwap_bar = bar_time

        exit_time, exit_prem, reason = simulate_exit(opt_df, fill_time, fill_price)

        pnl_pts = round(exit_prem - fill_price, 2)
        pnl_rs  = round(pnl_pts * LOT_SIZE * LOTS, 2)

        trades.append(dict(
            day       = day_str,
            sig_time  = bar_time.strftime('%H:%M'),
            fill_time = fill_time.strftime('%H:%M') if fill_time else '-',
            exit_time = exit_time.strftime('%H:%M'),
            side      = side,
            strike    = strike,
            ref_price = round(ref_price, 2),
            entry     = round(fill_price, 2),
            exit      = round(exit_prem, 2),
            pnl_pts   = pnl_pts,
            pnl_rs    = pnl_rs,
            reason    = reason,
            body_pct  = round(body_pct, 2),
        ))

        last_exit_time = exit_time
        if pnl_pts < 0:
            daily_losses += 1
            if daily_losses >= CIRCUIT_BREAKER:
                halted = True
                notes.append(f"  {day_str}: CIRCUIT BREAKER — {daily_losses} losses, halted")

    return trades, notes

# ── Summary printer ────────────────────────────────────────────────────
def print_summary(all_trades, all_notes, days_found, days_loaded):
    sep = '=' * 72

    entry_mode = f"MARKET (ref_price, no offset)" if LIMIT_OFFSET == 0 else f"LIMIT -₹{LIMIT_OFFSET}"

    print(f"\n{sep}")
    print(f"  ORION OFFLINE BACKTEST — ENTRY: Fut VWAP 15m + {entry_mode}")
    print(f"  Exit: V2.5.12 | RI={RI} | Lots: {LOTS}×{LOT_SIZE}={LOTS*LOT_SIZE} qty")
    print(f"  Days found : {len(days_found)}  ({days_found[0] if days_found else '-'} → {days_found[-1] if days_found else '-'})")
    print(f"  Days loaded: {len(days_loaded)}")
    print(sep)

    if not all_trades:
        print("\n  NO TRADES fired across all days.")
        return

    wins  = [t for t in all_trades if t['pnl_pts'] > 0]
    loss  = [t for t in all_trades if t['pnl_pts'] <= 0]
    total_pts = sum(t['pnl_pts'] for t in all_trades)
    total_rs  = sum(t['pnl_rs']  for t in all_trades)
    wr = len(wins) / len(all_trades) * 100

    print(f"\n  OVERALL SUMMARY")
    print(f"  {'─'*50}")
    print(f"  Total trades : {len(all_trades)}  (W:{len(wins)}  L:{len(loss)})")
    print(f"  Win rate     : {wr:.1f}%")
    print(f"  Total PnL    : {total_pts:+.1f} pts  |  ₹{total_rs:+,.0f}")
    if wins:
        print(f"  Avg win      : {np.mean([t['pnl_pts'] for t in wins]):+.1f} pts")
    if loss:
        print(f"  Avg loss     : {np.mean([t['pnl_pts'] for t in loss]):+.1f} pts")
    avg_per_day = total_rs / len(days_loaded) if days_loaded else 0
    print(f"  Avg day PnL  : ₹{avg_per_day:+,.0f}")

    # By exit reason
    reasons: Dict = {}
    for t in all_trades:
        r = t['reason']
        reasons.setdefault(r, {'n': 0, 'pnl': 0})
        reasons[r]['n']   += 1
        reasons[r]['pnl'] += t['pnl_pts']
    print(f"\n  BY EXIT REASON:")
    for r, v in sorted(reasons.items(), key=lambda x: -x[1]['pnl']):
        print(f"    {r:<22} n={v['n']:>3}  pnl={v['pnl']:>+8.1f} pts")

    # By day
    print(f"\n  BY DAY:")
    print(f"  {'DATE':<12} {'#':>4} {'PNL_PTS':>10} {'PNL_RS':>12} {'WR%':>7}")
    print(f"  {'─'*55}")
    day_groups: Dict[str, List] = {}
    for t in all_trades:
        day_groups.setdefault(t['day'], []).append(t)
    for d in sorted(day_groups):
        dtrades  = day_groups[d]
        dpnl_pts = sum(t['pnl_pts'] for t in dtrades)
        dpnl_rs  = sum(t['pnl_rs']  for t in dtrades)
        dwr      = sum(1 for t in dtrades if t['pnl_pts'] > 0) / len(dtrades) * 100
        flag = '✅' if dpnl_pts > 0 else '❌'
        print(f"  {flag} {d:<10} {len(dtrades):>4}  {dpnl_pts:>+9.1f}  ₹{dpnl_rs:>+10,.0f}  {dwr:>6.1f}%")

    # Trade-by-trade
    print(f"\n  TRADE-BY-TRADE:")
    print(f"  {'DATE':<12}{'SIG':>6}{'FILL':>6}{'EXIT':>6}  {'S':>3}  "
          f"{'STK':>6}  {'REF':>7}  {'ENTRY':>7}  {'EXIT_P':>7}  "
          f"{'PTS':>7}  {'Rs':>9}  REASON")
    print(f"  {'─'*105}")
    for t in all_trades:
        flag = '✅' if t['pnl_pts'] > 0 else '❌'
        print(f"  {flag} {t['day']:<10} {t['sig_time']:>5} {t['fill_time']:>5} {t['exit_time']:>5}  "
              f"{t['side']:>3}  {t['strike']:>6}  {t['ref_price']:>7.2f}  "
              f"{t['entry']:>7.2f}  {t['exit']:>7.2f}  "
              f"{t['pnl_pts']:>+7.2f}  ₹{t['pnl_rs']:>+8,.0f}  {t['reason']}")

    # Skips
    print(f"\n  SIGNALS SKIPPED / DATA GAPS:")
    if all_notes:
        for n in all_notes:
            print(n)
    else:
        print("  (none)")

    print(f"\n{sep}")
    print(f"  Body threshold : >{BODY_MIN_PCT:.0%}  |  Entry: {entry_mode}")
    print(f"  HARDSL: -{HARDSL_PCT:.0%}  |  RI: {RI}  |  CB: {CIRCUIT_BREAKER} losses/day")
    print(sep)

# ── Main ───────────────────────────────────────────────────────────────
def main():
    import io, builtins, subprocess

    print("=" * 72)
    print("  ORION OFFLINE BACKTEST  (no Kite API needed)")
    print("=" * 72)

    df_fut15 = load_fut15m()

    all_days = discover_days()
    if not all_days:
        print(f"[ERROR] No option data days found in {OPT_BASES}")
        sys.exit(1)
    print(f"[DATA] {len(all_days)} option days: {all_days[0]} → {all_days[-1]}")

    all_trades: List[dict] = []
    all_notes:  List[str]  = []
    days_loaded: List[str] = []

    for day_str in all_days:
        day_date = datetime.strptime(day_str, '%Y-%m-%d').date()
        IST_09_15 = datetime(day_date.year, day_date.month, day_date.day, 9, 15)
        IST_15_30 = datetime(day_date.year, day_date.month, day_date.day, 15, 30)
        if df_fut15[(df_fut15['date'] >= IST_09_15) & (df_fut15['date'] <= IST_15_30)].empty:
            all_notes.append(f"  {day_str}: No futures data — skipped")
            continue

        day_opt = load_day_options(day_str)
        if day_opt is None:
            all_notes.append(f"  {day_str}: No option data — skipped")
            continue

        print(f"  {day_str} ...")
        days_loaded.append(day_str)
        trades, notes = run_day(day_str, df_fut15, day_opt, day_date)
        all_trades.extend(trades)
        all_notes.extend(notes)

    # Tee output to file
    buf = io.StringIO()
    _orig_print = builtins.print
    def _tee(*args, **kwargs):
        _orig_print(*args, **kwargs)
        kw2 = {k: v for k, v in kwargs.items() if k != 'file'}
        _orig_print(*args, file=buf, **kw2)
    builtins.print = _tee

    print_summary(all_trades, all_notes, all_days, days_loaded)

    builtins.print = _orig_print

    out_path = os.path.join(REPO_DIR, 'futvwap_result.txt')
    with open(out_path, 'w') as f:
        f.write(buf.getvalue())
    _orig_print(f"\n[SAVED] {out_path}")

    # Push to GitHub
    try:
        branch = 'claude/general-session-YfHuZ'
        subprocess.run(['git', 'add', out_path, __file__], cwd=REPO_DIR, check=True)
        r = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=REPO_DIR)
        if r.returncode != 0:
            mode = 'market-entry' if LIMIT_OFFSET == 0 else f'limit-{LIMIT_OFFSET}'
            subprocess.run(
                ['git', 'commit', '-m',
                 f'backtest offline {mode}: {len(all_trades)} trades on {len(days_loaded)} days'],
                cwd=REPO_DIR, check=True)
            # Try with embedded PAT if available
            try:
                import credentials as _c
                pat = getattr(_c, 'GITHUB_PAT', None)
                remote = (f"https://{pat}@github.com/amolselukar/Amol.git"
                          if pat else "origin")
            except Exception:
                remote = "origin"
            subprocess.run(['git', 'push', '-u', remote, branch], cwd=REPO_DIR, check=True)
            _orig_print("[GITHUB] Pushed results.")
        else:
            _orig_print("[GITHUB] No changes to push.")
    except subprocess.CalledProcessError as e:
        _orig_print(f"[GITHUB] Push failed: {e}")


if __name__ == '__main__':
    main()
