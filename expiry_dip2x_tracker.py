#!/usr/bin/env python3
"""EXPIRY DIP->RISE->2x TRACKER (standalone PAPER/shadow, NIFTY only) — 2026-10-28.
Observe-only; NO real orders; does NOT touch the live ORION EXPIRY engine.

Tracks the validated rule (study 2026-10-28, 9 expiries, +EV & fill-robust):
 on EXPIRY DAYS, afternoon (>=14:00), on ORION's actual morning-flagged strike
 (parsed from today's Nifty flight-recorder '[EXPIRY] AFT mode: WATCH <strike><side>'),
 BUY a confirmed +20% rise off a fresh dip; STOP = dip-undercut (60% floor);
 TARGET = 2.0x; max 1 re-entry. Alerts once each to the V2520 Telegram channel +
 books to EXPIRY_DIP2X_TradeBook.csv. Deterministic on COMPLETED 1m bars, idempotent.
"""
import sys, os, csv, json, glob, re, requests
from datetime import datetime, timedelta
import credentials as c
from upstox_kite_shim import UpstoxKite, IST

k = UpstoxKite(c.UPSTOX_ACCESS_TOKEN)
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state_EXPIRYDIP2X.json")
BOOK = os.path.join(HERE, "EXPIRY_DIP2X_TradeBook.csv")
DRY = ("test" in sys.argv)
TG_TOK = getattr(c, "TELEGRAM_V2520_BOT_TOKEN", None) or c.TELEGRAM_BOT_TOKEN
TG_CID = getattr(c, "TELEGRAM_V2520_CHAT_ID", None) or c.TELEGRAM_CHAT_ID

# ---- validated params (study 2026-10-28) ----
RISE = 0.20; STOPFLOOR = 0.60; TARGET = 2.0; MAXENTRY = 2
STOP_CONFIRM = 2       # stop valid only if price stays below it for >1 min (N consecutive 1m closes); else whipsaw
DIPFRESH = 15          # dip must be within 15 completed 1m bars of the rise trigger
PMIN_ENTRY = 3.0       # don't chase sub-3 junk premium
AFT_H, AFT_M = 14, 0   # afternoon window start
EOD_H, EOD_M = 15, 25  # force close
LOT = 65               # NIFTY lot
STEP_NAME = "NIFTY"

def tg(msg):
    if DRY: print("[TG]", msg); return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOK}/sendMessage",
                      json={"chat_id": TG_CID, "text": msg, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print("TG err", e)

_INST = None
def nifty_opts():
    global _INST
    if _INST is None:
        _INST = [r for r in k.instruments("NFO")
                 if r.get("name") == "NIFTY" and r.get("instrument_type") in ("CE", "PE")]
    return _INST

def expiry_today(day):
    exps = sorted({str(r["expiry"])[:10] for r in nifty_opts()})
    front = next((e for e in exps if e >= day), None)
    return (front == day), front

def flagged_token(strike, side, day):
    for r in nifty_opts():
        if (r.get("instrument_type") == side and int(float(r["strike"])) == strike
                and str(r["expiry"])[:10] == day):
            return r["instrument_token"]
    return None

def read_flag(now):
    """Parse ORION's morning flag from today's Nifty flight-recorder."""
    for fn in sorted(glob.glob(os.path.join(HERE, f"Nifty_FlightRecorder_V2_5_20_{now:%Y%m%d}_*.log"))):
        try:
            m = re.findall(r"\[EXPIRY\] AFT mode: WATCH (\d+)(CE|PE)", open(fn).read())
        except Exception:
            m = []
        if m:
            s, sd = m[-1]; return int(s), sd
    return None

def completed_1m(tok, day, now):
    """Afternoon completed 1m bars (drop the still-forming current minute)."""
    d0 = datetime.strptime(day, "%Y-%m-%d")
    frm = d0.replace(hour=AFT_H, minute=AFT_M, tzinfo=IST)
    to = d0.replace(hour=15, minute=30, tzinfo=IST)
    try:
        bars = k.historical_data(tok, frm, to, "minute")
    except Exception as e:
        print("fetch err", e); return []
    bars = sorted(bars, key=lambda x: x["date"])
    cutoff = now.replace(second=0, microsecond=0)   # keep only fully-closed minutes
    return [b for b in bars if b["date"] < cutoff and (b["date"].hour, b["date"].minute) >= (AFT_H, AFT_M)]

def compute(bars, strike, side, now):
    """Deterministic replay of the dip->rise->2x rule on completed 1m bars.
    Returns (closed_trades, open_pos)."""
    closed = []; pos = None; ent = 0; runmin = None; rmi = None; below = 0
    def mk(p, t, xpx, reason):
        pct = (xpx - p["ep"]) / p["ep"] * 100 if p["ep"] else 0
        return dict(day=p["e"].strftime("%Y-%m-%d"), strike=strike, side=side,
                    entry=p["e"].strftime("%H:%M"), exit=t.strftime("%H:%M"),
                    ep=round(p["ep"], 2), xp=round(xpx, 2), dip=round(p["dip"], 2),
                    stop=round(p["stop"], 2), tgt=round(p["tgt"], 2),
                    pct=round(pct, 1), rupees=round((xpx - p["ep"]) * LOT), reason=reason)
    for i, b in enumerate(bars):
        t, o, h, l, cl = b["date"], b["open"], b["high"], b["low"], b["close"]
        if pos:
            if h >= pos["tgt"]:
                closed.append(mk(pos, t, pos["tgt"], "target")); pos = None; runmin = None; rmi = None; below = 0; continue
            # whipsaw filter: a single bar wicking below stop is ignored; exit only if the
            # close stays below stop for >1 min (STOP_CONFIRM consecutive 1m closes).
            if cl < pos["stop"]:
                below += 1
                if below >= STOP_CONFIRM:
                    closed.append(mk(pos, t, cl, "stop")); pos = None; runmin = None; rmi = None; below = 0; continue
            else:
                below = 0
            if (t.hour, t.minute) >= (EOD_H, EOD_M):
                closed.append(mk(pos, t, cl, "eod")); pos = None; runmin = None; rmi = None; below = 0; continue
            continue
        if runmin is None or cl < runmin:
            runmin = cl; rmi = i
        if (ent < MAXENTRY and runmin and cl >= PMIN_ENTRY and cl >= runmin * (1 + RISE)
                and (i - rmi) <= DIPFRESH and rmi != i and (t.hour, t.minute) < (EOD_H, EOD_M)):
            ent += 1
            pos = dict(e=t, ep=cl, dip=runmin, stop=max(runmin, cl * STOPFLOOR), tgt=TARGET * cl)
            runmin = None; rmi = None; below = 0
    return closed, pos

def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}
def save_state(s):
    if not DRY: json.dump(s, open(STATE, "w"))

def rewrite_book(day, closed):
    cols = ["day", "strike", "side", "entry", "exit", "ep", "xp", "dip", "stop", "tgt", "pct", "rupees", "reason"]
    rows = []
    if os.path.exists(BOOK):
        rows = [r for r in csv.DictReader(open(BOOK)) if r.get("day") != day]
    if DRY: return
    with open(BOOK, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({cc: r.get(cc, "") for cc in cols})
        for t in closed: w.writerow(t)

def main():
    now = datetime.now(IST); day = now.strftime("%Y-%m-%d")
    st = load_state()
    if st.get("date") != day: st = {"date": day}
    is_exp, front = expiry_today(day)
    if not is_exp:
        print(f"[EXPIRY-DIP2X] {day}: not an expiry day (front {front}) — idle"); save_state(st); return
    hm = now.hour * 60 + now.minute
    flag = read_flag(now)
    if not flag:
        print(f"[EXPIRY-DIP2X] {day}: expiry day, no ORION WATCH flag yet"); save_state(st); return
    strike, side = flag
    if not st.get("flagmsg"):
        tg(f"👁️ <b>EXPIRY-DIP2X</b> watching <b>{strike}{side}</b> (ORION flag). "
           f"From 14:00: buy +{int(RISE*100)}% rise off a dip → tgt <b>2.0x</b>, stop at dip. [paper]")
        st["flagmsg"] = True
    if hm < AFT_H * 60 + AFT_M:
        print(f"[EXPIRY-DIP2X] {day}: watching {strike}{side}, pre-14:00"); save_state(st); return
    tok = flagged_token(strike, side, day)
    if not tok:
        print(f"[EXPIRY-DIP2X] {day}: token not found for {strike}{side} exp {day}"); save_state(st); return
    bars = completed_1m(tok, day, now)
    if not bars:
        print(f"[EXPIRY-DIP2X] {day}: no completed afternoon bars yet"); save_state(st); return
    closed, openp = compute(bars, strike, side, now)
    sk = st.setdefault("fired", {"entries": [], "exits": []})
    # ENTRY alerts (closed + open), once each
    ents = [(t["entry"], t["ep"], t["dip"], t["tgt"], t["stop"]) for t in closed]
    if openp:
        ents.append((openp["e"].strftime("%H:%M"), round(openp["ep"], 2), round(openp["dip"], 2),
                     round(openp["tgt"], 2), round(openp["stop"], 2)))
    for e, ep, dip, tgt, stop in ents:
        if e not in sk["entries"]:
            tg(f"🟢 <b>EXPIRY-DIP2X</b> {strike}{side} BUY @ <b>{ep}</b> (dip {dip}) "
               f"→ tgt {tgt} / stop {stop} | {e} [paper]")
            sk["entries"].append(e)
    # EXIT alerts, once each
    for t in closed:
        kx = f"{t['entry']}|{t['exit']}"
        if kx not in sk["exits"]:
            emoji = "✅" if t["rupees"] >= 0 else "🔴"
            tg(f"{emoji} <b>EXPIRY-DIP2X</b> {strike}{side} EXIT @ <b>{t['xp']}</b> "
               f"({t['pct']:+.1f}%, Rs{t['rupees']:+.0f}) [{t['reason']}] | {t['exit']} [paper]")
            sk["exits"].append(kx)
    rewrite_book(day, closed)
    # daily P&L flash, once, after all closed
    if hm >= 15 * 60 + 31 and not openp and closed and not st.get("pnlmsg"):
        tot = sum(t["rupees"] for t in closed); w = sum(1 for t in closed if t["rupees"] > 0)
        em = "✅" if tot >= 0 else "🔴"
        tg(f"💰 <b>EXPIRY-DIP2X P&amp;L {day}</b> {em}  {len(closed)}tr {w}W  Rs{tot:+.0f} [paper]")
        st["pnlmsg"] = True
    print(f"[EXPIRY-DIP2X] {day}: {strike}{side} {len(closed)} closed, open={'yes' if openp else 'no'}")
    save_state(st)

def loop():
    import time
    print(f"[EXPIRY-DIP2X] loop start {datetime.now(IST)}")
    while True:
        now = datetime.now(IST); hm = now.hour * 60 + now.minute
        if hm >= 15 * 60 + 33:
            print(f"[EXPIRY-DIP2X] market closed, loop exit {now}"); break
        if hm >= 9 * 60 + 15:
            try: main()
            except Exception as e: print("[EXPIRY-DIP2X] run err", e)
        time.sleep(60)

if __name__ == "__main__":
    if "loop" in sys.argv: loop()
    else: main()
