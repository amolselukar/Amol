"""
check_oi_24000.py — scan today's daily_option_data for 24000 CE/PE
and nearby strikes; push summary to GitHub.
"""
import os, sys, json, base64, glob
import pandas as pd
from datetime import datetime, date
import requests

DATA_DIR = "/home/Selukar/daily_option_data"
TODAY    = date.today().strftime("%Y-%m-%d")
BRANCH   = "claude/general-session-YfHuZ"
STRIKES  = [23700, 23800, 23900, 24000, 24100, 24200, 24300]

# ── load credentials ──────────────────────────────────────────────
sys.path.insert(0, "/home/Selukar/Amol")
import credentials as _c
_PAT = getattr(_c, 'GITHUB_PAT', '')

# ── find all CSV files ────────────────────────────────────────────
all_files = glob.glob(os.path.join(DATA_DIR, "**", "*.csv"), recursive=True)

rows = []
for f in all_files:
    fname = os.path.basename(f)
    # expect format like NIFTY24000CE.csv or similar
    for strike in STRIKES:
        for side in ['CE', 'PE']:
            if str(strike) in fname and side in fname.upper():
                try:
                    df = pd.read_csv(f)
                    # filter today's 5m bars
                    df.columns = [c.strip().lower() for c in df.columns]
                    if 'date' not in df.columns:
                        continue
                    df['date'] = pd.to_datetime(df['date'], errors='coerce')
                    mask = (df['date'].dt.date == date.today()) & (df.get('tf', pd.Series(['5m']*len(df))) == '5m')
                    # handle tf column presence
                    if 'tf' in df.columns:
                        today_df = df[(df['date'].dt.date == date.today()) & (df['tf'] == '5m')]
                    else:
                        today_df = df[df['date'].dt.date == date.today()]

                    if today_df.empty:
                        continue

                    open_  = today_df['open'].iloc[0]
                    close_ = today_df['close'].iloc[-1]
                    high_  = today_df['high'].max()
                    low_   = today_df['low'].min()
                    vol    = today_df['volume'].sum() if 'volume' in today_df.columns else 0
                    bars   = len(today_df)

                    rows.append({
                        'strike': strike,
                        'side':   side,
                        'open':   open_,
                        'high':   high_,
                        'low':    low_,
                        'close':  close_,
                        'volume': int(vol),
                        'bars':   bars
                    })
                except Exception as e:
                    print(f"  [warn] {f}: {e}")

# ── build output ──────────────────────────────────────────────────
lines = []
lines.append(f"=== 24000 Zone OI/Volume Analysis — {TODAY} ===\n")

if not rows:
    lines.append("No data found for today. Check if daily_option_data has today's files.\n")
    lines.append(f"DATA_DIR: {DATA_DIR}\n")
    lines.append(f"Files found: {len(all_files)}\n")
    sample = [os.path.basename(f) for f in all_files[:10]]
    lines.append(f"Sample files: {sample}\n")
else:
    df_out = pd.DataFrame(rows).sort_values(['strike', 'side'])

    lines.append(f"{'Strike':>8}  {'Side':4}  {'Open':>7}  {'High':>7}  {'Low':>7}  {'Close':>7}  {'Volume':>10}  {'Bars':>5}")
    lines.append("-" * 72)
    for _, r in df_out.iterrows():
        lines.append(
            f"{r['strike']:>8}  {r['side']:4}  {r['open']:>7.1f}  {r['high']:>7.1f}  "
            f"{r['low']:>7.1f}  {r['close']:>7.1f}  {r['volume']:>10,}  {r['bars']:>5}"
        )

    lines.append("")
    # CE vs PE volume ratio at each strike
    lines.append("=== CE/PE Volume Ratio (>1 = more calls = bulls paying) ===")
    pivot = df_out.pivot_table(index='strike', columns='side', values='volume', aggfunc='sum')
    if 'CE' in pivot and 'PE' in pivot:
        for strike in STRIKES:
            if strike in pivot.index:
                ce_vol = pivot.loc[strike, 'CE'] if 'CE' in pivot.columns else 0
                pe_vol = pivot.loc[strike, 'PE'] if 'PE' in pivot.columns else 0
                ratio  = ce_vol / pe_vol if pe_vol > 0 else float('inf')
                flag   = " ← WATCH" if strike == 24000 else ""
                lines.append(f"  {strike}: CE={ce_vol:>8,}  PE={pe_vol:>8,}  ratio={ratio:.2f}{flag}")

    lines.append("")
    # Highlight 24000
    k24 = df_out[df_out['strike'] == 24000]
    if not k24.empty:
        lines.append("=== 24000 Detailed ===")
        for _, r in k24.iterrows():
            chg = r['close'] - r['open']
            lines.append(f"  {r['side']}: open={r['open']:.1f}  close={r['close']:.1f}  "
                         f"chg={chg:+.1f}  high={r['high']:.1f}  vol={r['volume']:,}")
        ce = k24[k24['side']=='CE']
        pe = k24[k24['side']=='PE']
        if not ce.empty and not pe.empty:
            ce_close = ce['close'].values[0]
            pe_close = pe['close'].values[0]
            lines.append(f"\n  Straddle premium at close: {ce_close + pe_close:.1f}")
            lines.append(f"  CE/PE close ratio: {ce_close/pe_close:.2f} (>1 = CE costlier = bullish bias)")

out_text = "\n".join(lines)
print(out_text)

# ── push to GitHub ────────────────────────────────────────────────
if not _PAT:
    print("\n[warn] No GITHUB_PAT — skipping push")
    sys.exit(0)

FNAME   = "oi_24000_result.txt"
API_URL = f"https://api.github.com/repos/amolselukar/Amol/contents/{FNAME}"
REMOTE  = f"https://{_PAT}@github.com/amolselukar/Amol.git"
HEADERS = {"Authorization": f"token {_PAT}", "Accept": "application/vnd.github.v3+json"}

# get existing sha if file exists
sha = None
r = requests.get(API_URL, headers=HEADERS, params={"ref": BRANCH})
if r.status_code == 200:
    sha = r.json().get("sha")

payload = {
    "message": f"OI 24000 zone analysis {TODAY}",
    "content": base64.b64encode(out_text.encode()).decode(),
    "branch":  BRANCH,
}
if sha:
    payload["sha"] = sha

r = requests.put(API_URL, headers=HEADERS, json=payload)
if r.status_code in (200, 201):
    print(f"\n[OK] Pushed {FNAME} to GitHub.")
else:
    print(f"\n[error] Push failed: {r.status_code} {r.text[:200]}")
