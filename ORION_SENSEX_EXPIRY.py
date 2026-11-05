#!/usr/bin/env python3
"""
ORION_SENSEX_EXPIRY — PAPER expiry-day option-BUY engine for SENSEX.
Built 2026-11-04 (user-directed). Observe-only; NO real orders.

MAIN THEME = NIFTY "EXPIRY" engine (AFT mode), adapted to SENSEX moves:
  the Nifty EXPIRY engine beat the Nifty EXPIRY-DIP2X engine head-to-head on
  2026-11-03 (EXPIRY +40.6pt held to 15:25 vs DIP2X stopped out twice), so the
  winning logic is carried over as the base:

    • a morning ROUND-LEVEL break picks the day's side (CE if up / PE if down);
    • in the AFTERNOON (>=14:00) BUY a CHEAP option on that side (premium inside a
      band) — small premium = small risk, big expiry gamma upside;
    • NO hard stop (max loss = the premium paid);
    • profit LOCK arms at 1.5x entry and keeps half the gain (ratchets up only);
    • force-close at 15:25.

SENSEX adaptations (vs Nifty):
    • round step 100 (Nifty 50); lot 20 (Nifty 65); BFO exchange; spot token 265;
    • premium band scaled ~3.3x for SENSEX premiums: [15, 200] (Nifty was [5, 60]);
    • trend-confirm needs a >= MIN_MOVE point move off the open (SENSEX is noisier).

ADDED LOGIC (mine, user-approved "use ur logic where required"):
    • RIDE tier — once a winner reaches 2.0x, the lock switches to a 30% trailing
      giveback so a late expiry run (market often trends into 15:30) is captured,
      instead of only keeping 50% at the 1.5x tier. Directly addresses the Nifty
      case where EXPIRY exited 86 while the option ran to 110.

Deterministic replay of COMPLETED 1-minute bars (idempotent; nothing is written to
disk except the per-trade row + a tiny state file). Alerts to the SENSEX Telegram
channel. Runs only on SENSEX expiry days.
"""
import sys, os, csv, json, requests
from datetime import datetime
import credentials as c
from upstox_kite_shim import UpstoxKite, IST

k = UpstoxKite(c.UPSTOX_ACCESS_TOKEN)
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state_SENSEX_EXPIRY.json")
BOOK = os.path.join(HERE, "Sensex_Expiry_TradeBook.csv")
DRY = ("test" in sys.argv)

TG_TOK = getattr(c, "TELEGRAM_SENSEX_BOT_TOKEN", None) or c.TELEGRAM_BOT_TOKEN
TG_CID = getattr(c, "TELEGRAM_SENSEX_CHAT_ID", None) or c.TELEGRAM_CHAT_ID
PREFIX = "🟣 <b>SENSEX-EXPIRY</b> | "

# ---- params ----
STEP = 100                 # SENSEX round-level step
LOT = 20                   # SENSEX lot
PREM_MIN, PREM_MAX = 15.0, 200.0   # afternoon entry premium band (Nifty 5-60 x ~3.3)
MIN_MOVE = 150             # pts off open to confirm a morning trend/break
AFT_H, AFT_M = 14, 0       # afternoon entry window start
EOD_H, EOD_M = 15, 25      # force close
LOCK_ARM = 1.5             # peak >= entry*1.5 arms the lock
LOCK_KEEP = 0.5            # floor = entry + (peak-entry)*0.5
RIDE_TIER = 2.0            # peak >= entry*2.0 switches to trailing ride
RIDE_GIVEBACK = 0.30       # ride floor = peak*(1-0.30)
MAX_OTM_SCAN = 6           # how many round steps OTM to scan for a band-priced strike
SPOT_TOK = 265             # shim legacy SENSEX index token

def tg(msg):
    if DRY: print("[TG]", msg.replace("<b>", "").replace("</b>", "")); return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOK}/sendMessage",
                      json={"chat_id": TG_CID, "text": PREFIX + msg, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print("TG err", e)

_INST = None
def sensex_opts():
    global _INST
    if _INST is None:
        _INST = [r for r in k.instruments("BFO")
                 if r.get("name") == "SENSEX" and r.get("instrument_type") in ("CE", "PE")]
    return _INST

def front_expiry(day):
    exps = sorted({str(r["expiry"])[:10] for r in sensex_opts()})
    return next((e for e in exps if e >= day), None)

def resolve(strike, side, expiry):
    for r in sensex_opts():
        if (r.get("instrument_type") == side and int(float(r["strike"])) == strike
                and str(r["expiry"])[:10] == expiry):
            return r["instrument_token"], r.get("tradingsymbol", f"SENSEX{strike}{side}")
    return None, None

def bars_1m(tok, day, now, from_h=9, from_m=15):
    d0 = datetime.strptime(day, "%Y-%m-%d")
    frm = d0.replace(hour=from_h, minute=from_m, tzinfo=IST)
    to = d0.replace(hour=15, minute=30, tzinfo=IST)
    try:
        bars = k.historical_data(tok, frm, to, "minute")
    except Exception as e:
        print("fetch err", tok, e); return []
    cutoff = now.replace(second=0, microsecond=0)
    return [b for b in sorted(bars, key=lambda x: x["date"]) if b["date"] < cutoff]

def pick_side_strike(spot_bars, now):
    """Morning break -> side + a cheap OTM round-100 strike whose afternoon premium
    is inside [PREM_MIN, PREM_MAX]. Returns (side, strike, entry_prem, opt_token, sym)
    or None if no clean trend / no band-priced strike yet."""
    if not spot_bars:
        return None
    day = now.strftime("%Y-%m-%d"); exp = front_expiry(day)
    if not exp:
        return None
    opn = spot_bars[0]["open"]
    spot = spot_bars[-1]["close"]
    move = spot - opn
    if abs(move) < MIN_MOVE:
        return None                      # no decisive morning break
    side = "CE" if move > 0 else "PE"
    atm = round(spot / STEP) * STEP
    # scan OTM in the trend direction for the first strike priced in band
    for n in range(0, MAX_OTM_SCAN + 1):
        strike = atm + n * STEP if side == "CE" else atm - n * STEP
        tok, sym = resolve(strike, side, exp)
        if not tok:
            continue
        ob = bars_1m(tok, day, now)
        aft = [b for b in ob if (b["date"].hour, b["date"].minute) >= (AFT_H, AFT_M)]
        if not aft:
            continue
        prem = aft[0]["close"]           # premium at first completed bar >= 14:00
        if PREM_MIN <= prem <= PREM_MAX:
            return side, strike, round(prem, 2), tok, sym
    return None

def replay(opt_bars, ep, now):
    """EXPIRY-engine ride: no stop; lock arms at 1.5x (keep 50%), trail 30% beyond 2x;
    force-close 15:25. Returns (exit_price, exit_time, reason, open_bool, peak)."""
    peak = ep; floor = None
    aft = [b for b in opt_bars if (b["date"].hour, b["date"].minute) >= (AFT_H, AFT_M)]
    entered = False
    for b in aft:
        t, h, l, cl = b["date"], b["high"], b["low"], b["close"]
        if not entered:                  # first aft bar = entry bar
            entered = True; continue
        peak = max(peak, h)
        # lock tiers
        if peak >= ep * RIDE_TIER:
            floor = max(floor or 0, peak * (1 - RIDE_GIVEBACK))
        elif peak >= ep * LOCK_ARM:
            floor = max(floor or 0, ep + (peak - ep) * LOCK_KEEP)
        if floor is not None and l <= floor:
            return round(floor, 2), t.strftime("%H:%M"), "LOCK", False, round(peak, 2)
        if (t.hour, t.minute) >= (EOD_H, EOD_M):
            return round(cl, 2), t.strftime("%H:%M"), "FORCE_1525", False, round(peak, 2)
    last = aft[-1] if aft else None
    return (round(last["close"], 2) if last else ep,
            last["date"].strftime("%H:%M") if last else "", "OPEN", True, round(peak, 2))

def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}
def save_state(s):
    if not DRY: json.dump(s, open(STATE, "w"), indent=2)

def book_row(row):
    if DRY: return
    new = not os.path.exists(BOOK)
    with open(BOOK, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["day","side","strike","symbol","entry","exit",
                                          "ep","xp","peak","pts","rupees","reason"])
        if new: w.writeheader()
        w.writerow(row)

def main():
    now = datetime.now(IST); day = now.strftime("%Y-%m-%d")
    st = load_state()
    if st.get("date") != day: st = {"date": day}
    exp = front_expiry(day)
    if exp != day:
        print(f"[SENSEX-EXPIRY] {day}: not a SENSEX expiry day (front {exp}) — idle")
        save_state(st); return
    hm = now.hour * 60 + now.minute
    if hm < AFT_H * 60 + AFT_M:
        print(f"[SENSEX-EXPIRY] {day}: expiry day, pre-14:00"); save_state(st); return

    spot_bars = bars_1m(SPOT_TOK, day, now)
    # --- pick/lock the trade once ---
    if "trade" not in st:
        if hm >= 15 * 60:          # past 15:00 — buy window closed, no fresh entry
            print(f"[SENSEX-EXPIRY] {day}: past 15:00 entry window — no trade"); save_state(st); return
        pick = pick_side_strike(spot_bars, now)
        if not pick:
            print(f"[SENSEX-EXPIRY] {day}: no band-priced trend strike yet"); save_state(st); return
        side, strike, ep, tok, sym = pick
        st["trade"] = dict(side=side, strike=strike, ep=ep, tok=tok, sym=sym,
                           entry=now.strftime("%H:%M"))
        tg(f"🟢 BUY <b>{strike}{side}</b> @ <b>{ep}</b> (expiry {exp}) — no stop, "
           f"lock 1.5x keep 50%, ride 30% beyond 2x, force-close 15:25 [PAPER]")
        print(f"[SENSEX-EXPIRY] {day}: ENTRY {strike}{side} @ {ep}")
        save_state(st); return

    tr = st["trade"]
    opt_bars = bars_1m(tr["tok"], day, now)
    xp, xt, reason, is_open, peak = replay(opt_bars, tr["ep"], now)
    pts = round(xp - tr["ep"], 2); rs = round(pts * LOT)

    if is_open:
        if not st.get("last_track") or hm - st.get("last_track_hm", 0) >= 15:
            cur = opt_bars[-1]["close"] if opt_bars else tr["ep"]
            mtm = round((cur - tr["ep"]) * LOT)
            emo = "🟢" if mtm >= 0 else "🔴"
            tg(f"📊 {tr['strike']}{tr['side']} entry {tr['ep']} → now {cur:.2f} "
               f"{emo} Rs{mtm:+,} (peak {peak}) [PAPER]")
            st["last_track"] = True; st["last_track_hm"] = hm
        print(f"[SENSEX-EXPIRY] {day}: open {tr['strike']}{tr['side']} peak={peak}")
    elif not st.get("closed"):
        emo = "✅" if rs >= 0 else "🔴"
        tg(f"{emo} EXIT <b>{tr['strike']}{tr['side']}</b> @ <b>{xp}</b> "
           f"({pts:+.2f}pt, Rs{rs:+,}) [{reason}] peak {peak} | {xt} [PAPER]")
        tg(f"🌙 <b>EOD {day}</b> Realized: <b>Rs{rs:+,}</b>\n"
           f"<i>PAPER · expiry buy · forward validation only</i>")
        book_row(dict(day=day, side=tr["side"], strike=tr["strike"], symbol=tr["sym"],
                      entry=tr["entry"], exit=xt, ep=tr["ep"], xp=xp, peak=peak,
                      pts=pts, rupees=rs, reason=reason))
        st["closed"] = True
    save_state(st)

def loop():
    import time
    print(f"[SENSEX-EXPIRY] loop start {datetime.now(IST)}")
    while True:
        now = datetime.now(IST); hm = now.hour * 60 + now.minute
        if hm >= EOD_H * 60 + EOD_M + 4:
            try: main()
            except Exception as e: print("[SENSEX-EXPIRY] run err", e)
            print(f"[SENSEX-EXPIRY] done, loop exit {now}"); break
        if hm >= AFT_H * 60 + AFT_M:
            try: main()
            except Exception as e: print("[SENSEX-EXPIRY] run err", e)
        time.sleep(60)

if __name__ == "__main__":
    if "loop" in sys.argv: loop()
    else: main()
