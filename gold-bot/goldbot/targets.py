"""Forward targets for each horizon h (sessions after the close of row d).

    up_atr  = (max High over d+1..d+h - Close_d) / ATR_d     -> how far above
    dn_atr  = (Close_d - min Low over d+1..d+h) / ATR_d      -> how far below
    ret     = log(Close_{d+h} / Close_d)
    y_up    = 1 if ret > 0 (bullish over the horizon)
    y3      = +1 / 0 / -1 using a +-0.25 * ATR * sqrt(h) dead-band
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import atr


def forward_targets(d: pd.DataFrame, h: int) -> pd.DataFrame:
    a = atr(d)
    c = d.Close
    fwd_hi = d.High[::-1].rolling(h, min_periods=h).max()[::-1].shift(-1)
    fwd_lo = d.Low[::-1].rolling(h, min_periods=h).min()[::-1].shift(-1)
    fwd_c = c.shift(-h)
    t = pd.DataFrame(index=d.index)
    t["up_atr"] = (fwd_hi - c) / a
    t["dn_atr"] = (c - fwd_lo) / a
    t["ret"] = np.log(fwd_c / c)
    t["y_up"] = (t["ret"] > 0).astype(float)
    band = 0.25 * (a / c) * np.sqrt(h)
    t["y3"] = np.select([t["ret"] > band, t["ret"] < -band], [1, -1], 0).astype(float)
    t.loc[fwd_c.isna(), ["y_up", "y3"]] = np.nan
    t["atr"] = a
    t["close"] = c
    return t
