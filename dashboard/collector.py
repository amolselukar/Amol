#!/usr/bin/env python3
"""ORION dashboard collector — 2026-08-26.

Builds a PERMANENT engine-wise daily P&L archive so past performance never has
to be re-derived by hand:

    ~/Amol/dashboard/data/snapshots.json   append-only capture store (the truth)
    ~/Amol/dashboard/data/history.json     derived view the dashboard reads

Why a separate append-only store: each bot keeps the day's closed trades in
`trades_today` inside its state file, and WIPES it at the next day boundary.
The flight-recorder logs are not a reliable fallback (the SENSEX ones on disk
and in git contain only the boot banner). So this collector must run while a
day's trades are still in the state file and keep its own copy forever. Run it
on a cron during and after market hours; it is safe to run any number of times.

Sources (all read-only; nothing here ever writes to a bot's own files):
  1. state_*.json `trades_today`   -> captured per day, per engine, forever
  2. FlightRecorder ENTRY/EXIT log -> backfill for older days, each pair
     validated against the logged `pnl/sh`
  3. apex_/t5_/exp12_ shadow CSVs  -> shadow-book engines
  4. Stocks_TradeBook.csv          -> STOCKS_V1 closed trades
  5. state_STOCKS.json + state_*   -> positions still open right now

Log timestamps are UTC (system TZ=UTC); everything is converted to IST.
"""
import csv
import datetime as dt
import glob
import json
import os
import re
import sys

AMOL = os.path.expanduser("~/Amol")
HOME = os.path.expanduser("~")
DATA = os.path.join(AMOL, "dashboard", "data")
SNAP = os.path.join(DATA, "snapshots.json")
OUT = os.path.join(DATA, "history.json")

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
IST_OFFSET = dt.timedelta(hours=5, minutes=30)

BOTS = {
    "NIFTY V2.5.20": {
        "logs": "Nifty_FlightRecorder_V2_5_20_*.log",
        "lot": 65, "lots_per_engine": {"FUT5VWAP": 3}, "default_lots": 1,
        "state": "state_V2_5_20.json",
        "shadow": {"APEX": "apex_shadow_v2520_trades.csv",
                   "T5": "t5_shadow_v2520_trades.csv",
                   "EXP12": "exp12_shadow_v2520_trades.csv"},
    },
    "SENSEX V2.5.20": {
        "logs": "Sensex_FlightRecorder_V2_5_20-SENSEX_*.log",
        "lot": 20, "lots_per_engine": {"FUT5VWAP": 3}, "default_lots": 1,
        "state": "state_V2_5_20-SENSEX.json",
        "shadow": {"EXP12": "sensex_exp12_shadow_trades.csv"},
    },
}

# What each engine actually does — shown on the dashboard's Logic tab so the
# rules never have to be looked up in 390k lines of bot source again.
ENGINE_LOGIC = {
    "BASE": "V2 core. 1h SMA20/50 regime + 15m StochRSI K (CE K>=38 rising, "
            "PE K<=80 falling). Exits: HARDSL -15pt fixed, trail arms at "
            "entry*1.15.",
    "VWAP": "Triple VWAP confirmation with FUTURES VWAP as the primary gate; "
            "spot and option VWAP confirm. Exit on option 15m close below its "
            "own VWAP. Persist-gate + cooldown filters live since 08-21.",
    "FUT5VWAP": "Futures 5-min VWAP cross with candle-body and pivot-distance "
                "filters. Runs 3 lots (only engine that does). Stop:lock ratio "
                "deliberately left un-tuned — the sweep was non-monotonic.",
    "ORB": "Opening-range breakout, H3 rule since 09-14: 5m break must be "
           "confirmed by the NEXT 5m bar, then buy the pullback to the OR edge "
           "(1m close within 8pt, within 45 min). No premium stop: exit only on a "
           "1m spot close back inside the OR by >10pt. +18 lock, chandelier peak-8, "
           "no flip. Chop-kill and SIDEWAYS stand-down unchanged.",
    "GAPBREAK": "Gap-open continuation break, confirmed against the opening "
                "range. Same universal exit ladder as ORB.",
    "STOCH": "NEW 09-14. Counter-trend scalp: 15m Stochastic %K(5) SMA(3) on "
             "completed spot bars crosses INTO >=80 -> buy nearest-50 ATM PE, "
             "INTO <=20 -> buy ATM CE. FIXED +14 Rs target, -10 Rs stop, 60-min "
             "time-out, 15:20 square-off. No trail. Exempt from the veto and the "
             "renko gate (counter-trend by design).",
    "RENKO_GATE": "NEW 09-14. Sits above VWAP/ORB/FUT5VWAP/V2: brick = mean of "
                  "last 5 session ranges / 12 (fixed at boot); close-based renko "
                  "on today's completed 1m spot closes; direction established "
                  "only when the last 2 bricks share a colour; entry allowed only "
                  "if it agrees with the side, neutral blocked. V2 is also "
                  "evaluated in a CHOP regime when the renko direction is "
                  "established. Replay on 114 live trades: Rs-3,821 -> +7,962.",
    "EXPIRY": "AFT mode since 09-14: the morning round-50 cross only PICKS the "
              "near-ATM strike; the buy is the first tick >= 14:00 with premium "
              "Rs5-60; no stop; lock arms at 1.5x and keeps half the gain; 15:25 "
              "force close. 48-expiry replay: old morning buy 25% win Rs-10,454; "
              "AFT n=34 68% +Rs6,021 (thin, forward test).",
    "APEX": "Shadow book. Confluence method (level + premium divergence). "
            "Known open leak: the exhaust-exit, reconfirmed 07-28.",
    "T5": "Shadow book. 5-minute trigger variant; timeout-based exit.",
    "EXP1": "Expiry Engine 1 (shadow). RSI-snap on 3-min bars + OI15<=+5% + "
            "spot-through-strike. Since 08-25: NO stop loss; a 20% trail arms "
            "only after the premium doubles, else rides to the 15:28 force "
            "exit. Entry window 14:30-15:25.",
    "EXP2": "Expiry Engine 2 (shadow). Cheap-ladder: buy the Rs8-20 (NIFTY) / "
            "Rs26-66 (SENSEX) band in the max-OI strike zone, OI15<=+5%, "
            "spot-through-strike relaxed. Exit = 20% trail after the premium "
            "arms at Rs40/130. No percentage stop — never use one on cheap "
            "options.",
    "EXP2W": "NEW 08-26. Identical to EXP2 PLUS the was-expensive selection "
             "filter: the option's afternoon high (from 13:00) must have "
             "reached Rs40 (NIFTY) / Rs130 (SENSEX) and the premium must decay "
             "DOWN into the band. Runs in parallel with EXP2 so the difference "
             "between the two books isolates the filter's effect.",
    "STOCKS": "STOCKS_V1 stock options. 10 core + 10 daily movers, ATM monthly "
              "CE/PE. Two entry paths: breakout (20-day level + volume) and "
              "the GTT morning premium-dip limit order. Exits: SL (breakout: "
              "back through the level by 0.5*ATR; GTT: wide patience stop at "
              "the OPPOSITE 20-day level), TRAIL (peak -0.6*ATR after 1*ATR "
              "in favour), PREM_STOP (premium <=50% of entry), TIME (day 5 at "
              "15:20). Positions carry overnight, 5 trading days max.",
}

ENTRY_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] ENTRY: "
    r"(?P<sym>\S+) @ (?P<px>[\d.]+)\s+engine=(?P<eng>\S+)")
EXIT_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] EXIT: "
    r"(?P<sym>\S+) @ (?P<px>[\d.]+) reason=(?P<rsn>\S+) pnl/sh=(?P<pnl>[-+][\d.]+)")


def lots(cfg, engine):
    return cfg["lots_per_engine"].get(engine, cfg["default_lots"])


def load_snapshots():
    if os.path.exists(SNAP):
        try:
            return json.load(open(SNAP))
        except ValueError:
            pass
    return {}


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)


def capture_states(snaps):
    """Merge each bot's CURRENT trades_today into the append-only store.

    Keyed by (date, bot, engine, entry_time, symbol) so re-running mid-session
    adds new trades without ever duplicating or dropping earlier ones.
    """
    added = 0
    for bot, cfg in BOTS.items():
        sp = os.path.join(AMOL, cfg["state"])
        if not os.path.exists(sp):
            continue
        try:
            st = json.load(open(sp))
        except (OSError, ValueError):
            continue
        day = st.get("date")
        if not day:
            continue
        bucket = snaps.setdefault(day, {}).setdefault(bot, [])
        have = {(t.get("engine"), t.get("entry_time"), t.get("symbol"),
                 round(float(t.get("entry", 0)), 2)) for t in bucket}
        for eng, es in (st.get("engines") or {}).items():
            for t in (es or {}).get("trades_today") or []:
                eng_name = t.get("engine") or eng
                k = (eng_name, t.get("entry_time"), t.get("symbol"),
                     round(float(t.get("entry", 0)), 2))
                if k in have:
                    continue
                have.add(k)
                bucket.append({
                    "engine": eng_name, "symbol": t.get("symbol", ""),
                    "side": t.get("side", ""), "entry": t.get("entry", 0.0),
                    "exit": t.get("exit", 0.0), "pnl_sh": t.get("pnl", 0.0),
                    "reason": t.get("reason", ""),
                    "entry_time": t.get("entry_time", ""),
                    "elapsed_min": round(t.get("elapsed_min") or 0, 1),
                    "src": "state",
                })
                added += 1
    return added


def parse_logs(cfg):
    """Backfill older days by pairing ENTRY->EXIT per symbol."""
    trades, open_by_sym = [], {}
    stats = {"entries": 0, "exits": 0, "matched": 0, "unmatched_exits": 0,
             "pnl_mismatch": 0, "still_open": 0}
    lines, seen = [], set()
    for fp in sorted(glob.glob(os.path.join(AMOL, cfg["logs"]))):
        try:
            with open(fp, errors="replace") as fh:
                for ln in fh:
                    if (" ENTRY: " in ln or " EXIT: " in ln) and ln.strip() not in seen:
                        seen.add(ln.strip())
                        lines.append(ln)
        except OSError:
            continue
    lines.sort(key=lambda l: l[:19])

    for ln in lines:
        m = ENTRY_RE.match(ln)
        if m:
            stats["entries"] += 1
            t = dt.datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S") + IST_OFFSET
            open_by_sym.setdefault(m.group("sym"), []).append(
                {"eng": m.group("eng"), "entry": float(m.group("px")), "t": t})
            continue
        m = EXIT_RE.match(ln)
        if not m:
            continue
        stats["exits"] += 1
        stack = open_by_sym.get(m.group("sym")) or []
        exit_px, pnl_sh = float(m.group("px")), float(m.group("pnl"))
        pick = None
        for i in range(len(stack) - 1, -1, -1):
            if abs((exit_px - stack[i]["entry"]) - pnl_sh) < 0.02:
                pick = i
                break
        if pick is None:
            if not stack:
                stats["unmatched_exits"] += 1
                continue
            pick = len(stack) - 1
            stats["pnl_mismatch"] += 1
        e = stack.pop(pick)
        te = dt.datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S") + IST_OFFSET
        stats["matched"] += 1
        trades.append({"date": te.date().isoformat(), "engine": e["eng"],
                       "symbol": m.group("sym"), "entry": e["entry"],
                       "exit": exit_px, "pnl_sh": round(exit_px - e["entry"], 2),
                       "entry_time": e["t"].strftime("%H:%M:%S"),
                       "exit_time": te.strftime("%H:%M:%S"),
                       "reason": m.group("rsn"), "src": "log"})
    stats["still_open"] = sum(len(v) for v in open_by_sym.values())
    return trades, stats


def parse_shadow_csv(path, eng_of):
    out = []
    if not os.path.exists(path):
        return out
    try:
        with open(path) as fh:
            for r in csv.DictReader(fh):
                if not r.get("date"):
                    continue
                try:
                    rs = float(r.get("rupees") or 0)
                except ValueError:
                    continue
                out.append({"date": r["date"], "engine": eng_of(r),
                            "symbol": f"{r.get('strike','')}{r.get('side','')}",
                            "entry": float(r.get("entry") or 0),
                            "exit": float(r.get("exit") or 0),
                            "entry_time": r.get("entry_time", ""),
                            "exit_time": r.get("exit_time", ""),
                            "pnl_rs": rs, "reason": r.get("reason", ""),
                            "src": "shadow-csv"})
    except OSError:
        pass
    return out


def parse_stocks():
    path = os.path.join(AMOL, "Stocks_TradeBook.csv")
    out = []
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for r in csv.DictReader(fh):
            if r.get("action") != "EXIT" or not r.get("pnl_rs"):
                continue
            try:
                rs = float(r["pnl_rs"])
            except ValueError:
                continue
            ts = r["ts"][:19]
            out.append({"date": ts[:10], "engine": "STOCKS",
                        "symbol": r.get("symbol", ""), "stock": r.get("stock", ""),
                        "side": r.get("side", ""),
                        "entry": float(r.get("opt_price") or 0), "exit": 0.0,
                        "entry_time": "", "exit_time": ts[11:19], "pnl_rs": rs,
                        "reason": r.get("reason", ""),
                        "held_days": r.get("held_days", ""), "src": "tradebook"})
    return out


def open_positions():
    out = []
    for bot, cfg in BOTS.items():
        sp = os.path.join(AMOL, cfg["state"])
        if not os.path.exists(sp):
            continue
        try:
            st = json.load(open(sp))
        except (OSError, ValueError):
            continue
        for eng, es in (st.get("engines") or {}).items():
            p = (es or {}).get("pos") or {}
            if not p.get("active"):
                continue
            e = p.get("engine") or eng
            out.append({"bot": bot, "engine": e, "symbol": p.get("symbol", ""),
                        "side": p.get("side", ""),
                        "entry": p.get("entry_premium", 0.0),
                        "qty": cfg["lot"] * lots(cfg, e),
                        "entry_time": str(p.get("entry_time") or "")[:19]})
    sp = os.path.join(AMOL, "state_STOCKS.json")
    if os.path.exists(sp):
        try:
            st = json.load(open(sp))
        except (OSError, ValueError):
            st = {}
        for p in (st.get("open") or {}).values():
            out.append({"bot": "STOCKS_V1",
                        "engine": f"STOCKS/{p.get('kind','')}",
                        "symbol": p.get("symbol", ""), "stock": p.get("stock", ""),
                        "side": p.get("side", ""), "entry": p.get("entry_prem", 0.0),
                        "qty": p.get("lot", 0), "days_held": p.get("days_held", 0),
                        "src_list": p.get("src", ""), "sl_level": p.get("sl_level"),
                        "entry_stock": p.get("entry_stock"),
                        "atr": p.get("atr"), "peak": p.get("peak"),
                        "entry_time": str(p.get("entry_ts") or "")[:19]})
    return out


def build():
    snaps = load_snapshots()
    added = capture_states(snaps)
    save_json(SNAP, snaps)

    arch = {"generated": dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "bots": {}, "parse_stats": {}, "days": {},
            "engine_logic": ENGINE_LOGIC, "captured_now": added}

    def add(bot, date, engine, rs, detail):
        d = arch["days"].setdefault(date, {})
        b = d.setdefault(bot, {"engines": {}, "pnl_rs": 0.0, "trades": 0})
        e = b["engines"].setdefault(engine, {"pnl_rs": 0.0, "trades": 0,
                                             "wins": 0, "detail": []})
        e["pnl_rs"] += rs
        e["trades"] += 1
        e["wins"] += 1 if rs > 0 else 0
        e["detail"].append({**detail, "pnl_rs": round(rs)})
        b["pnl_rs"] += rs
        b["trades"] += 1

    # 1) captured state snapshots (authoritative for days we captured)
    captured = set()
    for date, bots in snaps.items():
        for bot, rows in bots.items():
            cfg = BOTS.get(bot)
            if not cfg:
                continue
            captured.add((date, bot))
            for t in rows:
                rs = t["pnl_sh"] * cfg["lot"] * lots(cfg, t["engine"])
                add(bot, date, t["engine"], rs, t)

    # 2) log backfill, only for (date, bot) not already captured from state
    for bot, cfg in BOTS.items():
        trades, stats = parse_logs(cfg)
        arch["parse_stats"][bot] = stats
        for t in trades:
            if (t["date"], bot) in captured:
                continue
            add(bot, t["date"], t["engine"],
                t["pnl_sh"] * cfg["lot"] * lots(cfg, t["engine"]), t)
        for eng, fn in cfg.get("shadow", {}).items():
            rows = parse_shadow_csv(
                os.path.join(AMOL, fn),
                (lambda r: r.get("engine") or "EXP12") if eng == "EXP12"
                else (lambda r, _e=eng: _e))
            for t in rows:
                add(bot, t["date"], t["engine"], t["pnl_rs"], t)
        arch["bots"][bot] = {"lot": cfg["lot"],
                             "lots_per_engine": cfg["lots_per_engine"],
                             "default_lots": cfg["default_lots"],
                             "state_file": cfg["state"]}

    for t in parse_stocks():
        add("STOCKS_V1", t["date"], "STOCKS", t["pnl_rs"], t)
    arch["bots"]["STOCKS_V1"] = {"lot": "per-stock F&O lot",
                                 "lots_per_engine": {}, "default_lots": 1,
                                 "state_file": "state_STOCKS.json"}

    for d in arch["days"].values():
        for b in d.values():
            b["pnl_rs"] = round(b["pnl_rs"])
            for e in b["engines"].values():
                e["pnl_rs"] = round(e["pnl_rs"])

    arch["open_positions"] = open_positions()
    save_json(OUT, arch)
    return arch


if __name__ == "__main__":
    a = build()
    print(f"captured {a['captured_now']} new trades into snapshots.json")
    print(f"wrote {OUT}  |  days archived: {len(a['days'])}")
    for bot, s in a["parse_stats"].items():
        print(f"  log-parse {bot}: {s}")
    tot = {}
    for d in a["days"].values():
        for bot, b in d.items():
            tot[bot] = tot.get(bot, 0) + b["pnl_rs"]
    for bot, v in sorted(tot.items()):
        print(f"  TOTAL {bot}: Rs{v:+,.0f}")
    print(f"  open positions now: {len(a['open_positions'])}")
    if "--show" in sys.argv:
        for day in sorted(a["days"])[-8:]:
            print(f"\n{day}")
            for bot, b in a["days"][day].items():
                engs = " ".join(f"{k}:Rs{v['pnl_rs']:+,.0f}"
                                for k, v in sorted(b["engines"].items()))
                print(f"   {bot:15s} Rs{b['pnl_rs']:+9,.0f} | {engs}")
