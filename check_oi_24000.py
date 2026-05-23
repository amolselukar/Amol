"""
check_oi_24000.py — scan daily_option_data for 24000 zone CE/PE volume.
Uses last available trading day if today has no data.
"""
import os, sys, json, base64, glob
import pandas as pd
from datetime import datetime, date, timedelta
import requests

DATA_DIR = "/home/Selukar/daily_option_data"
BRANCH   = "claude/general-session-YfHuZ"
STRIKES  = [23700, 23800, 23900, 24000, 24100, 24200, 24300]

sys.path.insert(0, "/home/Selukar/Amol")
import credentials as _c
_PAT = getattr(_c, 'GITHUB_PAT', '')

# ── peek at one file to understand structure ──────────────────────
all_files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
print(f"Files found: {len(all_files)}")
print(f"Sample: {[os.path.basename(f) for f in all_files[:15]]}")

# peek at a strike file
strike_files = [f for f in all_files if os.path.basename(f).replace('.csv','').isdigit()]
print(f"\nStrike-only files: {[os.path.basename(f) for f in strike_files[:10]]}")

if strike_files:
    sample = pd.read_csv(strike_files[0])
    print(f"\nColumns in {os.path.basename(strike_files[0])}: {list(sample.columns)}")
    print(sample.head(5).to_string())

# peek at atm_tracker if exists
atm_file = os.path.join(DATA_DIR, "atm_tracker_5m.csv")
if os.path.exists(atm_file):
    atm = pd.read_csv(atm_file)
    print(f"\nColumns in atm_tracker_5m.csv: {list(atm.columns)}")
    print(atm.tail(10).to_string())

# ── find last trading date in the data ───────────────────────────
def get_last_trading_date(files):
    """Find most recent date across all CSV files."""
    latest = None
    for f in files[:20]:
        try:
            df = pd.read_csv(f, nrows=5)
            df.columns = [c.strip().lower() for c in df.columns]
            date_col = next((c for c in df.columns if 'date' in c or 'time' in c), None)
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                mx = df[date_col].max()
                if pd.notna(mx):
                    d = mx.date()
                    if latest is None or d > latest:
                        latest = d
        except:
            pass
    return latest

last_date = get_last_trading_date(all_files)
print(f"\nLast trading date found: {last_date}")

# ── main analysis ─────────────────────────────────────────────────
lines = []
lines.append(f"=== 24000 Zone OI/Volume Analysis — Last trading day: {last_date} ===\n")

rows = []
for f in strike_files:
    strike_str = os.path.basename(f).replace('.csv', '')
    try:
        strike = int(strike_str)
    except:
        continue
    if strike not in STRIKES:
        continue

    try:
        df = pd.read_csv(f)
        df.columns = [c.strip().lower() for c in df.columns]

        # find date column
        date_col = next((c for c in df.columns if 'date' in c or 'time' in c), None)
        if not date_col:
            continue
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

        # filter last trading date
        if last_date:
            df = df[df[date_col].dt.date == last_date]

        # filter 5m if tf column exists
        if 'tf' in df.columns:
            df = df[df['tf'] == '5m']

        if df.empty:
            continue

        # detect if CE/PE is a column or separate files
        if 'side' in df.columns or 'type' in df.columns:
            type_col = 'side' if 'side' in df.columns else 'type'
            for side in ['CE', 'PE']:
                s = df[df[type_col].str.upper() == side]
                if s.empty:
                    continue
                rows.append(_build_row(strike, side, s))
        elif 'ce_close' in df.columns or 'ce_volume' in df.columns:
            # wide format: CE and PE in same row
            for side in ['CE', 'PE']:
                p = side.lower()
                row = {
                    'strike': strike, 'side': side,
                    'open':   df.get(f'{p}_open', pd.Series([0])).iloc[0],
                    'high':   df.get(f'{p}_high', pd.Series([0])).max(),
                    'low':    df.get(f'{p}_low',  pd.Series([0])).min(),
                    'close':  df.get(f'{p}_close', pd.Series([0])).iloc[-1],
                    'volume': int(df.get(f'{p}_volume', pd.Series([0])).sum()),
                    'bars':   len(df)
                }
                rows.append(row)
        else:
            # assume file has both CE+PE stacked or only one side — check close column
            vol_col    = next((c for c in df.columns if 'vol' in c), None)
            close_col  = next((c for c in df.columns if 'close' in c), None)
            open_col   = next((c for c in df.columns if 'open' in c), None)
            high_col   = next((c for c in df.columns if 'high' in c), None)
            low_col    = next((c for c in df.columns if 'low' in c), None)
            if close_col:
                rows.append({
                    'strike': strike, 'side': '?',
                    'open':   df[open_col].iloc[0]  if open_col  else 0,
                    'high':   df[high_col].max()    if high_col  else 0,
                    'low':    df[low_col].min()      if low_col   else 0,
                    'close':  df[close_col].iloc[-1],
                    'volume': int(df[vol_col].sum()) if vol_col   else 0,
                    'bars':   len(df)
                })
    except Exception as e:
        print(f"  [warn] {f}: {e}")

def _build_row(strike, side, df):
    vc = next((c for c in df.columns if 'vol' in c), None)
    return {
        'strike': strike, 'side': side,
        'open':   df['open'].iloc[0]   if 'open'  in df.columns else 0,
        'high':   df['high'].max()     if 'high'  in df.columns else 0,
        'low':    df['low'].min()      if 'low'   in df.columns else 0,
        'close':  df['close'].iloc[-1] if 'close' in df.columns else 0,
        'volume': int(df[vc].sum())    if vc else 0,
        'bars':   len(df)
    }

if not rows:
    lines.append("Could not parse strike data. See raw column dump above.\n")
    lines.append(f"Strike files checked: {[os.path.basename(f) for f in strike_files]}\n")
else:
    df_out = pd.DataFrame(rows).sort_values(['strike', 'side'])
    lines.append(f"{'Strike':>8}  {'Side':4}  {'Open':>7}  {'High':>7}  {'Low':>7}  {'Close':>7}  {'Volume':>10}")
    lines.append("-" * 68)
    for _, r in df_out.iterrows():
        lines.append(
            f"{r['strike']:>8}  {r['side']:4}  {r['open']:>7.1f}  {r['high']:>7.1f}  "
            f"{r['low']:>7.1f}  {r['close']:>7.1f}  {r['volume']:>10,}"
        )

    # CE/PE ratio
    lines.append("\n=== CE/PE Volume Ratio ===")
    pivot = df_out[df_out['side'].isin(['CE','PE'])].pivot_table(
        index='strike', columns='side', values='volume', aggfunc='sum')
    if 'CE' in pivot.columns and 'PE' in pivot.columns:
        for s in STRIKES:
            if s in pivot.index:
                ce = pivot.loc[s, 'CE']; pe = pivot.loc[s, 'PE']
                ratio = ce/pe if pe > 0 else 99
                flag = " ← KEY RESISTANCE" if s == 24000 else ""
                lines.append(f"  {s}: CE={ce:>8,.0f}  PE={pe:>8,.0f}  ratio={ratio:.2f}{flag}")

out_text = "\n".join(lines)
print("\n" + out_text)

# ── push to GitHub ────────────────────────────────────────────────
if not _PAT:
    print("\n[warn] No GITHUB_PAT — skipping push")
    sys.exit(0)

FNAME   = "oi_24000_result.txt"
API_URL = f"https://api.github.com/repos/amolselukar/Amol/contents/{FNAME}"
HEADERS = {"Authorization": f"token {_PAT}", "Accept": "application/vnd.github.v3+json"}
sha = None
r = requests.get(API_URL, headers=HEADERS, params={"ref": BRANCH})
if r.status_code == 200:
    sha = r.json().get("sha")

payload = {
    "message": f"OI 24000 zone analysis {last_date}",
    "content": base64.b64encode(out_text.encode()).decode(),
    "branch":  BRANCH,
}
if sha:
    payload["sha"] = sha

r = requests.put(API_URL, headers=HEADERS, json=payload)
print(f"\n[{'OK' if r.status_code in (200,201) else 'error'}] Push: {r.status_code}")
