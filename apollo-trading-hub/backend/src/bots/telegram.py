"""Telegram bot via the Bot API (long polling: works behind NAT, no public URL needed)."""
from __future__ import annotations

import asyncio
import logging

import httpx

from .commands import CommandEngine, Ctx

log = logging.getLogger("apollo.telegram")
API = "https://api.telegram.org/bot{token}/{method}"


class TelegramBot:
    def __init__(self, cfg: dict, engine: CommandEngine, client: httpx.AsyncClient | None = None):
        self.cfg, self.engine = cfg, engine
        self.client = client or httpx.AsyncClient(timeout=40)
        self.offset = 0
        self.status = {"running": False, "error": None, "username": None}

    async def call(self, method: str, **params):
        r = await self.client.post(API.format(token=self.cfg["token"], method=method), json=params)
        d = r.json()
        if not d.get("ok"):
            raise RuntimeError(f"Telegram {method}: {d.get('description', r.status_code)}")
        return d["result"]

    async def send(self, chat_id, text: str) -> None:
        for i in range(0, len(text), 4000):
            await self.call("sendMessage", chat_id=chat_id, text=text[i:i + 4000], disable_web_page_preview=True)

    async def register_commands(self) -> None:
        """Puts every built-in and custom command into Telegram's '/' menu at launch."""
        cmds = [{"command": n, "description": (d or n)[:250]} for n, d in self.engine.menu()][:100]
        await self.call("setMyCommands", commands=cmds)

    def allowed(self, uid: str) -> bool:
        al = [str(x) for x in self.cfg.get("allowed_user_ids") or []]
        return not al or uid in al or uid in [str(x) for x in self.cfg.get("control_user_ids") or []]

    async def handle(self, upd: dict) -> str | None:
        m = upd.get("message") or upd.get("edited_message")
        if not m or not (m.get("text") or "").startswith("/"):
            return None
        uid, chat = str(m["from"]["id"]), m["chat"]["id"]
        if not self.allowed(uid):
            reply = f"⛔ Not authorised. Your Telegram user ID is {uid}; add it in Apollo Settings."
        else:
            ctx = Ctx("telegram", uid, uid in [str(x) for x in self.cfg.get("control_user_ids") or []])
            reply = await self.engine.run(m["text"], ctx)
        await self.send(chat, reply)
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

    async def alert(self, text: str) -> None:
        for cid in self.cfg.get("alert_chat_ids") or []:
            try:
                await self.send(cid, text)
            except Exception as e:
                self.status["error"] = f"alert to {cid} failed: {e}"
