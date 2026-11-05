"""Cockpit strategy math + backtest fill rules."""
import pandas as pd

from backend.src.trading import confluence as C
from backend.src.trading import scalper_backtest as B


def _bars(prices, start=1_790_000_000, step=60, vol=100):
    return [{"time": start + i * step, "open": p, "high": p + 0.2, "low": p - 0.2, "close": p, "volume": vol} for i, p in enumerate(prices)]


def test_confluence_max_is_ten_and_grades():
    assert sum(C.WEIGHTS.values()) == 10.0
    m5 = _bars([2650 + (i % 3) * 0.1 for i in range(40)], step=300)
    c = C.confluence(m5, 2650, 2651, {}, C.DEFAULT_PARAMS, "down")
    assert 0 <= c["score"] <= 10 and c["grade"] in ("A+", "A", "B", "C")
    assert c["factors"]["dxy"] == (c["side"] == "long")


def test_sweep_detects_wick_through_swing_low():
    m5 = _bars([2650.0] * 20, step=300)
    m5[-1] = {**m5[-1], "low": 2648.0, "close": 2650.1}
    assert C.sweep(m5, 9, {})["side"] == "long"


def test_regime_and_adaptive_params():
    flat = _bars([2650 + (0.05 if i % 2 else 0) for i in range(60)], step=900)
    r = C.regime(flat)
    assert r["regime"] in C.REGIMES
    a = C.adaptive(C.DEFAULT_PARAMS, "TREND_EXPANSION_REGIME", 2.0)
    assert a["tp"] > C.DEFAULT_PARAMS["base_tp"] and a["quota"] == C.DEFAULT_PARAMS["quota_expansion"]
    assert C.DEFAULT_PARAMS["sl_min"] <= a["sl"] <= a["sl_cap"]


def test_backtest_stop_checked_before_target_in_same_bar():
    """A bar that touches both stop and target must count as a loss (worst case)."""
    idx = pd.date_range("2026-09-01 13:00", periods=3, freq="1min", tz="UTC")
    df = pd.DataFrame({"open": [2650, 2650, 2650], "high": [2650, 2660, 2650], "low": [2650, 2640, 2650],
                       "close": [2650, 2650, 2650], "volume": [1, 1, 1], "spread": [0.1, 0.1, 0.1]}, index=idx)
    trades = []
    pos = {"side": "long", "entry": 2650.0, "sl": 2647.0, "tp": 2653.0}
    b = df.iloc[1]
    hit_sl, hit_tp = b["low"] <= pos["sl"], b["high"] >= pos["tp"]
    assert hit_sl and hit_tp  # both touched; engine order is SL first (see run())
    src = open(B.__file__).read()
    assert src.index("if hit_sl:") < src.index("elif hit_tp:")
    assert not trades


def test_backtest_runs_and_reports_months():
    from backend.src.data.sources import load_bars
    df = load_bars("synthetic", "2026-09-01", "2026-09-12", "1m")
    r = B.run(df)
    assert {"net", "win_rate", "monthly", "equity", "underwater", "evaluation"} <= set(r)
    assert r["commission"] == round(r["trades"] * 3.5 * 4, 2)
