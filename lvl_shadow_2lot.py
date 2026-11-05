#!/usr/bin/env python3
"""LVL SHADOW 2-LOT (PAPER-ONLY, NIFTY) — 2026-10-30.

Observe-only shadow of the 2-lot step-trail strategy, run ALONGSIDE the real live
1-lot engine (lvl_live_nifty.py). PLACES NO ORDERS. Reuses the live engine's signal
(lvl_engine.compute) and the live engine's Telegram channel for updates.

  lotA = THE LIVE LOT. Mirrors lvl_engine's exact entry + exit (level-ratchet / EOD).
         Its exit premium is x. (So re-entries == live; NO churn artifact.)
  lotB = x-ANCHORED STEP-TRAIL (paper). After lotA exits in PROFIT, lotB is floored at
         x, ratchets its stop up in STEP-pt rungs as the premium makes new highs, books
         at the stop on a pullback ("return to x -> book at x"), else rides to EOD.
         If lotA exits at a LOSS (level broke), lotB exits WITH lotA at the SL.

By construction lotB >= lotA on every trade, so this measures the PURE incremental value
of adding a floored-at-x trailing 2nd lot, with the re-entry/churn confound removed.
Idealised fills (1m closes; stop fills at the rung) — slippage/brokerage is a SEPARATE
haircut, not modelled here. P&L reported at FULL LOT (65); real live is currently qty=1.

Telegram lifecycle per trade: 🟢 entry (both lots) -> 🅰️ lotA(=live) exit, x set ->
🅱️ lotB riding -> 🅱️ lotB exit + per-trade 1-lot-vs-2-lot -> 💰 EOD summary vs live.

Run:  python3 lvl_shadow_2lot.py test   # DRY single pass (prints, sends nothing)
      python3 lvl_shadow_2lot.py loop    # paper poll loop (cron)
      python3 lvl_shadow_2lot.py         # single pass
"""
import sys, os, csv, json, time, logging
from datetime import datetime

import lvl_engine as eng           # reuse data client, compute(), levels, tg(), INSTR
from lvl_engine import IST

HERE  = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state_LVL_SHADOW.json")
BOOK  = os.path.join(HERE, "LVL_SHADOW_2lot_TradeBook.csv")
LIVE_BOOK = os.path.join(HERE, "LVL_LIVE_Nifty_TradeBook.csv")

KEY  = "NIFTY"
STEP = 10                          # lot-B step-trail rung (NIFTY premium pts; step10 = study best)
LOT  = eng.INSTR[KEY]['lot']       # 65 — full-lot P&L basis for BOTH lots
DRY  = ("test" in sys.argv)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler(os.path.join(HERE, "lvl_shadow_2lot.log"))])
log = logging.getLogger("lvl_shadow")

def tg(msg):
    try: eng.tg(msg)                # respects eng.DRY (prints in test mode)
    except Exception as e: log.error(f"tg err {e}")

# ── helpers ───────────────────────────────────────────────────────────
def hm_dt(day, hm):
    h, m = map(int, hm.split(":"))
    return datetime.strptime(day, "%Y-%m-%d").replace(hour=h, minute=m, tzinfo=IST)

def opt_bars(strike, side, day):
    """Option 1m bars for the trade's strike/side, 09:15 -> 15:30 (fetched fresh each poll
    so the series grows through the day). Same front-weekly map the engine prices off."""
    d0 = datetime.strptime(day, "%Y-%m-%d")
    o1 = d0.replace(hour=9, minute=15, tzinfo=IST); o2 = d0.replace(hour=15, minute=30, tzinfo=IST)
    omap = eng.opt_map(eng.INSTR[KEY]['exch'], eng.INSTR[KEY]['name'], day)
    tok = omap.get((int(strike), side))
    return eng.fetch(tok, o1, o2, "minute") if tok else []

def lotB_from_trade(t, now):
    """Deterministic lot-B state given lot-A's live exit and option bars up to `now`.
    Returns dict(done, xo, reason, exit, bstop, peak, ltp)."""
    eo, xo, strike, side, day = t['eo'], t['xo'], t['strike'], t['side'], t['day']
    if xo < eo:                                   # lotA took the SL -> lotB out with it
        return dict(done=True, xo=xo, reason='sl_with_lotA', exit=t['exit'], bstop=xo, peak=xo, ltp=xo)
    ob = opt_bars(strike, side, day)
    if not ob:
        return dict(done=False, xo=None, reason='no-data', exit=None, bstop=xo, peak=xo, ltp=None)
    exit_dt = hm_dt(day, t['exit'])
    af = next((x for x in ob if x['date'] >= exit_dt), None)      # lotA fill bar
    xtA = af['date'] if af else exit_dt
    xA = xo; peak = xA; bstop = xA; booked = None
    for x in ob:
        if x['date'] <= xtA: continue
        p = x['close']
        if p > peak:
            peak = p
            rung = xA + ((peak - xA) // STEP) * STEP             # x, x+STEP, x+2*STEP, ...
            if rung > bstop: bstop = rung
        if p <= bstop:
            booked = (x['date'], bstop); break
    is_eod = now.hour * 60 + now.minute >= 15 * 60 + 30          # last 1m bar is in
    last_close = ob[-1]['close']; last_t = ob[-1]['date']
    if booked:
        bt, bx = booked
        reason = 'book_x' if bx == xA else 'steptrail'
        return dict(done=True, xo=round(bx, 1), reason=reason, exit=bt.strftime('%H:%M'),
                    bstop=round(bstop, 1), peak=round(peak, 1), ltp=round(last_close, 1))
    if is_eod:                                                   # never pulled back -> ride to EOD
        return dict(done=True, xo=round(last_close, 1), reason='eod_ride', exit=last_t.strftime('%H:%M'),
                    bstop=round(bstop, 1), peak=round(peak, 1), ltp=round(last_close, 1))
    return dict(done=False, xo=None, reason='riding', exit=None,
                bstop=round(bstop, 1), peak=round(peak, 1), ltp=round(last_close, 1))

def real_live_today(day):
    """(pnl, n) of the real live qty=1 trades today, for context (from the live book)."""
    if not os.path.exists(LIVE_BOOK): return None, 0
    tot = 0.0; n = 0
    try:
        for r in csv.DictReader(open(LIVE_BOOK)):
            if r.get('day') == day and r.get('pnl') not in (None, ''):
                try: tot += float(r['pnl']); n += 1
                except Exception: pass
    except Exception: return None, 0
    return tot, n

# ── state ─────────────────────────────────────────────────────────────
def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}
def save_state(s):
    if not DRY: json.dump(s, open(STATE, "w"), indent=2)

def book_row(row):
    cols = ["day","entry","side","strike","level","eo","xoA","rupeesA","reasonA",
            "lotB_xo","rupeesB","lotB_reason","lotB_exit","two_lot"]
    exists = os.path.exists(BOOK)
    if DRY: return
    with open(BOOK, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if not exists: w.writeheader()
        w.writerow({k: row.get(k, "") for k in cols})

# ── one pass ──────────────────────────────────────────────────────────
def run_once():
    now = datetime.now(IST); day = now.strftime("%Y-%m-%d")
    st = load_state()
    if st.get("date") != day: st = {"date": day, "trades": {}, "eod": False}
    trades = st.setdefault("trades", {})

    closed, openp = eng.compute(KEY, day)

    # ENTRY alerts (closed + still-open), once each (both lots go on together)
    seen = [t for t in closed] + ([openp] if openp else [])
    for t in seen:
        e = t['entry']; rec = trades.setdefault(e, {})
        if not rec.get('entry_alert'):
            rec.update(side=t['side'], strike=t['strike'], level=t.get('level'),
                       lval=t.get('lval'), target=t.get('target'), espot=t.get('espot'), entry=e)
            tgt = f" → tgt {t.get('target')}" if t.get('target') else ""
            eo_s = f"₹{t.get('eo')}" if t.get('eo') is not None else "—"
            tg(f"🟢 <b>SHADOW 2-LOT (paper) — BUY {t['side']} {t['strike']} @ {eo_s}</b>\n"
               f"break {t.get('level')} {t.get('lval')} @ spot {t.get('espot')}{tgt} | {e}\n"
               f"lotA = LIVE (mirrors live exit) + lotB = x-anchored step-trail")
            rec['entry_alert'] = True

    # lotA (= LIVE) exits + lotB lifecycle
    for t in closed:
        e = t['entry']; rec = trades.setdefault(e, {})
        rec.update(eo=t['eo'], xoA=t['xo'], exitA=t['exit'], reasonA=t['reason'], rupeesA=t['rupees'])
        if not rec.get('lotA_alert'):
            emo = "🔴" if t['rupees'] < 0 else "✅"
            tg(f"🅰️ <b>SHADOW</b> lotA = LIVE exit {t['side']}{t['strike']} @ {t['xo']} "
               f"[{t['reason']}] ({t['pts']:+.1f}pt, Rs{t['rupees']:+.0f}) {emo} | {t['exit']}\n"
               f"→ lotB now floored at x={t['xo']}, trailing in {STEP}-pt steps")
            rec['lotA_alert'] = True
        if rec.get('lotB_done'): continue

        lb = lotB_from_trade(t, now)
        rec['lotB_bstop'] = lb.get('bstop'); rec['lotB_peak'] = lb.get('peak')
        if lb['done']:
            rupB = round((lb['xo'] - t['eo']) * LOT)
            two = t['rupees'] + rupB
            rec.update(lotB_done=True, lotB_xo=lb['xo'], lotB_reason=lb['reason'],
                       lotB_exit=lb['exit'], rupeesB=rupB)
            if lb['reason'] == 'sl_with_lotA':
                tg(f"🅱️ <b>SHADOW</b> lotB exits WITH lotA (level broke, SL) @ {lb['xo']} Rs{rupB:+.0f}\n"
                   f"📦 {t['side']}{t['strike']}: 1-lot(live) Rs{t['rupees']:+.0f} → 2-lot Rs{two:+.0f} "
                   f"(2nd lot Rs{rupB:+.0f})")
            else:
                emo = "🔴" if rupB < 0 else "✅"
                tg(f"🅱️ <b>SHADOW</b> lotB exit @ {lb['xo']} [{lb['reason']}] Rs{rupB:+.0f} {emo} | "
                   f"{lb['exit']} (peak {lb.get('peak')})\n"
                   f"📦 {t['side']}{t['strike']}: 1-lot(live) Rs{t['rupees']:+.0f} → "
                   f"<b>2-lot Rs{two:+.0f}</b> (2nd lot added Rs{rupB:+.0f})")
            book_row(dict(day=day, entry=e, side=t['side'], strike=t['strike'], level=t.get('level'),
                          eo=t['eo'], xoA=t['xo'], rupeesA=t['rupees'], reasonA=t['reason'],
                          lotB_xo=lb['xo'], rupeesB=rupB, lotB_reason=lb['reason'],
                          lotB_exit=lb['exit'], two_lot=two))
        elif not rec.get('lotB_riding_alert') and t['xo'] >= t['eo']:
            tg(f"🅱️ <b>SHADOW</b> lotB riding {t['side']}{t['strike']} — bstop {lb.get('bstop')}, "
               f"peak {lb.get('peak')}, ltp {lb.get('ltp')} (books at bstop on pullback, else EOD)")
            rec['lotB_riding_alert'] = True

    # EOD summary — once, after the last 1m bar, when every lotB is finalized
    hm = now.hour * 60 + now.minute
    if hm >= 15 * 60 + 31 and not st.get("eod") and closed and \
       all(trades.get(t['entry'], {}).get('lotB_done') for t in closed):
        rows = [trades[t['entry']] for t in closed]
        A = sum(r.get('rupeesA', 0) for r in rows)
        B = sum(r.get('rupeesB', 0) for r in rows)
        two = A + B
        Aw = sum(1 for r in rows if r.get('rupeesA', 0) > 0)
        twow = sum(1 for r in rows if (r.get('rupeesA', 0) + r.get('rupeesB', 0)) > 0)
        pct = f" ({100*B/A:+.1f}%)" if A > 0 else ""
        lines = [f"💰 <b>LVL SHADOW 2-LOT {day}</b> (paper, full lot {LOT})"]
        for i, r in enumerate(rows, 1):
            lines.append(f" T{i} {r.get('side')}{r.get('strike')} {r.get('level')}: "
                         f"live {r.get('eo')}→{r.get('xoA')} Rs{r.get('rupeesA',0):+.0f} | "
                         f"lotB→{r.get('lotB_xo')} [{r.get('lotB_reason')}] Rs{r.get('rupeesB',0):+.0f} | "
                         f"2-lot Rs{r.get('rupeesA',0)+r.get('rupeesB',0):+.0f}")
        lines.append(f"<b>1-LOT (live-logic): Rs{A:+.0f}</b> | {len(rows)}tr {Aw}W")
        lines.append(f"<b>2-LOT strategy: Rs{two:+.0f}</b> | {twow}W | 2nd lot added <b>Rs{B:+.0f}</b>{pct}")
        rp, rn = real_live_today(day)
        if rp is not None and rn:
            lines.append(f"(real live qty=1 today: Rs{rp:+.0f} / {rn}tr — micro size, for context)")
        lines.append("ⓘ idealised fills; slippage+brokerage haircut not modelled")
        tg("\n".join(lines))
        st["eod"] = True

    st["trades"] = trades; save_state(st)
    log.info(f"[SHADOW {day}] closed={len(closed)} open={'yes' if openp else 'no'} "
             f"tracked={len(trades)}")

def loop():
    log.info(f"[SHADOW] loop start {datetime.now(IST)} | step={STEP} lot={LOT} PAPER-ONLY")
    tg(f"🫧 <b>LVL SHADOW 2-LOT</b> started (paper, NIFTY, step{STEP}, full lot {LOT}) — "
       f"lotA mirrors LIVE, lotB = x-anchored step-trail. No orders.")
    while True:
        now = datetime.now(IST); hm = now.hour * 60 + now.minute
        if hm >= 15 * 60 + 34:
            log.info(f"[SHADOW] market closed, loop exit {now}"); break
        if hm >= 9 * 60 + 15:
            try: run_once()
            except Exception as e:
                log.error(f"[SHADOW] run err {e}"); tg(f"🚨 <b>SHADOW</b> run error: {e}")
        time.sleep(60)

if __name__ == "__main__":
    if "loop" in sys.argv: loop()
    else: run_once()
