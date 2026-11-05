import numpy as np

from tickbench import stats
from tickbench.core.bars import Bars
from tickbench.core.broker import Trade


def test_drawdown_and_profit_factor():
    t = np.arange(5) * 86_400_000
    b = Bars.from_arrays(t, [1] * 5, [1] * 5, [1] * 5, [1] * 5)
    eq = np.array([100.0, 120.0, 90.0, 110.0, 130.0])
    trades = [Trade(1, 1, 1, 0, 0, 1, exit_bar=1, exit_time=1, exit_price=2, pnl=30.0),
              Trade(2, 1, 1, 1, 0, 1, exit_bar=2, exit_time=2, exit_price=1, pnl=-10.0),
              Trade(3, 1, 1, 2, 0, 1, exit_bar=4, exit_time=4, exit_price=2, pnl=10.0)]
    s = stats.compute(b, eq, trades, 100.0, eq)
    assert round(s["maxDrawdownPct"], 6) == 25.0
    assert s["maxDrawdown"] == 30.0
    assert s["profitFactor"] == 4.0
    assert round(s["winRate"], 4) == round(2 / 3 * 100, 4)
    assert s["maxConsecWins"] == 1 and s["trades"] == 3
    assert s["netProfit"] == 30.0


def test_monthly_returns():
    t = np.array([0, 31, 59]) * 86_400_000  # Jan 1, Feb 1, Mar 1 1970
    m = stats.monthly_returns(t, np.array([100.0, 110.0, 99.0]))
    assert [round(x["pct"], 6) for x in m] == [0.0, 10.0, -10.0]
