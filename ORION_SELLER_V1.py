#!/usr/bin/env python3
"""
ORION_SELLER_V1 — PAPER naked-seller tracker (NIFTY weekly), forward-validation only.

Reconstructed 2026-11-04 from the surviving run log (~/orion_seller_run.log) and the
user's Telegram screenshot, after the original (untracked) file was lost in a disk
cleanup. Behaviour reproduced 1:1 from the log:

  • ENTRY (once/day, ~11:15 IST): round spot to nearest 50 = ATM, then SELL 4 legs —
        ATM CE, (ATM+50) CE, ATM PE, (ATM-50) PE   (short straddle + one strangle leg/side)
    record sold premium; STOP = 2x sold premium (naked-short 2x stop).
  • MONITOR (every 15 min): per-leg mark-to-market; a leg whose price reaches its 2x stop is
    booked STOP; a "tracker" message shows each open leg, how close it is to its stop
    ("% of the way there" = ltp/stop), and Open MTM.
  • EOD (15:15 IST): square off every still-open leg at market  -> reason SQOFF_1515.
  • Messages post to the OrionStocksbot chat (same token/chat as ORION_STOCKS_V1),
    prefixed "🔴 SELLER | ".  LOT = 65.

PURPOSE (per user): this is a BIAS GAUGE, not a trade engine — it shows which side
(CE vs PE) is being sold into / decaying faster today, i.e. the side the market is
NOT moving toward, so you avoid taking trades / staying on that side. The tracker and
EOD therefore print an explicit CE-side vs PE-side readout.

PAPER ONLY — no real orders anywhere. Prices use the latest COMPLETED 1-minute close
via the Upstox shim (deterministic, idempotent; polled only every 15 min).
"""
import sys, os, json, csv, requests
from datetime import datetime
import credentials as c
from upstox_kite_shim import UpstoxKite, IST

k = UpstoxKite(c.UPSTOX_ACCESS_TOKEN)
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state_SELLER.json")
BOOK = os.path.join(HERE, "Seller_TradeBook.csv")
DRY = ("test" in sys.argv)

# OrionStocksbot chat (same as ORION_STOCKS_V1), SELLER prefix
TG_TOK = c.TELEGRAM_BOT_TOKEN
TG_CID = c.TELEGRAM_CHAT_ID
PREFIX = "🔴 <b>SELLER</b> | "

# ---- params (from run log) ----
LOT = 65
ENTRY_H, ENTRY_M = 11, 15     # sell at 11:15 IST
ENTRY_CUTOFF_H, ENTRY_CUTOFF_M = 14, 30   # never open a fresh short after this (late/post-mkt guard)
EOD_H, EOD_M = 15, 15         # SQOFF_1515
STOP_MULT = 2.0               # naked-short 2x stop
NIFTY_SPOT_TOK = 256265       # shim legacy index token (mapped to Upstox Nifty 50)

def tg(msg):
    if DRY:
        print("[TG]", msg.replace("<b>", "").replace("</b>", "")); return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOK}/sendMessage",
                      json={"chat_id": TG_CID, "text": PREFIX + msg, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print("TG err", e)

# ---- instruments / expiry ----
_INST = None
def nifty_opts():
    global _INST
    if _INST is None:
        _INST = [r for r in k.instruments("NFO")
                 if r.get("name") == "NIFTY" and r.get("instrument_type") in ("CE", "PE")]
    return _INST

def front_expiry(day):
    exps = sorted({str(r["expiry"])[:10] for r in nifty_opts()})
    return next((e for e in exps if e >= day), None)

def resolve(strike, side, expiry):
    for r in nifty_opts():
        if (r.get("instrument_type") == side and int(float(r["strike"])) == strike
                and str(r["expiry"])[:10] == expiry):
            return r["instrument_token"], r.get("tradingsymbol", f"NIFTY{strike}{side}")
    return None, None

def last_close(tok, day, now):
    """Latest COMPLETED 1-minute close for a token today (None if unavailable)."""
    d0 = datetime.strptime(day, "%Y-%m-%d")
    frm = d0.replace(hour=9, minute=15, tzinfo=IST)
    to = d0.replace(hour=15, minute=30, tzinfo=IST)
    try:
        bars = k.historical_data(tok, frm, to, "minute")
    except Exception as e:
        print("fetch err", tok, e); return None
    cutoff = now.replace(second=0, microsecond=0)
    done = [b for b in sorted(bars, key=lambda x: x["date"]) if b["date"] < cutoff]
    return float(done[-1]["close"]) if done else None

def get_spot(day, now):
    return last_close(NIFTY_SPOT_TOK, day, now)

# ---- state / book ----
def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}
def save_state(s):
    if not DRY: json.dump(s, open(STATE, "w"), indent=2)

def book_row(row):
    if DRY: return
    new = not os.path.exists(BOOK)
    with open(BOOK, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["day","entry","exit","side","strike","symbol",
                                          "sold","bought","pts","rupees","reason","held_min"])
        if new: w.writeheader()
        w.writerow(row)

def _mins(a, b):
    try:
        return int((datetime.strptime(b, "%H:%M") - datetime.strptime(a, "%H:%M")).total_seconds() // 60)
    except Exception:
        return 0

# ---- main ----
def build_legs(spot):
    atm = round(spot / 50) * 50
    return [(atm, "CE"), (atm + 50, "CE"), (atm, "PE"), (atm - 50, "PE")]

def bias_line(legs):
    """CE-side vs PE-side seller MTM -> which side to avoid."""
    ce = sum(l["mtm"] for l in legs if l["side"] == "CE")
    pe = sum(l["mtm"] for l in legs if l["side"] == "PE")
    if abs(ce - pe) < 1:
        tag = "दोन्ही बाजू सारख्या — स्पष्ट bias नाही"
    elif pe > ce:
        tag = "PE-बाजू जास्त decay → मार्केट पडणार नाही → <b>PE/short टाळ</b>"
    else:
        tag = "CE-बाजू जास्त decay → मार्केट वर जाणार नाही → <b>CE/long टाळ</b>"
    return f"📊 bias: CE-side Rs{ce:+,.0f} | PE-side Rs{pe:+,.0f}\n   {tag}"

def main():
    now = datetime.now(IST); day = now.strftime("%Y-%m-%d")
    hm = now.hour * 60 + now.minute
    st = load_state()
    if st.get("date") != day:
        st = {"date": day}

    # ---- ENTRY (once, at/after 11:15) ----
    if "legs" not in st:
        if hm < ENTRY_H * 60 + ENTRY_M:
            print(f"[SELLER] {day}: pre-entry ({ENTRY_H}:{ENTRY_M:02d})"); save_state(st); return
        if hm > ENTRY_CUTOFF_H * 60 + ENTRY_CUTOFF_M:
            print(f"[SELLER] {day}: past entry cutoff — no entry today"); save_state(st); return
        exp = front_expiry(day)
        spot = get_spot(day, now)
        if not exp or not spot:
            print(f"[SELLER] {day}: no expiry/spot yet (exp={exp} spot={spot})"); save_state(st); return
        legs = []
        for strike, side in build_legs(spot):
            tok, sym = resolve(strike, side, exp)
            prem = last_close(tok, day, now) if tok else None
            if not prem:
                print(f"[SELLER] {day}: could not price {strike}{side} — abort entry this run"); save_state(st); return
            legs.append(dict(strike=strike, side=side, tok=tok, sym=sym,
                             sold=round(prem, 2), stop=round(prem * STOP_MULT, 2),
                             entry=now.strftime("%H:%M"), status="open", bought=None,
                             exit=None, reason=None))
        st["legs"] = legs; st["expiry"] = exp
        lines = [f"{'🟩' if l['side']=='CE' else '🟥'} {l['side']} {l['strike']} sold <b>{l['sold']}</b> · stop {l['stop']}"
                 for l in legs]
        tg(f"🚀 ENTRY {now:%H:%M} (spot {spot:.0f}, exp {exp}) — naked short 2x stop [PAPER]\n" + "\n".join(lines))
        print(f"[SELLER] {day}: ENTRY {len(legs)} legs")
        save_state(st); return

    legs = st["legs"]

    # ---- price every leg (live-ish: latest completed 1m close) ----
    for l in legs:
        if l["status"] == "open":
            px = last_close(l["tok"], day, now)
            l["ltp"] = px if px is not None else l.get("ltp", l["sold"])
            l["mtm"] = round((l["sold"] - l["ltp"]) * LOT)   # short: profit when price falls
            # STOP: price reached 2x sold premium
            if l["ltp"] >= l["stop"]:
                l["status"] = "closed"; l["bought"] = round(l["ltp"], 2)
                l["exit"] = now.strftime("%H:%M"); l["reason"] = "STOP"
                pts = round(l["sold"] - l["bought"], 2); rs = round(pts * LOT)
                book_row(dict(day=day, entry=l["entry"], exit=l["exit"], side=l["side"],
                              strike=l["strike"], symbol=l["sym"], sold=l["sold"],
                              bought=l["bought"], pts=pts, rupees=rs, reason="STOP",
                              held_min=_mins(l["entry"], l["exit"])))
                tg(f"🛑 STOP {l['side']} {l['strike']} sold {l['sold']} → bought <b>{l['bought']}</b> "
                   f"= Rs{rs:+,} ({pts:+.2f}pt) [2x] | {l['exit']} [PAPER]")
        else:
            l["mtm"] = round((l["sold"] - (l.get("bought") or l.get("ltp", l["sold"]))) * LOT)
    st["legs"] = legs

    open_legs = [l for l in legs if l["status"] == "open"]

    # ---- EOD square-off (15:15) ----
    if hm >= EOD_H * 60 + EOD_M and open_legs and not st.get("closed_sent"):
        lines = []
        for l in open_legs:
            l["status"] = "closed"; l["bought"] = round(l.get("ltp", l["sold"]), 2)
            l["exit"] = now.strftime("%H:%M"); l["reason"] = "SQOFF_1515"
            pts = round(l["sold"] - l["bought"], 2); rs = round(pts * LOT)
            book_row(dict(day=day, entry=l["entry"], exit=l["exit"], side=l["side"],
                          strike=l["strike"], symbol=l["sym"], sold=l["sold"],
                          bought=l["bought"], pts=pts, rupees=rs, reason="SQOFF_1515",
                          held_min=_mins(l["entry"], l["exit"])))
            emo = "✅" if rs >= 0 else "🔴"
            lines.append(f"{emo} {l['side']} {l['strike']} sold {l['sold']} → bought <b>{l['bought']}</b> "
                         f"= Rs{rs:+,} ({pts:+.2f}pt) [SQOFF_1515] after {_mins(l['entry'], l['exit'])}m")
        realized = sum(round((l['sold'] - l['bought']) * LOT) for l in legs if l.get("bought") is not None)
        tg("CLOSED\n" + "\n".join(lines) + f"\n\nRealized this run: <b>Rs{realized:+,}</b>")
        st["closed_sent"] = True; st["legs"] = legs

    # ---- tracker (once per 15-min slot, while legs open) ----
    elif open_legs:
        slot = f"{now:%H}{(now.minute // 15) * 15:02d}"
        if st.get("last_track_slot") != slot:
            lines = []
            for l in open_legs:
                emo = "🟢" if l["mtm"] >= 0 else "🔴"
                pct = round(l["ltp"] / l["stop"] * 100) if l.get("stop") else 0
                lines.append(f"{emo} {l['side']} {l['strike']} sold {l['sold']} → now {l['ltp']:.2f} "
                             f"Rs{l['mtm']:+,}\n   stop {l['stop']} ({pct}% of the way there)")
            open_mtm = sum(l["mtm"] for l in legs)
            tg(f"📊 tracker {now:%H:%M}\n" + "\n".join(lines) +
               f"\n\nOpen MTM <b>Rs{open_mtm:+,}</b>\n" + bias_line(legs))
            st["last_track_slot"] = slot

    # ---- EOD summary (once, after close) ----
    if hm >= EOD_H * 60 + EOD_M and not open_legs and not st.get("eod_sent"):
        realized = sum(round((l['sold'] - l['bought']) * LOT) for l in legs if l.get("bought") is not None)
        emo = "✅" if realized >= 0 else "🔴"
        tg(f"🌙 EOD {day}\nRealized today: <b>Rs{realized:+,}</b> {emo}\n"
           f"<i>PAPER · naked short w/ 2x stop · forward validation only</i>\n" + bias_line(legs))
        st["eod_sent"] = True

    print(f"[SELLER] {day}: open={len(open_legs)} "
          f"mtm=Rs{sum(l['mtm'] for l in legs):+}")
    save_state(st)

def loop():
    """Wake only on 15-minute boundaries (:00/:15/:30/:45) — no per-minute polling.
    Entry 11:15 and EOD 15:15 are quarter-hour marks, so they are hit exactly. This
    keeps API calls / Telegram / log lines to ~16 a day; nothing accumulates on disk."""
    import time
    print(f"[SELLER] loop start {datetime.now(IST)}")
    while True:
        now = datetime.now(IST); hm = now.hour * 60 + now.minute
        if hm >= ENTRY_H * 60 + ENTRY_M:
            try: main()
            except Exception as e: print("[SELLER] run err", e)
        if hm >= EOD_H * 60 + EOD_M + 3:
            print(f"[SELLER] done for day, loop exit {now}"); break
        now = datetime.now(IST)
        time.sleep(max((15 - now.minute % 15) * 60 - now.second, 30))

if __name__ == "__main__":
    if "loop" in sys.argv: loop()
    else: main()
