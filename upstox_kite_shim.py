#!/usr/bin/env python3
"""
upstox_kite_shim.py — drop-in Kite-API-compatible client backed by Upstox
(2026-08-26, per user: "today EOD we will stop using kite and use only
upstox api only").

Exposes a class UpstoxKite whose surface matches the subset of kiteconnect
the ORION bots actually use:

    kite = UpstoxKite(access_token)      # UPSTOX extended token (read-only,
    kite.set_access_token(tok)           #   valid ~1yr, see UPSTOX_REFERENCE.md)
    kite.profile()
    kite.instruments("NFO"|"NSE"|"BFO"|"BSE")
    kite.historical_data(token, frm, to, interval[, continuous[, oi]])
    kite.quote([...symbols...]) / kite.ltp([...symbols...])

Compatibility decisions (all verified live 2026-08-26 before deployment):
- instrument_token returned by instruments() IS the Upstox instrument_key
  string (e.g. "NSE_FO|46913"). historical_data() accepts either that key or
  the two legacy hard-coded Kite index tokens (256265 NIFTY spot, 265 SENSEX
  spot) which are mapped to the Upstox index keys.
- tradingsymbol is SYNTHESIZED in Kite's format (TCS26SEP2300PE /
  NIFTY2690224500CE weekly) from asset+expiry+strike, NOT Upstox's spaced
  format. This keeps carried state files (state_STOCKS.json), Telegram text
  and the dormant mStock live path identical to the Kite era. Upstox's own
  quote response keys happen to use the same compact format, but we map
  responses back via the instrument_token field, not the key text.
- historical candles: Upstox v3 serves completed days via /historical-candle/
  and TODAY's bars via /historical-candle/intraday/ — the shim stitches both
  and returns ascending Kite-style dict rows with tz-aware IST 'date'.
  Candle format [ts,o,h,l,c,volume,oi] — real per-minute OI (Kite never had
  OI at all; callers passing oi=True now get true values).
- instrument masters come from assets.upstox.com {NSE,BSE}.json.gz, cached
  on disk per calendar day (upstox_assets_cache/) and in memory per process,
  so EXP12's 5-min universe re-resolve does NOT re-download.

No write/order endpoints are used anywhere — bots are paper; the read-only
extended token is sufficient and needs NO daily login (auto_login.py for
Kite is retired from the launchers).
"""

import os, io, json, gzip, time
from datetime import datetime, date, timedelta

import requests as _rq
import pytz

IST = pytz.timezone("Asia/Kolkata")
_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_DIR, "upstox_assets_cache")

_ASSETS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{exch}.json.gz"
_BASE = "https://api.upstox.com"

_MONTH3 = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_WEEKCODE = "123456789OND"   # Kite weekly symbol month code

# legacy Kite spot tokens still hard-coded in the bots
_LEGACY_TOKEN_MAP = {
    256265: "NSE_INDEX|Nifty 50",     # NSE NIFTY 50
    265:    "BSE_INDEX|SENSEX",       # BSE SENSEX
    260105: "NSE_INDEX|Nifty Bank",
}

CHANGE_HISTORY = """
STATUS legend: [BT] backtested  [FWD] forward-paper only  [USER] user-directed
               [FIX] bug fix    [UNVAL] unvalidated

SHIM [2026-08-26] Created. Drop-in Kite-compatible client over Upstox v3, so all
  three bots migrate with no engine changes. Long-lived read-only token, no
  daily login. Candle/quote/OI parity verified live before deployment.  [USER]

SHIM [2026-08-29] *** INTRADAY FORMING-BAR FIX ***
  WHAT: for TODAY's bars, historical_data() now fetches 1-MINUTE intraday and
  aggregates locally (_resample_1m) instead of asking the intraday endpoint for
  5m/15m/1h directly. Completed sessions still come from the historical
  endpoint unchanged. Same number of API calls.
  WHY: the intraday endpoint is built around COMPLETED intervals, so the
  forming 15m bar appeared 0-6 min late; Kite returned the partial bar from the
  first tick. The engines read iloc[-2] assuming iloc[-1] is the forming bar, so
  when it was absent they evaluated a bar 30-45 min old, and the 16-min stale
  guard blocked entries on 18 of 77 Nifty cycles on 08-27.
  Upstox is NOT slower than Kite — 1m/tick data is as fast. Wrong endpoint
  granularity was chosen in the 08-26 migration, then blamed on the vendor.
  NOT DONE ON PURPOSE: raising the stale guard 16 -> 21 min. That hides the
  problem — the engines would read stale indicators SILENTLY instead of loudly.
  EVIDENCE: 52/52 instrument-day-interval combinations reproduce Upstox's OWN
  bars EXACTLY (O/H/L/C/volume/OI) — NIFTY spot, SENSEX spot, NIFTY futures and
  5 option strikes from ATM to far-OTM, 5m/15m/1h, 08-25..08-28. Buckets are
  anchored to the 09:15 session open, verified against Upstox's own 60minute
  bars which start 09:15/10:15/11:15 (NOT clock hours). A never-traded strike
  returns 0 bars at every interval both before and after, so no regression.
  STATUS: offline-verified only. MUST be confirmed against the LIVE feed at the
  next market open — that the forming bar is present within ~1 min of each
  interval and [STALE] events drop to zero.
  REVERT: upstox_kite_shim_BACKUP_20260829_pre_1m_resample.py  [FIX]
SHIM [2026-09-20] *** QUOTES v2 -> v3 (deprecation migration) ***
  WHAT: the two remaining v2 calls, /v2/market-quote/ltp (token check) and
  /v2/market-quote/quotes (all chain quotes), now call the v3 paths. Candles
  were already v3. No other line changed.
  WHY: Upstox deprecation notice lists Market LTP Quotes V2 and Market Quotes
  V2 for removal with no published sunset date; a silent switch-off would
  drop every option quote in both bots mid-session.
  EVIDENCE: live parity 2026-09-20 12:54 on Nifty 50, SENSEX, NIFTY26DEC27000CE:
  v2 and v3 return identical data-map keys (EXCHANGE:SYMBOL), identical
  instrument_token / last_price / volume / oi / average_price / net_change /
  ohlc / depth. v3 only ADDS fields (ltq, cp; prev_close_price, previous_oi,
  cas_eligible, indicative_equilibrium_price ...) which the shim ignores.
  STATUS: parity-verified off-market; boot proof = 09-21 09:02 both bots
  "[BOOT] token ok" + first chain quote.  [FIX]
  REVERT: upstox_kite_shim_BACKUP_20260920_pre_v3_quotes.py
"""
CODE_FINGERPRINT = "7822c543ba40baa73e28f009a0c86193fd8f33f12b9531c354db84859d6f8b83"


# --- 2026-08-29: intraday forming-bar fix -------------------------------------
# PROBLEM (found 08-27, root-caused 08-29): /historical-candle/intraday/ is built
# around COMPLETED intervals, so on a 15-minute request the FORMING bar only
# appears 0-6 min after the interval opens. Kite returned the partial bar from
# the first tick. The bots read df15['K'].iloc[-2] assuming iloc[-1] is the
# forming bar; when it is absent, iloc[-2] is a bar 30-45 min old. Evidence:
# ZERO [STALE] events in ~37 Kite trading days, 50 on the FIRST Upstox day.
# Upstox is NOT slower than Kite -- its 1-minute/tick data is as fast. We were
# asking the wrong endpoint granularity, then blaming the vendor.
#
# FIX: for TODAY's bars, fetch 1-MINUTE intraday and aggregate locally. The
# forming bar then exists as soon as the first minute of the interval closes,
# and iloc[-1]/iloc[-2] mean exactly what every engine and every backtest
# assumes. Completed sessions still come from the historical endpoint unchanged
# (correct already, and one call instead of ~375).
#
# Buckets are anchored to the 09:15 session open, NOT to the clock hour --
# verified against Upstox's own 60minute bars, which start 09:15/10:15/11:15.
SESSION_OPEN = (9, 15)

def _bucket_start(dt, unit, n):
    """Session-anchored bucket start for dt. Mirrors Kite's bar boundaries."""
    open_dt = dt.replace(hour=SESSION_OPEN[0], minute=SESSION_OPEN[1],
                         second=0, microsecond=0)
    if dt < open_dt:                      # pre-open ticks: leave them alone
        return dt.replace(second=0, microsecond=0)
    width = n * 60 if unit == "minutes" else n * 3600
    delta = int((dt - open_dt).total_seconds())
    return open_dt + timedelta(seconds=(delta // width) * width)


def _resample_1m(candles, unit, n):
    """Aggregate raw 1-minute Upstox candles [ts,o,h,l,c,vol,oi] into n-unit bars.
    open=first, high=max, low=min, close=last, volume=sum, oi=last (OI is a
    level, not a flow -- summing it would be meaningless)."""
    if unit == "days" or (unit == "minutes" and n == 1):
        return candles
    buckets = {}
    order = []
    for c in candles:
        dt = datetime.fromisoformat(c[0]).astimezone(IST)
        b = _bucket_start(dt, unit, n)
        if b not in buckets:
            buckets[b] = [b.isoformat(), c[1], c[2], c[3], c[4],
                          int(c[5] or 0), (c[6] if len(c) > 6 else 0)]
            order.append(b)
        else:
            r = buckets[b]
            r[2] = max(r[2], c[2])          # high
            r[3] = min(r[3], c[3])          # low
            r[4] = c[4]                     # close = last
            r[5] += int(c[5] or 0)          # volume = sum
            if len(c) > 6:
                r[6] = c[6]                 # oi = last
    return [buckets[b] for b in sorted(order)]


_INTERVAL_MAP = {
    "minute":   ("minutes", 1),
    "2minute":  ("minutes", 2),
    "3minute":  ("minutes", 3),
    "5minute":  ("minutes", 5),
    "10minute": ("minutes", 10),
    "15minute": ("minutes", 15),
    "30minute": ("minutes", 30),
    "60minute": ("hours", 1),
    "day":      ("days", 1),
}

# which Upstox master file + segment feeds each Kite "exchange" argument
_EXCH_SPEC = {
    "NFO": ("NSE", "NSE_FO"),
    "NSE": ("NSE", "NSE_EQ"),
    "BFO": ("BSE", "BSE_FO"),
    "BSE": ("BSE", "BSE_EQ"),
}


def _fmt_strike(s):
    f = float(s)
    return str(int(f)) if f.is_integer() else ("%g" % f)


def _kite_symbol(asset, exp, itype, strike, weekly):
    yy = exp.strftime("%y")
    if itype == "FUT":
        return f"{asset}{yy}{_MONTH3[exp.month - 1]}FUT"
    if weekly:
        return f"{asset}{yy}{_WEEKCODE[exp.month - 1]}{exp.day:02d}{_fmt_strike(strike)}{itype}"
    return f"{asset}{yy}{_MONTH3[exp.month - 1]}{_fmt_strike(strike)}{itype}"


def _to_ist_dt(x, end_of_day=False):
    """Accept datetime / date / iso-string; return tz-aware IST datetime."""
    if isinstance(x, datetime):
        return x.astimezone(IST) if x.tzinfo else IST.localize(x)
    if isinstance(x, date):
        t = datetime(x.year, x.month, x.day,
                     23, 59, 59) if end_of_day else datetime(x.year, x.month, x.day)
        return IST.localize(t)
    s = str(x).strip()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.strptime(s[:10], "%Y-%m-%d")
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
    return dt.astimezone(IST) if dt.tzinfo else IST.localize(dt)


class UpstoxKite:
    def __init__(self, access_token=None, api_key=None):
        self._token = access_token
        self._raw = {}        # exch file ("NSE"/"BSE") -> parsed master list
        self._rows = {}       # kite exchange arg -> kite-shaped rows
        self._sym2key = {}    # "NFO:TCS26SEP2300PE" -> instrument_key
        self._key2sym = {}    # instrument_key -> preferred "EXCH:SYM"
        self._sess = _rq.Session()
        # 2026-10-18: sub-second quote micro-cache. ~12 engines + each open
        # position each call quote()/ltp() per tick for overlapping instruments,
        # so the same key was fetched many times/sec -> Upstox v3 burst limiter
        # (UDAPI10005 "Too Many Request") -> each 429 stalled the loop ~20s via
        # retries, worst on fast days (Oct-13 big move = 39 stalls). Caching by
        # instrument_key for _Q_CACHE_TTL seconds collapses the redundant calls
        # into one with no engine changes. Set _Q_CACHE_TTL=0 to disable.
        self._q_cache = {}    # instrument_key -> (monotonic_ts, entry_dict)
        self._Q_CACHE_TTL = float(os.environ.get("UPSTOX_QUOTE_TTL", "1.0"))

    # -- kiteconnect surface ------------------------------------------------
    def set_access_token(self, token):
        self._token = token

    def profile(self):
        # validates the token (raises on failure), mirroring k.profile()
        q = self._api_get("/v3/market-quote/ltp",
                          params={"instrument_key": "NSE_INDEX|Nifty 50"})
        if q.get("status") != "success":
            raise RuntimeError(f"Upstox token check failed: {q}")
        return {"user_name": "upstox-shim", "broker": "UPSTOX"}

    def instruments(self, exchange="NFO"):
        exchange = (exchange or "NFO").upper()
        if exchange in self._rows:
            return self._rows[exchange]
        if exchange not in _EXCH_SPEC:
            raise ValueError(f"unsupported exchange {exchange}")
        exch_file, segment = _EXCH_SPEC[exchange]
        master = self._load_master(exch_file)
        rows = []
        if segment.endswith("_FO"):
            for r in master:
                if r.get("segment") != segment:
                    continue
                itype = r.get("instrument_type")
                if itype not in ("CE", "PE", "FUT"):
                    continue
                exp = datetime.fromtimestamp(r["expiry"] / 1000.0, IST).date()
                asset = r.get("asset_symbol") or r.get("underlying_symbol") or ""
                sym = _kite_symbol(asset, exp, itype,
                                   r.get("strike_price") or 0.0, bool(r.get("weekly")))
                key = r["instrument_key"]
                rows.append({
                    "instrument_token": key,
                    "exchange_token": r.get("exchange_token"),
                    "tradingsymbol": sym,
                    "name": asset,
                    "expiry": exp,
                    "strike": float(r.get("strike_price") or 0.0),
                    "tick_size": (r.get("tick_size") or 5.0) / 100.0,
                    "lot_size": int(r.get("lot_size") or 0),
                    "instrument_type": itype,
                    "segment": exchange + ("-FUT" if itype == "FUT" else "-OPT"),
                    "exchange": exchange,
                })
                self._register(exchange, sym, key)
        else:
            for r in master:
                if r.get("segment") != segment:
                    continue
                if r.get("instrument_type") != "EQ":
                    continue
                sym = r.get("trading_symbol")
                key = r["instrument_key"]
                if not sym:
                    continue
                rows.append({
                    "instrument_token": key,
                    "exchange_token": r.get("exchange_token"),
                    "tradingsymbol": sym,
                    "name": r.get("name") or sym,
                    "expiry": "",
                    "strike": 0.0,
                    "tick_size": (r.get("tick_size") or 5.0) / 100.0,
                    "lot_size": int(r.get("lot_size") or 1),
                    "instrument_type": "EQ",
                    "segment": exchange,
                    "exchange": exchange,
                })
                self._register(exchange, sym, key)
        # index aliases used by the bots ("NSE:NIFTY 50" style)
        for alias, key in (("NSE:NIFTY 50", "NSE_INDEX|Nifty 50"),
                           ("NSE:NIFTY BANK", "NSE_INDEX|Nifty Bank"),
                           ("BSE:SENSEX", "BSE_INDEX|SENSEX")):
            self._sym2key.setdefault(alias, key)
            self._key2sym.setdefault(key, alias)
        self._rows[exchange] = rows
        return rows

    def historical_data(self, token, frm, to, interval,
                        continuous=False, oi=False):
        key = _LEGACY_TOKEN_MAP.get(token, token)
        if not isinstance(key, str) or "|" not in key:
            raise ValueError(f"historical_data: unresolvable token {token!r}")
        if interval not in _INTERVAL_MAP:
            raise ValueError(f"historical_data: unsupported interval {interval}")
        unit, n = _INTERVAL_MAP[interval]
        frm_dt = _to_ist_dt(frm)
        to_dt = _to_ist_dt(to, end_of_day=True)
        today = datetime.now(IST).date()
        ekey = _rq.utils.quote(key, safe="")

        candles = []
        # completed sessions (Upstox historical endpoint serves up to the
        # previous trading day)
        hist_to = min(to_dt.date(), today - timedelta(days=1))
        if hist_to >= frm_dt.date():
            j = self._api_get(f"/v3/historical-candle/{ekey}/{unit}/{n}/"
                              f"{hist_to.isoformat()}/{frm_dt.date().isoformat()}")
            candles += (j.get("data") or {}).get("candles") or []
        # today's bars -- see the forming-bar note above _resample_1m().
        # Always pull 1-MINUTE intraday and aggregate locally, so the in-progress
        # bar exists from its first completed minute instead of 0-6 min late.
        if to_dt.date() >= today and frm_dt.date() <= today and unit != "days":
            j = self._api_get(f"/v3/historical-candle/intraday/{ekey}/minutes/1")
            today_1m = (j.get("data") or {}).get("candles") or []
            # Upstox returns newest-first; _resample_1m sorts by bucket, but the
            # within-bucket open/close depend on order, so normalise first.
            today_1m = sorted(today_1m, key=lambda c: c[0])
            candles += _resample_1m(today_1m, unit, n)

        out = []
        for c in candles:
            dt = datetime.fromisoformat(c[0]).astimezone(IST)
            if dt < frm_dt or dt > to_dt:
                continue
            row = {"date": dt, "open": c[1], "high": c[2], "low": c[3],
                   "close": c[4], "volume": int(c[5] or 0)}
            if oi:
                row["oi"] = int(c[6] or 0)
            out.append(row)
        out.sort(key=lambda r: r["date"])
        return out

    def quote(self, symbols):
        if isinstance(symbols, str):
            symbols = [symbols]
        want = {}   # instrument_key -> requested symbol string
        for s in symbols:
            k = self._resolve_symbol(s)
            if k:
                want[k] = s
        result = {}
        # serve instruments still within the micro-cache TTL; only fetch the rest
        now_m = time.monotonic()
        ttl = self._Q_CACHE_TTL
        to_fetch = []
        for ik, sym in want.items():
            hit = self._q_cache.get(ik) if ttl > 0 else None
            if hit and (now_m - hit[0]) <= ttl:
                result[sym] = dict(hit[1])   # copy so callers can't mutate the cache
            else:
                to_fetch.append(ik)
        for b in range(0, len(to_fetch), 400):
            batch = to_fetch[b:b + 400]
            j = self._api_get("/v3/market-quote/quotes",
                              params={"instrument_key": ",".join(batch)})
            for entry in (j.get("data") or {}).values():
                ik = entry.get("instrument_token")
                sym = want.get(ik)
                e = {
                    "instrument_token": ik,
                    "last_price": entry.get("last_price"),
                    "volume": entry.get("volume") or 0,
                    "oi": entry.get("oi") or 0,
                    "average_price": entry.get("average_price"),
                    "net_change": entry.get("net_change"),
                    "ohlc": entry.get("ohlc") or {},
                    "depth": entry.get("depth") or {},
                    "timestamp": entry.get("timestamp"),
                }
                if ttl > 0 and ik is not None:
                    self._q_cache[ik] = (time.monotonic(), e)
                if sym:
                    result[sym] = e
        return result

    def ltp(self, symbols):
        q = self.quote(symbols)
        return {s: {"instrument_token": v["instrument_token"],
                    "last_price": v["last_price"]} for s, v in q.items()}

    # -- internals ----------------------------------------------------------
    def _register(self, exchange, sym, key):
        full = f"{exchange}:{sym}"
        self._sym2key[full] = key
        self._sym2key.setdefault(sym, key)      # bare-symbol fallback
        self._key2sym.setdefault(key, full)

    def _resolve_symbol(self, s):
        if s in self._sym2key:
            return self._sym2key[s]
        if isinstance(s, str) and "|" in s:      # already an instrument_key
            return s
        # lazily load masters for the exchange prefix, then retry
        pfx = s.split(":", 1)[0] if ":" in s else None
        try:
            if pfx in _EXCH_SPEC:
                self.instruments(pfx)
            elif pfx in ("NSE", "BSE"):
                self.instruments(pfx)
            else:
                self.instruments("NFO"); self.instruments("NSE")
        except Exception:
            pass
        return self._sym2key.get(s)

    def _load_master(self, exch_file):
        if exch_file in self._raw:
            return self._raw[exch_file]
        os.makedirs(_CACHE_DIR, exist_ok=True)
        cache = os.path.join(_CACHE_DIR,
                             f"{exch_file}_{datetime.now(IST).date().isoformat()}.json.gz")
        data = None
        if os.path.exists(cache):
            try:
                data = json.load(gzip.open(cache))
            except Exception:
                data = None
        if data is None:
            r = self._sess.get(_ASSETS_URL.format(exch=exch_file), timeout=60)
            r.raise_for_status()
            data = json.load(gzip.open(io.BytesIO(r.content)))
            with open(cache, "wb") as f:
                f.write(r.content)
            # keep only today's cache files for this exchange
            for fn in os.listdir(_CACHE_DIR):
                if fn.startswith(exch_file + "_") and fn != os.path.basename(cache):
                    try:
                        os.remove(os.path.join(_CACHE_DIR, fn))
                    except OSError:
                        pass
        self._raw[exch_file] = data
        return data

    def _api_get(self, path, params=None, retries=3):
        last = None
        for attempt in range(retries):
            try:
                r = self._sess.get(_BASE + path, params=params, timeout=20,
                                   headers={"Authorization": f"Bearer {self._token}",
                                            "Accept": "application/json"})
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code in (400, 401, 403, 404):
                    break   # not transient — let caller's kite_safe decide
            except Exception as e:
                last = repr(e)
            time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(f"Upstox GET {path} failed: {last}")


if __name__ == "__main__":
    # smoke test: python3 upstox_kite_shim.py
    import credentials as c
    k = UpstoxKite(c.UPSTOX_ACCESS_TOKEN)
    print("profile:", k.profile())
    nfo = k.instruments("NFO")
    print("NFO rows:", len(nfo))
    print("spot 5m today:", len(k.historical_data(256265,
          datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0),
          datetime.now(IST), "5minute")))
