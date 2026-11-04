"""Script adapter: turns (almost) any user strategy script into something the Apollo engine can test.

The user's file is NEVER modified. It is hashed, copied to ~/.apollo-trading-hub/adapted/<hash>/, and loaded from
that copy inside a compatibility harness. The result is an `AdaptedStrategy` whose `.run(bars)` returns a target
position per bar (+ long / - short / 0 flat), plus a human-readable report of how the script was understood.

Recognised styles (auto-detected, first match wins):
  native_tick   generate_signals(secs, px, spread, events) -> [(entry_idx, side, exit_idx)]   (Apollo tick engine)
  vectorized    any of generate_signals/signals/signal/strategy/compute_signals/get_signals/run/apply/predict(df[, params])
                returning: Series/array/list of numbers or words (buy/sell/long/short/flat/close/hold),
                a DataFrame with signal|position|positions|target|side|direction column,
                entries/exits (+ short_entries/short_exits) columns or tuple  (vectorbt style),
                or the df itself with a new signal column added.
  event_class   a class with on_bar/next/on_candle/on_tick/on_data/handle_bar/onBar/OnTick (backtrader, backtesting.py,
                QuantConnect-ish, custom). Gets self.data/self.close[0]/self.close[-1], self.buy()/sell()/close(),
                self.position, self.I(fn, ...) (backtesting.py indicators) and may also *return* an action.
  event_func    module-level on_bar(bar[, ctx]) / next(bar) / on_tick(tick) / OnTick() returning an action.
  mql5          .mq5/.ex5 Expert Advisor -> executed by MetaTrader 5's own Strategy Tester (see mt5_tester.py).
Imports that only exist in other platforms (backtrader, backtesting, talib, MetaTrader5, pandas_ta, vectorbt...)
are satisfied with light shims when the real package is missing, so the script loads.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import re
import shutil
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

CACHE = Path.home() / ".apollo-trading-hub" / "adapted"
VECTOR_NAMES = ["generate_signals", "signals", "signal", "strategy", "compute_signals", "get_signals",
                "calculate_signals", "run_strategy", "run", "apply", "predict", "logic", "trade_logic"]
EVENT_METHODS = ["on_bar", "next", "on_candle", "on_data", "handle_bar", "onBar", "OnBar", "OnTick", "on_tick", "ontick", "handle_data"]
SIGNAL_COLS = ["signal", "signals", "position", "positions", "target", "target_position", "side", "direction", "pos", "trade"]
WORDS = {"buy": 1, "long": 1, "enter_long": 1, "go_long": 1, "b": 1, "sell": -1, "short": -1, "enter_short": -1,
         "go_short": -1, "s": -1, "flat": 0, "close": 0, "exit": 0, "close_all": 0, "flatten": 0}
HOLD = {"hold", "none", "wait", "", "nan", "keep", "stay"}


class AdapterError(ValueError):
    pass


@dataclass
class AdaptedStrategy:
    name: str
    source_path: str
    source_sha256: str
    style: str
    entrypoint: str
    report: list[str] = field(default_factory=list)
    _fn: Callable | None = None
    _cls: type | None = None
    _params: dict = field(default_factory=dict)
    module: Any = None

    # ---------- public ----------
    def run(self, bars: pd.DataFrame) -> np.ndarray:
        """Target position per bar (float; sign = direction, |v|<=1 = fraction of lot size, >1 = contracts)."""
        if self.style == "vectorized":
            return self._run_vector(bars)
        if self.style in ("event_class", "event_func"):
            return self._run_events(bars)
        if self.style == "mt5_python":
            return self._run_mt5(bars)
        if self.style == "pine":
            from .pine import PineRuntime
            rt = PineRuntime(self.module, self._params)
            out = rt.run(bars)
            self.report[:] = [r for r in self.report if not r.startswith(("inputs used", "pine notes", "pine: "))]
            self.report.append(f"inputs used: {rt.used_inputs}" if rt.used_inputs else "inputs used: none")
            notes = sorted(rt.strat.notes | rt.unsupported)
            if notes:
                self.report.append("pine notes: " + "; ".join(notes))
            if rt.meta["kind"] != "strategy":
                self.report.append("pine: script is an indicator (no strategy.* orders) -> flat; convert to strategy() to trade")
            return out
        if self.style == "freqtrade":
            return self._run_freqtrade(bars)
        if self.style == "quantconnect":
            return self._run_qc(bars)
        raise AdapterError(f"style {self.style} is not bar-driven")

    def lookahead_check(self, bars: pd.DataFrame, full: np.ndarray, samples: int = 4) -> list[int]:
        """Re-run on truncated history; a past signal that changes means the script peeks at future bars."""
        if self.style != "vectorized" or len(bars) < 200 or self.entrypoint.startswith(("trade_list", "signal_file")):
            return []  # external fixed signals/trades: nothing to peek at
        bad = []
        for cut in np.linspace(len(bars) * 0.3, len(bars) - 2, samples).astype(int):
            part = self.run(bars.iloc[: cut + 1])
            if not np.isclose(part[-1], full[cut], equal_nan=True):
                bad.append(int(cut))
        if bad:
            self.report.append(f"WARNING look-ahead bias: signals at bars {bad} change when future bars are removed. "
                               "Results are optimistic; fix shift(-n)/centered windows in the script.")
        else:
            self.report.append(f"look-ahead check passed ({samples} truncation points)")
        return bad

    def describe(self) -> dict:
        return {"name": self.name, "source_path": self.source_path, "source_sha256": self.source_sha256,
                "style": self.style, "entrypoint": self.entrypoint, "report": self.report}

    # ---------- vectorized ----------
    def _run_vector(self, bars: pd.DataFrame) -> np.ndarray:
        df = user_frame(bars)
        fn = self._fn
        sig = inspect.signature(fn)
        kwargs = {k: v for k, v in self._params.items() if k in sig.parameters}
        req = [p.name for p in sig.parameters.values() if p.default is p.empty
               and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.name not in kwargs]
        if req and all(r.lower() in df for r in req):      # e.g. signals(close, high)
            args = [df[r.lower()] for r in req]
        elif len(req) >= 2:                                # e.g. strategy(df, params)
            args = [df, dict(self._params)] + [None] * (len(req) - 2)
        else:
            args = [df] if req else []
        out = fn(*args, **kwargs) if args or not req else fn(df)
        return normalize_output(out, df, self.report)

    # ---------- event-driven ----------
    def _run_events(self, bars: pd.DataFrame) -> np.ndarray:
        df = user_frame(bars)
        ctx = EventContext(df)
        if self.style == "event_class":
            obj = _instantiate(self._cls, ctx, self._params)
            for hook in ("init", "start", "on_start", "OnInit", "initialize", "Initialize"):
                if hasattr(obj, hook) and callable(getattr(obj, hook)):
                    try:
                        getattr(obj, hook)()
                    except TypeError:
                        pass
            method = getattr(obj, self.entrypoint)
        else:
            method = self._fn
        nargs = len([p for p in inspect.signature(method).parameters.values() if p.default is p.empty])
        out = np.zeros(len(df))
        for i in range(len(df)):
            ctx.i = i
            bar = ctx.bar()
            r = method() if nargs == 0 else method(bar) if nargs == 1 else method(bar, ctx)
            ctx.apply(r)
            out[i] = ctx.position_target
        return out


    # ---------- Freqtrade IStrategy ----------
    def _run_freqtrade(self, bars: pd.DataFrame) -> np.ndarray:
        df = user_frame(bars).rename(columns={"time": "date"})
        obj = self._cls.__new__(self._cls)
        try:
            self._cls.__init__(obj, {})
        except TypeError:
            try:
                self._cls.__init__(obj)
            except Exception:
                pass
        meta = {"pair": "MGC/USD"}
        df = obj.populate_indicators(df, meta)
        if hasattr(obj, "populate_entry_trend"):
            df = obj.populate_entry_trend(df, meta); df = obj.populate_exit_trend(df, meta)
            cols = {"entries": "enter_long", "exits": "exit_long", "short_entries": "enter_short", "short_exits": "exit_short"}
        else:  # legacy freqtrade: populate_buy_trend / populate_sell_trend with 'buy'/'sell' columns
            df = obj.populate_buy_trend(df, meta); df = obj.populate_sell_trend(df, meta)
            cols = {"entries": "buy", "exits": "sell"}
        sig = pd.DataFrame({k: (df[v].fillna(0).astype(bool) if v in df else False) for k, v in cols.items()}, index=df.index)
        if not getattr(obj, "can_short", False):
            sig["short_entries"] = False
        roi = getattr(obj, "minimal_roi", None); sl = getattr(obj, "stoploss", None)
        if roi or sl:
            self.report.append(f"freqtrade minimal_roi/stoploss ({sl}) not simulated; exits come from exit signals")
        return normalize_output(sig, df, self.report)

    # ---------- QuantConnect / LEAN ----------
    def _run_qc(self, bars: pd.DataFrame) -> np.ndarray:
        df = user_frame(bars)
        ctx = EventContext(df)
        algo = self._cls.__new__(self._cls)
        _QCBase._bind(algo, ctx)
        for init in ("Initialize", "initialize"):
            if hasattr(algo, init):
                getattr(algo, init)(); break
        on = getattr(algo, "OnData", None) or getattr(algo, "on_data")
        out = np.zeros(len(df))
        for i in range(len(df)):
            ctx.i = i
            algo._qc_update()
            on(_QCSlice(algo, ctx))
            out[i] = ctx.position_target
        self.report.extend(sorted(algo._qc_notes))
        return out

    # ---------- MetaTrader5 python bot ----------
    def _run_mt5(self, bars: pd.DataFrame) -> np.ndarray:
        import time as real_time
        df = user_frame(bars)
        ctx = EventContext(df)
        sim = MT5Sim(ctx, self._params.get("symbol", "XAUUSD"))
        g = self.module.__dict__
        swapped = {}
        for k, v in list(g.items()):
            if isinstance(v, types.ModuleType) and v.__name__ == "MetaTrader5":
                swapped[k] = v; g[k] = sim
            elif v is real_time:
                swapped[k] = v; g[k] = _TimeProxy(real_time)
            elif k == "sleep" and v is real_time.sleep:
                swapped[k] = v; g[k] = _TimeProxy(real_time).sleep
        out = np.zeros(len(df))
        try:
            for i in range(len(df)):
                ctx.i = i
                try:
                    with_deadline(self._fn, 10, f"{self.entrypoint}() on bar {i}")
                except _NextBar:
                    pass
                out[i] = ctx.position_target
        finally:
            g.update(swapped)
        self.report.extend(sorted(sim.notes))
        return out


# ---------------- helpers ----------------
def user_frame(bars: pd.DataFrame) -> pd.DataFrame:
    """Give scripts the column spellings they usually expect."""
    df = bars.copy()
    for c in ("open", "high", "low", "close", "volume"):
        df[c.capitalize()] = df[c]
        df[c.upper()] = df[c]
    df["time"] = df.index
    df["Date"] = df.index
    df["tick_volume"] = df["volume"]
    return df


def _word(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float, np.integer, np.floating)):
        return None if np.isnan(v) else float(v)
    s = str(v).strip().lower()
    if s in HOLD:
        return None
    if s in WORDS:
        return float(WORDS[s])
    try:
        return float(s)
    except ValueError:
        raise AdapterError(f"unrecognised signal value {v!r}")


def normalize_output(out, df: pd.DataFrame, report: list[str]) -> np.ndarray:
    n = len(df)
    if isinstance(out, tuple) and len(out) in (2, 4) and all(hasattr(x, "__len__") for x in out):
        report.append("output: (entries, exits[, short_entries, short_exits]) tuple")
        names = ["entries", "exits", "short_entries", "short_exits"][: len(out)]
        out = pd.DataFrame(dict(zip(names, out)), index=df.index)
    if isinstance(out, pd.DataFrame):
        cols = {c.lower(): c for c in out.columns}
        if "entries" in cols or "long_entries" in cols or "buy" in cols:
            ent = out[cols.get("entries", cols.get("long_entries", cols.get("buy")))].fillna(False).astype(bool).to_numpy()
            ex = out[cols.get("exits", cols.get("long_exits", cols.get("sell", "")))] if ("exits" in cols or "long_exits" in cols or "sell" in cols) else None
            ex = ex.fillna(False).astype(bool).to_numpy() if ex is not None else np.zeros(n, bool)
            se = out[cols["short_entries"]].fillna(False).astype(bool).to_numpy() if "short_entries" in cols else np.zeros(n, bool)
            sx = out[cols["short_exits"]].fillna(False).astype(bool).to_numpy() if "short_exits" in cols else np.zeros(n, bool)
            report.append("output: entries/exits flags -> stateful position")
            pos, cur = np.zeros(n), 0.0
            for i in range(n):
                if cur > 0 and ex[i]: cur = 0.0
                if cur < 0 and sx[i]: cur = 0.0
                if ent[i]: cur = 1.0
                elif se[i]: cur = -1.0
                pos[i] = cur
            return pos
        col = next((cols[c] for c in SIGNAL_COLS if c in cols), None)
        if col is None:
            new = [c for c in out.columns if c not in df.columns]
            if len(new) == 1:
                col = new[0]
            else:
                raise AdapterError(f"returned DataFrame has no signal column (looked for {SIGNAL_COLS}; new columns: {new})")
        report.append(f"output: DataFrame column '{col}'")
        out = out[col]
    if isinstance(out, (list, np.ndarray, pd.Series)):
        s = pd.Series(list(out) if not isinstance(out, pd.Series) else out.to_numpy())
        if len(s) != n:
            raise AdapterError(f"signal length {len(s)} != bars {n}")
        vals = s.map(_word)
        if not report or not report[-1].startswith("output"):
            report.append("output: per-bar signal series")
        # 'hold'/NaN keeps previous position; values are targets
        return vals.ffill().fillna(0.0).to_numpy(dtype=float)
    raise AdapterError(f"unsupported return type {type(out).__name__}; return a Series/list/DataFrame of signals")


class _Line:
    """backtrader-style line: line[0] = current bar, line[-1] = previous; also behaves like an array."""
    def __init__(self, arr: np.ndarray, ctx: "EventContext"):
        self.arr, self.ctx = arr, ctx

    def __getitem__(self, k):
        if isinstance(k, slice):
            return self.arr[: self.ctx.i + 1][k]
        j = self.ctx.i + k if k <= 0 else k
        if j < 0 or j > self.ctx.i:
            raise IndexError("line index out of available history")
        return float(self.arr[j])

    def __len__(self): return self.ctx.i + 1
    def __float__(self): return float(self.arr[self.ctx.i])
    def __array__(self, dtype=None): return np.asarray(self.arr[: self.ctx.i + 1], dtype=dtype)
    def get(self, ago=0, size=1): return list(self.arr[max(0, self.ctx.i - ago - size + 1): self.ctx.i - ago + 1])
    @property
    def array(self): return self.arr[: self.ctx.i + 1]


class _CloseLine(_Line):
    """`self.close` is both the close-price line (self.close[0]) and the close-position verb (self.close())."""
    def __call__(self, *a, **k):
        self.ctx.close()


class EventContext:
    """What event-style scripts can touch: data lines, position, buy/sell/close, bar dict."""
    def __init__(self, df: pd.DataFrame):
        self.df, self.i = df, 0
        self.position_target = 0.0
        self.lines = {c: (_CloseLine if c == "close" else _Line)(df[c].to_numpy(dtype=float), self)
                      for c in ("open", "high", "low", "close", "volume")}
        self.history: list[dict] = []

    def bar(self) -> dict:
        r = self.df.iloc[self.i]
        b = {"time": self.df.index[self.i], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
             "volume": r["volume"], "index": self.i}
        b.update({k.capitalize(): v for k, v in list(b.items())})
        return _AttrDict(b)

    def apply(self, r) -> None:
        if r is None:
            return
        if isinstance(r, dict):
            r = r.get("action", r.get("signal", r.get("side")))
        v = _word(r)
        if v is not None:
            self.position_target = v

    # trading verbs
    def buy(self, size: float | None = None, *a, **k):
        self.position_target = (self.position_target if self.position_target > 0 else 0) + (size or 1) if size and size > 1 else 1.0
        return self.position_target

    def sell(self, size: float | None = None, *a, **k):
        if self.position_target > 0 and not k.get("short", False) and size is None:
            self.position_target = 0.0  # backtrader: sell closes a long
        else:
            self.position_target = -(size if size and size > 1 else 1.0)
        return self.position_target

    def close(self, *a, **k):
        self.position_target = 0.0

    @property
    def position(self):
        return _Pos(self.position_target, self)


class _Pos:
    def __init__(self, p, ctx=None): self.size = p; self.is_long = p > 0; self.is_short = p < 0; self._ctx = ctx
    def __bool__(self): return self.size != 0
    def __float__(self): return float(self.size)
    def __int__(self): return int(self.size)
    def __gt__(self, o): return self.size > o
    def __lt__(self, o): return self.size < o
    def __eq__(self, o): return self.size == o
    def close(self, *a, **k):
        if self._ctx: self._ctx.close()


class _AttrDict(dict):
    __getattr__ = dict.get


def _instantiate(cls: type, ctx: EventContext, params: dict):
    """Wire data/verbs onto the instance BEFORE the user's __init__ runs (backtrader reads self.data in __init__)."""
    try:
        obj = cls.__new__(cls)
    except TypeError as e:
        raise AdapterError(f"cannot construct {cls.__name__}: {e}")
    raw = getattr(cls, "params", ())
    p = dict(raw) if isinstance(raw, (tuple, list)) else dict(raw) if isinstance(raw, dict) else {}
    p.update({k: v for k, v in params.items() if k in p})
    for k, v in (("p", types.SimpleNamespace(**p)), ("params", types.SimpleNamespace(**p))):
        try:
            object.__setattr__(obj, k, v)
        except (AttributeError, TypeError):
            pass
    data = _Data(ctx)
    wiring = {"data": data, "data0": data, "datas": [data], "df": ctx.df, "buy": ctx.buy, "sell": ctx.sell,
              "close": ctx.lines["close"], "open": ctx.lines["open"], "high": ctx.lines["high"], "low": ctx.lines["low"],
              "volume": ctx.lines["volume"], "close_position": ctx.close, "flatten": ctx.close,
              "order_target": lambda t, *a, **k: setattr(ctx, "position_target", float(t)),
              "set_holdings": lambda *a, **k: setattr(ctx, "position_target", float(a[-1])),
              "I": lambda fn, *a, **k: _Indicator(fn, a, k, ctx)}
    for k, v in wiring.items():
        if k in cls.__dict__ and callable(cls.__dict__[k]):
            continue  # user defined their own method with this name; keep it
        try:
            object.__setattr__(obj, k, v)
        except (AttributeError, TypeError):
            pass
    try:
        obj.__class__ = type(f"Apollo{cls.__name__}", (cls,), {"position": property(lambda self: ctx.position)})
    except TypeError:
        pass
    init = cls.__dict__.get("__init__")
    if init is not None:
        sig = inspect.signature(init)
        kw = {k: v for k, v in params.items() if k in sig.parameters}
        try:
            init(obj, **kw)
        except TypeError as e:
            if "positional argument" not in str(e):
                raise
    return obj


class _Data:
    """self.data: .close/.Close lines, data['close'], data.df."""
    def __init__(self, ctx):
        self._ctx, self.df = ctx, ctx.df
        for c, ln in ctx.lines.items():
            setattr(self, c, ln); setattr(self, c.capitalize(), ln)
        self.datetime = self.index = ctx.df.index

    def __getitem__(self, k):
        return self._ctx.lines[k.lower()] if isinstance(k, str) else self._ctx.lines["close"][k]

    def __len__(self):
        return self._ctx.i + 1


class _Indicator:
    """backtesting.py self.I(fn, series, n): computed once over full history, indexed causally."""
    def __init__(self, fn, a, k, ctx):
        args = [x.arr if isinstance(x, _Line) else x.vals if isinstance(x, _Indicator) else x for x in a]
        self.vals = np.asarray(fn(*args, **k), dtype=float)
        self.ctx = ctx

    def __getitem__(self, k): return float(self.vals[self.ctx.i + k if k <= 0 else k])
    def __float__(self): return float(self.vals[self.ctx.i])
    def __array__(self, dtype=None): return self.vals[: self.ctx.i + 1]


# ---------------- import shims ----------------
def _shim_modules() -> dict[str, types.ModuleType]:
    shims = {}

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        m.__apollo_shim__ = True
        return m

    class _Strategy:  # backtrader.Strategy / backtesting.Strategy stand-in
        params: tuple | dict = ()
        def __init__(self, *a, **k):
            p = self.params if isinstance(self.params, dict) else dict(self.params or ())
            self.p = self.params_ns = types.SimpleNamespace(**{**p, **k})
        def log(self, *a, **k): pass

    bt = mod("backtrader", Strategy=_Strategy, Cerebro=object, indicators=mod("backtrader.indicators"),
             feeds=mod("backtrader.feeds"), analyzers=mod("backtrader.analyzers"), sizers=mod("backtrader.sizers"))
    ind = bt.indicators
    ind.SMA = ind.SimpleMovingAverage = lambda data, period=30, **k: _bt_ind(data, lambda a: pd.Series(a).rolling(period).mean().to_numpy())
    ind.EMA = ind.ExponentialMovingAverage = lambda data, period=30, **k: _bt_ind(data, lambda a: pd.Series(a).ewm(span=period, adjust=False).mean().to_numpy())
    ind.RSI = ind.RelativeStrengthIndex = lambda data, period=14, **k: _bt_ind(data, lambda a: _rsi(a, period))
    ind.CrossOver = lambda a, b: _bt_ind(a, lambda x: np.sign(np.nan_to_num(x - np.asarray(b.arr if hasattr(b, "arr") else b, float))) * 0, b=b, cross=True)
    bt.ind = ind
    shims["backtrader"] = bt
    shims["backtrader.indicators"] = ind
    shims["backtesting"] = mod("backtesting", Strategy=_Strategy, Backtest=object)
    shims["backtesting.lib"] = mod("backtesting.lib", crossover=lambda a, b: bool(len(np.asarray(a)) > 1 and np.asarray(a)[-2] < np.asarray(b)[-2] and np.asarray(a)[-1] > np.asarray(b)[-1]))
    class _IStrategy:
        INTERFACE_VERSION, can_short, minimal_roi, stoploss, timeframe = 3, False, {}, -1.0, "5m"
        def __init__(self, config=None): self.config = config or {}
    def _param(default=None, *a, **k):
        return types.SimpleNamespace(value=k.get("default", default if not isinstance(default, (list, tuple)) else default[0]))
    shims["freqtrade"] = mod("freqtrade")
    shims["freqtrade.strategy"] = mod("freqtrade.strategy", IStrategy=_IStrategy, IntParameter=lambda lo, hi, default=None, **k: types.SimpleNamespace(value=default),
                                      DecimalParameter=lambda lo, hi, default=None, **k: types.SimpleNamespace(value=default),
                                      CategoricalParameter=lambda cats, default=None, **k: types.SimpleNamespace(value=default),
                                      BooleanParameter=lambda default=None, **k: types.SimpleNamespace(value=default),
                                      merge_informative_pair=lambda df, *a, **k: df, informative=lambda *a, **k: (lambda f: f))
    shims["freqtrade.strategy.interface"] = shims["freqtrade.strategy"]
    shims["freqtrade.vendor"] = mod("freqtrade.vendor")
    shims["freqtrade.vendor.qtpylib"] = mod("freqtrade.vendor.qtpylib")
    shims["freqtrade.vendor.qtpylib.indicators"] = qtl = mod("freqtrade.vendor.qtpylib.indicators",
        crossed_above=lambda a, b: (a > b) & (a.shift(1) <= (b.shift(1) if hasattr(b, "shift") else b)),
        crossed_below=lambda a, b: (a < b) & (a.shift(1) >= (b.shift(1) if hasattr(b, "shift") else b)),
        typical_price=lambda df: (df["high"] + df["low"] + df["close"]) / 3,
        bollinger_bands=lambda s, window=20, stds=2: pd.DataFrame({"mid": s.rolling(window).mean(),
            "upper": s.rolling(window).mean() + stds * s.rolling(window).std(), "lower": s.rolling(window).mean() - stds * s.rolling(window).std()}))
    class _QCAlgorithm:
        pass
    qc = mod("AlgorithmImports", QCAlgorithm=_QCAlgorithm, Resolution=types.SimpleNamespace(Minute="Minute", Hour="Hour", Daily="Daily", Second="Second", Tick="Tick"),
             Market=types.SimpleNamespace(), MovingAverageType=types.SimpleNamespace(Simple="Simple", Exponential="Exponential"),
             BrokerageName=types.SimpleNamespace(), AccountType=types.SimpleNamespace(), Futures=types.SimpleNamespace(),
             Symbol=types.SimpleNamespace, TradeBar=object, Slice=object, Chart=object, Series=object)
    shims["AlgorithmImports"] = qc
    shims["QuantConnect"] = mod("QuantConnect", **{k: v for k, v in vars(qc).items() if not k.startswith("__")})
    shims["QuantConnect.Algorithm"] = mod("QuantConnect.Algorithm", QCAlgorithm=_QCAlgorithm)
    consts = {k: v for k, v in vars(MT5Sim).items() if k.isupper()}
    shims["MetaTrader5"] = mod("MetaTrader5", initialize=lambda *a, **k: True, shutdown=lambda: None,
                               login=lambda *a, **k: True, last_error=lambda: (1, "Success"), **consts)
    return shims


def _bt_ind(data, fn, b=None, cross=False):
    src = data.arr if isinstance(data, _Line) else np.asarray(data, float)
    if cross:
        other = b.arr if isinstance(b, _Line) else np.asarray(getattr(b, "vals", b), float)
        diff = np.sign(src - other)
        vals = np.r_[0, np.where((diff[1:] != diff[:-1]) & (diff[1:] != 0), diff[1:], 0)]
    else:
        vals = fn(src)
    ctx = data.ctx if isinstance(data, _Line) else None
    ln = _Line(np.asarray(vals, float), ctx) if ctx else vals
    return ln


def _rsi(a, n):
    d = np.diff(a, prepend=a[0])
    up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()


# ---------------- safety ----------------
class ScriptTimeout(AdapterError):
    pass


def with_deadline(fn, seconds: float, what: str):
    """Run fn() but abort if the script loops forever (works in worker threads, unlike signal.alarm)."""
    import time as _t
    end = _t.monotonic() + seconds
    def tracer(frame, event, arg):
        if _t.monotonic() > end:
            raise ScriptTimeout(f"{what} exceeded {seconds:.0f}s (infinite loop at import/top level? "
                                "put live-trading loops under `if __name__ == '__main__':`)")
        return tracer
    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        return fn()
    finally:
        sys.settrace(old)


# ---------------- MetaTrader5 python-bot harness ----------------
class _NextBar(Exception):
    """Raised from the bot's time.sleep(): one loop iteration == one bar."""


class _NS(types.SimpleNamespace):
    def _asdict(self): return dict(self.__dict__)


class MT5Sim:
    """Drop-in for the MetaTrader5 module during a backtest: serves history up to the current bar,
    records order_send as position changes. No connection to any real terminal."""
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 5, 15, 30
    TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = 16385, 16388, 16408
    ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT = 0, 1, 2, 3
    TRADE_ACTION_DEAL, TRADE_ACTION_PENDING, TRADE_ACTION_SLTP, TRADE_ACTION_REMOVE = 1, 5, 6, 8
    TRADE_RETCODE_DONE, ORDER_TIME_GTC, ORDER_TIME_DAY = 10009, 0, 1
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    POSITION_TYPE_BUY, POSITION_TYPE_SELL, COPY_TICKS_ALL = 0, 1, -1

    def __init__(self, ctx: "EventContext", symbol: str = "XAUUSD"):
        self.ctx, self.symbol, self.notes = ctx, symbol, set()
        self.lots = 0.0

    def initialize(self, *a, **k): return True
    def login(self, *a, **k): return True
    def shutdown(self): return None
    def last_error(self): return (1, "Success")
    def symbol_select(self, *a, **k): return True
    def version(self): return (500, 0, "apollo-sim")
    def terminal_info(self): return _NS(connected=True, trade_allowed=True, name="Apollo backtest")

    def _bar(self, j=None):
        j = self.ctx.i if j is None else j
        r = self.ctx.df.iloc[j]
        return r, int(self.ctx.df.index[j].timestamp())

    def symbol_info_tick(self, symbol=None):
        r, t = self._bar()
        sp = float(r.get("spread", 0.1) or 0.1) if hasattr(r, "get") else 0.1
        return _NS(time=t, bid=r["close"] - sp / 2, ask=r["close"] + sp / 2, last=r["close"], volume=1, time_msc=t * 1000)

    def symbol_info(self, symbol=None):
        tk = self.symbol_info_tick()
        return _NS(name=symbol or self.symbol, point=0.01, digits=2, trade_tick_size=0.01, trade_tick_value=1.0,
                   trade_contract_size=100.0, volume_min=0.01, volume_max=100.0, volume_step=0.01, visible=True,
                   bid=tk.bid, ask=tk.ask, spread=int(round((tk.ask - tk.bid) / 0.01)), filling_mode=3, trade_stops_level=0)

    def account_info(self):
        return _NS(balance=150000.0, equity=150000.0, margin_free=150000.0, currency="USD", leverage=100, login=0, server="apollo-sim")

    def _rates(self, count, end=None):
        end = self.ctx.i if end is None else end
        lo = max(0, end - int(count) + 1)
        d = self.ctx.df.iloc[lo:end + 1]
        arr = np.zeros(len(d), dtype=[("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
                                      ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")])
        arr["time"] = d.index.view("int64") // 10**9
        for c in ("open", "high", "low", "close"):
            arr[c] = d[c].to_numpy()
        arr["tick_volume"] = d["volume"].to_numpy()
        arr["spread"] = np.nan_to_num(d["spread"].to_numpy() / 0.01) if "spread" in d else 0
        return arr

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self._tf(timeframe)
        return self._rates(count, self.ctx.i - int(start_pos))

    def copy_rates_from(self, symbol, timeframe, date_from, count):
        self._tf(timeframe)
        return self._rates(count)

    def copy_rates_range(self, symbol, timeframe, date_from, date_to):
        self._tf(timeframe)
        ts = pd.Timestamp(date_from).tz_localize("UTC") if pd.Timestamp(date_from).tzinfo is None else pd.Timestamp(date_from)
        start = int(np.searchsorted(self.ctx.df.index, ts))
        return self._rates(self.ctx.i - start + 1)

    def _tf(self, tf):
        self.notes.add(f"bot requests timeframe {tf}; served the backtest's bar size")

    def positions_get(self, *a, **k):
        p = self.ctx.position_target
        if not p:
            return ()
        r, t = self._bar()
        return (_NS(ticket=1, symbol=self.symbol, type=0 if p > 0 else 1, volume=self.lots or 1.0, price_open=r["close"],
                    price_current=r["close"], profit=0.0, sl=0.0, tp=0.0, magic=k.get("magic", 0), time=t),)

    def positions_total(self): return len(self.positions_get())
    def orders_get(self, *a, **k): return ()
    def orders_total(self): return 0
    def history_deals_get(self, *a, **k): return ()

    def order_check(self, request): return _NS(retcode=0, comment="ok")

    def order_send(self, request):
        req = dict(request)
        if req.get("action", 1) != self.TRADE_ACTION_DEAL:
            self.notes.add("pending/SLTP orders are ignored; only market deals are simulated")
            return _NS(retcode=self.TRADE_RETCODE_DONE, order=0, deal=0, comment="ignored by apollo-sim", request=req)
        side = 1 if req.get("type", 0) == self.ORDER_TYPE_BUY else -1
        cur = self.ctx.position_target
        if req.get("position") or (cur and np.sign(cur) != side):
            self.ctx.position_target = 0.0  # closing deal
        else:
            self.ctx.position_target = float(side)
            self.lots = float(req.get("volume", 1.0))
        return _NS(retcode=self.TRADE_RETCODE_DONE, order=1, deal=1, volume=req.get("volume"), price=self.symbol_info_tick().last,
                   comment="apollo-sim", request=req)


class _QCIndicator:
    def __init__(self, kind, n, ctx):
        self.kind, self.n, self.ctx, self.vals = kind, int(n), ctx, []
        self.Current = types.SimpleNamespace(Value=0.0)
        self.IsReady = False

    def _update(self):
        c = self.ctx.df["close"].to_numpy()[: self.ctx.i + 1]
        if self.kind == "SMA":
            v = c[-self.n:].mean() if len(c) >= self.n else np.nan
        elif self.kind == "EMA":
            v = pd.Series(c).ewm(span=self.n, adjust=False).mean().iloc[-1] if len(c) >= self.n else np.nan
        else:  # RSI
            v = _rsi(c, self.n)[-1] if len(c) > self.n else np.nan
        self.IsReady = not np.isnan(v)
        self.Current.Value = float(v) if self.IsReady else 0.0

    def __float__(self): return self.Current.Value
    @property
    def current(self): return self.Current
    @property
    def is_ready(self): return self.IsReady


class _QCSymbolData(dict):
    pass


class _QCSlice:
    def __init__(self, algo, ctx):
        r = ctx.df.iloc[ctx.i]
        bar = types.SimpleNamespace(Open=r["open"], High=r["high"], Low=r["low"], Close=r["close"], Volume=r["volume"],
                                    Price=r["close"], EndTime=ctx.df.index[ctx.i], Time=ctx.df.index[ctx.i])
        for k in list(vars(bar)):
            setattr(bar, k.lower(), getattr(bar, k))
        self._bar, self.Bars = bar, {s: bar for s in algo._qc_symbols}
        self.bars = self.Bars

    def __getitem__(self, k): return self._bar
    def __contains__(self, k): return True
    def ContainsKey(self, k): return True
    def contains_key(self, k): return True


class _QCBase:
    """Methods injected into a QCAlgorithm subclass instance."""
    @staticmethod
    def _bind(a, ctx):
        a._qc_ctx, a._qc_symbols, a._qc_inds, a._qc_notes = ctx, [], [], set()
        noop = lambda *x, **k: None
        def add(ticker, *x, **k):
            sym = types.SimpleNamespace(Symbol=str(ticker), symbol=str(ticker), Value=str(ticker))
            a._qc_symbols.append(str(ticker)); return sym
        def ind(kind):
            def make(sym, n, *x, **k):
                i = _QCIndicator(kind, n, ctx); a._qc_inds.append(i); return i
            return make
        def holdings(sym, pct, *x, **k):
            ctx.position_target = float(np.sign(pct)) if abs(pct) <= 1 else float(pct)
        def liquidate(*x, **k):
            ctx.position_target = 0.0
        def mo(sym, qty, *x, **k):
            ctx.position_target = 0.0 if np.sign(qty) == -np.sign(ctx.position_target) and ctx.position_target else float(np.sign(qty))
        class Port(dict):
            def __getitem__(self_, k):
                p = ctx.position_target
                return types.SimpleNamespace(Invested=p != 0, invested=p != 0, Quantity=p, quantity=p, IsLong=p > 0, IsShort=p < 0,
                                             is_long=p > 0, is_short=p < 0)
            @property
            def Invested(self_): return ctx.position_target != 0
        def secs():
            class S(dict):
                def __getitem__(self_, k):
                    c = ctx.df["close"].iloc[ctx.i]; return types.SimpleNamespace(Price=c, price=c, Close=c, close=c)
            return S()
        def hist(sym, n, *x, **k):
            d = ctx.df.iloc[max(0, ctx.i - int(n) + 1): ctx.i + 1]
            return d[["open", "high", "low", "close", "volume"]]
        api = {"SetStartDate": noop, "SetEndDate": noop, "SetCash": noop, "SetWarmUp": noop, "SetBenchmark": noop,
               "SetBrokerageModel": noop, "Debug": noop, "Log": noop, "Plot": noop, "SetTimeZone": noop,
               "AddEquity": add, "AddForex": add, "AddCfd": add, "AddFuture": add, "AddCrypto": add, "AddSecurity": add,
               "SMA": ind("SMA"), "EMA": ind("EMA"), "RSI": ind("RSI"),
               "SetHoldings": holdings, "Liquidate": liquidate, "MarketOrder": mo, "History": hist,
               "Portfolio": Port(), "Securities": secs(), "IsWarmingUp": False, "Time": None}
        api.update({"set_start_date": noop, "set_end_date": noop, "set_cash": noop, "set_warm_up": noop, "debug": noop, "log": noop,
                    "plot": noop, "add_equity": add, "add_forex": add, "add_cfd": add, "add_future": add, "add_crypto": add,
                    "sma": ind("SMA"), "ema": ind("EMA"), "rsi": ind("RSI"), "set_holdings": holdings, "liquidate": liquidate,
                    "market_order": mo, "history": hist, "portfolio": api["Portfolio"], "securities": api["Securities"],
                    "is_warming_up": False})
        for k, v in api.items():
            object.__setattr__(a, k, v)
        def upd():
            for i in a._qc_inds:
                i._update()
            object.__setattr__(a, "Time", ctx.df.index[ctx.i]); object.__setattr__(a, "time", ctx.df.index[ctx.i])
        object.__setattr__(a, "_qc_update", upd)


class _TimeProxy:
    def __init__(self, real): self._real = real
    def sleep(self, *_): raise _NextBar()
    def __getattr__(self, k): return getattr(self._real, k)


# ---------------- loader ----------------
def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adapt(path: str | Path, params: dict | None = None) -> AdaptedStrategy:
    src = Path(path).expanduser().resolve()
    if not src.exists():
        raise AdapterError(f"script not found: {src}")
    digest = sha256(src)
    ext = src.suffix.lower()
    if ext in (".mq5", ".ex5", ".mq4", ".ex4"):
        if ext in (".mq4", ".ex4"):
            raise AdapterError("MQL4 (MT4) EAs can't run in MT5's tester; recompile as .mq5 or export signals to CSV")
        return AdaptedStrategy(src.stem, str(src), digest, "mql5", "OnTick",
                               ["MQL5 Expert Advisor: executed by the MetaTrader 5 Strategy Tester on a copy; "
                                "deals are then replayed through Apollo's LucidFlex rules"])
    if ext in (".pine", ".pinescript") or (ext == ".txt" and re.search(r"//\s*@version|\b(strategy|indicator|study)\s*\(", src.read_text(errors="replace")[:4000])):
        return _pine(src, digest, params)
    if ext in (".csv", ".tsv"):
        return _signal_file(src, digest)
    if ext == ".json":
        return _json_signals(src, digest)
    if ext in UNSUPPORTED:
        raise AdapterError(UNSUPPORTED[ext])
    if ext not in (".py", ".ipynb"):
        raise AdapterError(f"unsupported script type {ext}; supported: {', '.join(SUPPORTED_EXTS)}")

    work = CACHE / digest[:16]
    work.mkdir(parents=True, exist_ok=True)
    copy = work / src.name
    if ext == ".ipynb":  # notebook -> code cells (magics/shell lines dropped) into the harness copy
        import json as _json
        nb = _json.loads(src.read_text())
        cells = ["".join(c["source"]) if isinstance(c["source"], list) else c["source"] for c in nb.get("cells", []) if c.get("cell_type") == "code"]
        code = "\n\n".join("\n".join(ln for ln in c.splitlines() if not ln.lstrip().startswith(("%", "!"))) for c in cells)
        copy = work / (src.stem + ".py")
        copy.write_text(code)
    elif not copy.exists():
        shutil.copy2(src, copy)  # the harness only ever touches this copy
    report = [f"source untouched: {src} (sha256 {digest[:12]}…); harness copy {copy}"]
    text = copy.read_text(errors="replace")

    shims = {}
    for name, m in _shim_modules().items():
        root = name.split(".")[0]
        if re.search(rf"^\s*(import|from)\s+{re.escape(root)}\b", text, re.M) and importlib.util.find_spec(root) is None:
            shims[name] = m
    if shims:
        report.append(f"shimmed missing platform imports: {sorted({k.split('.')[0] for k in shims})}")
    for missing in ("talib", "pandas_ta", "ta"):
        if re.search(rf"^\s*(import|from)\s+{missing}\b", text, re.M) and importlib.util.find_spec(missing) is None:
            raise AdapterError(f"script imports '{missing}' which is not installed. Install it (pip install {missing if missing != 'talib' else 'TA-Lib'}) or replace with pandas math.")

    saved = {k: sys.modules.get(k) for k in shims}
    sys.modules.update(shims)
    old_path = list(sys.path)
    sys.path.insert(0, str(src.parent))  # let the script import its own sibling modules (read-only)
    try:
        spec = importlib.util.spec_from_file_location(f"apollo_user_{digest[:12]}", copy)
        module = importlib.util.module_from_spec(spec)
        try:
            with_deadline(lambda: spec.loader.exec_module(module), 20, "loading the script")  # type: ignore[union-attr]
        except SystemExit:
            report.append("script called exit() at import time; ignored")
        except Exception as e:
            raise AdapterError(f"script failed to load: {type(e).__name__}: {e}") from e
    finally:
        sys.path[:] = old_path
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    p = dict(getattr(module, "PARAMS", {}) or getattr(module, "params", {}) or {}) if isinstance(getattr(module, "PARAMS", getattr(module, "params", {})), dict) else {}
    p.update(params or {})
    st = AdaptedStrategy(src.stem, str(src), digest, "", "", report, _params=p, module=module)

    for name, obj in vars(module).items():
        if inspect.isclass(obj) and obj.__module__ == module.__name__ and callable(getattr(obj, "populate_indicators", None)):
            st.style, st.entrypoint, st._cls = "freqtrade", f"{name}.populate_*", obj
            report.append(f"detected Freqtrade strategy {name}: populate_indicators -> entry/exit trend columns")
            return st
        if inspect.isclass(obj) and obj.__module__ == module.__name__ and (callable(getattr(obj, "OnData", None)) or callable(getattr(obj, "on_data", None))) \
                and (callable(getattr(obj, "Initialize", None)) or callable(getattr(obj, "initialize", None))):
            st.style, st.entrypoint, st._cls = "quantconnect", f"{name}.OnData", obj
            report.append(f"detected QuantConnect/LEAN algorithm {name}: Initialize() once, OnData() per bar "
                          "(SetHoldings/Liquidate/MarketOrder, Portfolio, SMA/EMA/RSI, History)")
            return st
    f = getattr(module, "generate_signals", None)
    if callable(f) and len(inspect.signature(f).parameters) == 4:
        st.style, st.entrypoint, st._fn = "native_tick", "generate_signals", f
        report.append("detected Apollo native tick strategy generate_signals(secs, px, spread, events)")
        return st
    if re.search(r"\border_send\s*\(", text) and re.search(r"^\s*(import|from)\s+MetaTrader5\b", text, re.M):
        cands = ["main", "run", "start", "trade", "check_and_trade", "on_new_bar", "step", "run_once", "loop", "bot", "trading_loop"]
        fns = {n: o for n, o in vars(module).items() if inspect.isfunction(o) and o.__module__ == module.__name__}
        entry = next((n for n in cands if n in fns and not inspect.signature(fns[n]).parameters), None) \
            or next((n for n, o in fns.items() if "while" in inspect.getsource(o) and not inspect.signature(o).parameters), None) \
            or next((n for n, o in fns.items() if "order_send" in inspect.getsource(o) and not inspect.signature(o).parameters), None)
        if entry:
            st.style, st.entrypoint, st._fn = "mt5_python", entry, fns[entry]
            report.append(f"detected MetaTrader5 Python bot; {entry}() runs against a simulated MT5 (history up to the current bar, "
                          "order_send -> positions). Each time.sleep() in the loop = advance one bar.")
            return st
    for n in VECTOR_NAMES:
        f = getattr(module, n, None)
        if callable(f) and not inspect.isclass(f) and getattr(f, "__module__", None) == module.__name__:
            st.style, st.entrypoint, st._fn = "vectorized", n, f
            report.append(f"detected vectorized function {n}{inspect.signature(f)} -> called once on the full bar DataFrame")
            return st
    for name, obj in vars(module).items():
        if inspect.isclass(obj) and obj.__module__ == module.__name__:
            m = next((x for x in EVENT_METHODS if callable(getattr(obj, x, None))), None)
            if m:
                st.style, st.entrypoint, st._cls = "event_class", m, obj
                base = [b.__name__ for b in obj.__mro__[1:-1]]
                report.append(f"detected event-driven class {name}.{m}() (bases: {base or ['object']}); fed bar-by-bar with no look-ahead")
                return st
    for m in EVENT_METHODS:
        f = getattr(module, m, None)
        if callable(f):
            st.style, st.entrypoint, st._fn = "event_func", m, f
            report.append(f"detected module-level event function {m}(); fed bar-by-bar with no look-ahead")
            return st
    funcs = [n for n, o in vars(module).items() if inspect.isfunction(o) and o.__module__ == module.__name__]
    raise AdapterError("could not find a strategy entry point. Expected one of: "
                       f"{VECTOR_NAMES[:6]}… (df -> signals), a class with {EVENT_METHODS[:4]}…, "
                       f"or Apollo generate_signals(secs, px, spread, events). Functions found: {funcs}")


UNSUPPORTED = {
    ".cs": "NinjaScript (C#) needs NinjaTrader. Export Strategy Analyzer > Trades to CSV and backtest that file (trade lists are supported).",
    ".els": "EasyLanguage needs TradeStation. Export the Strategy Performance Report 'List of Trades' to CSV and backtest that.",
    ".eld": "EasyLanguage needs TradeStation. Export the 'List of Trades' to CSV and backtest that.",
    ".mq4": "MQL4 (MT4) can't run in MT5. Recompile as .mq5, or export the MT4 account history (trades) to CSV.",
    ".ex4": "MQL4 (MT4) can't run in MT5. Recompile as .mq5, or export the MT4 account history (trades) to CSV.",
    ".afl": "AmiBroker AFL needs AmiBroker. Export the backtest trade list to CSV and backtest that.",
    ".xlsx": "Save the sheet as CSV (File > Save As > CSV) and backtest the CSV.",
}
SUPPORTED_EXTS = [".py", ".ipynb", ".pine", ".mq5", ".ex5", ".csv", ".tsv", ".json"]


def _pine(src: Path, digest: str, params: dict | None) -> AdaptedStrategy:
    from .pine import PineError, compile_pine
    text = src.read_text(errors="replace")
    try:
        py, meta = compile_pine(text)
    except PineError as e:
        raise AdapterError(f"Pine: {e}") from e
    work = CACHE / digest[:16]
    work.mkdir(parents=True, exist_ok=True)
    (work / src.name).write_text(text)
    (work / (src.stem + "_transpiled.py")).write_text(py)  # inspectable translation; source file untouched
    return AdaptedStrategy(src.stem, str(src), digest, "pine", f"{meta['kind']}() v{meta['version']}",
                           [f"source untouched: {src} (sha256 {digest[:12]}…); transpiled copy {work / (src.stem + '_transpiled.py')}",
                            f"Pine v{meta['version']} {meta['kind']}: {meta['sites']} call sites, user functions {meta['user_functions'] or 'none'}; "
                            "runs bar-by-bar with Pine series semantics, orders fill next bar open"],
                           _params=dict(params or {}), module=text)


def _json_signals(src: Path, digest: str) -> AdaptedStrategy:
    import json as _json
    data = _json.loads(src.read_text())
    rows = data.get("signals", data.get("trades", data)) if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise AdapterError("JSON must be a list of {time, signal} objects (or {'signals': [...]})")
    tmp = CACHE / digest[:16]
    tmp.mkdir(parents=True, exist_ok=True)
    csv = tmp / (src.stem + ".csv")
    pd.DataFrame(rows).to_csv(csv, index=False)
    st = _signal_file(csv, digest)
    st.source_path = str(src)
    st.report.insert(0, "JSON signals converted to a harness CSV")
    return st


TRADE_COLS = {  # (entry time, exit time, side, qty) aliases across TradingView, NinjaTrader, TradeStation, MT4/MT5 exports
    "entry_time": ["entry time", "entry date", "open time", "entry date/time", "time open", "opentime"],
    "exit_time": ["exit time", "exit date", "close time", "exit date/time", "time close", "closetime"],
    "side": ["market pos.", "market position", "side", "direction", "type", "position"],
    "qty": ["qty", "quantity", "contracts", "volume", "size", "lots"],
}


def _trade_list(df: pd.DataFrame, src: Path, digest: str) -> AdaptedStrategy | None:
    cols = {c: c for c in df.columns}
    find = lambda key: next((cols[c] for c in cols if c in TRADE_COLS[key]), None)
    et, xt, sd = find("entry_time"), find("exit_time"), find("side")
    if et and xt and sd:
        trades = df[[et, xt, sd]].dropna()
    elif "trade #" in cols and "date/time" in cols and "type" in cols:
        # TradingView "List of trades": two rows per trade ("Entry Long"/"Exit Long")
        tv = df.copy()
        tv["kind"] = tv["type"].str.lower()
        ent = tv[tv["kind"].str.contains("entry")].set_index("trade #")
        ext = tv[tv["kind"].str.contains("exit")].set_index("trade #")
        trades = pd.DataFrame({"e": ent["date/time"], "x": ext["date/time"], "s": ent["kind"]}).dropna()
        et, xt, sd = "e", "x", "s"
    else:
        return None
    t_e = pd.to_datetime(trades[et]); t_x = pd.to_datetime(trades[xt])
    tz = lambda t: t.dt.tz_localize("America/New_York") if t.dt.tz is None else t
    t_e, t_x = tz(t_e).dt.tz_convert("UTC"), tz(t_x).dt.tz_convert("UTC")
    side = trades[sd].astype(str).str.lower().map(lambda v: -1.0 if any(w in v for w in ("short", "sell")) else 1.0)
    spans = list(zip(t_e, t_x, side))

    def fn(d):
        out = np.zeros(len(d))
        idx = d.index
        for a, b, s_ in spans:
            # decision bar = bar before entry so the engine's next-open fill lands on the entry bar
            i0 = max(0, idx.searchsorted(a) - 1); i1 = max(0, idx.searchsorted(b) - 1)
            out[i0:i1] = s_
        return out
    return AdaptedStrategy(src.stem, str(src), digest, "vectorized", "trade_list",
                           [f"trade list export: {len(spans)} trades re-simulated on bars with Apollo costs and LucidFlex rules "
                            f"(columns {et!r}/{xt!r}/{sd!r})"], _fn=fn)


def _signal_file(src: Path, digest: str) -> AdaptedStrategy:
    """A CSV of signals/trades (e.g. TradingView export): time + signal|position|side|action."""
    sig = pd.read_csv(src, sep=None, engine="python")
    sig.columns = [c.strip().lower() for c in sig.columns]
    tl = _trade_list(sig, src, digest)
    if tl:
        return tl
    tcol = next((c for c in ("time", "timestamp", "datetime", "date/time", "date") if c in sig), None)
    vcol = next((c for c in SIGNAL_COLS + ["action", "type"] if c in sig), None)
    if not tcol or not vcol:
        raise AdapterError(f"CSV not recognised: need time + one of {SIGNAL_COLS + ['action', 'type']} (signals), "
                           "or entry/exit time + side columns (trade list, e.g. TradingView/NinjaTrader/MT5 export)")
    idx = pd.to_datetime(sig[tcol])
    idx = idx.dt.tz_localize("America/New_York") if idx.dt.tz is None else idx
    ser = pd.Series(sig[vcol].map(lambda v: _word(re.sub(r"^(entry|exit)\s*", "", str(v).lower()).strip() or v)).to_numpy(),
                    index=pd.DatetimeIndex(idx).tz_convert("UTC")).sort_index()

    def fn(df):
        return ser.reindex(df.index, method="ffill").to_numpy()
    return AdaptedStrategy(src.stem, str(src), digest, "vectorized", f"signal_file:{vcol}",
                           [f"signal file: '{vcol}' at '{tcol}', forward-filled onto bars"], _fn=fn)
