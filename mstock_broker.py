"""
=========================================================================
mstock_broker.py  —  mStock (Mirae Asset) execution adapter for ORION
=========================================================================
Handles authentication, order placement, cancellation, status checks
via mStock Trading API Type B.

Architecture:
  Kite  → data feed (historical bars, WebSocket ticks)  [unchanged]
  mStock → live order execution only                     [this module]

Usage in ORION:
  Set EXECUTION_BROKER = "mstock_live" in ORION_PAPER_V2_5_12.py
  Add MSTOCK_* credentials to credentials.py

SDK:  pip install mStock-TradingApi-B
Docs: https://tradingapi.mstock.com/docs/v1/typeB/

Symbol format:  NIFTY25MAY24000CE  (DDMMM + strike + CE/PE)
Product type:   INTRADAY  (for all intraday options)
=========================================================================
"""
import os, sys, json, time, logging
from datetime import datetime
from typing import Optional, Tuple

log = logging.getLogger("mstock")

# ── SDK import ────────────────────────────────────────────────────────
try:
    from tradingapi_b.mconnect import MConnectB as _SDK
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    log.warning("[mstock] mStock-TradingApi-B not installed. "
                "Run: pip install mStock-TradingApi-B")

TOKEN_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           ".mstock_token_cache.json")


def build_option_symbol(underlying: str, expiry: datetime,
                        strike: int, side: str) -> str:
    """
    Build mStock NFO option trading symbol.
    Format: NIFTY25MAY24000CE  (DDMMM + strike + CE/PE)

    Examples:
      NIFTY, expiry=2026-05-29, strike=24000, CE  → NIFTY29MAY24000CE
      NIFTY, expiry=2026-06-05, strike=23500, PE  → NIFTY05JUN23500PE

    Note: Verify against mStock instrument master if fills fail.
    To dump instrument master: broker.dump_instruments("NFO")
    """
    dd  = expiry.strftime("%d")            # 29
    mmm = expiry.strftime("%b").upper()    # MAY
    return f"{underlying}{dd}{mmm}{strike}{side}"


class MStockBroker:
    """
    mStock execution adapter — ORION live order execution.
    Paper mode: EXECUTION_BROKER="kite_paper" → this class is never called.
    Live  mode: EXECUTION_BROKER="mstock_live" → used for BUY/SELL orders only.
    """

    def __init__(self):
        if not _SDK_AVAILABLE:
            raise RuntimeError(
                "mStock SDK not installed. Run: pip install mStock-TradingApi-B")

        _repo = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, _repo)
        try:
            import credentials as _c
            self._api_key  = getattr(_c, 'MSTOCK_API_KEY',  '')
            self._user_id  = getattr(_c, 'MSTOCK_USER_ID',  '')
            self._password = getattr(_c, 'MSTOCK_PASSWORD', '')
            self._totp_sec = getattr(_c, 'MSTOCK_TOTP_SECRET', '')
        except ImportError:
            raise RuntimeError("credentials.py not found")

        if not all([self._api_key, self._user_id, self._password]):
            raise RuntimeError(
                "MSTOCK_API_KEY / MSTOCK_USER_ID / MSTOCK_PASSWORD "
                "missing in credentials.py")

        self._client = _SDK(
            api_key=self._api_key,
            debug=False,
            disable_ssl=True
        )
        self._logged_in = False

    # ── Authentication ────────────────────────────────────────────────
    @staticmethod
    def _to_dict(resp) -> dict:
        """Normalize SDK response — handles dict, requests.Response, or custom objects."""
        if isinstance(resp, dict):
            return resp
        if hasattr(resp, 'json'):
            try:
                return resp.json()
            except Exception:
                pass
        if hasattr(resp, '__dict__'):
            return vars(resp)
        return {}

    def login(self) -> bool:
        """TOTP-based login. Token valid until midnight."""
        if self._load_cached_token():
            log.info("[mstock] Using cached token.")
            return True
        try:
            import pyotp
        except ImportError:
            raise RuntimeError("pyotp not installed. pip install pyotp")

        try:
            # Step 1: login with credentials
            raw = self._client.login(
                user_id=self._user_id,
                password=self._password
            )
            resp = self._to_dict(raw)
            log.info(f"[mstock] Login step1: {resp.get('message', raw)}")

            # Step 2: TOTP verification
            totp_code = pyotp.TOTP(self._totp_sec).now()
            raw2 = self._client.verify_totp(otp=totp_code)
            resp2 = self._to_dict(raw2)
            log.info(f"[mstock] TOTP verify: {resp2.get('message', raw2)}")

            if resp2.get('status') in ('true', True, 'True', 'success', 'SUCCESS') \
                    or resp2.get('success') is True:
                self._logged_in = True
                self._cache_token()
                log.info("[mstock] Login successful.")
                return True
            else:
                log.error(f"[mstock] TOTP verification failed: {resp2}")
                return False

        except Exception as e:
            log.error(f"[mstock] Login failed: {e}")
            return False

    def _cache_token(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with open(TOKEN_CACHE, 'w') as f:
            json.dump({'date': today, 'logged_in': True}, f)

    def _load_cached_token(self) -> bool:
        """Check if we already logged in today (session persists until midnight)."""
        if not os.path.exists(TOKEN_CACHE):
            return False
        try:
            data = json.load(open(TOKEN_CACHE))
            today = datetime.now().strftime("%Y-%m-%d")
            if data.get('date') == today and data.get('logged_in'):
                self._logged_in = True
                return True
        except Exception:
            pass
        return False

    def ensure_logged_in(self):
        if not self._logged_in:
            if not self.login():
                raise RuntimeError("[mstock] Login required but failed.")

    # ── Instrument lookup ─────────────────────────────────────────────
    def get_symbol_token(self, trading_symbol: str,
                         exchange: str = "NFO") -> Optional[str]:
        """
        Lookup instrument token for a symbol from mStock instrument master.
        Returns token string or None.
        Tip: call dump_instruments() once to inspect available symbols.
        """
        self.ensure_logged_in()
        try:
            resp = self._to_dict(self._client.search_scrip(
                exchange=exchange,
                searchscrip=trading_symbol
            ))
            scrips = resp.get('data', [])
            for s in scrips:
                if s.get('tradingsymbol') == trading_symbol:
                    return str(s.get('symboltoken') or s.get('token', ''))
        except Exception as e:
            log.warning(f"[mstock] get_symbol_token failed: {e}")
        return None

    # ── Order placement ───────────────────────────────────────────────
    def place_order(self,
                    transaction_type: str,      # "BUY" or "SELL"
                    trading_symbol: str,         # e.g. "NIFTY29MAY24000CE"
                    quantity: int,               # total quantity (lots × lot_size)
                    order_type: str = "MARKET",  # "MARKET" or "LIMIT"
                    price: float = 0.0,
                    exchange: str = "NFO",
                    product: str = "INTRADAY",   # always INTRADAY for options
                    symbol_token: str = "",
                    tag: str = "ORION"
                    ) -> Optional[str]:
        """
        Place order. Returns order_id string on success, None on failure.
        If symbol_token is empty, attempts auto-lookup (slower).
        """
        self.ensure_logged_in()

        # Auto-resolve token if not provided
        if not symbol_token:
            symbol_token = self.get_symbol_token(trading_symbol, exchange) or ""
            if not symbol_token:
                log.warning(f"[mstock] Could not resolve token for {trading_symbol}. "
                             "Order may still work (some endpoints accept symbol without token).")

        try:
            resp = self._to_dict(self._client.place_order(
                _variety="NORMAL",
                _tradingsymbol=trading_symbol,
                _symboltoken=symbol_token,
                _exchange=exchange,
                _transactiontype=transaction_type,
                _ordertype=order_type,
                _quantity=str(quantity),
                _producttype=product,
                _price=str(price) if order_type == "LIMIT" else "0",
                _triggerprice="0",
                _squareoff="0",
                _stoploss="0",
                _trailingStopLoss="",
                _disclosedquantity="",
                _duration="DAY",
                _ordertag=tag
            ))
            log.info(f"[mstock] place_order resp: {resp}")
            order_id = (resp.get('data', {}).get('orderid')
                        or resp.get('orderid')
                        or resp.get('order_id'))
            if order_id:
                log.info(f"[mstock] {transaction_type} placed: {trading_symbol} "
                         f"qty={quantity} type={order_type} → orderid={order_id}")
                return str(order_id)
            log.error(f"[mstock] No orderid in response: {resp}")
            return None

        except Exception as e:
            log.error(f"[mstock] place_order exception: {e}")
            return None

    def cancel_order(self, order_id: str,
                     variety: str = "NORMAL") -> bool:
        """Cancel a pending order. Returns True on success."""
        self.ensure_logged_in()
        try:
            resp = self._to_dict(self._client.cancel_order(
                _variety=variety,
                _orderid=order_id
            ))
            log.info(f"[mstock] cancel_order {order_id}: {resp.get('message','')}")
            return resp.get('status') in ('true', True, 'True', 'success')
        except Exception as e:
            log.error(f"[mstock] cancel_order {order_id}: {e}")
            return False

    def order_status(self, order_id: str) -> Tuple[str, float]:
        """
        Returns (status, fill_price).
        status: "COMPLETE" / "OPEN" / "PENDING" / "REJECTED" / "CANCELLED" / "UNKNOWN"
        fill_price: average execution price (0 if not yet filled)
        """
        self.ensure_logged_in()
        try:
            resp = self._to_dict(self._client.get_order_book())
            orders = resp.get('data', [])
            if not isinstance(orders, list):
                orders = []
            if isinstance(orders, list):
                for o in orders:
                    if str(o.get('orderid', '')) == str(order_id):
                        status = str(o.get('status', 'UNKNOWN')).upper()
                        fill   = float(o.get('averageprice') or
                                       o.get('fillprice') or 0)
                        return status, fill
        except Exception as e:
            log.error(f"[mstock] order_status {order_id}: {e}")
        return "UNKNOWN", 0.0

    def wait_for_fill(self, order_id: str,
                      timeout_sec: int = 10,
                      poll_sec: float = 0.5) -> Tuple[str, float]:
        """
        Poll until COMPLETE / REJECTED / CANCELLED or timeout.
        Returns (status, fill_price).
        """
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            status, fill = self.order_status(order_id)
            if status in ("COMPLETE", "REJECTED", "CANCELLED"):
                return status, fill
            time.sleep(poll_sec)
        log.warning(f"[mstock] wait_for_fill timeout — order {order_id} not confirmed.")
        return "TIMEOUT", 0.0

    def positions(self) -> list:
        """Returns list of current intraday positions."""
        self.ensure_logged_in()
        try:
            resp = self._to_dict(self._client.get_net_position())
            return resp.get('data', [])
        except Exception as e:
            log.error(f"[mstock] positions(): {e}")
            return []

    def net_qty(self, trading_symbol: str) -> int:
        """Net quantity for a symbol (positive=long, 0=flat)."""
        for p in self.positions():
            sym = p.get('tradingsymbol') or p.get('trading_symbol', '')
            if sym == trading_symbol:
                return int(p.get('netqty') or p.get('net_qty') or 0)
        return 0

    def dump_instruments(self, exchange: str = "NFO"):
        """
        Print first 20 NFO instruments — call once to verify symbol format.
        Run manually: python3 -c "from mstock_broker import *; b=MStockBroker(); b.login(); b.dump_instruments()"
        """
        self.ensure_logged_in()
        try:
            resp = self._to_dict(self._client.get_all_instruments(exchange=exchange))
            instruments = resp.get('data', [])[:20]
            print(f"\n--- mStock {exchange} instruments (first 20) ---")
            for i in instruments:
                print(f"  {i.get('tradingsymbol','?'):30s}  token={i.get('symboltoken','?')}")
        except Exception as e:
            log.error(f"[mstock] dump_instruments: {e}")
