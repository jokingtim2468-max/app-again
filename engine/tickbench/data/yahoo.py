"""Free historical prices from Yahoo Finance (via yfinance), cached on disk.

Yahoo's limits: 1m bars for the last ~7 days, 2m–30m for ~60 days, 1h for ~730 days,
daily and weekly for decades. Futures use the ``=F`` suffix (ES=F, GC=F), forex ``=X``
(EURUSD=X), crypto ``-USD`` (BTC-USD).
"""

from __future__ import annotations

import hashlib
import json
import os
import time

import numpy as np

from ..core.bars import Bars, to_epoch_ms
from ..errors import DataError
from .loader import infer_timeframe

INTERVALS = {"1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m",
             "1d": "1d", "1w": "1wk", "1mo": "1mo"}
MAX_DAYS = {"1m": 7, "2m": 59, "5m": 59, "15m": 59, "30m": 59, "1h": 729}

# Friendly names people type -> Yahoo tickers
SYMBOL_ALIASES = {
    "XAUUSD": "GC=F", "GOLD": "GC=F", "XAGUSD": "SI=F", "SILVER": "SI=F", "OIL": "CL=F", "WTI": "CL=F",
    "ES": "ES=F", "MES": "MES=F", "NQ": "NQ=F", "MNQ": "MNQ=F", "YM": "YM=F", "MYM": "MYM=F",
    "RTY": "RTY=F", "M2K": "M2K=F", "CL": "CL=F", "MCL": "MCL=F", "GC": "GC=F", "MGC": "MGC=F",
    "SI": "SI=F", "ZB": "ZB=F", "ZN": "ZN=F", "6E": "6E=F", "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
    "SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI", "US30": "^DJI", "US500": "^GSPC", "NAS100": "^NDX",
}


def resolve_symbol(sym: str) -> str:
    s = sym.strip().upper()
    if s in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[s]
    if len(s) == 6 and s.isalpha() and s[:3] in {"EUR", "GBP", "USD", "AUD", "NZD", "CAD", "CHF", "JPY"}:
        return s + "=X"
    return s


def cache_dir() -> str:
    base = os.environ.get("TICKBENCH_DATA") or os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~/.local/share"), "Tickbench")
    d = os.path.join(base, "cache")
    os.makedirs(d, exist_ok=True)
    return d


def download(symbol: str, interval: str = "1d", start: str | None = None, end: str | None = None,
             max_age_hours: float = 12) -> Bars:
    if interval not in INTERVALS:
        raise DataError(f"Yahoo doesn't offer a '{interval}' interval.", hint="Try " + ", ".join(INTERVALS))
    ticker = resolve_symbol(symbol)
    key = hashlib.sha1(json.dumps([ticker, interval, start, end]).encode()).hexdigest()[:16]
    path = os.path.join(cache_dir(), f"{ticker.replace('^', '_').replace('=', '_')}_{interval}_{key}.npz")
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_hours * 3600:
        z = np.load(path)
        b = Bars.from_arrays(z["t"], z["o"], z["h"], z["l"], z["c"], z["v"], ticker, interval)
        b.meta.update(source="yahoo", cached=True, ticker=ticker)
        return b
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover
        raise DataError("yfinance is not installed in this build.") from e
    kwargs = {"interval": INTERVALS[interval], "auto_adjust": False, "progress": False, "threads": False}
    if start:
        kwargs["start"] = start
        if end:
            kwargs["end"] = end
    else:
        kwargs["period"] = f"{MAX_DAYS[interval]}d" if interval in MAX_DAYS else "max"
    try:
        df = yf.download(ticker, **kwargs)
    except Exception as e:
        raise DataError(f"Yahoo download failed for {ticker}: {e}",
                        hint="Check your internet connection, or import a CSV instead.") from e
    if df is None or df.empty:
        hint = "Check the symbol on finance.yahoo.com."
        if interval in MAX_DAYS:
            hint += f" Yahoo only keeps about {MAX_DAYS[interval]} days of {interval} bars."
        raise DataError(f"Yahoo returned no data for {ticker} ({interval}).", hint=hint)
    if hasattr(df.columns, "levels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Close"])
    t = to_epoch_ms(df.index)
    b = Bars.from_arrays(np.asarray(t), df["Open"].to_numpy(float), df["High"].to_numpy(float),
                         df["Low"].to_numpy(float), df["Close"].to_numpy(float),
                         df["Volume"].fillna(0).to_numpy(float) if "Volume" in df else None, ticker, interval)
    if len(b) < 2:
        raise DataError(f"Yahoo returned only {len(b)} bar(s) for {ticker}.")
    np.savez_compressed(path, t=b.time, o=b.open, h=b.high, l=b.low, c=b.close, v=b.volume)
    b.timeframe = interval if interval else infer_timeframe(b.time)
    b.meta.update(source="yahoo", cached=False, ticker=ticker)
    return b
