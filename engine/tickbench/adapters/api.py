"""The simple strategy API shared by the Python, rules, JS and Tradovate adapters."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .. import indicators as ta
from ..core.engine import RunContext


class Series:
    """A full-length array viewed from the current bar: ``s[0]`` is now, ``s[1]`` one bar ago.

    Values after the current bar are never reachable, so a strategy cannot peek ahead.
    """

    __slots__ = ("_arr", "_ctx", "name")

    def __init__(self, arr: np.ndarray, ctx: RunContext, name: str = ""):
        self._arr = np.asarray(arr, dtype=float)
        self._ctx = ctx
        self.name = name

    def __getitem__(self, k: int) -> float:
        if not isinstance(k, int):
            raise TypeError("Use an integer bars-ago index, e.g. close[0] for now, close[1] for the previous bar.")
        j = self._ctx.i - k
        if k < 0 or j < 0:
            return math.nan
        return float(self._arr[j])

    @property
    def values(self) -> np.ndarray:
        """Everything up to and including the current bar (oldest first)."""
        return self._arr[: self._ctx.i + 1]

    def __len__(self) -> int:
        return self._ctx.i + 1

    def __float__(self) -> float:
        return self[0]

    def __repr__(self) -> str:
        return f"Series({self.name or '?'} = {self[0]:.6g})"

    # comparisons against the current value, so `if ctx.close > sma:` reads naturally
    def _v(self, o):
        return o[0] if isinstance(o, Series) else o

    def __gt__(self, o): return self[0] > self._v(o)
    def __lt__(self, o): return self[0] < self._v(o)
    def __ge__(self, o): return self[0] >= self._v(o)
    def __le__(self, o): return self[0] <= self._v(o)
    def __add__(self, o): return self[0] + self._v(o)
    def __radd__(self, o): return self._v(o) + self[0]
    def __sub__(self, o): return self[0] - self._v(o)
    def __rsub__(self, o): return self._v(o) - self[0]
    def __mul__(self, o): return self[0] * self._v(o)
    def __rmul__(self, o): return self._v(o) * self[0]
    def __truediv__(self, o): return self[0] / self._v(o)
    def __rtruediv__(self, o): return self._v(o) / self[0]


def _val(x, k=0):
    if isinstance(x, Series):
        return x[k]
    if isinstance(x, (list, tuple, np.ndarray)):
        return float(x[-1 - k]) if len(x) > k else math.nan
    return float(x)


class StrategyAPI:
    """Object handed to strategies as ``ctx``."""

    def __init__(self, ctx: RunContext, params: dict, immediate: bool = False):
        self._ctx = ctx
        self._immediate = immediate
        self.params = params
        b = ctx.bars
        self.open = Series(b.open, ctx, "open")
        self.high = Series(b.high, ctx, "high")
        self.low = Series(b.low, ctx, "low")
        self.close = Series(b.close, ctx, "close")
        self.volume = Series(b.volume, ctx, "volume")
        self.time = Series(b.time.astype(float), ctx, "time")
        self.symbol = b.symbol
        self.timeframe = b.timeframe
        self.state: dict[str, Any] = {}

    # ---- bar info
    @property
    def i(self) -> int:
        return self._ctx.i

    bar_index = i

    @property
    def broker(self):
        return self._ctx.broker

    @property
    def position(self) -> float:
        return self._ctx.broker.position_size

    @property
    def position_price(self) -> float:
        return self._ctx.broker.position_avg_price

    @property
    def equity(self) -> float:
        return self._ctx.broker.equity()

    @property
    def cash(self) -> float:
        return self._ctx.broker.cash

    @property
    def open_trades(self) -> list:
        return list(self._ctx.broker.open)

    # ---- data helpers
    def src(self, name: str) -> np.ndarray:
        return self._ctx.bars.series(name)

    def _arr(self, source) -> np.ndarray:
        if isinstance(source, str):
            return self.src(source)
        if isinstance(source, Series):
            return source._arr
        return np.asarray(source, dtype=float)

    def _wrap(self, arr, name):
        return Series(arr, self._ctx, name)

    # ---- indicators (computed once over the full history, read through Series so no look-ahead)
    def sma(self, source="close", length=14): return self._wrap(ta.sma(self._arr(source), length), f"sma{length}")
    def ema(self, source="close", length=14): return self._wrap(ta.ema(self._arr(source), length), f"ema{length}")
    def rma(self, source="close", length=14): return self._wrap(ta.rma(self._arr(source), length), f"rma{length}")
    def wma(self, source="close", length=14): return self._wrap(ta.wma(self._arr(source), length), f"wma{length}")
    def rsi(self, source="close", length=14): return self._wrap(ta.rsi(self._arr(source), length), f"rsi{length}")
    def stdev(self, source="close", length=20): return self._wrap(ta.stdev(self._arr(source), length), f"stdev{length}")
    def highest(self, source="high", length=20): return self._wrap(ta.highest(self._arr(source), length), f"highest{length}")
    def lowest(self, source="low", length=20): return self._wrap(ta.lowest(self._arr(source), length), f"lowest{length}")
    def cci(self, source="hlc3", length=20): return self._wrap(ta.cci(self._arr(source), length), f"cci{length}")

    def atr(self, length=14):
        b = self._ctx.bars
        return self._wrap(ta.atr(b.high, b.low, b.close, length), f"atr{length}")

    def macd(self, source="close", fast=12, slow=26, signal=9):
        m, s, h = ta.macd(self._arr(source), fast, slow, signal)
        return self._wrap(m, "macd"), self._wrap(s, "signal"), self._wrap(h, "hist")

    def bbands(self, source="close", length=20, mult=2.0):
        m, u, l = ta.bbands(self._arr(source), length, mult)
        return self._wrap(m, "basis"), self._wrap(u, "upper"), self._wrap(l, "lower")

    def indicator(self, fn, *args, name="custom"):
        """Wrap any function that maps full arrays to an array (must not look ahead)."""
        return self._wrap(np.asarray(fn(*args), dtype=float), name)

    @staticmethod
    def crossover(a, b) -> bool:
        a0, a1, b0, b1 = _val(a, 0), _val(a, 1), _val(b, 0), _val(b, 1)
        if any(math.isnan(v) for v in (a0, a1, b0, b1)):
            return False
        return a0 > b0 and a1 <= b1

    @staticmethod
    def crossunder(a, b) -> bool:
        a0, a1, b0, b1 = _val(a, 0), _val(a, 1), _val(b, 0), _val(b, 1)
        if any(math.isnan(v) for v in (a0, a1, b0, b1)):
            return False
        return a0 < b0 and a1 >= b1

    @staticmethod
    def na(x) -> bool:
        v = _val(x) if not isinstance(x, float) else x
        return v is None or (isinstance(v, float) and math.isnan(v))

    # ---- orders
    def buy(self, qty: float | None = None, *, sl: float | None = None, tp: float | None = None,
            sl_pct: float | None = None, tp_pct: float | None = None, sl_points: float | None = None,
            tp_points: float | None = None, trail: float | None = None, tag: str = "long", reason: str = ""):
        return self._enter(1, qty, sl, tp, sl_pct, tp_pct, sl_points, tp_points, trail, tag, reason)

    def sell(self, qty: float | None = None, *, sl: float | None = None, tp: float | None = None,
             sl_pct: float | None = None, tp_pct: float | None = None, sl_points: float | None = None,
             tp_points: float | None = None, trail: float | None = None, tag: str = "short", reason: str = ""):
        return self._enter(-1, qty, sl, tp, sl_pct, tp_pct, sl_points, tp_points, trail, tag, reason)

    short = sell

    def _enter(self, side, qty, sl, tp, sl_pct, tp_pct, sl_points, tp_points, trail, tag, reason):
        ref = self._ctx.bars.close[self._ctx.i]
        sl_off = sl_points if sl_points is not None else (ref * sl_pct / 100 if sl_pct is not None else None)
        tp_off = tp_points if tp_points is not None else (ref * tp_pct / 100 if tp_pct is not None else None)
        self._ctx.log("signal", f"{'Buy' if side > 0 else 'Sell'} signal" + (f": {reason}" if reason else ""))
        return self._ctx.broker.submit_market(side, qty, tag=tag, reason=reason, sl=sl, tp=tp, sl_offset=sl_off,
                                              tp_offset=tp_off, trail=trail, immediate=self._immediate)

    def buy_limit(self, price, qty=None, **kw): return self._pending("limit", 1, price, qty, **kw)
    def sell_limit(self, price, qty=None, **kw): return self._pending("limit", -1, price, qty, **kw)
    def buy_stop(self, price, qty=None, **kw): return self._pending("stop", 1, price, qty, **kw)
    def sell_stop(self, price, qty=None, **kw): return self._pending("stop", -1, price, qty, **kw)

    def _pending(self, kind, side, price, qty, *, sl=None, tp=None, tag="", reason="", expire_bars=None):
        exp = self._ctx.i + int(expire_bars) if expire_bars else None
        return self._ctx.broker.submit_pending(kind, side, float(price), qty, tag=tag, reason=reason, sl=sl, tp=tp,
                                               expire_bar=exp)

    def close_position(self, tag: str | None = None, reason: str = "Exit signal", qty: float | None = None):
        if not self._ctx.broker.open:
            return None
        self._ctx.log("signal", f"Exit signal: {reason}")
        return self._ctx.broker.submit_close(tag=tag, qty=qty, reason=reason, immediate=self._immediate)

    exit = close_position

    def close_long(self, reason="Exit long"):
        return self._ctx.broker.submit_close(side=1, reason=reason, immediate=self._immediate)

    def close_short(self, reason="Exit short"):
        return self._ctx.broker.submit_close(side=-1, reason=reason, immediate=self._immediate)

    def cancel(self, tag: str):
        return self._ctx.broker.cancel(tag=tag)

    def set_stop(self, price: float | None = None, take_profit: float | None = None):
        for t in self._ctx.broker.open:
            self._ctx.broker.modify(t, sl=price, tp=take_profit)

    # ---- output
    def log(self, *msg):
        self._ctx.log("log", " ".join(str(m) for m in msg))

    def plot(self, name: str, value, overlay: bool = True, color: str | None = None):
        self._ctx.plot(name, _val(value) if value is not None else None, overlay=overlay, color=color)
