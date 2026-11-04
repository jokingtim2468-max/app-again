"""Broker connector interface. One connector instance per broker/login; accounts map to connectors by name."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Callable

FillCallback = Callable[[dict], None]  # {"account", "action", "qty", "symbol", "price"}


class BrokerError(RuntimeError):
    pass


class Connector(ABC):
    name = "base"
    #: True if the connector can push master fills itself; otherwise the router polls positions()
    streams_fills = False

    def __init__(self, live: bool):
        self.live = live
        self.connected = False

    @property
    def mode(self) -> str:
        return f"LIVE:{self.name}" if self.live else "PAPER"

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def place_market(self, account: str, action: str, symbol: str, qty: float) -> dict: ...

    async def positions(self, account: str) -> dict[str, float]:
        """{symbol: signed qty}. Used for fill detection when streams_fills is False."""
        return {}

    async def run_fill_stream(self, master_account: str, on_fill: FillCallback) -> None:
        raise NotImplementedError

    def status(self) -> dict:
        return {"broker": self.name, "connected": self.connected, "mode": self.mode}


def env(*names: str, required: bool = True) -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    if required:
        raise BrokerError(f"missing environment variable {names[0]}")
    return ""
