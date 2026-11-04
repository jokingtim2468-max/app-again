"""Forward test (paper) an adapted script on LIVE data (MT5 or the SIM feed). Never sends broker orders."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

import numpy as np
import pandas as pd

from .adapter import adapt
from .bar_engine import CONTRACTS
from .risk_sentinel import RiskSentinel


class ForwardTester:
    def __init__(self, emit: Callable[[dict], None], sim_feed=None):
        self.emit, self.sim_feed = emit, sim_feed
        self.task: asyncio.Task | None = None
        self.state: dict = {"running": False}

    def status(self) -> dict:
        return self.state

    async def start(self, script: str, source: str = "mt5", symbol: str = "XAUUSD", timeframe: str = "1m",
                    lot_size_micros: int = 5, contract: str = "MGC", warmup_bars: int = 500, params: dict | None = None) -> dict:
        await self.stop()
        st = adapt(script, params)
        if source != "mt5":
            symbol = "MGC (SIM)"
        if st.style not in ("vectorized", "event_class", "event_func", "mt5_python", "pine", "freqtrade", "quantconnect"):
            raise ValueError(f"forward testing supports bar-driven scripts; this one is {st.style}")
        sentinel = RiskSentinel()
        acct = sentinel.new_account("FORWARD")
        sentinel.accounts["FORWARD"] = acct
        self.state = {"running": True, "script": st.describe(), "source": source, "symbol": symbol, "timeframe": timeframe,
                      "started": datetime.now(timezone.utc).isoformat(), "position": 0, "entry": 0.0, "realized": 0.0,
                      "open_pnl": 0.0, "trades": [], "last_bar": None, "error": None}
        self.task = asyncio.create_task(self._loop(st, sentinel, source, symbol, timeframe, lot_size_micros,
                                                   CONTRACTS[contract], warmup_bars))
        return self.state

    async def stop(self) -> dict:
        if self.task:
            self.task.cancel()
            self.task = None
        self.state["running"] = False
        return self.state

    def _bars(self, source, symbol, tf, n):
        if source == "mt5":
            from ..data.sources import load_bars
            mins = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}[tf]
            end = datetime.now(timezone.utc) + timedelta(minutes=1)
            start = end - timedelta(minutes=mins * n * 2 + 60 * 24 * 3)  # cover weekends/gaps
            df = load_bars("mt5", start.isoformat(), end.isoformat(), tf, symbol)
            return df.iloc[-n:]
        bars = self.sim_feed.bars_tf(tf)[-n:]
        df = pd.DataFrame(bars)
        df.index = pd.to_datetime(df.pop("time"), unit="s", utc=True)
        df["spread"] = 0.1
        return df[["open", "high", "low", "close", "volume", "spread"]]

    def _price(self, source, symbol) -> tuple[float, float]:
        if source == "mt5":
            from ..data import mt5_data
            t = mt5_data.client().tick(symbol)
            return (t["bid"] + t["ask"]) / 2, max(t["ask"] - t["bid"], 0.0)
        return self.sim_feed.last, 0.1

    async def _loop(self, st, sentinel, source, symbol, tf, lots, spec, warmup):
        s = self.state
        pv, comm = spec["point_value"], spec["commission_rt"]
        while True:
            try:
                df = await asyncio.to_thread(self._bars, source, symbol, tf, warmup)
                closed = df.iloc[:-1]  # last bar is still forming
                if len(closed) > 10 and str(closed.index[-1]) != s["last_bar"]:
                    s["last_bar"] = str(closed.index[-1])
                    target = float(np.nan_to_num(st.run(closed)[-1]))
                    want = int(np.sign(target)) * (int(round(abs(target) * lots)) if abs(target) <= 1 else int(abs(target)))
                    mid, spr = await asyncio.to_thread(self._price, source, symbol)
                    if want != s["position"]:
                        side = 1 if want > s["position"] else -1
                        px = mid + side * spr / 2
                        if s["position"]:
                            pnl = (px - s["entry"]) * np.sign(s["position"]) * abs(s["position"]) * pv - comm * abs(s["position"])
                            s["realized"] += pnl
                            sentinel.realize("FORWARD", pnl)
                            s["trades"].append({"time": time.time(), "exit": round(px, 2), "pnl": round(pnl, 2)})
                        s["position"], s["entry"] = want, (px if want else 0.0)
                        self.emit({"type": "forward_fill", "position": want, "price": round(px, 2), "bar": s["last_bar"]})
                mid, _ = await asyncio.to_thread(self._price, source, symbol)
                s["open_pnl"] = round((mid - s["entry"]) * np.sign(s["position"]) * abs(s["position"]) * pv, 2) if s["position"] else 0.0
                s["mark"] = mid
                s["error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as e:  # keep running; surface the error
                s["error"] = f"{type(e).__name__}: {e}"
            await asyncio.sleep(2)
