"""MGC market data: Tradovate market-data WebSocket when APOLLO_LIVE=1, otherwise a deterministic
seeded simulator (labelled SIM everywhere). Produces trades, 1m bars and a 10-level DOM book."""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from typing import Callable

import numpy as np

TICK = 0.10
MD_URLS = {"demo": "wss://md-demo.tradovateapi.com/v1/websocket", "live": "wss://md.tradovateapi.com/v1/websocket"}


class MarketFeed:
    def __init__(self, symbol: str, on_event: Callable[[dict], None], seed: int = 11):
        self.symbol = symbol
        self.on_event = on_event
        self.live = os.getenv("APOLLO_LIVE") == "1"
        self.rng = np.random.default_rng(seed)
        self.last = 2650.0
        self.bars: deque[dict] = deque(maxlen=3000)  # 1m bars
        self.trades: deque[dict] = deque(maxlen=500)
        self.book: dict = {"bids": [], "asks": []}
        self.token_getter: Callable[[], str | None] = lambda: None
        self._seed_history()

    @property
    def source(self) -> str:
        return "TRADOVATE" if self.live else "SIM"

    # ---------- shared ----------
    def _on_trade(self, price: float, size: int, side: str, ts: float) -> None:
        self.last = price
        minute = int(ts // 60) * 60
        b = self.bars[-1] if self.bars else None
        if b is None or b["time"] != minute:
            b = {"time": minute, "open": price, "high": price, "low": price, "close": price, "volume": 0, "delta": 0}
            self.bars.append(b)
        b["high"] = max(b["high"], price); b["low"] = min(b["low"], price); b["close"] = price
        b["volume"] += size; b["delta"] += size if side == "B" else -size
        t = {"time": ts, "price": round(price, 1), "size": size, "side": side}
        self.trades.append(t)
        self.on_event({"type": "trade", **t})

    def bars_tf(self, tf: str) -> list[dict]:
        n = {"1m": 1, "5m": 5, "15m": 15}.get(tf)
        if not n:
            raise ValueError("timeframe must be 1m, 5m or 15m")
        out: list[dict] = []
        for b in self.bars:
            t = b["time"] - b["time"] % (n * 60)
            if out and out[-1]["time"] == t:
                o = out[-1]
                o["high"] = max(o["high"], b["high"]); o["low"] = min(o["low"], b["low"])
                o["close"] = b["close"]; o["volume"] += b["volume"]; o["delta"] += b["delta"]
            else:
                out.append({**b, "time": t})
        return out

    def session_levels(self) -> dict:
        now = time.time()
        day = [b for b in self.bars if b["time"] >= now - 86400]
        prev = [b for b in self.bars if now - 2 * 86400 <= b["time"] < now - 86400]
        lv = {}
        if day:
            lv.update(session_high=max(b["high"] for b in day), session_low=min(b["low"] for b in day),
                      session_open=day[0]["open"])
            vol = sum(b["volume"] for b in day) or 1
            lv["vwap"] = round(sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in day) / vol, 2)
        if prev:
            lv.update(prior_high=max(b["high"] for b in prev), prior_low=min(b["low"] for b in prev),
                      prior_close=prev[-1]["close"])
        return lv

    # ---------- simulator ----------
    def _seed_history(self) -> None:
        now = int(time.time() // 60) * 60
        px = self.last
        for k in range(2 * 1440, 0, -1):
            o = px
            steps = self.rng.standard_normal(30) * 0.18
            path = o + np.cumsum(steps)
            px = round(path[-1] / TICK) * TICK
            v = int(self.rng.integers(40, 400))
            d = int(self.rng.integers(-v // 3, v // 3))
            self.bars.append({"time": now - k * 60, "open": round(o, 1), "high": round(max(o, path.max()), 1),
                              "low": round(min(o, path.min()), 1), "close": round(px, 1), "volume": v, "delta": d})
        self.last = px

    def _sim_book(self) -> None:
        bid = round((self.last - TICK / 2) / TICK) * TICK
        mk = lambda: int(self.rng.integers(3, 60))
        self.book = {"bids": [[round(bid - i * TICK, 1), mk()] for i in range(10)],
                     "asks": [[round(bid + (i + 1) * TICK, 1), mk()] for i in range(10)]}

    async def _run_sim(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            n = int(self.rng.integers(1, 4))
            for _ in range(n):
                step = int(self.rng.choice([-1, 0, 0, 1])) * TICK
                size = int(self.rng.choice([1, 1, 1, 2, 3, 5, 8, 12, 25], p=[.3, .2, .1, .12, .1, .08, .05, .03, .02]))
                self._on_trade(round(self.last + step, 1), size, "B" if step >= 0 else "S", time.time())
            self._sim_book()
            self.on_event({"type": "dom", **self.book})

    # ---------- live ----------
    async def _run_live(self) -> None:
        import websockets
        env = os.getenv("TRADOVATE_ENV", "demo")
        while True:
            token = self.token_getter()
            if not token:
                await asyncio.sleep(2)
                continue
            try:
                async with websockets.connect(MD_URLS[env]) as ws:
                    await ws.recv()
                    await ws.send(f"authorize\n0\n\n{token}")
                    await ws.send(f"md/subscribeQuote\n1\n\n{json.dumps({'symbol': self.symbol})}")
                    await ws.send(f"md/subscribeDOM\n2\n\n{json.dumps({'symbol': self.symbol})}")
                    hb = asyncio.create_task(self._hb(ws))
                    try:
                        async for raw in ws:
                            if raw.startswith("a"):
                                for m in json.loads(raw[1:]):
                                    self._live_msg(m)
                    finally:
                        hb.cancel()
            except Exception as e:  # reconnect on any socket error
                self.on_event({"type": "feed_error", "error": str(e)})
                await asyncio.sleep(3)

    async def _hb(self, ws) -> None:
        while True:
            await asyncio.sleep(2.5)
            await ws.send("[]")

    def _live_msg(self, m: dict) -> None:
        if m.get("e") != "md":
            return
        d = m.get("d", {})
        for q in d.get("quotes", []):
            e = q.get("entries", {})
            tr = e.get("Trade")
            if tr and tr.get("price") is not None:
                bid = e.get("Bid", {}).get("price", tr["price"])
                self._on_trade(float(tr["price"]), int(tr.get("size", 1)),
                               "S" if tr["price"] <= bid else "B", time.time())
        for dom in d.get("doms", []):
            self.book = {"bids": [[b["price"], b["size"]] for b in dom.get("bids", [])[:10]],
                         "asks": [[a["price"], a["size"]] for a in dom.get("offers", [])[:10]]}
            self.on_event({"type": "dom", **self.book})

    async def run(self) -> None:
        await (self._run_live() if self.live else self._run_sim())
