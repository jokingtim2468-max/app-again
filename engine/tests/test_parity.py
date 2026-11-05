"""The same SMA 10/30 cross written in every supported script type must trade identically."""
import os

import pytest

from conftest import EX, GOLD
from tickbench.runner import run

EXACT = ["sma_cross_native.py", "sma_cross_backtesting.py", "sma_cross_backtrader.py", "sma_cross_rules.json",
         "sma_cross.js", "sma_cross.pine", "sma_cross.mq4", "sma_cross.mq5", "tradovate_crossover_strategy.js"]
SETTINGS = {"point_value": 1, "default_qty": 1}


def trades(name):
    r = run({"path": os.path.join(EX, "strategies", name)}, {"source": "csv", "path": GOLD}, SETTINGS)
    return r, [(t["entryBar"], t["exitBar"], round(t["entryPrice"], 6), round(t["exitPrice"], 6)) for t in r["trades"]]


@pytest.fixture(scope="module")
def reference():
    return trades("sma_cross_native.py")[1]


@pytest.mark.parametrize("name", EXACT)
def test_identical_trades(name, reference):
    r, t = trades(name)
    assert r["script"]["kind"] != "unknown"
    assert t == reference, f"{name} differs from the native reference"


def test_tradovate_indicator_matches_within_float_noise(reference):
    # Tradovate's tools/SMA keeps a running sum; on one near-tie bar it crosses one bar later.
    _, t = trades("tradovate_two_sma_indicator.js")
    assert len(t) == len(reference)
    diffs = [(a, b) for a, b in zip(t, reference) if a != b]
    assert len(diffs) <= 1
    for a, b in diffs:
        assert a[0] == b[0] and abs(a[1] - b[1]) <= 1
