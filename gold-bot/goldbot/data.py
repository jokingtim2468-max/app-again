"""Load the processed datasets built by scripts/build_dataset.py."""
from __future__ import annotations

import pandas as pd

from .config import NY, PROCESSED, SESSION_CLOSE_HOUR_ET


def last_complete_session() -> pd.Timestamp:
    now = pd.Timestamp.now(tz=NY)
    day = now.normalize().tz_localize(None)
    return day if now.hour >= SESSION_CLOSE_HOUR_ET else day - pd.Timedelta(days=1)


def load_daily(drop_forming: bool = True) -> pd.DataFrame:
    """Spot-equivalent gold OHLC per CME session (17:00 ET close)."""
    d = pd.read_parquet(PROCESSED / "xau_d1.parquet")
    if drop_forming:
        d = d[d.index <= last_complete_session()]
    return d


def load_macro() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / "macro_d1.parquet").sort_index()


def latest_futures_close(symbol: str = "micro_gold_fut") -> tuple[pd.Timestamp, float]:
    """Last daily close of a futures series from the macro table (Yahoo)."""
    s = load_macro()[symbol].dropna()
    return s.index[-1], float(s.iloc[-1])
