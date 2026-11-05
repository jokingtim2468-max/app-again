"""Point-in-time feature library.

Row d = the session that closed at 17:00 ET on date d. Every feature in row d
uses only information available at that close, so the model can be run each
evening to forecast the next 1 / 5 / 21 / 63 sessions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def atr(d: pd.DataFrame, n: int = 14) -> pd.Series:
    c = d.Close
    tr = pd.concat([d.High - d.Low, (d.High - c.shift()).abs(), (d.Low - c.shift()).abs()],
                   axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _slope(logp: pd.Series, n: int) -> pd.Series:
    x = np.arange(n) - (n - 1) / 2
    denom = (x ** 2).sum()
    return logp.rolling(n).apply(lambda y: float((x * (y - y.mean())).sum() / denom), raw=True)


def price_features(d: pd.DataFrame) -> pd.DataFrame:
    c, h, l, o = d.Close, d.High, d.Low, d.Open
    r = np.log(c).diff()
    a = atr(d)
    atr_pct = a / c
    f = pd.DataFrame(index=d.index)
    f["atr_pct"] = atr_pct
    for k in (1, 2, 3, 5, 10, 21, 63, 126, 252):
        f[f"ret_{k}"] = np.log(c / c.shift(k))
        if k >= 5:
            f[f"ret_{k}_z"] = f[f"ret_{k}"] / (r.rolling(63).std() * np.sqrt(k))
    # candle shape (ATR units)
    f["body"] = (c - o) / a
    f["upper_wick"] = (h - np.maximum(o, c)) / a
    f["lower_wick"] = (np.minimum(o, c) - l) / a
    f["range_atr"] = (h - l) / a
    f["close_loc"] = (c - l) / (h - l)
    # volatility regime
    for n in (5, 21, 63, 126):
        f[f"vol_{n}"] = r.rolling(n).std() * np.sqrt(252)
    f["vol_ratio_5_63"] = f["vol_5"] / f["vol_63"]
    f["vol_ratio_21_126"] = f["vol_21"] / f["vol_126"]
    f["atr_pct_rank_252"] = atr_pct.rolling(252).rank(pct=True)
    # oscillators
    f["rsi_2"] = rsi(c, 2)
    f["rsi_14"] = rsi(c, 14)
    f["rsi_63"] = rsi(c, 63)
    # trend / mean distance (ATR units)
    for n in (10, 21, 50, 100, 200):
        f[f"dist_sma{n}"] = (c - c.rolling(n).mean()) / a
    f["sma50_over_200"] = c.rolling(50).mean() / c.rolling(200).mean() - 1
    logp = np.log(c)
    f["slope_21"] = _slope(logp, 21) / atr_pct
    f["slope_63"] = _slope(logp, 63) / atr_pct
    # where are we inside recent highs/lows (the levels traders watch)
    for n in (5, 21, 63, 252):
        hi, lo = h.rolling(n).max(), l.rolling(n).min()
        f[f"pos_{n}"] = (c - lo) / (hi - lo)
        f[f"to_hi_{n}"] = (hi - c) / a
        f[f"to_lo_{n}"] = (c - lo) / a
    f["drawdown_ath"] = c / c.cummax() - 1
    f["days_since_hi_63"] = h.rolling(63).apply(lambda x: 62 - int(np.argmax(x)), raw=True)
    f["days_since_lo_63"] = l.rolling(63).apply(lambda x: 62 - int(np.argmin(x)), raw=True)
    # previous calendar week / month levels
    # labels are period ends, so forward-filling onto days gives the last *completed*
    # week / month (complete at that Friday's / month-end's close) with no look-ahead
    wk = d.resample("W-FRI").agg({"High": "max", "Low": "min"})
    mo = d.resample("ME").agg({"High": "max", "Low": "min"})
    wk = wk.reindex(d.index, method="ffill")
    mo = mo.reindex(d.index, method="ffill")
    f["to_prev_wk_hi"] = (wk.High - c) / a
    f["to_prev_wk_lo"] = (c - wk.Low) / a
    f["to_prev_mo_hi"] = (mo.High - c) / a
    f["to_prev_mo_lo"] = (c - mo.Low) / a
    # streaks
    f["up_streak"] = (r > 0).astype(int).groupby((r <= 0).cumsum()).cumsum()
    f["dn_streak"] = (r < 0).astype(int).groupby((r >= 0).cumsum()).cumsum()
    # calendar
    f["dow"] = d.index.day_of_week
    f["month"] = d.index.month
    f["day_of_month"] = d.index.day
    return f


def macro_features(dates: pd.DatetimeIndex, macro: pd.DataFrame) -> pd.DataFrame:
    """Cross-asset features as of each session close (latest value on or before d)."""
    m = macro.ffill()
    f = pd.DataFrame(index=m.index)
    for col in ("dxy", "spx", "silver_fut", "wti_fut", "copper_fut", "eurusd", "usdjpy",
                "tip", "gdx", "gld", "btc"):
        lp = np.log(m[col])
        for k in (1, 5, 21, 63):
            f[f"{col}_r{k}"] = lp.diff(k)
    for col in ("us10y", "us3m", "us30y", "us5y"):
        for k in (1, 5, 21):
            f[f"{col}_d{k}"] = m[col].diff(k)
    f["us10y"] = m["us10y"]
    f["curve_10y3m"] = m["us10y"] - m["us3m"]
    f["curve_30y5y"] = m["us30y"] - m["us5y"]
    for col in ("vix", "gvz", "move"):
        f[col] = m[col]
        f[f"{col}_d5"] = m[col].diff(5)
        f[f"{col}_rank_252"] = m[col].rolling(252, min_periods=60).rank(pct=True)
    f["gold_silver_ratio"] = m["gold_fut"] / m["silver_fut"]
    f["gsr_z_252"] = (f["gold_silver_ratio"] - f["gold_silver_ratio"].rolling(252).mean()) / \
        f["gold_silver_ratio"].rolling(252).std()
    f["gdx_gld_r21"] = np.log(m["gdx"] / m["gld"]).diff(21)
    # futures curve carry proxy: front future vs spot ETF is not available; use GC vs MGC
    out = pd.merge_asof(pd.DataFrame(index=dates).reset_index(names="date"),
                        f.reset_index(names="mdate").sort_values("mdate"),
                        left_on="date", right_on="mdate", direction="backward")
    out = out.set_index("date")
    stale = (out.index - out["mdate"]).dt.days
    out = out.drop(columns="mdate")
    out.loc[stale > 5] = np.nan  # don't carry macro data across long gaps
    return out


def build_features(d: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    X = price_features(d).join(macro_features(d.index, macro))
    return X.replace([np.inf, -np.inf], np.nan)
