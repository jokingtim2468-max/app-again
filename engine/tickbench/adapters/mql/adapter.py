"""MetaTrader 4/5 Expert Advisors on the Tickbench engine.

Tick model: MetaTrader's "Open prices only" — OnTick()/start() runs once at each bar's open, market
orders fill at that open (buys at Ask = open + spread), and stops/targets are checked against the
bar's high/low afterwards. Accounts are hedging by default (each order is its own position); switch
to netting in the run settings for exchange-style accounts.
"""

from __future__ import annotations

import re

from ...core.engine import RunContext, StrategyAdapter
from ...errors import ScriptError, TickbenchError
from .api import MqlApi
from .interp import Interp, MqlArr, MStruct
from .parser import parse


class MqlAdapter(StrategyAdapter):
    wants_open = True
    wants_close = False

    def __init__(self, source: str, filename: str = "expert.mq5", dialect: str = "mql5"):
        self.source = source
        self.filename = filename
        self.dialect = dialect
        try:
            self.parsed = parse(source)
        except ScriptError as e:
            e.file = filename
            raise

    def _interp(self) -> Interp:
        return Interp(self.parsed.program, self.parsed.enums, self.api)

    def describe(self) -> dict:
        class _Dummy:
            pass
        self.api = _NullApi()
        it = self._interp()
        handlers = [n for n in ("OnInit", "OnTick", "OnDeinit", "OnTimer", "OnTrade", "OnTradeTransaction",
                                "init", "start", "deinit") if it.has(n)]
        return {"flavor": self.dialect, "params": it.describe_inputs(), "handlers": handlers,
                "properties": self.parsed.properties}

    def setup(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.bars = ctx.bars
        sym = ctx.bars.symbol.replace("=F", "").replace("=X", "").replace("-", "").replace("^", "")
        self.symbol = sym
        self.api = MqlApi(self)
        self.it = self._interp()
        overrides = {k: v for k, v in ctx.params.items() if not k.startswith("_")}
        self.tick_fn = "OnTick" if self.it.has("OnTick") else ("start" if self.it.has("start") else None)
        if self.tick_fn is None:
            raise ScriptError("No OnTick() (or MQL4 start()) function found.", file=self.filename,
                              hint="An Expert Advisor needs void OnTick() { ... }.")
        if self.it.has("OnTimer"):
            ctx.log("warn", "OnTimer() isn't called in backtests here (no timer events in open-prices mode).")
        ctx.i = 0
        try:
            self.it.init_globals(overrides)
            init = "OnInit" if self.it.has("OnInit") else ("init" if self.it.has("init") else None)
            if init:
                self.it.steps = 0
                r = self.it.call_user(init, [])
                if isinstance(r, (int, float)) and int(r) != 0 and init == "OnInit":
                    raise ScriptError(f"OnInit() returned {int(r)} (INIT_FAILED or bad parameters), so the EA "
                                      "would not start.", file=self.filename,
                                      hint="Check the input values and any conditions in OnInit().")
        except TickbenchError as e:
            e.file = e.file or self.filename
            raise
        mode = "hedging" if ctx.settings.hedging else "netting"
        ctx.log("info", f"MetaTrader 'open prices only' model, {mode} account, contract size "
                        f"{ctx.settings.point_value:g} per lot, point {ctx.settings.tick_size:g}.")

    def on_open(self, ctx: RunContext, i: int) -> None:
        if self.api.stopped:
            return
        self.it.steps = 0
        try:
            self.it.call_user(self.tick_fn, [])
        except TickbenchError as e:
            e.file = e.file or self.filename
            if "bar" not in e.message:
                e.message = f"{e.message} (bar {i})"
            raise

    def teardown(self, ctx: RunContext) -> None:
        fn = "OnDeinit" if self.it.has("OnDeinit") else ("deinit" if self.it.has("deinit") else None)
        if fn:
            try:
                self.it.steps = 0
                self.it.call_user(fn, [0])
            except TickbenchError:
                pass
        if self.api.comment:
            ctx.log("log", f"Last Comment(): {self.api.comment}")


class _NullApi:
    """Used only to evaluate input defaults for describe()."""
    classes: dict = {}

    def name(self, n, line):
        from .api import CONST
        if n in CONST:
            return CONST[n]
        return 0

    def call(self, name, nodes, it, line):
        return 0

    def parse_datetime(self, s):
        return 0


def guess_contract_size(symbol: str) -> float:
    s = re.sub(r"[^A-Z]", "", symbol.upper())
    if s.startswith(("XAU", "GOLD", "GC")):
        return 100.0
    if s.startswith(("XAG", "SILVER", "SI")):
        return 5000.0
    if len(s) == 6 and s[:3] in {"EUR", "GBP", "USD", "AUD", "NZD", "CAD", "CHF", "JPY"}:
        return 100000.0
    return 1.0
