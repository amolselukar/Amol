"""
check_oi_24000.py — scan daily_option_data/{date}/CE|PE/{strike}.csv
for 24000 zone volume analysis. Uses latest date folder automatically.
"""
import os, sys, base64, glob
import pandas as pd
import requests

DATA_DIR = "/home/Selukar/daily_option_data"
BRANCH   = "claude/general-session-YfHuZ"
STRIKES  = [23700, 23800, 23900, 24000, 24100, 24200, 24300]

sys.path.insert(0, "/home/Selukar/Amol")
import credentials as _c
_PAT = getattr(_c, 'GITHUB_PAT', '')

# ── find latest date folder ───────────────────────────────────────
date_dirs = sorted([
    d for d in os.listdir(DATA_DIR)
    if os.path.isdir(os.path.join(DATA_DIR, d))
], reverse=True)
last_date = date_dirs[0]
print(f"Using date: {last_date}")

rows = []
for side in ['CE', 'PE']:
    side_dir = os.path.join(DATA_DIR, last_date, side)
    if not os.path.isdir(side_dir):
        print(f"[warn] {side_dir} not found")
        continue
    for strike in STRIKES:
        f = os.path.join(side_dir, f"{strike}.csv")
        if not os.path.exists(f):
            continue
        try:
            df = pd.read_csv(f)
            df.columns = [c.strip().lower() for c in df.columns]
            if 'tf' in df.columns:
                df = df[df['tf'] == '5m']
            if df.empty:
                continue
            vol_col   = next((c for c in df.columns if 'vol' in c), None)
            close_col = next((c for c in df.columns if 'close' in c), None)
            open_col  = next((c for c in df.columns if 'open'  in c), None)
            high_col  = next((c for c in df.columns if 'high'  in c), None)
            low_col   = next((c for c in df.columns if 'low'   in c), None)
            rows.append({
                'strike': strike,
                'side':   side,
                'open':   df[open_col].iloc[0]   if open_col  else 0,
                'high':   df[high_col].max()     if high_col  else 0,
                'low':    df[low_col].min()      if low_col   else 0,
                'close':  df[close_col].iloc[-1] if close_col else 0,
                'volume': int(df[vol_col].sum()) if vol_col   else 0,
                'bars':   len(df),
            })
        except Exception as e:
            print(f"  [warn] {f}: {e}")

# ── build output ──────────────────────────────────────────────────
lines = [f"=== 24000 Zone Volume Analysis — {last_date} ===\n"]

if not rows:
    lines.append("No data found. Check folder structure.")
else:
    df_out = pd.DataFrame(rows).sort_values(['strike', 'side'])

    lines.append(f"{'Strike':>8}  {'Side':4}  {'Open':>7}  {'High':>7}  {'Low':>7}  {'Close':>7}  {'Volume':>10}")
    lines.append("-" * 68)
    for _, r in df_out.iterrows():
        lines.append(
            f"{r['strike']:>8}  {r['side']:4}  {r['open']:>7.1f}  {r['high']:>7.1f}  "
            f"{r['low']:>7.1f}  {r['close']:>7.1f}  {r['volume']:>10,}"
        )

    lines.append("\n=== CE/PE Volume Ratio (>1 = more call buying = resistance above) ===")
    pivot = df_out.pivot_table(index='strike', columns='side', values='volume', aggfunc='sum')
    if 'CE' in pivot.columns and 'PE' in pivot.columns:
        for s in STRIKES:
            if s not in pivot.index:
                continue
            ce = pivot.loc[s, 'CE']; pe = pivot.loc[s, 'PE']
            ratio = ce / pe if pe > 0 else 99
            flag = " ← KEY LEVEL" if s == 24000 else ""
            lines.append(f"  {s}: CE={ce:>9,.0f}  PE={pe:>9,.0f}  ratio={ratio:.2f}{flag}")

    # 24000 detail
    k24 = df_out[df_out['strike'] == 24000]
    if not k24.empty:
        lines.append("\n=== 24000 Strike Detail ===")
        for _, r in k24.iterrows():
            lines.append(
                f"  {r['side']}: open={r['open']:.1f}  high={r['high']:.1f}  "
                f"low={r['low']:.1f}  close={r['close']:.1f}  vol={r['volume']:,}"
            )
        ce_row = k24[k24['side'] == 'CE']
        pe_row = k24[k24['side'] == 'PE']
        if not ce_row.empty and not pe_row.empty:
            ce_c = ce_row['close'].values[0]
            pe_c = pe_row['close'].values[0]
            lines.append(f"\n  Straddle at close : {ce_c + pe_c:.1f} pts")
            lines.append(f"  CE/PE close ratio : {ce_c/pe_c:.2f}  (>1 = CE costlier = bullish bias)")

out_text = "\n".join(lines)
print("\n" + out_text)

# ── push to GitHub ────────────────────────────────────────────────
if not _PAT:
    print("\n[warn] No GITHUB_PAT — skipping push"); sys.exit(0)

FNAME   = "oi_24000_result.txt"
API_URL = f"https://api.github.com/repos/amolselukar/Amol/contents/{FNAME}"
HEADERS = {"Authorization": f"token {_PAT}", "Accept": "application/vnd.github.v3+json"}
r = requests.get(API_URL, headers=HEADERS, params={"ref": BRANCH})
sha = r.json().get("sha") if r.status_code == 200 else None

payload = {"message": f"OI 24000 zone {last_date}", "branch": BRANCH,
           "content": base64.b64encode(out_text.encode()).decode()}
if sha:
    payload["sha"] = sha

r = requests.put(API_URL, headers=HEADERS, json=payload)
print(f"\n[{'OK' if r.status_code in (200,201) else 'error'}] Push: {r.status_code}")
