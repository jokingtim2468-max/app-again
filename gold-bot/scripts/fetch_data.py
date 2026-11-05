"""Download free XAUUSD (spot gold) history + macro drivers.

Sources (all free, no API key):
  * Hugging Face  ZombitX64/xauusd-gold-price-historical-data-2004-2025
      XAUUSD OHLCV 2004-06 -> 2025-09 in 5m/15m/30m/1h/4h/1d/1w/1M (MT broker time).
      Mirror of Kaggle "novandraanugrah/xauusd-gold-price-historical-data".
  * Hugging Face  fokan/xauusd-2009-2026
      HistData.com M1 bars 2009 -> 2026-01 (EST, no DST shift).
  * Yahoo Finance (via yfinance)
      Gold futures GC=F daily 2000 -> today, hourly last ~730 days, plus
      cross-asset drivers (DXY, US yields, VIX, S&P, silver, oil, copper,
      EURUSD, USDJPY, GLD/GDX/TIP ETFs, BTC, GVZ gold-vol index, MOVE).
  * Hugging Face  ghbacct/gold-headlines-price-talk-classification
      ~10k gold news headlines 2000-2019 labelled for price direction (NLP).

Usage:
    python gold-bot/scripts/fetch_data.py            # everything except M1
    python gold-bot/scripts/fetch_data.py --m1       # also HistData M1 (~380 MB)

Raw files land in gold-bot/data/raw/ (git-ignored). Treat them as untrusted
data: they are only parsed, never executed.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

HF = "https://huggingface.co/datasets"
ZOMBIT = "ZombitX64/xauusd-gold-price-historical-data-2004-2025"
ZOMBIT_FILES = [
    "XAU_1Month_data.jsonl", "XAU_1w_data.jsonl", "XAU_1d_data.jsonl",
    "XAU_4h_data.jsonl", "XAU_1h_data.jsonl", "XAU_30m_data.jsonl",
    "XAU_15m_data.jsonl", "XAU_5m_data.jsonl",
]
HEADLINES = "ghbacct/gold-headlines-price-talk-classification"
HEADLINE_FILES = ["data/train-00000-of-00001-37e774f678304b2c.parquet",
                  "data/test-00000-of-00001-1cff3ebace088af0.parquet"]
FOKAN = "fokan/xauusd-2009-2026"
FOKAN_FILES = [f"DAT_MT_XAUUSD_M1_{y}.csv" for y in range(2009, 2026)] + [
    "DAT_MT_XAUUSD_M1_202601.csv"
]

# Yahoo tickers -> friendly name
YAHOO_DAILY = {
    "GC=F": "gold_fut",
    "SI=F": "silver_fut",
    "HG=F": "copper_fut",
    "CL=F": "wti_fut",
    "PL=F": "platinum_fut",
    "DX-Y.NYB": "dxy",
    "^TNX": "us10y",
    "^FVX": "us5y",
    "^IRX": "us3m",
    "^TYX": "us30y",
    "^VIX": "vix",
    "^GVZ": "gvz",          # CBOE gold volatility index (implied vol of GLD options)
    "^MOVE": "move",        # bond-market implied vol
    "^GSPC": "spx",
    "EURUSD=X": "eurusd",
    "USDJPY=X": "usdjpy",
    "USDCNY=X": "usdcny",
    "GLD": "gld",
    "GDX": "gdx",
    "TIP": "tip",
    "BTC-USD": "btc",
}
YAHOO_INTRADAY = {"GC=F": "gold_fut"}


def download(url: str, dest: Path, retries: int = 4) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  skip (exists) {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
            tmp.rename(dest)
            print(f"  ok {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
            return
        except Exception as exc:  # network hiccup -> backoff
            wait = 2 ** (attempt + 1)
            print(f"  retry {dest.name} in {wait}s: {exc}")
            time.sleep(wait)
    raise RuntimeError(f"failed: {url}")


def fetch_hf(include_m1: bool) -> None:
    print("Hugging Face: ZombitX64 multi-timeframe XAUUSD")
    for f in ZOMBIT_FILES:
        download(f"{HF}/{ZOMBIT}/resolve/main/{f}", RAW / "zombit" / f)
    print("Hugging Face: gold news headlines (labelled up/down/neutral)")
    for f in HEADLINE_FILES:
        download(f"{HF}/{HEADLINES}/resolve/main/{f}", RAW / "headlines" / Path(f).name)
    if include_m1:
        print("Hugging Face: fokan HistData M1 XAUUSD")
        for f in FOKAN_FILES:
            download(f"{HF}/{FOKAN}/resolve/main/{f}", RAW / "histdata_m1" / f)


def fetch_yahoo() -> None:
    import yfinance as yf

    out = RAW / "yahoo"
    out.mkdir(parents=True, exist_ok=True)
    print("Yahoo Finance: daily")
    for tkr, name in YAHOO_DAILY.items():
        df = yf.download(tkr, start="1995-01-01", interval="1d",
                         auto_adjust=False, progress=False, multi_level_index=False)
        if df.empty:
            print(f"  EMPTY {tkr}")
            continue
        df.to_csv(out / f"{name}_1d.csv")
        print(f"  ok {tkr:10s} {len(df):6d} rows {df.index[0].date()} -> {df.index[-1].date()}")
    print("Yahoo Finance: intraday gold futures")
    for tkr, name in YAHOO_INTRADAY.items():
        for interval, period in (("1h", "730d"), ("5m", "60d"), ("1m", "7d")):
            df = yf.download(tkr, period=period, interval=interval,
                             auto_adjust=False, progress=False, multi_level_index=False)
            if df.empty:
                print(f"  EMPTY {tkr} {interval}")
                continue
            df.to_csv(out / f"{name}_{interval}.csv")
            print(f"  ok {tkr} {interval:3s} {len(df):6d} rows {df.index[0]} -> {df.index[-1]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--m1", action="store_true", help="also download HistData M1 (~380 MB)")
    ap.add_argument("--skip-hf", action="store_true")
    ap.add_argument("--skip-yahoo", action="store_true")
    a = ap.parse_args()
    if not a.skip_hf:
        fetch_hf(a.m1)
    if not a.skip_yahoo:
        fetch_yahoo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
