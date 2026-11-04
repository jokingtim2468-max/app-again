"""Telegram bot via the Bot API (long polling: works behind NAT, no public URL needed).

Transport only: every command goes to `handler(text, meta) -> reply`, so the same client runs inside the Apollo app
(own bot token) or inside the shared Apollo Bot Relay.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import httpx

log = logging.getLogger("apollo.telegram")
API = "https://api.telegram.org/bot{token}/{method}"
Handler = Callable[[str, dict], Awaitable[str | None]]


class TelegramBot:
    def __init__(self, token: str, handler: Handler, menu: Callable[[], list[tuple[str, str]]],
                 client: httpx.AsyncClient | None = None):
        self.token, self.handler, self.menu = token, handler, menu
        self.client = client or httpx.AsyncClient(timeout=40)
        self.offset = 0
        self.status = {"running": False, "error": None, "username": None}

    async def call(self, method: str, **params):
        r = await self.client.post(API.format(token=self.token, method=method), json=params)
        d = r.json()
        if not d.get("ok"):
            raise RuntimeError(f"Telegram {method}: {d.get('description', r.status_code)}")
        return d["result"]

    async def send(self, chat_id, text: str) -> None:
        for i in range(0, len(text), 4000):
            await self.call("sendMessage", chat_id=chat_id, text=text[i:i + 4000], disable_web_page_preview=True)

    async def register_commands(self) -> None:
        """Puts every command (built-in + custom + /verify) into Telegram's '/' menu at launch."""
        cmds = [{"command": n, "description": (d or n)[:250]} for n, d in self.menu()][:100]
        await self.call("setMyCommands", commands=cmds)

    async def handle(self, upd: dict) -> str | None:
        m = upd.get("message") or upd.get("edited_message")
        if not m or not (m.get("text") or "").startswith("/"):
            return None
        chat = m["chat"]
        meta = {"platform": "telegram", "user_id": str(m["from"]["id"]), "user_name": m["from"].get("username") or m["from"].get("first_name"),
                "chat_id": str(chat["id"]), "chat_title": chat.get("title") or chat.get("username") or chat.get("first_name") or "private chat",
                "chat_type": chat.get("type")}
        reply = await self.handler(m["text"], meta)
        if reply:
            await self.send(chat["id"], reply)
        return reply

    async def run(self) -> None:
        me = await self.call("getMe")
        self.status.update(running=True, username=me.get("username"), error=None)
        await self.register_commands()
        while True:
            try:
                ups = await self.call("getUpdates", offset=self.offset, timeout=30, allowed_updates=["message"])
                for u in ups:
                    self.offset = u["update_id"] + 1
                    await self.handle(u)
                self.status["error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.status["error"] = str(e)
                log.warning("telegram poll error: %s", e)
                await asyncio.sleep(5)
