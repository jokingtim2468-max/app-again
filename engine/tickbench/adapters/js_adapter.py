"""Plain JavaScript strategies (``module.exports = { params, init(ctx), onBar(ctx) }``)."""

from __future__ import annotations

import json
import math

from ..core.engine import RunContext, StrategyAdapter
from .jsrt.runtime import JsRuntime, _read


def apply_commands(ctx: RunContext, cmds: list[dict]) -> None:
    b = ctx.broker
    ref = ctx.bars.close[ctx.i]
    for c in cmds:
        op = c.get("op")
        if op == "enter":
            side = int(c["side"])
            sl_off = c.get("slPoints")
            if sl_off is None and c.get("slPct") is not None:
                sl_off = ref * float(c["slPct"]) / 100
            tp_off = c.get("tpPoints")
            if tp_off is None and c.get("tpPct") is not None:
                tp_off = ref * float(c["tpPct"]) / 100
            reason = c.get("reason") or ""
            ctx.log("signal", f"{'Buy' if side > 0 else 'Sell'} signal" + (f": {reason}" if reason else ""))
            b.submit_market(side, c.get("qty"), tag=c.get("tag") or "", reason=reason, sl=c.get("sl"),
                            tp=c.get("tp"), sl_offset=sl_off, tp_offset=tp_off, trail=c.get("trail"))
        elif op == "pending":
            b.submit_pending(c["kind"], int(c["side"]), float(c["price"]), c.get("qty"), tag=c.get("tag") or "",
                             reason=c.get("reason") or "", sl=c.get("sl"), tp=c.get("tp"))
        elif op == "close":
            if b.open:
                ctx.log("signal", f"Exit signal: {c.get('reason') or ''}")
                b.submit_close(tag=c.get("tag"), qty=c.get("qty"), reason=c.get("reason") or "Exit signal")
        elif op == "cancel":
            b.cancel(tag=c.get("tag"))


class JsAdapter(StrategyAdapter):
    def __init__(self, source: str, filename: str = "strategy.js"):
        self.source = source
        self.filename = filename

    def _rt(self) -> tuple[JsRuntime, str]:
        rt = JsRuntime(self.filename)
        rt.eval(_read("strategy_ctx.js"))
        main = rt.register_sources(self.source)
        return rt, main

    def describe(self) -> dict:
        rt, main = self._rt()
        return {"flavor": "javascript", "params": json.loads(rt.call("__describe", main))}

    def setup(self, ctx: RunContext) -> None:
        self.rt, main = self._rt()
        self.rt.load_bars(ctx.bars)
        params = {k: v for k, v in ctx.params.items() if not k.startswith("_")}
        out = json.loads(self.rt.call("__initStrategy", main, json.dumps(params)))
        for line in out["logs"]:
            ctx.log("log", line)

    def on_close(self, ctx: RunContext, i: int) -> None:
        b = ctx.broker
        avg = b.position_avg_price
        res = json.loads(self.rt.call("__step", int(i), float(b.position_size), None if math.isnan(avg) else float(avg), float(b.equity()), float(b.cash)))
        for line in res["logs"]:
            ctx.log("log", line)
        for name, p in res["plots"].items():
            v = p.get("v")
            ctx.plot(name, None if v is None else float(v), overlay=p.get("overlay", True), color=p.get("color"))
        apply_commands(ctx, res["cmds"])
