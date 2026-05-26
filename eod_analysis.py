#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eod_analysis.py  --  ORION End-of-Day OI Analysis
===================================================
Reads today's _oi_survey.json (written by Optiondata_1.py),
computes key support/resistance levels from option OI + volume,
writes next_day_plan.json and pushes to GitHub, sends Telegram.

Can be called from Optiondata_1.py or run standalone:
    python3 eod_analysis.py [YYYY-MM-DD]

Output: daily_option_data/{date}/next_day_plan.json
        GitHub: next_day_plan.json (root of repo)
"""

import sys
import os
import json
import base64
import math
from datetime import date, datetime, timedelta

import requests

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
DATA_ROOT  = "/home/Selukar/daily_option_data"
REPO       = "amolselukar/Amol"
BRANCH     = "claude/general-session-YfHuZ"
GITHUB_FILE = "next_day_plan.json"

# OI classification thresholds (standard deviations above mean)
OI_MASSIVE_STD      = 2.0   # > mean + 2*std  -> WALL (Grade A trigger)
OI_SIGNIFICANT_STD  = 1.0   # > mean + 1*std  -> SIGNIFICANT (Grade B trigger)

# Expiry caution: if days_to_expiry <= this, suppress OI trade triggers
EXPIRY_CAUTION_DAYS = 2

# Minimum OI increase from yesterday for fresh-buildup confirmation
# (as % of yesterday's OI; 0 = any increase qualifies)
MIN_OI_INCREASE_PCT = 0.0

# ---------------------------------------------------------------------------
# V3 PRICE CLUSTER CONFIG  (must match ORION_PAPER_V2_5_12.py constants)
# ---------------------------------------------------------------------------
_V3_CLUSTER_RADIUS    = 20    # pts — merge sources within this window
_V3_GRADE_A_MIN       = 3    # distinct source kinds for Grade A
_V3_GRADE_B_MIN       = 2    # distinct source kinds for Grade B
_V3_SWING_LOOKBACK    = 20   # 1h bars back for swing pivot detection
_V3_SWING_N           = 3    # bars each side that must be lower/higher
_V3_ROUND_STEP        = 50   # round-level grid step (50pt)
_V3_ROUND_RANGE       = 300  # PDC ± this range for round levels
_V3_PDC_BUFFER        = 25   # min gap between G/R and PDC
_V3_PROMOTE_R100_BAND = 200  # round_100 standalone promotion band from PDC
_V3_PROMOTE_SWING_BAND = 300 # swing pivot standalone promotion band from PDC

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def _load_creds():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import credentials as c
        return {
            'pat':           getattr(c, 'GITHUB_PAT', ''),
            'tg_token':      getattr(c, 'TELEGRAM_BOT_TOKEN', ''),
            'tg_chat':       getattr(c, 'TELEGRAM_CHAT_ID', ''),
        }
    except ImportError:
        return {}


def _latest_date_dir(root):
    dirs = sorted([
        d for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d)) and d[:4].isdigit()
    ], reverse=True)
    return dirs[0] if dirs else None


def _load_survey(root, date_str):
    path = os.path.join(root, date_str, "_oi_survey.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _prev_trading_date(date_str):
    """Previous trading date (skip weekends)."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    for _ in range(7):
        d -= timedelta(days=1)
        if d.weekday() < 5:
            return d.strftime("%Y-%m-%d")
    return None


def _days_to_expiry(expiry_str, from_date_str):
    try:
        exp = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        frm = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        return (exp - frm).days
    except Exception:
        return 99


def _classify_oi(oi_values):
    """
    Given a list of OI values, return (mean, std, threshold_massive, threshold_significant).
    Uses only non-zero values for stats.
    """
    nonzero = [v for v in oi_values if v > 0]
    if len(nonzero) < 2:
        return 0, 0, 0, 0
    mean = sum(nonzero) / len(nonzero)
    variance = sum((v - mean) ** 2 for v in nonzero) / len(nonzero)
    std = math.sqrt(variance)
    return mean, std, mean + OI_MASSIVE_STD * std, mean + OI_SIGNIFICANT_STD * std


# ---------------------------------------------------------------------------
# V3 PRICE CLUSTER HELPERS  (same algorithm as ORION_PAPER_V2_5_12.py)
# ---------------------------------------------------------------------------
def _find_swing_pivots(df):
    pivots = []
    n = _V3_SWING_N
    sub = df.iloc[-(_V3_SWING_LOOKBACK + 2*n):].copy().reset_index(drop=True)
    if len(sub) < 2*n + 1:
        return pivots
    for i in range(n, len(sub) - n):
        h = float(sub['high'].iloc[i])
        l = float(sub['low'].iloc[i])
        is_h = all(h > float(sub['high'].iloc[i-k]) for k in range(1, n+1)) and \
               all(h > float(sub['high'].iloc[i+k]) for k in range(1, n+1))
        is_l = all(l < float(sub['low'].iloc[i-k])  for k in range(1, n+1)) and \
               all(l < float(sub['low'].iloc[i+k])  for k in range(1, n+1))
        if is_h: pivots.append((h, 'swing_high'))
        if is_l: pivots.append((l, 'swing_low'))
    return pivots


def _generate_round_levels(price):
    out = set()
    base = round(price / _V3_ROUND_STEP) * _V3_ROUND_STEP
    for off in range(-_V3_ROUND_RANGE, _V3_ROUND_RANGE + 1, _V3_ROUND_STEP):
        p = base + off
        kind = 'round_100' if p % 100 == 0 else 'round_50'
        out.add((float(p), kind))
    return list(out)


def _cluster_levels(sources):
    if not sources: return []
    s = sorted(sources, key=lambda x: x[0])
    clusters, cur = [], [s[0]]
    for p, k in s[1:]:
        if p - cur[-1][0] <= _V3_CLUSTER_RADIUS:
            cur.append((p, k))
        else:
            clusters.append(cur); cur = [(p, k)]
    clusters.append(cur)
    out = []
    for c in clusters:
        kinds = set(k for _, k in c)
        center = sum(p for p, _ in c) / len(c)
        n = len(kinds)
        grade = 'A' if n >= _V3_GRADE_A_MIN else ('B' if n >= _V3_GRADE_B_MIN else 'C')
        out.append({'center': round(center, 1), 'kinds': sorted(kinds), 'grade': grade})
    return out


def _compute_price_clusters(data_root, date_str):
    """
    Compute V3 price-action S/R clusters from nifty_1h.csv.
    Uses same algorithm as compute_levels_for_day() in the paper bot.
    PDH/PDL/PDC = today's session H/L/C (last 7 1h bars).
    Always computed regardless of expiry_caution.
    Returns dict or None on failure.
    """
    try:
        import pandas as pd
    except ImportError:
        return None

    path = os.path.join(data_root, date_str, "nifty_1h.csv")
    if not os.path.exists(path):
        return None

    try:
        df = pd.read_csv(path)
        if df.empty or 'high' not in df.columns or len(df) < 8:
            return None

        # Last 7 1h bars = today's trading session (~6.25h)
        pdh = float(df['high'].iloc[-7:].max())
        pdl = float(df['low'].iloc[-7:].min())
        pdc = float(df['close'].iloc[-1])

        # Build sources: PDH + PDL (PDC excluded per V3_EXCLUDE_PDC_FROM_CLUSTERS)
        src = [(pdh, 'PDH'), (pdl, 'PDL')]
        src += _generate_round_levels(pdc)
        swing_pivots = _find_swing_pivots(df)
        src += swing_pivots
        # Restrict to ±ROUND_RANGE of PDC
        src = [s for s in src if abs(s[0] - pdc) <= _V3_ROUND_RANGE]

        clusters = _cluster_levels(src)

        # Promote singletons: PDH/PDL/round_100/swing pivots → standalone Grade B
        def _in_ab(price):
            for c in clusters:
                if c['grade'] in ('A', 'B') and abs(c['center'] - price) <= _V3_CLUSTER_RADIUS:
                    return True
            return False

        promoted = []
        for p, kind in [(pdh, 'PDH'), (pdl, 'PDL')]:
            if not _in_ab(p):
                promoted.append({'center': round(p, 1), 'kinds': [kind], 'grade': 'B', 'promoted': True})
        base = round(pdc / 100) * 100
        for off in range(-_V3_PROMOTE_R100_BAND, _V3_PROMOTE_R100_BAND + 1, 100):
            p = float(base + off)
            if not _in_ab(p):
                promoted.append({'center': round(p, 1), 'kinds': ['round_100'], 'grade': 'B', 'promoted': True})
        for p, kind in swing_pivots:
            if abs(p - pdc) <= _V3_PROMOTE_SWING_BAND and not _in_ab(p):
                promoted.append({'center': round(p, 1), 'kinds': [kind], 'grade': 'B', 'promoted': True})

        all_levels = clusters + promoted

        buf = _V3_PDC_BUFFER
        above = [c for c in all_levels if c['center'] > pdc + buf and c['grade'] in ('A', 'B')]
        below = [c for c in all_levels if c['center'] < pdc - buf and c['grade'] in ('A', 'B')]
        above.sort(key=lambda c: (0 if c['grade'] == 'A' else 1, abs(c['center'] - pdc)))
        below.sort(key=lambda c: (0 if c['grade'] == 'A' else 1, abs(c['center'] - pdc)))

        return {
            'pdh': round(pdh, 1),
            'pdl': round(pdl, 1),
            'pdc': round(pdc, 1),
            'clusters_above': above,
            'clusters_below': below,
        }
    except Exception as e:
        print(f"[eod_analysis] Price cluster computation failed: {e}")
        return None


def _push_github(content_str, pat, filename=GITHUB_FILE):
    if not pat:
        return False
    api_url = f"https://api.github.com/repos/{REPO}/contents/{filename}"
    headers = {"Authorization": f"token {pat}",
                "Accept": "application/vnd.github.v3+json"}
    r = requests.get(api_url, headers=headers, params={"ref": BRANCH})
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {
        "message": f"EOD OI plan {datetime.now().strftime('%Y-%m-%d')}",
        "content": base64.b64encode(content_str.encode()).decode(),
        "branch":  BRANCH,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(api_url, headers=headers, json=payload)
    return r.status_code in (200, 201)


def _send_telegram(text, tg_token, tg_chat):
    if not tg_token or not tg_chat:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{tg_token}/sendMessage",
            data={"chat_id": tg_chat, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# MAIN ANALYSIS
# ---------------------------------------------------------------------------
def run(date_str=None, data_root=DATA_ROOT):
    creds = _load_creds()

    if date_str is None:
        date_str = _latest_date_dir(data_root)
    if date_str is None:
        print("[eod_analysis] No date folder found.")
        return None

    print(f"\n[EOD] Running analysis for {date_str}")

    survey = _load_survey(data_root, date_str)
    if survey is None:
        print(f"[eod_analysis] No _oi_survey.json for {date_str}. Run Optiondata_1.py first.")
        return None

    prev_date = _prev_trading_date(date_str)
    prev_survey = _load_survey(data_root, prev_date) if prev_date else None

    strikes_data = survey.get("strikes", {})
    if not strikes_data:
        print("[eod_analysis] Empty strikes data in survey.")
        return None

    expiry_str      = survey.get("expiry", "")
    monthly_expiry  = survey.get("monthly_expiry", "")
    atm             = survey.get("atm", 0)
    days_to_exp     = _days_to_expiry(expiry_str, date_str)
    is_expiry_day   = (days_to_exp == 0)
    expiry_caution  = (days_to_exp <= EXPIRY_CAUTION_DAYS)
    is_monthly_exp  = (expiry_str == monthly_expiry)

    # ---- collect OI arrays ----
    all_strikes = sorted(int(s) for s in strikes_data.keys())
    ce_oi_map   = {}
    pe_oi_map   = {}
    ce_vol_map  = {}
    pe_vol_map  = {}
    ce_ltp_map  = {}
    pe_ltp_map  = {}

    for s in all_strikes:
        sd = strikes_data.get(str(s), {})
        ce = sd.get("CE", {})
        pe = sd.get("PE", {})
        ce_oi_map[s]  = ce.get("oi",  0)
        pe_oi_map[s]  = pe.get("oi",  0)
        ce_vol_map[s] = ce.get("volume", 0)
        pe_vol_map[s] = pe.get("volume", 0)
        ce_ltp_map[s] = ce.get("ltp", 0)
        pe_ltp_map[s] = pe.get("ltp", 0)

    # ---- OI change from yesterday ----
    ce_oi_chg = {}
    pe_oi_chg = {}
    if prev_survey:
        prev_strikes = prev_survey.get("strikes", {})
        for s in all_strikes:
            ps = prev_strikes.get(str(s), {})
            ce_oi_chg[s] = ce_oi_map[s] - ps.get("CE", {}).get("oi", 0)
            pe_oi_chg[s] = pe_oi_map[s] - ps.get("PE", {}).get("oi", 0)
    else:
        for s in all_strikes:
            ce_oi_chg[s] = 0
            pe_oi_chg[s] = 0

    # ---- OI classification ----
    ce_mean, ce_std, ce_wall_thresh, ce_sig_thresh = _classify_oi(list(ce_oi_map.values()))
    pe_mean, pe_std, pe_wall_thresh, pe_sig_thresh = _classify_oi(list(pe_oi_map.values()))

    # ---- PCR (Put-Call Ratio) ----
    total_ce_oi = sum(ce_oi_map.values())
    total_pe_oi = sum(pe_oi_map.values())
    pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1.0
    if pcr >= 1.2:
        bias = "BULLISH"
    elif pcr <= 0.8:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    # ---- Max Pain ----
    # For each potential expiry level, compute total pain for option buyers
    max_pain = atm
    min_pain_val = float('inf')
    for ep in all_strikes:
        pain = sum(max(0, ep - s) * ce_oi_map[s] for s in all_strikes)
        pain += sum(max(0, s - ep) * pe_oi_map[s] for s in all_strikes)
        if pain < min_pain_val:
            min_pain_val = pain
            max_pain = ep

    # ---- Classify each strike ----
    resistance_levels = []   # CE walls above ATM
    support_levels    = []   # PE walls below ATM
    info_levels       = []   # Significant but not confirmed

    for s in all_strikes:
        ce_oi = ce_oi_map[s]
        pe_oi = pe_oi_map[s]
        ce_chg = ce_oi_chg[s]
        pe_chg = pe_oi_chg[s]
        ce_fresh = (ce_chg > 0) or (prev_survey is None)
        pe_fresh = (pe_chg > 0) or (prev_survey is None)

        # CE wall (resistance) — strike ABOVE ATM with massive CE OI
        if s >= atm and ce_oi >= ce_wall_thresh and ce_fresh and not expiry_caution:
            resistance_levels.append({
                "strike": s, "ce_oi": ce_oi, "ce_oi_chg": ce_chg,
                "ce_vol": ce_vol_map[s], "ltp": ce_ltp_map[s],
                "signal": "WALL", "grade": "A"
            })
        elif s >= atm and ce_oi >= ce_sig_thresh and ce_fresh and not expiry_caution:
            resistance_levels.append({
                "strike": s, "ce_oi": ce_oi, "ce_oi_chg": ce_chg,
                "ce_vol": ce_vol_map[s], "ltp": ce_ltp_map[s],
                "signal": "SIGNIFICANT", "grade": "B"
            })
        elif s >= atm and ce_oi >= ce_sig_thresh:
            info_levels.append({"strike": s, "side": "CE", "reason": "OI significant but stale/expiry caution"})

        # PE wall (support) — strike BELOW ATM with massive PE OI
        if s <= atm and pe_oi >= pe_wall_thresh and pe_fresh and not expiry_caution:
            support_levels.append({
                "strike": s, "pe_oi": pe_oi, "pe_oi_chg": pe_chg,
                "pe_vol": pe_vol_map[s], "ltp": pe_ltp_map[s],
                "signal": "WALL", "grade": "A"
            })
        elif s <= atm and pe_oi >= pe_sig_thresh and pe_fresh and not expiry_caution:
            support_levels.append({
                "strike": s, "pe_oi": pe_oi, "pe_oi_chg": pe_chg,
                "pe_vol": pe_vol_map[s], "ltp": pe_ltp_map[s],
                "signal": "SIGNIFICANT", "grade": "B"
            })
        elif s <= atm and pe_oi >= pe_sig_thresh:
            info_levels.append({"strike": s, "side": "PE", "reason": "OI significant but stale/expiry caution"})

    # Sort: resistance ascending (nearest first), support descending (nearest first)
    resistance_levels.sort(key=lambda x: x["strike"])
    support_levels.sort(key=lambda x: x["strike"], reverse=True)

    # V3 triggers: only WALL + SIGNIFICANT with confirmed fresh OI
    v3_resistance = [r["strike"] for r in resistance_levels]
    v3_support    = [s["strike"] for s in support_levels]

    # ---- V3 PRICE CLUSTERS (PDH/PDL/round/swing) — always computed ----
    price_clusters = _compute_price_clusters(data_root, date_str)
    if price_clusters:
        print(f"[EOD] Price clusters: PDH={price_clusters['pdh']} PDL={price_clusters['pdl']} PDC={price_clusters['pdc']}")
        print(f"      Above PDC: {price_clusters['clusters_above'][:5]}")
        print(f"      Below PDC: {price_clusters['clusters_below'][:5]}")
    else:
        print("[EOD] Price clusters: nifty_1h.csv not available yet — will compute at bot boot")

    # ---- Straddle at ATM ----
    straddle = ce_ltp_map.get(atm, 0) + pe_ltp_map.get(atm, 0)

    # ---- Build plan ----
    plan = {
        "date":             date_str,
        "for_date":         (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"),
        "generated_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "atm":              atm,
        "expiry":           expiry_str,
        "monthly_expiry":   monthly_expiry,
        "is_monthly_expiry": is_monthly_exp,
        "days_to_expiry":   days_to_exp,
        "expiry_caution":   expiry_caution,
        "is_expiry_day":    is_expiry_day,
        "pcr":              round(pcr, 3),
        "bias":             bias,
        "max_pain":         max_pain,
        "straddle_atm":     round(straddle, 1),
        "oi_stats": {
            "ce_mean": round(ce_mean), "ce_std": round(ce_std),
            "pe_mean": round(pe_mean), "pe_std": round(pe_std),
            "ce_wall_threshold": round(ce_wall_thresh),
            "pe_wall_threshold": round(pe_wall_thresh),
        },
        "resistance_levels": resistance_levels,
        "support_levels":    support_levels,
        "info_levels":       info_levels,
        "v3_resistance":     v3_resistance,
        "v3_support":        v3_support,
        "price_clusters":    price_clusters,
    }

    # ---- Save to date folder ----
    plan_path = os.path.join(data_root, date_str, "next_day_plan.json")
    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=2)
    print(f"[EOD] Saved: {plan_path}")

    # ---- Push to GitHub root (so paper bot can find it on fresh pull) ----
    plan_json = json.dumps(plan, indent=2)
    pat = creds.get("pat", "")
    if pat:
        ok = _push_github(plan_json, pat)
        print(f"[EOD] GitHub push: {'OK' if ok else 'FAILED'}")
    else:
        print("[EOD] No GITHUB_PAT — skipping push")

    # ---- Build Telegram summary ----
    exp_flag = ""
    if is_expiry_day:
        exp_flag = " | EXPIRY DAY — OI unreliable"
    elif expiry_caution:
        exp_flag = f" | T-{days_to_exp} to expiry — use caution"
    elif is_monthly_exp:
        exp_flag = " | MONTHLY EXPIRY WEEK"

    tg_lines = [
        f"<b>ORION EOD OI Plan — {date_str}</b>{exp_flag}",
        f"ATM: {atm} | PCR: {pcr:.2f} | Bias: <b>{bias}</b> | Max Pain: {max_pain}",
        f"Straddle (ATM): {straddle:.0f} | Expiry: {expiry_str} ({days_to_exp}d)",
        "",
    ]

    if resistance_levels:
        tg_lines.append("<b>Resistance (CE Walls):</b>")
        for r in resistance_levels[:4]:
            chg = f" chg:{r['ce_oi_chg']:+,.0f}" if r['ce_oi_chg'] != 0 else ""
            tg_lines.append(f"  {r['strike']} [{r['signal']}] OI:{r['ce_oi']:,.0f}{chg}")
    else:
        tg_lines.append("No significant CE resistance identified")

    tg_lines.append("")
    if support_levels:
        tg_lines.append("<b>Support (PE Walls):</b>")
        for s in support_levels[:4]:
            chg = f" chg:{s['pe_oi_chg']:+,.0f}" if s['pe_oi_chg'] != 0 else ""
            tg_lines.append(f"  {s['strike']} [{s['signal']}] OI:{s['pe_oi']:,.0f}{chg}")
    else:
        tg_lines.append("No significant PE support identified")

    tg_lines.append("")
    if v3_resistance or v3_support:
        tg_lines.append(f"V3 OI triggers: R={v3_resistance} | S={v3_support}")

    # ---- V3 Price-action levels (always shown, expiry_caution does NOT suppress) ----
    tg_lines.append("")
    tg_lines.append("<b>V3 Price Levels (PDH/PDL/round/swing — always active):</b>")
    if price_clusters:
        tg_lines.append(
            f"PDH: {price_clusters['pdh']} | PDL: {price_clusters['pdl']} | PDC: {price_clusters['pdc']}"
        )
        above = price_clusters['clusters_above'][:6]
        below = price_clusters['clusters_below'][:6]
        if above:
            parts = []
            for c in above:
                kinds = "+".join(c['kinds'])
                parts.append(f"{c['center']:.0f}[{c['grade']}:{kinds}]")
            tg_lines.append(f"  Resistance: {' | '.join(parts)}")
        if below:
            parts = []
            for c in below:
                kinds = "+".join(c['kinds'])
                parts.append(f"{c['center']:.0f}[{c['grade']}:{kinds}]")
            tg_lines.append(f"  Support:    {' | '.join(parts)}")
    else:
        tg_lines.append("  (nifty_1h.csv not found — levels computed at bot boot)")

    tg_msg = "\n".join(tg_lines)
    print("\n" + tg_msg)

    _send_telegram(tg_msg, creds.get("tg_token", ""), creds.get("tg_chat", ""))

    print(f"\n[EOD] Analysis complete for {date_str}")
    return plan


# ---------------------------------------------------------------------------
# STANDALONE ENTRY POINT
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    result = run(date_str=date_arg)
    if result is None:
        sys.exit(1)
