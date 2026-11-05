"""Simulated broker.

Fill model (no look-ahead):
* Orders a strategy places while looking at a closed bar are queued and fill at the
  *next* bar's open (``immediate=False``).
* Strategies that run at a bar's open (MQL ``OnTick`` in open-prices mode) may fill
  immediately at that open (``immediate=True``).
* Stop-loss / take-profit / pending stop & limit orders are checked against each bar's
  high/low. A gap through a level fills at the open. If one bar touches both the stop
  and the target we assume the stop was hit first (the conservative choice).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Callable

from .bars import Bars


@dataclass
class Settings:
    initial_capital: float = 10_000.0
    commission_per_unit: float = 0.0      # $ per contract/share/lot, per side
    commission_pct: float = 0.0           # % of notional, per side
    slippage_ticks: float = 0.0
    spread: float = 0.0                   # price units added to buy fills
    tick_size: float = 0.01
    point_value: float = 1.0              # $ per 1.0 price move per unit (futures multiplier)
    hedging: bool = False                 # MQL4/5-style independent positions
    pyramiding: int = 1                   # max simultaneous entries in one direction (netting mode)
    default_qty: float = 1.0
    qty_mode: str = "fixed"               # fixed | percent_equity | cash
    allow_short: bool = True
    integer_qty: bool = False             # futures contracts are whole numbers
    close_at_end: bool = True

    @staticmethod
    def from_dict(d: dict | None) -> "Settings":
        s = Settings()
        for k, v in (d or {}).items():
            if hasattr(s, k) and v is not None:
                cur = getattr(s, k)
                if isinstance(cur, bool):
                    v = bool(v)
                elif isinstance(cur, int) and not isinstance(cur, bool):
                    v = int(v)
                elif isinstance(cur, float):
                    v = float(v)
                setattr(s, k, v)
        return s

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Trade:
    id: int
    side: int                 # +1 long, -1 short
    qty: float
    entry_bar: int
    entry_time: int
    entry_price: float
    tag: str = ""
    entry_reason: str = ""
    sl: float | None = None
    tp: float | None = None
    trail_dist: float | None = None
    magic: int = 0
    comment: str = ""
    initial_sl: float | None = None
    exit_bar: int | None = None
    exit_time: int | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl: float = 0.0
    commission: float = 0.0
    mae: float = 0.0          # worst adverse excursion, price units (>= 0)
    mfe: float = 0.0          # best favourable excursion, price units (>= 0)
    best_price: float = 0.0   # for trailing stops
    order_id: int = 0         # id of the order that opened it (MetaTrader ticket)

    @property
    def is_open(self) -> bool:
        return self.exit_bar is None

    def unrealized(self, price: float, point_value: float) -> float:
        return (price - self.entry_price) * self.side * self.qty * point_value

    def to_dict(self, bars: Bars | None = None) -> dict:
        d = {
            "id": self.id, "side": "long" if self.side > 0 else "short", "qty": self.qty,
            "entryBar": self.entry_bar, "entryTime": self.entry_time, "entryPrice": self.entry_price,
            "exitBar": self.exit_bar, "exitTime": self.exit_time, "exitPrice": self.exit_price,
            "tag": self.tag, "entryReason": self.entry_reason, "exitReason": self.exit_reason,
            "pnl": self.pnl, "commission": self.commission, "mae": self.mae, "mfe": self.mfe,
            "sl": self.initial_sl, "tp": self.tp,
            "barsHeld": (self.exit_bar - self.entry_bar) if self.exit_bar is not None else None,
        }
        risk = abs(self.entry_price - self.initial_sl) if self.initial_sl is not None else None
        if risk and self.exit_price is not None:
            d["r"] = (self.exit_price - self.entry_price) * self.side / risk
        else:
            d["r"] = None
        return d


@dataclass
class Order:
    id: int
    kind: str                         # market | limit | stop | close
    side: int = 0
    qty: float | None = None
    price: float | None = None
    tag: str = ""
    reason: str = ""
    sl: float | None = None
    tp: float | None = None
    sl_offset: float | None = None    # price distance from fill, set when the fill price is unknown
    tp_offset: float | None = None
    trail: float | None = None        # trailing-stop distance in price units
    placed_bar: int = 0
    expire_bar: int | None = None
    oco: str | None = None
    close_ids: list[int] | None = None   # for kind == close: trades to close (None = all matching tag/side)
    close_side: int = 0
    close_qty: float | None = None
    magic: int = 0
    comment: str = ""
    net: bool = False                 # netting order: reduce an opposite position first, open only the rest

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "side": self.side, "qty": self.qty, "price": self.price,
                "tag": self.tag, "sl": self.sl, "tp": self.tp}


class Broker:
    def __init__(self, bars: Bars, settings: Settings, log: Callable[..., None]):
        self.bars = bars
        self.s = settings
        self.log = log
        self.cash = settings.initial_capital
        self.trades: list[Trade] = []
        self.open: list[Trade] = []
        self.queue: list[Order] = []      # market/close orders waiting for the next open
        self.pending: list[Order] = []    # resting limit/stop orders
        self._next_trade = 1
        self._next_order = 1
        self.bar = 0                      # index of the bar being processed
        self.equity_curve: list[float] = []
        self.exit_hooks: list[Callable[[Trade], None]] = []
        self.fill_hooks: list[Callable[[Trade], None]] = []
        self.ignored_orders = 0

    # ------------------------------------------------------------------ queries
    @property
    def position_size(self) -> float:
        return sum(t.side * t.qty for t in self.open)

    @property
    def position_avg_price(self) -> float:
        q = sum(t.qty for t in self.open)
        if not q:
            return math.nan
        return sum(t.entry_price * t.qty for t in self.open) / q

    def equity(self, price: float | None = None) -> float:
        if price is None:
            price = self.bars.close[min(self.bar, len(self.bars) - 1)]
        return self.cash + sum(t.unrealized(price, self.s.point_value) for t in self.open)

    @property
    def closed(self) -> list[Trade]:
        return [t for t in self.trades if not t.is_open]

    def net_profit(self) -> float:
        return self.cash - self.s.initial_capital

    # ------------------------------------------------------------------ costs
    def _commission(self, price: float, qty: float) -> float:
        return (self.s.commission_per_unit * qty
                + self.s.commission_pct / 100.0 * price * qty * self.s.point_value)

    def _fill_price(self, raw: float, side: int, slip: bool = True) -> float:
        """side = direction of the fill (+1 buy, -1 sell)."""
        p = raw
        if side > 0:
            p += self.s.spread
        if slip and self.s.slippage_ticks:
            p += side * self.s.slippage_ticks * self.s.tick_size
        return p

    def _size(self, qty: float | None, price: float) -> float:
        s = self.s
        if qty is None:
            if s.qty_mode == "percent_equity":
                qty = self.equity() * s.default_qty / 100.0 / (price * s.point_value)
            elif s.qty_mode == "cash":
                qty = s.default_qty / (price * s.point_value)
            else:
                qty = s.default_qty
        if s.integer_qty:
            qty = math.floor(qty + 1e-9)
        return max(0.0, float(qty))

    # ------------------------------------------------------------------ order entry
    def submit_market(self, side: int, qty: float | None = None, *, tag: str = "", reason: str = "",
                      sl: float | None = None, tp: float | None = None, sl_offset: float | None = None,
                      tp_offset: float | None = None, trail: float | None = None, immediate: bool = False,
                      magic: int = 0, comment: str = "", net: bool = False, at_close: bool = False) -> Order | None:
        if side < 0 and not self.s.allow_short and self.position_size <= 0 and not net:
            self.log("warn", f"Short entry ignored (shorting is turned off): {reason or tag}")
            return None
        o = Order(self._next_order, "market", side=side, qty=qty, tag=tag, reason=reason, sl=sl, tp=tp,
                  sl_offset=sl_offset, tp_offset=tp_offset, trail=trail, placed_bar=self.bar,
                  magic=magic, comment=comment, net=net)
        self._next_order += 1
        if immediate:
            self._execute_market(o, self.bars.close[self.bar] if at_close else self.bars.open[self.bar])
        else:
            self.queue.append(o)
        return o

    def submit_pending(self, kind: str, side: int, price: float, qty: float | None = None, *, tag: str = "",
                       reason: str = "", sl: float | None = None, tp: float | None = None,
                       sl_offset: float | None = None, tp_offset: float | None = None,
                       trail: float | None = None, oco: str | None = None, expire_bar: int | None = None,
                       magic: int = 0, comment: str = "", net: bool = False) -> Order:
        # Replace an existing resting order with the same tag (Pine semantics).
        if tag:
            self.pending = [p for p in self.pending if not (p.tag == tag and p.kind in ("limit", "stop") and p.close_ids is None and p.close_side == 0)]
        o = Order(self._next_order, kind, side=side, qty=qty, price=price, tag=tag, reason=reason, sl=sl, tp=tp,
                  sl_offset=sl_offset, tp_offset=tp_offset, trail=trail, placed_bar=self.bar, oco=oco,
                  expire_bar=expire_bar, magic=magic, comment=comment, net=net)
        self._next_order += 1
        self.pending.append(o)
        self.log("order", f"{'Buy' if side > 0 else 'Sell'} {kind} @ {price:.6g} placed" + (f" ({reason})" if reason else ""))
        return o

    def submit_close(self, *, tag: str | None = None, trade_ids: list[int] | None = None, side: int = 0,
                     qty: float | None = None, reason: str = "", immediate: bool = False,
                     at_close: bool = False) -> Order:
        o = Order(self._next_order, "close", tag=tag or "", reason=reason, close_ids=trade_ids,
                  close_side=side, close_qty=qty, placed_bar=self.bar)
        self._next_order += 1
        if immediate:
            self._execute_close(o, self.bars.close[self.bar] if at_close else self.bars.open[self.bar])
        else:
            self.queue.append(o)
        return o

    def cancel(self, *, tag: str | None = None, order_id: int | None = None) -> int:
        before = len(self.pending) + len(self.queue)
        keep = lambda o: not ((tag is not None and o.tag == tag) or (order_id is not None and o.id == order_id))
        self.pending = [o for o in self.pending if keep(o)]
        self.queue = [o for o in self.queue if keep(o)]
        return before - len(self.pending) - len(self.queue)

    def cancel_all(self) -> None:
        self.pending.clear()
        self.queue = [o for o in self.queue if o.kind == "close"]

    def modify(self, trade: Trade, *, sl: float | None = None, tp: float | None = None,
               trail: float | None = None, keep_none: bool = True) -> None:
        if sl is not None or not keep_none:
            trade.sl = sl
            if trade.initial_sl is None and sl is not None:
                trade.initial_sl = sl
        if tp is not None or not keep_none:
            trade.tp = tp
        if trail is not None:
            trade.trail_dist = trail
            trade.best_price = trade.best_price or trade.entry_price

    # ------------------------------------------------------------------ execution
    def _open_trade(self, o: Order, raw_price: float) -> Trade | None:
        price = self._fill_price(raw_price, o.side)
        qty = self._size(o.qty, price)
        if qty <= 0:
            self.log("warn", f"Order skipped: size rounds to 0 ({o.reason or o.tag})")
            return None
        t = Trade(self._next_trade, o.side, qty, self.bar, int(self.bars.time[self.bar]), price, tag=o.tag,
                  entry_reason=o.reason, magic=o.magic, comment=o.comment, order_id=o.id)
        self._next_trade += 1
        t.sl = o.sl if o.sl is not None else (price - o.side * o.sl_offset if o.sl_offset is not None else None)
        t.tp = o.tp if o.tp is not None else (price + o.side * o.tp_offset if o.tp_offset is not None else None)
        if o.trail:
            t.trail_dist = o.trail
            if t.sl is None:
                t.sl = price - o.side * o.trail
        t.initial_sl = t.sl
        t.best_price = price
        fee = self._commission(price, qty)
        t.commission += fee
        self.cash -= fee
        self.trades.append(t)
        self.open.append(t)
        self.log("fill", f"{'Long' if o.side > 0 else 'Short'} {qty:g} @ {price:.6g}"
                 + (f" — {o.reason}" if o.reason else (f" [{o.tag}]" if o.tag else "")), trade=t.id)
        for h in self.fill_hooks:
            h(t)
        return t

    def close_trade(self, t: Trade, raw_price: float, reason: str, qty: float | None = None, slip: bool = True) -> None:
        if not t.is_open:
            return
        if qty is not None and qty < t.qty - 1e-12:
            # Partial close: split the trade so each record stays a single round trip.
            rest = Trade(**{**t.__dict__})
            rest.id = self._next_trade
            self._next_trade += 1
            rest.qty = t.qty - qty
            rest.commission = 0.0
            t.qty = qty
            self.trades.append(rest)
            self.open.append(rest)
        price = self._fill_price(raw_price, -t.side, slip)
        fee = self._commission(price, t.qty)
        gross = (price - t.entry_price) * t.side * t.qty * self.s.point_value
        t.commission += fee
        t.pnl = gross - t.commission
        self.cash += gross - fee
        t.exit_bar = self.bar
        t.exit_time = int(self.bars.time[self.bar])
        t.exit_price = price
        t.exit_reason = reason
        self.open.remove(t)
        self.log("exit", f"Closed {'long' if t.side > 0 else 'short'} #{t.id} @ {price:.6g}: {reason} "
                 f"({'+' if t.pnl >= 0 else ''}{t.pnl:,.2f})", trade=t.id)
        for h in self.exit_hooks:
            h(t)

    def _execute_market(self, o: Order, raw_price: float) -> None:
        if o.net and not self.s.hedging:
            want = self._size(o.qty, raw_price)
            for t in [t for t in self.open if t.side == -o.side]:
                if want <= 1e-12:
                    break
                q = min(want, t.qty)
                want -= q
                self.close_trade(t, raw_price, o.reason or "Opposite order", qty=q)
            if want > 1e-12:
                if o.side < 0 and not self.s.allow_short and self.position_size <= 0:
                    return
                o.qty = want
                self._open_trade(o, raw_price)
            return
        if self.s.hedging:
            self._open_trade(o, raw_price)
            return
        opposite = [t for t in self.open if t.side == -o.side]
        if opposite:
            for t in list(opposite):
                self.close_trade(t, raw_price, f"Reversed by {o.reason or o.tag or 'opposite entry'}")
        same = [t for t in self.open if t.side == o.side]
        if len(same) >= max(1, self.s.pyramiding):
            self.ignored_orders += 1  # summarised once at the end; Pine scripts often re-send entries every bar
            return
        if o.side < 0 and not self.s.allow_short:
            return
        self._open_trade(o, raw_price)

    def _matching(self, o: Order) -> list[Trade]:
        ts = list(self.open)
        if o.close_ids is not None:
            ts = [t for t in ts if t.id in o.close_ids]
        if o.tag:
            ts = [t for t in ts if t.tag == o.tag]
        if o.close_side:
            ts = [t for t in ts if t.side == o.close_side]
        return ts

    def _execute_close(self, o: Order, raw_price: float) -> None:
        remaining = o.close_qty
        for t in self._matching(o):
            if remaining is not None:
                if remaining <= 1e-12:
                    break
                q = min(remaining, t.qty)
                remaining -= q
                self.close_trade(t, raw_price, o.reason or "Close", qty=q)
            else:
                self.close_trade(t, raw_price, o.reason or "Close")

    # ------------------------------------------------------------------ per-bar processing
    def on_bar_open(self, i: int) -> None:
        self.bar = i
        if not self.queue:
            return
        q, self.queue = self.queue, []
        price = self.bars.open[i]
        for o in q:
            if o.kind == "close":
                self._execute_close(o, price)
            else:
                self._execute_market(o, price)

    def on_bar_range(self, i: int) -> None:
        b = self.bars
        o_, h, l = b.open[i], b.high[i], b.low[i]
        # 1. protective exits for trades that were open before this bar's range unfolded
        for t in list(self.open):
            self._check_exits(t, o_, h, l)
        # 2. resting stop / limit orders
        filled_oco: set[str] = set()
        for o in list(self.pending):
            if o.expire_bar is not None and i > o.expire_bar:
                self.pending.remove(o)
                self.log("order", f"Order expired: {o.reason or o.tag}")
                continue
            if o.placed_bar >= i:
                continue  # placed at this bar's close: active from the next bar
            if o.oco and o.oco in filled_oco:
                self.pending.remove(o)
                continue
            px = self._trigger(o, o_, h, l)
            if px is None:
                continue
            self.pending.remove(o)
            if o.oco:
                filled_oco.add(o.oco)
            if o.close_side or o.close_ids is not None:
                self._execute_close(o, px)
            else:
                self._execute_market(o, px)
        if filled_oco:
            self.pending = [p for p in self.pending if p.oco not in filled_oco]
        # 3. excursions and trailing stops
        for t in self.open:
            if t.side > 0:
                t.mae = max(t.mae, t.entry_price - l)
                t.mfe = max(t.mfe, h - t.entry_price)
            else:
                t.mae = max(t.mae, h - t.entry_price)
                t.mfe = max(t.mfe, t.entry_price - l)
            if t.trail_dist:
                if t.side > 0:
                    t.best_price = max(t.best_price, h)
                    new = t.best_price - t.trail_dist
                    if t.sl is None or new > t.sl:
                        t.sl = new
                else:
                    t.best_price = min(t.best_price or t.entry_price, l)
                    new = t.best_price + t.trail_dist
                    if t.sl is None or new < t.sl:
                        t.sl = new

    @staticmethod
    def _trigger(o: Order, op: float, h: float, l: float) -> float | None:
        p = o.price
        if p is None:
            return None
        if o.kind == "limit":
            if o.side > 0 and l <= p:
                return min(op, p)
            if o.side < 0 and h >= p:
                return max(op, p)
        elif o.kind == "stop":
            if o.side > 0 and h >= p:
                return max(op, p)
            if o.side < 0 and l <= p:
                return min(op, p)
        return None

    def _check_exits(self, t: Trade, op: float, h: float, l: float) -> None:
        sl, tp = t.sl, t.tp
        if sl is None and tp is None:
            return
        trailing = bool(t.trail_dist)
        sl_reason = "Trailing stop" if trailing else "Stop loss"
        if t.side > 0:
            if sl is not None and op <= sl:
                self.close_trade(t, op, f"{sl_reason} (gap)")
            elif tp is not None and op >= tp:
                self.close_trade(t, op, "Take profit (gap)")
            elif sl is not None and l <= sl:
                self.close_trade(t, sl, sl_reason)
            elif tp is not None and h >= tp:
                self.close_trade(t, tp, "Take profit", slip=False)
        else:
            if sl is not None and op >= sl:
                self.close_trade(t, op, f"{sl_reason} (gap)")
            elif tp is not None and op <= tp:
                self.close_trade(t, op, "Take profit (gap)")
            elif sl is not None and h >= sl:
                self.close_trade(t, sl, sl_reason)
            elif tp is not None and l <= tp:
                self.close_trade(t, tp, "Take profit", slip=False)

    def mark(self, i: int) -> None:
        self.equity_curve.append(self.equity(self.bars.close[i]))

    def finish(self) -> None:
        last = len(self.bars) - 1
        self.bar = last
        if self.ignored_orders:
            self.log("info", f"{self.ignored_orders:,} entry order(s) were skipped because a position in that "
                             f"direction was already open (pyramiding limit {max(1, self.s.pyramiding)}).")
        if self.queue:
            self.log("info", f"{len(self.queue)} order(s) placed on the last bar were never filled (no next bar).")
            self.queue.clear()
        if self.s.close_at_end:
            for t in list(self.open):
                self.close_trade(t, self.bars.close[last], "End of data", slip=False)
            if self.equity_curve:
                self.equity_curve[-1] = self.equity(self.bars.close[last])
