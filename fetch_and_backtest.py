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
LOT_SIZE = 75
LOTS = 2
QTY = LOT_SIZE * LOTS

# ═══════════════════════════════════════════════════════════════
#  DATA FETCH
# ═══════════════════════════════════════════════════════════════

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
nifty_futs_sorted = sorted(nifty_futs, key=lambda x: x["expiry"])
fut = nifty_futs_sorted[0]
NIFTY_FUT_TOKEN = fut["instrument_token"]
print(f"   FUT token: {NIFTY_FUT_TOKEN}, expiry: {fut['expiry']}, sym: {fut['tradingsymbol']}")

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
df_spot['date'] = pd.to_datetime(df_spot['date'])
trading_days = sorted(df_spot['date'].dt.date.unique())
print(f"   {len(trading_days)} trading days found")

option_data = {}

for day in trading_days:
    day_spot = df_spot[df_spot['date'].dt.date == day]
    if len(day_spot) < 2:
        print(f"   {day} ⚠️ SKIPPED — only {len(day_spot)} spot bars")
        continue
    first_close = float(day_spot.iloc[0]['close'])
    atm = int(round(first_close / 50) * 50)

    relevant_opts = [i for i in nifty_options
                     if i["strike"] == atm and i["expiry"] >= day]
    if not relevant_opts:
        print(f"   {day} ⚠️ SKIPPED — no options found for ATM={atm}")
        continue
    nearest_expiry = min(i["expiry"] for i in relevant_opts)
    ce_opts = [i for i in relevant_opts if i["instrument_type"] == "CE" and i["expiry"] == nearest_expiry]
    pe_opts = [i for i in relevant_opts if i["instrument_type"] == "PE" and i["expiry"] == nearest_expiry]
    if not ce_opts or not pe_opts:
        print(f"   {day} ⚠️ SKIPPED — CE or PE not found for ATM={atm} exp={nearest_expiry}")
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
                "CE": pd.DataFrame(ce_data), "PE": pd.DataFrame(pe_data),
                "atm": atm, "ce_token": ce_token, "pe_token": pe_token,
                "ce_sym": ce_opts[0]["tradingsymbol"],
                "pe_sym": pe_opts[0]["tradingsymbol"],
            }
            print(f"   {day} ATM={atm} CE={ce_opts[0]['tradingsymbol']} PE={pe_opts[0]['tradingsymbol']} "
                  f"CE_bars={len(ce_data)} PE_bars={len(pe_data)} ✅")
        else:
            print(f"   {day} ⚠️ SKIPPED — empty option data (CE={len(ce_data or [])} PE={len(pe_data or [])})")
        time.sleep(0.3)
    except Exception as e:
        print(f"   {day} ❌ SKIPPED — API error: {e}")
        time.sleep(1)

print(f"\n   ✅ Option data fetched for {len(option_data)}/{len(trading_days)} trading days")

for day, data in option_data.items():
    for side in ("CE", "PE"):
        fn = os.path.join(DATA_DIR, f"opt_{day}_{data['atm']}_{side}.csv")
        data[side].to_csv(fn, index=False)

# ═══════════════════════════════════════════════════════════════
#  BACKTEST HELPERS
# ═══════════════════════════════════════════════════════════════

def compute_session_vwap(df, day):
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    day_df = df[df['date'].dt.date == day].copy()
    if len(day_df) < 1:
        return None, None
    tp = (day_df['high'] + day_df['low'] + day_df['close']) / 3
    vol = day_df['volume'] if 'volume' in day_df.columns else pd.Series([1]*len(day_df), index=day_df.index)
    cum_vol = vol.cumsum().replace(0, np.nan)
    vwap_series = (tp * vol).cumsum() / cum_vol
    return day_df, vwap_series


def compute_option_vwap_at_bar(opt_df, bar_idx):
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
    """Simulate trade from entry_idx forward. Exit on option VWAP trail or EOD.
    Returns (exit_price, peak_price, exit_reason, exit_time, bars_held)."""
    peak = entry_price
    for j in range(int(entry_idx), len(opt_df)):
        bar_c = float(opt_df.loc[j, 'close'])
        bar_h = float(opt_df.loc[j, 'high'])
        bar_time = pd.to_datetime(opt_df.loc[j, 'date'])
        if bar_h > peak:
            peak = bar_h
        # HARDSL: -18% of entry
        hardsl = entry_price * (1 - 0.18)
        if bar_c <= hardsl:
            return round(hardsl, 2), round(peak, 2), "HARDSL_-18%", bar_time.strftime("%H:%M"), j - entry_idx + 1
        # VWAP trail
        j_vwap = compute_option_vwap_at_bar(opt_df, j)
        if j_vwap and bar_c < j_vwap:
            return round(bar_c, 2), round(peak, 2), "VWAP_TRAIL", bar_time.strftime("%H:%M"), j - entry_idx + 1
        # Force close 15:15+
        if bar_time.hour >= 15 and bar_time.minute >= 15:
            return round(bar_c, 2), round(peak, 2), "FORCE_CLOSE", bar_time.strftime("%H:%M"), j - entry_idx + 1
    last_c = float(opt_df.iloc[-1]['close'])
    return round(last_c, 2), round(peak, 2), "EOD", "15:30", len(opt_df) - entry_idx


# ═══════════════════════════════════════════════════════════════
#  BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("  BACKTEST: VWAP ENGINE COMPARISON (OLD double vs NEW triple vs FAST option-B)")
print("=" * 90)

df_fut['date'] = pd.to_datetime(df_fut['date'])
df_spot['date'] = pd.to_datetime(df_spot['date'])

results = {"OLD": [], "NEW": [], "FAST": []}
daily_log = {"OLD": {}, "NEW": {}, "FAST": {}}

for day in trading_days:
    print(f"\n{'─'*90}")
    print(f"  📅 {day}")
    print(f"{'─'*90}")

    if day not in option_data:
        print(f"  ⚠️ SKIPPED — no option data available for this day")
        continue

    opt_info = option_data[day]
    fut_day, fut_vwap_s = compute_session_vwap(df_fut, day)
    spot_day, spot_vwap_s = compute_session_vwap(df_spot, day)

    if fut_day is None or len(fut_day) < 3:
        print(f"  ⚠️ SKIPPED — insufficient futures data ({0 if fut_day is None else len(fut_day)} bars)")
        continue
    if spot_day is None or len(spot_day) < 3:
        print(f"  ⚠️ SKIPPED — insufficient spot data ({0 if spot_day is None else len(spot_day)} bars)")
        continue

    print(f"  ATM={opt_info['atm']}  CE={opt_info['ce_sym']}  PE={opt_info['pe_sym']}")
    print(f"  FUT bars={len(fut_day)}  SPOT bars={len(spot_day)}  "
          f"CE_bars={len(opt_info['CE'])}  PE_bars={len(opt_info['PE'])}")

    fut_day = fut_day.reset_index(drop=True)
    spot_day = spot_day.reset_index(drop=True)
    fut_vwap_s = fut_vwap_s.reset_index(drop=True)
    spot_vwap_s = spot_vwap_s.reset_index(drop=True)
    n_bars = min(len(fut_day), len(spot_day))

    fired = {"OLD": False, "NEW": False, "FAST": False}

    for i in range(2, n_bars - 1):
        bar_time = pd.to_datetime(fut_day['date'].iloc[i])
        if bar_time.hour < 9 or (bar_time.hour == 9 and bar_time.minute < 45):
            continue
        if bar_time.hour >= 15:
            continue

        # ── Futures bar ──
        f_bar = fut_day.iloc[i]
        fo, fh, fl, fc = float(f_bar['open']), float(f_bar['high']), float(f_bar['low']), float(f_bar['close'])
        f_rng = fh - fl
        if f_rng <= 0:
            continue
        f_body_pct = abs(fc - fo) / f_rng
        f_vwap = float(fut_vwap_s.iloc[i]) if i < len(fut_vwap_s) else None
        if f_vwap is None:
            continue

        # ── Spot bar ──
        s_bar = spot_day.iloc[i]
        so, sh, sl_v, sc = float(s_bar['open']), float(s_bar['high']), float(s_bar['low']), float(s_bar['close'])
        s_rng = sh - sl_v
        s_body_pct = abs(sc - so) / s_rng if s_rng > 0 else 0
        s_vwap = float(spot_vwap_s.iloc[i]) if i < len(spot_vwap_s) else None
        if s_vwap is None:
            continue

        # ── Direction ──
        fut_bullish = fc > f_vwap
        fut_bearish = fc < f_vwap
        spot_bullish = sc > s_vwap
        spot_bearish = sc < s_vwap
        side_fut = 'CE' if fut_bullish else ('PE' if fut_bearish else None)
        side_spot = 'CE' if spot_bullish else ('PE' if spot_bearish else None)

        # ── Option data for the relevant side ──
        def try_trade(strategy, opt_side, reason_prefix):
            if fired[strategy]:
                return
            opt_df = opt_info[opt_side].copy()
            opt_df['date'] = pd.to_datetime(opt_df['date'])
            opt_mask = opt_df['date'] == bar_time
            if not opt_mask.any():
                return
            opt_idx = opt_mask.idxmax()
            opt_close = float(opt_df.loc[opt_idx, 'close'])
            opt_vwap = compute_option_vwap_at_bar(opt_df, opt_idx)
            if opt_vwap is None:
                return

            opt_vwap_ok = (opt_close > opt_vwap) if opt_side == 'CE' else (opt_close < opt_vwap)
            if not opt_vwap_ok:
                print(f"  [{strategy}] {bar_time.strftime('%H:%M')} {opt_side} REJECTED — "
                      f"option VWAP gate failed: opt_close={opt_close:.1f} opt_vwap={opt_vwap:.1f} "
                      f"({'need above' if opt_side=='CE' else 'need below'})")
                return

            # Premium filter: 30-180 CE, 30-300 PE
            prem_max = 180 if opt_side == 'CE' else 300
            if opt_close < 30 or opt_close > prem_max:
                print(f"  [{strategy}] {bar_time.strftime('%H:%M')} {opt_side} REJECTED — "
                      f"premium out of range: {opt_close:.1f} (need 30-{prem_max})")
                return

            # Entry at next bar's open
            if opt_idx + 1 >= len(opt_df):
                return
            entry_price = float(opt_df.loc[opt_idx + 1, 'open'])
            if entry_price <= 0:
                return
            entry_time = pd.to_datetime(opt_df.loc[opt_idx + 1, 'date']).strftime("%H:%M")

            exit_price, peak_price, exit_reason, exit_time, bars_held = simulate_trade(
                opt_df, opt_idx + 1, entry_price)

            pnl_pts = round(exit_price - entry_price, 2)
            pnl_rs = round(pnl_pts * QTY, 0)
            peak_pts = round(peak_price - entry_price, 2)
            win = "WIN" if pnl_pts > 0 else "LOSS"
            icon = "✅" if pnl_pts > 0 else "❌"

            print(f"  [{strategy}] {icon} {opt_side} ENTRY {entry_time} @ ₹{entry_price:.1f} → "
                  f"EXIT {exit_time} @ ₹{exit_price:.1f} | "
                  f"PnL: {pnl_pts:+.1f}pts (₹{pnl_rs:+,.0f}) | Peak: +{peak_pts:.1f}pts | "
                  f"Reason: {exit_reason} | Bars: {bars_held}")
            print(f"           {reason_prefix}")

            trade = {
                "date": str(day), "entry_time": entry_time, "exit_time": exit_time,
                "side": opt_side, "atm": opt_info["atm"],
                "entry": entry_price, "exit": exit_price,
                "pnl_pts": pnl_pts, "pnl_rs": pnl_rs,
                "peak_pts": peak_pts, "exit_reason": exit_reason,
                "bars_held": bars_held, "win": win,
                "fut_close": fc, "fut_vwap": round(f_vwap, 1),
                "fut_body_pct": round(f_body_pct * 100, 1),
                "spot_close": sc, "spot_vwap": round(s_vwap, 1),
                "spot_body_pct": round(s_body_pct * 100, 1),
                "opt_close": opt_close, "opt_vwap": round(opt_vwap, 1),
                "strategy": strategy,
            }
            results[strategy].append(trade)
            fired[strategy] = True

        # ═══════════════════════════════════════════════════════════
        #  STRATEGY 1: OLD (Spot VWAP double — V2.5.12)
        #  Gate 1: Spot 15m close crosses spot VWAP, body >= 50%
        #  Gate 2: Option LTP above/below option VWAP
        # ═══════════════════════════════════════════════════════════
        if not fired["OLD"] and side_spot and s_body_pct >= VWAP_BODY_MIN_PCT:
            reason = (f"SPOT {sc:.0f}{'>' if spot_bullish else '<'}{s_vwap:.0f} "
                      f"body={s_body_pct*100:.0f}%")
            try_trade("OLD", side_spot, reason)
        elif not fired["OLD"] and side_spot and s_body_pct < VWAP_BODY_MIN_PCT:
            if i % 4 == 0:  # don't spam every bar
                print(f"  [OLD]  {bar_time.strftime('%H:%M')} {side_spot} REJECTED — "
                      f"spot body too weak: {s_body_pct*100:.0f}% (need ≥50%) "
                      f"spot={sc:.0f} vwap={s_vwap:.0f}")

        # ═══════════════════════════════════════════════════════════
        #  STRATEGY 2: NEW (Futures VWAP triple — V2.5.14)
        #  Gate 1 (PRIMARY): Futures 15m close crosses futures VWAP, body >= 50%
        #  Gate 2: Spot 15m close agrees (same direction vs spot VWAP)
        #  Gate 3: Option LTP above/below option VWAP
        # ═══════════════════════════════════════════════════════════
        if not fired["NEW"] and side_fut and f_body_pct >= VWAP_BODY_MIN_PCT:
            if side_spot != side_fut:
                print(f"  [NEW]  {bar_time.strftime('%H:%M')} {side_fut} REJECTED — "
                      f"spot disagrees: fut={side_fut}(fc={fc:.0f} fvwap={f_vwap:.0f}) "
                      f"spot={side_spot}(sc={sc:.0f} svwap={s_vwap:.0f})")
            else:
                reason = (f"FUT {fc:.0f}{'>' if fut_bullish else '<'}{f_vwap:.0f} body={f_body_pct*100:.0f}% | "
                          f"SPOT {sc:.0f}{'>' if spot_bullish else '<'}{s_vwap:.0f}")
                try_trade("NEW", side_fut, reason)
        elif not fired["NEW"] and side_fut and f_body_pct < VWAP_BODY_MIN_PCT:
            if i % 4 == 0:
                print(f"  [NEW]  {bar_time.strftime('%H:%M')} {side_fut} REJECTED — "
                      f"futures body too weak: {f_body_pct*100:.0f}% (need ≥50%) "
                      f"fut={fc:.0f} vwap={f_vwap:.0f}")

        # ═══════════════════════════════════════════════════════════
        #  STRATEGY 3: FAST (Futures VWAP + spot LIVE price — Option B)
        #  Gate 1 (PRIMARY): Futures 15m close crosses futures VWAP, body >= 50%
        #  Gate 2: Spot LIVE price (bar high for CE / bar low for PE) crossed VWAP
        #          (not waiting for spot bar close — fires intra-bar)
        #  Gate 3: Option LTP above/below option VWAP
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
                reason = (f"FUT {fc:.0f}{'>' if fut_bullish else '<'}{f_vwap:.0f} body={f_body_pct*100:.0f}% | "
                          f"SPOT live {'high' if side_fut=='CE' else 'low'}="
                          f"{sh if side_fut=='CE' else sl_v:.0f} > VWAP {s_vwap:.0f}")
                try_trade("FAST", side_fut, reason)

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
    strat_trades = results[strat]
    if not strat_trades:
        print(f"\n  {strat}: No trades")
        continue
    df_s = pd.DataFrame(strat_trades)
    print(f"\n  ── {strat} ──")
    print(f"  {'Date':<12} {'Time':<6} {'Side':<4} {'Entry':>7} {'Exit':>7} "
          f"{'PnL pts':>8} {'PnL ₹':>10} {'Peak':>6} {'Exit Reason':<14} {'W/L':<4}")
    print(f"  {'─'*85}")
    running_pnl_pts = 0
    running_pnl_rs = 0
    for _, t in df_s.iterrows():
        running_pnl_pts += t['pnl_pts']
        running_pnl_rs += t['pnl_rs']
        icon = "✅" if t['pnl_pts'] > 0 else "❌"
        print(f"  {t['date']:<12} {t['entry_time']:<6} {t['side']:<4} "
              f"{t['entry']:>7.1f} {t['exit']:>7.1f} "
              f"{t['pnl_pts']:>+8.1f} {t['pnl_rs']:>+10,.0f} "
              f"{t['peak_pts']:>+6.1f} {t['exit_reason']:<14} {icon}")
    print(f"  {'─'*85}")
    print(f"  {'RUNNING TOTAL':<35} {running_pnl_pts:>+8.1f} {running_pnl_rs:>+10,.0f}")


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

# ── Only in one strategy ──
only_new = sorted(set(new_by_date.keys()) - set(fast_by_date.keys()))
only_fast = sorted(set(fast_by_date.keys()) - set(new_by_date.keys()))
if only_new:
    print(f"\n  Dates with NEW signal but NO FAST signal: {', '.join(only_new)}")
if only_fast:
    print(f"  Dates with FAST signal but NO NEW signal: {', '.join(only_fast)}")

# Save full results
all_trades = []
for strat in ("OLD", "NEW", "FAST"):
    all_trades.extend(results[strat])
if all_trades:
    df_all = pd.DataFrame(all_trades)
    fn = os.path.join(DATA_DIR, "backtest_vwap_comparison.csv")
    df_all.to_csv(fn, index=False)
    print(f"\n  📊 Full results CSV: {fn}")

print("\n" + "=" * 90)
print(f"  Config: LOT_SIZE={LOT_SIZE} × LOTS={LOTS} = QTY={QTY}")
print(f"  VWAP body min: {VWAP_BODY_MIN_PCT*100:.0f}%  |  Period: {DAYS_BACK} days")
print("=" * 90)
print("  DONE ✅")
