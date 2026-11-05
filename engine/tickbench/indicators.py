"""Streaming technical indicators.

Every indicator is a small class with ``update(...) -> value`` that is called once per bar.
The same classes back every script type (Pine ``ta.*``, MQL ``iMA``…, the Python/JS
helpers and the rule engine), so a strategy produces identical numbers no matter which
language it was written in. ``nan`` means "not enough data yet" (Pine's ``na``).

Definitions follow TradingView's documented formulas: EMA and RMA seed with the SMA of
the first ``length`` values, RSI/ATR use RMA, standard deviation is the population form.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Iterable

import numpy as np

NaN = math.nan


def isna(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


class SMA:
    def __init__(self, length: int):
        self.n = max(1, int(length))
        self.buf: deque = deque()
        self.sum = 0.0
        self.nan_count = 0

    def update(self, x: float) -> float:
        x = NaN if x is None else float(x)
        self.buf.append(x)
        if math.isnan(x):
            self.nan_count += 1
        else:
            self.sum += x
        if len(self.buf) > self.n:
            old = self.buf.popleft()
            if math.isnan(old):
                self.nan_count -= 1
            else:
                self.sum -= old
        if len(self.buf) < self.n or self.nan_count:
            return NaN
        # fsum over the window each bar: exact, so no floating-point drift builds up.
        return math.fsum(self.buf) / self.n


class EMA:
    def __init__(self, length: int, alpha: float | None = None):
        self.n = max(1, int(length))
        self.alpha = alpha if alpha is not None else 2.0 / (self.n + 1)
        self.seed = SMA(self.n)
        self.value = NaN

    def update(self, x: float) -> float:
        if isna(x):
            return self.value if not math.isnan(self.value) else NaN
        if math.isnan(self.value):
            s = self.seed.update(x)
            if not math.isnan(s):
                self.value = s
            return self.value
        self.value = self.alpha * float(x) + (1 - self.alpha) * self.value
        return self.value


class RMA(EMA):
    def __init__(self, length: int):
        super().__init__(length, alpha=1.0 / max(1, int(length)))


class WMA:
    def __init__(self, length: int):
        self.n = max(1, int(length))
        self.buf: deque = deque(maxlen=self.n)
        self.den = self.n * (self.n + 1) / 2

    def update(self, x: float) -> float:
        self.buf.append(NaN if x is None else float(x))
        if len(self.buf) < self.n or any(math.isnan(v) for v in self.buf):
            return NaN
        return sum(v * (i + 1) for i, v in enumerate(self.buf)) / self.den


class VWMA:
    def __init__(self, length: int):
        self.pv = SMA(length)
        self.v = SMA(length)

    def update(self, x: float, vol: float) -> float:
        a = self.pv.update(x * vol)
        b = self.v.update(vol)
        return a / b if b else NaN


class Stdev:
    def __init__(self, length: int, biased: bool = True):
        self.n = max(1, int(length))
        self.buf: deque = deque(maxlen=self.n)
        self.biased = biased

    def update(self, x: float) -> float:
        self.buf.append(NaN if x is None else float(x))
        if len(self.buf) < self.n or any(math.isnan(v) for v in self.buf):
            return NaN
        arr = np.fromiter(self.buf, float)
        return float(np.std(arr, ddof=0 if self.biased else 1))


class Highest:
    def __init__(self, length: int):
        self.n = max(1, int(length))
        self.buf: deque = deque(maxlen=self.n)

    def update(self, x: float) -> float:
        self.buf.append(NaN if x is None else float(x))
        if len(self.buf) < self.n:
            return NaN
        return max(self.buf)


class Lowest(Highest):
    def update(self, x: float) -> float:
        self.buf.append(NaN if x is None else float(x))
        if len(self.buf) < self.n:
            return NaN
        return min(self.buf)


class RSI:
    def __init__(self, length: int):
        self.up = RMA(length)
        self.down = RMA(length)
        self.prev = NaN

    def update(self, x: float) -> float:
        if isna(self.prev) or isna(x):
            self.prev = x if not isna(x) else self.prev
            return NaN
        ch = float(x) - self.prev
        self.prev = float(x)
        u = self.up.update(max(ch, 0.0))
        d = self.down.update(max(-ch, 0.0))
        if math.isnan(u) or math.isnan(d):
            return NaN
        if d == 0:
            return 100.0  # TradingView: down == 0 ? 100
        return 100.0 - 100.0 / (1.0 + u / d)


class TrueRange:
    def __init__(self):
        self.prev_close = NaN

    def update(self, high: float, low: float, close: float) -> float:
        if math.isnan(self.prev_close):
            tr = high - low
        else:
            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
        self.prev_close = close
        return tr


class ATR:
    def __init__(self, length: int):
        self.tr = TrueRange()
        self.rma = RMA(length)

    def update(self, high: float, low: float, close: float) -> float:
        return self.rma.update(self.tr.update(high, low, close))


class MACD:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.f = EMA(fast)
        self.s = EMA(slow)
        self.sig = EMA(signal)

    def update(self, x: float) -> tuple[float, float, float]:
        f, s = self.f.update(x), self.s.update(x)
        m = f - s if not (math.isnan(f) or math.isnan(s)) else NaN
        sg = self.sig.update(m) if not math.isnan(m) else NaN
        h = m - sg if not (math.isnan(m) or math.isnan(sg)) else NaN
        return m, sg, h


class Bollinger:
    def __init__(self, length: int = 20, mult: float = 2.0):
        self.ma = SMA(length)
        self.sd = Stdev(length)
        self.mult = mult

    def update(self, x: float) -> tuple[float, float, float]:
        m = self.ma.update(x)
        d = self.sd.update(x)
        if math.isnan(m) or math.isnan(d):
            return NaN, NaN, NaN
        return m, m + self.mult * d, m - self.mult * d


class Stoch:
    """Raw %K (Pine ta.stoch). Smoothing is done by the caller with SMA."""

    def __init__(self, length: int):
        self.h = Highest(length)
        self.l = Lowest(length)

    def update(self, close: float, high: float, low: float) -> float:
        hh, ll = self.h.update(high), self.l.update(low)
        if math.isnan(hh) or math.isnan(ll) or hh == ll:
            return NaN if math.isnan(hh) else 50.0
        return 100.0 * (close - ll) / (hh - ll)


class CCI:
    def __init__(self, length: int):
        self.n = max(1, int(length))
        self.buf: deque = deque(maxlen=self.n)

    def update(self, x: float) -> float:
        self.buf.append(float(x))
        if len(self.buf) < self.n:
            return NaN
        arr = np.fromiter(self.buf, float)
        m = arr.mean()
        md = np.abs(arr - m).mean()
        return float((x - m) / (0.015 * md)) if md else 0.0


class Change:
    def __init__(self, length: int = 1):
        self.buf: deque = deque(maxlen=max(1, int(length)) + 1)

    def update(self, x: float) -> float:
        self.buf.append(NaN if x is None else float(x))
        if len(self.buf) < self.buf.maxlen:
            return NaN
        return self.buf[-1] - self.buf[0]


class ROC(Change):
    def update(self, x: float) -> float:
        self.buf.append(NaN if x is None else float(x))
        if len(self.buf) < self.buf.maxlen or not self.buf[0]:
            return NaN
        return 100.0 * (self.buf[-1] - self.buf[0]) / self.buf[0]


class Cross:
    """Tracks the previous pair of values to detect crossings (Pine semantics)."""

    def __init__(self):
        self.pa = NaN
        self.pb = NaN

    def update(self, a: float, b: float) -> tuple[bool, bool]:
        a = NaN if a is None else float(a)
        b = NaN if b is None else float(b)
        up = (not any(math.isnan(v) for v in (a, b, self.pa, self.pb))) and a > b and self.pa <= self.pb
        down = (not any(math.isnan(v) for v in (a, b, self.pa, self.pb))) and a < b and self.pa >= self.pb
        self.pa, self.pb = a, b
        return up, down


class SuperTrend:
    def __init__(self, factor: float, atr_len: int):
        self.atr = ATR(atr_len)
        self.factor = factor
        self.upper = NaN
        self.lower = NaN
        self.prev_close = NaN
        self.prev_st = NaN
        self.direction = 1

    def update(self, high: float, low: float, close: float) -> tuple[float, int]:
        a = self.atr.update(high, low, close)
        if math.isnan(a):
            self.prev_close = close
            return NaN, 0
        src = (high + low) / 2
        up = src + self.factor * a
        lo = src - self.factor * a
        prev_upper, prev_lower = self.upper, self.lower
        if not math.isnan(prev_lower):
            lo = lo if (lo > prev_lower or self.prev_close < prev_lower) else prev_lower
        if not math.isnan(prev_upper):
            up = up if (up < prev_upper or self.prev_close > prev_upper) else prev_upper
        if math.isnan(self.prev_st):
            direction = 1
        elif self.prev_st == prev_upper:
            direction = -1 if close > up else 1
        else:
            direction = 1 if close < lo else -1
        st = lo if direction == -1 else up
        self.upper, self.lower, self.prev_st, self.prev_close, self.direction = up, lo, st, close, direction
        return st, direction


# ---------------------------------------------------------------------------------------------
# Vectorised helpers (run a streaming indicator across a whole array)

def run(ind, *arrays: Iterable[float]) -> np.ndarray:
    cols = [np.asarray(a, dtype=float) for a in arrays]
    out = np.empty(len(cols[0]))
    for i in range(len(cols[0])):
        out[i] = ind.update(*(c[i] for c in cols))
    return out


def run_multi(ind, n_out: int, *arrays) -> list[np.ndarray]:
    cols = [np.asarray(a, dtype=float) for a in arrays]
    outs = [np.empty(len(cols[0])) for _ in range(n_out)]
    for i in range(len(cols[0])):
        vals = ind.update(*(c[i] for c in cols))
        for k in range(n_out):
            outs[k][i] = vals[k]
    return outs


def sma(x, n):
    return run(SMA(n), x)


def ema(x, n):
    return run(EMA(n), x)


def rma(x, n):
    return run(RMA(n), x)


def wma(x, n):
    return run(WMA(n), x)


def rsi(x, n):
    return run(RSI(n), x)


def atr(h, l, c, n):
    return run(ATR(n), h, l, c)


def stdev(x, n):
    return run(Stdev(n), x)


def highest(x, n):
    return run(Highest(n), x)


def lowest(x, n):
    return run(Lowest(n), x)


def macd(x, fast=12, slow=26, signal=9):
    return run_multi(MACD(fast, slow, signal), 3, x)


def bbands(x, n=20, mult=2.0):
    return run_multi(Bollinger(n, mult), 3, x)


def cci(x, n):
    return run(CCI(n), x)


def crossover(a, b) -> np.ndarray:
    c = Cross()
    return np.array([c.update(x, y)[0] for x, y in zip(a, b)])


def crossunder(a, b) -> np.ndarray:
    c = Cross()
    return np.array([c.update(x, y)[1] for x, y in zip(a, b)])


MA_BY_NAME = {"sma": SMA, "ema": EMA, "rma": RMA, "smma": RMA, "wma": WMA, "lwma": WMA}


def ma(kind: str, x, n):
    cls = MA_BY_NAME.get(kind.lower())
    if cls is None:
        raise KeyError(kind)
    return run(cls(n), x)
