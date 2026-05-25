#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORION - DAILY OPTION DATA CAPTURE  (V3)
========================================
Companion to ORION_PAPER_V2_5_12.py.

Run AFTER market close (or any time after 15:35 IST on a trading day).
Captures the day's option + Nifty data needed to replay strategy in backtest.

V3 additions vs V2:
  6. OI SURVEY -- kite.quote() for ATM +/- OI_SURVEY_RADIUS at 100pt steps.
     Captures actual open interest (not just volume) for the macro OI picture.
     Strikes outside the ATM trading band (e.g. 24000 when ATM=23800) are
     included so eod_analysis.py can identify major walls.
     Saved to _oi_survey.json in the date folder.

  7. EOD ANALYSIS -- automatically calls eod_analysis.py at end.
     Computes support/resistance from OI, writes next_day_plan.json,
     pushes to GitHub, sends Telegram with next-day levels.
     Bot reads next_day_plan.json on startup and injects OI walls into V3.

================================================================================
OUTPUT STRUCTURE:
  daily_option_data/
    YYYY-MM-DD/
      _meta.json                  session metadata, expiry, ATM rule, fetch log
      _oi_survey.json             EOD OI snapshot for all survey strikes (NEW V3)
      next_day_plan.json          EOD analysis output: S/R levels, V3 triggers
      nifty_5m.csv                Nifty index 5m OHLC + 7d context
      nifty_15m.csv               Nifty index 15m OHLC + 15d context
      nifty_1h.csv                Nifty index 1h OHLC + 90d context
      atm_tracker_5m.csv          per-5m: time, spot, atm, ce/pe band strikes
      CE/
        24000.csv                 5m+15m+1h OHLC concatenated, 'tf' column
        24050.csv
        ...
      PE/
        24000.csv
        ...

USAGE:
  python3 Optiondata_1.py
  python3 Optiondata_1.py 2026-05-22   # back-fill a past date
================================================================================
"""

import sys
import os
import json
import time
from datetime import datetime, timedelta, date as date_type
import pandas as pd
import pytz

try:
    from kiteconnect import KiteConnect
    import credentials
except ImportError as e:
    print(f"[X] Missing dependency: {e}")
    print("Install: pip install kiteconnect pandas pytz --user")
    sys.exit(1)

IST = pytz.timezone('Asia/Kolkata')
NIFTY_TOKEN = 256265

# ============================================================================
# CONFIG
# ============================================================================
ATM_STEP            = 100    # ATM rounding rule - MUST MATCH paper bot
LADDER_STEP         = 50     # ITM/OTM ladder spacing (NIFTY 50-pt grid)
ITM_OTM_COUNT       = 2      # 2 ITM + 2 OTM (plus ATM = 5 strikes per snapshot)

NIFTY_DAYS_BACK     = {'5minute': 7, '15minute': 15, '60minute': 90}
OPTION_DAYS_BACK    = {'5minute': 7, '15minute': 10, '60minute': 30}
TIMEFRAMES          = ['5minute', '15minute', '60minute']
TF_LABELS           = {'5minute': '5m', '15minute': '15m', '60minute': '1h'}
RATE_LIMIT_SLEEP    = 0.4    # ~2.5 req/sec, well under Kite's 3/sec
OUT_ROOT            = "daily_option_data"

# V3: OI Survey config
OI_SURVEY_RADIUS    = 600    # ATM +/- this many points for OI survey
OI_SURVEY_STEP      = 100    # Step between survey strikes (100-pt grid)


# ============================================================================
# HELPERS
# ============================================================================
def ensure_dir(d):
    if not os.path.exists(d):
        os.makedirs(d)


def round_to_atm(price):
    return int(round(price / ATM_STEP)) * ATM_STEP


def parse_target_date(argv):
    if len(argv) > 1:
        try:
            return datetime.strptime(argv[1], "%Y-%m-%d").date()
        except ValueError:
            print(f"[X] Invalid date '{argv[1]}'. Use YYYY-MM-DD.")
            sys.exit(1)
    return datetime.now(IST).date()


def find_target_expiry(nifty_master, target_date):
    expiries = sorted(set(pd.to_datetime(nifty_master['expiry']).dt.date))
    future = [e for e in expiries if e >= target_date]
    return future[0] if future else None


def find_monthly_expiry(nifty_master, target_date):
    """Return the nearest monthly expiry >= target_date (last Thursday of month)."""
    expiries = sorted(set(pd.to_datetime(nifty_master['expiry']).dt.date))
    # Monthly expiries are typically the last Thursday; they have the highest
    # open interest. Heuristic: monthly expiry = expiry with day >= 24.
    monthly = [e for e in expiries if e >= target_date and e.day >= 24]
    return monthly[0] if monthly else None


def fetch_nifty_tf(kite, target_date, interval, days_back):
    end = datetime.combine(target_date, datetime.min.time()).replace(hour=15, minute=35)
    start = end - timedelta(days=days_back)
    end_ist = IST.localize(end)
    start_ist = IST.localize(start)
    try:
        recs = kite.historical_data(NIFTY_TOKEN, start_ist, end_ist, interval)
    except Exception as e:
        return pd.DataFrame(), f"FETCH_ERROR: {e}"
    if not recs:
        return pd.DataFrame(), "EMPTY"
    df = pd.DataFrame(recs)[['date', 'open', 'high', 'low', 'close', 'volume']]
    return df, None


def fetch_option_tf(kite, token, target_date, interval, days_back):
    end = datetime.combine(target_date, datetime.min.time()).replace(hour=15, minute=35)
    start = end - timedelta(days=days_back)
    end_ist = IST.localize(end)
    start_ist = IST.localize(start)
    try:
        recs = kite.historical_data(token, start_ist, end_ist, interval)
    except Exception as e:
        return pd.DataFrame(), f"FETCH_ERROR: {e}"
    if not recs:
        return pd.DataFrame(), "EMPTY"
    df = pd.DataFrame(recs)[['date', 'open', 'high', 'low', 'close', 'volume']]
    return df, None


def build_atm_tracker(nifty_5m_df, target_date):
    df = nifty_5m_df.copy()
    df['date_only'] = pd.to_datetime(df['date']).dt.date
    df = df[df['date_only'] == target_date].drop(columns=['date_only'])
    rows = []
    for _, bar in df.iterrows():
        nifty_close = float(bar['close'])
        atm = round_to_atm(nifty_close)
        rows.append({
            'time': bar['date'], 'nifty_close': nifty_close, 'atm_strike': atm,
            'ce_itm2': atm - 2*LADDER_STEP, 'ce_itm1': atm - LADDER_STEP,
            'ce_atm':  atm,
            'ce_otm1': atm + LADDER_STEP,   'ce_otm2': atm + 2*LADDER_STEP,
            'pe_itm2': atm + 2*LADDER_STEP, 'pe_itm1': atm + LADDER_STEP,
            'pe_atm':  atm,
            'pe_otm1': atm - LADDER_STEP,   'pe_otm2': atm - 2*LADDER_STEP,
        })
    return pd.DataFrame(rows)


def collect_unique_strikes(tracker_df):
    ce_cols = ['ce_itm2', 'ce_itm1', 'ce_atm', 'ce_otm1', 'ce_otm2']
    pe_cols = ['pe_itm2', 'pe_itm1', 'pe_atm', 'pe_otm1', 'pe_otm2']
    ce_strikes, pe_strikes = set(), set()
    for c in ce_cols:
        ce_strikes.update(int(s) for s in tracker_df[c].unique())
    for c in pe_cols:
        pe_strikes.update(int(s) for s in tracker_df[c].unique())
    return sorted(ce_strikes), sorted(pe_strikes)


def fetch_oi_survey(kite, nifty_master, expiry, target_date, eod_atm,
                    ce_volume_map, pe_volume_map):
    """
    V3: Fetch actual OI via kite.quote() for survey strikes (ATM +/- OI_SURVEY_RADIUS).
    Also incorporates intraday volume from already-fetched CSVs for the trading band.

    Returns dict suitable for _oi_survey.json.
    """
    survey_strikes = list(range(
        eod_atm - OI_SURVEY_RADIUS,
        eod_atm + OI_SURVEY_RADIUS + OI_SURVEY_STEP,
        OI_SURVEY_STEP
    ))

    # Build tradingsymbol -> strike/side lookup for all survey strikes
    weekly_master = nifty_master[nifty_master['expiry'] == expiry]
    sym_to_info = {}
    for _, row in weekly_master.iterrows():
        s = int(row['strike'])
        if s in survey_strikes:
            side = row['instrument_type']  # 'CE' or 'PE'
            sym = row['tradingsymbol']
            sym_to_info[f"NFO:{sym}"] = (s, side, row['last_price'] if 'last_price' in row else 0)

    if not sym_to_info:
        print("  [OI Survey] No matching instruments found in master.")
        return {}

    # kite.quote() in batches of 200
    all_quotes = {}
    syms = list(sym_to_info.keys())
    for i in range(0, len(syms), 200):
        batch = syms[i:i+200]
        try:
            q = kite.quote(batch)
            all_quotes.update(q)
            time.sleep(RATE_LIMIT_SLEEP)
        except Exception as e:
            print(f"  [OI Survey] quote() batch error: {e}")

    # Build survey data per strike
    strikes_data = {}
    for sym, (strike, side, _) in sym_to_info.items():
        key = str(strike)
        if key not in strikes_data:
            strikes_data[key] = {"CE": {}, "PE": {}}
        q = all_quotes.get(sym, {})
        oi  = q.get("oi", 0) or 0
        ltp = q.get("last_price", 0) or 0
        vol = q.get("volume", 0) or 0
        # Override volume with intraday 5m volume sum if we have it (more accurate)
        if side == "CE" and strike in ce_volume_map:
            vol = ce_volume_map[strike]
        elif side == "PE" and strike in pe_volume_map:
            vol = pe_volume_map[strike]
        strikes_data[key][side] = {"oi": oi, "ltp": ltp, "volume": vol}

    return strikes_data


# ============================================================================
# MAIN
# ============================================================================
def main():
    target_date = parse_target_date(sys.argv)
    print("=" * 78)
    print(f"ORION DAILY OPTION DATA CAPTURE - V3")
    print(f"Target date: {target_date}")
    print(f"Run time:    {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("=" * 78)

    if target_date.weekday() >= 5:
        print(f"[!] {target_date} is weekend ({target_date.strftime('%A')}). Aborting.")
        return 1

    # 1) Connect to Kite
    try:
        _use_enc = getattr(credentials, 'KITE_USE_ENCTOKEN', False)
        if _use_enc:
            kite = KiteConnect(api_key=credentials.KITE_API_KEY, root="https://kite.zerodha.com")
            kite.set_access_token(credentials.KITE_ACCESS_TOKEN)
            import requests as _req
            class _EnctokenAuth(_req.auth.AuthBase):
                def __call__(self, r):
                    r.headers["Authorization"] = f"enctoken {credentials.KITE_ACCESS_TOKEN}"
                    return r
            kite.reqsession.auth = _EnctokenAuth()
        else:
            kite = KiteConnect(api_key=credentials.KITE_API_KEY)
            kite.set_access_token(credentials.KITE_ACCESS_TOKEN)
        _ = kite.historical_data(NIFTY_TOKEN,
                                 datetime.now(IST) - timedelta(days=2),
                                 datetime.now(IST), "5minute")
        print(f"\n[AUTH] Connected to Kite.")
    except Exception as e:
        print(f"\n[X] AUTH FAILED: {e}")
        return 1

    # 2) Load NFO master, identify expiries
    print(f"\n[INSTRUMENTS] Loading NFO master...")
    inst_df = pd.DataFrame(kite.instruments("NFO"))
    nifty_master = inst_df[inst_df['name'] == 'NIFTY'].copy()
    nifty_master['expiry'] = pd.to_datetime(nifty_master['expiry']).dt.date

    expiry = find_target_expiry(nifty_master, target_date)
    monthly_expiry = find_monthly_expiry(nifty_master, target_date)
    if expiry is None:
        print(f"[X] No NIFTY expiry found on or after {target_date}")
        return 1
    print(f"              weekly expiry:  {expiry}")
    print(f"              monthly expiry: {monthly_expiry}")

    # 3) Fetch Nifty multi-TF
    print(f"\n[NIFTY] Fetching multi-timeframe OHLC for {target_date}...")
    nifty_data = {}
    for tf in TIMEFRAMES:
        df, err = fetch_nifty_tf(kite, target_date, tf, NIFTY_DAYS_BACK[tf])
        if err or df.empty:
            print(f"[X] Nifty {TF_LABELS[tf]} fetch failed: {err or 'EMPTY'}")
            return 1
        nifty_data[tf] = df
        df_today = df[pd.to_datetime(df['date']).dt.date == target_date]
        print(f"        {TF_LABELS[tf]:>3}: {len(df):>5} bars total, "
              f"{len(df_today):>3} on {target_date}")
        time.sleep(RATE_LIMIT_SLEEP)

    nifty_5m = nifty_data['5minute']
    nifty_5m_today = nifty_5m[pd.to_datetime(nifty_5m['date']).dt.date == target_date]
    if nifty_5m_today.empty:
        print(f"[X] No 5m bars ON {target_date} - market closed (holiday)?")
        return 1
    nifty_lo = nifty_5m_today['close'].min()
    nifty_hi = nifty_5m_today['close'].max()
    eod_close = float(nifty_5m_today['close'].iloc[-1])
    eod_atm   = round_to_atm(eod_close)
    print(f"        Nifty range: {nifty_lo:.2f} -> {nifty_hi:.2f}  EOD close: {eod_close:.2f}  EOD ATM: {eod_atm}")

    # 4) Build ATM tracker
    tracker = build_atm_tracker(nifty_5m, target_date)
    print(f"\n[TRACKER] Built {len(tracker)} 5-min snapshots")
    atm_counts = tracker['atm_strike'].value_counts().sort_index()
    for strike, count in atm_counts.items():
        print(f"            ATM {strike}: {count} snapshots")

    # 5) Collect unique strikes
    ce_strikes, pe_strikes = collect_unique_strikes(tracker)
    print(f"\n[STRIKES TO FETCH]")
    print(f"  CE: {ce_strikes}")
    print(f"  PE: {pe_strikes}")

    # 6) Resolve instrument tokens
    weekly_master = nifty_master[nifty_master['expiry'] == expiry]
    contract_lookup = {}
    for _, row in weekly_master.iterrows():
        key = (int(row['strike']), row['instrument_type'])
        contract_lookup[key] = (int(row['instrument_token']), row['tradingsymbol'])

    # 7) Set up output dirs
    day_dir = os.path.join(OUT_ROOT, str(target_date))
    ce_dir  = os.path.join(day_dir, "CE")
    pe_dir  = os.path.join(day_dir, "PE")
    ensure_dir(ce_dir)
    ensure_dir(pe_dir)

    # 8) Save Nifty multi-TF and ATM tracker
    for tf in TIMEFRAMES:
        out = os.path.join(day_dir, f"nifty_{TF_LABELS[tf]}.csv")
        nifty_data[tf].to_csv(out, index=False)
        print(f"\n[SAVED] {out}")
    tracker.to_csv(os.path.join(day_dir, "atm_tracker_5m.csv"), index=False)
    print(f"[SAVED] {day_dir}/atm_tracker_5m.csv")

    # 9) Fetch each strike's OHLC across all 3 TFs
    print(f"\n[FETCH] Strike-level OHLC ({len(ce_strikes)+len(pe_strikes)} strikes x 3 TFs)")
    fetch_log = []
    ce_volume_map = {}   # strike -> total 5m volume (for OI survey)
    pe_volume_map = {}

    def fetch_strike_all_tfs(side, strike):
        side_dir = ce_dir if side == 'CE' else pe_dir
        key = (strike, side)
        if key not in contract_lookup:
            print(f"        [X] {side} {strike}: no token in master")
            for tf in TIMEFRAMES:
                fetch_log.append({'side': side, 'strike': strike, 'tf': TF_LABELS[tf],
                                  'status': 'NO_TOKEN', 'bars': 0})
            return
        token, tsym = contract_lookup[key]
        all_dfs = []
        total_vol_5m = 0
        for tf in TIMEFRAMES:
            df, err = fetch_option_tf(kite, token, target_date, tf, OPTION_DAYS_BACK[tf])
            tf_label = TF_LABELS[tf]
            if err or df.empty:
                fetch_log.append({'side': side, 'strike': strike, 'tf': tf_label,
                                  'status': 'EMPTY' if not err else err[:30], 'bars': 0})
                time.sleep(RATE_LIMIT_SLEEP)
                continue
            df = df.copy()
            df['tf'] = tf_label
            if tf == '5minute':
                today_mask = pd.to_datetime(df['date']).dt.date == target_date
                total_vol_5m = int(df.loc[today_mask, 'volume'].sum())
            all_dfs.append(df)
            fetch_log.append({'side': side, 'strike': strike, 'tf': tf_label,
                              'status': 'OK', 'bars': len(df)})
            time.sleep(RATE_LIMIT_SLEEP)
        if not all_dfs:
            return
        combined = pd.concat(all_dfs, ignore_index=True)
        combined = combined[['tf', 'date', 'open', 'high', 'low', 'close', 'volume']]
        combined.to_csv(os.path.join(side_dir, f"{strike}.csv"), index=False)
        if side == 'CE':
            ce_volume_map[strike] = total_vol_5m
        else:
            pe_volume_map[strike] = total_vol_5m
        bar_sum = ' '.join(
            f"{r['tf']}:{r['bars']}" for r in fetch_log[-3:]
            if r['side'] == side and r['strike'] == strike
        )
        print(f"        [OK] {side} {strike} ({tsym}) [{bar_sum}]")

    print(f"\n  --- CE strikes ---")
    for strike in ce_strikes:
        fetch_strike_all_tfs('CE', strike)

    print(f"\n  --- PE strikes ---")
    for strike in pe_strikes:
        fetch_strike_all_tfs('PE', strike)

    # 10) OI Survey -- actual OI from kite.quote() for broad strike range
    print(f"\n[OI SURVEY] Fetching actual OI for ATM {eod_atm} +/- {OI_SURVEY_RADIUS}pts...")
    survey_strikes_data = fetch_oi_survey(
        kite, nifty_master, expiry, target_date,
        eod_atm, ce_volume_map, pe_volume_map
    )

    oi_survey = {
        "date":            str(target_date),
        "expiry":          str(expiry),
        "monthly_expiry":  str(monthly_expiry) if monthly_expiry else "",
        "atm":             eod_atm,
        "eod_nifty_close": eod_close,
        "survey_radius":   OI_SURVEY_RADIUS,
        "survey_step":     OI_SURVEY_STEP,
        "strikes":         survey_strikes_data,
    }
    survey_path = os.path.join(day_dir, "_oi_survey.json")
    with open(survey_path, "w") as f:
        json.dump(oi_survey, f, indent=2)
    print(f"[SAVED] {survey_path}")

    # Print OI summary
    if survey_strikes_data:
        print(f"\n  {'Strike':>8}  {'CE OI':>10}  {'CE LTP':>8}  {'PE OI':>10}  {'PE LTP':>8}")
        print(f"  {'-'*50}")
        for s in sorted(int(k) for k in survey_strikes_data.keys()):
            sd  = survey_strikes_data.get(str(s), {})
            ce  = sd.get("CE", {})
            pe  = sd.get("PE", {})
            marker = " <-- ATM" if s == eod_atm else ""
            print(f"  {s:>8}  {ce.get('oi',0):>10,}  {ce.get('ltp',0):>8.1f}  "
                  f"{pe.get('oi',0):>10,}  {pe.get('ltp',0):>8.1f}{marker}")

    # 11) Save metadata
    ok_count   = sum(1 for r in fetch_log if r['status'] == 'OK')
    fail_count = len(fetch_log) - ok_count
    total_bars = sum(r['bars'] for r in fetch_log)
    meta = {
        'capture_script_version':  'V3',
        'target_date':             str(target_date),
        'capture_run_time':        datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        'target_expiry':           str(expiry),
        'monthly_expiry':          str(monthly_expiry),
        'atm_rule':                f'round(spot/{ATM_STEP})*{ATM_STEP}',
        'eod_atm':                 eod_atm,
        'eod_nifty_close':         eod_close,
        'ladder_step':             LADDER_STEP,
        'itm_otm_count':           ITM_OTM_COUNT,
        'timeframes':              [TF_LABELS[tf] for tf in TIMEFRAMES],
        'nifty_5m_bars_total':     len(nifty_5m),
        'nifty_5m_bars_target':    len(nifty_5m_today),
        'nifty_range_target':      {'low': float(nifty_lo), 'high': float(nifty_hi)},
        'atm_tracker_rows':        len(tracker),
        'unique_atm_strikes':      sorted(int(x) for x in tracker['atm_strike'].unique()),
        'ce_strikes_fetched':      ce_strikes,
        'pe_strikes_fetched':      pe_strikes,
        'oi_survey_strikes':       sorted(int(k) for k in survey_strikes_data.keys()),
        'fetch_log':               fetch_log,
    }
    meta_path = os.path.join(day_dir, "_meta.json")
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2, default=str)
    print(f"[SAVED] {meta_path}")

    # 12) Summary
    print(f"\n{'=' * 78}")
    print(f"DATA CAPTURE COMPLETE")
    print(f"{'=' * 78}")
    print(f"  Date:            {target_date}")
    print(f"  Expiry:          {expiry} (monthly: {monthly_expiry})")
    print(f"  EOD ATM:         {eod_atm}  (Nifty close: {eod_close:.2f})")
    print(f"  Option fetches:  {len(fetch_log)}  (OK={ok_count}  fail={fail_count})")
    print(f"  Option bars:     {total_bars:,}")
    print(f"  OI survey:       {len(survey_strikes_data)} strikes")
    print(f"\n  Running EOD analysis...")

    # 13) Auto-run EOD analysis
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, script_dir)
        import eod_analysis
        # Point eod_analysis at the right data root
        eod_analysis.run(date_str=str(target_date), data_root=OUT_ROOT)
    except Exception as e:
        print(f"[!] EOD analysis failed: {e}")
        print("    Run manually: python3 eod_analysis.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
