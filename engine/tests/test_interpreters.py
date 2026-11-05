"""Language edge cases for the Pine and MQL interpreters."""
import numpy as np

from tickbench.adapters.mql.adapter import MqlAdapter
from tickbench.adapters.pine.adapter import PineAdapter
from tickbench.core.bars import Bars
from tickbench.core.broker import Settings
from tickbench.core.engine import run_backtest


def data(n=120):
    t = np.arange(n) * 86_400_000
    c = 100 + np.sin(np.arange(n) / 6) * 10
    return Bars.from_arrays(t, c, c + 1, c - 1, c)


def logs(ctx):
    return [e["text"] for e in ctx.events if e["kind"] == "log"]


def test_pine_var_history_function_switch_tuple():
    src = '''//@version=5
strategy("t")
var int n = 0
n += 1
f(x) =>
    x * 2
[a, b] = [close, close[1]]
s = switch
    n == 3 => "three"
    => "other"
if barstate.islast
    log.info(str.tostring(n) + " " + s + " " + str.tostring(f(3)) + " " + str.tostring(na(b[200])))
'''
    ctx = run_backtest(data(), PineAdapter(src), Settings())
    assert logs(ctx)[-1] == "120 other 6 true"


def test_pine_for_loop_and_series_in_function():
    src = '''//@version=5
strategy("t")
mysum(src, n) =>
    t = 0.0
    for i = 0 to n - 1
        t += src[i]
    t
s = mysum(close, 3)
if bar_index == 10
    log.info(str.tostring(math.round(s - (close + close[1] + close[2]), 6)))
'''
    ctx = run_backtest(data(), PineAdapter(src), Settings())
    assert logs(ctx) == ["0"]


def test_mql_integer_division_switch_static_ref():
    src = '''
void bump(int &x) { x = x + 1; }
int counter() { static int c = 0; c++; return c; }
void OnTick()
{
   if(Bars != 5) return;
   int a = 7 / 2;
   double b = 7 / 2.0;
   int r = 0;
   switch(a) { case 2: r = 20; case 3: r = 30; break; default: r = -1; }
   int z = 1; bump(z);
   counter(); int c = counter();
   Print(a, " ", DoubleToString(b, 1), " ", r, " ", z, " ", c);
}
'''
    ctx = run_backtest(data(), MqlAdapter(src, "t.mq5", "mql5"), Settings(hedging=True))
    assert logs(ctx) == ["3 3.5 30 2 2"]


def test_mql_arrays_as_series():
    src = '''
void OnTick()
{
   if(Bars != 10) return;
   double c[];
   ArraySetAsSeries(c, true);
   CopyClose(_Symbol, PERIOD_CURRENT, 1, 3, c);
   Print(c[0] == iClose(_Symbol, 0, 1), " ", c[2] == iClose(_Symbol, 0, 3));
}
'''
    ctx = run_backtest(data(), MqlAdapter(src, "t.mq5", "mql5"), Settings(hedging=True))
    assert logs(ctx) == ["true true"]
