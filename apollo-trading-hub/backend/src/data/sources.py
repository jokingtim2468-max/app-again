"""Unified historical data loading for the backtester: synthetic | csv | mt5.

Bars: pandas DataFrame indexed by UTC timestamp with open, high, low, close, volume, spread (price units).
Tick-days: {date_ET: (secs_of_day[08:00-16:59], price, spread_ticks)} for the 1-second tick engine.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..trading.risk_sentinel import ET
from . import mt5_data

RULE = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1D"}


def _utc(d: str, end: bool = False) -> datetime:
    dt = datetime.fromisoformat(d)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt + timedelta(days=1) if end and len(d) == 10 else dt


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(float)
    df["volume"] = df.get("volume", pd.Series(1, index=df.index)).fillna(0).astype(float)
    df["spread"] = df.get("spread", pd.Series(np.nan, index=df.index)).astype(float)
    return df[["open", "high", "low", "close", "volume", "spread"]]


def ticks_to_bars(t: pd.DataFrame, tf: str) -> pd.DataFrame:
    g = t.resample(RULE[tf], label="left", closed="left")
    bars = pd.DataFrame({"open": g["price"].first(), "high": g["price"].max(), "low": g["price"].min(),
                         "close": g["price"].last(), "volume": g["volume"].sum(), "spread": g["spread"].mean()})
    return bars.dropna(subset=["open"])


def read_csv(path: str) -> pd.DataFrame:
    """Accepts bar CSVs (time/date + open/high/low/close[/volume/spread]) or tick CSVs (timestamp + price|last|bid/ask).
    Naive timestamps are treated as US/Eastern (CME convention); MT5 exports should include an offset or be UTC."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"data file not found: {p}")
    raw = pd.read_csv(p, sep=None, engine="python")
    cols = {c: c.strip().lower().strip("<>") for c in raw.columns}
    raw = raw.rename(columns=cols)
    tcol = next((c for c in ("timestamp", "time", "datetime", "date") if c in raw.columns), None)
    if tcol is None:
        raise ValueError(f"no time column in {p.name}; expected one of timestamp/time/datetime/date")
    ts = raw[tcol].astype(str)
    if tcol == "date" and "time" in raw.columns:  # MT5 export: <DATE> <TIME>
        ts = raw["date"].astype(str) + " " + raw["time"].astype(str)
    idx = pd.to_datetime(ts.str.replace(".", "-", regex=False) if ts.str.match(r"^\d{4}\.\d{2}\.\d{2}").all() else ts)
    idx = idx.dt.tz_localize(ET) if idx.dt.tz is None else idx
    raw.index = pd.DatetimeIndex(idx).tz_convert("UTC")
    if {"open", "high", "low", "close"} <= set(raw.columns):
        vol = raw["volume"] if "volume" in raw else raw.get("tickvol", raw.get("vol", 1))
        return _finish(pd.DataFrame({"open": raw["open"], "high": raw["high"], "low": raw["low"], "close": raw["close"],
                                     "volume": vol, "spread": raw.get("spread", np.nan)}, index=raw.index))
    if "price" in raw or "last" in raw or {"bid", "ask"} <= set(raw.columns):
        price = raw["price"] if "price" in raw else raw["last"] if "last" in raw else (raw["bid"] + raw["ask"]) / 2
        spread = (raw["ask"] - raw["bid"]) if {"bid", "ask"} <= set(raw.columns) else raw.get("spread_ticks", np.nan) * 0.1 if "spread_ticks" in raw else np.nan
        return pd.DataFrame({"price": price.astype(float), "spread": spread, "volume": raw.get("volume", 1)}, index=raw.index)
    raise ValueError(f"{p.name}: need OHLC columns (bars) or price/last/bid+ask (ticks)")


def load_bars(source: str, start: str, end: str, tf: str = "1m", symbol: str = "XAUUSD",
              path: str | None = None, seed: int = 7) -> pd.DataFrame:
    s, e = _utc(start), _utc(end, end=True)
    if tf not in RULE:
        raise ValueError(f"timeframe must be one of {list(RULE)}")
    if source == "mt5":
        r = mt5_data.client().rates(symbol, tf, s, e)
        df = pd.DataFrame(r, index=pd.to_datetime(r.pop("time"), unit="s", utc=True)).drop(columns=[], errors="ignore")
        return _finish(df)
    if source == "csv":
        if not path:
            raise ValueError("data_source=csv requires a file path")
        d = read_csv(path)
        d = d[(d.index >= s) & (d.index < e)]
        if d.empty:
            raise ValueError(f"no rows in {path} between {start} and {end}")
        return _finish(ticks_to_bars(d, tf) if "price" in d else d.resample(RULE[tf]).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "spread": "mean"}).dropna(subset=["open"]))
    if source == "synthetic":
        from ..trading.backtester import build_news_schedule, synthetic_day_ticks
        rng = np.random.default_rng(seed)
        sched = build_news_schedule(s.date(), e.date(), None)
        frames, px = [], 2650.0
        d = s.date()
        while d < e.date():
            if d.weekday() < 5:
                secs, p, sp = synthetic_day_ticks(rng, d, px, [x for x in sched if x["date"] == d])
                px = float(p[-1])
                base = pd.Timestamp(d, tz=ET)
                frames.append(pd.DataFrame({"price": p, "spread": sp * 0.1, "volume": 1},
                                           index=(base + pd.to_timedelta(secs, unit="s")).tz_convert("UTC")))
            d += timedelta(days=1)
        if not frames:
            raise ValueError("date range has no weekdays")
        return _finish(ticks_to_bars(pd.concat(frames), tf))
    raise ValueError("data_source must be synthetic, csv or mt5")


def load_tick_days(source: str, start: str, end: str, symbol: str = "XAUUSD", path: str | None = None) -> dict:
    """Ticks resampled to the 1-second 08:00-16:59 ET grid used by the native tick engine."""
    if source == "mt5":
        r = mt5_data.client().ticks(symbol, _utc(start), _utc(end, end=True))
        t = pd.DataFrame({"price": r["price"], "spread": r["spread"]}, index=pd.to_datetime(r["time"], unit="s", utc=True))
    elif source == "csv":
        t = read_csv(path or "")
        if "price" not in t:  # bars given: use closes
            t = pd.DataFrame({"price": t["close"], "spread": t["spread"]}, index=t.index)
    else:
        raise ValueError("tick-days only for csv or mt5")
    t = t.tz_convert(ET)
    out: dict[date, tuple] = {}
    grid = np.arange(8 * 3600, 17 * 3600)
    for d, g in t.groupby(t.index.date):
        secs = (g.index.hour * 3600 + g.index.minute * 60 + g.index.second).to_numpy()
        m = (secs >= grid[0]) & (secs <= grid[-1])
        if not m.any():
            continue
        s_, p_, sp_ = secs[m], g["price"].to_numpy()[m], np.nan_to_num(g["spread"].to_numpy()[m], nan=0.1)
        idx = np.clip(np.searchsorted(s_, grid, side="right") - 1, 0, len(s_) - 1)
        out[d] = (grid, p_[idx], np.maximum(1, np.round(sp_[idx] / 0.1)))
    s0, e0 = _utc(start).date(), _utc(end).date()
    return {d: v for d, v in out.items() if s0 <= d <= e0}
