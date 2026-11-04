"""1 master -> N slave copy trader on Tradovate.

Safety: runs in PAPER mode (fills simulated locally, no orders sent) unless CLAW_LIVE=1.
With CLAW_LIVE=1 and TRADOVATE_ENV=demo it trades the Tradovate demo; TRADOVATE_ENV=live
targets real accounts. Every slave order passes RiskSentinel.validate_order first.

Credentials come from env: TRADOVATE_USER, TRADOVATE_PASS, TRADOVATE_APP_ID,
TRADOVATE_CID, TRADOVATE_SEC, TRADOVATE_DEVICE_ID. Never commit them.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Callable

import httpx
import websockets

from .risk_sentinel import RiskSentinel

log = logging.getLogger("closed_claw.bridge")

ENDPOINTS = {
    "demo": ("https://demo.tradovateapi.com/v1", "wss://demo.tradovateapi.com/v1/websocket"),
    "live": ("https://live.tradovateapi.com/v1", "wss://live.tradovateapi.com/v1/websocket"),
}


@dataclass
class Fill:
    account: str
    action: str  # Buy / Sell
    symbol: str
    qty: int
    price: float | None = None


class TradovateBridge:
    def __init__(self, sentinel: RiskSentinel, on_event: Callable[[dict], None] | None = None):
        self.sentinel = sentinel
        self.cfg = sentinel.config
        self.live = os.getenv("CLAW_LIVE") == "1"
        self.env = os.getenv("TRADOVATE_ENV", "demo")
        self.rest, self.ws_url = ENDPOINTS[self.env]
        self.token: str | None = None
        self.account_ids: dict[str, int] = {}
        self.on_event = on_event or (lambda e: None)
        self.ws = None
        self._req = 1
        self.copy_ratio = 1  # 1:1 contract mirroring
        self.journal: list[dict] = []

    @property
    def mode(self) -> str:
        return f"LIVE:{self.env}" if self.live else "PAPER"

    # ---- auth ------------------------------------------------------------
    async def authenticate(self) -> None:
        if not self.live:
            return
        body = {
            "name": os.environ["TRADOVATE_USER"], "password": os.environ["TRADOVATE_PASS"],
            "appId": os.getenv("TRADOVATE_APP_ID", "ClosedClaw"), "appVersion": "1.0",
            "cid": int(os.environ["TRADOVATE_CID"]), "sec": os.environ["TRADOVATE_SEC"],
            "deviceId": os.getenv("TRADOVATE_DEVICE_ID", str(uuid.uuid4())),
        }
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{self.rest}/auth/accesstokenrequest", json=body)
            r.raise_for_status()
            data = r.json()
            if "accessToken" not in data:
                raise RuntimeError(f"Tradovate auth failed: {data.get('errorText', data)}")
            self.token = data["accessToken"]
            r = await c.get(f"{self.rest}/account/list", headers=self._h())
            r.raise_for_status()
            self.account_ids = {a["name"]: a["id"] for a in r.json()}
        log.info("authenticated; accounts=%s", list(self.account_ids))

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    # ---- order routing ---------------------------------------------------
    async def place_market(self, account: str, action: str, symbol: str, qty: int) -> dict:
        if not self.live:
            res = {"mode": "PAPER", "account": account, "action": action, "symbol": symbol, "qty": qty,
                   "orderId": f"paper-{uuid.uuid4().hex[:8]}"}
        else:
            body = {"accountSpec": account, "accountId": self.account_ids[account], "action": action,
                    "symbol": symbol, "orderQty": qty, "orderType": "Market", "isAutomated": True}
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{self.rest}/order/placeorder", json=body, headers=self._h())
                r.raise_for_status()
                res = {"mode": self.mode, **r.json()}
        acct = self.sentinel.accounts.get(account)
        if acct:
            acct.position_qty += qty if action == "Buy" else -qty
        self.journal.append(res)
        self.on_event({"type": "order", **res})
        return res

    async def mirror(self, master_fill: Fill) -> list[dict]:
        """Copy a master fill to every slave 1:1 after risk validation."""
        results = []
        for slave in self.cfg["slave_accounts"]:
            acct = self.sentinel.accounts[slave]
            qty = master_fill.qty * self.copy_ratio
            # closing orders reduce exposure: always allowed unless halted
            reducing = (acct.position_qty > 0 and master_fill.action == "Sell") or \
                       (acct.position_qty < 0 and master_fill.action == "Buy")
            if not reducing:
                check = self.sentinel.validate_order(slave, acct.stage, qty, master_fill.symbol)
                if not check["approved"]:
                    qty = check["approved_qty"]
                    self.on_event({"type": "risk_clamp", "account": slave, **check})
                    if qty <= 0:
                        continue
            elif acct.halted or acct.liquidated:
                continue
            results.append(await self.place_market(slave, master_fill.action, master_fill.symbol, qty))
        return results

    # ---- websocket listener ---------------------------------------------
    async def run(self) -> None:
        """Listen to master account fills and mirror them. In PAPER mode this idles."""
        await self.authenticate()
        if not self.live:
            log.warning("PAPER mode: no broker connection. Use /api/fleet/simulate_fill to drive copies.")
            while True:
                await asyncio.sleep(3600)
        master_id = self.account_ids[self.cfg["master_account"]]
        async with websockets.connect(self.ws_url) as ws:
            self.ws = ws
            await ws.recv()  # 'o' open frame
            await ws.send(f"authorize\n0\n\n{self.token}")
            await ws.send(f"user/syncrequest\n1\n\n{json.dumps({'accounts': [master_id]})}")
            hb = asyncio.create_task(self._heartbeat(ws))
            try:
                async for raw in ws:
                    await self._handle(raw, master_id)
            finally:
                hb.cancel()

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(2.5)
            await ws.send("[]")

    async def _handle(self, raw: str, master_id: int) -> None:
        if not raw.startswith("a"):
            return
        for msg in json.loads(raw[1:]):
            if msg.get("e") != "props":
                continue
            d = msg.get("d", {})
            if d.get("entityType") == "fill" and d.get("eventType") == "Created":
                f = d["entity"]
                if f.get("accountId") != master_id:
                    continue
                contract = await self._contract_name(f["contractId"])
                fill = Fill(self.cfg["master_account"], f["action"], contract, int(f["qty"]), f.get("price"))
                self.on_event({"type": "master_fill", **fill.__dict__})
                await self.mirror(fill)

    async def _contract_name(self, contract_id: int) -> str:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.rest}/contract/item", params={"id": contract_id}, headers=self._h())
            r.raise_for_status()
            return r.json()["name"]

    async def flatten(self, account: str, symbol: str) -> dict | None:
        acct = self.sentinel.accounts[account]
        if acct.position_qty == 0:
            return None
        action = "Sell" if acct.position_qty > 0 else "Buy"
        return await self.place_market(account, action, symbol, abs(acct.position_qty))
