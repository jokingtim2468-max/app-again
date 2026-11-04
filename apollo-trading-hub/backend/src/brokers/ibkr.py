"""Interactive Brokers via TWS / IB Gateway (pip install ib_async). Env: IBKR_HOST (127.0.0.1), IBKR_PORT (7497 paper,
7496 live), IBKR_CLIENT_ID. Account = IB account code (e.g. DU1234567). Symbol like MGCZ6 -> COMEX MGC future."""
from __future__ import annotations

import os

from .base import BrokerError, Connector

MONTHS = "FGHJKMNQUVXZ"


class IBKRConnector(Connector):
    name = "ibkr"

    async def connect(self):
        try:
            from ib_async import IB  # type: ignore
        except ImportError:
            try:
                from ib_insync import IB  # type: ignore
            except ImportError as e:
                raise BrokerError("install ib_async (pip install ib_async) to use Interactive Brokers") from e
        self.ib = IB()
        await self.ib.connectAsync(os.getenv("IBKR_HOST", "127.0.0.1"), int(os.getenv("IBKR_PORT", "7497")),
                                   clientId=int(os.getenv("IBKR_CLIENT_ID", "54")))
        self.connected = True

    def _contract(self, symbol: str):
        try:
            from ib_async import Future  # type: ignore
        except ImportError:
            from ib_insync import Future  # type: ignore
        root, m, y = symbol[:-2], symbol[-2], symbol[-1]
        return Future(root, f"202{y}{MONTHS.index(m) + 1:02d}", "COMEX")

    async def place_market(self, account, action, symbol, qty):
        try:
            from ib_async import MarketOrder  # type: ignore
        except ImportError:
            from ib_insync import MarketOrder  # type: ignore
        c = self._contract(symbol)
        await self.ib.qualifyContractsAsync(c)
        o = MarketOrder("BUY" if action == "Buy" else "SELL", int(qty), account=account)
        t = self.ib.placeOrder(c, o)
        return {"mode": self.mode, "orderId": t.order.orderId, "account": account}

    async def positions(self, account):
        return {p.contract.localSymbol: float(p.position) for p in self.ib.positions(account)}
