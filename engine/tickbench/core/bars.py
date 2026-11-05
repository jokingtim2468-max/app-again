"""Price data container shared by every part of the engine."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Bars:
    time: np.ndarray  # int64, milliseconds since epoch (UTC)
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    symbol: str = "SYMBOL"
    timeframe: str = "1d"
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.close)

    def slice(self, start: int, stop: int) -> "Bars":
        return Bars(self.time[start:stop], self.open[start:stop], self.high[start:stop],
                    self.low[start:stop], self.close[start:stop], self.volume[start:stop],
                    self.symbol, self.timeframe, dict(self.meta))

    def series(self, name: str) -> np.ndarray:
        name = name.lower()
        if name in ("open", "high", "low", "close", "volume"):
            return getattr(self, name)
        if name == "hl2":
            return (self.high + self.low) / 2
        if name == "hlc3":
            return (self.high + self.low + self.close) / 3
        if name == "ohlc4":
            return (self.open + self.high + self.low + self.close) / 4
        if name == "hlcc4":
            return (self.high + self.low + 2 * self.close) / 4
        raise KeyError(name)

    def to_payload(self) -> dict:
        return {
            "time": self.time.tolist(),
            "open": self.open.tolist(),
            "high": self.high.tolist(),
            "low": self.low.tolist(),
            "close": self.close.tolist(),
            "volume": self.volume.tolist(),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
        }

    @staticmethod
    def from_arrays(time, open_, high, low, close, volume=None, symbol="SYMBOL", timeframe="1d") -> "Bars":
        n = len(close)
        vol = np.zeros(n) if volume is None else np.asarray(volume, dtype=float)
        return Bars(np.asarray(time, dtype=np.int64), np.asarray(open_, dtype=float),
                    np.asarray(high, dtype=float), np.asarray(low, dtype=float),
                    np.asarray(close, dtype=float), vol, symbol, timeframe)
