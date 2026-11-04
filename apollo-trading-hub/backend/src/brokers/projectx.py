"""ProjectX Gateway API (TopstepX and other ProjectX-powered prop firms).
Env: PROJECTX_USER, PROJECTX_API_KEY, PROJECTX_URL (default https://api.topstepx.com; each firm has its own gateway host).
Accounts are matched by the account *name* shown in the platform."""
from __future__ import annotations

import httpx

from .base import BrokerError, Connector, env


class ProjectXConnector(Connector):
    name = "projectx"

    def __init__(self, live: bool, suffix: str = ""):
        super().__init__(live)
        self.sfx = suffix
        self.base = (env(f"PROJECTX_URL{suffix}", "PROJECTX_URL", required=False) or "https://api.topstepx.com").rstrip("/")
        self.token = None
        self.accounts: dict[str, int] = {}
        self.contracts: dict[str, str] = {}

    async def _post(self, path, body):
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{self.base}{path}", json=body,
                             headers={"Authorization": f"Bearer {self.token}"} if self.token else {})
            r.raise_for_status()
            d = r.json()
            if d.get("success") is False:
                raise BrokerError(f"ProjectX {path}: {d.get('errorMessage') or d}")
            return d

    async def connect(self):
        d = await self._post("/api/Auth/loginKey", {"userName": env(f"PROJECTX_USER{self.sfx}", "PROJECTX_USER"),
                                                    "apiKey": env(f"PROJECTX_API_KEY{self.sfx}", "PROJECTX_API_KEY")})
        self.token = d["token"]
        a = await self._post("/api/Account/search", {"onlyActiveAccounts": True})
        self.accounts = {x["name"]: x["id"] for x in a.get("accounts", [])}
        self.connected = True

    async def _contract_id(self, symbol: str) -> str:
        if symbol not in self.contracts:
            root = symbol.rstrip("0123456789")[:-1] if symbol[-1:].isdigit() else symbol
            d = await self._post("/api/Contract/search", {"searchText": root, "live": False})
            cands = d.get("contracts", [])
            if not cands:
                raise BrokerError(f"ProjectX: no contract for {symbol}")
            active = [c for c in cands if c.get("activeContract")] or cands
            self.contracts[symbol] = active[0]["id"]
        return self.contracts[symbol]

    async def place_market(self, account, action, symbol, qty):
        if account not in self.accounts:
            raise BrokerError(f"ProjectX login has no account {account!r} (has {list(self.accounts)})")
        d = await self._post("/api/Order/place", {"accountId": self.accounts[account], "contractId": await self._contract_id(symbol),
                                                  "type": 2, "side": 0 if action == "Buy" else 1, "size": int(qty)})
        return {"mode": self.mode, "orderId": d.get("orderId"), "account": account}

    async def positions(self, account):
        d = await self._post("/api/Position/searchOpen", {"accountId": self.accounts[account]})
        # type 1 = long, 2 = short
        return {p["contractId"]: float(p["size"]) * (1 if p.get("type") == 1 else -1) for p in d.get("positions", [])}
