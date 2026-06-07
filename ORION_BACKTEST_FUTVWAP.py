"""
==========================================================================
ORION_BACKTEST_FUTVWAP.py
==========================================================================
Entry logic : Nifty Futures 15m bar
              - body > 50% of bar range
              - bar closes ABOVE daily VWAP  → ATM CE signal
              - bar closes BELOW daily VWAP  → ATM PE signal
              - buy limit = option price at signal time - 13
              - limit order window: next 15 min (3 × 5m bars); if not filled → skip

Exit logic  : V2.5.12 (same as live bot)
              HARDSL -18% | Velvet Rope (peak+12→SL entry+2)
              Ladder T2 (peak+24→SL entry+12) | Ladder T3 (peak+36→SL entry+24)
              Runner +25/+25 | SMA8(low) trail | Force close 15:25

Data sources:
  Nifty Futures 15m  → fetched from Kite API (auto-discovers correct expiry)
  Nifty Spot 15m     → from daily_option_data/<day>/nifty_15m.csv (for ATM)
  Option prices      → from both DATA_BASES below

Both data folders are scanned; dates are merged (Selukar + Amol).
Runs auto_login.py first if access_token is stale.
==========================================================================
"""
import os, sys, glob, json, csv
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Tuple

# ── Paths ──────────────────────────────────────────────────────────────
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_DIR)

# Both option-data folders — script scans whichever exists
DATA_BASES = [
    "/home/Selukar/daily_option_data",
    "/home/Amol/daily_option_data",
]

# ── Credentials ────────────────────────────────────────────────────────
try:
    import credentials as _c
    KITE_API_KEY    = _c.KITE_API_KEY
    KITE_API_SECRET = _c.KITE_API_SECRET
    KITE_ACCESS_TOKEN = _c.KITE_ACCESS_TOKEN
    GITHUB_PAT      = getattr(_c, 'GITHUB_PAT', None)
except (ImportError, AttributeError) as e:
    print(f"[ERROR] credentials.py missing key: {e}")
    sys.exit(1)

from kiteconnect import KiteConnect

# ── Strategy constants (V2.5.12) ───────────────────────────────────────
LOT_SIZE       = 65
LOTS           = 2
HARDSL_PCT     = 0.18           # -18% hard stop
RI             = 12             # Velvet Rope trigger: peak >= entry + RI
VR_SL          = 2              # SL after Velvet Rope: entry + 2
T2_PEAK        = 24             # Ladder Tier2 peak threshold
T2_SL          = 12             # Ladder Tier2 SL
T3_PEAK        = 36             # Ladder Tier3 peak threshold
T3_SL          = 24             # Ladder Tier3 SL
RUNNER_STEP    = 25             # Runner ratchet step (pts)
SMA_TRAIL_BARS = 8              # SMA8(low) trail on 15m option bars
FORCE_CLOSE    = "15:25"
ENTRY_CUTOFF   = "14:45"        # no new entries after this 15m bar close

PREM_MIN       = 30             # minimum option premium at entry
PREM_MAX       = 300            # max (PE generous for panic moves)
BODY_MIN_PCT   = 0.50           # futures bar body must be > 50% of range
LIMIT_OFFSET   = 13             # buy limit = option_price - 13
LIMIT_WINDOW_BARS = 3           # max 5m bars to wait for limit fill (~15 min)
CIRCUIT_BREAKER = 3             # non-flip losses per day

# ── KiteConnect init ───────────────────────────────────────────────────
def init_kite() -> KiteConnect:
    kite = KiteConnect(api_key=KITE_API_KEY)
    kite.set_access_token(KITE_ACCESS_TOKEN)
    # Quick validity check
    try:
        kite.profile()
        print("[KITE] Access token valid.")
    except Exception as e:
        print(f"[KITE] Token invalid ({e}). Run: python auto_login.py")
        sys.exit(1)
    return kite

# ── Instrument token for Nifty Futures ────────────────────────────────
def get_nifty_fut_token(kite: KiteConnect, for_date: date) -> Optional[int]:
    """Find the Nifty futures token active on for_date (nearest expiry >= for_date)."""
    instr = kite.instruments("NFO")
    nifty_futs = [
        i for i in instr
        if i['name'] == 'NIFTY'
        and i['instrument_type'] == 'FUT'
        and i['expiry'] >= for_date
    ]
    if not nifty_futs:
        return None
    nifty_futs.sort(key=lambda x: x['expiry'])
    tok = nifty_futs[0]['instrument_token']
    sym = nifty_futs[0]['tradingsymbol']
    print(f"[FUT] {for_date} → {sym} token={tok} expiry={nifty_futs[0]['expiry']}")
    return tok

# ── Fetch Nifty Futures 15m data from Kite ────────────────────────────
def fetch_fut15m(kite: KiteConnect, token: int, from_dt: datetime, to_dt: datetime) -> pd.DataFrame:
    """Fetch 15m futures bars from Kite API."""
    try:
        bars = kite.historical_data(token, from_dt, to_dt, "15minute")
    except Exception as e:
        print(f"[FUT] Kite fetch error: {e}")
        return pd.DataFrame()
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    df = df.sort_values('date').reset_index(drop=True)
    return df

# ── Compute rolling session VWAP from futures 15m bars ────────────────
def compute_fut_vwap(df_day: pd.DataFrame) -> pd.Series:
    """
    Rolling VWAP for one trading day.
    Resets at 9:15. Returns Series indexed same as df_day.
    """
    tp  = (df_day['high'] + df_day['low'] + df_day['close']) / 3
    vol = df_day['volume'].fillna(1).replace(0, 1)
    cum_tpv = (tp * vol).cumsum()
    cum_vol = vol.cumsum()
    return (cum_tpv / cum_vol).reset_index(drop=True)

# ── Load one day's option data from the two folders ───────────────────
def load_day_options(day_str: str) -> Optional[dict]:
    """
    Tries DATA_BASES in order. Returns dict with:
      df15_spot : Nifty spot 15m (for ATM calc)
      opt       : {(strike, 'CE'/'PE'): df_5m}
      source    : which folder
    Returns None if day not found in any folder.
    """
    for base in DATA_BASES:
        ddir = os.path.join(base, day_str)
        if not os.path.isdir(ddir):
            continue
        try:
            # Spot 15m
            p15 = os.path.join(ddir, 'nifty_15m.csv')
            if not os.path.exists(p15):
                continue
            df15 = pd.read_csv(p15, parse_dates=['date'])
            df15['date'] = pd.to_datetime(df15['date']).dt.tz_localize(None)
            df15 = df15.sort_values('date').reset_index(drop=True)

            # Option 5m files: CE/*.csv + PE/*.csv
            opt = {}
            for side in ('CE', 'PE'):
                sdir = os.path.join(ddir, side)
                if not os.path.isdir(sdir):
                    continue
                for fp in glob.glob(os.path.join(sdir, '*.csv')):
                    strike = int(os.path.basename(fp).replace('.csv', ''))
                    try:
                        dfopt = pd.read_csv(fp, parse_dates=['date'])
                        dfopt['date'] = pd.to_datetime(dfopt['date']).dt.tz_localize(None)
                        # support both 5m-only files and multi-tf files
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
            print(f"  [LOAD] {day_str} in {base}: error {e}")
            continue
    return None

# ── Discover all available days across both folders ───────────────────
def discover_days() -> List[str]:
    days = set()
    for base in DATA_BASES:
        if not os.path.isdir(base):
            print(f"  [DATA] Folder not found: {base}")
            continue
        for d in os.listdir(base):
            if d.startswith('20') and os.path.isdir(os.path.join(base, d)):
                days.add(d)
    return sorted(days)

# ── ATM strike from spot price ─────────────────────────────────────────
def atm_strike(spot: float) -> int:
    return int(round(spot / 50) * 50)  # Nifty ATM is ±50 strikes

# ── Get option 5m bar closest to (but not after) a given time ─────────
def opt_price_at(opt_df: pd.DataFrame, at_time: datetime) -> Optional[float]:
    """Return close of the last 5m bar whose date <= at_time."""
    mask = opt_df['date'] <= at_time
    if not mask.any():
        return None
    return float(opt_df.loc[mask, 'close'].iloc[-1])

# ── Simulate limit order fill ──────────────────────────────────────────
def try_limit_fill(opt_df: pd.DataFrame, signal_time: datetime,
                   ref_price: float) -> Tuple[Optional[float], Optional[datetime]]:
    """
    After signal_time, look at next LIMIT_WINDOW_BARS 5m bars.
    If any bar has low <= (ref_price - LIMIT_OFFSET): filled at ref_price - LIMIT_OFFSET.
    Returns (fill_price, fill_time) or (None, None).
    """
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
    """
    Simulate V2.5.12 exit on 5m option bars from entry_time onward.
    Returns (exit_time, exit_prem, reason).
    """
    hardsl   = entry_prem * (1 - HARDSL_PCT)
    tr_armed = False
    tr_sl    = 0.0
    peak     = entry_prem
    sma_lows = []   # accumulate bar lows; treat every 3 5m bars as one 15m bar

    bars = opt_df[opt_df['date'] >= entry_time].reset_index(drop=True)
    if bars.empty:
        return entry_time, entry_prem, 'NO_DATA'

    for _, bar in bars.iterrows():
        dt = bar['date']
        o, h, l, c = float(bar['open']), float(bar['high']), float(bar['low']), float(bar['close'])

        peak = max(peak, h)
        sma_lows.append(l)

        # Force close
        if dt.strftime('%H:%M') >= FORCE_CLOSE:
            return dt, c, 'FORCE_CLOSE'

        # HARDSL
        if l <= hardsl:
            return dt, round(hardsl, 2), 'HARDSL_-18pct'

        # Velvet Rope: peak reaches entry+RI → SL immediately to entry+VR_SL
        if not tr_armed and h >= entry_prem + RI:
            tr_armed = True
            tr_sl    = entry_prem + VR_SL
            if l <= tr_sl:
                return dt, round(tr_sl, 2), 'VELVET_ROPE'

        if tr_armed:
            # Ladder T3 (check first — higher threshold)
            if peak >= entry_prem + T3_PEAK and tr_sl < entry_prem + T3_SL:
                tr_sl = entry_prem + T3_SL
            # Ladder T2
            elif peak >= entry_prem + T2_PEAK and tr_sl < entry_prem + T2_SL:
                tr_sl = entry_prem + T2_SL
            # Runner +25/+25
            while peak >= tr_sl + RUNNER_STEP:
                tr_sl += RUNNER_STEP
            if l <= tr_sl:
                pts = round(tr_sl - entry_prem, 1)
                return dt, round(tr_sl, 2), f'RATCHET_+{int(pts)}'

        # SMA8(low) trail — check every 3 bars (≈15m boundary)
        if len(sma_lows) >= SMA_TRAIL_BARS and len(sma_lows) % 3 == 0:
            sma8l = float(np.mean(sma_lows[-SMA_TRAIL_BARS:]))
            if c < sma8l:
                return dt, c, 'SMA8_TRAIL'

    last = bars.iloc[-1]
    return last['date'], float(last['close']), 'EOD'

# ── Run backtest for one day ───────────────────────────────────────────
def run_day(day_str: str, df_fut15: pd.DataFrame, day_opt: dict,
            day_date: date) -> Tuple[List[dict], List[str]]:
    """
    Returns (trades, skip_notes).
    trades: list of trade dicts
    skip_notes: list of signals that were skipped and why
    """
    trades = []
    notes  = []

    IST_09_15 = datetime(day_date.year, day_date.month, day_date.day, 9, 15)
    IST_15_30 = datetime(day_date.year, day_date.month, day_date.day, 15, 30)

    # Filter futures bars for this day
    fut_day = df_fut15[
        (df_fut15['date'] >= IST_09_15) &
        (df_fut15['date'] <= IST_15_30)
    ].reset_index(drop=True)

    if fut_day.empty:
        notes.append(f"  {day_str}: NO futures 15m data for this day")
        return trades, notes

    # Compute running VWAP from futures
    fut_day = fut_day.copy()
    fut_day['vwap'] = compute_fut_vwap(fut_day)

    # Spot 15m for ATM calculation
    df15_spot = day_opt['df15_spot']
    opt        = day_opt['opt']

    daily_losses = 0
    halted       = False
    last_exit_time: Optional[datetime] = None
    last_vwap_bar: Optional[datetime]  = None   # dedup: fire once per futures bar

    for i in range(1, len(fut_day)):   # skip first bar (no prior VWAP)
        if halted:
            break

        fbar = fut_day.iloc[i]
        bar_time = fbar['date']       # close time of this 15m bar

        # Cutoff check
        if bar_time.strftime('%H:%M') > ENTRY_CUTOFF:
            break

        # Don't re-enter before previous trade exits
        if last_exit_time and bar_time <= last_exit_time:
            continue

        # Same-bar dedup
        if last_vwap_bar == bar_time:
            continue

        fo, fh, fl, fc = float(fbar['open']), float(fbar['high']), float(fbar['low']), float(fbar['close'])
        vwap = float(fbar['vwap'])
        f_range = fh - fl
        if f_range <= 0:
            continue
        body_pct = abs(fc - fo) / f_range

        # Body > 50% check
        if body_pct <= BODY_MIN_PCT:
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                         f"body={body_pct:.0%} ≤ 50% — skip")
            continue

        # VWAP side
        if fc > vwap:
            side = 'CE'
        elif fc < vwap:
            side = 'PE'
        else:
            continue

        signal_reason = (f"Fut VWAP cross {fc:.0f}{'>' if side=='CE' else '<'}{vwap:.0f} "
                         f"body={body_pct:.0%} fut_bar={bar_time.strftime('%H:%M')}")

        # ATM from spot price at same time
        spot_at = df15_spot[df15_spot['date'] <= bar_time]
        if spot_at.empty:
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: no spot bar yet — skip")
            continue
        spot_price = float(spot_at.iloc[-1]['close'])
        atm = atm_strike(spot_price)

        # Get option data (try ATM, then ±50)
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
                             f"no option data for ATM {atm} {side} — skip")
                continue

        opt_df = opt[opt_key]
        strike = opt_key[0]

        # Reference option price at signal time
        ref_price = opt_price_at(opt_df, bar_time)
        if ref_price is None or ref_price <= 0:
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                         f"option {strike}{side} no price at signal time — skip")
            continue

        limit_price = round(ref_price - LIMIT_OFFSET, 2)

        # Premium gate at reference price (before limit)
        if not (PREM_MIN <= ref_price <= PREM_MAX):
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                         f"{side} {strike} ref_price={ref_price:.1f} outside gate [{PREM_MIN},{PREM_MAX}] — skip")
            continue

        if limit_price <= 0:
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                         f"limit_price={limit_price:.2f} ≤ 0 — skip")
            continue

        # Try limit fill in next LIMIT_WINDOW_BARS 5m bars
        fill_price, fill_time = try_limit_fill(opt_df, bar_time, ref_price)

        if fill_price is None:
            notes.append(f"  {day_str} {bar_time.strftime('%H:%M')}: "
                         f"{side} {strike} limit={limit_price:.2f} not filled in "
                         f"{LIMIT_WINDOW_BARS}×5m window — ORDER EXPIRED")
            continue

        # Mark this bar as fired
        last_vwap_bar = bar_time

        # Simulate exit from fill_time onward
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
            limit     = round(limit_price, 2),
            entry     = round(fill_price, 2),
            exit      = round(exit_prem, 2),
            pnl_pts   = pnl_pts,
            pnl_rs    = pnl_rs,
            reason    = reason,
            signal    = signal_reason,
        ))

        # Circuit breaker (exclude MANUAL_EXIT equivalent — here force-close not a loss per se)
        last_exit_time = exit_time
        if pnl_pts < 0:
            daily_losses += 1
            if daily_losses >= CIRCUIT_BREAKER:
                halted = True
                notes.append(f"  {day_str}: CIRCUIT BREAKER — {daily_losses} losses, halted")

    return trades, notes

# ── Print full summary ─────────────────────────────────────────────────
def print_summary(all_trades: List[dict], all_notes: List[str],
                  days_found: List[str], days_loaded: List[str]):
    sep = '=' * 72

    print(f"\n{sep}")
    print(f"  ORION FUTVWAP BACKTEST — ENTRY: Nifty Futures 15m VWAP + Limit -₹{LIMIT_OFFSET}")
    print(f"  Exit: V2.5.12 | Lots: {LOTS} × {LOT_SIZE} = {LOTS*LOT_SIZE} qty")
    print(f"  Data dates found : {len(days_found)} ({days_found[0] if days_found else '-'} → {days_found[-1] if days_found else '-'})")
    print(f"  Data dates loaded: {len(days_loaded)}")
    print(sep)

    if not all_trades:
        print("\n  NO TRADES fired across all days.")
    else:
        wins = [t for t in all_trades if t['pnl_pts'] > 0]
        loss = [t for t in all_trades if t['pnl_pts'] <= 0]
        total_pnl_pts = sum(t['pnl_pts'] for t in all_trades)
        total_pnl_rs  = sum(t['pnl_rs']  for t in all_trades)
        wr = len(wins) / len(all_trades) * 100

        print(f"\n  OVERALL SUMMARY")
        print(f"  {'─'*50}")
        print(f"  Total trades : {len(all_trades)}  (W:{len(wins)}  L:{len(loss)})")
        print(f"  Win rate     : {wr:.1f}%")
        print(f"  Total PnL    : {total_pnl_pts:+.1f} pts  |  ₹{total_pnl_rs:+,.0f}")
        print(f"  Avg win      : {np.mean([t['pnl_pts'] for t in wins]):+.1f} pts" if wins else "  Avg win  : N/A")
        print(f"  Avg loss     : {np.mean([t['pnl_pts'] for t in loss]):+.1f} pts" if loss else "  Avg loss : N/A")

        # By exit reason
        reasons = {}
        for t in all_trades:
            r = t['reason']
            reasons.setdefault(r, {'n':0, 'pnl':0})
            reasons[r]['n']   += 1
            reasons[r]['pnl'] += t['pnl_pts']
        print(f"\n  BY EXIT REASON:")
        for r, v in sorted(reasons.items(), key=lambda x: -x[1]['pnl']):
            print(f"    {r:<20} n={v['n']:>3}  pnl={v['pnl']:+.1f} pts")

        # By day
        from itertools import groupby
        print(f"\n  BY DAY:")
        print(f"  {'DATE':<12} {'#':>4} {'PNL_PTS':>10} {'PNL_RS':>12} {'WR%':>7}")
        print(f"  {'─'*55}")
        day_groups: Dict[str, List] = {}
        for t in all_trades:
            day_groups.setdefault(t['day'], []).append(t)
        for d in sorted(day_groups):
            dtrades = day_groups[d]
            dpnl_pts = sum(t['pnl_pts'] for t in dtrades)
            dpnl_rs  = sum(t['pnl_rs']  for t in dtrades)
            dwr      = sum(1 for t in dtrades if t['pnl_pts'] > 0) / len(dtrades) * 100
            flag = '✅' if dpnl_pts > 0 else '❌'
            print(f"  {flag} {d:<10} {len(dtrades):>4}  {dpnl_pts:>+9.1f}  ₹{dpnl_rs:>+10,.0f}  {dwr:>6.1f}%")

        # Trade by trade
        print(f"\n  TRADE-BY-TRADE:")
        print(f"  {'DATE':<12}{'TIME':>6}{'FILL':>6}{'EXIT':>6}  {'S':>3}  "
              f"{'STK':>6}  {'REF':>7}  {'LMT':>7}  {'ENTRY':>7}  {'EXIT_P':>7}  "
              f"{'PTS':>7}  {'Rs':>9}  REASON")
        print(f"  {'─'*110}")
        for t in all_trades:
            flag = '✅' if t['pnl_pts'] > 0 else '❌'
            print(f"  {flag} {t['day']:<10} {t['sig_time']:>5} {t['fill_time']:>5} {t['exit_time']:>5}  "
                  f"{t['side']:>3}  {t['strike']:>6}  {t['ref_price']:>7.2f}  "
                  f"{t['limit']:>7.2f}  {t['entry']:>7.2f}  {t['exit']:>7.2f}  "
                  f"{t['pnl_pts']:>+7.2f}  ₹{t['pnl_rs']:>+8,.0f}  {t['reason']}")

    # Skipped signals
    print(f"\n  SIGNALS SKIPPED / DATA GAPS:")
    if all_notes:
        for n in all_notes:
            print(n)
    else:
        print("  (none)")

    print(f"\n{sep}")
    print(f"  Body threshold : >{BODY_MIN_PCT:.0%} of bar range")
    print(f"  Limit offset   : entry ≤ option_price - ₹{LIMIT_OFFSET}")
    print(f"  Limit window   : {LIMIT_WINDOW_BARS} × 5min bars (~{LIMIT_WINDOW_BARS*5} min)")
    print(f"  HARDSL         : -{HARDSL_PCT:.0%}")
    print(f"  Circuit Breaker: {CIRCUIT_BREAKER} bot-driven losses/day")
    print(sep)

# ── Main ───────────────────────────────────────────────────────────────
def main():
    print("=" * 72)
    print("  ORION FUTVWAP BACKTEST")
    print("=" * 72)

    kite = init_kite()

    # Discover all available dates
    all_days = discover_days()
    if not all_days:
        print("[ERROR] No option data days found in any DATA_BASE folder.")
        print(f"  Checked: {DATA_BASES}")
        sys.exit(1)

    print(f"\n[DATA] Found {len(all_days)} days: {all_days[0]} → {all_days[-1]}")
    for base in DATA_BASES:
        if os.path.isdir(base):
            cnt = len([d for d in os.listdir(base)
                       if d.startswith('20') and os.path.isdir(os.path.join(base, d))])
            print(f"       {base}: {cnt} days")
        else:
            print(f"       {base}: NOT FOUND")

    # Fetch Nifty Futures 15m for the date range (one API call with date range)
    start_dt = datetime.strptime(all_days[0],  '%Y-%m-%d') - timedelta(days=1)
    end_dt   = datetime.strptime(all_days[-1], '%Y-%m-%d') + timedelta(days=1)

    print(f"\n[FUT] Fetching Nifty Futures 15m: {start_dt.date()} → {end_dt.date()}")
    # Get token for the first date (covers the range; handles roll automatically
    # because instrument list always shows nearest future)
    fut_token = get_nifty_fut_token(kite, for_date=start_dt.date())
    if fut_token is None:
        print("[ERROR] Could not find Nifty Futures instrument token. Check Kite instruments.")
        sys.exit(1)

    df_fut15 = fetch_fut15m(kite, fut_token, start_dt, end_dt)
    if df_fut15.empty:
        print("[ERROR] Futures 15m data is empty. Check token, date range, and Kite subscription.")
        sys.exit(1)

    print(f"[FUT] Got {len(df_fut15)} bars from {df_fut15['date'].iloc[0]} to {df_fut15['date'].iloc[-1]}")

    # Handle roll: if date range spans an expiry, fetch next future too
    last_day_date = datetime.strptime(all_days[-1], '%Y-%m-%d').date()
    fut_token2 = get_nifty_fut_token(kite, for_date=last_day_date)
    if fut_token2 and fut_token2 != fut_token:
        print(f"[FUT] Detected futures roll — fetching second contract token={fut_token2}")
        df_fut15b = fetch_fut15m(kite, fut_token2, start_dt, end_dt)
        if not df_fut15b.empty:
            df_fut15 = pd.concat([df_fut15, df_fut15b]).sort_values('date').drop_duplicates('date').reset_index(drop=True)
            print(f"[FUT] Combined: {len(df_fut15)} bars after roll merge")

    # Run backtest day by day
    all_trades = []
    all_notes  = []
    days_loaded = []

    for day_str in all_days:
        day_date = datetime.strptime(day_str, '%Y-%m-%d').date()

        # Check futures data for this day
        IST_09_15 = datetime(day_date.year, day_date.month, day_date.day, 9, 15)
        IST_15_30 = datetime(day_date.year, day_date.month, day_date.day, 15, 30)
        fut_day_check = df_fut15[(df_fut15['date'] >= IST_09_15) &
                                  (df_fut15['date'] <= IST_15_30)]
        if fut_day_check.empty:
            all_notes.append(f"  {day_str}: NO Nifty Futures 15m data — day skipped")
            continue

        # Load option data
        day_opt = load_day_options(day_str)
        if day_opt is None:
            all_notes.append(f"  {day_str}: No option data in any folder — day skipped")
            continue

        print(f"  Processing {day_str} (from {day_opt['source']}) ...")
        days_loaded.append(day_str)

        trades, notes = run_day(day_str, df_fut15, day_opt, day_date)
        all_trades.extend(trades)
        all_notes.extend(notes)

    # Capture summary into string and save to file
    import io, subprocess
    buf = io.StringIO()
    import builtins
    _orig_print = builtins.print
    def _tee(*args, **kwargs):
        _orig_print(*args, **kwargs)
        kwargs.pop('file', None)
        _orig_print(*args, file=buf, **kwargs)
    builtins.print = _tee
    print_summary(all_trades, all_notes, all_days, days_loaded)
    builtins.print = _orig_print

    out_path = os.path.join(REPO_DIR, 'futvwap_result.txt')
    with open(out_path, 'w') as f:
        f.write(buf.getvalue())
    _orig_print(f"\n[SAVED] Results → {out_path}")

    # Push to GitHub
    try:
        branch = 'claude/general-session-YfHuZ'
        subprocess.run(['git', 'add', out_path], cwd=REPO_DIR, check=True)
        r = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=REPO_DIR)
        if r.returncode != 0:
            subprocess.run(['git', 'commit', '-m',
                f'futvwap_backtest: {len(all_trades)} trades on {len(days_loaded)} days'],
                cwd=REPO_DIR, check=True)
            remote = (f"https://{GITHUB_PAT}@github.com/amolselukar/Amol.git"
                      if GITHUB_PAT else "origin")
            subprocess.run(['git', 'push', remote, branch], cwd=REPO_DIR, check=True)
            _orig_print("[GITHUB] Results pushed.")
        else:
            _orig_print("[GITHUB] No changes to push.")
    except subprocess.CalledProcessError as e:
        _orig_print(f"[GITHUB] Push failed: {e}. Results still saved locally.")


if __name__ == '__main__':
    main()
