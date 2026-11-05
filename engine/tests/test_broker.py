import numpy as np

from tickbench.core.bars import Bars
from tickbench.core.broker import Broker, Settings


def bars(rows):
    t = np.arange(len(rows)) * 86_400_000
    o, h, l, c = zip(*rows)
    return Bars.from_arrays(t, o, h, l, c)


def mk(rows, **s):
    logs = []
    b = Broker(bars(rows), Settings(**s), lambda *a, **k: logs.append(a))
    return b, logs


def step(b, i):
    b.on_bar_open(i)
    b.on_bar_range(i)
    b.mark(i)


def test_market_order_fills_next_open():
    b, _ = mk([(10, 11, 9, 10), (12, 13, 11, 12), (12, 12, 12, 12)])
    step(b, 0)
    b.submit_market(1, 1)
    step(b, 1)
    assert b.open[0].entry_price == 12 and b.open[0].entry_bar == 1


def test_stop_hit_first_when_bar_touches_both():
    b, _ = mk([(100, 100, 100, 100), (100, 110, 90, 100)])
    step(b, 0)
    b.submit_market(1, 1, sl=95, tp=105, immediate=True)
    step(b, 1)
    t = b.trades[0]
    assert t.exit_price == 95 and t.exit_reason == "Stop loss"


def test_gap_through_stop_fills_at_open():
    b, _ = mk([(100, 100, 100, 100), (90, 92, 88, 91)])
    b.on_bar_open(0)
    b.submit_market(1, 1, sl=95, immediate=True)
    b.on_bar_range(0)
    b.mark(0)
    step(b, 1)
    assert b.trades[0].exit_price == 90 and "gap" in b.trades[0].exit_reason


def test_commission_and_point_value():
    b, _ = mk([(100, 100, 100, 100), (100, 100, 100, 100), (110, 110, 110, 110)], commission_per_unit=2.0,
              point_value=50.0, integer_qty=True)
    step(b, 0)
    b.submit_market(1, 1)
    step(b, 1)
    b.submit_close()
    step(b, 2)
    t = b.trades[0]
    assert t.pnl == (110 - 100) * 50 - 4.0
    assert b.cash == 10_000 + t.pnl


def test_reverse_in_netting_mode():
    b, _ = mk([(100, 100, 100, 100)] * 3)
    step(b, 0)
    b.submit_market(1, 1)
    step(b, 1)
    b.submit_market(-1, 1)
    step(b, 2)
    assert b.trades[0].exit_bar == 2 and b.open[0].side == -1


def test_net_order_reduces_instead_of_reversing():
    b, _ = mk([(100, 100, 100, 100)] * 3)
    step(b, 0)
    b.submit_market(1, 2)
    step(b, 1)
    b.submit_market(-1, 1, net=True)
    step(b, 2)
    assert b.position_size == 1


def test_trailing_stop_follows_high():
    b, _ = mk([(100, 100, 100, 100), (100, 120, 100, 119), (118, 118, 105, 106)])
    b.on_bar_open(0)
    b.submit_market(1, 1, trail=5, immediate=True)
    b.on_bar_range(0)
    b.mark(0)
    step(b, 1)
    step(b, 2)
    t = b.trades[0]
    assert t.exit_price == 115 and t.exit_reason == "Trailing stop"


def test_limit_order_fills_at_better_open():
    b, _ = mk([(100, 100, 100, 100), (95, 99, 94, 98)])
    step(b, 0)
    b.submit_pending("limit", 1, 97, 1)
    step(b, 1)
    assert b.trades[0].entry_price == 95
