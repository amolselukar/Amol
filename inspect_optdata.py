"""One-shot script: inspect daily_option_data structure and push summary to GitHub."""
import os, json, glob, subprocess

BASE = "/home/Selukar/daily_option_data"
OUT  = "/home/Selukar/Amol/optdata_inspect.txt"
BRANCH = "claude/general-session-YfHuZ"

lines = []
def w(s=""): lines.append(s); print(s)

# --- dates available ---
dates = sorted(d for d in os.listdir(BASE) if os.path.isdir(f"{BASE}/{d}") and d.startswith("20"))
w(f"=== DATES ({len(dates)}) ===")
w(", ".join(dates))

# --- inspect latest date ---
day = dates[-1]
w(f"\n=== STRUCTURE: {day} ===")
top = sorted(os.listdir(f"{BASE}/{day}"))
w("Top-level: " + str(top))

# meta
meta_path = f"{BASE}/{day}/_meta.json"
if os.path.exists(meta_path):
    w("\n--- _meta.json ---")
    w(open(meta_path).read().strip())

# nifty_1h sample
f1h = f"{BASE}/{day}/nifty_1h.csv"
if os.path.exists(f1h):
    rows = open(f1h).readlines()
    w(f"\n--- nifty_1h.csv ({len(rows)-1} rows) ---")
    w("header: " + rows[0].strip())
    w("first:  " + rows[1].strip())
    w("last:   " + rows[-1].strip())

# nifty_15m sample
f15 = f"{BASE}/{day}/nifty_15m.csv"
if os.path.exists(f15):
    rows = open(f15).readlines()
    w(f"\n--- nifty_15m.csv ({len(rows)-1} rows) ---")
    w("header: " + rows[0].strip())
    w("first:  " + rows[1].strip())
    w("last:   " + rows[-1].strip())

# CE directory
ce_dir = f"{BASE}/{day}/CE"
if os.path.exists(ce_dir):
    ce_files = sorted(os.listdir(ce_dir))
    w(f"\n--- CE/ ({len(ce_files)} files) ---")
    w("files: " + str(ce_files[:8]))
    if ce_files:
        sample = open(f"{ce_dir}/{ce_files[len(ce_files)//2]}").readlines()
        w(f"sample file: {ce_files[len(ce_files)//2]}")
        w("header: " + sample[0].strip())
        w("row1:   " + (sample[1].strip() if len(sample)>1 else "empty"))
        w("last:   " + sample[-1].strip())

# PE directory
pe_dir = f"{BASE}/{day}/PE"
if os.path.exists(pe_dir):
    pe_files = sorted(os.listdir(pe_dir))
    w(f"\n--- PE/ ({len(pe_files)} files) ---")
    w("files: " + str(pe_files[:8]))

# atm_tracker sample
atm_f = f"{BASE}/{day}/atm_tracker_5m.csv"
if os.path.exists(atm_f):
    rows = open(atm_f).readlines()
    w(f"\n--- atm_tracker_5m.csv ({len(rows)-1} rows) ---")
    w("header: " + rows[0].strip())
    w("row1:   " + rows[1].strip())

# --- check all dates have same structure ---
w("\n=== ROW COUNTS PER DATE ===")
for d in dates:
    ce = f"{BASE}/{d}/CE"
    n1h = f"{BASE}/{d}/nifty_1h.csv"
    n15 = f"{BASE}/{d}/nifty_15m.csv"
    ce_cnt = len(os.listdir(ce)) if os.path.exists(ce) else 0
    h1_cnt = len(open(n1h).readlines())-1 if os.path.exists(n1h) else 0
    h15_cnt = len(open(n15).readlines())-1 if os.path.exists(n15) else 0
    w(f"  {d}: CE_files={ce_cnt}  1h_rows={h1_cnt}  15m_rows={h15_cnt}")

# --- write and push ---
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print(f"\nWritten to {OUT}")

repo = "/home/Selukar/Amol"
subprocess.run(["git", "add", OUT], cwd=repo, check=True)
r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo)
if r.returncode != 0:
    subprocess.run(["git", "commit", "-m", "optdata_inspect: daily_option_data structure dump"], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", BRANCH], cwd=repo, check=True)
    print("Pushed to GitHub.")
else:
    print("No changes to push.")
