"""strategy.* built-ins for Pine, mapped onto the Tickbench broker."""

from __future__ import annotations

import math

from ...errors import UnsupportedFeature
from .runtime import NA, is_na, truthy


def _arg(args, kw, i, name, default=NA):
    if i < len(args):
        return args[i]
    return kw.get(name, default)


def _direction(v, kw) -> int:
    if "long" in kw and v is NA:  # Pine v4: strategy.entry(id, long=true)
        v = kw["long"]
    if v in (True, "long", 1):
        return 1
    if v in (False, "short", -1):
        return -1
    raise UnsupportedFeature(f"Unknown direction {v!r}; use strategy.long or strategy.short.")


def make_strategy_builtins(host) -> dict:
    B = {}

    def why(node, label, comment):
        r = label
        if node.text:
            r += f" when {node.text}"
        if comment and not is_na(comment):
            r += f" — {comment}"
        return r

    def entry(rt, nid, args, kw, node):
        if "when" in kw and not truthy(kw["when"]):
            return NA
        eid = str(_arg(args, kw, 0, "id"))
        side = _direction(_arg(args, kw, 1, "direction"), kw)
        qty = _arg(args, kw, 2, "qty")
        limit = _arg(args, kw, 3, "limit")
        stop = _arg(args, kw, 4, "stop")
        comment = kw.get("comment")
        reason = why(node, f'strategy.entry("{eid}")', comment)
        return host.entry(eid, side, None if is_na(qty) else float(qty), limit, stop, reason, net=False)

    def order(rt, nid, args, kw, node):
        if "when" in kw and not truthy(kw["when"]):
            return NA
        eid = str(_arg(args, kw, 0, "id"))
        side = _direction(_arg(args, kw, 1, "direction"), kw)
        qty = _arg(args, kw, 2, "qty")
        limit = _arg(args, kw, 3, "limit")
        stop = _arg(args, kw, 4, "stop")
        reason = why(node, f'strategy.order("{eid}")', kw.get("comment"))
        return host.entry(eid, side, None if is_na(qty) else float(qty), limit, stop, reason, net=True)

    def close(rt, nid, args, kw, node):
        if "when" in kw and not truthy(kw["when"]):
            return NA
        eid = str(_arg(args, kw, 0, "id"))
        qty = kw.get("qty", NA)
        qty_pct = kw.get("qty_percent", NA)
        reason = why(node, f'strategy.close("{eid}")', kw.get("comment"))
        host.close(eid, None if is_na(qty) else float(qty), None if is_na(qty_pct) else float(qty_pct), reason,
                   truthy(kw.get("immediately", False)))
        return NA

    def close_all(rt, nid, args, kw, node):
        if "when" in kw and not truthy(kw["when"]):
            return NA
        reason = why(node, "strategy.close_all()", kw.get("comment"))
        host.close(None, None, None, reason, truthy(kw.get("immediately", False)))
        return NA

    def exit_(rt, nid, args, kw, node):
        if "when" in kw and not truthy(kw["when"]):
            return NA
        xid = str(_arg(args, kw, 0, "id"))
        from_entry = _arg(args, kw, 1, "from_entry", "")
        spec = {k: kw.get(k, NA) for k in ("qty", "qty_percent", "profit", "limit", "loss", "stop",
                                           "trail_price", "trail_points", "trail_offset")}
        # positional: id, from_entry, qty, qty_percent, profit, limit, loss, stop, trail_price, trail_points, trail_offset
        for i, k in enumerate(("qty", "qty_percent", "profit", "limit", "loss", "stop", "trail_price",
                               "trail_points", "trail_offset"), start=2):
            if i < len(args):
                spec[k] = args[i]
        host.exit(xid, "" if is_na(from_entry) else str(from_entry), spec,
                  why(node, f'strategy.exit("{xid}")', kw.get("comment")))
        return NA

    def cancel(rt, nid, args, kw, node):
        host.ctx.broker.cancel(tag=str(_arg(args, kw, 0, "id")))
        return NA

    def cancel_all(rt, nid, args, kw, node):
        host.ctx.broker.cancel_all()
        return NA

    def declaration(rt, nid, args, kw, node):
        host.declare_strategy(args, kw)
        return NA

    def risk_noop(name):
        def fn(rt, nid, args, kw, node):
            host.warn_once(name, f"{name}() is ignored in backtests.")
            return NA
        return fn

    B.update({"strategy.entry": entry, "strategy.order": order, "strategy.close": close,
              "strategy.close_all": close_all, "strategy.exit": exit_, "strategy.cancel": cancel,
              "strategy.cancel_all": cancel_all, "strategy": declaration,
              "indicator": lambda rt, nid, args, kw, node: host.declare_indicator(args, kw),
              "study": lambda rt, nid, args, kw, node: host.declare_indicator(args, kw)})
    for r in ("strategy.risk.allow_entry_in", "strategy.risk.max_drawdown", "strategy.risk.max_intraday_loss",
              "strategy.risk.max_cons_loss_days", "strategy.risk.max_position_size", "strategy.risk.max_intraday_filled_orders"):
        B[r] = risk_noop(r)

    # --- trade inspection functions
    def opentrade(attr):
        def fn(rt, nid, args, kw, node):
            k = int(args[0]) if args else 0
            ts = host.ctx.broker.open
            if not 0 <= k < len(ts):
                return NA
            t = ts[k]
            return {
                "entry_price": t.entry_price, "entry_bar_index": t.entry_bar, "entry_time": t.entry_time,
                "size": t.qty * t.side, "entry_id": t.tag, "entry_comment": t.comment,
                "profit": t.unrealized(host.bars.close[rt.i], host.ctx.settings.point_value),
                "max_drawup": t.mfe * t.qty * host.ctx.settings.point_value,
                "max_runup": t.mfe * t.qty * host.ctx.settings.point_value,
                "max_drawdown": t.mae * t.qty * host.ctx.settings.point_value,
                "commission": t.commission,
            }.get(attr, NA)
        return fn

    def closedtrade(attr):
        def fn(rt, nid, args, kw, node):
            k = int(args[0]) if args else 0
            ts = host.ctx.broker.closed
            if not 0 <= k < len(ts):
                return NA
            t = ts[k]
            return {
                "entry_price": t.entry_price, "entry_bar_index": t.entry_bar, "entry_time": t.entry_time,
                "exit_price": t.exit_price, "exit_bar_index": t.exit_bar, "exit_time": t.exit_time,
                "size": t.qty * t.side, "entry_id": t.tag, "exit_id": t.exit_reason, "profit": t.pnl,
                "commission": t.commission, "max_runup": t.mfe * t.qty * host.ctx.settings.point_value,
                "max_drawdown": t.mae * t.qty * host.ctx.settings.point_value,
            }.get(attr, NA)
        return fn

    for a in ("entry_price", "entry_bar_index", "entry_time", "size", "entry_id", "entry_comment", "profit",
              "max_drawup", "max_runup", "max_drawdown", "commission"):
        B["strategy.opentrades." + a] = opentrade(a)
    for a in ("entry_price", "entry_bar_index", "entry_time", "exit_price", "exit_bar_index", "exit_time", "size",
              "entry_id", "exit_id", "profit", "commission", "max_runup", "max_drawdown"):
        B["strategy.closedtrades." + a] = closedtrade(a)
    return B


def strategy_constants(host) -> dict:
    b = lambda: host.ctx.broker  # noqa: E731

    def closed():
        return b().closed

    return {
        "strategy.position_size": lambda rt: b().position_size,
        "strategy.position_avg_price": lambda rt: (lambda v: NA if math.isnan(v) else v)(b().position_avg_price),
        "strategy.equity": lambda rt: b().equity(),
        "strategy.netprofit": lambda rt: b().cash - host.ctx.settings.initial_capital,
        "strategy.openprofit": lambda rt: sum(t.unrealized(host.bars.close[rt.i], host.ctx.settings.point_value) for t in b().open),
        "strategy.grossprofit": lambda rt: sum(t.pnl for t in closed() if t.pnl > 0),
        "strategy.grossloss": lambda rt: -sum(t.pnl for t in closed() if t.pnl <= 0),
        "strategy.opentrades": lambda rt: len(b().open),
        "strategy.closedtrades": lambda rt: len(closed()),
        "strategy.wintrades": lambda rt: sum(1 for t in closed() if t.pnl > 0),
        "strategy.losstrades": lambda rt: sum(1 for t in closed() if t.pnl < 0),
        "strategy.eventrades": lambda rt: sum(1 for t in closed() if t.pnl == 0),
        "strategy.initial_capital": lambda rt: host.ctx.settings.initial_capital,
        "strategy.max_drawdown": lambda rt: host.max_drawdown(),
        "strategy.position_entry_name": lambda rt: (b().open[0].tag if b().open else ""),
        "strategy.long": "long",
        "strategy.short": "short",
        "strategy.fixed": "fixed",
        "strategy.cash": "cash",
        "strategy.percent_of_equity": "percent_of_equity",
        "strategy.commission.percent": "percent",
        "strategy.commission.cash_per_contract": "cash_per_contract",
        "strategy.commission.cash_per_order": "cash_per_order",
        "strategy.direction.all": "all",
        "strategy.direction.long": "long",
        "strategy.direction.short": "short",
        "strategy.oca.cancel": "cancel",
        "strategy.oca.reduce": "reduce",
        "strategy.oca.none": "none",
    }
