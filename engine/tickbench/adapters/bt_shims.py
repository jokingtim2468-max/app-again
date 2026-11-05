"""Stand-ins for the backtesting.py and backtrader libraries.

They implement the parts strategies actually touch (data access, indicators, orders,
position) and forward orders to the Tickbench broker.
"""

from __future__ import annotations

import inspect
import math
import types
from numbers import Number
from typing import Any

import numpy as np
import pandas as pd

from .. import indicators as ta
from ..core.engine import RunContext
from ..errors import UnsupportedFeature

MODULE_NAMES = ["backtesting", "backtesting.lib", "backtesting.test", "backtrader", "backtrader.indicators",
                "backtrader.feeds", "backtrader.analyzers", "backtrader.sizers"]


def find_strategy_class(mod, base):
    found = [v for v in vars(mod).values()
             if inspect.isclass(v) and issubclass(v, base) and v is not base and v.__module__ == mod.__name__]
    if not found:
        found = [v for v in vars(mod).values() if inspect.isclass(v) and issubclass(v, base) and v is not base]
    return found[-1] if found else None


def _qty_from_size(ctx: RunContext, size):
    """backtesting.py: 0 < size < 1 is a fraction of equity, >= 1 is a unit count."""
    if size is None:
        return None
    if 0 < size < 1:
        price = ctx.bars.close[ctx.i]
        return ctx.broker.equity() * size / (price * ctx.settings.point_value)
    return float(size)


# =============================================================================== backtesting.py
class _Ind:
    """An indicator array whose visible length grows bar by bar."""

    def __init__(self, arr: np.ndarray, runner: "BpyRunner", name: str = ""):
        self._arr = np.asarray(arr, dtype=float)
        self._r = runner
        self.name = name

    def _vis(self) -> np.ndarray:
        n = self._r.visible
        return self._arr if n is None else self._arr[:n]

    def __array__(self, dtype=None, copy=None):
        v = self._vis()
        return v.astype(dtype) if dtype else v

    def __getitem__(self, k):
        return self._vis()[k]

    def __len__(self):
        return len(self._vis())

    def __iter__(self):
        return iter(self._vis())

    def __float__(self):
        return float(self._vis()[-1])

    @property
    def values(self):
        return self._vis()

    @property
    def s(self):
        return pd.Series(self._vis())

    def _o(self, o):
        return o._vis() if isinstance(o, _Ind) else o

    def __gt__(self, o): return self._vis() > self._o(o)
    def __lt__(self, o): return self._vis() < self._o(o)
    def __ge__(self, o): return self._vis() >= self._o(o)
    def __le__(self, o): return self._vis() <= self._o(o)
    def __add__(self, o): return self._vis() + self._o(o)
    def __sub__(self, o): return self._vis() - self._o(o)
    def __mul__(self, o): return self._vis() * self._o(o)
    def __truediv__(self, o): return self._vis() / self._o(o)
    def __radd__(self, o): return self._o(o) + self._vis()
    def __rsub__(self, o): return self._o(o) - self._vis()
    def __rmul__(self, o): return self._o(o) * self._vis()
    def __rtruediv__(self, o): return self._o(o) / self._vis()


class _BpyData:
    def __init__(self, runner: "BpyRunner"):
        self._r = runner
        b = runner.ctx.bars
        self._cols = {"Open": b.open, "High": b.high, "Low": b.low, "Close": b.close, "Volume": b.volume}
        self._index = pd.to_datetime(b.time, unit="ms", utc=True)

    def __getattr__(self, name):
        cols = self.__dict__.get("_cols", {})
        if name in cols:
            n = self._r.visible
            a = cols[name]
            return a if n is None else a[:n]
        raise AttributeError(name)

    def __getitem__(self, name):
        return getattr(self, name)

    @property
    def index(self):
        n = self._r.visible
        return self._index if n is None else self._index[:n]

    @property
    def df(self):
        n = self._r.visible
        d = pd.DataFrame({k: (v if n is None else v[:n]) for k, v in self._cols.items()}, index=self.index)
        return d

    def __len__(self):
        n = self._r.visible
        return len(self._cols["Close"]) if n is None else n


class _BpyPosition:
    def __init__(self, runner: "BpyRunner"):
        self._r = runner

    @property
    def size(self):
        return self._r.ctx.broker.position_size

    def __bool__(self):
        return self.size != 0

    @property
    def is_long(self):
        return self.size > 0

    @property
    def is_short(self):
        return self.size < 0

    @property
    def pl(self):
        b = self._r.ctx.broker
        price = self._r.ctx.bars.close[self._r.ctx.i]
        return sum(t.unrealized(price, b.s.point_value) for t in b.open)

    @property
    def pl_pct(self):
        b = self._r.ctx.broker
        if not b.open:
            return 0.0
        price = self._r.ctx.bars.close[self._r.ctx.i]
        avg = b.position_avg_price
        return (price / avg - 1) * 100 * (1 if self.size > 0 else -1)

    def close(self, portion: float = 1.0):
        ctx = self._r.ctx
        qty = None if portion >= 1 else abs(self.size) * portion
        ctx.broker.submit_close(qty=qty, reason="position.close()")


class _BpyTrade:
    def __init__(self, t, runner):
        self._t = t
        self._r = runner

    size = property(lambda s: s._t.qty * s._t.side)
    entry_price = property(lambda s: s._t.entry_price)
    exit_price = property(lambda s: s._t.exit_price)
    pl = property(lambda s: s._t.pnl)
    is_long = property(lambda s: s._t.side > 0)
    is_short = property(lambda s: s._t.side < 0)
    entry_bar = property(lambda s: s._t.entry_bar)
    exit_bar = property(lambda s: s._t.exit_bar)
    tag = property(lambda s: s._t.tag)

    @property
    def sl(self):
        return self._t.sl

    @sl.setter
    def sl(self, v):
        self._t.sl = v

    @property
    def tp(self):
        return self._t.tp

    @tp.setter
    def tp(self, v):
        self._t.tp = v

    def close(self, portion: float = 1.0):
        qty = None if portion >= 1 else self._t.qty * portion
        self._r.ctx.broker.submit_close(trade_ids=[self._t.id], qty=qty, reason="trade.close()")


def make_bpy_strategy_base():
    class Strategy:
        def __init__(self, runner: "BpyRunner", params: dict):
            self._runner = runner
            for k, v in params.items():
                setattr(self, k, v)

        # set in BpyRunner
        data: Any = None
        position: Any = None

        def init(self):
            pass

        def next(self):
            pass

        def I(self, func, *args, name=None, plot=True, overlay=None, color=None, scatter=False, **kwargs):  # noqa: E743
            args = [np.asarray(a, dtype=float) if isinstance(a, (_Ind, pd.Series)) else a for a in args]
            val = func(*args, **kwargs)
            if isinstance(val, (pd.Series, pd.DataFrame)):
                val = val.to_numpy().T
            val = np.asarray(val, dtype=float)
            label = name or getattr(func, "__name__", "indicator")
            n = len(self._runner.ctx.bars)
            if val.ndim == 1:
                if len(val) != n:
                    raise ValueError(f"Indicator {label} returned {len(val)} values, expected {n}.")
                ind = _Ind(val, self._runner, label)
                if plot:
                    self._runner.register_plot(label, val, overlay)
                return ind
            rows = [_Ind(r, self._runner, f"{label}[{k}]") for k, r in enumerate(val)]
            if plot:
                for k, r in enumerate(val):
                    self._runner.register_plot(f"{label}[{k}]", r, overlay)
            return rows

        def buy(self, *, size=None, limit=None, stop=None, sl=None, tp=None, tag=None):
            return self._runner.order(1, size, limit, stop, sl, tp, tag)

        def sell(self, *, size=None, limit=None, stop=None, sl=None, tp=None, tag=None):
            return self._runner.order(-1, size, limit, stop, sl, tp, tag)

        @property
        def equity(self):
            return self._runner.ctx.broker.equity()

        @property
        def trades(self):
            return tuple(_BpyTrade(t, self._runner) for t in self._runner.ctx.broker.open)

        @property
        def closed_trades(self):
            return tuple(_BpyTrade(t, self._runner) for t in self._runner.ctx.broker.closed)

        @property
        def orders(self):
            return tuple(self._runner.ctx.broker.pending)

    return Strategy


def bpy_params(cls) -> dict:
    out = {}
    for klass in reversed(cls.__mro__):
        for k, v in vars(klass).items():
            if not k.startswith("_") and isinstance(v, (int, float, bool)) and not callable(v):
                out[k] = v
    return out


class BpyRunner:
    def __init__(self, cls, ctx: RunContext, params: dict):
        self.ctx = ctx
        self.visible: int | None = None
        merged = bpy_params(cls)
        for k, v in params.items():
            if k in merged or hasattr(cls, k):
                merged[k] = v
        self.strategy = cls.__new__(cls)
        self.strategy._runner = self
        for k, v in merged.items():
            setattr(self.strategy, k, v)
        self.strategy.data = _BpyData(self)
        self.strategy.position = _BpyPosition(self)
        self.min_bar = 0
        self._plots: list[tuple[str, np.ndarray, bool | None]] = []

    def register_plot(self, name, arr, overlay):
        self._plots.append((name, arr, overlay))

    def init(self):
        self.visible = None
        self.strategy.init()
        # backtesting.py skips bars until every indicator has a value
        start = 0
        for _, arr, _ in self._plots:
            finite = np.where(np.isfinite(arr))[0]
            if len(finite):
                start = max(start, int(finite[0]))
        self.min_bar = start
        close = self.ctx.bars.close
        for name, arr, overlay in self._plots:
            if overlay is None:
                with np.errstate(all="ignore"):
                    rel = np.nanmean(np.abs(arr / close - 1)) if np.isfinite(arr).any() else 1
                overlay = bool(rel < 0.25)
            from ..core.engine import Plot
            self.ctx.plots[name] = Plot(name, [float(v) if np.isfinite(v) else None for v in arr], overlay)

    def step(self):
        i = self.ctx.i
        if i < self.min_bar:
            return
        self.visible = i + 1
        self.strategy.next()

    def order(self, side, size, limit, stop, sl, tp, tag):
        ctx = self.ctx
        qty = _qty_from_size(ctx, size)
        tag = str(tag) if tag is not None else ("long" if side > 0 else "short")
        if limit is not None or stop is not None:
            kind = "limit" if limit is not None else "stop"
            price = limit if limit is not None else stop
            return ctx.broker.submit_pending(kind, side, float(price), qty, tag=tag, sl=sl, tp=tp,
                                             reason=f"{'buy' if side > 0 else 'sell'}({kind}={price:.6g})")
        reason = f"self.{'buy' if side > 0 else 'sell'}()"
        ctx.log("signal", reason)
        # backtesting.py: an opposite order closes existing trades FIFO before opening
        return ctx.broker.submit_market(side, qty, tag=tag, sl=sl, tp=tp, reason=reason)


def _lib_crossover(series1, series2) -> bool:
    series1 = (series1.values if isinstance(series1, pd.Series) else
               (series1, series1) if isinstance(series1, Number) else series1)
    series2 = (series2.values if isinstance(series2, pd.Series) else
               (series2, series2) if isinstance(series2, Number) else series2)
    try:
        return bool(series1[-2] < series2[-2] and series1[-1] > series2[-1])
    except IndexError:
        return False


def _lib_cross(a, b) -> bool:
    return _lib_crossover(a, b) or _lib_crossover(b, a)


def _lib_barssince(condition, default=np.inf):
    return next(iter(np.where(np.asarray(condition)[::-1])[0]), default)


def _sma(values, n):
    return pd.Series(np.asarray(values, dtype=float)).rolling(n).mean().to_numpy()


def _unsupported(name):
    def f(*a, **k):
        raise UnsupportedFeature(f"{name} isn't supported in Tickbench's backtesting.py mode.",
                                 hint="Write the logic inside next() instead.")
    return f


# =============================================================================== backtrader
class Line:
    """A backtrader-style line: ``line[0]`` is the current bar, ``line[-1]`` the previous one."""

    def __init__(self, arr, runner: "BtrRunner", name: str = ""):
        self.array = np.asarray(arr, dtype=float)
        self._r = runner
        self.name = name

    def __getitem__(self, k: int) -> float:
        j = self._r.ctx.i + int(k)
        if j < 0 or j > self._r.ctx.i:
            return math.nan
        return float(self.array[j])

    def __call__(self, ago: int = 0):
        return self[ago]

    def __len__(self):
        return self._r.ctx.i + 1

    def get(self, ago=0, size=1):
        j = self._r.ctx.i + ago
        return list(self.array[max(0, j - size + 1): j + 1])

    def __bool__(self):
        v = self[0]
        return bool(v) and not math.isnan(v)

    def __float__(self):
        return self[0]

    def _binop(self, o, op):
        if self._r.stage == 1:
            other = o.array if isinstance(o, Line) else (o.lines0.array if hasattr(o, "lines0") else o)
            with np.errstate(all="ignore"):
                return Line(op(self.array, other).astype(float), self._r)
        other = o[0] if isinstance(o, (Line, _BtrIndicator)) else o
        return op(self[0], other)

    def __gt__(self, o): return self._binop(o, lambda a, b: a > b)
    def __lt__(self, o): return self._binop(o, lambda a, b: a < b)
    def __ge__(self, o): return self._binop(o, lambda a, b: a >= b)
    def __le__(self, o): return self._binop(o, lambda a, b: a <= b)
    def __add__(self, o): return self._binop(o, lambda a, b: a + b)
    def __sub__(self, o): return self._binop(o, lambda a, b: a - b)
    def __mul__(self, o): return self._binop(o, lambda a, b: a * b)
    def __truediv__(self, o): return self._binop(o, lambda a, b: a / b)
    def __radd__(self, o): return self._binop(o, lambda a, b: b + a)
    def __rsub__(self, o): return self._binop(o, lambda a, b: b - a)
    def __rmul__(self, o): return self._binop(o, lambda a, b: b * a)
    def __rtruediv__(self, o): return self._binop(o, lambda a, b: b / a)
    def __neg__(self): return self._binop(0, lambda a, b: -a)
    __hash__ = object.__hash__


class _Lines:
    def __init__(self, mapping: dict):
        self.__dict__.update(mapping)
        self._order = list(mapping)

    def __getitem__(self, k):
        return getattr(self, self._order[k])

    def __len__(self):
        return len(self._order)


class _BtrIndicator:
    """Indicator with named lines; delegates line behaviour to its first line."""

    alias_lines: tuple = ()

    def __init__(self, runner: "BtrRunner", lines: dict, plotname: str, overlay: bool):
        self._r = runner
        self.lines = _Lines(lines)
        for k, v in lines.items():
            setattr(self, k, v)
        self.lines0 = next(iter(lines.values()))
        for k, ln in lines.items():
            runner.register(f"{plotname}.{k}" if len(lines) > 1 else plotname, ln, overlay)

    def __getitem__(self, k): return self.lines0[k]
    def __call__(self, ago=0): return self.lines0[ago]
    def __len__(self): return len(self.lines0)
    def __bool__(self): return bool(self.lines0)
    def __float__(self): return float(self.lines0)
    def __gt__(self, o): return self.lines0 > o
    def __lt__(self, o): return self.lines0 < o
    def __ge__(self, o): return self.lines0 >= o
    def __le__(self, o): return self.lines0 <= o
    def __add__(self, o): return self.lines0 + o
    def __sub__(self, o): return self.lines0 - o
    def __mul__(self, o): return self.lines0 * o
    def __truediv__(self, o): return self.lines0 / o
    def __radd__(self, o): return o + self.lines0
    def __rsub__(self, o): return self.lines0.__rsub__(o)
    def __rmul__(self, o): return self.lines0.__rmul__(o)
    __hash__ = object.__hash__

    @property
    def array(self):
        return self.lines0.array


class _BtrData:
    def __init__(self, runner: "BtrRunner"):
        b = runner.ctx.bars
        self._r = runner
        self.open = Line(b.open, runner, "open")
        self.high = Line(b.high, runner, "high")
        self.low = Line(b.low, runner, "low")
        self.close = Line(b.close, runner, "close")
        self.volume = Line(b.volume, runner, "volume")
        self.openinterest = Line(np.zeros(len(b)), runner, "openinterest")
        self.datetime = _BtrDatetime(b.time, runner)
        self.lines = _Lines({"close": self.close, "low": self.low, "high": self.high, "open": self.open,
                             "volume": self.volume, "openinterest": self.openinterest})
        self.lines0 = self.close
        self._name = b.symbol

    def __getitem__(self, k): return self.close[k]
    def __len__(self): return self._r.ctx.i + 1
    def __float__(self): return self.close[0]
    def _getline(self): return self.close


class _BtrDatetime(Line):
    def __init__(self, times, runner):
        super().__init__(np.asarray(times, dtype=float), runner, "datetime")

    def datetime(self, ago=0):
        import datetime as _dt
        j = self._r.ctx.i + ago
        return _dt.datetime.fromtimestamp(self.array[j] / 1000, tz=_dt.timezone.utc).replace(tzinfo=None)

    def date(self, ago=0):
        return self.datetime(ago).date()

    def time(self, ago=0):
        return self.datetime(ago).time()


class _BtrPosition:
    def __init__(self, runner):
        self._r = runner

    @property
    def size(self):
        return self._r.ctx.broker.position_size

    @property
    def price(self):
        p = self._r.ctx.broker.position_avg_price
        return 0.0 if math.isnan(p) else p

    def __bool__(self):
        return self.size != 0

    def __len__(self):
        return int(abs(self.size) > 0)


class _BtrTrade:
    def __init__(self, t):
        self.ref = t.id
        self.size = t.qty * t.side
        self.price = t.entry_price
        self.pnl = (t.exit_price - t.entry_price) * t.side * t.qty if t.exit_price is not None else 0.0
        self.pnlcomm = t.pnl
        self.isclosed = not t.is_open
        self.isopen = t.is_open
        self.barlen = (t.exit_bar or t.entry_bar) - t.entry_bar
        self.commission = t.commission
        self.status = 2 if self.isclosed else 1


class _BtrOrder:
    Created, Submitted, Accepted, Partial, Completed, Canceled, Expired, Margin, Rejected = range(9)
    Market, Close, Limit, Stop, StopLimit, StopTrail, StopTrailLimit, Historical = range(8)
    Buy, Sell = 0, 1

    def __init__(self, o, side):
        self.ref = o.id if o else 0
        self.status = self.Accepted
        self.size = (o.qty or 0) * side if o else 0
        self._side = side
        self.executed = types.SimpleNamespace(price=math.nan, size=self.size, comm=0.0, value=0.0)

    def isbuy(self):
        return self._side > 0

    def issell(self):
        return self._side < 0

    def alive(self):
        return self.status in (self.Created, self.Submitted, self.Accepted, self.Partial)


def make_btr_module():
    m = types.ModuleType("backtrader")
    ind = types.ModuleType("backtrader.indicators")

    def _runner():
        r = BtrRunner.current
        if r is None:
            raise UnsupportedFeature("backtrader indicators must be created inside the strategy.")
        return r

    def _src(data, field_default="close"):
        if isinstance(data, _BtrData):
            return getattr(data, field_default).array
        if isinstance(data, (Line, _BtrIndicator)):
            return data.array
        if data is None:
            return getattr(_runner().data, field_default).array
        return np.asarray(data, dtype=float)

    def _ind_factory(name, compute, lines, overlay, defaults):
        class _I(_BtrIndicator):
            params = defaults

            def __init__(self, *datas, **kw):
                r = _runner()
                p = dict(defaults)
                p.update({k: v for k, v in kw.items() if k in defaults})
                self.p = self.params = types.SimpleNamespace(**p)
                arrays = compute(r, list(datas), p)
                super().__init__(r, {ln: Line(a, r, ln) for ln, a in zip(lines, arrays)},
                                 f"{name}({','.join(str(v) for v in p.values())})", overlay)
        _I.__name__ = name
        return _I

    def _first(r, datas):
        return datas[0] if datas else r.data

    SMA = _ind_factory("SMA", lambda r, d, p: [ta.sma(_src(_first(r, d)), p["period"])], ["sma"], True, {"period": 30})
    EMA = _ind_factory("EMA", lambda r, d, p: [ta.ema(_src(_first(r, d)), p["period"])], ["ema"], True, {"period": 30})
    WMA = _ind_factory("WMA", lambda r, d, p: [ta.wma(_src(_first(r, d)), p["period"])], ["wma"], True, {"period": 30})
    SMMA = _ind_factory("SMMA", lambda r, d, p: [ta.rma(_src(_first(r, d)), p["period"])], ["smma"], True, {"period": 30})
    RSI = _ind_factory("RSI", lambda r, d, p: [ta.rsi(_src(_first(r, d)), p["period"])], ["rsi"], False,
                       {"period": 14, "upperband": 70.0, "lowerband": 30.0})

    def _atr(r, d, p):
        data = _first(r, d)
        data = data if isinstance(data, _BtrData) else r.data
        return [ta.atr(data.high.array, data.low.array, data.close.array, p["period"])]
    ATR = _ind_factory("ATR", _atr, ["atr"], False, {"period": 14})
    StdDev = _ind_factory("StdDev", lambda r, d, p: [ta.stdev(_src(_first(r, d)), p["period"])], ["stddev"], False, {"period": 20})
    Highest = _ind_factory("Highest", lambda r, d, p: [ta.highest(_src(_first(r, d), "high"), p["period"])], ["highest"], True, {"period": 30})
    Lowest = _ind_factory("Lowest", lambda r, d, p: [ta.lowest(_src(_first(r, d), "low"), p["period"])], ["lowest"], True, {"period": 30})
    BB = _ind_factory("BollingerBands", lambda r, d, p: list(ta.bbands(_src(_first(r, d)), p["period"], p["devfactor"])),
                      ["mid", "top", "bot"], True, {"period": 20, "devfactor": 2.0})
    MACD = _ind_factory("MACD", lambda r, d, p: list(ta.macd(_src(_first(r, d)), p["period_me1"], p["period_me2"], p["period_signal"]))[:2],
                        ["macd", "signal"], False, {"period_me1": 12, "period_me2": 26, "period_signal": 9})
    MACDHisto = _ind_factory("MACDHisto", lambda r, d, p: list(ta.macd(_src(_first(r, d)), p["period_me1"], p["period_me2"], p["period_signal"])),
                             ["macd", "signal", "histo"], False, {"period_me1": 12, "period_me2": 26, "period_signal": 9})

    def _cross(r, d, p):
        a, b = _src(d[0]), _src(d[1]) if not isinstance(d[1], Number) else np.full(len(r.ctx.bars), float(d[1]))
        up, dn = ta.crossover(a, b), ta.crossunder(a, b)
        return [up.astype(float) - dn.astype(float)]
    CrossOver = _ind_factory("CrossOver", _cross, ["crossover"], False, {})

    def _stoch(r, d, p):
        data = _first(r, d)
        k = ta.run(ta.Stoch(p["period"]), data.close.array, data.high.array, data.low.array)
        kf = ta.sma(k, p["period_dfast"])
        return [kf, ta.sma(kf, p["period_dslow"])]
    Stochastic = _ind_factory("Stochastic", _stoch, ["percK", "percD"], False,
                              {"period": 14, "period_dfast": 3, "period_dslow": 3})
    def _cci(r, d, p):
        data = _first(r, d)
        return [ta.cci((data.high.array + data.low.array + data.close.array) / 3, p["period"])]
    CCI = _ind_factory("CCI", _cci, ["cci"], False, {"period": 20})

    for alias, cls in {
        "SMA": SMA, "SimpleMovingAverage": SMA, "MovingAverageSimple": SMA, "MovAv": SMA,
        "EMA": EMA, "ExponentialMovingAverage": EMA, "MovingAverageExponential": EMA,
        "WMA": WMA, "WeightedMovingAverage": WMA, "SMMA": SMMA, "SmoothedMovingAverage": SMMA,
        "RSI": RSI, "RelativeStrengthIndex": RSI, "RSI_SMA": RSI, "RSI_Safe": RSI,
        "ATR": ATR, "AverageTrueRange": ATR, "StdDev": StdDev, "StandardDeviation": StdDev,
        "Highest": Highest, "MaxN": Highest, "Lowest": Lowest, "MinN": Lowest,
        "BollingerBands": BB, "BBands": BB, "MACD": MACD, "MACDHisto": MACDHisto,
        "CrossOver": CrossOver, "Stochastic": Stochastic, "StochasticSlow": Stochastic,
        "CCI": CCI, "CommodityChannelIndex": CCI,
    }.items():
        setattr(ind, alias, cls)
    ind.MovAv = types.SimpleNamespace(SMA=SMA, Simple=SMA, EMA=EMA, Exponential=EMA, WMA=WMA, SMMA=SMMA)

    class Strategy:
        params: Any = ()

        def __init__(self):
            pass

        def next(self):
            pass

        def prenext(self):
            pass

        def nextstart(self):
            self.next()

        def start(self):
            pass

        def stop(self):
            pass

        def notify_order(self, order):
            pass

        def notify_trade(self, trade):
            pass

        def log(self, txt, dt=None):
            print(txt)

        def buy(self, data=None, size=None, price=None, exectype=None, **kw):
            return self._r.order(1, size, price, exectype)

        def sell(self, data=None, size=None, price=None, exectype=None, **kw):
            return self._r.order(-1, size, price, exectype)

        def close(self, data=None, size=None, **kw):
            b = self._r.ctx.broker
            if not b.open:
                return None
            self._r.ctx.log("signal", "self.close()")
            return _BtrOrder(b.submit_close(qty=size, reason="self.close()"), -1 if b.position_size > 0 else 1)

        def cancel(self, order):
            self._r.ctx.broker.cancel(order_id=getattr(order, "ref", None))

        def order_target_size(self, data=None, target=0, **kw):
            cur = self._r.ctx.broker.position_size
            diff = target - cur
            if diff > 0:
                return self.buy(size=diff)
            if diff < 0:
                return self.sell(size=-diff)
            return None

        def getposition(self, data=None, broker=None):
            return self.position

        def getsizing(self, data=None, isbuy=True):
            return self._r.default_size

        @property
        def position(self):
            return _BtrPosition(self._r)

        @property
        def broker(self):
            r = self._r
            return types.SimpleNamespace(getvalue=lambda *a, **k: r.ctx.broker.equity(),
                                         get_value=lambda *a, **k: r.ctx.broker.equity(),
                                         getcash=lambda: r.ctx.broker.cash, get_cash=lambda: r.ctx.broker.cash,
                                         getposition=lambda *a, **k: _BtrPosition(r))

    class Cerebro:  # module-level scripts often build a Cerebro; it is a no-op here
        def __init__(self, *a, **k):
            self.broker = types.SimpleNamespace(setcash=lambda *a, **k: None, setcommission=lambda *a, **k: None,
                                                getvalue=lambda: 0.0, set_coc=lambda *a, **k: None,
                                                set_slippage_perc=lambda *a, **k: None)

        def __getattr__(self, name):
            return lambda *a, **k: []

    feeds = types.ModuleType("backtrader.feeds")
    for n in ("YahooFinanceData", "YahooFinanceCSVData", "GenericCSVData", "PandasData", "BacktraderCSVData"):
        setattr(feeds, n, lambda *a, **k: None)
    analyzers = types.ModuleType("backtrader.analyzers")
    for n in ("SharpeRatio", "DrawDown", "TradeAnalyzer", "Returns", "SQN"):
        setattr(analyzers, n, type(n, (), {}))
    sizers = types.ModuleType("backtrader.sizers")
    for n in ("FixedSize", "PercentSizer", "AllInSizer"):
        setattr(sizers, n, type(n, (), {}))

    m.Strategy = Strategy
    m.Cerebro = Cerebro
    m.indicators = m.ind = ind
    m.feeds = feeds
    m.analyzers = analyzers
    m.sizers = sizers
    m.Order = _BtrOrder
    m.TimeFrame = types.SimpleNamespace(Minutes=4, Days=5, Weeks=6, Months=7)
    m.num2date = lambda x: x
    return m, ind, feeds, analyzers, sizers


def btr_params(cls) -> dict:
    out: dict = {}
    for klass in reversed(cls.__mro__):
        p = vars(klass).get("params")
        if isinstance(p, dict):
            out.update(p)
        elif isinstance(p, (tuple, list)):
            for item in p:
                if isinstance(item, (tuple, list)) and len(item) == 2:
                    out[item[0]] = item[1]
    return out


class BtrRunner:
    current: "BtrRunner | None" = None

    def __init__(self, cls, ctx: RunContext, params: dict, shim):
        self.ctx = ctx
        self.cls = cls
        self.stage = 1
        merged = btr_params(cls)
        merged.update({k: v for k, v in params.items() if k in merged})
        self.params = merged
        self.data = _BtrData(self)
        self._lines: list[tuple[str, Line, bool]] = []
        self.default_size = 1
        self.min_bar = 0
        self.started = False

    def register(self, name, line, overlay):
        self._lines.append((name, line, overlay))

    def init(self):
        BtrRunner.current = self
        s = self.cls.__new__(self.cls)
        s._r = self
        s.p = s.params = types.SimpleNamespace(**self.params)
        s.data = s.data0 = self.data
        s.datas = [self.data]
        s.datetime = self.data.datetime
        s.env = s.cerebro = None
        self.strategy = s
        self.ctx.broker.exit_hooks.append(lambda t: s.notify_trade(_BtrTrade(t)))
        try:
            self.cls.__init__(s)
            s.start()
        finally:
            BtrRunner.current = None
        start = 0
        for name, ln, overlay in self._lines:
            finite = np.where(np.isfinite(ln.array))[0]
            if len(finite):
                start = max(start, int(finite[0]))
            from ..core.engine import Plot
            self.ctx.plots[name] = Plot(name, [float(v) if np.isfinite(v) else None for v in ln.array], overlay)
        self.min_bar = start
        self.stage = 2

    def step(self):
        i = self.ctx.i
        if i < self.min_bar:
            self.strategy.prenext()
            return
        if not self.started:
            self.started = True
            self.strategy.nextstart()
            return
        self.strategy.next()

    def order(self, side, size, price, exectype):
        b = self.ctx.broker
        size = float(size) if size is not None else float(self.default_size)
        reason = f"self.{'buy' if side > 0 else 'sell'}(size={size:g})"
        if exectype in (_BtrOrder.Limit, _BtrOrder.Stop) and price is not None:
            kind = "limit" if exectype == _BtrOrder.Limit else "stop"
            return _BtrOrder(b.submit_pending(kind, side, float(price), size, reason=reason), side)
        self.ctx.log("signal", reason)
        pos = b.position_size
        # backtrader orders are netting: selling 1 while long 1 just goes flat
        if pos * side < 0:
            closing = min(abs(pos), size)
            o = b.submit_close(side=-side, qty=closing, reason=reason)
            rest = size - closing
            if rest > 1e-12:
                o = b.submit_market(side, rest, reason=reason)
            return _BtrOrder(o, side)
        return _BtrOrder(b.submit_market(side, size, reason=reason), side)


def make_modules() -> dict:
    bpy = types.ModuleType("backtesting")
    bpy.Strategy = make_bpy_strategy_base()

    class Backtest:  # scripts sometimes build one at module level; it does nothing here
        def __init__(self, *a, **k):
            pass

        def run(self, *a, **k):
            return {}

        def optimize(self, *a, **k):
            return {}

        def plot(self, *a, **k):
            return None
    bpy.Backtest = Backtest
    lib = types.ModuleType("backtesting.lib")
    lib.crossover = _lib_crossover
    lib.cross = _lib_cross
    lib.barssince = _lib_barssince
    lib.resample_apply = _unsupported("resample_apply")
    lib.SignalStrategy = bpy.Strategy
    lib.TrailingStrategy = bpy.Strategy
    test = types.ModuleType("backtesting.test")
    test.SMA = _sma
    test.GOOG = None
    test.EURUSD = None
    bpy.lib = lib
    bpy.test = test
    btr, ind, feeds, analyzers, sizers = make_btr_module()
    return {"backtesting": bpy, "backtesting.lib": lib, "backtesting.test": test, "backtrader": btr,
            "backtrader.indicators": ind, "backtrader.feeds": feeds, "backtrader.analyzers": analyzers,
            "backtrader.sizers": sizers}
