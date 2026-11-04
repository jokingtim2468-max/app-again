"""MetaTrader 5 data access (history + live).

Two transports, chosen automatically:
  1. Direct: the `MetaTrader5` Python package (Windows Python, MT5 terminal installed & logged in).
  2. Bridge: when the package isn't importable (e.g. backend runs in WSL for Antigravity), calls
     scripts/mt5_bridge.py running on Windows at APOLLO_MT5_BRIDGE_URL (default http://127.0.0.1:54982).

Env: APOLLO_MT5_PATH (terminal64.exe), APOLLO_MT5_LOGIN, APOLLO_MT5_PASSWORD, APOLLO_MT5_SERVER,
     APOLLO_MT5_UTC_OFFSET (hours; auto-detected from the live tick clock when unset).
MT5 timestamps are broker *server* time; everything returned here is converted to UTC epoch seconds.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import httpx
import numpy as np

TIMEFRAMES = {"1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15", "30m": "TIMEFRAME_M30",
              "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4", "1d": "TIMEFRAME_D1"}
BRIDGE = os.getenv("APOLLO_MT5_BRIDGE_URL", "http://127.0.0.1:54982")


class MT5Error(RuntimeError):
    pass


def _mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        return None
    return mt5


class _Direct:
    def __init__(self, mt5):
        self.mt5 = mt5
        self._ok = False
        self._offset: int | None = None

    def connect(self):
        if self._ok:
            return
        kw = {}
        if os.getenv("APOLLO_MT5_PATH"):
            kw["path"] = os.environ["APOLLO_MT5_PATH"]
        if os.getenv("APOLLO_MT5_LOGIN"):
            kw.update(login=int(os.environ["APOLLO_MT5_LOGIN"]), password=os.getenv("APOLLO_MT5_PASSWORD", ""),
                      server=os.getenv("APOLLO_MT5_SERVER", ""))
        if not self.mt5.initialize(**kw):
            raise MT5Error(f"MT5 initialize failed: {self.mt5.last_error()}  (is the terminal installed and logged in?)")
        self._ok = True

    def _select(self, symbol: str):
        self.connect()
        if not self.mt5.symbol_select(symbol, True):
            raise MT5Error(f"symbol {symbol!r} not available in this MT5 account (check Market Watch / broker symbol name)")
        return self.mt5.symbol_info(symbol)

    def utc_offset(self, symbol: str) -> int:
        if os.getenv("APOLLO_MT5_UTC_OFFSET"):
            return int(float(os.environ["APOLLO_MT5_UTC_OFFSET"]) * 3600)
        if self._offset is None:
            self._select(symbol)
            t = self.mt5.symbol_info_tick(symbol)
            # tick clock is server time; round to nearest 30 min against real UTC
            self._offset = int(round((t.time - time.time()) / 1800.0) * 1800) if t and t.time else 0
        return self._offset

    def info(self, symbol: str) -> dict:
        i = self._select(symbol)
        return {"symbol": symbol, "point": i.point, "digits": i.digits, "tick_size": i.trade_tick_size or i.point,
                "tick_value": i.trade_tick_value, "contract_size": i.trade_contract_size, "description": i.description}

    def rates(self, symbol: str, tf: str, start: datetime, end: datetime) -> dict:
        i = self._select(symbol)
        off = self.utc_offset(symbol)
        r = self.mt5.copy_rates_range(symbol, getattr(self.mt5, TIMEFRAMES[tf]),
                                      datetime.fromtimestamp(start.timestamp() + off, timezone.utc),
                                      datetime.fromtimestamp(end.timestamp() + off, timezone.utc))
        if r is None or len(r) == 0:
            raise MT5Error(f"no {tf} bars for {symbol} in range ({self.mt5.last_error()}). Scroll the chart back in MT5 to download history.")
        return {"time": (r["time"] - off).tolist(), "open": r["open"].tolist(), "high": r["high"].tolist(),
                "low": r["low"].tolist(), "close": r["close"].tolist(), "volume": r["tick_volume"].tolist(),
                "spread": (r["spread"] * i.point).tolist()}

    def ticks(self, symbol: str, start: datetime, end: datetime) -> dict:
        self._select(symbol)
        off = self.utc_offset(symbol)
        t = self.mt5.copy_ticks_range(symbol, datetime.fromtimestamp(start.timestamp() + off, timezone.utc),
                                      datetime.fromtimestamp(end.timestamp() + off, timezone.utc), self.mt5.COPY_TICKS_ALL)
        if t is None or len(t) == 0:
            raise MT5Error(f"no ticks for {symbol} in range ({self.mt5.last_error()})")
        last = np.where(t["last"] > 0, t["last"], (t["bid"] + t["ask"]) / 2)
        return {"time": (t["time_msc"] / 1000.0 - off).tolist(), "price": last.tolist(),
                "spread": (t["ask"] - t["bid"]).tolist(), "volume": np.maximum(t["volume"], 1).astype(int).tolist()}

    def tick(self, symbol: str) -> dict:
        self._select(symbol)
        off = self.utc_offset(symbol)
        t = self.mt5.symbol_info_tick(symbol)
        if t is None:
            raise MT5Error(f"no live tick for {symbol}")
        return {"time": t.time_msc / 1000.0 - off, "bid": t.bid, "ask": t.ask, "last": t.last or (t.bid + t.ask) / 2,
                "volume": int(t.volume or 1)}

    def book(self, symbol: str) -> dict:
        self._select(symbol)
        self.mt5.market_book_add(symbol)
        b = self.mt5.market_book_get(symbol) or ()
        bids = [[x.price, int(x.volume)] for x in b if x.type in (2, 4)]  # BOOK_TYPE_BUY(_MARKET)
        asks = [[x.price, int(x.volume)] for x in b if x.type in (1, 3)]  # BOOK_TYPE_SELL(_MARKET)
        return {"bids": sorted(bids, reverse=True)[:10], "asks": sorted(asks)[:10]}


class _Bridge:
    def _get(self, path: str, **params):
        try:
            r = httpx.get(f"{BRIDGE}{path}", params=params, timeout=120)
        except httpx.HTTPError as e:
            raise MT5Error(f"MetaTrader5 package not importable here and MT5 bridge unreachable at {BRIDGE} ({e}). "
                           "On Windows run: python scripts/mt5_bridge.py") from e
        if r.status_code != 200:
            raise MT5Error(r.json().get("error", r.text))
        return r.json()

    def info(self, symbol): return self._get("/info", symbol=symbol)
    def rates(self, symbol, tf, start, end): return self._get("/rates", symbol=symbol, tf=tf, start=start.timestamp(), end=end.timestamp())
    def ticks(self, symbol, start, end): return self._get("/ticks", symbol=symbol, start=start.timestamp(), end=end.timestamp())
    def tick(self, symbol): return self._get("/tick", symbol=symbol)
    def book(self, symbol): return self._get("/book", symbol=symbol)


_client = None


def client():
    """Direct MT5 package if importable, else the Windows bridge."""
    global _client
    if _client is None:
        m = _mt5()
        _client = _Direct(m) if m else _Bridge()
    return _client


def status() -> dict:
    c = client()
    try:
        if isinstance(c, _Direct):
            c.connect()
            acc = c.mt5.account_info()
            return {"connected": True, "transport": "direct", "server": getattr(acc, "server", None)}
        return {"connected": True, "transport": "bridge", **c._get("/status")}
    except MT5Error as e:
        return {"connected": False, "transport": "direct" if isinstance(c, _Direct) else "bridge", "error": str(e)}
