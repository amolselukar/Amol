#!/usr/bin/env python3
"""
lvl_daily_summary.py — one consolidated Telegram summary of TODAY's LVL trades
(NIFTY + SENSEX), built 2026-11-05 (user-directed). Reads the LVL tradebooks for
closed trades + state_LVL.json for still-open positions; posts to the LVL channel.
Run at EOD from cron, or any time (`test` prints instead of sending).
"""
import sys, os, csv, json, requests
from datetime import datetime
import credentials as c
try:
    import lvl_engine as eng
    from lvl_engine import IST
except Exception:
    eng = None
    import pytz; IST = pytz.timezone("Asia/Kolkata")

HERE = os.path.dirname(os.path.abspath(__file__))
DRY = ("test" in sys.argv)
TG_TOK = getattr(c, "TELEGRAM_LVL_BOT_TOKEN", None) or getattr(c, "TELEGRAM_V2520_BOT_TOKEN", None) or c.TELEGRAM_BOT_TOKEN
TG_CID = getattr(c, "TELEGRAM_LVL_CHAT_ID", None) or getattr(c, "TELEGRAM_V2520_CHAT_ID", None) or c.TELEGRAM_CHAT_ID

BOOKS = {"NIFTY": os.path.join(HERE, "LVL_Nifty_TradeBook.csv"),
         "SENSEX": os.path.join(HERE, "LVL_Sensex_TradeBook.csv")}

def tg(msg):
    if DRY: print(msg); return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOK}/sendMessage",
                      json={"chat_id": TG_CID, "text": msg, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print("TG err", e)

def today_rows(path, day):
    if not os.path.exists(path): return []
    out = []
    for r in csv.DictReader(open(path)):
        if r.get("day") == day:
            out.append(r)
    return out

def main():
    now = datetime.now(IST); day = now.strftime("%Y-%m-%d")
    try:
        st = json.load(open(os.path.join(HERE, "state_LVL.json")))
    except Exception:
        st = {}
    lines = [f"📒 <b>LVL TRADE SUMMARY {day}</b>"]
    grand = 0; any_trade = False
    for mkt in ("NIFTY", "SENSEX"):
        rows = today_rows(BOOKS[mkt], day)
        # open position (with live target/SL) straight from the engine, not state
        openp = None
        if eng is not None:
            try: _cl, openp = eng.compute(mkt, day)
            except Exception as ex: print(f"compute {mkt} err {ex}"); openp = None
        if not rows and not openp:
            lines.append(f"\n<b>{mkt}</b>: — no trades")
            continue
        any_trade = True
        tot = sum(int(float(r.get("rupees") or 0)) for r in rows)
        grand += tot
        w = sum(1 for r in rows if float(r.get("rupees") or 0) > 0)
        l = sum(1 for r in rows if float(r.get("rupees") or 0) <= 0)
        lines.append(f"\n<b>{mkt}</b>  {len(rows)}tr  {w}W/{l}L  <b>Rs{tot:+,}</b>")
        for r in rows:
            emo = "✅" if float(r.get("rupees") or 0) > 0 else "🔴"
            th = "🎯" if str(r.get("target_hit")) in ("1", "1.0") else ""
            lines.append(f"  {emo} {r.get('side')} {r.get('strike')} "
                         f"{r.get('eo')}→{r.get('xo')} ({float(r.get('pts') or 0):+.0f}pt Rs{int(float(r.get('rupees') or 0)):+,}) "
                         f"{th}[{r.get('reason')}] {r.get('entry')}→{r.get('exit')}")
        if openp:
            sl = openp.get("stop", openp.get("lval")); tgt = openp.get("target")
            lines.append(f"  ⏳ OPEN {openp.get('side')} {openp.get('strike')} @ ₹{openp.get('eo')} "
                         f"(entry {openp.get('entry')})\n"
                         f"     🎯 target <b>{tgt}</b> | 🛑 SL <b>{sl}</b> ({openp.get('level')}) 15m-close")
    if any_trade:
        lines.append(f"\n<b>TOTAL Rs{grand:+,}</b>  <i>(LVL paper)</i>")
    tg("\n".join(lines))
    print(f"[LVL-SUMMARY] sent {day} total Rs{grand:+}")

if __name__ == "__main__":
    main()
