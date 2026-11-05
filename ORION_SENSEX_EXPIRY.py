#!/usr/bin/env python3
"""
ORION_SENSEX_EXPIRY — expiry-day option-BUY engine for SENSEX.
Built 2026-11-04; LIVE mStock orders enabled 2026-11-05 (user-directed, small acct).

MAIN THEME = NIFTY "EXPIRY" engine (the head-to-head winner vs EXPIRY-DIP2X on
2026-11-03): a morning ROUND-LEVEL break picks the side; in the AFTERNOON (>=14:00)
BUY a CHEAP option on that side (premium in a band); NO hard stop (risk = premium);
ride to 15:25 force-close. SENSEX adaptations: round step 100, lot 20, BFO, premium
band [15,200] (~3.3x the Nifty [5,60]); trend-confirm needs >= MIN_MOVE pts.

LIVE mode (real mStock BFO orders) is GUARDED for a tiny (~₹3800) account:
  • exactly ONE lot (qty 20);
  • AFFORDABILITY: skip entry if entry_premium*lot > MAX_SPEND (no funds API);
  • ONE trade per expiry day;
  • SELL-TO-LOCK if premium reaches 2.5x (protects a runner), else ride;
  • STRICT 15:25 square-off (market SELL);
  • if a SELL order fails, a LOUD Telegram alert tells you to square off MANUALLY.
Set LIVE_ORDERS=False to run pure paper (deterministic replay) instead.

NOTE: mStock is single-session — run this live ONLY when the Nifty live bot
(lvl_live_nifty) is NOT also holding an mStock session (its cron is paused for the
live-test day). Posts to the SENSEX Telegram channel. Runs only on SENSEX expiry days.
"""
import sys, os, csv, json, time, requests
from datetime import datetime
import credentials as c
from upstox_kite_shim import UpstoxKite, IST
from mstock_broker import MStockBroker

k = UpstoxKite(c.UPSTOX_ACCESS_TOKEN)
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state_SENSEX_EXPIRY.json")
BOOK = os.path.join(HERE, "Sensex_Expiry_TradeBook.csv")
DRY = ("test" in sys.argv)

TG_TOK = getattr(c, "TELEGRAM_SENSEX_BOT_TOKEN", None) or c.TELEGRAM_BOT_TOKEN
TG_CID = getattr(c, "TELEGRAM_SENSEX_CHAT_ID", None) or c.TELEGRAM_CHAT_ID
PREFIX = "🟣 <b>SENSEX-EXPIRY</b> | "

# ---- strategy params ----
STEP = 100
LOT = 20                   # exactly ONE SENSEX lot
PREM_MIN, PREM_MAX = 15.0, 200.0
MIN_MOVE = 150
AFT_H, AFT_M = 14, 0
EOD_H, EOD_M = 15, 25
LOCK_ARM = 1.5
LOCK_KEEP = 0.5
RIDE_TIER = 2.0
RIDE_GIVEBACK = 0.30
MAX_OTM_SCAN = 6
SPOT_TOK = 265

# ---- LIVE execution (user-enabled 2026-11-05; real mStock BFO orders, guarded) ----
LIVE_ORDERS = True         # False -> pure paper replay
MAX_SPEND = 3700           # ₹ affordability cap (~₹3800 acct): skip if entry_prem*LOT exceeds
EXCHANGE = "BFO"
PRODUCT = "INTRADAY"
ORDER_TYPE = "MARKET"
ORDER_TAG = "SENSEXEXP"
LOCK_SELL_MULT = 2.5       # market-SELL to lock if premium hits 2.5x entry; else ride to 15:25

def tg(msg):
    if DRY: print("[TG]", msg.replace("<b>", "").replace("</b>", "")); return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOK}/sendMessage",
                      json={"chat_id": TG_CID, "text": PREFIX + msg, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print("TG err", e)

_BROKER = None
def broker():
    global _BROKER
    if _BROKER is None:
        b = MStockBroker()
        if not b.login():
            tg("🚨 mStock login FAILED — live orders disabled this run.")
            raise RuntimeError("mStock login failed")
        _BROKER = b
    return _BROKER

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

def latest_price(tok, day, now):
    b = bars_1m(tok, day, now)
    return float(b[-1]["close"]) if b else None

def pick_side_strike(spot_bars, now):
    """Morning break -> side + a cheap OTM round-100 strike whose afternoon premium is
    inside [PREM_MIN, PREM_MAX]. Returns (side, strike, entry_prem, opt_token, sym) or None."""
    if not spot_bars:
        return None
    day = now.strftime("%Y-%m-%d"); exp = front_expiry(day)
    if not exp:
        return None
    opn = spot_bars[0]["open"]; spot = spot_bars[-1]["close"]
    move = spot - opn
    if abs(move) < MIN_MOVE:
        return None
    side = "CE" if move > 0 else "PE"
    atm = round(spot / STEP) * STEP
    for n in range(0, MAX_OTM_SCAN + 1):
        strike = atm + n * STEP if side == "CE" else atm - n * STEP
        tok, sym = resolve(strike, side, exp)
        if not tok:
            continue
        ob = bars_1m(tok, day, now)
        aft = [b for b in ob if (b["date"].hour, b["date"].minute) >= (AFT_H, AFT_M)]
        if not aft:
            continue
        prem = aft[0]["close"]
        if PREM_MIN <= prem <= PREM_MAX:
            return side, strike, round(prem, 2), tok, sym
    return None

def replay(opt_bars, ep, now):
    """Paper ride: no stop; lock 1.5x keep 50%, trail 30% beyond 2x; force-close 15:25."""
    peak = ep; floor = None
    aft = [b for b in opt_bars if (b["date"].hour, b["date"].minute) >= (AFT_H, AFT_M)]
    entered = False
    for b in aft:
        t, h, l, cl = b["date"], b["high"], b["low"], b["close"]
        if not entered:
            entered = True; continue
        peak = max(peak, h)
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
                                          "ep","xp","peak","pts","rupees","reason","mode"])
        if new: w.writeheader()
        w.writerow(row)

# ============================= PAPER (deterministic replay) =============================
def main_paper():
    now = datetime.now(IST); day = now.strftime("%Y-%m-%d")
    st = load_state()
    if st.get("date") != day: st = {"date": day}
    if front_expiry(day) != day:
        print(f"[SENSEX-EXPIRY] {day}: not expiry — idle"); save_state(st); return
    hm = now.hour * 60 + now.minute
    if hm < AFT_H * 60 + AFT_M:
        print(f"[SENSEX-EXPIRY] {day}: pre-14:00"); save_state(st); return
    spot_bars = bars_1m(SPOT_TOK, day, now)
    if "trade" not in st:
        if hm >= 15 * 60:
            print(f"[SENSEX-EXPIRY] {day}: past 15:00 window — no trade"); save_state(st); return
        pick = pick_side_strike(spot_bars, now)
        if not pick:
            print(f"[SENSEX-EXPIRY] {day}: no band-priced trend strike yet"); save_state(st); return
        side, strike, ep, tok, sym = pick
        st["trade"] = dict(side=side, strike=strike, ep=ep, tok=tok, sym=sym, entry=now.strftime("%H:%M"))
        tg(f"🟢 (paper) BUY <b>{strike}{side}</b> @ <b>{ep}</b> — no stop, lock 1.5x, ride 2x, 15:25 close")
        save_state(st); return
    tr = st["trade"]
    xp, xt, reason, is_open, peak = replay(bars_1m(tr["tok"], day, now), tr["ep"], now)
    pts = round(xp - tr["ep"], 2); rs = round(pts * LOT)
    if is_open:
        if hm - st.get("last_track_hm", -99) >= 15:
            cur = latest_price(tr["tok"], day, now) or tr["ep"]; mtm = round((cur - tr["ep"]) * LOT)
            tg(f"📊 (paper) {tr['strike']}{tr['side']} entry {tr['ep']} → now {cur:.2f} "
               f"{'🟢' if mtm>=0 else '🔴'} Rs{mtm:+,} (peak {peak})")
            st["last_track_hm"] = hm
    elif not st.get("closed"):
        tg(f"{'✅' if rs>=0 else '🔴'} (paper) EXIT {tr['strike']}{tr['side']} @ {xp} "
           f"({pts:+.2f}pt, Rs{rs:+,}) [{reason}] peak {peak} | {xt}")
        book_row(dict(day=day, side=tr["side"], strike=tr["strike"], symbol=tr["sym"], entry=tr["entry"],
                      exit=xt, ep=tr["ep"], xp=xp, peak=peak, pts=pts, rupees=rs, reason=reason, mode="paper"))
        st["closed"] = True
    save_state(st)

# ============================= LIVE (real mStock BFO, guarded) =============================
def _sell(tr, day, now, reason):
    """Market-SELL the held lot to close. LOUD alert if it fails."""
    oid = broker().place_order("SELL", tr["sym"], LOT, order_type=ORDER_TYPE,
                               exchange=EXCHANGE, product=PRODUCT, tag=ORDER_TAG)
    if not oid:
        tg(f"🚨 <b>SELL FAILED</b> {tr['sym']} x{LOT}: {getattr(broker(),'_last_error','?')}\n"
           f"⚠️ square off MANUALLY now."); return None
    status, xfill = broker().wait_for_fill(oid, timeout_sec=12)
    pts = round(xfill - tr["ep"], 2); rs = round(pts * LOT)
    tg(f"{'✅' if rs>=0 else '🔴'} <b>SELL {tr['strike']}{tr['side']} @ {xfill}</b> "
       f"({pts:+.2f}pt, Rs{rs:+,}) [{reason}] | {now:%H:%M} [LIVE]")
    tg(f"🌙 <b>EOD {day}</b> Realized: <b>Rs{rs:+,}</b> <i>(LIVE 1-lot, SENSEX expiry)</i>")
    book_row(dict(day=day, side=tr["side"], strike=tr["strike"], symbol=tr["sym"], entry=tr["entry"],
                  exit=now.strftime("%H:%M"), ep=tr["ep"], xp=round(xfill,2), peak=tr.get("peak",tr["ep"]),
                  pts=pts, rupees=rs, reason=reason, mode="LIVE"))
    return xfill

def main_live():
    now = datetime.now(IST); day = now.strftime("%Y-%m-%d")
    st = load_state()
    if st.get("date") != day: st = {"date": day}
    if front_expiry(day) != day:
        print(f"[SENSEX-EXPIRY] {day}: not expiry — idle"); save_state(st); return
    hm = now.hour * 60 + now.minute
    if hm < AFT_H * 60 + AFT_M:
        print(f"[SENSEX-EXPIRY] {day}: pre-14:00"); save_state(st); return

    # ---------- ENTRY ----------
    if "trade" not in st and not st.get("skipped") and not st.get("done"):
        if hm >= 15 * 60:
            print(f"[SENSEX-EXPIRY] {day}: past 15:00 — no entry"); save_state(st); return
        pick = pick_side_strike(bars_1m(SPOT_TOK, day, now), now)
        if not pick:
            print(f"[SENSEX-EXPIRY] {day}: no band-priced trend strike yet"); save_state(st); return
        side, strike, ep, tok, sym = pick
        cost = ep * LOT
        if cost > MAX_SPEND:                                   # affordability guard
            tg(f"⏭️ skip <b>{strike}{side}</b> @ {ep} — cost ₹{cost:,.0f} > cap ₹{MAX_SPEND:,} (funds) [LIVE]")
            st["skipped"] = True; save_state(st); return
        if not broker().get_symbol_token(sym, EXCHANGE):       # must be a real mStock BFO scrip
            tg(f"⚠️ {sym} not found at broker (BFO) — no order."); save_state(st); return
        oid = broker().place_order("BUY", sym, LOT, order_type=ORDER_TYPE,
                                   exchange=EXCHANGE, product=PRODUCT, tag=ORDER_TAG)
        if not oid:
            tg(f"🚨 BUY FAILED {sym} x{LOT}: {getattr(broker(),'_last_error','?')} [LIVE]")
            save_state(st); return                              # retry next poll (still inside window)
        status, fill = broker().wait_for_fill(oid, timeout_sec=12)
        fill = fill or ep
        st["trade"] = dict(side=side, strike=strike, sym=sym, tok=tok, ep=round(fill, 2),
                           buy_oid=oid, entry=now.strftime("%H:%M"), peak=round(fill, 2), sold=False)
        tg(f"🟢 <b>BUY {strike}{side} @ {fill}</b> x{LOT} ({status}) — cost ₹{fill*LOT:,.0f}\n"
           f"no stop · lock-sell at 2.5x · square off 15:25 [LIVE]")
        save_state(st); return

    # ---------- MANAGE / EXIT ----------
    tr = st.get("trade")
    if not tr or tr.get("sold"):
        print(f"[SENSEX-EXPIRY] {day}: nothing open (skipped={st.get('skipped')}, done={st.get('done')})")
        save_state(st); return
    cur = latest_price(tr["tok"], day, now)
    if cur is not None:
        tr["peak"] = max(tr.get("peak", tr["ep"]), cur)
    sell_now = (hm >= EOD_H * 60 + EOD_M) or (cur is not None and cur >= tr["ep"] * LOCK_SELL_MULT)
    if sell_now:
        reason = "FORCE_1525" if hm >= EOD_H * 60 + EOD_M else "LOCK_2.5x"
        if _sell(tr, day, now, reason) is not None:
            tr["sold"] = True; st["done"] = True
    else:
        if hm - st.get("last_track_hm", -99) >= 15 and cur is not None:
            mtm = round((cur - tr["ep"]) * LOT)
            tg(f"📊 {tr['strike']}{tr['side']} entry {tr['ep']} → now {cur:.2f} "
               f"{'🟢' if mtm>=0 else '🔴'} Rs{mtm:+,} (peak {tr['peak']}) [LIVE]")
            st["last_track_hm"] = hm
    st["trade"] = tr; save_state(st)

def main():
    (main_live if (LIVE_ORDERS and not DRY) else main_paper)()

def loop():
    print(f"[SENSEX-EXPIRY] loop start {datetime.now(IST)} (LIVE={LIVE_ORDERS})")
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
