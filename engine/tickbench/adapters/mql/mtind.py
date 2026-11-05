"""MetaTrader-definition indicators and shift-indexed access.

The EA runs at each bar's *open* (MetaTrader's "Open prices only" model): shift 0 is the bar that
just opened (its high/low/close all equal the open so far), shift 1 is the last completed bar.
Values for completed bars come from one pass over the data; the forming bar's value comes from a
copy of the streaming state fed with the forming prices, so nothing from the future leaks in.
"""

from __future__ import annotations

import copy
import math
from collections import deque

import numpy as np

from ... import indicators as ind

NaN = math.nan


class EMA_MT:
    """MetaTrader EMA: starts from the first price (no SMA seed)."""

    def __init__(self, n):
        self.k = 2.0 / (int(n) + 1)
        self.v = NaN

    def update(self, x):
        self.v = x if math.isnan(self.v) else self.v + self.k * (x - self.v)
        return self.v


class ATR_MT:
    """MetaTrader ATR = simple average of true range."""

    def __init__(self, n):
        self.tr = ind.TrueRange()
        self.sma = ind.SMA(n)

    def update(self, h, l, c):
        return self.sma.update(self.tr.update(h, l, c))


class MACD_MT:
    """Main = EMA(fast) - EMA(slow); signal = SMA(main, signal) (MetaTrader's definition)."""

    def __init__(self, fast, slow, signal):
        self.f, self.s, self.sig = EMA_MT(fast), EMA_MT(slow), ind.SMA(signal)

    def update(self, x):
        m = self.f.update(x) - self.s.update(x)
        return m, self.sig.update(m)


class Stoch_MT:
    def __init__(self, k, d, slowing, ma_method=0):
        self.hh, self.ll = ind.Highest(k), ind.Lowest(k)
        self.num, self.den = ind.SMA(slowing), ind.SMA(slowing)
        self.d = MA_FACTORY.get(ma_method, ind.SMA)(d)

    def update(self, h, l, c):
        hh, ll = self.hh.update(h), self.ll.update(l)
        if math.isnan(hh) or math.isnan(ll):
            self.num.update(NaN)
            self.den.update(NaN)
            return NaN, NaN
        num = self.num.update(c - ll)
        den = self.den.update(hh - ll)
        if math.isnan(num) or math.isnan(den):
            return NaN, NaN
        k = 100.0 if den == 0 else 100.0 * num / den
        return k, self.d.update(k)


class Momentum_MT:
    def __init__(self, n):
        self.buf = deque(maxlen=int(n) + 1)

    def update(self, x):
        self.buf.append(x)
        if len(self.buf) < self.buf.maxlen or not self.buf[0]:
            return NaN
        return self.buf[-1] / self.buf[0] * 100.0


class Bands_MT:
    def __init__(self, n, dev):
        self.b = ind.Bollinger(n, dev)

    def update(self, x):
        return self.b.update(x)  # (middle, upper, lower)


class ADX_MT:
    """Approximation: Wilder DMI/ADX (MetaTrader's iADX smooths slightly differently)."""

    def __init__(self, n):
        from ..pine.builtins import _DMI
        self.d = _DMI(n, n)

    def update(self, h, l, c):
        p, m, a = self.d.update(h, l, c)
        return a, p, m


MA_FACTORY = {0: ind.SMA, 1: EMA_MT, 2: ind.RMA, 3: ind.WMA}


class Price:
    """Applied price for bar j; the forming bar only knows its open."""

    def __init__(self, bars):
        self.b = bars

    def get(self, applied: int, j: int, forming: bool):
        b = self.b
        if forming:
            return b.open[j]  # every applied price equals the open until the bar develops
        if applied == 0:
            return b.close[j]
        if applied == 1:
            return b.open[j]
        if applied == 2:
            return b.high[j]
        if applied == 3:
            return b.low[j]
        if applied == 4:
            return (b.high[j] + b.low[j]) / 2
        if applied == 5:
            return (b.high[j] + b.low[j] + b.close[j]) / 3
        if applied == 6:
            return (b.high[j] + b.low[j] + 2 * b.close[j]) / 4
        return b.close[j]

    def hlc(self, j: int, forming: bool):
        b = self.b
        if forming:
            return b.open[j], b.open[j], b.open[j]
        return b.high[j], b.low[j], b.close[j]


class IndSeries:
    """One indicator instance (one handle). ``value(buf, shift, i)`` with MetaTrader shift semantics."""

    def __init__(self, bars, factory, inputs, n_out: int):
        self.bars = bars
        self.factory = factory
        self.inputs = inputs          # (j, forming) -> tuple of update() args
        self.n_out = n_out
        self.completed: list[np.ndarray] | None = None
        self.stream = factory()
        self.fed = 0
        self.form_cache: tuple[int, tuple] | None = None

    def _complete(self):
        n = len(self.bars)
        outs = [np.full(n, NaN) for _ in range(self.n_out)]
        s = self.factory()
        for j in range(n):
            v = s.update(*self.inputs(j, False))
            if self.n_out == 1:
                outs[0][j] = v
            else:
                for k in range(self.n_out):
                    outs[k][j] = v[k]
        self.completed = outs

    def _forming(self, i: int) -> tuple:
        if self.form_cache and self.form_cache[0] == i:
            return self.form_cache[1]
        while self.fed < i:
            self.stream.update(*self.inputs(self.fed, False))
            self.fed += 1
        s = copy.deepcopy(self.stream)
        v = s.update(*self.inputs(i, True))
        v = (v,) if self.n_out == 1 else tuple(v)
        self.form_cache = (i, v)
        return v

    def value(self, buf: int, shift: int, i: int) -> float:
        if buf >= self.n_out or shift < 0:
            return NaN
        if shift == 0:
            return float(self._forming(i)[buf])
        j = i - shift
        if j < 0:
            return NaN
        if self.completed is None:
            self._complete()
        return float(self.completed[buf][j])
