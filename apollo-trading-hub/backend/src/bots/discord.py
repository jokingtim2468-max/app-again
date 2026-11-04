"""Discord bot over the Gateway WebSocket (no public URL needed).

- Slash commands for every built-in + custom command are registered at launch (guild-scoped if guild_id is set:
  instant; otherwise global: can take up to an hour to appear the first time).
- Prefix commands (default "!status") also work; that needs the MESSAGE CONTENT intent enabled for the bot in the
  Discord Developer Portal (Bot > Privileged Gateway Intents).
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import websockets

from .commands import CommandEngine, Ctx

log = logging.getLogger("apollo.discord")
REST = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
INTENTS = (1 << 0) | (1 << 9) | (1 << 12) | (1 << 15)  # GUILDS, GUILD_MESSAGES, DIRECT_MESSAGES, MESSAGE_CONTENT


class DiscordBot:
    def __init__(self, cfg: dict, engine: CommandEngine, client: httpx.AsyncClient | None = None):
        self.cfg, self.engine = cfg, engine
        self.client = client or httpx.AsyncClient(timeout=20)
        self.app_id: str | None = None
        self.status = {"running": False, "error": None, "username": None}
        self.seq = None

    def _h(self):
        return {"Authorization": f"Bot {self.cfg['token']}"}

    async def rest(self, method: str, path: str, **kw):
        r = await self.client.request(method, REST + path, headers=self._h(), **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Discord {method} {path}: {r.status_code} {r.text[:200]}")
        return r.json() if r.content else None

    async def send(self, channel_id, text: str) -> None:
        for i in range(0, len(text), 1900):
            await self.rest("POST", f"/channels/{channel_id}/messages", json={"content": text[i:i + 1900]})

    async def register_commands(self) -> None:
        app = await self.rest("GET", "/oauth2/applications/@me")
        self.app_id = app["id"]
        body = [{"name": n, "description": (d or n)[:100], "type": 1,
                 "options": [{"type": 3, "name": "args", "description": "arguments, e.g. account and amount", "required": False}]}
                for n, d in self.engine.menu()][:100]
        g = self.cfg.get("guild_id")
        path = f"/applications/{self.app_id}/guilds/{g}/commands" if g else f"/applications/{self.app_id}/commands"
        await self.rest("PUT", path, json=body)

    def _perm(self, uid: str) -> tuple[bool, bool]:
        al = [str(x) for x in self.cfg.get("allowed_user_ids") or []]
        ctl = [str(x) for x in self.cfg.get("control_user_ids") or []]
        return (not al or uid in al or uid in ctl), uid in ctl

    async def on_message(self, d: dict) -> str | None:
        pre = self.cfg.get("prefix") or "!"
        text = d.get("content") or ""
        if d.get("author", {}).get("bot") or not text.startswith(pre):
            return None
        uid = str(d["author"]["id"])
        ok, ctl = self._perm(uid)
        reply = await self.engine.run(text[len(pre):], Ctx("discord", uid, ctl)) if ok else \
            f"⛔ Not authorised. Your Discord user ID is {uid}; add it in Apollo Settings."
        await self.send(d["channel_id"], reply)
        return reply

    async def on_interaction(self, d: dict) -> str | None:
        if d.get("type") != 2:
            return None
        user = (d.get("member") or {}).get("user") or d.get("user") or {}
        uid = str(user.get("id"))
        name = d["data"]["name"]
        args = next((o["value"] for o in d["data"].get("options", []) if o["name"] == "args"), "")
        ok, ctl = self._perm(uid)
        reply = await self.engine.run(f"{name} {args}".strip(), Ctx("discord", uid, ctl)) if ok else \
            f"⛔ Not authorised. Your Discord user ID is {uid}; add it in Apollo Settings."
        await self.client.post(f"{REST}/interactions/{d['id']}/{d['token']}/callback",
                               json={"type": 4, "data": {"content": reply[:1900]}})
        return reply

    async def _heartbeat(self, ws, interval: float):
        while True:
            await asyncio.sleep(interval)
            await ws.send(json.dumps({"op": 1, "d": self.seq}))

    async def run(self) -> None:
        await self.register_commands()
        while True:
            try:
                async with websockets.connect(GATEWAY, max_size=2 ** 22) as ws:
                    hello = json.loads(await ws.recv())
                    hb = asyncio.create_task(self._heartbeat(ws, hello["d"]["heartbeat_interval"] / 1000))
                    await ws.send(json.dumps({"op": 2, "d": {"token": self.cfg["token"], "intents": INTENTS,
                                                             "properties": {"os": "apollo", "browser": "apollo", "device": "apollo"}}}))
                    try:
                        async for raw in ws:
                            m = json.loads(raw)
                            if m.get("s") is not None:
                                self.seq = m["s"]
                            if m.get("op") == 0:
                                t, d = m.get("t"), m.get("d") or {}
                                if t == "READY":
                                    self.status.update(running=True, username=d["user"]["username"], error=None)
                                elif t == "MESSAGE_CREATE":
                                    await self.on_message(d)
                                elif t == "INTERACTION_CREATE":
                                    await self.on_interaction(d)
                            elif m.get("op") in (7, 9):  # reconnect / invalid session
                                break
                    finally:
                        hb.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.status["error"] = str(e)
                log.warning("discord gateway error: %s", e)
            await asyncio.sleep(5)

    async def alert(self, text: str) -> None:
        for cid in self.cfg.get("alert_channel_ids") or []:
            try:
                await self.send(cid, text)
            except Exception as e:
                self.status["error"] = f"alert to {cid} failed: {e}"
