"""
==========================================================================
ORION_DATA_COLLECTOR.py
==========================================================================
Step-by-step data collection per user spec:

Step 1 : Find all A events — 15m futures bar crossing daily VWAP with
         >50% body. Record time (A1, A2..), direction, futures OHLCV,
         VWAP, spot price, ATM CE/PE option prices.

Step 2 : After each A event, track subsequent 15m bars for:
         - Higher Highs (H1, H2..) : bar.high > running max since A
         - Lower Lows  (L1, L2..) : bar.low < running min since A
         Record futures price, spot, ATM CE/PE at each H/L event.

Step 3 : Which direction did futures move FIRST after A? HH or LL?
         "Continuation" = same direction as A. "Reversal" = opposite.

Step 4 : For continuation events: find B1 = min pullback low between
         A and first HH (for bullish A); or max pullback high between
         A and first LL (for bearish A). Record option prices at B1.

Step 5 : B1 option price vs A option price = natural limit-order discount.
         Average this across all continuation events → calibrate entry.

Step 6 : Reversal events → track how deep it reversed (for HARDSL cal).

Step 7 : Hn/Ln = overall max high / min low after A.
         Option price at Hn/Ln → max achievable gain → calibrate target.

Step 8 : Output summary stats for parameter calibration.

Data needed:
  market_data/nifty_fut_15m.csv    <- from FETCH_MARKET_DATA.py
  option_data/selukar/<day>/       <- from PythonAnywhere upload
  option_data/amol/<day>/          <- from PythonAnywhere upload
==========================================================================
"""
import os, sys, glob
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Paths ──────────────────────────────────────────────────────────────
FUT_FILE   = os.path.join(REPO_DIR, 'market_data', 'nifty_fut_15m.csv')
OPT_BASES  = [
    os.path.join(REPO_DIR, 'option_data', 'selukar'),
    os.path.join(REPO_DIR, 'option_data', 'amol'),
]

# ── Strategy params (adjustable) ──────────────────────────────────────
BODY_MIN_PCT = 0.50
FORCE_CLOSE  = "15:25"

# ── Helpers ───────────────────────────────────────────────────────────
def atm_strike(spot: float) -> int:
    return int(round(spot / 50) * 50)

def opt_price_at(opt_df: Optional[pd.DataFrame], at_time: datetime) -> Optional[float]:
    if opt_df is None or opt_df.empty: return None
    mask = opt_df['date'] <= at_time
    if not mask.any(): return None
    return float(opt_df.loc[mask, 'close'].iloc[-1])

def compute_vwap(df_day: pd.DataFrame) -> pd.Series:
    tp  = (df_day['high'] + df_day['low'] + df_day['close']) / 3
    vol = df_day['volume'].fillna(1).replace(0, 1)
    return ((tp * vol).cumsum() / vol.cumsum()).reset_index(drop=True)

# ── Load futures 15m ──────────────────────────────────────────────────
def load_futures() -> pd.DataFrame:
    if not os.path.exists(FUT_FILE):
        print(f"[ERROR] {FUT_FILE} not found.")
        print("  Run on PythonAnywhere first: python FETCH_MARKET_DATA.py")
        sys.exit(1)
    df = pd.read_csv(FUT_FILE, parse_dates=['date'])
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    return df.sort_values('date').reset_index(drop=True)

# ── Discover available days ───────────────────────────────────────────
def discover_days() -> List[str]:
    days = set()
    for base in OPT_BASES:
        if not os.path.isdir(base): continue
        for d in os.listdir(base):
            if d.startswith('20') and os.path.isdir(os.path.join(base, d)):
                days.add(d)
    return sorted(days)

# ── Load one day's option data ────────────────────────────────────────
def load_day_options(day_str: str) -> Optional[dict]:
    for base in OPT_BASES:
        ddir = os.path.join(base, day_str)
        if not os.path.isdir(ddir): continue
        try:
            p15 = os.path.join(ddir, 'nifty_15m.csv')
            if not os.path.exists(p15): continue
            df15 = pd.read_csv(p15, parse_dates=['date'])
            df15['date'] = pd.to_datetime(df15['date']).dt.tz_localize(None)
            df15 = df15.sort_values('date').reset_index(drop=True)

            opt = {}
            for side in ('CE', 'PE'):
                sdir = os.path.join(ddir, side)
                if not os.path.isdir(sdir): continue
                for fp in glob.glob(os.path.join(sdir, '*.csv')):
                    strike = int(os.path.basename(fp).replace('.csv', ''))
                    try:
                        dfopt = pd.read_csv(fp, parse_dates=['date'])
                        dfopt['date'] = pd.to_datetime(dfopt['date']).dt.tz_localize(None)
                        if 'tf' in dfopt.columns:
                            dfopt = dfopt[dfopt['tf'] == '5m']
                        dfopt = dfopt.sort_values('date').reset_index(drop=True)
                        if not dfopt.empty:
                            opt[(strike, side)] = dfopt
                    except Exception: pass
            if opt:
                return dict(df15_spot=df15, opt=opt, source=base)
        except Exception as e:
            print(f"  [LOAD ERR] {day_str}: {e}")
    return None

# ── Get spot and option prices at a given time ────────────────────────
def get_prices(df15_spot: pd.DataFrame, opt: dict, at_time: datetime
               ) -> Tuple[Optional[float], int, Optional[float], Optional[float]]:
    """Returns (spot, atm, ce_price, pe_price)"""
    spot_rows = df15_spot[df15_spot['date'] <= at_time]
    if spot_rows.empty: return None, 0, None, None
    spot = float(spot_rows.iloc[-1]['close'])
    atm  = atm_strike(spot)

    def get_opt(side):
        key = (atm, side)
        if key not in opt:
            for adj in (50, -50, 100, -100):
                if (atm + adj, side) in opt:
                    return opt[(atm + adj, side)]
            return None
        return opt[key]

    ce_df = get_opt('CE')
    pe_df = get_opt('PE')
    ce_p  = opt_price_at(ce_df, at_time)
    pe_p  = opt_price_at(pe_df, at_time)
    return spot, atm, ce_p, pe_p

# ── Analyse one day ───────────────────────────────────────────────────
def analyse_day(day_str: str, df_fut15: pd.DataFrame, day_opt: dict) -> dict:
    day_date = datetime.strptime(day_str, '%Y-%m-%d')
    IST_09_15 = day_date.replace(hour=9, minute=15)
    IST_15_30 = day_date.replace(hour=15, minute=30)

    fut_day = df_fut15[
        (df_fut15['date'] >= IST_09_15) &
        (df_fut15['date'] <= IST_15_30)
    ].copy().reset_index(drop=True)

    if fut_day.empty:
        return {'day': day_str, 'error': 'No futures data', 'a_events': []}

    fut_day['vwap'] = compute_vwap(fut_day)
    df15_spot = day_opt['df15_spot']
    opt        = day_opt['opt']

    a_events = []

    for i in range(1, len(fut_day)):  # skip bar 0 (no prior VWAP)
        fbar = fut_day.iloc[i]
        bar_time = fbar['date']
        if bar_time.strftime('%H:%M') > FORCE_CLOSE: break

        fo = float(fbar['open']); fh = float(fbar['high'])
        fl = float(fbar['low']);  fc = float(fbar['close'])
        vwap = float(fbar['vwap'])
        rng  = fh - fl
        if rng <= 0: continue
        body_pct = abs(fc - fo) / rng
        if body_pct <= BODY_MIN_PCT: continue

        if fc > vwap:   direction = 'CE'  # bullish
        elif fc < vwap: direction = 'PE'  # bearish
        else: continue

        # Get option prices at A event time
        spot, atm, ce_p, pe_p = get_prices(df15_spot, opt, bar_time)
        if spot is None: continue

        # ── Subsequent bar analysis ──────────────────────────────────
        # running max high and min low from A close onward
        running_hi  = fh   # start from A bar's high
        running_lo  = fl   # start from A bar's low

        hh_events   = []   # Higher Highs: bar.high > previous running_hi
        ll_events   = []   # Lower Lows:   bar.low  < previous running_lo
        all_sub     = []   # every bar after A

        first_hh_bar_idx = None
        first_ll_bar_idx = None

        for j in range(i + 1, len(fut_day)):
            sb      = fut_day.iloc[j]
            sb_time = sb['date']
            if sb_time.strftime('%H:%M') > FORCE_CLOSE: break

            sh = float(sb['high']); sl = float(sb['low']); sc = float(sb['close'])
            s_spot, s_atm, s_ce, s_pe = get_prices(df15_spot, opt, sb_time)

            bar_rec = dict(
                time=sb_time, fut_high=sh, fut_low=sl, fut_close=sc,
                spot=s_spot, atm=s_atm, ce=s_ce, pe=s_pe
            )
            all_sub.append(bar_rec)

            if sh > running_hi:
                running_hi = sh
                hh_events.append({**bar_rec, 'level': sh})
                if first_hh_bar_idx is None:
                    first_hh_bar_idx = len(all_sub) - 1

            if sl < running_lo:
                running_lo = sl
                ll_events.append({**bar_rec, 'level': sl})
                if first_ll_bar_idx is None:
                    first_ll_bar_idx = len(all_sub) - 1

        # ── Determine first move direction ───────────────────────────
        if first_hh_bar_idx is None and first_ll_bar_idx is None:
            first_move = 'none'
        elif first_hh_bar_idx is None:
            first_move = 'LL'
        elif first_ll_bar_idx is None:
            first_move = 'HH'
        else:
            first_move = 'HH' if first_hh_bar_idx <= first_ll_bar_idx else 'LL'

        continuation = (
            (direction == 'CE' and first_move == 'HH') or
            (direction == 'PE' and first_move == 'LL')
        )
        reversal = (
            (direction == 'CE' and first_move == 'LL') or
            (direction == 'PE' and first_move == 'HH')
        )

        # ── B1: pullback between A and first continuation event ──────
        b1 = None
        b1_opt_price = None    # option price at B1 (CE if bullish, PE if bearish)
        a_opt_price  = ce_p if direction == 'CE' else pe_p
        b1_discount  = None    # how much cheaper vs A price

        if continuation:
            if direction == 'CE' and first_hh_bar_idx is not None:
                # B1 = minimum LOW between A bar and first HH bar
                window = all_sub[:first_hh_bar_idx + 1]
                if window:
                    # include A bar's low in window
                    lows = [fl] + [b['fut_low'] for b in window]
                    times_lows = [bar_time] + [b['time'] for b in window]
                    min_idx = int(np.argmin(lows))
                    b1_time   = times_lows[min_idx]
                    b1_fut_lo = lows[min_idx]
                    _, _, b1_ce, b1_pe = get_prices(df15_spot, opt, b1_time)
                    b1_opt_price = b1_ce
                    b1 = dict(time=b1_time, fut_low=b1_fut_lo,
                              ce=b1_ce, pe=b1_pe)
                    if a_opt_price and b1_opt_price:
                        b1_discount = a_opt_price - b1_opt_price  # positive = cheaper at B1

            elif direction == 'PE' and first_ll_bar_idx is not None:
                # B1 = maximum HIGH between A bar and first LL bar
                window = all_sub[:first_ll_bar_idx + 1]
                if window:
                    highs = [fh] + [b['fut_high'] for b in window]
                    times_highs = [bar_time] + [b['time'] for b in window]
                    max_idx = int(np.argmax(highs))
                    b1_time   = times_highs[max_idx]
                    b1_fut_hi = highs[max_idx]
                    _, _, b1_ce, b1_pe = get_prices(df15_spot, opt, b1_time)
                    b1_opt_price = b1_pe
                    b1 = dict(time=b1_time, fut_high=b1_fut_hi,
                              ce=b1_ce, pe=b1_pe)
                    if a_opt_price and b1_opt_price:
                        b1_discount = a_opt_price - b1_opt_price  # positive = cheaper at B1

        # ── Overall Hn/Ln after A ─────────────────────────────────────
        hn = None; ln = None
        if hh_events:
            hn = max(hh_events, key=lambda x: x['level'])
        if ll_events:
            ln = min(ll_events, key=lambda x: x['level'])

        # Gain from A to Hn/Ln option price
        hn_opt = hn['ce'] if (direction == 'CE' and hn) else (hn['pe'] if hn else None)
        ln_opt = ln['pe'] if (direction == 'PE' and ln) else (ln['ce'] if ln else None)
        target_opt = hn_opt if direction == 'CE' else ln_opt

        gain_from_a  = (target_opt - a_opt_price) if (target_opt and a_opt_price) else None
        gain_from_b1 = (target_opt - b1_opt_price) if (target_opt and b1_opt_price) else None

        # Reversal depth (for HARDSL calibration)
        reversal_depth_opt = None
        if reversal and direction == 'CE' and ll_events:
            ll1_opt = ll_events[0].get('ce')
            reversal_depth_opt = (a_opt_price - ll1_opt) if (a_opt_price and ll1_opt) else None
        elif reversal and direction == 'PE' and hh_events:
            hh1_opt = hh_events[0].get('pe')
            reversal_depth_opt = (a_opt_price - hh1_opt) if (a_opt_price and hh1_opt) else None

        a_events.append(dict(
            day          = day_str,
            a_idx        = len(a_events) + 1,
            time         = bar_time,
            direction    = direction,
            fut_close    = round(fc, 2),
            vwap         = round(vwap, 2),
            body_pct     = round(body_pct * 100, 1),
            spot         = round(spot, 2) if spot else None,
            atm          = atm,
            ce_price     = round(ce_p, 2) if ce_p else None,
            pe_price     = round(pe_p, 2) if pe_p else None,
            first_move   = first_move,
            continuation = continuation,
            reversal     = reversal,
            hh_count     = len(hh_events),
            ll_count     = len(ll_events),
            hh_events    = hh_events,
            ll_events    = ll_events,
            b1           = b1,
            b1_discount  = round(b1_discount, 2) if b1_discount is not None else None,
            a_opt_price  = round(a_opt_price, 2) if a_opt_price else None,
            b1_opt_price = round(b1_opt_price, 2) if b1_opt_price else None,
            hn           = hn,
            ln           = ln,
            gain_from_a  = round(gain_from_a, 2) if gain_from_a is not None else None,
            gain_from_b1 = round(gain_from_b1, 2) if gain_from_b1 is not None else None,
            reversal_depth_opt = round(reversal_depth_opt, 2) if reversal_depth_opt else None,
        ))

    return {'day': day_str, 'a_events': a_events}

# ── Print detailed report ─────────────────────────────────────────────
def print_report(all_days_results: List[dict]):
    sep  = '=' * 80
    sep2 = '-' * 80

    print(f"\n{sep}")
    print("  ORION DATA COLLECTOR — Nifty Futures VWAP Cross Analysis")
    print(sep)

    all_a = [a for d in all_days_results for a in d.get('a_events', [])]

    # ── Per-day, per-event detail ─────────────────────────────────────
    for day_res in all_days_results:
        day_str = day_res['day']
        events  = day_res.get('a_events', [])
        err     = day_res.get('error')

        print(f"\n{'─'*80}")
        print(f"  DAY: {day_str}   A-events: {len(events)}"
              + (f"  ⚠ {err}" if err else ""))
        if not events: continue

        for ev in events:
            cont_str = "✅ CONTINUATION" if ev['continuation'] else ("❌ REVERSAL" if ev['reversal'] else "— no move")
            print(f"\n  A{ev['a_idx']}  {ev['time'].strftime('%H:%M')}  "
                  f"{'🟢CE' if ev['direction']=='CE' else '🔴PE'}  "
                  f"Fut={ev['fut_close']:.1f}  VWAP={ev['vwap']:.1f}  "
                  f"Body={ev['body_pct']:.0f}%  Spot={ev['spot']}  "
                  f"ATM={ev['atm']}  CE={ev['ce_price']}  PE={ev['pe_price']}")
            print(f"     First move: {ev['first_move']}  →  {cont_str}")
            print(f"     HHs after A: {ev['hh_count']}  |  LLs after A: {ev['ll_count']}")

            # HH events
            if ev['hh_events']:
                print(f"     Higher Highs:")
                for k, h in enumerate(ev['hh_events'][:5], 1):
                    t = h['time'].strftime('%H:%M') if hasattr(h['time'], 'strftime') else str(h['time'])
                    print(f"       H{k}: {t}  Fut_Hi={h['level']:.1f}  "
                          f"CE={h.get('ce','?')}  PE={h.get('pe','?')}")

            # LL events
            if ev['ll_events']:
                print(f"     Lower Lows:")
                for k, l in enumerate(ev['ll_events'][:5], 1):
                    t = l['time'].strftime('%H:%M') if hasattr(l['time'], 'strftime') else str(l['time'])
                    print(f"       L{k}: {t}  Fut_Lo={l['level']:.1f}  "
                          f"CE={l.get('ce','?')}  PE={l.get('pe','?')}")

            # B1 pullback
            if ev['b1']:
                b = ev['b1']
                bt = b['time'].strftime('%H:%M') if hasattr(b['time'], 'strftime') else str(b['time'])
                print(f"     B1 (pullback): {bt}  "
                      f"Opt@A={ev['a_opt_price']}  Opt@B1={ev['b1_opt_price']}  "
                      f"Discount={ev['b1_discount']} pts")

            # Gain analysis
            if ev['gain_from_a'] is not None:
                hn_ln = ev['hn'] if ev['direction'] == 'CE' else ev['ln']
                hn_t  = hn_ln['time'].strftime('%H:%M') if hn_ln and hasattr(hn_ln['time'], 'strftime') else '?'
                print(f"     Max gain from A:  {ev['gain_from_a']:+.1f} pts  (at {hn_t})")
            if ev['gain_from_b1'] is not None:
                print(f"     Max gain from B1: {ev['gain_from_b1']:+.1f} pts")
            if ev['reversal_depth_opt'] is not None:
                print(f"     Reversal depth:   {ev['reversal_depth_opt']:+.1f} pts  (option drop at first reversal bar)")

    # ── Summary statistics ─────────────────────────────────────────────
    print(f"\n{sep}")
    print("  SUMMARY STATISTICS")
    print(sep)

    total_a   = len(all_a)
    cont_evs  = [e for e in all_a if e['continuation']]
    rev_evs   = [e for e in all_a if e['reversal']]
    no_move   = [e for e in all_a if not e['continuation'] and not e['reversal']]

    print(f"\n  Total A events (VWAP cross >50% body): {total_a}")
    print(f"  ✅ Continuation (same direction):      {len(cont_evs)}  ({len(cont_evs)/total_a*100:.1f}%)")
    print(f"  ❌ Reversal (opposite direction):       {len(rev_evs)}  ({len(rev_evs)/total_a*100:.1f}%)")
    print(f"  — No further move (flat/EOD):          {len(no_move)}  ({len(no_move)/total_a*100:.1f}%)")

    # CE vs PE breakdown
    ce_cont = [e for e in cont_evs if e['direction']=='CE']
    pe_cont = [e for e in cont_evs if e['direction']=='PE']
    ce_rev  = [e for e in rev_evs  if e['direction']=='CE']
    pe_rev  = [e for e in rev_evs  if e['direction']=='PE']
    print(f"\n  CE events: continuation={len(ce_cont)}  reversal={len(ce_rev)}")
    print(f"  PE events: continuation={len(pe_cont)}  reversal={len(pe_rev)}")

    # B1 discount stats (from continuation events that have B1)
    b1_discounts = [e['b1_discount'] for e in cont_evs if e['b1_discount'] is not None]
    if b1_discounts:
        print(f"\n  ── B1 PULLBACK STATS (from A to B1) ──")
        print(f"  Events with B1 data : {len(b1_discounts)}")
        print(f"  Avg discount        : {np.mean(b1_discounts):+.2f} pts")
        print(f"  Median discount     : {np.median(b1_discounts):+.2f} pts")
        print(f"  Min  (smallest dip) : {min(b1_discounts):+.2f} pts")
        print(f"  Max  (biggest dip)  : {max(b1_discounts):+.2f} pts")
        print(f"  Std dev             : {np.std(b1_discounts):.2f} pts")
        print(f"  Pctile 25/50/75     : "
              f"{np.percentile(b1_discounts,25):+.2f} / "
              f"{np.percentile(b1_discounts,50):+.2f} / "
              f"{np.percentile(b1_discounts,75):+.2f} pts")
        # B1 wait time
        b1_waits = []
        for e in cont_evs:
            if e['b1'] and e['b1'].get('time'):
                b1_t = e['b1']['time']
                a_t  = e['time']
                wait_min = (b1_t - a_t).total_seconds() / 60
                b1_waits.append(wait_min)
        if b1_waits:
            print(f"  Avg wait to B1      : {np.mean(b1_waits):.1f} min")
            print(f"  Max wait to B1      : {max(b1_waits):.0f} min")

    # Gain stats
    gains_from_a  = [e['gain_from_a']  for e in cont_evs if e['gain_from_a']  is not None]
    gains_from_b1 = [e['gain_from_b1'] for e in cont_evs if e['gain_from_b1'] is not None]
    if gains_from_a:
        print(f"\n  ── GAIN STATS (continuation events only) ──")
        print(f"  From A price → Hn/Ln:")
        print(f"    Avg  : {np.mean(gains_from_a):+.2f} pts")
        print(f"    Median:{np.median(gains_from_a):+.2f} pts")
        print(f"    Min  : {min(gains_from_a):+.2f} pts")
        print(f"    Max  : {max(gains_from_a):+.2f} pts")
        print(f"    25/50/75: {np.percentile(gains_from_a,25):+.2f} / "
              f"{np.percentile(gains_from_a,50):+.2f} / "
              f"{np.percentile(gains_from_a,75):+.2f} pts")
    if gains_from_b1:
        print(f"  From B1 price → Hn/Ln (optimal entry):")
        print(f"    Avg  : {np.mean(gains_from_b1):+.2f} pts")
        print(f"    Median:{np.median(gains_from_b1):+.2f} pts")
        print(f"    Min  : {min(gains_from_b1):+.2f} pts")
        print(f"    Max  : {max(gains_from_b1):+.2f} pts")

    # Reversal depth stats
    rev_depths = [e['reversal_depth_opt'] for e in rev_evs if e['reversal_depth_opt'] is not None]
    if rev_depths:
        print(f"\n  ── REVERSAL DEPTH (for HARDSL calibration) ──")
        print(f"  Events : {len(rev_depths)}")
        print(f"  Avg reversal drop : {np.mean(rev_depths):.2f} pts")
        print(f"  Max reversal drop : {max(rev_depths):.2f} pts")
        print(f"  25/50/75          : {np.percentile(rev_depths,25):.2f} / "
              f"{np.percentile(rev_depths,50):.2f} / "
              f"{np.percentile(rev_depths,75):.2f} pts")

    # ── Calibration recommendations ─────────────────────────────────
    print(f"\n{sep}")
    print("  CALIBRATION RECOMMENDATIONS")
    print(sep)
    if b1_discounts and gains_from_b1:
        med_disc = np.median(b1_discounts)
        p25_disc = np.percentile(b1_discounts, 25)
        med_gain = np.median(gains_from_b1)
        p75_gain = np.percentile(gains_from_b1, 75)
        avg_wait  = np.mean(b1_waits) if b1_waits else 15
        wait_bars = max(1, int(np.ceil(avg_wait / 5)))

        print(f"\n  LIMIT_OFFSET (buy below A price):")
        print(f"    Conservative (median dip) : {med_disc:.1f} pts → buy at signal_price - {med_disc:.0f}")
        print(f"    Aggressive   (25th pctile): {p25_disc:.1f} pts → buy at signal_price - {p25_disc:.0f}")
        print(f"\n  LIMIT_WINDOW (wait for fill):")
        print(f"    Avg wait to B1: {avg_wait:.1f} min → {wait_bars} × 5min bars (recommend {wait_bars + 1})")
        print(f"\n  VELVET ROPE / TARGET (peak trigger):")
        print(f"    Median gain from B1 : {med_gain:.1f} pts → set RI ≈ {int(med_gain * 0.5)}-{int(med_gain * 0.7)} pts")
        print(f"    75th pctile gain    : {p75_gain:.1f} pts → runner to {p75_gain:.0f} pts available")
        print(f"\n  ➤ Suggested params to test:")
        print(f"    LIMIT_OFFSET       = {max(3, int(med_disc))} (vs current 13)")
        print(f"    LIMIT_WINDOW_BARS  = {wait_bars + 1} (vs current 3)")
        print(f"    RI (Velvet Rope)   = {max(10, int(med_gain * 0.5))} (vs current 12)")

    print(f"\n{sep}\n")

# ── Main ──────────────────────────────────────────────────────────────
def main():
    print("=" * 80)
    print("  ORION DATA COLLECTOR")
    print("=" * 80)

    df_fut15 = load_futures()
    print(f"[FUT] Loaded {len(df_fut15)} bars  "
          f"({df_fut15['date'].iloc[0].date()} → {df_fut15['date'].iloc[-1].date()})")

    all_days = discover_days()
    if not all_days:
        print("[ERROR] No option data found in option_data/ subfolders.")
        print(f"  Expected: {OPT_BASES}")
        sys.exit(1)
    print(f"[OPT] {len(all_days)} days: {all_days[0]} → {all_days[-1]}")

    all_results = []
    for day_str in all_days:
        day_opt = load_day_options(day_str)
        if day_opt is None:
            all_results.append({'day': day_str, 'error': 'No option data', 'a_events': []})
            continue

        day_date = datetime.strptime(day_str, '%Y-%m-%d')
        IST_09_15 = day_date.replace(hour=9, minute=15)
        IST_15_30 = day_date.replace(hour=15, minute=30)
        fut_check = df_fut15[(df_fut15['date'] >= IST_09_15) &
                              (df_fut15['date'] <= IST_15_30)]
        if fut_check.empty:
            all_results.append({'day': day_str, 'error': 'No futures data', 'a_events': []})
            continue

        print(f"  Analysing {day_str} ...")
        result = analyse_day(day_str, df_fut15, day_opt)
        all_results.append(result)

    print_report(all_results)

    # Save report to file and push
    import io, builtins, subprocess
    buf = io.StringIO()
    orig = builtins.print
    def tee(*a, **k):
        orig(*a, **k)
        k.pop('file', None)
        orig(*a, file=buf, **k)
    builtins.print = tee
    print_report(all_results)
    builtins.print = orig

    out_path = os.path.join(REPO_DIR, 'data_collector_result.txt')
    with open(out_path, 'w') as f:
        f.write(buf.getvalue())
    orig(f"\n[SAVED] {out_path}")

if __name__ == '__main__':
    main()
