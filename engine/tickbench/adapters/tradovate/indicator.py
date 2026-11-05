"""Tradovate Code Explorer custom indicators.

The indicator's calculator runs bar by bar in V8 with Tradovate's own ``tools/`` helpers, so its
plots match what Tradovate Trader draws. Indicators don't trade by themselves, so a *signal rule*
turns the plots into trades:

* ``cross`` – plot ``a`` crossing above plot/level ``b`` goes long, crossing below exits (or reverses
  when shorts are enabled). ``a``/``b`` may be a plot name, ``close`` or a number.
* ``threshold`` – plot ``a`` dropping below ``lower`` goes long and rising above ``upper`` goes short/
  exits (``contrarian: true``, the RSI style) or the reverse for breakouts.

With no rule the adapter picks one: two plots -> first crosses second; one overlay plot -> close
crosses the plot; one bounded 0–100 plot -> 30/70 contrarian; otherwise zero-line cross.
"""

from __future__ import annotations

import json
import math

import numpy as np

from ... import indicators as ta
from ...core.engine import Plot, RunContext, StrategyAdapter
from ...errors import ScriptError
from ..jsrt.runtime import JsRuntime, _read
from .common import contract_for


class TradovateIndicatorAdapter(StrategyAdapter):
    def __init__(self, source: str, filename: str = "indicator.js", signal: dict | None = None,
                 extra_files: dict | None = None):
        self.source = source
        self.filename = filename
        self.signal = dict(signal or {})
        self.extra = extra_files or {}

    def _rt(self):
        rt = JsRuntime(self.filename)
        rt.eval(_read("tradovate_indicator.js"))
        main = rt.register_sources(self.source, self.extra)
        return rt, main

    def describe(self) -> dict:
        rt, main = self._rt()
        d = json.loads(rt.call("__tiDescribe", main))
        d["flavor"] = "tradovate-indicator"
        return d

    def setup(self, ctx: RunContext) -> None:
        self.ctx = ctx
        rt, main = self._rt()
        rt.load_bars(ctx.bars)
        c = contract_for(ctx.bars, ctx.settings.tick_size, ctx.params.get("_contract"))
        params = {k: v for k, v in ctx.params.items() if not k.startswith("_")}
        res = json.loads(rt.call("__tiRun", main, json.dumps(params), json.dumps(
            {"contract": c["name"], "product": c["product"], "tickSize": c["tickSize"],
             "daily": ctx.bars.timeframe in ("1d", "1w", "1mo")})))
        for line in res.get("logs", []):
            ctx.log("log", line)
        n = len(ctx.bars)
        self.fields = {k: np.array([math.nan if v is None else float(v) for v in vals]) for k, vals in res["fields"].items()}
        plots = [k for k in res["plots"] if k in self.fields]
        if not plots:
            raise ScriptError("The indicator produced no numeric output.", file=self.filename,
                              hint="map(d) must return a number or an object of numbers.")
        close = ctx.bars.close
        self.overlay = {}
        for k in plots:
            arr = self.fields[k]
            with np.errstate(all="ignore"):
                rel = np.nanmedian(np.abs(arr / close - 1)) if np.isfinite(arr).any() else 1.0
            ov = res.get("areaChoice", "overlay") != "new" and rel < 0.3
            self.overlay[k] = ov
            ctx.plots[res["titles"].get(k, k)] = Plot(res["titles"].get(k, k),
                                                      [None if not math.isfinite(v) else v for v in arr], ov)
        self.plots = plots
        self.rule = self._auto_rule() if not self.signal.get("mode") else self.signal
        self.allow_short = bool(self.rule.get("short", self.signal.get("short", False)))
        ctx.log("info", "Signal rule: " + self._describe_rule())
        self.cross = ta.Cross()
        self.prev_a = math.nan
        if n and not any(np.isfinite(self.fields[p]).any() for p in plots):
            ctx.log("warn", "Indicator values are all empty; no trades will be generated.")

    # -------------------------------------------------------------- signal rule
    def _auto_rule(self) -> dict:
        p = self.plots
        if len(p) >= 2:
            return {"mode": "cross", "a": p[0], "b": p[1]}
        a = p[0]
        if self.overlay[a]:
            return {"mode": "cross", "a": "close", "b": a}
        arr = self.fields[a]
        fin = arr[np.isfinite(arr)]
        if len(fin) and fin.min() >= 0 and fin.max() <= 100:
            return {"mode": "threshold", "a": a, "lower": 30, "upper": 70, "contrarian": True}
        return {"mode": "cross", "a": a, "b": 0}

    def _describe_rule(self) -> str:
        r = self.rule
        if r["mode"] == "cross":
            return f"long when {r['a']} crosses above {r['b']}, exit/short when it crosses below"
        if r["mode"] == "threshold":
            if r.get("contrarian", True):
                return f"long when {r['a']} drops below {r['lower']}, exit/short when it rises above {r['upper']}"
            return f"long when {r['a']} rises above {r['upper']}, exit/short when it drops below {r['lower']}"
        return str(r)

    def _series(self, key, i):
        if isinstance(key, (int, float)):
            return float(key)
        if key in ("close", "open", "high", "low"):
            return float(getattr(self.ctx.bars, key)[i])
        arr = self.fields.get(key)
        if arr is None:
            raise ScriptError(f"Signal rule refers to '{key}', which the indicator doesn't output.",
                              hint="Outputs: " + ", ".join(self.plots))
        return float(arr[i])

    def on_close(self, ctx: RunContext, i: int) -> None:
        r = self.rule
        b = ctx.broker
        pos = b.position_size
        go_long = go_short = False
        if r["mode"] == "cross":
            up, down = self.cross.update(self._series(r["a"], i), self._series(r["b"], i))
            go_long, go_short = up, down
            why_l = f"{r['a']} crossed above {r['b']}"
            why_s = f"{r['a']} crossed below {r['b']}"
        else:
            a = self._series(r["a"], i)
            prev, self.prev_a = self.prev_a, a
            if math.isnan(a) or math.isnan(prev):
                return
            lo, hi = float(r["lower"]), float(r["upper"])
            below = prev >= lo > a
            above = prev <= hi < a
            if r.get("contrarian", True):
                go_long, go_short = below, above
                why_l, why_s = f"{r['a']} fell below {lo:g}", f"{r['a']} rose above {hi:g}"
            else:
                go_long, go_short = above, below
                why_l, why_s = f"{r['a']} rose above {hi:g}", f"{r['a']} fell below {lo:g}"
        if go_long and pos <= 0:
            ctx.log("signal", "Long: " + why_l)
            if pos < 0:
                b.submit_close(side=-1, reason=why_l)
            b.submit_market(1, reason=why_l, tag="long")
        elif go_short and pos >= 0:
            if pos > 0:
                ctx.log("signal", "Exit long: " + why_s)
                b.submit_close(side=1, reason=why_s)
            if self.allow_short:
                ctx.log("signal", "Short: " + why_s)
                b.submit_market(-1, reason=why_s, tag="short")
