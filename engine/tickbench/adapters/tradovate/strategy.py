"""Tradovate API strategies (the AutoTrade pattern from tradovate/example-api-trading-strategy).

The strategy's ``init(props)`` / ``next(state, [event, payload])`` run unchanged in V8. Each bar is
sent as a ``TdEvent.Chart`` event; position and cash-balance changes caused by fills are sent as
``TdEvent.Props`` events (entityType position / cashBalance), exactly the events the strategy would
receive from Tradovate. Order effects are executed by the Tickbench broker:

* ``orderStrategy/startOrderStrategy`` – entry plus bracket (profitTarget / stopLoss are price
  offsets from the fill; ``trailingStop: true`` makes the stop trail)
* ``order/placeOrder`` – Market / Limit / Stop orders (netting: a Sell while long reduces the long)
* ``order/placeOCO`` – two linked orders; filling one cancels the other
* ``order/liquidatePosition`` – flatten

Websocket, auth and replay plumbing is not needed and not run.
"""

from __future__ import annotations

import json
import math
import re

from ...core.engine import RunContext, StrategyAdapter
from ...errors import ScriptError
from ..jsrt.runtime import JsRuntime, _read
from .common import contract_for


def _default_for(name: str, typ: str):
    n = name.lower()
    if typ in ("int", "float", "number"):
        if "period" in n or "length" in n or "lookback" in n:
            if any(w in n for w in ("long", "slow")):
                return 30
            if any(w in n for w in ("short", "fast")):
                return 10
            return 14
        if any(w in n for w in ("qty", "quantity", "contracts", "size")):
            return 1
        return 1 if typ == "int" else 1.0
    if typ in ("boolean", "bool"):
        return False
    if typ == "string":
        return ""
    return None


class TradovateStrategyAdapter(StrategyAdapter):
    def __init__(self, source: str, filename: str = "strategy.js", extra_files: dict | None = None):
        self.source = source
        self.filename = filename
        self.extra = extra_files or {}

    def _rt(self):
        rt = JsRuntime(self.filename)
        rt.eval(_read("tradovate_strategy.js"))
        main = rt.register_sources(self.source, self.extra)
        return rt, main

    def describe(self) -> dict:
        rt, main = self._rt()
        spec = json.loads(rt.call("__tvParamSpec", main))
        params = []
        for p in spec["params"]:
            d = _default_for(p["name"], str(p["type"]))
            if d is not None:
                params.append({"name": p["name"], "default": d, "type": p["type"]})
        return {"flavor": "tradovate-strategy", "className": spec["name"], "params": params}

    def setup(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.rt, main = self._rt()
        self.rt.load_bars(ctx.bars)
        desc = self.describe()
        props = {p["name"]: p["default"] for p in desc["params"]}
        props.update({k: v for k, v in ctx.params.items() if not k.startswith("_")})
        contract = contract_for(ctx.bars, ctx.settings.tick_size, ctx.params.get("_contract"))
        tf = ctx.bars.timeframe
        m = re.match(r"(\d+)([mhdw])", tf or "")
        props.update({
            "contract": contract,
            # AutoTrade's DataBuffer uses BarsTransformer when barType === 'Bars'
            "barType": "Bars",
            "underlyingType": "MinuteBar" if (m and m.group(2) in "mh") else "DailyBar",
            "barInterval": (int(m.group(1)) * (60 if m.group(2) == "h" else 1)) if m and m.group(2) in "mh" else 1,
            "elementSizeUnit": "UnderlyingUnits",
            "histogram": False,
            "timeRangeType": "asMuchAsElements",
            "timeRangeValue": len(ctx.bars),
            "dev_mode": False,
            "replay_periods": [],
        })
        product = {"name": contract["product"], "id": 1, "tickSize": contract["tickSize"],
                   "valuePerPoint": ctx.settings.point_value, "currencyId": 1}
        out = json.loads(self.rt.call("__tvInit", main, json.dumps(props), json.dumps(product)))
        self._apply(out)
        self.last_pos = 0.0
        self.last_realized = 0.0
        self.realized = 0.0
        ctx.broker.exit_hooks.append(self._on_exit)

    def _on_exit(self, t) -> None:
        self.realized += t.pnl

    def _apply(self, out: dict) -> None:
        ctx = self.ctx
        for line in out.get("logs", []):
            ctx.log("log", line)
        b = ctx.broker
        tick = ctx.settings.tick_size
        for c in out.get("cmds", []):
            op = c["op"]
            side = int(c.get("side", 0) or 0)
            if op == "bracket":
                otype = (c.get("orderType") or "Market").lower()
                ctx.log("signal", f"{c['reason']} ({c['qty']:g} @ {otype}, target {c.get('tp')}, stop {c.get('sl')}"
                        f"{', trailing' if c.get('trail') else ''})")
                sl = c.get("sl") or None
                if otype == "market":
                    b.submit_market(side, c["qty"], reason=c["reason"], tp_offset=c.get("tp") or None,
                                    sl_offset=None if c.get("trail") else sl, trail=sl if c.get("trail") else None,
                                    net=True)
                else:
                    price = c.get("price") if otype == "limit" else (c.get("stopPrice") or c.get("price"))
                    if price is None:
                        raise ScriptError(f"{otype} order without a price.", file=self.filename)
                    b.submit_pending("limit" if otype == "limit" else "stop", side, float(price), c["qty"],
                                     reason=c["reason"], tp_offset=c.get("tp") or None,
                                     sl_offset=None if c.get("trail") else sl, trail=sl if c.get("trail") else None,
                                     net=True)
            elif op == "order":
                otype = (c.get("orderType") or "Market").lower()
                ctx.log("signal", c["reason"])
                if otype == "market":
                    b.submit_market(side, c["qty"], reason=c["reason"], net=True)
                else:
                    price = c.get("price") if otype == "limit" else (c.get("stopPrice") or c.get("price"))
                    b.submit_pending("limit" if otype == "limit" else "stop", side, float(price), c["qty"],
                                     reason=c["reason"], net=True)
            elif op == "oco":
                group = f"oco{ctx.i}_{len(b.pending)}"
                for leg in (c["a"], c["b"]):
                    otype = (leg.get("orderType") or "Limit").lower()
                    price = leg.get("price") if otype == "limit" else (leg.get("stopPrice") or leg.get("price"))
                    if price is None:
                        continue
                    b.submit_pending("limit" if otype == "limit" else "stop", int(leg["side"]), float(price),
                                     leg.get("qty"), reason=f"OCO {otype}", oco=group, net=True)
            elif op == "flatten":
                if b.open:
                    ctx.log("signal", "liquidatePosition")
                    b.submit_close(reason="liquidatePosition")
            elif op == "cancelAll":
                b.cancel_all()

    def on_close(self, ctx: RunContext, i: int) -> None:
        b = ctx.broker
        pos = b.position_size
        changed = pos != self.last_pos or abs(self.realized - self.last_realized) > 1e-9
        avg = b.position_avg_price
        pos_json = json.dumps({"netPos": pos, "netPrice": None if math.isnan(avg) else avg,
                               "timestamp": int(ctx.bars.time[i]),
                               "bought": sum(t.qty for t in b.open if t.side > 0),
                               "sold": sum(t.qty for t in b.open if t.side < 0)})
        out = json.loads(self.rt.call("__tvBar", int(i), pos_json, float(self.realized), bool(changed)))
        self.last_pos = pos
        self.last_realized = self.realized
        self._apply(out)
