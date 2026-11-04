"""MetaTrader 5 order routing (FTMO, FundedNext, The5ers and any MT5 broker). Windows + MetaTrader5 package required:
the WSL bridge is deliberately read-only, so live MT5 orders only go out from a Windows-hosted backend.
Account = MT5 login number; the terminal must be logged into that login. Volume is in lots."""
from __future__ import annotations

import asyncio

from .base import BrokerError, Connector


class MT5Connector(Connector):
    name = "mt5"

    async def connect(self):
        from ..data import mt5_data
        c = mt5_data.client()
        if not isinstance(c, mt5_data._Direct):
            raise BrokerError("MT5 order routing needs the backend running in Windows Python with the MetaTrader5 package "
                              "(the WSL bridge only serves market data)")
        await asyncio.to_thread(c.connect)
        self.mt5 = c.mt5
        self.connected = True

    async def place_market(self, account, action, symbol, qty):
        m = self.mt5
        acc = m.account_info()
        if str(acc.login) != str(account):
            raise BrokerError(f"MT5 terminal is logged into {acc.login}, not {account}")
        tick = m.symbol_info_tick(symbol)
        info = m.symbol_info(symbol)
        step = info.volume_step or 0.01
        vol = max(info.volume_min, round(round(qty / step) * step, 2))
        req = {"action": m.TRADE_ACTION_DEAL, "symbol": symbol, "volume": vol,
               "type": m.ORDER_TYPE_BUY if action == "Buy" else m.ORDER_TYPE_SELL,
               "price": tick.ask if action == "Buy" else tick.bid, "deviation": 20, "magic": 54981,
               "comment": "apollo", "type_time": m.ORDER_TIME_GTC, "type_filling": m.ORDER_FILLING_IOC}
        r = await asyncio.to_thread(m.order_send, req)
        if r is None or r.retcode != m.TRADE_RETCODE_DONE:
            raise BrokerError(f"MT5 order_send failed: {getattr(r, 'retcode', None)} {getattr(r, 'comment', m.last_error())}")
        return {"mode": self.mode, "orderId": r.order, "volume": vol, "price": r.price, "account": account}

    async def positions(self, account):
        ps = await asyncio.to_thread(self.mt5.positions_get) or ()
        out: dict[str, float] = {}
        for p in ps:
            out[p.symbol] = out.get(p.symbol, 0.0) + (p.volume if p.type == 0 else -p.volume)
        return out
