"""Tradovate REST + WebSocket (used by Lucid, Apex, MFFU, Tradeify, TakeProfitTrader... accounts on Tradovate).
Env (per login, optional suffix): TRADOVATE_USER, TRADOVATE_PASS, TRADOVATE_CID, TRADOVATE_SEC, TRADOVATE_APP_ID,
TRADOVATE_DEVICE_ID, TRADOVATE_ENV=demo|live."""
from __future__ import annotations

import asyncio
import json
import uuid

import httpx

from .base import BrokerError, Connector, env

ENDPOINTS = {"demo": ("https://demo.tradovateapi.com/v1", "wss://demo.tradovateapi.com/v1/websocket"),
             "live": ("https://live.tradovateapi.com/v1", "wss://live.tradovateapi.com/v1/websocket")}


class TradovateConnector(Connector):
    name = "tradovate"
    streams_fills = True

    def __init__(self, live: bool, suffix: str = ""):
        super().__init__(live)
        self.sfx = suffix
        self.env = env(f"TRADOVATE_ENV{suffix}", "TRADOVATE_ENV", required=False) or "demo"
        self.rest, self.ws_url = ENDPOINTS[self.env]
        self.token: str | None = None
        self.account_ids: dict[str, int] = {}

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    async def connect(self) -> None:
        s = self.sfx
        body = {"name": env(f"TRADOVATE_USER{s}"), "password": env(f"TRADOVATE_PASS{s}"),
                "appId": env(f"TRADOVATE_APP_ID{s}", required=False) or "ApolloTrading", "appVersion": "1.0",
                "cid": int(env(f"TRADOVATE_CID{s}")), "sec": env(f"TRADOVATE_SEC{s}"),
                "deviceId": env(f"TRADOVATE_DEVICE_ID{s}", required=False) or str(uuid.uuid4())}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{self.rest}/auth/accesstokenrequest", json=body)
            r.raise_for_status()
            d = r.json()
            if "accessToken" not in d:
                raise BrokerError(f"Tradovate auth failed: {d.get('errorText', d)}")
            self.token = d["accessToken"]
            r = await c.get(f"{self.rest}/account/list", headers=self._h())
            r.raise_for_status()
            self.account_ids = {a["name"]: a["id"] for a in r.json()}
        self.connected = True

    async def place_market(self, account, action, symbol, qty):
        if account not in self.account_ids:
            raise BrokerError(f"Tradovate login has no account {account!r} (has {list(self.account_ids)})")
        body = {"accountSpec": account, "accountId": self.account_ids[account], "action": action, "symbol": symbol,
                "orderQty": int(qty), "orderType": "Market", "isAutomated": True}
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{self.rest}/order/placeorder", json=body, headers=self._h())
            r.raise_for_status()
            return {"mode": self.mode, **r.json()}

    async def positions(self, account):
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.rest}/position/list", headers=self._h())
            r.raise_for_status()
            out: dict[str, float] = {}
            for p in r.json():
                if p.get("accountId") == self.account_ids.get(account) and p.get("netPos"):
                    out[await self._contract(p["contractId"])] = float(p["netPos"])
            return out

    async def _contract(self, cid: int) -> str:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.rest}/contract/item", params={"id": cid}, headers=self._h())
            r.raise_for_status()
            return r.json()["name"]

    async def run_fill_stream(self, master_account, on_fill):
        import websockets
        mid = self.account_ids[master_account]
        async with websockets.connect(self.ws_url) as ws:
            await ws.recv()
            await ws.send(f"authorize\n0\n\n{self.token}")
            await ws.send(f"user/syncrequest\n1\n\n{json.dumps({'accounts': [mid]})}")

            async def hb():
                while True:
                    await asyncio.sleep(2.5)
                    await ws.send("[]")
            t = asyncio.create_task(hb())
            try:
                async for raw in ws:
                    if not raw.startswith("a"):
                        continue
                    for m in json.loads(raw[1:]):
                        d = m.get("d", {}) if m.get("e") == "props" else {}
                        if d.get("entityType") == "fill" and d.get("eventType") == "Created" and d["entity"].get("accountId") == mid:
                            f = d["entity"]
                            on_fill({"account": master_account, "action": f["action"], "qty": float(f["qty"]),
                                     "symbol": await self._contract(f["contractId"]), "price": f.get("price")})
            finally:
                t.cancel()
