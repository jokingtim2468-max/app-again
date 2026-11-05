"""Pine Script strategies (and indicators) on the Tickbench engine.

Execution model matches TradingView's default strategy settings: the script runs once per bar on
the bar's close; market orders fill at the next bar's open (or at the same close with
``process_orders_on_close=true``).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from ...core.engine import RunContext, StrategyAdapter
from ...detect import pine_version
from ...errors import ScriptError
from .builtins import BUILTINS
from .parser import Node, parse
from .runtime import NA, Compiler, Frame, Runtime, is_na
from .strategy_api import make_strategy_builtins, strategy_constants

STRING_NAMESPACES = {"color", "shape", "location", "size", "plot", "display", "xloc", "yloc", "extend", "position",
                     "text", "font", "order", "currency", "hline", "label", "line", "format", "scale", "adjustment",
                     "barmerge", "alert", "dividends", "earnings", "splits", "session", "dayofweek", "input",
                     "math", "backadjustment", "settlement_as_close", "style", "table", "box"}

DAYS = {"sunday": 1, "monday": 2, "tuesday": 3, "wednesday": 4, "thursday": 5, "friday": 6, "saturday": 7}


class Constants(dict):
    """Built-in variables. Unknown names in style namespaces (color.red, shape.triangleup…) are strings."""

    def get(self, key, default=None):
        if key in self:
            return dict.__getitem__(self, key)
        ns, _, rest = key.partition(".")
        if ns == "dayofweek" and rest in DAYS:
            return DAYS[rest]
        if rest and ns in STRING_NAMESPACES:
            return f"{ns}.{rest}"
        return default


def _literal(n: Node):
    if n is None:
        return None
    if n.kind in ("num", "str", "bool"):
        return n.a
    if n.kind == "neg" and n.a.kind == "num":
        return -n.a.a
    if n.kind == "name":
        return n.a  # e.g. close for input.source
    return None


class PineAdapter(StrategyAdapter):
    def __init__(self, source: str, filename: str = "strategy.pine"):
        self.source = source
        self.filename = filename
        self.version = pine_version(source) or 5
        try:
            self.ast = parse(source)
        except ScriptError as e:
            e.file = filename
            raise
        self.inputs = self._scan_inputs()

    # ------------------------------------------------------------------ static info
    def _walk(self, nodes):
        stack = list(nodes)
        while stack:
            n = stack.pop()
            if not isinstance(n, Node):
                continue
            yield n
            for v in (n.a, n.b, n.c, n.d):
                if isinstance(v, Node):
                    stack.append(v)
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, Node):
                            stack.append(x)
                        elif isinstance(x, tuple):
                            stack.extend(y for y in x if isinstance(y, Node))
                            for y in x:
                                if isinstance(y, list):
                                    stack.extend(z for z in y if isinstance(z, Node))
                elif isinstance(v, dict):
                    stack.extend(x for x in v.values() if isinstance(x, Node))
                elif isinstance(v, tuple):
                    stack.extend(x for x in v if isinstance(x, Node))

    def _scan_inputs(self) -> list[dict]:
        out = []
        for n in self._walk(self.ast):
            if n.kind == "decl" and isinstance(n.b, Node) and n.b.kind == "call" and n.b.d and \
                    (n.b.d == "input" or n.b.d.startswith("input.")):
                call = n.b
                kind = call.d.split(".")[1] if "." in call.d else "any"
                default = _literal(call.b[0]) if call.b else _literal(call.c.get("defval"))
                title = call.c.get("title")
                title = _literal(title) if title is not None else (_literal(call.b[1]) if len(call.b) > 1 and call.b[1].kind == "str" else None)
                opts = call.c.get("options")
                spec = {"name": n.a, "title": title or n.a, "default": default, "kind": kind, "nid": call.nid,
                        "type": type(default).__name__ if default is not None else kind}
                for k in ("minval", "maxval", "step"):
                    if k in call.c:
                        spec[k] = _literal(call.c[k])
                if opts is not None and opts.kind == "tuple":
                    spec["options"] = [_literal(x) for x in opts.a]
                if kind == "source":
                    spec["type"] = "source"
                    spec["options"] = ["open", "high", "low", "close", "hl2", "hlc3", "ohlc4", "hlcc4", "volume"]
                out.append(spec)
        out.sort(key=lambda s: s["nid"])
        return out

    def describe(self) -> dict:
        decl = None
        for n in self.ast:
            if n.kind == "exprstmt" and n.a.kind == "call" and n.a.d in ("strategy", "indicator", "study"):
                decl = n.a.d
                break
        return {"flavor": f"pine-v{self.version}", "declaration": decl,
                "params": [{k: v for k, v in s.items() if k != "nid"} for s in self.inputs]}

    # ------------------------------------------------------------------ host API (used by built-ins)
    def input_value(self, nid, title, defval, kind, kw):
        spec = self.input_by_nid.get(nid)
        if spec is not None:
            for key in (spec["name"], spec["title"]):
                if key in self.overrides:
                    v = self.overrides[key]
                    if kind == "source" and isinstance(v, str):
                        try:
                            return float(self.bars.series(v)[self.rt.i])
                        except KeyError:
                            return defval
                    if kind == "int" and isinstance(v, (int, float)):
                        return int(v)
                    if kind == "float" and isinstance(v, (int, float)):
                        return float(v)
                    return v
        return defval

    def plot(self, title, value, color, kw):
        if title in self._plot_seen and self._plot_seen[title] != self.rt.i:
            pass
        self._plot_seen[title] = self.rt.i
        v = None
        if isinstance(value, bool):
            v = 1.0 if value else 0.0
        elif isinstance(value, (int, float)) and not is_na(value):
            v = float(value)
        overlay = self.overlay if not kw.get("_hline") else self.overlay
        if "force_overlay" in kw and kw["force_overlay"]:
            overlay = True
        self.ctx.plot(title, v, overlay=overlay, color=color)

    def warn_once(self, key, text):
        if key not in self._warned:
            self._warned.add(key)
            self.ctx.log("warn", text)

    def max_drawdown(self):
        eq = np.asarray(self.ctx.broker.equity_curve or [self.ctx.settings.initial_capital])
        return float(np.max(np.maximum.accumulate(eq) - eq))

    def declare_strategy(self, args, kw):
        if self._declared:
            return
        self._declared = True
        s = self.ctx.settings
        user = set(self.ctx.params.get("_user_settings", []))
        title = args[0] if args else kw.get("title", "")
        self.title = title
        self.overlay = bool(kw.get("overlay", args[2] if len(args) > 2 else False))
        applied = []

        def setv(attr, value, label):
            if attr in user or value is None or is_na(value):
                return
            setattr(s, attr, value)
            applied.append(f"{label}={value}")

        if "initial_capital" in kw and "initial_capital" not in user:
            s.initial_capital = float(kw["initial_capital"])
            if not self.ctx.broker.trades:
                self.ctx.broker.cash = s.initial_capital
            applied.append(f"initial_capital={s.initial_capital:g}")
        qt = kw.get("default_qty_type")
        if qt is not None:
            setv("qty_mode", {"fixed": "fixed", "percent_of_equity": "percent_of_equity", "cash": "cash"}.get(qt, "fixed"),
                 "default_qty_type")
        if "default_qty_value" in kw:
            setv("default_qty", float(kw["default_qty_value"]), "default_qty_value")
        if "pyramiding" in kw:
            setv("pyramiding", int(kw["pyramiding"]), "pyramiding")
        ct, cv = kw.get("commission_type"), kw.get("commission_value")
        if cv is not None and not is_na(cv):
            if ct == "percent":
                setv("commission_pct", float(cv), "commission %")
            elif ct in ("cash_per_contract", "cash_per_order"):
                setv("commission_per_unit", float(cv), "commission per contract")
        if "slippage" in kw:
            setv("slippage_ticks", float(kw["slippage"]), "slippage ticks")
        self.process_on_close = bool(kw.get("process_orders_on_close", False))
        if applied:
            self.ctx.log("info", "Using settings from strategy(): " + ", ".join(applied))

    def declare_indicator(self, args, kw):
        if not self._declared:
            self._declared = True
            self.is_indicator = True
            self.overlay = bool(kw.get("overlay", args[2] if len(args) > 2 else False))
            self.ctx.log("warn", "This is an indicator(), not a strategy(): it plots but places no trades. "
                                 "Add strategy.entry() calls to backtest it.")
        return NA

    def entry(self, eid, side, qty, limit, stop, reason, net):
        b = self.ctx.broker
        if not is_na(limit) or not is_na(stop):
            kind = "stop" if not is_na(stop) else "limit"
            price = stop if not is_na(stop) else limit
            b.submit_pending(kind, side, float(price), qty, tag=eid, reason=reason, net=net)
            return NA
        self.ctx.log("signal", reason)
        b.submit_market(side, qty, tag=eid, reason=reason, net=net, immediate=self.process_on_close,
                        at_close=self.process_on_close)
        return NA

    def close(self, eid, qty, qty_pct, reason, immediately):
        b = self.ctx.broker
        trades = [t for t in b.open if eid is None or t.tag == eid]
        if not trades:
            return
        if qty_pct is not None:
            qty = sum(t.qty for t in trades) * qty_pct / 100
        self.ctx.log("signal", reason)
        now = immediately or self.process_on_close
        b.submit_close(tag=eid, qty=qty, reason=reason, immediate=now, at_close=now)

    def exit(self, xid, from_entry, spec, reason):
        self.exit_specs[from_entry or "*"] = (spec, reason, xid)
        for t in self.ctx.broker.open:
            if not from_entry or t.tag == from_entry:
                self._apply_exit(t, spec)
        # pending entries pick the exit up when they fill (fill hook)

    def _apply_exit(self, t, spec):
        tick = self.mintick
        side = t.side
        sl = tp = None
        if not is_na(spec.get("stop")):
            sl = float(spec["stop"])
        elif not is_na(spec.get("loss")):
            sl = t.entry_price - side * float(spec["loss"]) * tick
        if not is_na(spec.get("limit")):
            tp = float(spec["limit"])
        elif not is_na(spec.get("profit")):
            tp = t.entry_price + side * float(spec["profit"]) * tick
        trail = None
        if not is_na(spec.get("trail_offset")) and (not is_na(spec.get("trail_points")) or not is_na(spec.get("trail_price"))):
            trail = float(spec["trail_offset"]) * tick
            self.warn_once("trail", "strategy.exit trailing stops start trailing immediately (activation level is not modelled).")
        qp = spec.get("qty_percent")
        if not is_na(qp) and float(qp) < 100:
            self.warn_once("qtypct", "strategy.exit qty_percent < 100 is treated as a full exit.")
        self.ctx.broker.modify(t, sl=sl, tp=tp, trail=trail)

    def _on_fill(self, t):
        spec = self.exit_specs.get(t.tag) or self.exit_specs.get("*")
        if spec:
            self._apply_exit(t, spec[0])

    # ------------------------------------------------------------------ run
    def _constants(self) -> Constants:
        b = self.bars
        T, O, H, L, C, V = b.time, b.open, b.high, b.low, b.close, b.volume
        n = len(b)
        step = int(np.median(np.diff(T))) if n > 2 else 86_400_000
        k = Constants()
        for name, arr in (("open", O), ("high", H), ("low", L), ("close", C), ("volume", V)):
            k[name] = (lambda a: (lambda rt: float(a[rt.i])))(arr)
            k["__series__:" + name] = (lambda a: (lambda rt, j: float(a[j])))(arr)
        hl2, hlc3, ohlc4, hlcc4 = (H + L) / 2, (H + L + C) / 3, (O + H + L + C) / 4, (H + L + 2 * C) / 4
        for name, arr in (("hl2", hl2), ("hlc3", hlc3), ("ohlc4", ohlc4), ("hlcc4", hlcc4)):
            k[name] = (lambda a: (lambda rt: float(a[rt.i])))(arr)
            k["__series__:" + name] = (lambda a: (lambda rt, j: float(a[j])))(arr)
        k["time"] = lambda rt: int(T[rt.i])
        k["__series__:time"] = lambda rt, j: int(T[j])
        k["time_close"] = lambda rt: int(T[rt.i + 1]) if rt.i + 1 < n else int(T[rt.i]) + step
        k["timenow"] = lambda rt: int(T[-1])
        k["bar_index"] = lambda rt: rt.i
        k["__series__:bar_index"] = lambda rt, j: j
        k["last_bar_index"] = n - 1
        k["last_bar_time"] = int(T[-1])

        def dpart(attr):
            def f(rt):
                d = datetime.fromtimestamp(T[rt.i] / 1000, tz=timezone.utc)
                if attr == "dayofweek":
                    return (d.isoweekday() % 7) + 1
                if attr == "weekofyear":
                    return d.isocalendar()[1]
                return getattr(d, attr)
            return f
        for nm, attr in (("year", "year"), ("month", "month"), ("dayofmonth", "day"), ("dayofweek", "dayofweek"),
                         ("hour", "hour"), ("minute", "minute"), ("second", "second"), ("weekofyear", "weekofyear")):
            k[nm] = dpart(attr)
        k["barstate.isfirst"] = lambda rt: rt.i == 0
        k["barstate.islast"] = lambda rt: rt.i == n - 1
        k["barstate.isconfirmed"] = True
        k["barstate.ishistory"] = True
        k["barstate.isrealtime"] = False
        k["barstate.isnew"] = True
        k["barstate.islastconfirmedhistory"] = lambda rt: rt.i == n - 1
        tf = b.timeframe or "1d"
        k["timeframe.period"] = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240",
                                 "1d": "D", "1w": "W", "1mo": "M"}.get(tf, tf)
        k["timeframe.isintraday"] = tf.endswith(("m", "h")) and tf != "1mo"
        k["timeframe.isdaily"] = tf == "1d"
        k["timeframe.isweekly"] = tf == "1w"
        k["timeframe.ismonthly"] = tf == "1mo"
        k["timeframe.isdwm"] = tf in ("1d", "1w", "1mo")
        k["timeframe.isminutes"] = tf.endswith("m") and tf != "1mo"
        k["timeframe.isseconds"] = False
        k["timeframe.multiplier"] = int("".join(ch for ch in tf if ch.isdigit()) or 1)
        k["syminfo.mintick"] = self.mintick
        k["syminfo.ticker"] = b.symbol
        k["syminfo.tickerid"] = b.symbol
        k["syminfo.root"] = b.symbol
        k["syminfo.pointvalue"] = self.ctx.settings.point_value
        k["syminfo.currency"] = "USD"
        k["syminfo.basecurrency"] = "USD"
        k["syminfo.timezone"] = "UTC"
        k["syminfo.type"] = "futures" if self.ctx.settings.point_value != 1 else "stock"
        k["syminfo.session"] = "regular"
        k["math.pi"] = math.pi
        k["math.e"] = math.e
        k["math.phi"] = (1 + 5 ** 0.5) / 2
        k["na"] = NA
        k["true"] = True
        k["false"] = False

        tr_state = {}

        def tr_var(rt):
            i = rt.i
            if i == 0:
                return NA
            pc = C[i - 1]
            return max(H[i] - L[i], abs(H[i] - pc), abs(L[i] - pc))
        k["ta.tr"] = tr_var

        vw = {"day": None, "pv": 0.0, "v": 0.0, "i": -1, "val": NA}

        def vwap_var(rt):
            i = rt.i
            if vw["i"] != i:
                day = int(T[i] // 86_400_000)
                if vw["day"] != day:
                    vw.update(day=day, pv=0.0, v=0.0)
                src = hlc3[i]
                vw["pv"] += src * V[i]
                vw["v"] += V[i]
                vw["val"] = vw["pv"] / vw["v"] if vw["v"] else src
                vw["i"] = i
            return vw["val"]
        k["ta.vwap"] = vwap_var
        k["ta.obv"] = self._cum_var(lambda i: (V[i] if C[i] > C[i - 1] else -V[i] if C[i] < C[i - 1] else 0.0) if i else 0.0)
        k["ta.accdist"] = self._cum_var(lambda i: (((C[i] - L[i]) - (H[i] - C[i])) / (H[i] - L[i]) * V[i]) if H[i] != L[i] else 0.0)
        k.update(strategy_constants(self))
        return k

    def _cum_var(self, f):
        st = {"i": -1, "v": 0.0}

        def g(rt):
            if st["i"] != rt.i:
                st["v"] += f(rt.i)
                st["i"] = rt.i
            return st["v"]
        return g

    def setup(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.bars = ctx.bars
        self.mintick = ctx.settings.tick_size or 0.01
        self.overrides = {k: v for k, v in ctx.params.items() if not k.startswith("_")}
        self.input_by_nid = {s["nid"]: s for s in self.inputs}
        self.exit_specs: dict = {}
        self._plot_seen: dict = {}
        self._warned: set = set()
        self._declared = False
        self.is_indicator = False
        self.overlay = True
        self.title = ""
        self.process_on_close = False
        builtins = dict(BUILTINS)
        builtins.update(make_strategy_builtins(self))
        comp = Compiler(builtins, self._constants(), lambda ln: "")
        try:
            self.program = comp.compile_program(self.ast)
        except ScriptError as e:
            e.file = self.filename
            raise
        self.rt = Runtime(self)
        self.rt.root = Frame(len(comp.global_persist), comp.global_persist)
        ctx.broker.fill_hooks.append(self._on_fill)
        if self.version and self.version < 4:
            ctx.log("warn", f"Pine v{self.version} script: run with v4 semantics where they differ.")

    def on_close(self, ctx: RunContext, i: int) -> None:
        rt = self.rt
        rt.i = i
        rt.loop_count = 0
        rt.visited = []
        rt.frame = rt.root
        try:
            self.program(rt)
        except ScriptError as e:
            e.file = self.filename
            if "bar" not in e.message:
                e.message = f"{e.message} (bar {i})"
            raise
        rt.root.commit()
        for fr in rt.visited:
            fr.commit()
