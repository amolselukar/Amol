#!/usr/bin/env python3
"""
ORION STOCKS V1 — stock-options paper-trading bot (2026-08-23)

Basket of 20 NSE F&O stocks each day:
  - CORE_10: fixed, liquidity-verified list (approved 2026-08-23). Rotated
    manually only after profit is booked on a name.
  - MOVERS_10: rebuilt every morning from ALL F&O stock underlyings — ranked
    by yesterday's |%move| x volume-surge, with equity-turnover liquidity floor.

Signal (per stock, both directions, daily timeframe research + live trigger):
  LONG : stock LTP crosses ABOVE its 20-day high  AND MA20 > MA50 (golden cross
         state, daily) AND day-volume pace >= 0.6x of 20-day average  -> buy ATM CE
  SHORT: mirror (crosses BELOW 20-day low, MA20 < MA50)               -> buy ATM PE
  Monthly expiry; if < 7 calendar days remain, roll to next month (decay guard).

Exits (stock-level, option exited at its LTP):
  - SL   : stock back through trigger by 0.5*ATR14(daily)
  - TRAIL: after +1.0*ATR favorable, trail at peak -0.6*ATR
  - PREM : option LTP <= 50% of entry premium (disaster stop / IV crush)
  - TIME : max 5 trading days, exit 15:20 on day 5
  Positions CARRY OVERNIGHT (state_STOCKS.json), unlike the index bots.

No position cap in paper mode (user 2026-08-23): every qualified trigger fires,
1 lot each. Entries 09:20-14:30 IST only. One trade per stock+side per day.

USER'S GTT-DIP MECHANISM (added 2026-08-23, runs ALONGSIDE the breakout path):
  User observation: even when a stock is set to move in a direction, that
  direction's option premium often FALLS in the morning first; a fixed-price
  GTT entered in loss, then turned profitable with patience. The trick that
  worked: place the GTT at a LOWER premium — dip fills = discount entry.
  Implementation: every morning, for WATCHLIST stocks trading within 2.5% of
  their 20d high (LONG/CE) or low (SHORT/PE) — NO golden/death-cross gate,
  per user — place a paper-GTT limit at yesterday's ATM premium x (1-12%),
  valid 09:15-11:00. Fill => position kind=GTT with the WIDE stop (opposite
  20d level -0.5*ATR = "patience"), same trail/PREM_STOP/5-day exits.
  WATCHLIST (stocks_watchlist.json, persists across days): CORE_10 always +
  any basket stock that closes within 2.5% of its level (aged out after 7
  calendar days unseen). This file is what fires next morning's GTTs.

PAPER ONLY. Telegram prefix "🟢 STOCKS | " (same V2520 bot/chat).
Holiday behavior: prices frozen -> volume gate blocks entries -> idles out 15:35.
"""

import os, sys, json, time, atexit, fcntl, logging, threading
import re  # 2026-08-29: changelog guard
from datetime import datetime, date, timedelta

import requests
import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import credentials as c
from kiteconnect import KiteConnect

IST = pytz.timezone("Asia/Kolkata")
VERSION = "STOCKS_V1"
RUN_TS = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------- singleton ----------------
_LOCK_FILE = os.path.join(DIR, ".orion_singleton_stocks.lock")
_lock_fd = None
def _acquire_lock():
    global _lock_fd
    _lock_fd = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another ORION_STOCKS_V1 instance is running. Exiting.")
        sys.exit(1)
_acquire_lock()
atexit.register(lambda: _lock_fd and fcntl.flock(_lock_fd, fcntl.LOCK_UN))

# ---------------- logging ----------------
LOG_FILE = os.path.join(DIR, "stocks_run.log")
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stocks")
def linfo(m): print(f"[INFO] {m}"); log.info(m)
def lwarn(m): print(f"[WARN] {m}"); log.warning(m)
def lerr(m):  print(f"[ERR ] {m}"); log.error(m)

# =========================================================================
# CHANGE HISTORY  (added 2026-08-29 — see stamp_changelog.py)
# =========================================================================
CHANGE_HISTORY = """
STATUS legend: [BT] backtested   [FWD] forward-paper only, no backtest
               [USER] user-directed   [FIX] bug fix   [UNVAL] unvalidated

STOCKS_V1 [2026-08-23] *** BUILT AND DEPLOYED *** (cron 18 3 * * 1-5 = 08:48 IST)
  Universe: CORE_10 fixed liquidity-verified + MOVERS_10 rebuilt each morning.
  ATM monthly CE/PE, roll to next month if < 7 days remain (decay guard).
  Two entry paths running side by side:
   (1) breakout + golden/death-cross + volume pace;
   (2) the USER'S GTT-DIP mechanism — user's observation that the right
       direction's premium often falls in the morning first, so a limit placed
       BELOW yesterday's ATM premium (-12%) fills at a discount; filled GTT
       positions get the WIDE "patience" stop (opposite 20d level -0.5*ATR).
  No position cap (user instruction). Positions CARRY OVERNIGHT, unlike the
  index bots. Own Telegram: OrionNewClaide_bot, the old V2519/PROB70 chat,
  repurposed after PROB70 was stopped permanently the same day.
  *** PARAMETERS ARE UNBACKTESTED — forward paper IS the validation. ***
  [USER][UNVAL]

STOCKS_V1 [2026-08-26] Kite retired; moved to Upstox behind the drop-in
  Kite-compatible shim (upstox_kite_shim.py), long-lived read-only token, no
  daily login. Same migration as the two index bots.
  NOTE: the 15m forming-candle staleness that hit the index bots does NOT apply
  here — this bot works on DAILY bars plus live quotes.  [FIX]

STOCKS_V1 [2026-08-29] Instrumented for change discipline: CHANGE_HISTORY +
  CODE_FINGERPRINT + boot undocumented-change check, matching the two index
  bots. No trading logic touched.
  [USER]

STOCKS_V1 [2026-08-29] *** CONSOLIDATED EOD STATEMENT *** (item 6)
  WHAT: the EOD Telegram was four aggregate lines (realized / open / watchlist /
  book) which the user called unreadable on 08-27. Replaced by a four-block
  statement: ① EXITS (time, stock, side, reason, pts, rupees, held) ② ENTRIES
  (time, stock, side, lot, entry premium, trigger, split breakout vs GTT-dip)
  ③ CARRIED OVERNIGHT with PER-NAME MTM, days held and source/kind ④ NET
  (realized / open MTM / combined) plus the watchlist line.
  Two new day-scoped lists (TODAY_EXITS / TODAY_ENTRIES) feed it; the durable
  record is still Stocks_TradeBook.csv. mtm was a scalar and is now a per-key
  map so the carried table can show MTM by name.
  SENT AS SEVERAL MESSAGES on purpose: Telegram caps a message at 4096 chars
  and TG.send() does no splitting, so a 14-position carry table would have
  silently 400'd into the fallback file. _chunk() splits per block.
  Wrapped in try/except falling back to the old 3-line message — an EOD
  formatting bug must never lose the day's numbers.
  EVIDENCE: rendered against the REAL 08-27 book (6 exits / 7 entries / 14
  carried) = 5 messages, longest 1,055 chars; totals reconcile to
  realized +Rs27,326, MTM -Rs17,634, combined +Rs9,692.
  REVERT: ORION_STOCKS_V1_BACKUP_20260829_pre_changelog_backfill.py
  STATUS: applied 2026-08-29; first live send at the next session's 15:35.
  [USER]
"""
CODE_FINGERPRINT = "03b0ed94bf54ebf4c49395a45bc4cdc0319fe7e20a99b02d2ef7d2d9937064f2"


# --- undocumented-change guard (2026-08-29), identical logic to the index bots
def _orion_code_fingerprint(path=None):
    """sha256 of this file's executable code (CHANGE_HISTORY + stamp excluded)."""
    import hashlib
    p = path or os.path.abspath(__file__)
    s = open(p, encoding="utf-8").read()
    s = re.sub(r'CHANGE_HISTORY = """.*?\n"""\n', "", s, count=1, flags=re.S)
    s = re.sub(r'^CODE_FINGERPRINT = ".*?"\n', "", s, count=1, flags=re.M)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _orion_changelog_newest_date():
    # Header lines only (e.g. `V2.5.20 [... 2026-08-29]`). Scanning every date in
    # the block reported dates merely MENTIONED in prose as the newest entry.
    h = re.findall(r"^\S+ \[[^\]]*?(20\d\d-\d\d-\d\d)[^\]]*\]",
                    CHANGE_HISTORY, re.M)
    if h:
        return sorted(h)[-1]
    d = sorted(set(re.findall(r"20\d\d-\d\d-\d\d", CHANGE_HISTORY)))
    return d[-1] if d else "none"


def check_changelog_current():
    """Boot check. Returns (ok, message). Never raises -- must not block a boot."""
    try:
        actual = _orion_code_fingerprint()
        if actual == CODE_FINGERPRINT:
            return True, f"[CHANGELOG] up to date (last entry {_orion_changelog_newest_date()})"
        return False, ("UNDOCUMENTED CHANGE — this file's code does not match the "
                       "last stamped fingerprint.\nNewest CHANGE_HISTORY entry: "
                       f"{_orion_changelog_newest_date()}\nstamped={CODE_FINGERPRINT[:12]} "
                       f"actual={actual[:12]}\nRun stamp_changelog.py.")
    except Exception as e:
        return True, f"[CHANGELOG] check skipped ({e})"


# ---------------- telegram ----------------
# Own chat: the old V2519/PROB70 bot (OrionNewClaide_bot / "Orionclaudebot"),
# repurposed for STOCKS per user 2026-08-23 after PROB70 was stopped permanently.
class TG:
    url = f"https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage"
    lock = threading.Lock()
    @classmethod
    def send(cls, msg, retries=3, html=True):
        with cls.lock:
            payload = {"chat_id": c.TELEGRAM_CHAT_ID, "text": "\U0001F7E2 STOCKS | " + msg}
            if html: payload["parse_mode"] = "HTML"
            for attempt in range(retries):
                try:
                    r = requests.post(cls.url, data=payload, timeout=10)
                    if r.status_code == 200: return True
                    if r.status_code == 400 and html:
                        payload.pop("parse_mode", None); html = False
                except Exception as e:
                    lwarn(f"telegram attempt {attempt+1}: {e}")
                time.sleep(2 ** attempt)
            try:
                with open(os.path.join(DIR, f"telegram_fallback_STOCKS_{RUN_TS}.log"), "a") as f:
                    f.write(f"\n--- {datetime.now(IST)} ---\n{msg}\n")
            except Exception: pass
            return False

# ---------------- config ----------------
CORE_10 = ["HDFCBANK", "ICICIBANK", "SBIN", "RELIANCE", "INFY",
           "TCS", "LT", "HAL", "VEDL", "MCX"]
N_MOVERS          = 10
MIN_TURNOVER_RS   = 50e7    # yesterday equity turnover floor Rs 50 cr
MIN_PRICE         = 50.0
EXPIRY_ROLL_DAYS  = 7       # roll to next month inside this window
LOOKBACK_HL       = 20      # trigger = 20-day high/low
VOL_PACE_MIN      = 0.6     # day volume >= 0.6x time-adjusted 20d avg
VOL_PACE_MIN_FRAC = 0.08    # skip volume gate very early in the day
SL_ATR            = 0.5
TRAIL_ARM_ATR     = 1.0
TRAIL_GAP_ATR     = 0.6
PREM_STOP_PCT     = 0.50    # exit if option <= 50% of entry premium
MAX_HOLD_DAYS     = 5
ENTRY_START, ENTRY_END = "09:20", "14:30"
POLL_SEC          = 15
MIN_OPT_PREM      = 2.0

# user's GTT-dip mechanism
WATCH_NEAR_PCT    = 2.5     # close within this % of 20d high/low => watch + GTT side
WATCH_AGE_DAYS    = 7       # calendar days a non-core name stays on watch unseen
GTT_DISCOUNT      = 0.12    # paper-GTT limit = yesterday ATM premium x (1 - this)
GTT_CUTOFF        = "11:00" # unfilled morning-dip GTTs cancelled after this

WATCH_FILE = os.path.join(DIR, "stocks_watchlist.json")
STATE_FILE = os.path.join(DIR, "state_STOCKS.json")
BOOK_FILE  = os.path.join(DIR, "Stocks_TradeBook.csv")

# 2026-08-29 (item 6): per-trade records for the consolidated EOD statement.
# The old EOD was four aggregate lines ("Realized today / Open carried /
# Watchlist / Book") which the user called unreadable on 08-27. These two lists
# are day-scoped and in-memory only -- the durable record stays the trade book.
TODAY_EXITS = []
TODAY_ENTRIES = []
PLAN_FILE  = os.path.join(DIR, f"stocks_plan_{date.today().isoformat()}.json")

def now():  return datetime.now(IST)
def hhmm(): return now().strftime("%H:%M")

# ---------------- market data: Upstox via Kite-compatible shim (2026-08-26,
# Kite retired per user; long-lived read-only token, no daily login) --------
from upstox_kite_shim import UpstoxKite
k = UpstoxKite(c.UPSTOX_ACCESS_TOKEN)
k.profile()   # raises if token bad -> launcher already validated, belt+braces
linfo(f"[BOOT] {VERSION} Upstox data client OK")

INDEXES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
NFO = k.instruments("NFO")
NSE_TOK = {i["tradingsymbol"]: i["instrument_token"] for i in k.instruments("NSE")
           if i["segment"] == "NSE" and i["instrument_type"] == "EQ"}

import collections
OPT = collections.defaultdict(list)
for i in NFO:
    if i["instrument_type"] in ("CE", "PE") and i["name"] not in INDEXES:
        OPT[i["name"]].append(i)
UNDERLYINGS = sorted(n for n in OPT if n in NSE_TOK)
linfo(f"[BOOT] {len(UNDERLYINGS)} F&O stock underlyings, NFO rows {len(NFO)}")

def pick_expiry(name):
    today = date.today()
    exps = sorted({r["expiry"] for r in OPT[name] if r["expiry"] >= today})
    if not exps: return None
    if (exps[0] - today).days < EXPIRY_ROLL_DAYS and len(exps) > 1:
        return exps[1]
    return exps[0]

def atm_option(name, spot, side):
    """side 'CE'/'PE' -> instrument row for ATM strike of chosen expiry."""
    exp = pick_expiry(name)
    rows = [r for r in OPT[name] if r["expiry"] == exp and r["instrument_type"] == side]
    if not rows: return None
    return min(rows, key=lambda r: abs(r["strike"] - spot))

# ---------------- watchlist (user's GTT-dip monitoring file) ----------------
def load_watchlist():
    if os.path.exists(WATCH_FILE):
        try: return json.load(open(WATCH_FILE))
        except Exception as e: lwarn(f"watchlist load failed: {e}")
    return {n: {"last_seen": date.today().isoformat(), "src": "CORE"} for n in CORE_10}

def save_watchlist(wl): json.dump(wl, open(WATCH_FILE, "w"), indent=1)

def update_watchlist(plan, eq):
    """EOD: refresh watch entries for basket stocks near their levels; age out."""
    wl = load_watchlist()
    today = date.today().isoformat()
    added = []
    for name, p in plan.items():
        q = eq.get("NSE:" + name)
        c0 = q["last_price"] if q else p["close"]
        near = (c0 >= p["hi20"] * (1 - WATCH_NEAR_PCT / 100)
                or c0 <= p["lo20"] * (1 + WATCH_NEAR_PCT / 100))
        if p["src"] == "CORE":
            wl[name] = {"last_seen": today, "src": "CORE"}
        elif near:
            if name not in wl: added.append(name)
            wl[name] = {"last_seen": today, "src": "WATCH"}
    for n in list(wl):
        if wl[n]["src"] != "CORE":
            age = (date.today() - date.fromisoformat(wl[n]["last_seen"])).days
            if age > WATCH_AGE_DAYS: del wl[n]
    save_watchlist(wl)
    linfo(f"[WATCH] {len(wl)} on watch (new: {added or 'none'})")
    return wl, added

# ---------------- morning research ----------------
def fetch_daily(name, days=90):
    tok = NSE_TOK[name]
    frm = (date.today() - timedelta(days=days + 45)).isoformat()
    to  = (date.today() - timedelta(days=1)).isoformat()   # exclude today
    return k.historical_data(tok, frm, to, "day")

def research():
    """Build the 20-stock basket + levels. Cached to PLAN_FILE for restarts."""
    if os.path.exists(PLAN_FILE):
        plan = json.load(open(PLAN_FILE))
        linfo(f"[RESEARCH] reusing cached plan ({len(plan)} stocks)")
        return plan
    t0 = time.time()
    stats = {}
    for i, name in enumerate(UNDERLYINGS):
        for attempt in range(3):
            try:
                cd = fetch_daily(name); break
            except Exception as e:
                if attempt == 2: lwarn(f"[RESEARCH] {name} history failed: {e}"); cd = []
                time.sleep(1.5)
        time.sleep(0.35)
        if len(cd) < 55: continue
        closes = [b["close"] for b in cd]
        vols   = [b["volume"] for b in cd]
        ma20 = sum(closes[-20:]) / 20
        ma50 = sum(closes[-50:]) / 50
        hi20 = max(b["high"] for b in cd[-LOOKBACK_HL:])
        lo20 = min(b["low"]  for b in cd[-LOOKBACK_HL:])
        trs = []
        for j in range(-14, 0):
            pc = cd[j - 1]["close"]
            trs.append(max(cd[j]["high"] - cd[j]["low"],
                           abs(cd[j]["high"] - pc), abs(cd[j]["low"] - pc)))
        atr = sum(trs) / 14
        avgvol = sum(vols[-20:]) / 20
        pct = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] else 0
        volratio = vols[-1] / avgvol if avgvol else 0
        stats[name] = {
            "close": closes[-1], "ma20": round(ma20, 2), "ma50": round(ma50, 2),
            "hi20": hi20, "lo20": lo20, "atr": round(atr, 2),
            "avgvol": round(avgvol), "pct": round(pct, 2),
            "volratio": round(volratio, 2),
            "turnover": vols[-1] * closes[-1],
        }
    movers = sorted(
        (n for n, s in stats.items()
         if n not in CORE_10 and s["turnover"] >= MIN_TURNOVER_RS and s["close"] >= MIN_PRICE),
        key=lambda n: -(abs(stats[n]["pct"]) * min(stats[n]["volratio"], 3.0)))[:N_MOVERS]
    wl = load_watchlist()
    extras = [n for n in wl if n in stats and n not in CORE_10 and n not in movers]
    basket = [n for n in CORE_10 if n in stats] + movers + extras
    plan = {n: {**stats[n], "src": "CORE" if n in CORE_10 else
                ("MOVER" if n in movers else "WATCH")} for n in basket}
    json.dump(plan, open(PLAN_FILE, "w"), indent=1)
    linfo(f"[RESEARCH] {len(stats)} scanned in {time.time()-t0:.0f}s; basket {len(plan)}")
    return plan

# ---------------- state / paper book ----------------
def load_state():
    if os.path.exists(STATE_FILE):
        try: return json.load(open(STATE_FILE))
        except Exception as e: lwarn(f"state load failed: {e}")
    return {"open": {}, "done_today": {}, "done_date": "", "gtt": {}}

def save_state(st): json.dump(st, open(STATE_FILE, "w"), indent=1, default=str)

def book_row(**kw):
    hdr = ["ts", "action", "stock", "side", "symbol", "lot", "opt_price", "stock_price",
           "reason", "pnl_pts", "pnl_rs", "held_days"]
    newfile = not os.path.exists(BOOK_FILE)
    with open(BOOK_FILE, "a") as f:
        if newfile: f.write(",".join(hdr) + "\n")
        f.write(",".join(str(kw.get(h, "")) for h in hdr) + "\n")

ST = load_state()
today_s = date.today().isoformat()
if ST.get("done_date") != today_s:
    ST["done_today"] = {}; ST["done_date"] = today_s
    ST["gtt"] = {}   # GTT-dip orders are regenerated fresh each morning
    # increment holding age only on a NEW day, not on same-day restarts
    for p in ST["open"].values():
        p["days_held"] = p.get("days_held", 0) + 1
ST.setdefault("gtt", {})
save_state(ST)
linfo(f"[BOOT] state: {len(ST['open'])} open carried positions")

# ---------------- live helpers ----------------
def quote_batch(keys):
    if not keys: return {}
    out = {}
    for b in range(0, len(keys), 200):
        for attempt in range(3):
            try: out.update(k.quote(keys[b:b+200])); break
            except Exception as e:
                lwarn(f"quote retry: {e}"); time.sleep(1.2)
    return out

def day_frac():
    t = now()
    o = t.replace(hour=9, minute=15, second=0)
    return max(0.0, min(1.0, (t - o).total_seconds() / (375 * 60)))

def vol_ok(name, dayvol, plan):
    f = day_frac()
    if f < VOL_PACE_MIN_FRAC: return True
    return dayvol >= VOL_PACE_MIN * plan[name]["avgvol"] * f

def try_enter(name, side, plan, stock_ltp):
    key = f"{name}:{side}"
    if key in ST["open"] or ST["done_today"].get(key): return
    opt = atm_option(name, stock_ltp, "CE" if side == "LONG" else "PE")
    if not opt: lwarn(f"[ENTRY-SKIP] {key} no ATM option"); return
    q = quote_batch(["NFO:" + opt["tradingsymbol"]])
    oq = q.get("NFO:" + opt["tradingsymbol"])
    if not oq or oq["last_price"] < MIN_OPT_PREM:
        lwarn(f"[ENTRY-SKIP] {key} bad option quote"); return
    prem = oq["last_price"]
    p = plan[name]
    trigger = p["hi20"] if side == "LONG" else p["lo20"]
    sl_level = trigger - SL_ATR * p["atr"] if side == "LONG" else trigger + SL_ATR * p["atr"]
    ST["open"][key] = {
        "stock": name, "side": side, "symbol": opt["tradingsymbol"],
        "lot": opt["lot_size"], "entry_prem": prem, "entry_stock": stock_ltp,
        "trigger": trigger, "sl_level": round(sl_level, 2), "kind": "BRK",
        "atr": p["atr"], "peak": stock_ltp,
        "entry_ts": now().isoformat(), "days_held": 0, "src": p["src"],
    }
    ST["done_today"][key] = True
    save_state(ST)
    TODAY_ENTRIES.append({"time": now().strftime("%H:%M"), "stock": name, "side": side,
                          "symbol": opt["tradingsymbol"], "lot": opt["lot_size"],
                          "prem": prem, "trigger": f"break_{trigger}"})
    book_row(ts=now().isoformat(), action="ENTRY", stock=name, side=side,
             symbol=opt["tradingsymbol"], lot=opt["lot_size"], opt_price=prem,
             stock_price=stock_ltp, reason=f"break_{trigger}")
    TG.send(f"📥 <b>ENTRY {side}</b> {name} ({p['src']})\n"
            f"{opt['tradingsymbol']} lot {opt['lot_size']} @ ₹{prem}\n"
            f"stock {stock_ltp} broke {trigger} | ATR {p['atr']} | Rs/lot ₹{round(prem*opt['lot_size'])}")
    linfo(f"[ENTRY] {key} {opt['tradingsymbol']} prem={prem} stock={stock_ltp}")

def place_paper_gtts(plan):
    """Morning: user's GTT-dip orders for watchlist stocks near their levels.
    Limit = yesterday's ATM premium x (1-GTT_DISCOUNT); valid till GTT_CUTOFF."""
    ST["gtt"] = {}
    wl = load_watchlist()
    cands = {}
    for name, p in plan.items():
        if name not in wl and p["src"] != "CORE": continue
        side = None
        if p["close"] >= p["hi20"] * (1 - WATCH_NEAR_PCT / 100): side = "LONG"
        elif p["close"] <= p["lo20"] * (1 + WATCH_NEAR_PCT / 100): side = "SHORT"
        if not side: continue
        key = f"{name}:{side}"
        if key in ST["open"] or ST["done_today"].get(key): continue
        opt = atm_option(name, p["close"], "CE" if side == "LONG" else "PE")
        if opt: cands[key] = (name, side, opt)
    oq = quote_batch(sorted({"NFO:" + o.get("tradingsymbol") for _, _, o in cands.values()}))
    lines = []
    for key, (name, side, opt) in cands.items():
        q = oq.get("NFO:" + opt["tradingsymbol"])
        if not q or q["last_price"] < MIN_OPT_PREM: continue
        trig = round(q["last_price"] * (1 - GTT_DISCOUNT), 1)
        if trig < MIN_OPT_PREM: continue
        ST["gtt"][key] = {"stock": name, "side": side, "symbol": opt["tradingsymbol"],
                          "lot": opt["lot_size"], "trigger_prem": trig,
                          "base_prem": q["last_price"], "src": plan[name]["src"]}
        lines.append(f"{name} {side} {opt['tradingsymbol']} buy ≤₹{trig} (yday ₹{q['last_price']})")
        linfo(f"[GTT] armed {key} {opt['tradingsymbol']} limit={trig} base={q['last_price']}")
    save_state(ST)
    if lines:
        TG.send(f"🎯 <b>Paper-GTT dip orders</b> (valid till {GTT_CUTOFF})\n" + "\n".join(lines))
    linfo(f"[GTT] {len(ST['gtt'])} paper-GTTs armed")

def check_gtts(plan, eq, t):
    """Fill armed GTT-dip orders when the option premium dips to the limit."""
    if not ST["gtt"]: return
    if t >= GTT_CUTOFF:
        n = len(ST["gtt"])
        ST["gtt"] = {}; save_state(ST)
        TG.send(f"⏲ GTT cutoff {GTT_CUTOFF}: {n} unfilled dip order(s) cancelled")
        linfo(f"[GTT] cutoff — {n} unfilled cancelled")
        return
    oq = quote_batch(sorted({"NFO:" + g["symbol"] for g in ST["gtt"].values()}))
    for key in list(ST["gtt"]):
        g = ST["gtt"][key]
        if key in ST["open"] or ST["done_today"].get(key):
            del ST["gtt"][key]; save_state(ST); continue
        q = oq.get("NFO:" + g["symbol"])
        sq = eq.get("NSE:" + g["stock"])
        p = plan.get(g["stock"])
        if not q or not sq or not p: continue
        if q["last_price"] > g["trigger_prem"]: continue
        long = g["side"] == "LONG"
        # patience stop: the OPPOSITE 20d level, not the entry-side one
        sl_level = p["lo20"] - SL_ATR * p["atr"] if long else p["hi20"] + SL_ATR * p["atr"]
        prem, s_ltp = q["last_price"], sq["last_price"]
        ST["open"][key] = {
            "stock": g["stock"], "side": g["side"], "symbol": g["symbol"],
            "lot": g["lot"], "entry_prem": prem, "entry_stock": s_ltp,
            "trigger": p["hi20"] if long else p["lo20"],
            "sl_level": round(sl_level, 2), "kind": "GTT",
            "atr": p["atr"], "peak": s_ltp,
            "entry_ts": now().isoformat(), "days_held": 0, "src": g["src"],
        }
        ST["done_today"][key] = True
        del ST["gtt"][key]
        save_state(ST)
        TODAY_ENTRIES.append({"time": now().strftime("%H:%M"), "stock": g["stock"],
                              "side": g["side"], "symbol": g["symbol"], "lot": g["lot"],
                              "prem": prem, "trigger": "gtt_dip"})
        book_row(ts=now().isoformat(), action="ENTRY", stock=g["stock"], side=g["side"],
                 symbol=g["symbol"], lot=g["lot"], opt_price=prem, stock_price=s_ltp,
                 reason=f"gtt_dip_{g['trigger_prem']}")
        TG.send(f"📥 <b>GTT-DIP FILL {g['side']}</b> {g['stock']} ({g['src']})\n"
                f"{g['symbol']} lot {g['lot']} @ ₹{prem} (yday ₹{g['base_prem']}, "
                f"-{round((1 - prem / g['base_prem']) * 100)}%)\n"
                f"patience SL {round(sl_level, 1)} | Rs/lot ₹{round(prem * g['lot'])}")
        linfo(f"[GTT-FILL] {key} {g['symbol']} prem={prem} stock={s_ltp}")

def close_pos(key, reason, opt_ltp, stock_ltp):
    p = ST["open"].pop(key)
    pts = round(opt_ltp - p["entry_prem"], 2)
    rs = round(pts * p["lot"])
    ST["done_today"][key] = True
    save_state(ST)
    book_row(ts=now().isoformat(), action="EXIT", stock=p["stock"], side=p["side"],
             symbol=p["symbol"], lot=p["lot"], opt_price=opt_ltp, stock_price=stock_ltp,
             reason=reason, pnl_pts=pts, pnl_rs=rs, held_days=p["days_held"])
    TODAY_EXITS.append({"time": now().strftime("%H:%M"), "stock": p["stock"],
                        "side": p["side"], "symbol": p["symbol"], "reason": reason,
                        "pts": pts, "rs": rs, "held": p["days_held"]})
    emo = "✅" if rs >= 0 else "❌"
    TG.send(f"{emo} <b>EXIT {p['side']}</b> {p['stock']} [{reason}]\n"
            f"{p['symbol']} @ ₹{opt_ltp} (in ₹{p['entry_prem']}) = {pts:+} pts = ₹{rs:+,}\n"
            f"held {p['days_held']}d")
    linfo(f"[EXIT] {key} {reason} pts={pts} rs={rs}")
    return rs

def manage_exits(plan, eq):
    if not ST["open"]: return 0
    opt_keys = ["NFO:" + p["symbol"] for p in ST["open"].values()]
    oq = quote_batch(opt_keys)
    realized = 0
    for key in list(ST["open"]):
        p = ST["open"][key]
        stock_q = eq.get("NSE:" + p["stock"])
        opt_q = oq.get("NFO:" + p["symbol"])
        if not stock_q or not opt_q: continue
        s_ltp, o_ltp = stock_q["last_price"], opt_q["last_price"]
        long = p["side"] == "LONG"
        p["peak"] = max(p["peak"], s_ltp) if long else min(p["peak"], s_ltp)
        atr = p["atr"]
        # BRK: stop just past the broken level; GTT: patience stop at opposite level
        sl = p.get("sl_level")
        if sl is None:
            sl = p["trigger"] - SL_ATR * atr if long else p["trigger"] + SL_ATR * atr
        reason = None
        if long and s_ltp <= sl: reason = "SL"
        if not long and s_ltp >= sl: reason = "SL"
        fav = (p["peak"] - p["entry_stock"]) if long else (p["entry_stock"] - p["peak"])
        if not reason and fav >= TRAIL_ARM_ATR * atr:
            tl = p["peak"] - TRAIL_GAP_ATR * atr if long else p["peak"] + TRAIL_GAP_ATR * atr
            if (long and s_ltp <= tl) or (not long and s_ltp >= tl): reason = "TRAIL"
        if not reason and o_ltp <= PREM_STOP_PCT * p["entry_prem"]: reason = "PREM_STOP"
        if not reason and p["days_held"] >= MAX_HOLD_DAYS and hhmm() >= "15:20": reason = "TIME"
        if reason:
            realized += close_pos(key, reason, o_ltp, s_ltp)
        else:
            save_state(ST)
    return realized

# ---------------- main ----------------
# =========================================================================
# CONSOLIDATED EOD STATEMENT (2026-08-29, item 6)
# =========================================================================
# User, 2026-08-27: the EOD message was four aggregate lines and unreadable.
# Agreed replacement: four blocks -- exits / entries / carried-with-MTM /
# realized+MTM+combined footer. Returned as a LIST of messages because Telegram
# caps a message at 4096 chars and TG.send() does no splitting: a 14-position
# carry table plus tables would silently 400 and land in the fallback file.
TG_LIMIT = 3900

def _rupees(n):
    return f"{n:+,}".replace("+-", "-")

def _table(header, rows, widths):
    out = [" ".join(h.ljust(w)[:w] for h, w in zip(header, widths)).rstrip()]
    out.append("-" * min(len(out[0]), 60))
    for r in rows:
        out.append(" ".join(str(cell).ljust(w)[:w] for cell, w in zip(r, widths)).rstrip())
    return "\n".join(out)

def _chunk(title, body_lines):
    """Split a <pre> block across as many messages as Telegram needs."""
    msgs, cur = [], []
    for ln in body_lines:
        if sum(len(x) + 1 for x in cur) + len(ln) > TG_LIMIT and cur:
            msgs.append(cur); cur = []
        cur.append(ln)
    if cur: msgs.append(cur)
    return [f"<b>{title}</b>" + (f" ({i+1}/{len(msgs)})" if len(msgs) > 1 else "")
            + "\n<pre>" + "\n".join(m) + "</pre>" for i, m in enumerate(msgs)]

def fmt_stocks_eod(mtm_map, wl, wl_added):
    """Return the list of Telegram messages making up the EOD statement."""
    d = now().strftime("%Y-%m-%d")
    realized = sum(e["rs"] for e in TODAY_EXITS)
    wins = sum(1 for e in TODAY_EXITS if e["rs"] > 0)
    loss = sum(1 for e in TODAY_EXITS if e["rs"] < 0)
    mtm_total = sum(mtm_map.values())
    msgs = []

    head = (f"🌙 <b>EOD STATEMENT — {VERSION}</b>  {d}  (PAPER)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Realized today: <b>₹{_rupees(realized)}</b> "
            f"({len(TODAY_EXITS)} exits: {wins}W / {loss}L)")
    msgs.append(head)

    if TODAY_EXITS:
        rows = [(e["time"], e["stock"], e["side"], e["reason"],
                 f'{e["pts"]:+.2f}', _rupees(e["rs"]), f'{e["held"]}d')
                for e in TODAY_EXITS]
        msgs += _chunk("① EXITS", _table(
            ["Time","Stock","Side","Reason","Pts","Rupees","Held"],
            rows, [5,12,5,10,8,10,4]).splitlines())
    else:
        msgs.append("<b>① EXITS</b>\nnone today")

    if TODAY_ENTRIES:
        rows = [(e["time"], e["stock"], e["side"], e["lot"],
                 f'{e["prem"]:.2f}', e["trigger"]) for e in TODAY_ENTRIES]
        nb = sum(1 for e in TODAY_ENTRIES if e["trigger"].startswith("break"))
        ng = len(TODAY_ENTRIES) - nb
        msgs += _chunk(f"② ENTRIES ({len(TODAY_ENTRIES)}: {nb} breakout, {ng} GTT-dip)",
            _table(["Time","Stock","Side","Lot","Entry","Trigger"],
                   rows, [5,12,5,6,8,12]).splitlines())
    else:
        msgs.append("<b>② ENTRIES</b>\nnone today")

    if ST["open"]:
        rows = []
        for k, p in ST["open"].items():
            rows.append((p["stock"], p["side"], p["lot"], f'{p["entry_prem"]:.2f}',
                         _rupees(mtm_map.get(k, 0)), f'{p["days_held"]}d',
                         f'{p.get("src","?")}/{p.get("kind","?")}'))
        msgs += _chunk(f"③ CARRIED OVERNIGHT ({len(ST['open'])}, MTM ₹{_rupees(mtm_total)})",
            _table(["Stock","Side","Lot","EntryPrem","MTM","Days","Source"],
                   rows, [12,5,6,9,10,5,9]).splitlines())
    else:
        msgs.append("<b>③ CARRIED OVERNIGHT</b>\nnone")

    combined = realized + mtm_total
    em = "🟢" if combined > 0 else "🔴" if combined < 0 else "⚪"
    msgs.append(f"<b>④ NET</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Realized:  ₹{_rupees(realized)}\n"
                f"Open MTM:  ₹{_rupees(mtm_total)}\n"
                f"{em} <b>Combined: ₹{_rupees(combined)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Watchlist tomorrow: {len(wl)}"
                + (f" (new: {', '.join(wl_added)})" if wl_added else "")
                + f"\nBook: Stocks_TradeBook.csv  ·  <i>all paper</i>")
    return msgs


def main():
    test_mode = "--research-test" in sys.argv
    if now().weekday() >= 5 and not test_mode:
        linfo("Market closed (weekend). Exiting."); return

    plan = research()
    core = [n for n in plan if plan[n]["src"] == "CORE"]
    movers = [n for n in plan if plan[n]["src"] == "MOVER"]
    lines = [f"{n} {plan[n]['pct']:+.1f}% vr{plan[n]['volratio']}" for n in movers]
    TG.send(f"🚀 <b>ORION {VERSION} boot</b> (PAPER)\n"
            f"Core {len(core)} | Movers: " + ", ".join(lines) + "\n"
            f"Open carried: {len(ST['open'])} | expiry roll &lt;{EXPIRY_ROLL_DAYS}d")
    # 2026-08-29: undocumented-change guard -- see check_changelog_current().
    _cl_ok, _cl_msg = check_changelog_current()
    if _cl_ok:
        linfo(_cl_msg)
    else:
        lwarn(f"[CHANGELOG] {_cl_msg}")
        TG.send("<b>⚠️ UNDOCUMENTED CHANGE</b>\n<pre>"
                + _cl_msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                + "</pre>")
    for n in plan:
        p = plan[n]
        gc = "GC" if p["ma20"] > p["ma50"] else "DC"
        linfo(f"[PLAN] {n:<12}{p['src']:<6}{gc} close={p['close']} hi20={p['hi20']} "
              f"lo20={p['lo20']} atr={p['atr']}")
    place_paper_gtts(plan)
    if test_mode:
        linfo("[TEST] research-test complete, exiting."); return

    eq_keys = ["NSE:" + n for n in plan] + \
              ["NSE:" + p["stock"] for p in ST["open"].values() if p["stock"] not in plan]
    eq_keys = sorted(set(eq_keys))
    prev_ltp = {}
    realized_today = 0

    while hhmm() < "09:15":
        time.sleep(10)
    linfo("[LIVE] loop start")

    while True:
        t = hhmm()
        if t >= "15:30":
            break
        try:
            eq = quote_batch(eq_keys)
            realized_today += manage_exits(plan, eq)
            check_gtts(plan, eq, t)
            if ENTRY_START <= t <= ENTRY_END:
                for name in plan:
                    q = eq.get("NSE:" + name)
                    if not q: continue
                    ltp, dayvol = q["last_price"], q.get("volume", 0)
                    pv = prev_ltp.get(name)
                    p = plan[name]
                    # gap window: stock opened straight through the level
                    # (within 0.5*ATR past it) — GTT would have filled at open
                    gap_win = t <= "09:25"
                    if pv is not None:
                        long_sig = (pv < p["hi20"] <= ltp) or \
                                   (gap_win and p["hi20"] <= ltp <= p["hi20"] + 0.5 * p["atr"])
                        short_sig = (pv > p["lo20"] >= ltp) or \
                                    (gap_win and p["lo20"] - 0.5 * p["atr"] <= ltp <= p["lo20"])
                        if p["ma20"] > p["ma50"] and long_sig and vol_ok(name, dayvol, plan):
                            try_enter(name, "LONG", plan, ltp)
                        if p["ma20"] < p["ma50"] and short_sig and vol_ok(name, dayvol, plan):
                            try_enter(name, "SHORT", plan, ltp)
                    prev_ltp[name] = ltp
        except Exception as e:
            lerr(f"loop error: {e}")
        time.sleep(POLL_SEC)

    # EOD: refresh the monitoring watchlist for tomorrow's GTT-dip orders
    try:
        eq_eod = quote_batch(eq_keys)
        wl, wl_added = update_watchlist(plan, eq_eod)
    except Exception as e:
        lerr(f"watchlist update failed: {e}"); wl, wl_added = {}, []

    # EOD summary (positions carry overnight — no force close)
    # 2026-08-29: per-position MTM map (was a single scalar) so the carried
    # table can show MTM per name -- see fmt_stocks_eod().
    mtm_map = {}
    if ST["open"]:
        oq = quote_batch(["NFO:" + p["symbol"] for p in ST["open"].values()])
        for k, p in ST["open"].items():
            q = oq.get("NFO:" + p["symbol"])
            if q: mtm_map[k] = round((q["last_price"] - p["entry_prem"]) * p["lot"])
    mtm = sum(mtm_map.values())
    try:
        for _m in fmt_stocks_eod(mtm_map, wl, wl_added):
            TG.send(_m)
    except Exception as _e:
        lerr(f"[EOD] consolidated statement failed: {_e}")
        TG.send(f"🌙 <b>EOD {VERSION}</b>\nRealized today: ₹{realized_today:+,}\n"
                f"Open carried: {len(ST['open'])} (MTM ₹{mtm:+,})")
    linfo(f"[EOD] realized={realized_today} exits={len(TODAY_EXITS)} "
          f"entries={len(TODAY_ENTRIES)} open={len(ST['open'])} mtm={mtm}")
    linfo("Market closed. Bot exiting cleanly.")

if __name__ == "__main__":
    main()
