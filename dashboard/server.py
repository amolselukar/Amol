#!/usr/bin/env python3
"""ORION dashboard server — 2026-08-26. Python stdlib only, no dependencies.

Serves the engine-wise performance archive plus live index/stock prices.

    python3 ~/Amol/dashboard/server.py [--port 8787] [--host 127.0.0.1]

Routes
  /                 dashboard page (token-gated when ORION_DASH_TOKEN is set)
  /api/history      the archive built by collector.py
  /api/live         live NIFTY/SENSEX + live LTP and unrealized P&L for every
                    open position (15s cache)

A background thread re-runs the collector every 60s, so today's trades appear
without a restart. Read-only with respect to every bot file.
"""
import argparse
import json
import os
import sys
import threading
import time
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.expanduser("~/Amol"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import collector  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TOKEN = os.environ.get("ORION_DASH_TOKEN", "")

_live_lock = threading.Lock()
_live_cache = {"ts": 0.0, "data": {}}
_kite = None
_kite_err = ""


def get_kite():
    global _kite, _kite_err
    if _kite is not None:
        return _kite
    try:
        import credentials as c
        from upstox_kite_shim import UpstoxKite
        _kite = UpstoxKite(c.UPSTOX_ACCESS_TOKEN)
        _kite.ltp(["NSE:NIFTY 50"])
        _kite_err = ""
    except Exception as e:            # noqa: BLE001 - surfaced to the page
        _kite, _kite_err = None, f"{type(e).__name__}: {e}"
    return _kite


def live_snapshot():
    """Live prices + unrealized P&L per open position. Cached 15s."""
    with _live_lock:
        if time.time() - _live_cache["ts"] < 15 and _live_cache["data"]:
            return _live_cache["data"]

    out = {"ts": dt.datetime.now(IST).strftime("%H:%M:%S IST"),
           "index": {}, "positions": [], "error": ""}
    try:
        hist = json.load(open(collector.OUT))
    except (OSError, ValueError):
        hist = {"open_positions": []}
    positions = hist.get("open_positions", [])

    k = get_kite()
    if k is None:
        out["error"] = f"live prices unavailable ({_kite_err})"
    else:
        wants = ["NSE:NIFTY 50", "BSE:SENSEX"]
        for p in positions:
            if p.get("symbol"):
                exch = "BFO" if "SENSEX" in p["symbol"] else "NFO"
                sym = p["symbol"] if ":" in p["symbol"] else f"{exch}:{p['symbol']}"
                wants.append(sym)
            if p.get("stock"):
                wants.append(f"NSE:{p['stock']}")
        try:
            q = k.ltp(list(dict.fromkeys(wants)))
        except Exception as e:        # noqa: BLE001
            q, out["error"] = {}, f"{type(e).__name__}: {e}"
        out["index"] = {
            "NIFTY": (q.get("NSE:NIFTY 50") or {}).get("last_price"),
            "SENSEX": (q.get("BSE:SENSEX") or {}).get("last_price"),
        }
        for p in positions:
            sym = p.get("symbol", "")
            if sym and ":" not in sym:
                sym = f"{'BFO' if 'SENSEX' in sym else 'NFO'}:{sym}"
            ltp = (q.get(sym) or {}).get("last_price")
            row = dict(p)
            row["ltp"] = ltp
            row["stock_ltp"] = (q.get(f"NSE:{p['stock']}") or {}).get(
                "last_price") if p.get("stock") else None
            if ltp is not None and p.get("entry") and p.get("qty"):
                row["unreal_rs"] = round((ltp - p["entry"]) * p["qty"])
                row["unreal_pct"] = round((ltp / p["entry"] - 1) * 100, 1)
            out["positions"].append(row)

    with _live_lock:
        _live_cache.update(ts=time.time(), data=out)
    return out


def refresher():
    while True:
        try:
            collector.build()
        except Exception as e:        # noqa: BLE001
            print(f"[collector] {type(e).__name__}: {e}", flush=True)
        time.sleep(60)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authed(self, q):
        if not TOKEN:
            return True
        if (q.get("t") or [""])[0] == TOKEN:
            return True
        return self.headers.get("X-Dash-Token") == TOKEN

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authed(q):
            self._send(403, "forbidden — append ?t=<token> to the URL", "text/plain")
            return
        if u.path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "static", "index.html"), "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            except OSError as e:
                self._send(500, f"missing page: {e}", "text/plain")
        elif u.path == "/api/history":
            try:
                with open(collector.OUT, "rb") as fh:
                    self._send(200, fh.read())
            except OSError:
                self._send(200, json.dumps({"days": {}, "bots": {},
                                            "open_positions": []}))
        elif u.path == "/api/live":
            self._send(200, json.dumps(live_snapshot()))
        elif u.path == "/api/refresh":
            collector.build()
            self._send(200, json.dumps({"ok": True}))
        else:
            self._send(404, "not found", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    collector.build()
    threading.Thread(target=refresher, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    tok = f" (token required)" if TOKEN else ""
    print(f"ORION dashboard on http://{a.host}:{a.port}/{tok}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
