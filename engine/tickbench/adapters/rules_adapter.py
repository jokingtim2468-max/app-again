"""No-code rule strategies written in JSON or YAML.

Example::

    {
      "name": "SMA cross",
      "params": {"fast": 10, "slow": 30},
      "indicators": {
        "fast": {"type": "sma", "source": "close", "length": "$fast"},
        "slow": {"type": "sma", "source": "close", "length": "$slow"}
      },
      "entry_long":  {"crosses_above": ["fast", "slow"]},
      "exit_long":   {"crosses_below": ["fast", "slow"]},
      "stop_loss":   {"atr": 2, "atr_length": 14},
      "take_profit": {"pct": 6}
    }

Operands are an indicator name, a price field (open/high/low/close/volume/hl2/hlc3/ohlc4),
a number, ``"$param"``, or ``{"ref": "fast", "bars_ago": 1}``. Conditions:
``crosses_above``, ``crosses_below``, ``>``, ``<``, ``>=``, ``<=``, ``==``, ``between``,
``rising`` / ``falling`` ([series, bars]) and combinators ``all`` / ``any`` / ``not``.
"""

from __future__ import annotations

import json
import math

import numpy as np

from .. import indicators as ta
from ..core.engine import Plot, RunContext, StrategyAdapter
from ..errors import ScriptError

PRICE = {"open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4", "hlcc4"}


class RulesAdapter(StrategyAdapter):
    def __init__(self, source: str, filename: str = "rules.json", fmt: str = "rules-json"):
        self.filename = filename
        try:
            if fmt == "rules-yaml":
                import yaml
                self.spec = yaml.safe_load(source)
            else:
                self.spec = json.loads(source)
        except Exception as e:
            line = getattr(e, "lineno", None) or getattr(getattr(e, "problem_mark", None), "line", None)
            raise ScriptError(f"Couldn't parse the rules file: {e}", file=filename, line=line) from e
        if not isinstance(self.spec, dict):
            raise ScriptError("Rules file must be an object with entry/exit rules.", file=filename)
        # shorthand: entry/exit mean long entry/exit
        if "entry" in self.spec and "entry_long" not in self.spec:
            self.spec["entry_long"] = self.spec["entry"]
        if "exit" in self.spec and "exit_long" not in self.spec:
            self.spec["exit_long"] = self.spec["exit"]

    def describe(self) -> dict:
        p = self.spec.get("params") or {}
        return {"flavor": "rules", "params": [{"name": k, "default": v, "type": type(v).__name__} for k, v in p.items()]}

    # ------------------------------------------------------------------ setup
    def _param(self, v):
        if isinstance(v, str) and v.startswith("$"):
            name = v[1:]
            if name not in self.params:
                raise ScriptError(f"Unknown parameter '{v}'.", file=self.filename, hint="Add it under \"params\".")
            return self.params[name]
        return v

    def setup(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.params = dict(self.spec.get("params") or {})
        self.params.update({k: v for k, v in ctx.params.items() if not k.startswith("_")})
        b = ctx.bars
        self.series: dict[str, np.ndarray] = {}
        for name, d in (self.spec.get("indicators") or {}).items():
            self.series[name] = self._build_indicator(name, d)
            overlay = d.get("type", "").lower() in ("sma", "ema", "wma", "rma", "highest", "lowest", "bb_upper",
                                                     "bb_lower", "bb_mid", "vwma", "supertrend")
            ctx.plots[name] = Plot(name, [float(v) if math.isfinite(v) else None for v in self.series[name]],
                                   overlay=d.get("overlay", overlay))
        self.qty = self._param(self.spec.get("qty")) if self.spec.get("qty") is not None else None
        self.rules = {k: self.spec.get(k) for k in ("entry_long", "exit_long", "entry_short", "exit_short")}
        if not any(self.rules.values()):
            raise ScriptError("No entry rules found.", file=self.filename,
                              hint="Add \"entry_long\" (and optionally \"exit_long\", \"entry_short\", \"exit_short\").")
        self.atr = ta.atr(b.high, b.low, b.close, int(self._param((self.spec.get("stop_loss") or {}).get("atr_length", 14))))

    def _src(self, s) -> np.ndarray:
        s = self._param(s)
        if isinstance(s, str) and s.lower() in PRICE:
            return self.ctx.bars.series(s.lower())
        if isinstance(s, str) and s in self.series:
            return self.series[s]
        raise ScriptError(f"Unknown source '{s}'.", file=self.filename,
                          hint="Use a price field (close, high…) or an indicator defined above it.")

    def _build_indicator(self, name: str, d: dict) -> np.ndarray:
        b = self.ctx.bars
        t = str(d.get("type", "")).lower()
        L = int(self._param(d.get("length", d.get("period", 14))))
        src = self._src(d.get("source", "close")) if t not in ("atr", "supertrend") else None
        if t in ("sma", "ema", "wma", "rma"):
            return ta.ma(t, src, L)
        if t == "rsi":
            return ta.rsi(src, L)
        if t == "atr":
            return ta.atr(b.high, b.low, b.close, L)
        if t == "stdev":
            return ta.stdev(src, L)
        if t == "highest":
            return ta.highest(src, L)
        if t == "lowest":
            return ta.lowest(src, L)
        if t == "cci":
            return ta.cci(src, L)
        if t in ("macd", "macd_signal", "macd_hist"):
            m, s, h = ta.macd(src, int(self._param(d.get("fast", 12))), int(self._param(d.get("slow", 26))),
                              int(self._param(d.get("signal", 9))))
            return {"macd": m, "macd_signal": s, "macd_hist": h}[t]
        if t in ("bb_upper", "bb_lower", "bb_mid"):
            m, u, l = ta.bbands(src, L, float(self._param(d.get("mult", 2.0))))
            return {"bb_mid": m, "bb_upper": u, "bb_lower": l}[t]
        if t == "roc":
            return ta.run(ta.ROC(L), src)
        if t == "change":
            return ta.run(ta.Change(L), src)
        raise ScriptError(f"Indicator '{name}' has unknown type '{t}'.", file=self.filename,
                          hint="Types: sma, ema, wma, rma, rsi, atr, stdev, highest, lowest, cci, macd, macd_signal, "
                               "macd_hist, bb_upper, bb_mid, bb_lower, roc, change")

    # ------------------------------------------------------------------ evaluation
    def _val(self, x, i: int, ago: int = 0) -> float:
        if isinstance(x, dict) and "ref" in x:
            return self._val(x["ref"], i, int(x.get("bars_ago", 0)) + ago)
        x = self._param(x)
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return float(x)
        arr = self._src(x)
        j = i - ago
        return float(arr[j]) if j >= 0 else math.nan

    def _eval(self, cond, i: int) -> bool:
        if cond is None:
            return False
        if isinstance(cond, list):
            return all(self._eval(c, i) for c in cond)
        if not isinstance(cond, dict) or len(cond) != 1:
            raise ScriptError(f"Bad condition: {json.dumps(cond)[:80]}", file=self.filename,
                              hint="Each condition is a single key, e.g. {\"crosses_above\": [\"fast\", \"slow\"]}.")
        (op, args), = cond.items()
        if op == "all":
            return all(self._eval(c, i) for c in args)
        if op == "any":
            return any(self._eval(c, i) for c in args)
        if op == "not":
            return not self._eval(args, i)
        if op in ("rising", "falling"):
            n = int(self._param(args[1])) if len(args) > 1 else 1
            now, then = self._val(args[0], i), self._val(args[0], i, n)
            return (now > then) if op == "rising" else (now < then)
        a0, b0 = self._val(args[0], i), self._val(args[1], i) if len(args) > 1 else math.nan
        if op in ("crosses_above", "crosses_below"):
            a1, b1 = self._val(args[0], i, 1), self._val(args[1], i, 1)
            if any(math.isnan(v) for v in (a0, b0, a1, b1)):
                return False
            return (a0 > b0 and a1 <= b1) if op == "crosses_above" else (a0 < b0 and a1 >= b1)
        if any(math.isnan(v) for v in (a0, b0)):
            return False
        if op == ">":
            return a0 > b0
        if op == "<":
            return a0 < b0
        if op == ">=":
            return a0 >= b0
        if op == "<=":
            return a0 <= b0
        if op == "==":
            return a0 == b0
        if op == "between":
            hi = self._val(args[2], i)
            return b0 <= a0 <= hi
        raise ScriptError(f"Unknown condition '{op}'.", file=self.filename)

    def _offset(self, spec, i: int) -> float | None:
        if not spec:
            return None
        c = self.ctx.bars.close[i]
        if "pct" in spec:
            return c * float(self._param(spec["pct"])) / 100
        if "points" in spec:
            return float(self._param(spec["points"]))
        if "ticks" in spec:
            return float(self._param(spec["ticks"])) * self.ctx.settings.tick_size
        if "atr" in spec:
            a = self.atr[i]
            return float(self._param(spec["atr"])) * a if math.isfinite(a) else None
        return None

    @staticmethod
    def _describe(cond) -> str:
        if isinstance(cond, dict) and len(cond) == 1:
            (op, args), = cond.items()
            if op in ("all", "any"):
                return f" {op.upper()} ".join(RulesAdapter._describe(c) for c in args)
            if op == "not":
                return "NOT " + RulesAdapter._describe(args)
            if isinstance(args, list):
                parts = [a if not isinstance(a, dict) else f"{a.get('ref')}[{a.get('bars_ago', 0)}]" for a in args]
                return f"{parts[0]} {op.replace('_', ' ')} {' '.join(str(p) for p in parts[1:])}"
        return json.dumps(cond)

    def on_close(self, ctx: RunContext, i: int) -> None:
        b = ctx.broker
        pos = b.position_size
        trail = (self.spec.get("stop_loss") or {}).get("trailing", False)
        if pos > 0 and self._eval(self.rules["exit_long"], i):
            ctx.log("signal", "Exit long: " + self._describe(self.rules["exit_long"]))
            b.submit_close(side=1, reason=self._describe(self.rules["exit_long"]))
            pos = 0
        if pos < 0 and self._eval(self.rules["exit_short"], i):
            ctx.log("signal", "Exit short: " + self._describe(self.rules["exit_short"]))
            b.submit_close(side=-1, reason=self._describe(self.rules["exit_short"]))
            pos = 0
        for side, key in ((1, "entry_long"), (-1, "entry_short")):
            if pos * side > 0 or not self.rules[key]:
                continue
            if self._eval(self.rules[key], i):
                why = self._describe(self.rules[key])
                sl = self._offset(self.spec.get("stop_loss"), i)
                tp = self._offset(self.spec.get("take_profit"), i)
                ctx.log("signal", f"{'Long' if side > 0 else 'Short'} entry: {why}")
                b.submit_market(side, self.qty, tag="long" if side > 0 else "short", reason=why,
                                sl_offset=None if trail else sl, tp_offset=tp, trail=sl if trail else None)
                break
