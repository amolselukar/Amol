"""
ORION V2.5.14 — Fetch historical data + backtest VWAP triple confirmation
Run on PythonAnywhere after auto_login.py refreshes the Kite token.

Usage:
    python3 auto_login.py
    python3 fetch_and_backtest.py

Fetches:
    1. Nifty futures 15m (1 month)
    2. Nifty spot 15m (1 month)
    3. ATM option 15m for each day (for option VWAP gate)
Then simulates the VWAP engine comparing:
    OLD: spot VWAP cross (double confirmation)
    NEW: futures VWAP cross as primary (triple confirmation)
    FAST: futures VWAP cross + spot LIVE price (Option B)
"""
import sys, os, time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import credentials
    KITE_API_KEY = credentials.KITE_API_KEY
    KITE_ACCESS_TOKEN = credentials.KITE_ACCESS_TOKEN
except Exception as e:
    print(f"❌ credentials.py error: {e}")
    sys.exit(1)

from kiteconnect import KiteConnect

kite = KiteConnect(api_key=KITE_API_KEY)
kite.set_access_token(KITE_ACCESS_TOKEN)

# Verify connection
try:
    profile = kite.profile()
    print(f"✅ Kite connected: {profile['user_name']}")
except Exception as e:
    print(f"❌ Kite auth failed: {e}")
    print("Run auto_login.py first.")
    sys.exit(1)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_data")
os.makedirs(DATA_DIR, exist_ok=True)

NIFTY_SPOT_TOKEN = 256265
DAYS_BACK = 30
VWAP_BODY_MIN_PCT = 0.50

# ── Step 1: Resolve Nifty Futures token ──
print("\n[1/4] Resolving Nifty futures token...")
insts = kite.instruments("NFO")
today = date.today()
nifty_futs = [i for i in insts if i["name"] == "NIFTY"
              and i["instrument_type"] == "FUT"
              and i["expiry"] >= today]
if not nifty_futs:
    print("❌ No Nifty FUT found")
    sys.exit(1)
# We need the futures that were active during the backtest period
# Sort all futures by expiry
nifty_futs_sorted = sorted(nifty_futs, key=lambda x: x["expiry"])
fut = nifty_futs_sorted[0]
NIFTY_FUT_TOKEN = fut["instrument_token"]
print(f"   FUT token: {NIFTY_FUT_TOKEN}, expiry: {fut['expiry']}, sym: {fut['tradingsymbol']}")

# Also collect all option instruments for later
nifty_options = [i for i in insts if i["name"] == "NIFTY"
                 and i["instrument_type"] in ("CE", "PE")]
print(f"   {len(nifty_options)} option instruments available")

# ── Step 2: Fetch futures 15m data ──
print("\n[2/4] Fetching Nifty FUTURES 15m data...")
now = datetime.now()
frm = now - timedelta(days=DAYS_BACK)
fut_15m = kite.historical_data(NIFTY_FUT_TOKEN, frm, now, "15minute")
df_fut = pd.DataFrame(fut_15m)
df_fut.to_csv(os.path.join(DATA_DIR, "nifty_fut_15m.csv"), index=False)
print(f"   ✅ {len(df_fut)} bars fetched, saved to backtest_data/nifty_fut_15m.csv")

# ── Step 3: Fetch spot 15m data ──
print("\n[3/4] Fetching Nifty SPOT 15m data...")
spot_15m = kite.historical_data(NIFTY_SPOT_TOKEN, frm, now, "15minute")
df_spot = pd.DataFrame(spot_15m)
df_spot.to_csv(os.path.join(DATA_DIR, "nifty_spot_15m.csv"), index=False)
print(f"   ✅ {len(df_spot)} bars fetched, saved to backtest_data/nifty_spot_15m.csv")

# ── Step 4: Fetch ATM option 15m data per day ──
print("\n[4/4] Fetching ATM option 15m data per trading day...")
# Get unique trading days from spot data
df_spot['date'] = pd.to_datetime(df_spot['date'])
trading_days = sorted(df_spot['date'].dt.date.unique())
print(f"   {len(trading_days)} trading days found")

# For each day, determine ATM strike at ~9:30, fetch CE and PE 15m
option_data = {}  # {date: {"CE": df, "PE": df, "atm": strike}}

for day in trading_days:
    day_spot = df_spot[df_spot['date'].dt.date == day]
    if len(day_spot) < 2:
        continue
    # Use first bar's close as reference for ATM
    first_close = float(day_spot.iloc[0]['close'])
    atm = int(round(first_close / 50) * 50)

    # Find option tokens for this ATM strike and the relevant expiry
    day_dt = datetime.combine(day, datetime.min.time())
    relevant_opts = [i for i in nifty_options
                     if i["strike"] == atm
                     and i["expiry"] >= day]
    if not relevant_opts:
        continue
    # Pick nearest expiry
    nearest_expiry = min(i["expiry"] for i in relevant_opts)
    ce_opts = [i for i in relevant_opts if i["instrument_type"] == "CE" and i["expiry"] == nearest_expiry]
    pe_opts = [i for i in relevant_opts if i["instrument_type"] == "PE" and i["expiry"] == nearest_expiry]
    if not ce_opts or not pe_opts:
        continue

    ce_token = ce_opts[0]["instrument_token"]
    pe_token = pe_opts[0]["instrument_token"]

    day_from = datetime.combine(day, datetime.min.time())
    day_to = datetime.combine(day, datetime.max.time())

    try:
        ce_data = kite.historical_data(ce_token, day_from, day_to, "15minute")
        pe_data = kite.historical_data(pe_token, day_from, day_to, "15minute")
        if ce_data and pe_data:
            option_data[day] = {
                "CE": pd.DataFrame(ce_data),
                "PE": pd.DataFrame(pe_data),
                "atm": atm,
                "ce_token": ce_token,
                "pe_token": pe_token,
                "ce_sym": ce_opts[0]["tradingsymbol"],
                "pe_sym": pe_opts[0]["tradingsymbol"],
            }
            print(f"   {day} ATM={atm} CE={ce_opts[0]['tradingsymbol']} PE={pe_opts[0]['tradingsymbol']} ✅")
        time.sleep(0.3)  # rate limit
    except Exception as e:
        print(f"   {day} ATM={atm} ❌ {e}")
        time.sleep(1)

print(f"\n   ✅ Option data for {len(option_data)} days")

# Save option data
for day, data in option_data.items():
    for side in ("CE", "PE"):
        fn = os.path.join(DATA_DIR, f"opt_{day}_{data['atm']}_{side}.csv")
        data[side].to_csv(fn, index=False)

# ═══════════════════════════════════════════════════════════════
#  BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  BACKTEST: VWAP ENGINE COMPARISON")
print("=" * 70)


def compute_session_vwap(df, day):
    """Compute session VWAP for a given day from 15m bars."""
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    day_df = df[df['date'].dt.date == day]
    if len(day_df) < 1:
        return None, None
    tp = (day_df['high'] + day_df['low'] + day_df['close']) / 3
    vol = day_df['volume'] if 'volume' in day_df.columns else pd.Series([1]*len(day_df), index=day_df.index)
    cum_vol = vol.cumsum().replace(0, np.nan)
    vwap_series = (tp * vol).cumsum() / cum_vol
    return day_df, vwap_series


def compute_option_vwap_at_bar(opt_df, bar_idx):
    """Compute option VWAP up to bar_idx."""
    subset = opt_df.iloc[:bar_idx+1]
    if len(subset) < 1:
        return None
    tp = (subset['high'] + subset['low'] + subset['close']) / 3
    vol = subset['volume'] if 'volume' in subset.columns else pd.Series([1]*len(subset), index=subset.index)
    vol_sum = vol.sum()
    if vol_sum == 0:
        return float(tp.mean())
    return float((tp * vol).sum() / vol_sum)


# ── Run three strategies ──
results_old = []     # OLD: spot VWAP cross only (double: spot + option)
results_new = []     # NEW: futures VWAP primary (triple: fut + spot + option)
results_fast = []    # FAST: futures VWAP primary + spot LIVE price (Option B)

df_fut['date'] = pd.to_datetime(df_fut['date'])
df_spot['date'] = pd.to_datetime(df_spot['date'])

for day in trading_days:
    if day not in option_data:
        continue

    opt_info = option_data[day]

    # Get day's futures and spot data with running VWAP
    fut_day, fut_vwap_s = compute_session_vwap(df_fut, day)
    spot_day, spot_vwap_s = compute_session_vwap(df_spot, day)

    if fut_day is None or spot_day is None:
        continue
    if len(fut_day) < 3 or len(spot_day) < 3:
        continue

    # Align bars by time (both should have same 15m timestamps)
    fut_day = fut_day.reset_index(drop=True)
    spot_day = spot_day.reset_index(drop=True)
    fut_vwap_s = fut_vwap_s.reset_index(drop=True)
    spot_vwap_s = spot_vwap_s.reset_index(drop=True)

    n_bars = min(len(fut_day), len(spot_day))

    old_fired = False
    new_fired = False
    fast_fired = False

    for i in range(2, n_bars - 1):  # iloc[-2] = last closed bar
        # Skip first 2 bars (9:15, 9:30) — warmup
        bar_time = pd.to_datetime(fut_day['date'].iloc[i])
        if bar_time.hour < 9 or (bar_time.hour == 9 and bar_time.minute < 45):
            continue
        if bar_time.hour >= 15:
            continue

        # ── Futures bar (closed) ──
        f_bar = fut_day.iloc[i]
        fo, fh, fl, fc = float(f_bar['open']), float(f_bar['high']), float(f_bar['low']), float(f_bar['close'])
        f_rng = fh - fl
        if f_rng <= 0:
            continue
        f_body_pct = abs(fc - fo) / f_rng
        f_vwap = float(fut_vwap_s.iloc[i]) if i < len(fut_vwap_s) else None
        if f_vwap is None:
            continue

        # ── Spot bar (closed) ──
        s_bar = spot_day.iloc[i]
        so, sh, sl_v, sc = float(s_bar['open']), float(s_bar['high']), float(s_bar['low']), float(s_bar['close'])
        s_rng = sh - sl_v
        s_body_pct = abs(sc - so) / s_rng if s_rng > 0 else 0
        s_vwap = float(spot_vwap_s.iloc[i]) if i < len(spot_vwap_s) else None
        if s_vwap is None:
            continue

        # ── Next bar open = simulated entry price (for option) ──
        # Direction
        fut_bullish = fc > f_vwap
        fut_bearish = fc < f_vwap
        spot_bullish = sc > s_vwap
        spot_bearish = sc < s_vwap

        side_fut = 'CE' if fut_bullish else ('PE' if fut_bearish else None)
        side_spot = 'CE' if spot_bullish else ('PE' if spot_bearish else None)

        if side_fut is None:
            continue

        # ── Option VWAP check ──
        opt_side = side_fut
        opt_df = opt_info[opt_side]
        opt_df_dt = pd.to_datetime(opt_df['date'])
        # Find option bar matching this timestamp
        opt_mask = opt_df_dt == bar_time
        if not opt_mask.any():
            continue
        opt_idx = opt_mask.idxmax()
        opt_close = float(opt_df.loc[opt_idx, 'close'])
        opt_vwap = compute_option_vwap_at_bar(opt_df, opt_idx)
        if opt_vwap is None:
            continue

        opt_above_vwap = opt_close > opt_vwap  # CE above = bullish
        opt_below_vwap = opt_close < opt_vwap  # PE below = bearish
        opt_vwap_ok = opt_above_vwap if opt_side == 'CE' else opt_below_vwap

        # ── Simulate P&L: entry at next bar's open, exit at session VWAP trail ──
        # Find next bar in option data
        if opt_idx + 1 >= len(opt_df):
            continue
        entry_price = float(opt_df.loc[opt_idx + 1, 'open'])
        if entry_price <= 0:
            continue

        # Simple exit: track forward bars, exit when option close < option VWAP
        # or at EOD (last bar)
        exit_price = entry_price
        peak_price = entry_price
        exit_reason = "EOD"
        for j in range(int(opt_idx) + 1, len(opt_df)):
            bar_p = float(opt_df.loc[j, 'close'])
            if bar_p > peak_price:
                peak_price = bar_p
            j_vwap = compute_option_vwap_at_bar(opt_df, j)
            if j_vwap and bar_p < j_vwap:
                exit_price = bar_p
                exit_reason = "VWAP_TRAIL"
                break
            exit_price = bar_p

        pnl = round(exit_price - entry_price, 2)
        peak_pnl = round(peak_price - entry_price, 2)

        trade_rec = {
            "date": str(day),
            "time": bar_time.strftime("%H:%M"),
            "side": opt_side,
            "atm": opt_info["atm"],
            "entry": entry_price,
            "exit": exit_price,
            "pnl": pnl,
            "peak": peak_pnl,
            "exit_reason": exit_reason,
            "fut_close": fc,
            "fut_vwap": round(f_vwap, 1),
            "fut_body": round(f_body_pct * 100, 1),
            "spot_close": sc,
            "spot_vwap": round(s_vwap, 1),
        }

        # ── OLD: spot VWAP cross + body >= 50% + option VWAP ──
        if not old_fired and side_spot and s_body_pct >= VWAP_BODY_MIN_PCT and opt_vwap_ok:
            results_old.append({**trade_rec, "strategy": "OLD_DOUBLE"})
            old_fired = True

        # ── NEW: futures VWAP primary + spot bar confirm + option VWAP ──
        if not new_fired and f_body_pct >= VWAP_BODY_MIN_PCT and side_spot == side_fut and opt_vwap_ok:
            results_new.append({**trade_rec, "strategy": "NEW_TRIPLE"})
            new_fired = True

        # ── FAST: futures VWAP primary + spot LIVE price (not bar close) ──
        # Simulate: spot's current bar high (CE) or low (PE) crossed VWAP
        # This approximates "spot live price crossed VWAP mid-bar"
        if not fast_fired and f_body_pct >= VWAP_BODY_MIN_PCT and opt_vwap_ok:
            spot_live_cross = False
            if side_fut == 'CE' and sh > s_vwap:  # spot high touched above VWAP
                spot_live_cross = True
            elif side_fut == 'PE' and sl_v < s_vwap:  # spot low touched below VWAP
                spot_live_cross = True
            if spot_live_cross:
                results_fast.append({**trade_rec, "strategy": "FAST_OPTB"})
                fast_fired = True

# ═══════════════════════════════════════════════════════════════
#  RESULTS
# ═══════════════════════════════════════════════════════════════
def print_summary(name, trades):
    if not trades:
        print(f"\n  {name}: 0 trades")
        return
    df = pd.DataFrame(trades)
    total_pnl = df['pnl'].sum()
    wins = (df['pnl'] > 0).sum()
    losses = (df['pnl'] <= 0).sum()
    wr = wins / len(df) * 100
    avg_win = df[df['pnl'] > 0]['pnl'].mean() if wins > 0 else 0
    avg_loss = df[df['pnl'] <= 0]['pnl'].mean() if losses > 0 else 0
    max_win = df['pnl'].max()
    max_loss = df['pnl'].min()
    avg_peak = df['peak'].mean()
    print(f"\n  {name}:")
    print(f"  {'─' * 50}")
    print(f"  Trades    : {len(df)}")
    print(f"  Total PnL : {total_pnl:+.1f} pts")
    print(f"  Win Rate  : {wr:.1f}% ({wins}W / {losses}L)")
    print(f"  Avg Win   : +{avg_win:.1f} pts")
    print(f"  Avg Loss  : {avg_loss:.1f} pts")
    print(f"  Max Win   : +{max_win:.1f} pts")
    print(f"  Max Loss  : {max_loss:.1f} pts")
    print(f"  Avg Peak  : +{avg_peak:.1f} pts")
    print(f"  {'─' * 50}")
    # Print each trade
    print(f"  {'Date':<12} {'Time':<6} {'Side':<4} {'Entry':>8} {'Exit':>8} {'PnL':>8} {'Peak':>8} {'Reason':<12} {'FUT':>10} {'SPOT':>10}")
    for _, t in df.iterrows():
        print(f"  {t['date']:<12} {t['time']:<6} {t['side']:<4} {t['entry']:>8.1f} {t['exit']:>8.1f} {t['pnl']:>+8.1f} {t['peak']:>+8.1f} {t['exit_reason']:<12} {t['fut_close']:>10.0f} {t['spot_close']:>10.0f}")


print("\n" + "=" * 70)
print("  RESULTS COMPARISON")
print("=" * 70)

print_summary("OLD (Spot VWAP double confirmation — V2.5.12)", results_old)
print_summary("NEW (Futures VWAP triple confirmation — V2.5.14)", results_new)
print_summary("FAST (Futures VWAP + spot live price — Option B)", results_fast)

# ── Head-to-head: timing comparison ──
print("\n" + "=" * 70)
print("  TIMING COMPARISON: NEW vs FAST (same-day trades)")
print("=" * 70)
new_by_date = {t['date']: t for t in results_new}
fast_by_date = {t['date']: t for t in results_fast}
common_dates = set(new_by_date.keys()) & set(fast_by_date.keys())
if common_dates:
    print(f"  {'Date':<12} {'NEW time':<8} {'FAST time':<8} {'NEW entry':>10} {'FAST entry':>10} {'Diff':>8} {'NEW pnl':>8} {'FAST pnl':>8}")
    total_entry_diff = 0
    total_pnl_diff = 0
    for d in sorted(common_dates):
        n = new_by_date[d]
        f = fast_by_date[d]
        entry_diff = round(f['entry'] - n['entry'], 1)
        pnl_diff = round(f['pnl'] - n['pnl'], 1)
        total_entry_diff += entry_diff
        total_pnl_diff += pnl_diff
        print(f"  {d:<12} {n['time']:<8} {f['time']:<8} {n['entry']:>10.1f} {f['entry']:>10.1f} {entry_diff:>+8.1f} {n['pnl']:>+8.1f} {f['pnl']:>+8.1f}")
    print(f"  {'─' * 78}")
    print(f"  {'TOTAL':<30} {'':>20} {total_entry_diff:>+8.1f} {'':>8} {total_pnl_diff:>+8.1f}")
    print(f"  Average entry improvement: {total_entry_diff/len(common_dates):+.1f} pts")
    print(f"  Average PnL improvement:   {total_pnl_diff/len(common_dates):+.1f} pts")
else:
    print("  No common trading days to compare.")

# Save full results
all_results = results_old + results_new + results_fast
if all_results:
    df_all = pd.DataFrame(all_results)
    fn = os.path.join(DATA_DIR, "backtest_vwap_comparison.csv")
    df_all.to_csv(fn, index=False)
    print(f"\n  Full results saved to: {fn}")

print("\n" + "=" * 70)
print("  DONE")
print("=" * 70)
