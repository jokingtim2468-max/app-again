"""Clean + merge raw downloads into analysis-ready parquet files.

Day definition used everywhere: the FX/metals trading day that closes at
17:00 America/New_York (the standard MT4/MT5 "GMT+2/+3" daily candle).

Outputs (gold-bot/data/processed/):
  xau_h1.parquet     spot XAUUSD hourly, UTC index, 2004 -> 2026-01
  xau_d1.parquet     spot XAUUSD daily (NY-close), 2004 -> today, `source` column
  macro_d1.parquet   Yahoo closes for cross-asset drivers, 1995 -> today
  gc_h1.parquet      COMEX gold futures hourly (Yahoo), last ~730 days
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
NY = "America/New_York"
AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}


def ny_trading_day(ts_utc: pd.DatetimeIndex) -> pd.Index:
    """Map UTC timestamps to the trading date whose session closes 17:00 NY."""
    local = ts_utc.tz_convert(NY)
    return (local + pd.Timedelta(hours=7)).normalize().tz_localize(None)


def load_histdata_m1() -> pd.DataFrame:
    frames = []
    for f in sorted((RAW / "histdata_m1").glob("DAT_MT_XAUUSD_M1_*.csv")):
        d = pd.read_csv(f, header=None, names=["d", "t", "Open", "High", "Low", "Close", "V"])
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    ts = pd.to_datetime(d["d"] + " " + d["t"], format="%Y.%m.%d %H:%M")
    # HistData = EST with no DST -> fixed UTC-5
    d.index = (ts + pd.Timedelta(hours=5)).dt.tz_localize("UTC")
    d = d[["Open", "High", "Low", "Close"]].astype("float64")
    return d[~d.index.duplicated()].sort_index()


def load_zombit(tf: str) -> pd.DataFrame:
    d = pd.read_json(RAW / "zombit" / f"XAU_{tf}_data.jsonl", lines=True)
    d.index = pd.to_datetime(d.pop("Date"), format="%Y.%m.%d %H:%M")
    return d.sort_index()[~d.index.duplicated()]


def daily_from_intraday(df_utc: pd.DataFrame) -> pd.DataFrame:
    g = df_utc.groupby(ny_trading_day(df_utc.index))
    d = g.agg(AGG)
    d["bars"] = g.size()
    d = d[d.index.day_of_week < 5]  # drop stray weekend sessions
    return d


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- spot hourly ------------------------------------------------------
    m1 = load_histdata_m1()
    h1_hist = m1.resample("1h").agg(AGG).dropna()
    # Zombit H1 is broker time (GMT+2 winter / GMT+3 summer == NY+7h)
    z1 = load_zombit("1h")
    z1.index = (z1.index - pd.Timedelta(hours=7)).tz_localize(NY, ambiguous="NaT",
                                                               nonexistent="NaT")
    z1 = z1[z1.index.notna()]
    z1.index = z1.index.tz_convert("UTC")
    z1 = z1[z1.index < h1_hist.index[0]][["Open", "High", "Low", "Close"]]
    h1 = pd.concat([z1, h1_hist]).sort_index()
    h1.to_parquet(OUT / "xau_h1.parquet")
    print(f"xau_h1   {len(h1):7d} rows {h1.index[0]} -> {h1.index[-1]}")

    # ---- spot daily -------------------------------------------------------
    d_hist = daily_from_intraday(m1)
    d_hist = d_hist[d_hist["bars"] > 300]  # need most of the session
    d_hist["source"] = "histdata_m1"
    zd = load_zombit("1d")
    zd = zd[zd.index < d_hist.index[0]][["Open", "High", "Low", "Close"]]
    zd["source"] = "zombit_d1"

    # ---- futures hourly -> NY-close daily, to extend past HistData ---------
    gc = pd.read_csv(RAW / "yahoo" / "gold_fut_1h.csv", index_col=0)
    gc.index = pd.to_datetime(gc.index, utc=True)
    gc = gc[["Open", "High", "Low", "Close"]].astype("float64")
    gc.to_parquet(OUT / "gc_h1.parquet")
    gd = daily_from_intraday(gc)
    gd = gd[gd["bars"] > 15]

    # check direction agreement on the overlap before trusting it
    ov = d_hist.index.intersection(gd.index)
    s_dir = np.sign(d_hist.loc[ov, "Close"] - d_hist.loc[ov, "Open"])
    f_dir = np.sign(gd.loc[ov, "Close"] - gd.loc[ov, "Open"])
    agree = float((s_dir == f_dir).mean())
    basis = float((gd.loc[ov, "Close"] / d_hist.loc[ov, "Close"]).median())
    print(f"spot vs GC=F(NY-close) overlap {len(ov)} days: direction agree {agree:.3f}, "
          f"median fut/spot {basis:.4f}")
    ext = gd[gd.index > d_hist.index[-1]][["Open", "High", "Low", "Close"]] / basis
    ext["source"] = "gc_fut_h1_basis_adj"

    d1 = pd.concat([zd, d_hist.drop(columns="bars"), ext]).sort_index()
    d1.index.name = "date"
    d1.to_parquet(OUT / "xau_d1.parquet")
    print(f"xau_d1   {len(d1):7d} rows {d1.index[0].date()} -> {d1.index[-1].date()}")
    print(d1["source"].value_counts().to_string())

    # ---- macro ------------------------------------------------------------
    cols = {}
    for f in sorted((RAW / "yahoo").glob("*_1d.csv")):
        s = pd.read_csv(f, index_col=0, parse_dates=True)["Close"]
        cols[f.stem.removesuffix("_1d")] = pd.to_numeric(s, errors="coerce")
    macro = pd.DataFrame(cols).sort_index()
    macro.index.name = "date"
    macro.to_parquet(OUT / "macro_d1.parquet")
    print(f"macro_d1 {len(macro):7d} rows x {macro.shape[1]} cols "
          f"{macro.index[0].date()} -> {macro.index[-1].date()}")


if __name__ == "__main__":
    main()
