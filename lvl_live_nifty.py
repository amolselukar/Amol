#!/usr/bin/env python3
"""LVL LIVE — NIFTY ONLY, REAL mSTOCK ORDERS (2026-10-29).

First real-money live loop for the LVL engine. The paper engine lvl_engine.py is
UNTOUCHED and remains the signal brain + audit trail; this file is a thin LIVE
EXECUTION LAYER around it:

  signal  : lvl_engine.compute('NIFTY', day)  -> (closed_trades, open_position)
  entry   : when the engine opens a FRESH position (on the last completed 15m bar)
            and we are flat live -> BUY MARKET the ATM CE/PE, 1 trade at a time.
  exit    : when that engine trade closes (ratchet / EOD) -> SELL MARKET our qty.
  broker  : MStockBroker (lifted verbatim from ORION_PAPER_V2_5_20.py, the proven
            path; account live-tested via test_live_order.py).

SIZE: LIVE_QTY=1 (micro) for the first proving session. Full lot = 65 (NSE NIFTY
F&O lot, per 2026-10-29 broker scrip master). Flip LIVE_QTY to 65 ONLY after the
full order->fill->exit->square-off loop is confirmed on a real session.

SHARED ACCOUNT SAFETY: MA2091850 is ALSO the user's real MANUAL account. Therefore
this layer:
  * NEVER squares off by net quantity (could close the user's own lots);
  * only ever SELLs the exact qty it itself bought, on its own symbol;
  * tags every order "LVLLIVE" and tracks its own order-ids;
  * on reconcile only ALERTS about untracked positions — never touches them.

State: state_LVL_LIVE.json (keyed by entry time HH:MM, idempotent across 60s polls
and restarts). Live book: LVL_LIVE_Nifty_TradeBook.csv. Telegram -> V2520 channel.

Run:  python3 lvl_live_nifty.py test   # DRY: logs intended orders, places NONE
      python3 lvl_live_nifty.py loop    # live poll loop (cron / lvl_loop)
      python3 lvl_live_nifty.py         # single pass
"""
import sys, os, csv, json, time, logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

import credentials as _c
import lvl_engine as eng          # reuse data client, compute(), levels, tg(); import does NOT run its main()
from lvl_engine import IST

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state_LVL_LIVE.json")
BOOK  = os.path.join(HERE, "LVL_LIVE_Nifty_TradeBook.csv")

# ── CONFIG ───────────────────────────────────────────────────────────
KEY                 = "NIFTY"
LIVE_QTY            = 65           # 1 NSE NIFTY option lot. Options trade ONLY in lot
                                   # multiples — qty=1 was rejected by broker (MA200
                                   # "quantity is not in multiple of lot size"). Fixed 2026-10-30.
FULL_LOT            = 65
LIVE_ORDERS_ENABLED = True         # master arm; False = paper-live (logs intents, no orders)
EXCHANGE            = "NFO"
PRODUCT             = "INTRADAY"    # MIS same-day; engine squares off by EOD
ORDER_TYPE          = "MARKET"
ORDER_TAG           = "LVLLIVE"    # stamped on every bot order (_ordertag) so bot vs manual
                                   # orders are distinguishable in the broker log AND the bot
                                   # can identify its own orders/positions (my_orders/bot_net_qty)
EOD_HARDSTOP_HM     = 15*60 + 20   # 15:20 IST — safety: ensure our own trade is flat
FRESH_CANDLES       = 2            # only auto-enter if the engine entry is within the
                                   # last N completed 15m bars (don't chase a stale signal on restart)
MAX_SELL_ATTEMPTS   = 3            # give up auto square-off after this many broker-side failures
                                   # (then alert loudly; never loop forever on a stuck SELL)
STATUS_EVERY_SEC    = 15*60        # push a trade/status heartbeat to Telegram this often
MAX_DATA_LAG_MIN    = 4            # if the newest spot 1m bar from Upstox is older than this,
                                   # treat the feed as STALE and BLOCK new entries (don't trade
                                   # real money on delayed/frozen prices). Loud, never silent.

DRY = ("test" in sys.argv)

# ── logging ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler(os.path.join(HERE, "lvl_live_nifty.log"))])
log = logging.getLogger("lvl_live")

def tg(msg):
    try: eng.tg(msg)
    except Exception as e: log.error(f"tg err {e}")

# ── mStock SDK ───────────────────────────────────────────────────────
try:
    from tradingapi_b.mconnect import MConnectB as _SDK
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False

# ── MStockBroker (lifted verbatim from ORION_PAPER_V2_5_20.py — the proven path) ──
class MStockBroker:
    def __init__(self):
        if not _SDK_AVAILABLE:
            raise RuntimeError("mStock SDK not installed. Run: pip install mStock-TradingApi-B")
        self._api_key  = getattr(_c, 'MSTOCK_API_KEY',  '')
        self._user_id  = getattr(_c, 'MSTOCK_USER_ID',  '')
        self._password = getattr(_c, 'MSTOCK_PASSWORD', '')
        self._totp_sec = getattr(_c, 'MSTOCK_TOTP_SECRET', '')
        if not all([self._api_key, self._user_id, self._password]):
            raise RuntimeError("MSTOCK_API_KEY / MSTOCK_USER_ID / MSTOCK_PASSWORD missing in credentials.py")
        self._client = _SDK(api_key=self._api_key, debug=False, disable_ssl=True)
        self._logged_in = False
        self._sym_token_cache = {}
        self._last_error = ""
        self._bot_order_ids = set()

    @staticmethod
    def _to_dict(resp) -> dict:
        if resp is None: return {}
        if isinstance(resp, dict): return resp
        if hasattr(resp, 'json'):
            try:
                d = resp.json()
                if isinstance(d, list): d = d[0] if d else {}
                return d if isinstance(d, dict) else {}
            except Exception: pass
        if hasattr(resp, '__dict__'): return vars(resp)
        return {}

    def login(self) -> bool:
        try:
            import pyotp
            totp_code = pyotp.TOTP(self._totp_sec).now() if self._totp_sec else ""
        except Exception:
            totp_code = ""
        try:
            raw  = self._client.login(user_id=self._user_id, password=self._password)
            resp = self._to_dict(raw)
            log.info(f"[mstock] login: status={resp.get('status')} msg={resp.get('message')}")
            data = resp.get('data') or {}
            jwt_token     = data.get('jwtToken', '')
            refresh_token = data.get('refreshToken', '')
            if not (resp.get('status') in (True, 'true', 'True') and jwt_token):
                log.error(f"[mstock] Login step-1 failed: {resp}")
                return False
            self._client.set_access_token(jwt_token)
            if totp_code and refresh_token:
                raw2 = self._client.verify_totp(_api_key=self._api_key, _request_token=refresh_token, _tOtp=totp_code)
                resp2 = self._to_dict(raw2)
                log.info(f"[mstock] verify_totp: status={resp2.get('status')} msg={resp2.get('message')}")
                if resp2.get('status') not in (True, 'true', 'True'):
                    log.error(f"[mstock] verify_totp failed: {resp2}")
                    return False
                final_jwt = (resp2.get('data') or {}).get('jwtToken', '')
                if final_jwt:
                    self._client.set_access_token(final_jwt)
            else:
                log.warning(f"[mstock] Skipping verify_totp (totp={'yes' if totp_code else 'NO'}, refreshToken={'yes' if refresh_token else 'NO'})")
            self._logged_in = True
            log.info("[mstock] Login complete.")
            self._build_token_cache()
            return True
        except Exception as e:
            log.error(f"[mstock] Login failed: {e}")
            return False

    def _build_token_cache(self):
        try:
            import requests as _req
            url = "https://api.mstock.trade/openapi/typeb/instruments/OpenAPIScripMaster"
            r = _req.get(url, timeout=30); r.raise_for_status()
            rows = r.json()
            if not isinstance(rows, list): rows = rows.get('data') or []
            for row in rows:
                sym = (row.get('name') or row.get('tradingsymbol') or row.get('Trading Symbol') or row.get('TradingSymbol') or row.get('TRADING_SYMBOL') or '')
                tok = str(row.get('token') or row.get('symboltoken') or row.get('symbolToken') or row.get('Token') or row.get('ScripCode') or row.get('SCRIP_CODE') or '')
                if sym and tok: self._sym_token_cache[sym] = tok
            log.info(f"[mstock] Instrument cache: {len(self._sym_token_cache)} symbols")
        except Exception as e:
            log.warning(f"[mstock] Instrument cache failed: {e}")

    def ensure_logged_in(self):
        if not self._logged_in:
            if not self.login(): raise RuntimeError("[mstock] Login required but failed.")

    def get_symbol_token(self, trading_symbol: str, exchange: str = "NFO") -> Optional[str]:
        return self._sym_token_cache.get(trading_symbol)

    def place_order(self, transaction_type: str, trading_symbol: str, quantity: int,
                    order_type: str = "MARKET", price: float = 0.0, exchange: str = "NFO",
                    product: str = "INTRADAY", symbol_token: str = "", tag: str = "LVLLIVE") -> Optional[str]:
        self.ensure_logged_in()
        if not symbol_token:
            symbol_token = self.get_symbol_token(trading_symbol, exchange) or ""
            if not symbol_token:
                log.warning(f"[mstock] Could not resolve token for {trading_symbol}.")
        try:
            resp = self._to_dict(self._client.place_order(
                _variety="NORMAL", _tradingsymbol=trading_symbol, _symboltoken=symbol_token,
                _exchange=exchange, _transactiontype=transaction_type, _ordertype=order_type,
                _quantity=str(quantity), _producttype=product,
                _price=str(price) if order_type == "LIMIT" else "0",
                _triggerprice="0", _squareoff="0", _stoploss="0", _trailingStopLoss="",
                _disclosedquantity="0", _duration="DAY", _ordertag=tag
            ))
            log.info(f"[mstock] place_order resp: {resp}")
            errorcode  = str(resp.get('errorcode', '') or '')
            status_str = str(resp.get('status', '')).lower()
            msg_str    = str(resp.get('message', '')).lower()
            if errorcode == 'IA403' or 'ip address' in msg_str:
                if getattr(self, '_ia403_relogin_attempted', False):
                    self._last_error = f"IA403: {resp.get('message','')} (persists after re-login)"
                    self._ia403_relogin_attempted = False
                    return None
                log.warning(f"[mstock] IA403 — rebuilding client + fresh TOTP re-login.")
                self._ia403_relogin_attempted = True
                self._client = _SDK(api_key=self._api_key, debug=False, disable_ssl=True)
                self._logged_in = False
                time.sleep(2)
                if self.login():
                    time.sleep(1)
                    result = self.place_order(transaction_type, trading_symbol, quantity,
                                              order_type, price, exchange, product, symbol_token, tag)
                    self._ia403_relogin_attempted = False
                    return result
                self._last_error = f"IA403 + re-login failed: {resp.get('message','')}"
                self._ia403_relogin_attempted = False
                return None
            jwt_expired = any(k in msg_str for k in ('unauthori', 'invalid token', 'session expired', 'not logged', 'token expired'))
            if jwt_expired:
                log.warning(f"[mstock] JWT expired in place_order — re-logging in.")
                self._logged_in = False
                if self.login():
                    return self.place_order(transaction_type, trading_symbol, quantity,
                                            order_type, price, exchange, product, symbol_token, tag)
                self._last_error = f"JWT expiry + re-login failed: {resp.get('message','')}"
                return None
            order_id = ((resp.get('data') or {}).get('orderid') or resp.get('orderid') or resp.get('order_id'))
            if order_id:
                log.info(f"[mstock] {transaction_type} placed: {trading_symbol} qty={quantity} type={order_type} tag={tag} → orderid={order_id}")
                self._last_error = ""
                self._bot_order_ids.add(str(order_id))
                return str(order_id)
            err_msg = resp.get('message') or resp.get('errMsg') or resp.get('error') or str(resp)
            log.error(f"[mstock] No orderid in response: {resp}")
            self._last_error = f"{err_msg}"
            return None
        except Exception as e:
            log.error(f"[mstock] place_order exception: {e}")
            self._last_error = str(e)
            return None

    def order_status(self, order_id: str) -> Tuple[str, float]:
        self.ensure_logged_in()
        try:
            raw = self._client.get_order_book()
            if hasattr(raw, 'json'): parsed = raw.json()
            elif isinstance(raw, dict): parsed = raw
            else: parsed = {}
            orders = parsed if isinstance(parsed, list) else (parsed.get('data') or [])
            if not isinstance(orders, list): orders = []
            for o in orders:
                oid = str(o.get('orderid') or o.get('order_id') or o.get('orderId') or o.get('uniqueorderid') or '')
                if oid == str(order_id):
                    raw_status = str(o.get('status') or o.get('orderstatus') or 'UNKNOWN')
                    if raw_status.lower() in ('traded', 'complete', 'trade confirmed'): status = 'COMPLETE'
                    elif raw_status.lower() in ('rejected', 'cancelled', 'canceled'): status = raw_status.upper()
                    else: status = raw_status.upper()
                    fill = float(o.get('averageprice') or o.get('averagePrice') or o.get('fillprice') or 0)
                    return status, fill
        except Exception as e:
            log.error(f"[mstock] order_status {order_id}: {e}")
        return "UNKNOWN", 0.0

    def wait_for_fill(self, order_id: str, timeout_sec: int = 10, poll_sec: float = 0.5) -> Tuple[str, float]:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            status, fill = self.order_status(order_id)
            if status in ("COMPLETE", "REJECTED", "CANCELLED"): return status, fill
            time.sleep(poll_sec)
        log.warning(f"[mstock] wait_for_fill timeout — order {order_id} not confirmed.")
        return "TIMEOUT", 0.0

    def positions(self) -> list:
        self.ensure_logged_in()
        try:
            raw = self._client.get_net_position()
            resp = self._to_dict(raw) if raw is not None else {}
            return resp.get('data') or []
        except Exception as e:
            log.error(f"[mstock] positions(): {e}")
            return []

    def net_qty(self, trading_symbol: str) -> int:
        """Whole-account net qty for a symbol (bot + any manual lots) — reflects what is
        ACTUALLY held, so it's the right number for short-safety / manual-exit checks.

        Hardened 2026-11-02: the old version matched ONE exact symbol string and ONE qty
        key; if mStock's net-position feed returned either in a different format it silently
        returned 0 → bot thought it was FLAT on a live lot → missed its own exit (the
        2026-11-02 12:30 PE booked nothing). Now matches the symbol case-insensitively over
        several key variants, derives qty from a net field OR buy−sell, and logs the raw
        payload ONCE when nothing matches so the real format is captured for certain."""
        want = str(trading_symbol or '').upper()
        rows = self.positions()
        # GROUND-TRUTH DUMP (once/session): capture the REAL get_net_position row format
        # — exact key names + symbol string — so net_qty matches reality instead of guessing.
        if rows and not getattr(self, '_posdump_logged', False):
            self._posdump_logged = True
            log.info(f"[net_qty RAWDUMP once] get_net_position rows[:3] = {rows[:3]}")
        # GROUND TRUTH (captured 2026-11-02 from the live feed): mStock's net-position rows
        # carry an EMPTY 'tradingsymbol' and a differently-formatted 'symbolname'
        # ('NIFTY-03Nov2026-23300-PE') — NOT the order symbol ('NIFTY26N0323300PE'). A plain
        # string compare therefore NEVER matched → net_qty returned 0 → bot thought it was
        # flat on a live lot and skipped its own exit. We now match STRUCTURALLY: same
        # underlying + option type (CE/PE) + strike (the order symbol literally contains the
        # strike and ends with CE/PE). Qty comes from 'netqty' (present as a string).
        import re as _re
        _m = _re.match(r'^([A-Z]+)', want)
        und  = _m.group(1) if _m else want                        # e.g. NIFTY
        otyp = want[-2:] if want[-2:] in ('CE', 'PE') else ''     # CE / PE
        for p in rows:
            symname  = str(p.get('symbolname') or p.get('tradingsymbol')
                           or p.get('symbol') or '').upper()
            row_otyp = str(p.get('optiontype') or '').upper()
            row_strk = str(p.get('strikeprice') or '').strip()
            try: row_strk = str(int(float(row_strk)))
            except Exception: pass
            matched = (bool(symname) and symname.startswith(und) and otyp and row_otyp == otyp
                       and row_strk and row_strk in want)          # structured (net-position feed)
            if not matched and symname and symname == want:        # exact fallback (any feed that uses order symbol)
                matched = True
            if not matched:
                continue
            for k in ('netqty', 'net_qty', 'netQuantity', 'net_quantity',
                      'netquantity', 'netQty', 'netqtylot'):
                v = p.get(k)
                if v not in (None, ''):
                    try:
                        return int(float(v))
                    except Exception:
                        pass
            bq = p.get('buyqty') or p.get('buyquantity') or p.get('buyQty') or p.get('buy_quantity') or 0
            sq = p.get('sellqty') or p.get('sellquantity') or p.get('sellQty') or p.get('sell_quantity') or 0
            try:
                return int(float(bq)) - int(float(sq))
            except Exception:
                return 0
        if rows and not getattr(self, '_posfmt_logged', False):
            self._posfmt_logged = True
            log.warning(f"[net_qty] no row matched {trading_symbol!r} (und={und} otyp={otyp}) — sample: {rows[:2]}")
        return 0

    def realized_exit(self, trading_symbol: str) -> Optional[dict]:
        """Realized exit for a now-FLAT symbol straight from the net-position feed — the
        authoritative source for a MANUAL exit on the shared account. The feed row carries
        'sellavgprice'/'buyavgprice'/'netqty'/'netvalue' even once netqty is 0 (captured
        2026-11-03: sellavgprice=268.6 after a manual square-off). Matches STRUCTURALLY
        (underlying+CE/PE+strike) like net_qty(), because the row's 'tradingsymbol' is empty
        and 'symbolname' is differently formatted. Returns dict(sell_avg, buy_avg, netqty,
        netvalue) or None if no closed row with a sell price is found."""
        import re as _re
        want = str(trading_symbol or '').upper()
        _m = _re.match(r'^([A-Z]+)', want); und = _m.group(1) if _m else want
        otyp = want[-2:] if want[-2:] in ('CE', 'PE') else ''
        for p in self.positions():
            symname = str(p.get('symbolname') or p.get('tradingsymbol') or p.get('symbol') or '').upper()
            row_otyp = str(p.get('optiontype') or '').upper()
            row_strk = str(p.get('strikeprice') or '').strip()
            try: row_strk = str(int(float(row_strk)))
            except Exception: pass
            matched = (bool(symname) and symname.startswith(und) and otyp and row_otyp == otyp
                       and row_strk and row_strk in want) or (symname and symname == want)
            if not matched:
                continue
            def _f(*keys):
                for k in keys:
                    v = p.get(k)
                    if v not in (None, ''):
                        try: return float(v)
                        except Exception: pass
                return None
            sell_avg = _f('sellavgprice', 'sellavg', 'sell_avg_price')
            if sell_avg is None or sell_avg <= 0:
                continue
            return dict(sell_avg=sell_avg, buy_avg=_f('buyavgprice', 'buyavg'),
                        netqty=_f('netqty', 'net_qty') or 0, netvalue=_f('netvalue'))
        return None

    def last_sell_fill(self, trading_symbol: str) -> Optional[float]:
        """Average fill price of the most recent COMPLETE SELL for this symbol in today's
        order book — used to book REALISTIC pnl when the user squared the bot's long off
        MANUALLY (that SELL carries no bot tag, so my_orders() won't see it). The order book
        uses the full trading symbol (unlike the net-position feed), so match on it directly.
        Returns None if no completed sell is found."""
        self.ensure_logged_in()
        want = str(trading_symbol or '').upper()
        best_price = None; best_key = None
        try:
            raw = self._client.get_order_book()
            parsed = raw.json() if hasattr(raw, 'json') else (raw if isinstance(raw, (list, dict)) else {})
            rows = parsed if isinstance(parsed, list) else (parsed.get('data') or [])
            for o in (rows if isinstance(rows, list) else []):
                sym = str(o.get('tradingsymbol') or o.get('trading_symbol') or o.get('symbol')
                          or o.get('symbolname') or '').upper()
                if sym != want:
                    continue
                txn = str(o.get('transactiontype') or o.get('transaction_type')
                          or o.get('transactionType') or o.get('buyorsell') or '').upper()
                if 'SELL' not in txn and txn not in ('S', 'SL'):
                    continue
                status = str(o.get('status') or o.get('orderstatus') or '').lower()
                if status not in ('traded', 'complete', 'trade confirmed'):
                    continue
                price = float(o.get('averageprice') or o.get('averagePrice') or o.get('fillprice') or 0)
                if price <= 0:
                    continue
                tkey = str(o.get('updatetime') or o.get('orderupdatetime') or o.get('ordertime')
                           or o.get('exchtime') or o.get('order_timestamp') or '')
                if best_price is None or tkey >= (best_key or ''):   # keep the latest sell
                    best_price = price; best_key = tkey
        except Exception as e:
            log.error(f"[mstock] last_sell_fill({trading_symbol}): {e}")
        return best_price

    def my_orders(self) -> list:
        """Order-book rows placed by THIS bot, identified by our order-tag OR a tracked
        order-id. This is how the bot tells its own orders apart from the user's manual
        trades on the shared account (and in the broker's order log)."""
        self.ensure_logged_in()
        out = []
        try:
            raw = self._client.get_order_book()
            parsed = raw.json() if hasattr(raw, 'json') else (raw if isinstance(raw, (list, dict)) else {})
            rows = parsed if isinstance(parsed, list) else (parsed.get('data') or [])
            for o in (rows if isinstance(rows, list) else []):
                tag = str(o.get('ordertag') or o.get('tag') or o.get('orderTag')
                          or o.get('ordertagname') or '')
                oid = str(o.get('orderid') or o.get('order_id') or o.get('orderId')
                          or o.get('uniqueorderid') or '')
                if tag == ORDER_TAG or (oid and oid in self._bot_order_ids):
                    out.append(o)
        except Exception as e:
            log.error(f"[mstock] my_orders(): {e}")
        return out

    def bot_net_qty(self, trading_symbol: str) -> int:
        """Net qty for a symbol from the BOT'S OWN tagged/tracked COMPLETE orders only
        (filled BUY − filled SELL) = what the bot itself put on. Compare against
        net_qty() (whole account) to detect manual exits of the bot's position."""
        net = 0
        for o in self.my_orders():
            sym = o.get('tradingsymbol') or o.get('trading_symbol', '')
            if sym != trading_symbol:
                continue
            status = str(o.get('status') or o.get('orderstatus') or '').lower()
            if status not in ('complete', 'traded', 'trade confirmed'):
                continue
            q = int(float(o.get('filledquantity') or o.get('filledQty')
                          or o.get('filledshares') or o.get('quantity') or 0))
            tt = str(o.get('transactiontype') or o.get('transaction_type')
                     or o.get('trantype') or '').upper()
            net += q if tt.startswith('B') else -q
        return net

# ── signal-side symbol map (front weekly, SAME expiry the engine prices) ──
_SYMMAP = {}
def sym_map(day):
    if day in _SYMMAP: return _SYMMAP[day]
    inst = eng.instruments_cached(eng.INSTR[KEY]['exch'])
    opts = [r for r in inst if r.get('name') == eng.INSTR[KEY]['name'] and r.get('instrument_type') in ('CE', 'PE')]
    exps = sorted({str(r['expiry'])[:10] for r in opts})
    fe = next((e for e in exps if e > day), exps[-1] if exps else None)
    m = {(int(float(r['strike'])), r['instrument_type']): r['tradingsymbol'] for r in opts if str(r['expiry'])[:10] == fe}
    _SYMMAP[day] = (fe, m); return _SYMMAP[day]

def resolve_symbol(strike, side, day):
    fe, m = sym_map(day)
    return m.get((int(strike), side)), fe

# ── state ────────────────────────────────────────────────────────────
def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}
def save_state(s):
    if not DRY: json.dump(s, open(STATE, "w"), indent=2)

def book_row(row):
    cols = ["day","entry","exit","side","strike","symbol","qty","buy_order_id","buy_fill",
            "sell_order_id","sell_fill","pnl","status"]
    exists = os.path.exists(BOOK)
    if DRY: return
    with open(BOOK, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if not exists: w.writeheader()
        w.writerow({k: row.get(k, "") for k in cols})

# ── 15m candle freshness (don't chase a stale signal on restart) ──────
def recent_entry_times(now):
    """Start-times (HH:MM) of the last FRESH_CANDLES completed 15m bars."""
    start = 9*60 + 15; mins = now.hour*60 + now.minute
    done = (mins - start)//15                   # completed candles so far
    out = []
    for i in range(done-1, max(done-1-FRESH_CANDLES, -1), -1):
        if i < 0: break
        m = start + i*15
        out.append(f"{m//60:02d}:{m%60:02d}")
    return set(out)

# ── data freshness (Upstox delay/freeze protection) ──────────────────
_DATA_STALE = False
def data_lag_min(now):
    """(lag_minutes, last_bar_dt) for the spot 1-minute feed, or (None, None) if no bars.
    The engine trades off Upstox candles; if that feed is delayed or frozen we must NOT
    open new real-money trades on prices that no longer reflect the market."""
    try:
        tok = eng.INSTR[KEY]['spot']
        d0  = now.replace(hour=9, minute=15, second=0, microsecond=0)
        bars = eng.fetch(tok, d0, now, "minute")
        if not bars:
            return None, None
        last = max(b['date'] for b in bars)
        if getattr(last, 'tzinfo', None) is None:
            last = last.replace(tzinfo=IST)
        return (now - last).total_seconds() / 60.0, last
    except Exception as e:
        log.warning(f"data_lag_min err {e}")
        return None, None

def check_freshness(now):
    """Return (stale: bool, lag_min, last_bar). Alerts on transition into/out of STALE."""
    global _DATA_STALE
    lag, last = data_lag_min(now)
    stale = (lag is None) or (lag > MAX_DATA_LAG_MIN)
    lag_s  = "n/a" if lag is None else f"{lag:.1f}m"
    last_s = "none" if last is None else f"{last:%H:%M}"
    if stale and not _DATA_STALE:
        _DATA_STALE = True
        tg(f"⚠️ <b>LVL-LIVE</b> Upstox data STALE (lag {lag_s}, last bar {last_s}) — "
           f"BLOCKING new entries until the feed is fresh again.")
        log.warning(f"[stale] feed stale lag={lag_s} last={last_s}")
    elif (not stale) and _DATA_STALE:
        _DATA_STALE = False
        tg(f"✅ <b>LVL-LIVE</b> Upstox data fresh again (lag {lag_s}) — entries re-enabled.")
        log.info(f"[stale] feed recovered lag={lag_s}")
    return stale, lag, last

# ── status heartbeat ─────────────────────────────────────────────────
_LAST_SNAP = {}
def status_text():
    s = _LAST_SNAP
    if not s:
        return "📊 <b>LVL-LIVE</b> status — warming up (no pass yet)"
    h = s.get("holding")
    if h:
        up = f" | uPnL Rs{h['upnl']:+.0f}" if h.get("upnl") is not None else ""
        ltp = f" | ltp {h['ltp']}" if h.get("ltp") is not None else ""
        warn = " ⚠️STUCK(manual action needed)" if h.get("blocked") else ""
        body = (f"HOLDING {h['sym']} x{h['qty']} @ {h['buy_fill']}{ltp}{up}{warn}")
    else:
        body = f"FLAT (engine signal: {'OPEN' if s.get('engine_open') else 'none'})"
    datastat = ""
    if s.get("stale"):
        datastat = f" | ⚠️DATA STALE (lag {s.get('lag')}m) entries blocked"
    return (f"📊 <b>LVL-LIVE</b> {s.get('hm')} | {body} | "
            f"today: {s.get('closed',0)} closed, {s.get('live_open',0)} live-open{datastat}")

# ── broker handle ────────────────────────────────────────────────────
_BROKER = None
def broker():
    global _BROKER
    if _BROKER is None and not DRY and LIVE_ORDERS_ENABLED:
        b = MStockBroker()
        if not b.login():
            tg("🚨 <b>LVL-LIVE</b> mStock login FAILED — live orders disabled this run.")
            raise RuntimeError("mStock login failed")
        _BROKER = b
    return _BROKER

def do_buy(entry, side, strike, day, tgt=None, stop=None, level=None):
    # tgt/stop/level are the engine's mapped target rung, current ratchet stop,
    # and broken level name — included in the entry TG so target+SL show at BUY
    # time (same values the exit-watch flash prints later). Messaging only.
    tl = f" | 🎯 target {tgt if tgt is not None else '—'} | 🛑 SL {stop if stop is not None else '—'}" \
         + (f" ({level})" if level else "")
    sym, fe = resolve_symbol(strike, side, day)
    if not sym:
        tg(f"⚠️ <b>LVL-LIVE</b> no symbol for {side} {strike} (exp {fe}) — entry {entry} SKIPPED")
        return dict(symbol=None, missed=True)
    if DRY or not LIVE_ORDERS_ENABLED:
        log.info(f"[DRY] BUY {sym} qty={LIVE_QTY} MARKET ({entry})")
        tg(f"🧪 <b>LVL-LIVE (paper)</b> would BUY {sym} x{LIVE_QTY} @MKT | entry {entry}{tl}")
        return dict(symbol=sym, qty=LIVE_QTY, buy_order_id="DRY", buy_fill=0.0, buy_status="DRY")
    b = broker()
    oid = b.place_order("BUY", sym, LIVE_QTY, order_type=ORDER_TYPE, exchange=EXCHANGE,
                        product=PRODUCT, tag=ORDER_TAG)
    if not oid:
        tg(f"🚨 <b>LVL-LIVE</b> BUY FAILED {sym} x{LIVE_QTY}: {b._last_error}")
        return dict(symbol=sym, missed=True)
    status, fill = b.wait_for_fill(oid, timeout_sec=12)
    ok = b.net_qty(sym) >= LIVE_QTY
    tg(f"🟢 <b>LVL-LIVE</b> BUY {sym} x{LIVE_QTY} @ {fill} [{status}{'/pos✓' if ok else '/pos?'}] | entry {entry}{tl}")
    # pos_confirmed: whether the position feed has already caught up with this fill.
    # If not yet (feed lag), the manual-exit sweep will confirm it on a later poll before
    # it is ever eligible to be read as a manual exit.
    return dict(symbol=sym, qty=LIVE_QTY, buy_order_id=oid, buy_fill=fill, buy_status=status,
                pos_confirmed=bool(ok))

def do_sell(rec, entry, reason, day):
    sym = rec.get("symbol")
    if DRY or not LIVE_ORDERS_ENABLED or rec.get("buy_order_id") in ("DRY", None):
        log.info(f"[DRY] SELL {sym} qty={rec.get('qty', LIVE_QTY)} MARKET ({reason})")
        tg(f"🧪 <b>LVL-LIVE (paper)</b> would SELL {sym} x{rec.get('qty', LIVE_QTY)} @MKT [{reason}]")
        rec.update(sell_order_id="DRY", sell_fill=0.0, sell_status="DRY")
        return rec
    b = broker()
    qty = int(rec.get("qty", LIVE_QTY))

    # --- MANUAL-EXIT / ALREADY-FLAT GUARD ---------------------------------
    # The account is shared with the user's manual trades. Before selling, confirm
    # the broker still actually holds the long we bought. If it's gone (user squared
    # it off manually, or it was already sold), DO NOT place another SELL — that would
    # either fail forever or open an unwanted SHORT. Mark it closed-externally and stop.
    held = b.net_qty(sym)
    if held <= 0:
        # already flat (user squared it off manually) — do NOT re-sell; book REALISTIC pnl
        # at the actual manual fill. book_manual_exit also writes the book row for us.
        return book_manual_exit(rec, entry, reason, day)
    sell_qty = min(qty, held)           # partial manual exit -> only sell what's really there
    if sell_qty < qty:
        tg(f"⚠️ <b>LVL-LIVE</b> {sym} broker holds {held} < our {qty} (partial manual exit?) — selling {sell_qty} only")

    oid = b.place_order("SELL", sym, sell_qty, order_type=ORDER_TYPE, exchange=EXCHANGE,
                        product=PRODUCT, tag=ORDER_TAG)
    if not oid:
        attempts = int(rec.get("sell_attempts", 0)) + 1
        rec["sell_attempts"] = attempts
        if attempts >= MAX_SELL_ATTEMPTS:
            rec.update(sell_status="FAILED_GAVEUP", sell_blocked=True)
            tg(f"🚨 <b>LVL-LIVE</b> SELL {sym} x{sell_qty} FAILED {attempts}x ({b._last_error}) — "
               f"GIVING UP auto square-off. ⚠️ MANUAL ACTION NEEDED, position may be OPEN.")
        else:
            rec.update(sell_status="FAILED")
            tg(f"🚨 <b>LVL-LIVE</b> SELL FAILED {sym} x{sell_qty} (try {attempts}/{MAX_SELL_ATTEMPTS}): "
               f"{b._last_error} — will retry next poll")
        return rec
    status, fill = b.wait_for_fill(oid, timeout_sec=12)
    pnl = round((fill - float(rec.get("buy_fill") or 0)) * sell_qty, 1) if fill else None
    rec.update(sell_order_id=oid, sell_fill=fill, sell_status=status, qty=sell_qty)
    em = "✅" if (pnl or 0) >= 0 else "🔴"
    tg(f"{em} <b>LVL-LIVE</b> SELL {sym} x{sell_qty} @ {fill} [{reason}] | pnl Rs{pnl:+.0f}" if pnl is not None
       else f"<b>LVL-LIVE</b> SELL {sym} x{sell_qty} @ {fill} [{reason}]")
    return rec

def book_manual_exit(rec, entry, reason, day):
    """User squared the bot's long off manually (shared account). Book REALISTIC pnl at the
    ACTUAL manual exit fill read from the broker order book; fall back to the last-seen option
    ltp (approx) and finally to unknown. Marks the trade closed-externally, sends ONE TG, and
    writes the live book row. (This is the realistic-pnl counterpart to the paper engine, which
    always books at the fired signal's exit price — user-directed 11-03.)"""
    sym = rec.get("symbol")
    exit_fill = None; approx = False
    # 1) authoritative: realized sell avg from the net-position feed (carries sellavgprice
    #    even once netqty hits 0 after a manual square-off).
    try:
        rz = broker().realized_exit(sym)
        if rz and rz.get("sell_avg"):
            exit_fill = rz["sell_avg"]
    except Exception as ex:
        log.warning(f"[manual-exit] realized_exit err {ex}")
    # 2) fallback: most recent completed SELL in today's order book.
    if exit_fill is None:
        try:
            exit_fill = broker().last_sell_fill(sym)
        except Exception as ex:
            log.warning(f"[manual-exit] last_sell_fill err {ex}")
    # 3) last resort: last-seen option ltp (approx).
    if exit_fill is None and rec.get("last_ltp"):
        exit_fill = float(rec["last_ltp"]); approx = True
    buyf = float(rec.get("buy_fill") or 0)
    q = int(rec.get("qty", LIVE_QTY))
    pnl = round((exit_fill - buyf) * q, 1) if (exit_fill and buyf) else None
    rec.update(sell_order_id="MANUAL", sell_status="MANUAL_EXIT",
               sell_fill=(round(exit_fill, 1) if exit_fill is not None else None),
               pnl=pnl, manual_exit=True, exit_approx=approx, exit=rec.get("exit") or "manual")
    src = " (approx=last ltp)" if approx else (" (broker fill)" if exit_fill is not None else "")
    if pnl is not None:
        em = "✅" if pnl >= 0 else "🔴"
        tg(f"🙋 <b>LVL-LIVE</b> {sym} (entry {entry}) MANUAL exit — booked REALISTIC pnl at your "
           f"exit {rec['sell_fill']}{src}: Rs{pnl:+.0f} {em}. Bot stops managing; ready for next signal. [{reason}]")
    else:
        tg(f"🙋 <b>LVL-LIVE</b> {sym} (entry {entry}) FLAT at broker — MANUAL exit, exit price "
           f"unreadable → pnl unknown. Bot stops managing; ready for next signal. [{reason}]")
    book_row(dict(day=day, entry=entry, exit=rec.get("exit"), side=rec.get("side"), strike=rec.get("strike"),
                  symbol=sym, qty=q, buy_order_id=rec.get("buy_order_id"), buy_fill=rec.get("buy_fill"),
                  sell_order_id="MANUAL", sell_fill=rec.get("sell_fill"), pnl=pnl, status="MANUAL_EXIT"))
    log.info(f"[manual-exit] {sym} entry {entry} exit_fill={exit_fill} approx={approx} pnl={pnl}")
    return rec

# ── one pass ─────────────────────────────────────────────────────────
def run_once():
    now = datetime.now(IST); day = now.strftime("%Y-%m-%d")
    st = load_state()
    if st.get("date") != day:
        # new day: any still-open trade from a prior day should already be EOD-closed;
        # start a clean per-day ledger. (We never carry live option positions overnight.)
        st = {"date": day, "trades": {}}
    trades = st.setdefault("trades", {})

    closed, openp = eng.compute(KEY, day)
    fresh = recent_entry_times(now)
    stale, lag, _lastbar = check_freshness(now)   # Upstox delay/freeze guard

    # 0) MANUAL-EXIT SWEEP — before anything else, if a trade we think we hold is
    #    already flat at the broker (user squared it off manually), understand it NOW:
    #    mark it closed-externally so we neither try to re-sell it (no stuck loop) nor
    #    keep it blocking the next signal.
    if not DRY and LIVE_ORDERS_ENABLED:
        for e, rec in trades.items():
            if rec.get("buy_order_id") and rec.get("buy_order_id") != "DRY" \
               and not rec.get("sell_order_id") and not rec.get("missed") \
               and not rec.get("sell_blocked"):
                try:
                    held = broker().net_qty(rec.get("symbol"))
                except Exception as ex:
                    log.warning(f"[manual-sweep] net_qty err {ex}"); continue
                want = int(rec.get("qty", LIVE_QTY))
                # FEED-LAG GUARD: the broker's net-position endpoint lags a just-placed
                # MARKET fill by a poll or two. Only treat "flat" as a manual exit AFTER
                # we have positively seen the position on the account at least once. A
                # fresh buy whose position feed hasn't caught up is "not yet confirmed" —
                # never swept. (Without this, the sweep fired ~60s after the buy, read 0,
                # falsely flagged MANUAL_EXIT, and the bot then wrongly reported FLAT while
                # it was really holding — 2026-11-02 09:17 buy, 09:18 false manual-exit.)
                if not rec.get("pos_confirmed"):
                    if held >= want:
                        rec["pos_confirmed"] = True
                    else:
                        log.info(f"[manual-sweep] {rec.get('symbol')} entry {e} not yet "
                                 f"confirmed at broker (held={held}/{want}) — feed catching up, no action")
                    continue
                if held <= 0:
                    trades[e] = book_manual_exit(rec, e, "manual-sweep", day)

    # 1) EXITS first — any engine-closed trade we hold live but haven't sold.
    for t in closed:
        e = t['entry']; rec = trades.get(e)
        if rec and not rec.get("missed") and rec.get("buy_order_id") \
           and not rec.get("sell_order_id") and not rec.get("sell_blocked"):
            rec = do_sell(rec, e, t.get('reason', 'exit'), day)
            trades[e] = rec
            if not rec.get("manual_exit"):   # manual exit already booked+rowed by book_manual_exit
                rec["exit"] = t['exit']
                rec["pnl"] = round((float(rec.get('sell_fill') or 0) - float(rec.get('buy_fill') or 0)) * int(rec.get('qty', LIVE_QTY)), 1)
                book_row(dict(day=day, entry=e, exit=t['exit'], side=rec.get('side'), strike=rec.get('strike'),
                              symbol=rec.get('symbol'), qty=rec.get('qty'), buy_order_id=rec.get('buy_order_id'),
                              buy_fill=rec.get('buy_fill'), sell_order_id=rec.get('sell_order_id'),
                              sell_fill=rec.get('sell_fill'), pnl=rec.get('pnl'), status=rec.get('sell_status')))
        elif not rec:
            # engine opened AND closed between our polls — we never held it. Log, do NOT trade.
            trades[e] = dict(missed=True, reason="not-held (opened+closed between polls)",
                             side=t['side'], strike=t['strike'], entry=e, exit=t['exit'])
            log.info(f"[miss] engine trade {e}->{t['exit']} not held live")
            tg(f"⏭️ <b>LVL-LIVE</b> engine {t['side']}{t['strike']} {e}→{t['exit']} opened+closed "
               f"between polls — not held live, no order")

    # 2) ENTRY — fresh open position, flat live, not already recorded.
    live_open = any(r.get("buy_order_id") and not r.get("sell_order_id") and not r.get("missed")
                    for r in trades.values())
    if openp and not live_open:
        e = openp['entry']
        if stale:
            log.info(f"[stale-block] entry {e} suppressed — Upstox data stale (lag {lag})")
            # do not record as missed; re-evaluate next poll once the feed recovers
        elif e in trades:
            pass  # already handled (bought or missed)
        else:
            # 10-30: FRESH_CANDLES "don't chase stale entry" guard REMOVED (user-directed).
            # It was a live-only filter NOT in the tested backtest and blocked every signal.
            # Live now executes the tested engine 1:1 (only the data-feed stale check above gates entry).
            rec = do_buy(e, openp['side'], openp['strike'], day,
                         tgt=openp.get('target'), stop=openp.get('stop'), level=openp.get('level'))
            rec.update(side=openp['side'], strike=openp['strike'], entry=e)
            trades[e] = rec

    # 2.5) EXIT-LEVEL WATCH — while we hold a live position, flash the engine's current
    #      ratchet STOP (the 15m-close level that triggers the exit) + mapped target, so the
    #      user can square off MANUALLY if the bot ever fails to book. Throttled: only re-send
    #      when the ratchet stop actually moves (or first sight) — never every 60s poll.
    if openp:
        e = openp['entry']; rec = trades.get(e)
        if rec and rec.get("buy_order_id") and rec.get("buy_order_id") != "DRY" \
           and not rec.get("sell_order_id") and not rec.get("missed"):
            stop = openp.get('stop'); tgt = openp.get('target')
            if stop != rec.get("last_flashed_stop"):
                rec["last_flashed_stop"] = stop; trades[e] = rec
                tg(f"🎯 <b>LVL-LIVE exit-watch</b> {openp['side']}{openp['strike']} (entry {e})\n"
                   f"🛑 SL / exit level: 15m spot close back through <b>{stop}</b> ({openp.get('level')})\n"
                   f"🎯 target: {tgt if tgt is not None else '—'}\n"
                   f"entry spot {openp.get('espot')} | opt ltp now {openp.get('ltp')}\n"
                   f"⚠️ if the bot does not book at SL {stop}, square off MANUALLY.")

    # 3) EOD hard safety — ensure our OWN still-open trade is flat (sell exact qty, never net).
    hm = now.hour*60 + now.minute
    if hm >= EOD_HARDSTOP_HM:
        for e, rec in trades.items():
            if rec.get("buy_order_id") and rec.get("buy_order_id") != "DRY" \
               and not rec.get("sell_order_id") and not rec.get("missed") \
               and not rec.get("sell_blocked"):
                tg(f"🛑 <b>LVL-LIVE</b> EOD safety square-off {rec.get('symbol')} (entry {e})")
                rec = do_sell(rec, e, "eod-safety", day); trades[e] = rec

    st["trades"] = trades; save_state(st)
    opencnt = sum(1 for r in trades.values() if r.get("buy_order_id") and r.get("buy_order_id") != "DRY"
                  and not r.get("sell_order_id") and not r.get("missed"))
    log.info(f"[LVL-LIVE {day}] engine closed={len(closed)} open={'yes' if openp else 'no'} | live-open={opencnt} qty={LIVE_QTY}")

    # status snapshot for the 15-min Telegram heartbeat (read by loop())
    _snap = dict(day=day, hm=f"{now:%H:%M}", engine_open=bool(openp),
                 closed=len(closed), live_open=opencnt, holding=None,
                 stale=stale, lag=(None if lag is None else round(lag, 1)))
    for e, rec in trades.items():
        if rec.get("buy_order_id") and rec.get("buy_order_id") not in ("DRY", None) \
           and not rec.get("sell_order_id") and not rec.get("missed"):
            bf = float(rec.get("buy_fill") or 0)
            ltp = float(openp["ltp"]) if (openp and openp.get("entry") == e) else None
            if ltp is not None:
                rec["last_ltp"] = ltp   # fallback price if a later MANUAL exit can't be read from the order book
            up = round((ltp - bf) * int(rec.get("qty", LIVE_QTY)), 0) if (ltp is not None and bf) else None
            _snap["holding"] = dict(sym=rec.get("symbol"), qty=rec.get("qty", LIVE_QTY),
                                    entry=e, buy_fill=bf, ltp=ltp, upnl=up,
                                    blocked=bool(rec.get("sell_blocked")))
            break
    global _LAST_SNAP; _LAST_SNAP = _snap

def reconcile_boot():
    """Once at startup: identify which held NIFTY-option positions are the bot's own
    (by our order TAG) vs the user's manual trades, and ALERT (never close) accordingly.
    Tag-based identity means a lost local state doesn't make us disown our own position."""
    if DRY or not LIVE_ORDERS_ENABLED: return
    try:
        b = broker()
        held = {}
        for p in b.positions():
            sym = p.get('tradingsymbol') or p.get('trading_symbol', '')
            q = int(p.get('netqty') or p.get('net_qty') or 0)
            if q != 0 and ('CE' in sym or 'PE' in sym) and sym.startswith('NIFTY'):
                held[sym] = q
        st = load_state()
        by_state = {r.get('symbol') for r in st.get('trades', {}).values()
                    if r.get('symbol') and r.get('buy_order_id') not in ("DRY", None)
                    and not r.get('sell_order_id')}
        tagged = {o.get('tradingsymbol') or o.get('trading_symbol', '') for o in b.my_orders()}
        mine_tracked = {s for s in held if s in by_state}
        mine_orphan  = {s for s in held if s not in by_state and s in tagged}   # ours by tag, no state
        manual       = {s for s in held if s not in by_state and s not in tagged}
        if mine_tracked:
            tg(f"🤖 <b>LVL-LIVE</b> boot: resuming management of my own tracked NIFTY position(s): "
               f"{ {s: held[s] for s in mine_tracked} }")
        if mine_orphan:
            tg(f"⚠️ <b>LVL-LIVE</b> boot: NIFTY position(s) tagged '{ORDER_TAG}' (MINE) but state lost: "
               f"{ {s: held[s] for s in mine_orphan} } — left untouched, square off manually if needed")
        if manual:
            tg(f"ℹ️ <b>LVL-LIVE</b> boot: NIFTY option position(s) NOT mine (manual, untagged), "
               f"left untouched: { {s: held[s] for s in manual} }")
    except Exception as e:
        log.warning(f"reconcile_boot: {e}")

def loop():
    log.info(f"[LVL-LIVE] loop start {datetime.now(IST)} | qty={LIVE_QTY} armed={LIVE_ORDERS_ENABLED} dry={DRY}")
    tg(f"🚀 <b>LVL-LIVE NIFTY</b> armed — qty={LIVE_QTY} (full lot {FULL_LOT}), orders={'ON' if LIVE_ORDERS_ENABLED else 'PAPER'}{' [DRY]' if DRY else ''}")
    reconcile_boot()
    last_status = 0.0
    while True:
        now = datetime.now(IST); hm = now.hour*60 + now.minute
        if hm >= 15*60 + 32:
            log.info(f"[LVL-LIVE] market closed, loop exit {now}")
            try: tg(f"🏁 <b>LVL-LIVE</b> market closed — loop exit {now:%H:%M} | {status_text()}")
            except Exception: pass
            break
        if hm >= 9*60 + 15:
            try: run_once()
            except Exception as e:
                log.error(f"[LVL-LIVE] run err {e}")
                tg(f"🚨 <b>LVL-LIVE</b> run error: {e}")
            if time.time() - last_status >= STATUS_EVERY_SEC:
                tg(status_text()); last_status = time.time()
        time.sleep(60)

if __name__ == "__main__":
    if "loop" in sys.argv: loop()
    else:
        if not DRY: reconcile_boot()
        run_once()
