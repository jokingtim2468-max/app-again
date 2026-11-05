"""Load OHLCV price history from almost any CSV export.

Recognised without configuration:
* MetaTrader 4/5 history exports (``<DATE> <TIME> <OPEN> …``, tab separated, or headerless
  ``2024.01.02,00:00,o,h,l,c,v``)
* TradingView chart exports (``time`` as unix seconds or ISO, ``open/high/low/close``)
* Yahoo Finance downloads (``Date,Open,High,Low,Close,Adj Close,Volume``)
* Compact ``yyyyMMdd HHmmss;o;h;l;c;v`` rows
* Any CSV with recognisable date/time and price column names, in any order and case.
"""

from __future__ import annotations

import csv
import io
import os
import re

import numpy as np
import pandas as pd

from ..core.bars import Bars
from ..errors import DataError

ALIASES = {
    "open": ["open", "o", "<open>", "open price", "opening price", "first"],
    "high": ["high", "h", "<high>", "high price", "max"],
    "low": ["low", "l", "<low>", "low price", "min"],
    "close": ["close", "c", "<close>", "close price", "last", "price", "adj close*", "close/last"],
    "volume": ["volume", "vol", "v", "<vol>", "<tickvol>", "tickvol", "tick volume", "<volume>", "tick_volume", "real_volume"],
    "datetime": ["datetime", "date time", "timestamp", "time", "date", "<date>", "gmt time", "local time",
                 "open time", "opentime", "date_time", "dt", "unix", "<dtyyyymmdd>"],
    "time_only": ["<time>", "time"],
}


def _norm(c: str) -> str:
    return re.sub(r"\s+", " ", str(c).strip().lower().replace("﻿", ""))


def _sniff(text: str) -> tuple[str, bool]:
    sample = "\n".join(text.splitlines()[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t| ")
        delim = dialect.delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in [",", ";", "\t", "|"]}
        delim = max(counts, key=counts.get)
    first = text.splitlines()[0] if text else ""
    has_header = bool(re.search(r"[A-Za-z<]", first.split(delim)[0] + (first.split(delim)[1] if delim in first else ""))) \
        and not re.match(r"^\s*\d{4}[.\-/]\d{2}", first)
    return delim, has_header


def _parse_times(series: pd.Series, extra: pd.Series | None = None) -> np.ndarray:
    s = series.astype(str).str.strip()
    if extra is not None:
        s = s + " " + extra.astype(str).str.strip()
    # Unix timestamps (seconds or ms)
    if re.fullmatch(r"\d{9,13}(\.\d+)?", s.iloc[0]):
        v = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
        if np.nanmedian(v) < 1e11:
            v = v * 1000
        return v.astype(np.int64)
    # compact 20240102 093000
    if re.fullmatch(r"\d{8} \d{6}", s.iloc[0]):
        dt = pd.to_datetime(s, format="%Y%m%d %H%M%S", errors="coerce", utc=True)
    elif re.fullmatch(r"\d{8}", s.iloc[0]):
        dt = pd.to_datetime(s, format="%Y%m%d", errors="coerce", utc=True)
    else:
        s2 = s.str.replace(r"^(\d{4})\.(\d{2})\.(\d{2})", r"\1-\2-\3", regex=True)  # MT 2024.01.02
        dt = pd.to_datetime(s2, errors="coerce", utc=True, format="mixed")
    if dt.isna().mean() > 0.2:
        raise DataError("Couldn't read the date/time column.",
                        hint=f"First value looks like '{s.iloc[0]}'. Use ISO dates like 2024-01-31 or 2024-01-31 14:30.")
    return (dt.astype("int64") // 1_000_000).to_numpy()


def _pick(cols: list[str], names: list[str]) -> str | None:
    for n in names:
        if n.endswith("*"):
            for c in cols:
                if c.startswith(n[:-1]):
                    return c
        elif n in cols:
            return n
    return None


def load_csv(path_or_text: str, symbol: str | None = None, *, is_text: bool = False) -> Bars:
    if is_text:
        text = path_or_text
        name = symbol or "DATA"
    else:
        if not os.path.exists(path_or_text):
            raise DataError(f"File not found: {path_or_text}")
        with open(path_or_text, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        name = symbol or os.path.splitext(os.path.basename(path_or_text))[0]
    if not text.strip():
        raise DataError("The data file is empty.")
    delim, has_header = _sniff(text)
    try:
        df = pd.read_csv(io.StringIO(text), sep=delim, header=0 if has_header else None, engine="python",
                         skipinitialspace=True)
    except Exception as e:  # pragma: no cover - pandas error text is good enough
        raise DataError(f"Couldn't parse the CSV: {e}") from e
    df = df.dropna(axis=1, how="all")

    if not has_header:
        df = _headerless(df)
    df.columns = [_norm(c) for c in df.columns]
    cols = list(df.columns)

    o = _pick(cols, ALIASES["open"])
    h = _pick(cols, ALIASES["high"])
    l = _pick(cols, ALIASES["low"])
    c = _pick(cols, [x for x in ALIASES["close"] if x != "adj close*"]) or _pick(cols, ["adj close*"])
    v = _pick(cols, ALIASES["volume"])
    if c is None:
        raise DataError("No close/price column found.",
                        hint="Name the columns Date, Open, High, Low, Close, Volume (any order).")

    date_col = "<date>" if "<date>" in cols else _pick(cols, ALIASES["datetime"])
    time_col = "<time>" if "<time>" in cols and date_col == "<date>" else None
    if date_col == "date" and "time" in cols:
        time_col = "time"
    if date_col is None:
        raise DataError("No date/time column found.", hint="Add a column named Date or Time.")
    times = _parse_times(df[date_col], df[time_col] if time_col else None)

    def num(col, fallback):
        if col is None:
            return fallback
        return pd.to_numeric(df[col].astype(str).str.replace(",", "", regex=False), errors="coerce").to_numpy(float)

    close = num(c, None)
    open_ = num(o, close)
    high = num(h, np.maximum(open_, close))
    low = num(l, np.minimum(open_, close))
    vol = num(v, np.zeros(len(close)))
    mask = np.isfinite(close) & np.isfinite(open_) & np.isfinite(high) & np.isfinite(low)
    order = np.argsort(times[mask], kind="stable")
    t = times[mask][order]
    keep = np.concatenate([[True], np.diff(t) > 0]) if len(t) else np.array([], bool)
    bars = Bars.from_arrays(t[keep], open_[mask][order][keep], high[mask][order][keep], low[mask][order][keep],
                            close[mask][order][keep], np.nan_to_num(vol[mask][order][keep]), name.upper(),
                            infer_timeframe(t[keep]))
    if len(bars) < 2:
        raise DataError("Fewer than 2 usable rows of prices in the file.")
    # repair rows where high/low don't bracket open/close (common in hand-made CSVs)
    bars.high = np.maximum.reduce([bars.high, bars.open, bars.close])
    bars.low = np.minimum.reduce([bars.low, bars.open, bars.close])
    bars.meta["source"] = "csv"
    bars.meta["rows_dropped"] = int(len(df) - len(bars))
    return bars


def _headerless(df: pd.DataFrame) -> pd.DataFrame:
    n = df.shape[1]
    first = str(df.iloc[0, 0])
    second = str(df.iloc[0, 1]) if n > 1 else ""
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", second):  # MT4: date,time,o,h,l,c,v
        names = ["date", "time", "open", "high", "low", "close", "volume", "x1", "x2"][:n]
    elif re.fullmatch(r"\d{8} \d{6}", first) or re.fullmatch(r"\d{4}[.\-/]\d{2}[.\-/]\d{2}.*", first) or re.fullmatch(r"\d{9,13}", first):
        names = ["datetime", "open", "high", "low", "close", "volume", "x1", "x2"][:n]
    else:
        raise DataError("The CSV has no header row and an unrecognised layout.",
                        hint="Add a header: Date,Open,High,Low,Close,Volume")
    df.columns = names
    return df


TF_LABELS = [(60_000, "1m"), (300_000, "5m"), (900_000, "15m"), (1_800_000, "30m"), (3_600_000, "1h"),
             (14_400_000, "4h"), (86_400_000, "1d"), (604_800_000, "1w")]


def infer_timeframe(times: np.ndarray) -> str:
    if len(times) < 3:
        return "?"
    d = float(np.median(np.diff(times)))
    for ms, label in TF_LABELS:
        if d <= ms * 1.05:
            return label
    return "1mo" if d < 40 * 86_400_000 else "?"


RULES = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h",
         "4h": "4h", "1d": "1D", "1w": "W-FRI", "1mo": "MS"}


def resample(bars: Bars, timeframe: str) -> Bars:
    rule = RULES.get(timeframe)
    if not rule:
        raise DataError(f"Unknown timeframe '{timeframe}'.", hint="Use one of " + ", ".join(RULES))
    idx = pd.to_datetime(bars.time, unit="ms", utc=True)
    df = pd.DataFrame({"open": bars.open, "high": bars.high, "low": bars.low, "close": bars.close,
                       "volume": bars.volume}, index=idx)
    r = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    out = Bars.from_arrays(r.index.astype("int64") // 1_000_000, r.open, r.high, r.low, r.close, r.volume,
                           bars.symbol, timeframe)
    out.meta = dict(bars.meta)
    return out


def describe(bars: Bars) -> dict:
    return {"symbol": bars.symbol, "timeframe": bars.timeframe, "bars": len(bars),
            "start": int(bars.time[0]), "end": int(bars.time[-1]),
            "first": float(bars.close[0]), "last": float(bars.close[-1]),
            "source": bars.meta.get("source", "csv")}
