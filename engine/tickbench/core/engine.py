"""Bar-by-bar backtest loop shared by every script adapter."""

from __future__ import annotations

import math
import time as _time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from ..errors import Cancelled, ScriptError, TickbenchError
from .bars import Bars
from .broker import Broker, Settings

MAX_EVENTS = 25_000


class StrategyAdapter:
    """Interface every script type implements.

    ``on_open`` runs at a bar's open (orders may fill immediately at that open);
    ``on_close`` runs once the bar has closed (orders fill at the next open).
    """

    name = "strategy"
    wants_open = False
    wants_close = True

    def setup(self, ctx: "RunContext") -> None:  # called once before the first bar
        pass

    def on_open(self, ctx: "RunContext", i: int) -> None:
        pass

    def on_close(self, ctx: "RunContext", i: int) -> None:
        pass

    def teardown(self, ctx: "RunContext") -> None:
        pass


@dataclass
class Plot:
    name: str
    values: list
    overlay: bool = True
    color: str | None = None
    kind: str = "line"   # line | histogram | markers

    def to_dict(self) -> dict:
        vals = [None if (v is None or (isinstance(v, float) and not math.isfinite(v))) else float(v)
                for v in self.values]
        return {"name": self.name, "values": vals, "overlay": self.overlay, "color": self.color, "kind": self.kind}


@dataclass
class RunContext:
    bars: Bars
    settings: Settings
    params: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    plots: dict = field(default_factory=dict)
    progress: Callable[[float], None] | None = None
    cancelled: Callable[[], bool] | None = None
    broker: Broker = None  # type: ignore[assignment]
    i: int = 0
    dropped_events: int = 0

    def log(self, kind: str, text: str, **extra: Any) -> None:
        if len(self.events) >= MAX_EVENTS:
            self.dropped_events += 1
            return
        bar = self.i
        self.events.append({"bar": bar, "time": int(self.bars.time[min(bar, len(self.bars) - 1)]),
                            "kind": kind, "text": str(text), **extra})

    def plot(self, name: str, value: float | None, *, overlay: bool = True, color: str | None = None,
             kind: str = "line") -> None:
        p = self.plots.get(name)
        if p is None:
            p = self.plots[name] = Plot(name, [None] * len(self.bars), overlay, color, kind)
        p.values[self.i] = value


def run_backtest(bars: Bars, adapter: StrategyAdapter, settings: Settings, params: dict | None = None,
                 progress: Callable[[float], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> RunContext:
    if len(bars) < 2:
        raise TickbenchError("Need at least 2 bars of data to backtest.", hint="Pick a longer date range.")
    ctx = RunContext(bars, settings, dict(params or {}), progress=progress, cancelled=cancelled)
    ctx.broker = Broker(bars, settings, ctx.log)
    started = _time.perf_counter()
    adapter.setup(ctx)
    n = len(bars)
    step = max(1, n // 100)
    try:
        for i in range(n):
            ctx.i = i
            ctx.broker.on_bar_open(i)
            if adapter.wants_open:
                adapter.on_open(ctx, i)
            ctx.broker.on_bar_range(i)
            ctx.broker.mark(i)
            if adapter.wants_close:
                adapter.on_close(ctx, i)
            if i % step == 0:
                if cancelled and cancelled():
                    raise Cancelled("Run cancelled.")
                if progress:
                    progress(i / n)
    except TickbenchError:
        raise
    except RecursionError as e:
        raise ScriptError(f"Script recursed too deeply on bar {ctx.i}.", hint="Check for a function calling itself.") from e
    finally:
        try:
            adapter.teardown(ctx)
        except Exception:
            pass
    ctx.i = n - 1
    ctx.broker.finish()
    if ctx.dropped_events:
        ctx.events.append({"bar": n - 1, "time": int(bars.time[-1]), "kind": "warn",
                           "text": f"{ctx.dropped_events:,} further log lines were dropped to keep the log readable."})
    ctx.params["_elapsed_ms"] = round((_time.perf_counter() - started) * 1000, 1)
    return ctx


def buy_and_hold(bars: Bars, capital: float) -> np.ndarray:
    first = bars.open[1] if len(bars) > 1 else bars.close[0]
    return capital * bars.close / first
