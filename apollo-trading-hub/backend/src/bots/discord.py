"""Discord bot over the Gateway WebSocket (no public URL needed).

Transport only: commands go to `handler(text, meta) -> reply`. Slash commands for every command (incl. /verify) are
registered at launch (guild-scoped = instant; global can take up to an hour the first time). Prefix commands like
!status also work if the MESSAGE CONTENT intent is enabled for the bot.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import httpx
import websockets

log = logging.getLogger("apollo.discord")
REST = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
INTENTS = (1 << 0) | (1 << 9) | (1 << 12) | (1 << 15)  # GUILDS, GUILD_MESSAGES, DIRECT_MESSAGES, MESSAGE_CONTENT
INVITE_PERMS = 1024 | 2048 | 16384 | 65536             # view channel, send messages, embed links, read history
Handler = Callable[[str, dict], Awaitable[str | None]]


def invite_url(app_id: str) -> str:
    return f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands&permissions={INVITE_PERMS}"


class DiscordBot:
    def __init__(self, token: str, handler: Handler, menu: Callable[[], list[tuple[str, str]]], prefix: str = "!",
                 guild_id: str = "", client: httpx.AsyncClient | None = None):
        self.token, self.handler, self.menu, self.prefix, self.guild_id = token, handler, menu, prefix or "!", guild_id
        self.client = client or httpx.AsyncClient(timeout=20)
        self.app_id: str | None = None
        self.status = {"running": False, "error": None, "username": None, "invite_url": None}
        self.seq = None
        self.guild_names: dict[str, str] = {}

    def _h(self):
        return {"Authorization": f"Bot {self.token}"}

    async def rest(self, method: str, path: str, **kw):
        r = await self.client.request(method, REST + path, headers=self._h(), **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Discord {method} {path}: {r.status_code} {r.text[:200]}")
        return r.json() if r.content else None

    async def send(self, channel_id, text: str) -> None:
        for i in range(0, len(text), 1900):
            await self.rest("POST", f"/channels/{channel_id}/messages", json={"content": text[i:i + 1900]})

    async def guild_channels(self, guild_id: str) -> list[dict]:
        """Text channels the bot can see in a server: lets the user pick where each alert goes."""
        chans = await self.rest("GET", f"/guilds/{guild_id}/channels")
        return [{"id": c["id"], "name": c["name"], "position": c.get("position", 0)} for c in sorted(chans, key=lambda c: c.get("position", 0))
                if c.get("type") in (0, 5)]  # text + announcement

    async def register_commands(self) -> None:
        app = await self.rest("GET", "/oauth2/applications/@me")
        self.app_id = app["id"]
        self.status["invite_url"] = invite_url(self.app_id)
        body = [{"name": n, "description": (d or n)[:100], "type": 1,
                 "options": [{"type": 3, "name": "args", "description": "arguments (e.g. the verification code, or account + amount)", "required": False}]}
                for n, d in self.menu()][:100]
        path = f"/applications/{self.app_id}/guilds/{self.guild_id}/commands" if self.guild_id else f"/applications/{self.app_id}/commands"
        await self.rest("PUT", path, json=body)

    def _meta(self, d: dict, user: dict) -> dict:
        g = d.get("guild_id")
        return {"platform": "discord", "user_id": str(user.get("id")), "user_name": user.get("global_name") or user.get("username"),
                "chat_id": str(d.get("channel_id")), "guild_id": str(g) if g else None,
                "chat_title": self.guild_names.get(str(g), "server") if g else "direct message"}

    async def on_message(self, d: dict) -> str | None:
        text = d.get("content") or ""
        if d.get("author", {}).get("bot") or not text.startswith(self.prefix):
            return None
        reply = await self.handler(text[len(self.prefix):], self._meta(d, d["author"]))
        if reply:
            await self.send(d["channel_id"], reply)
        return reply

    async def on_interaction(self, d: dict) -> str | None:
        if d.get("type") != 2:
            return None
        user = (d.get("member") or {}).get("user") or d.get("user") or {}
        name = d["data"]["name"]
        args = next((o["value"] for o in d["data"].get("options", []) if o["name"] == "args"), "")
        reply = await self.handler(f"{name} {args}".strip(), self._meta(d, user)) or "Done."
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
                    await ws.send(json.dumps({"op": 2, "d": {"token": self.token, "intents": INTENTS,
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
                                elif t == "GUILD_CREATE":
                                    self.guild_names[str(d["id"])] = d.get("name", "server")
                                elif t == "MESSAGE_CREATE":
                                    await self.on_message(d)
                                elif t == "INTERACTION_CREATE":
                                    await self.on_interaction(d)
                            elif m.get("op") in (7, 9):
                                break
                    finally:
                        hb.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.status["error"] = str(e)
                log.warning("discord gateway error: %s", e)
            await asyncio.sleep(5)
