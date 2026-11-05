import os

import pytest

from conftest import EX
from tickbench.detect import detect

EXPECT = {
    "sma_cross.pine": "pine", "sma_cross.mq4": "mql4", "sma_cross.mq5": "mql5",
    "sma_cross_native.py": "python-native", "sma_cross_backtesting.py": "backtesting.py",
    "sma_cross_backtrader.py": "backtrader", "sma_cross.js": "javascript", "sma_cross_rules.json": "rules-json",
    "tradovate_two_sma_indicator.js": "tradovate-indicator",
    "tradovate_crossover_strategy.js": "tradovate-strategy",
}


@pytest.mark.parametrize("name,kind", EXPECT.items())
def test_examples(name, kind):
    src = open(os.path.join(EX, "strategies", name), encoding="utf-8").read()
    assert detect(src, name)["type"] == kind


@pytest.mark.parametrize("name,kind", EXPECT.items())
def test_without_extension(name, kind):
    """Content alone must be enough (files pasted or saved as .txt)."""
    src = open(os.path.join(EX, "strategies", name), encoding="utf-8").read()
    got = detect(src, "pasted.txt")["type"]
    if kind == "rules-json":
        assert got == "rules-json"
    else:
        assert got == kind


def test_pine_v4_and_yaml():
    assert detect('//@version=4\nstudy("x")\nplot(sma(close, 10))', "")["type"] == "pine"
    y = "params:\n  fast: 10\nindicators:\n  f: {type: sma, length: 10}\nentry_long:\n  '>': [close, f]\n"
    assert detect(y, "r.yaml")["type"] == "rules-yaml"


def test_unknown():
    assert detect("hello world", "a.txt")["type"] == "unknown"
