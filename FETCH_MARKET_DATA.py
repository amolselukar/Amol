"""
FETCH_MARKET_DATA.py
====================
Run ONCE on PythonAnywhere to fetch and save Nifty Futures 15m data.
Saves to market_data/nifty_fut_15m.csv and pushes to GitHub.
After this, ORION_DATA_COLLECTOR.py can run in Claude environment.

Usage:
    cd ~/Amol
    python FETCH_MARKET_DATA.py
"""
import os, sys, subprocess
import pandas as pd
from datetime import datetime, timedelta, date

REPO_DIR   = os.path.dirname(os.path.abspath(__file__))
OUT_DIR    = os.path.join(REPO_DIR, 'market_data')
FUT_FILE   = os.path.join(OUT_DIR, 'nifty_fut_15m.csv')
BRANCH     = 'claude/general-session-YfHuZ'

DATA_BASES = [
    "/home/Selukar/daily_option_data",
    "/home/Amol/daily_option_data",
]

sys.path.insert(0, REPO_DIR)
try:
    import credentials as _c
    KITE_API_KEY      = _c.KITE_API_KEY
    KITE_ACCESS_TOKEN = _c.KITE_ACCESS_TOKEN
    GITHUB_PAT        = getattr(_c, 'GITHUB_PAT', None)
except (ImportError, AttributeError) as e:
    print(f"[ERROR] credentials.py: {e}"); sys.exit(1)

from kiteconnect import KiteConnect

def discover_days():
    days = set()
    for base in DATA_BASES:
        if not os.path.isdir(base): continue
        for d in os.listdir(base):
            if d.startswith('20') and os.path.isdir(os.path.join(base, d)):
                days.add(d)
    return sorted(days)

def get_nifty_fut_token(kite, for_date):
    instr = kite.instruments("NFO")
    futs  = [i for i in instr
             if i['name'] == 'NIFTY' and i['instrument_type'] == 'FUT'
             and i['expiry'] >= for_date]
    if not futs: return None, None
    futs.sort(key=lambda x: x['expiry'])
    return futs[0]['instrument_token'], futs[0]['tradingsymbol']

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    kite = KiteConnect(api_key=KITE_API_KEY)
    kite.set_access_token(KITE_ACCESS_TOKEN)
    try:
        kite.profile(); print("[KITE] Token valid.")
    except Exception as e:
        print(f"[KITE] Token invalid: {e}. Run auto_login.py first."); sys.exit(1)

    all_days = discover_days()
    if not all_days:
        print("[ERROR] No option data days found."); sys.exit(1)

    print(f"[DATA] {len(all_days)} days: {all_days[0]} → {all_days[-1]}")

    start_dt = datetime.strptime(all_days[0],  '%Y-%m-%d') - timedelta(days=2)
    end_dt   = datetime.strptime(all_days[-1], '%Y-%m-%d') + timedelta(days=2)

    # Collect all unique expiry months needed
    all_tokens = {}
    for day_str in all_days:
        d = datetime.strptime(day_str, '%Y-%m-%d').date()
        tok, sym = get_nifty_fut_token(kite, d)
        if tok and tok not in all_tokens:
            all_tokens[tok] = sym
            print(f"  Token {tok} ({sym}) covers {day_str}")

    if not all_tokens:
        print("[ERROR] No futures tokens found."); sys.exit(1)

    # Fetch 15m data for each token
    all_dfs = []
    for tok, sym in all_tokens.items():
        print(f"[FUT] Fetching {sym} 15m from {start_dt.date()} to {end_dt.date()} ...")
        try:
            bars = kite.historical_data(tok, start_dt, end_dt, "15minute")
        except Exception as e:
            print(f"  [ERROR] {sym}: {e}"); continue
        if not bars:
            print(f"  [WARN] {sym}: no bars returned"); continue
        df = pd.DataFrame(bars)
        df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
        df['symbol'] = sym
        all_dfs.append(df)
        print(f"  Got {len(df)} bars")

    if not all_dfs:
        print("[ERROR] No futures data fetched."); sys.exit(1)

    combined = pd.concat(all_dfs).sort_values('date').drop_duplicates('date').reset_index(drop=True)
    combined.to_csv(FUT_FILE, index=False)
    print(f"\n[SAVED] {FUT_FILE}  ({len(combined)} rows)")

    # Push to GitHub
    try:
        subprocess.run(['git', 'add', FUT_FILE], cwd=REPO_DIR, check=True)
        r = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=REPO_DIR)
        if r.returncode != 0:
            subprocess.run(['git', 'commit', '-m', f'Add Nifty futures 15m market data ({len(all_days)} days)'],
                           cwd=REPO_DIR, check=True)
            remote = (f"https://{GITHUB_PAT}@github.com/amolselukar/Amol.git"
                      if GITHUB_PAT else "origin")
            subprocess.run(['git', 'push', remote, BRANCH], cwd=REPO_DIR, check=True)
            print("[GITHUB] Pushed market_data/nifty_fut_15m.csv")
        else:
            print("[GITHUB] No changes.")
    except subprocess.CalledProcessError as e:
        print(f"[GITHUB] Push failed: {e}. File saved locally at {FUT_FILE}")

if __name__ == '__main__':
    main()
