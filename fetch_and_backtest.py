"""
ORION V2.5.14 — Backtest VWAP triple confirmation using saved daily_option_data
Run on PythonAnywhere after auto_login.py refreshes the Kite token.

Reads from: daily_option_data/YYYY-MM-DD/ (saved by bot's EOD capture)
  - nifty_15m.csv          (Nifty spot 15m)
  - nifty_fut_15m.csv      (Nifty futures 15m — if saved by updated bot)
  - CE/<strike>.csv        (option data with tf=15m rows)
  - PE/<strike>.csv        (option data with tf=15m rows)

If nifty_fut_15m.csv not found locally, fetches from Kite as fallback.

Compares 3 strategies:
  OLD:  Spot VWAP cross (double confirmation — V2.5.12)
  NEW:  Futures VWAP primary + spot bar close + option VWAP (triple — V2.5.14)
  FAST: Futures VWAP primary + spot live price + option VWAP (Option B)

Usage:
    python3 auto_login.py
    python3 fetch_and_backtest.py
"""
import sys, os, time, json
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

try:
    profile = kite.profile()
    print(f"✅ Kite connected: {profile['user_name']}")
except Exception as e:
    print(f"❌ Kite auth failed: {e}")
    print("Run auto_login.py first.")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_option_data")
NIFTY_SPOT_TOKEN = 256265
VWAP_BODY_MIN_PCT = 0.50
LOT_SIZE = 75
LOTS = 2
QTY = LOT_SIZE * LOTS
HARDSL_PCT = 0.18
PREMIUM_MIN = 30
PREMIUM_MAX_CE = 180
PREMIUM_MAX_PE = 300

# ═══════════════════════════════════════════════════════════════
#  STEP 1: Discover available trading days from daily_option_data
# ═══════════════════════════════════════════════════════════════
print(f"\n[1/3] Scanning {DATA_ROOT} for saved trading days...")

if not os.path.isdir(DATA_ROOT):
    print(f"❌ Folder not found: {DATA_ROOT}")
    print("Run Optiondata_1.py after market close to capture data first.")
    sys.exit(1)

all_days = []
for entry in sorted(os.listdir(DATA_ROOT)):
    day_dir = os.path.join(DATA_ROOT, entry)
    if not os.path.isdir(day_dir):
        continue
    try:
        day = datetime.strptime(entry, "%Y-%m-%d").date()
    except ValueError:
        continue
    # Check required files exist
    spot_csv = os.path.join(day_dir, "nifty_15m.csv")
    ce_dir = os.path.join(day_dir, "CE")
    pe_dir = os.path.join(day_dir, "PE")
    meta_file = os.path.join(day_dir, "_meta.json")

    missing = []
    if not os.path.isfile(spot_csv):
        missing.append("nifty_15m.csv")
    if not os.path.isdir(ce_dir):
        missing.append("CE/")
    if not os.path.isdir(pe_dir):
        missing.append("PE/")

    if missing:
        print(f"   {entry} ⚠️ SKIPPED — missing: {', '.join(missing)}")
        continue

    # Read meta for ATM info
    atm = None
    if os.path.isfile(meta_file):
        try:
            with open(meta_file) as f:
                meta = json.load(f)
            atm = meta.get("atm_at_open") or meta.get("atm")
        except Exception:
            pass

    # Count CE/PE strike files
    ce_files = [f for f in os.listdir(ce_dir) if f.endswith('.csv')]
    pe_files = [f for f in os.listdir(pe_dir) if f.endswith('.csv')]

    all_days.append({
        "date": day, "dir": day_dir, "spot_csv": spot_csv,
        "ce_dir": ce_dir, "pe_dir": pe_dir, "atm": atm,
        "ce_count": len(ce_files), "pe_count": len(pe_files),
    })
    print(f"   {entry} ATM={atm or '?'} CE_strikes={len(ce_files)} PE_strikes={len(pe_files)} ✅")

print(f"\n   ✅ {len(all_days)} trading days with complete data")

if not all_days:
    print("❌ No trading days found. Run Optiondata_1.py after market close.")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
#  STEP 2: Load Nifty futures 15m (local first, Kite fallback)
# ═══════════════════════════════════════════════════════════════
print("\n[2/3] Loading Nifty FUTURES 15m data...")

# Try loading from local saved files first
fut_local_frames = []
days_needing_kite = []
for day_info in all_days:
    fut_csv = os.path.join(day_info["dir"], "nifty_fut_15m.csv")
    if os.path.isfile(fut_csv):
        df_tmp = pd.read_csv(fut_csv)
        df_tmp['date'] = pd.to_datetime(df_tmp['date'])
        fut_local_frames.append(df_tmp)
        print(f"   {day_info['date']} — loaded from local ({len(df_tmp)} bars)")
    else:
        days_needing_kite.append(day_info)
        print(f"   {day_info['date']} — nifty_fut_15m.csv not found, will fetch from Kite")

df_fut = pd.concat(fut_local_frames, ignore_index=True) if fut_local_frames else pd.DataFrame()

# Fetch missing days from Kite
if days_needing_kite:
    print(f"   Fetching {len(days_needing_kite)} days from Kite...")
    insts = kite.instruments("NFO")
    today = date.today()
    nifty_futs = [i for i in insts if i["name"] == "NIFTY"
                  and i["instrument_type"] == "FUT"
                  and i["expiry"] >= today]
    if not nifty_futs:
        print("   ⚠️ No Nifty FUT found — days without local futures data will be skipped")
    else:
        fut = sorted(nifty_futs, key=lambda x: x["expiry"])[0]
        NIFTY_FUT_TOKEN = fut["instrument_token"]
        print(f"   FUT token: {NIFTY_FUT_TOKEN}, expiry: {fut['expiry']}, sym: {fut['tradingsymbol']}")
        first_day = days_needing_kite[0]["date"]
        last_day = days_needing_kite[-1]["date"]
        frm = datetime.combine(first_day, datetime.min.time())
        to = datetime.combine(last_day, datetime.max.time())
        fut_15m = kite.historical_data(NIFTY_FUT_TOKEN, frm, to, "15minute")
        df_kite_fut = pd.DataFrame(fut_15m)
        df_kite_fut['date'] = pd.to_datetime(df_kite_fut['date'])
        df_fut = pd.concat([df_fut, df_kite_fut], ignore_index=True) if len(df_fut) > 0 else df_kite_fut
        print(f"   ✅ {len(df_kite_fut)} futures bars fetched from Kite")

if len(df_fut) == 0:
    print("❌ No futures data available (local or Kite)")
    sys.exit(1)

df_fut = df_fut.sort_values('date').reset_index(drop=True)
print(f"   ✅ Total: {len(df_fut)} futures bars")

# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def compute_session_vwap_series(df):
    """Return running VWAP series for today's bars (cumulative from first bar).
    If volume is all zeros (e.g. Nifty index), falls back to cumulative typical price average."""
    tp = (df['high'] + df['low'] + df['close']) / 3
    vol = df['volume'] if 'volume' in df.columns else pd.Series([1]*len(df), index=df.index)
    if vol.sum() == 0:
        return tp.expanding().mean()
    cum_vol = vol.cumsum().replace(0, np.nan)
    return (tp * vol).cumsum() / cum_vol


def load_option_15m(side_dir, atm_strike):
    """Load 15m option data for ATM strike from saved CSV."""
    csv_path = os.path.join(side_dir, f"{int(atm_strike)}.csv")
    if not os.path.isfile(csv_path):
        return None
    df = pd.read_csv(csv_path)
    # Filter to 15m rows only (file contains 5m + 15m + 1h with 'tf' column)
    if 'tf' in df.columns:
        df = df[df['tf'] == '15m'].copy()
    if len(df) < 3:
        return None
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    return df


def compute_option_vwap_at_bar(opt_df, bar_idx):
    """Compute option VWAP from start up to bar_idx (inclusive)."""
    subset = opt_df.iloc[:bar_idx+1]
    if len(subset) < 1:
        return None
    tp = (subset['high'] + subset['low'] + subset['close']) / 3
    vol = subset['volume'] if 'volume' in subset.columns else pd.Series([1]*len(subset), index=subset.index)
    vol_sum = vol.sum()
    if vol_sum == 0:
        return float(tp.mean())
    return float((tp * vol).sum() / vol_sum)


def simulate_trade(opt_df, entry_idx, entry_price):
    """Simulate trade forward from entry_idx. Exit on VWAP trail / HARDSL / EOD.
    Returns (exit_price, peak_price, exit_reason, exit_time, bars_held)."""
    peak = entry_price
    for j in range(int(entry_idx), len(opt_df)):
        bar_c = float(opt_df.loc[j, 'close'])
        bar_h = float(opt_df.loc[j, 'high'])
        bar_time = pd.to_datetime(opt_df.loc[j, 'date'])

        if bar_h > peak:
            peak = bar_h

        # HARDSL: -18% of entry
        hardsl = entry_price * (1 - HARDSL_PCT)
        if bar_c <= hardsl:
            return round(hardsl, 2), round(peak, 2), "HARDSL_-18%", bar_time.strftime("%H:%M"), j - entry_idx + 1

        # VWAP trail: option close < option VWAP
        j_vwap = compute_option_vwap_at_bar(opt_df, j)
        if j_vwap and bar_c < j_vwap:
            return round(bar_c, 2), round(peak, 2), "VWAP_TRAIL", bar_time.strftime("%H:%M"), j - entry_idx + 1

        # Force close 15:15+
        if bar_time.hour >= 15 and bar_time.minute >= 15:
            return round(bar_c, 2), round(peak, 2), "FORCE_CLOSE", bar_time.strftime("%H:%M"), j - entry_idx + 1

    last_c = float(opt_df.iloc[-1]['close'])
    return round(last_c, 2), round(peak, 2), "EOD", "15:30", len(opt_df) - entry_idx


# ═══════════════════════════════════════════════════════════════
#  STEP 3: BACKTEST
# ═══════════════════════════════════════════════════════════════
print(f"\n[3/3] Running backtest...")
print("=" * 90)
print("  BACKTEST: VWAP ENGINE COMPARISON (OLD double vs NEW triple vs FAST option-B)")
print(f"  Config: LOT_SIZE={LOT_SIZE} × LOTS={LOTS} = QTY={QTY} | HARDSL={HARDSL_PCT*100:.0f}%")
print("=" * 90)

results = {"OLD": [], "NEW": [], "FAST": []}

for day_info in all_days:
    day = day_info["date"]
    day_dir = day_info["dir"]

    print(f"\n{'─'*90}")
    print(f"  📅 {day}")
    print(f"{'─'*90}")

    # ── Load spot 15m ──
    try:
        df_spot = pd.read_csv(day_info["spot_csv"])
        df_spot['date'] = pd.to_datetime(df_spot['date'])
    except Exception as e:
        print(f"  ⚠️ SKIPPED — error reading nifty_15m.csv: {e}")
        continue

    # Filter to this day only
    df_spot_day = df_spot[df_spot['date'].dt.date == day].copy().reset_index(drop=True)
    if len(df_spot_day) < 3:
        print(f"  ⚠️ SKIPPED — insufficient spot bars ({len(df_spot_day)})")
        continue

    # ── Load futures 15m for this day ──
    df_fut_day = df_fut[df_fut['date'].dt.date == day].copy().reset_index(drop=True)
    if len(df_fut_day) < 3:
        print(f"  ⚠️ SKIPPED — insufficient futures bars ({len(df_fut_day)})")
        continue

    # ── Compute running VWAP ──
    spot_vwap_s = compute_session_vwap_series(df_spot_day)
    fut_vwap_s = compute_session_vwap_series(df_fut_day)

    # ── Determine ATM ──
    if day_info["atm"]:
        atm = int(day_info["atm"])
    else:
        first_close = float(df_spot_day.iloc[0]['close'])
        atm = int(round(first_close / 50) * 50)

    # ── Load ATM option data ──
    opt_ce = load_option_15m(day_info["ce_dir"], atm)
    opt_pe = load_option_15m(day_info["pe_dir"], atm)

    if opt_ce is None and opt_pe is None:
        # Try ATM ± 50
        for alt_atm in [atm - 50, atm + 50, atm - 100, atm + 100]:
            if opt_ce is None:
                opt_ce = load_option_15m(day_info["ce_dir"], alt_atm)
            if opt_pe is None:
                opt_pe = load_option_15m(day_info["pe_dir"], alt_atm)
            if opt_ce is not None and opt_pe is not None:
                atm = alt_atm
                break

    ce_status = f"{len(opt_ce)} bars" if opt_ce is not None else "NOT FOUND"
    pe_status = f"{len(opt_pe)} bars" if opt_pe is not None else "NOT FOUND"
    print(f"  ATM={atm}  FUT_bars={len(df_fut_day)}  SPOT_bars={len(df_spot_day)}  "
          f"CE_15m={ce_status}  PE_15m={pe_status}")

    if opt_ce is None and opt_pe is None:
        print(f"  ⚠️ SKIPPED — no CE or PE option data for ATM={atm}")
        continue

    n_bars = min(len(df_fut_day), len(df_spot_day))
    fired = {"OLD": False, "NEW": False, "FAST": False}

    for i in range(2, n_bars):
        bar_time = pd.to_datetime(df_fut_day['date'].iloc[i])
        if bar_time.hour < 9 or (bar_time.hour == 9 and bar_time.minute < 45):
            continue
        if bar_time.hour >= 15:
            continue

        # ── Futures closed bar ──
        f_bar = df_fut_day.iloc[i]
        fo, fh, fl, fc = float(f_bar['open']), float(f_bar['high']), float(f_bar['low']), float(f_bar['close'])
        f_rng = fh - fl
        if f_rng <= 0:
            continue
        f_body_pct = abs(fc - fo) / f_rng
        f_vwap = float(fut_vwap_s.iloc[i])

        # ── Spot closed bar ──
        s_bar = df_spot_day.iloc[i]
        so, sh, sl_v, sc = float(s_bar['open']), float(s_bar['high']), float(s_bar['low']), float(s_bar['close'])
        s_rng = sh - sl_v
        s_body_pct = abs(sc - so) / s_rng if s_rng > 0 else 0
        s_vwap = float(spot_vwap_s.iloc[i])

        # ── Direction ──
        fut_bull = fc > f_vwap
        fut_bear = fc < f_vwap
        spot_bull = sc > s_vwap
        spot_bear = sc < s_vwap
        side_fut = 'CE' if fut_bull else ('PE' if fut_bear else None)
        side_spot = 'CE' if spot_bull else ('PE' if spot_bear else None)

        if side_fut is None and side_spot is None:
            continue

        # ── Try to fire a trade for a given strategy ──
        def try_fire(strategy, opt_side, reason_prefix):
            if fired[strategy]:
                return

            opt_df = opt_ce if opt_side == 'CE' else opt_pe
            if opt_df is None:
                print(f"  [{strategy}] {bar_time.strftime('%H:%M')} {opt_side} REJECTED — "
                      f"no {opt_side} option data for ATM={atm}")
                return

            # Find matching bar in option data
            opt_mask = opt_df['date'] == bar_time
            if not opt_mask.any():
                # Try ±1 min tolerance
                for delta_sec in [60, -60, 120, -120]:
                    alt_time = bar_time + timedelta(seconds=delta_sec)
                    opt_mask = opt_df['date'] == alt_time
                    if opt_mask.any():
                        break
                if not opt_mask.any():
                    return  # silently skip — timing mismatch

            opt_idx = opt_mask.idxmax()
            opt_close = float(opt_df.loc[opt_idx, 'close'])
            opt_vwap = compute_option_vwap_at_bar(opt_df, opt_idx)

            if opt_vwap is None:
                print(f"  [{strategy}] {bar_time.strftime('%H:%M')} {opt_side} REJECTED — "
                      f"cannot compute option VWAP")
                return

            # Option VWAP gate
            opt_vwap_ok = (opt_close > opt_vwap) if opt_side == 'CE' else (opt_close < opt_vwap)
            if not opt_vwap_ok:
                print(f"  [{strategy}] {bar_time.strftime('%H:%M')} {opt_side} REJECTED — "
                      f"option VWAP failed: close={opt_close:.1f} vwap={opt_vwap:.1f} "
                      f"({'need above' if opt_side=='CE' else 'need below'})")
                return

            # Premium filter
            prem_max = PREMIUM_MAX_CE if opt_side == 'CE' else PREMIUM_MAX_PE
            if opt_close < PREMIUM_MIN or opt_close > prem_max:
                print(f"  [{strategy}] {bar_time.strftime('%H:%M')} {opt_side} REJECTED — "
                      f"premium {opt_close:.1f} out of range ({PREMIUM_MIN}-{prem_max})")
                return

            # Entry at next bar's open
            if opt_idx + 1 >= len(opt_df):
                return
            entry_price = float(opt_df.loc[opt_idx + 1, 'open'])
            if entry_price <= 0:
                return
            entry_time = pd.to_datetime(opt_df.loc[opt_idx + 1, 'date']).strftime("%H:%M")

            # Simulate trade
            exit_price, peak_price, exit_reason, exit_time, bars_held = simulate_trade(
                opt_df, opt_idx + 1, entry_price)

            pnl_pts = round(exit_price - entry_price, 2)
            pnl_rs = round(pnl_pts * QTY, 0)
            peak_pts = round(peak_price - entry_price, 2)
            icon = "✅" if pnl_pts > 0 else "❌"

            print(f"  [{strategy}] {icon} {opt_side} ENTRY {entry_time} @ ₹{entry_price:.1f} → "
                  f"EXIT {exit_time} @ ₹{exit_price:.1f} | "
                  f"PnL: {pnl_pts:+.1f}pts (₹{pnl_rs:+,.0f}) | Peak: +{peak_pts:.1f}pts | "
                  f"Reason: {exit_reason} | Bars: {bars_held}")
            print(f"           {reason_prefix}")

            results[strategy].append({
                "date": str(day), "entry_time": entry_time, "exit_time": exit_time,
                "side": opt_side, "atm": atm,
                "entry": entry_price, "exit": exit_price,
                "pnl_pts": pnl_pts, "pnl_rs": pnl_rs,
                "peak_pts": peak_pts, "exit_reason": exit_reason,
                "bars_held": bars_held, "win": "WIN" if pnl_pts > 0 else "LOSS",
                "fut_close": fc, "fut_vwap": round(f_vwap, 1),
                "fut_body_pct": round(f_body_pct * 100, 1),
                "spot_close": sc, "spot_vwap": round(s_vwap, 1),
                "spot_body_pct": round(s_body_pct * 100, 1),
                "opt_close": opt_close, "opt_vwap": round(opt_vwap, 1),
                "strategy": strategy,
            })
            fired[strategy] = True

        # ═══════════════════════════════════════════════════════════
        #  STRATEGY 1: OLD (Spot VWAP double — V2.5.12)
        # ═══════════════════════════════════════════════════════════
        if not fired["OLD"] and side_spot and s_body_pct >= VWAP_BODY_MIN_PCT:
            reason = (f"SPOT {sc:.0f}{'>' if spot_bull else '<'}{s_vwap:.0f} "
                      f"body={s_body_pct*100:.0f}%")
            try_fire("OLD", side_spot, reason)
        elif not fired["OLD"] and side_spot and s_body_pct < VWAP_BODY_MIN_PCT:
            if i % 4 == 0:
                print(f"  [OLD]  {bar_time.strftime('%H:%M')} {side_spot} REJECTED — "
                      f"spot body weak: {s_body_pct*100:.0f}% (need ≥50%) "
                      f"spot={sc:.0f} vwap={s_vwap:.0f}")

        # ═══════════════════════════════════════════════════════════
        #  STRATEGY 2: NEW (Futures VWAP triple — V2.5.14)
        # ═══════════════════════════════════════════════════════════
        if not fired["NEW"] and side_fut and f_body_pct >= VWAP_BODY_MIN_PCT:
            if side_spot != side_fut:
                print(f"  [NEW]  {bar_time.strftime('%H:%M')} {side_fut} REJECTED — "
                      f"spot disagrees: fut={side_fut}(fc={fc:.0f} fvwap={f_vwap:.0f}) "
                      f"spot={side_spot}(sc={sc:.0f} svwap={s_vwap:.0f})")
            else:
                reason = (f"FUT {fc:.0f}{'>' if fut_bull else '<'}{f_vwap:.0f} body={f_body_pct*100:.0f}% | "
                          f"SPOT {sc:.0f}{'>' if spot_bull else '<'}{s_vwap:.0f}")
                try_fire("NEW", side_fut, reason)
        elif not fired["NEW"] and side_fut and f_body_pct < VWAP_BODY_MIN_PCT:
            if i % 4 == 0:
                print(f"  [NEW]  {bar_time.strftime('%H:%M')} {side_fut} REJECTED — "
                      f"futures body weak: {f_body_pct*100:.0f}% (need ≥50%) "
                      f"fut={fc:.0f} vwap={f_vwap:.0f}")

        # ═══════════════════════════════════════════════════════════
        #  STRATEGY 3: FAST (Futures VWAP + spot LIVE price — Option B)
        # ═══════════════════════════════════════════════════════════
        if not fired["FAST"] and side_fut and f_body_pct >= VWAP_BODY_MIN_PCT:
            spot_live_cross = False
            if side_fut == 'CE' and sh > s_vwap:
                spot_live_cross = True
            elif side_fut == 'PE' and sl_v < s_vwap:
                spot_live_cross = True
            if not spot_live_cross:
                print(f"  [FAST] {bar_time.strftime('%H:%M')} {side_fut} REJECTED — "
                      f"spot live didn't cross VWAP: "
                      f"{'high' if side_fut=='CE' else 'low'}="
                      f"{sh if side_fut=='CE' else sl_v:.0f} vwap={s_vwap:.0f}")
            else:
                reason = (f"FUT {fc:.0f}{'>' if fut_bull else '<'}{f_vwap:.0f} body={f_body_pct*100:.0f}% | "
                          f"SPOT live {'high' if side_fut=='CE' else 'low'}="
                          f"{sh if side_fut=='CE' else sl_v:.0f} > VWAP {s_vwap:.0f}")
                try_fire("FAST", side_fut, reason)

    # ── Day summary ──
    for strat in ("OLD", "NEW", "FAST"):
        if not fired[strat]:
            print(f"  [{strat}] No signal fired today")


# ═══════════════════════════════════════════════════════════════
#  DAILY BREAKDOWN
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("  DAILY BREAKDOWN BY STRATEGY")
print("=" * 90)

for strat in ("OLD", "NEW", "FAST"):
    trades = results[strat]
    if not trades:
        print(f"\n  {strat}: 0 trades")
        continue
    df_s = pd.DataFrame(trades)
    print(f"\n  ── {strat} ──")
    print(f"  {'Date':<12} {'Time':<6} {'Side':<4} {'Entry':>7} {'Exit':>7} "
          f"{'PnL pts':>8} {'PnL ₹':>10} {'Peak':>6} {'Exit Reason':<14} {'W/L':<4}")
    print(f"  {'─'*85}")
    running_pts = 0
    running_rs = 0
    for _, t in df_s.iterrows():
        running_pts += t['pnl_pts']
        running_rs += t['pnl_rs']
        icon = "✅" if t['pnl_pts'] > 0 else "❌"
        print(f"  {t['date']:<12} {t['entry_time']:<6} {t['side']:<4} "
              f"{t['entry']:>7.1f} {t['exit']:>7.1f} "
              f"{t['pnl_pts']:>+8.1f} {t['pnl_rs']:>+10,.0f} "
              f"{t['peak_pts']:>+6.1f} {t['exit_reason']:<14} {icon}")
    print(f"  {'─'*85}")
    print(f"  {'RUNNING TOTAL':<35} {running_pts:>+8.1f} {running_rs:>+10,.0f}")


# ═══════════════════════════════════════════════════════════════
#  FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("  FINAL SUMMARY")
print("=" * 90)

label_map = {
    "OLD":  "OLD  (Spot VWAP double — V2.5.12)",
    "NEW":  "NEW  (FUT VWAP triple — V2.5.14)",
    "FAST": "FAST (FUT VWAP + spot live — Opt B)",
}

for strat in ("OLD", "NEW", "FAST"):
    trades = results[strat]
    if not trades:
        print(f"\n  {label_map[strat]}: 0 trades")
        continue
    df_s = pd.DataFrame(trades)
    total_pts = df_s['pnl_pts'].sum()
    total_rs = df_s['pnl_rs'].sum()
    wins = (df_s['pnl_pts'] > 0).sum()
    losses = (df_s['pnl_pts'] <= 0).sum()
    wr = wins / len(df_s) * 100
    avg_win = df_s[df_s['pnl_pts'] > 0]['pnl_pts'].mean() if wins > 0 else 0
    avg_loss = df_s[df_s['pnl_pts'] <= 0]['pnl_pts'].mean() if losses > 0 else 0
    avg_win_rs = df_s[df_s['pnl_rs'] > 0]['pnl_rs'].mean() if wins > 0 else 0
    avg_loss_rs = df_s[df_s['pnl_rs'] <= 0]['pnl_rs'].mean() if losses > 0 else 0
    max_win = df_s['pnl_pts'].max()
    max_loss = df_s['pnl_pts'].min()
    avg_peak = df_s['peak_pts'].mean()
    avg_bars = df_s['bars_held'].mean()

    print(f"\n  {label_map[strat]}:")
    print(f"  {'─'*55}")
    print(f"  Trades      : {len(df_s)}")
    print(f"  Total PnL   : {total_pts:+.1f} pts  |  ₹{total_rs:+,.0f}")
    print(f"  Win Rate    : {wr:.1f}% ({wins}W / {losses}L)")
    print(f"  Avg Win     : +{avg_win:.1f} pts  |  ₹{avg_win_rs:+,.0f}")
    print(f"  Avg Loss    : {avg_loss:.1f} pts  |  ₹{avg_loss_rs:+,.0f}")
    print(f"  Best Trade  : +{max_win:.1f} pts")
    print(f"  Worst Trade : {max_loss:.1f} pts")
    print(f"  Avg Peak    : +{avg_peak:.1f} pts")
    print(f"  Avg Bars    : {avg_bars:.1f}")
    print(f"  {'─'*55}")


# ═══════════════════════════════════════════════════════════════
#  HEAD-TO-HEAD: TIMING (NEW vs FAST)
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 90)
print("  TIMING: NEW (wait for spot bar close) vs FAST (spot live price)")
print("=" * 90)

new_by_date = {t['date']: t for t in results["NEW"]}
fast_by_date = {t['date']: t for t in results["FAST"]}
common_dates = sorted(set(new_by_date.keys()) & set(fast_by_date.keys()))

if common_dates:
    print(f"  {'Date':<12} {'NEW':>6} {'FAST':>6} {'NEW ₹':>10} {'FAST ₹':>10} "
          f"{'Entry Δ':>8} {'PnL Δ pts':>10} {'PnL Δ ₹':>10}")
    print(f"  {'─'*80}")
    total_entry_diff = 0
    total_pnl_diff_pts = 0
    total_pnl_diff_rs = 0
    for d in common_dates:
        n = new_by_date[d]
        f = fast_by_date[d]
        entry_diff = round(f['entry'] - n['entry'], 1)
        pnl_diff_pts = round(f['pnl_pts'] - n['pnl_pts'], 1)
        pnl_diff_rs = round(f['pnl_rs'] - n['pnl_rs'], 0)
        total_entry_diff += entry_diff
        total_pnl_diff_pts += pnl_diff_pts
        total_pnl_diff_rs += pnl_diff_rs
        print(f"  {d:<12} {n['entry_time']:>6} {f['entry_time']:>6} "
              f"{n['pnl_rs']:>+10,.0f} {f['pnl_rs']:>+10,.0f} "
              f"{entry_diff:>+8.1f} {pnl_diff_pts:>+10.1f} {pnl_diff_rs:>+10,.0f}")
    print(f"  {'─'*80}")
    nc = len(common_dates)
    print(f"  TOTAL ({nc} common days){' '*20} "
          f"{total_entry_diff:>+8.1f} {total_pnl_diff_pts:>+10.1f} {total_pnl_diff_rs:>+10,.0f}")
    print(f"  AVG per trade{' '*26} "
          f"{total_entry_diff/nc:>+8.1f} {total_pnl_diff_pts/nc:>+10.1f} {total_pnl_diff_rs/nc:>+10,.0f}")
    print(f"\n  → Positive entry Δ = FAST entered HIGHER (worse for CE, better for PE)")
    print(f"  → Positive PnL Δ = FAST made MORE money")
else:
    print("  No common trading days to compare.")

only_new = sorted(set(new_by_date.keys()) - set(fast_by_date.keys()))
only_fast = sorted(set(fast_by_date.keys()) - set(new_by_date.keys()))
if only_new:
    print(f"\n  Dates with NEW signal but NO FAST signal: {', '.join(only_new)}")
if only_fast:
    print(f"  Dates with FAST signal but NO NEW signal: {', '.join(only_fast)}")

# Save results CSV
all_trades = []
for strat in ("OLD", "NEW", "FAST"):
    all_trades.extend(results[strat])
if all_trades:
    out_dir = os.path.join(DATA_ROOT, "_backtest_results")
    os.makedirs(out_dir, exist_ok=True)
    fn = os.path.join(out_dir, f"vwap_comparison_{today}.csv")
    pd.DataFrame(all_trades).to_csv(fn, index=False)
    print(f"\n  📊 Full results CSV: {fn}")

print("\n" + "=" * 90)
print(f"  Config: LOT_SIZE={LOT_SIZE} × LOTS={LOTS} = QTY={QTY}")
print(f"  VWAP body min: {VWAP_BODY_MIN_PCT*100:.0f}% | HARDSL: {HARDSL_PCT*100:.0f}%")
print(f"  Premium range: CE {PREMIUM_MIN}-{PREMIUM_MAX_CE} | PE {PREMIUM_MIN}-{PREMIUM_MAX_PE}")
print(f"  Days tested: {len(all_days)} | Data source: {DATA_ROOT}")
print("=" * 90)
print("  DONE ✅")
