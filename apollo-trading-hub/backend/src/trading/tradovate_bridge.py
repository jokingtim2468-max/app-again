"""Fleet router: master -> N copy accounts across ANY mix of brokers and prop firms.

PAPER for every account unless APOLLO_LIVE=1. In live mode each account routes through its own connector
(tradovate / projectx / ninjatrader(rithmic) / mt5 / ibkr), opening orders are refused for accounts whose firm rules
are unverified templates, and every copy order passes RiskSentinel.validate_order first.
Credentials come only from env vars (see each connector). Multiple logins of one broker: set account `login: "_2"`
and use TRADOVATE_USER_2 etc.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Callable

from ..brokers import BrokerError, make_connector
from ..brokers.base import Connector
from .risk_sentinel import RiskSentinel

log = logging.getLogger("apollo.router")


@dataclass
class Fill:
    account: str
    action: str
    symbol: str
    qty: float
    price: float | None = None


class FleetRouter:
    def __init__(self, sentinel: RiskSentinel, on_event: Callable[[dict], None] | None = None):
        self.sentinel = sentinel
        self.cfg = sentinel.config
        self.live = os.getenv("APOLLO_LIVE") == "1"
        self.on_event = on_event or (lambda e: None)
        self.specs = {s["id"]: s for s in sentinel.specs}
        self.connectors: dict[str, Connector] = {}
        self.errors: dict[str, str] = {}
        self.journal: list[dict] = []
        for aid, s in self.specs.items():
            key = self._key(s)
            if key not in self.connectors:
                self.connectors[key] = make_connector(s.get("broker", "paper") if self.live else "paper", self.live, s.get("login", ""))

    @staticmethod
    def _key(spec: dict) -> str:
        return f"{spec.get('broker', 'paper')}{spec.get('login', '')}"

    def conn(self, aid: str) -> Connector:
        return self.connectors[self._key(self.specs[aid])]

    @property
    def mode(self) -> str:
        if not self.live:
            return "PAPER"
        return "LIVE:" + ",".join(sorted({c.name for c in self.connectors.values()}))

    @property
    def token(self) -> str | None:  # Tradovate market data reuses the Tradovate session
        for c in self.connectors.values():
            if c.name == "tradovate" and getattr(c, "token", None):
                return c.token
        return None

    def status(self) -> dict:
        return {"mode": self.mode, "connectors": {k: {**c.status(), "error": self.errors.get(k)} for k, c in self.connectors.items()}}

    def symbol_for(self, aid: str, symbol: str) -> str:
        return self.specs.get(aid, {}).get("symbol") or symbol

    # ---- routing ----------------------------------------------------------
    async def place_market(self, account: str, action: str, symbol: str, qty: float, price: float | None = None) -> dict:
        acct = self.sentinel.accounts.get(account)
        if self.live and acct and not acct.verified:
            opening = acct.position_qty == 0 or (acct.position_qty > 0) == (action == "Buy")
            if opening:
                raise BrokerError(f"{account}: {acct.rules.get('firm_name')} rules unverified; live opening orders refused")
        sym = self.symbol_for(account, symbol)
        broker_acct = self.specs.get(account, {}).get("broker_account", account)
        res = await self.conn(account).place_market(broker_acct, action, sym, qty)
        res.update(account=account, action=action, symbol=sym, qty=qty)
        if acct and price is not None:
            res["realized"] = round(self.sentinel.apply_fill(account, action, qty, price), 2)
        self.journal.append(res)
        self.on_event({"type": "order", **res})
        return res

    def copy_qty(self, slave: str, master_qty: float) -> float:
        a = self.sentinel.accounts[slave]
        q = master_qty * a.copy_ratio
        return round(q, 2) if a.contract == "XAUUSD" else float(int(round(q)))

    async def mirror(self, master_fill: Fill) -> list[dict]:
        results = []
        for slave in self.cfg["slave_accounts"]:
            acct = self.sentinel.accounts[slave]
            qty = self.copy_qty(slave, master_fill.qty)
            if qty <= 0:
                continue
            reducing = (acct.position_qty > 0 and master_fill.action == "Sell") or (acct.position_qty < 0 and master_fill.action == "Buy")
            if reducing:
                qty = min(qty, abs(acct.position_qty))
                if acct.liquidated:
                    continue
            else:
                check = self.sentinel.validate_order(slave, acct.stage, qty, self.symbol_for(slave, master_fill.symbol) if acct.contract != "MGC" else master_fill.symbol, live=self.live)
                if not check["approved"]:
                    qty = check["approved_qty"]
                    self.on_event({"type": "risk_clamp", "account": slave, **check})
                    if qty <= 0:
                        continue
            try:
                results.append(await self.place_market(slave, master_fill.action, master_fill.symbol, qty, master_fill.price))
            except (BrokerError, Exception) as e:  # one bad account must not stop the rest of the fleet
                self.on_event({"type": "route_error", "account": slave, "error": str(e)})
        return results

    async def flatten(self, account: str, symbol: str, price: float | None = None) -> dict | None:
        acct = self.sentinel.accounts[account]
        if acct.position_qty == 0:
            return None
        action = "Sell" if acct.position_qty > 0 else "Buy"
        return await self.place_market(account, action, symbol, abs(acct.position_qty), price)

    # ---- lifecycle --------------------------------------------------------
    async def run(self) -> None:
        for key, c in self.connectors.items():
            try:
                await c.connect()
            except Exception as e:
                self.errors[key] = str(e)
                self.on_event({"type": "connector_error", "connector": key, "error": str(e)})
        if not self.live:
            while True:
                await asyncio.sleep(3600)
        master = self.cfg["master_account"]
        mc = self.conn(master)
        if not mc.connected:
            log.error("master connector not connected: %s", self.errors)
            while True:
                await asyncio.sleep(3600)

        def on_fill(f: dict):
            fill = Fill(master, f["action"], f["symbol"], f["qty"], f.get("price"))
            self.sentinel.apply_fill(master, fill.action, fill.qty, float(fill.price or 0))
            self.on_event({"type": "master_fill", **fill.__dict__})
            asyncio.get_running_loop().create_task(self.mirror(fill))

        if mc.streams_fills:
            await mc.run_fill_stream(self.specs[master].get("broker_account", master), on_fill)
        else:
            await self._poll_fills(mc, master, on_fill)

    async def _poll_fills(self, mc: Connector, master: str, on_fill) -> None:
        """Brokers without a fill stream: diff the master's positions every second."""
        broker_acct = self.specs[master].get("broker_account", master)
        last = await mc.positions(broker_acct)
        while True:
            await asyncio.sleep(1)
            try:
                cur = await mc.positions(broker_acct)
            except Exception as e:
                self.on_event({"type": "connector_error", "connector": mc.name, "error": str(e)})
                continue
            for sym in set(cur) | set(last):
                d = cur.get(sym, 0.0) - last.get(sym, 0.0)
                if d:
                    on_fill({"action": "Buy" if d > 0 else "Sell", "qty": abs(d), "symbol": sym, "price": None})
            last = cur


TradovateBridge = FleetRouter  # backwards-compatible name
