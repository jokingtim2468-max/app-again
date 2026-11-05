"""Purged walk-forward splits (no look-ahead between train and test).

For a horizon of h sessions, the target of a training row looks h sessions ahead,
so the last h rows before a test block are dropped from training (purge), plus an
extra embargo. Test blocks are calendar years.
"""
from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd


def yearly_purged_splits(index: pd.DatetimeIndex, h: int, first_test_year: int = 2012,
                         embargo: int = 5, min_test: int = 20
                         ) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
    years = index.year
    pos = np.arange(len(index))
    for y in range(first_test_year, int(years.max()) + 1):
        te = pos[years == y]
        if len(te) < min_test:
            continue
        cut = te[0] - h - embargo
        tr = pos[:max(cut, 0)]
        if len(tr) < 500:
            continue
        yield y, tr, te
