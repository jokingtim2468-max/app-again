"""Runs the bots (own token) or the relay connection (shared Apollo bot), and routes alerts to linked destinations."""
from __future__ import annotations

import asyncio

from . import settings
from .commands import CommandEngine, alert_for
from .discord import DiscordBot
from .relay_client import RelayClient
from .router import Router
from .telegram import TelegramBot


class BotManager:
    def __init__(self, api: dict):
        self.engine = CommandEngine(api)
        self.router = Router(self.engine)
        self.bots: dict[str, object] = {}
        self.relay: RelayClient | None = None
        self.tasks: list[asyncio.Task] = []
        self.cfg = settings.load()
        self.recent_links: list[dict] = []
        self.router.listeners.append(lambda link: self.recent_links.append(link))

    @property
    def mode(self) -> str:
        return self.cfg.get("mode", "own")

    async def start(self) -> None:
        """(Re)launch with current settings; re-registers built-in + custom commands with Telegram/Discord."""
        await self.stop()
        self.cfg = settings.load()
        self.engine.set_custom(self.cfg.get("custom_commands", []))
        if self.mode == "relay":
            if self.cfg["relay"].get("url"):
                self.relay = RelayClient(self.router)
                self.tasks.append(asyncio.create_task(self.relay.run()))
        else:
            tg, dc = self.cfg["telegram"], self.cfg["discord"]
            if tg.get("enabled") and tg.get("token"):
                self.bots["telegram"] = TelegramBot(tg["token"], self.router.handle, self.router.menu)
            if dc.get("enabled") and dc.get("token"):
                self.bots["discord"] = DiscordBot(dc["token"], self.router.handle, self.router.menu, dc.get("prefix", "!"), dc.get("guild_id", ""))
            for name, b in self.bots.items():
                self.tasks.append(asyncio.create_task(self._guard(b)))
        if self.cfg["notify"].get("startup") and (self.bots or self.relay):
            asyncio.get_running_loop().call_later(4, lambda: asyncio.ensure_future(
                self.broadcast("startup", "🚀 Apollo Trading online. Send /help for commands.")))

    async def _guard(self, bot):
        try:
            await bot.run()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # bad token etc.: show it in Settings instead of crashing the server
            bot.status.update(running=False, error=str(e))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        self.tasks.clear()
        for b in self.bots.values():
            try:
                await b.client.aclose()
            except Exception:
                pass
        self.bots.clear()
        self.relay = None

    # ---- outbound ----
    async def send(self, platform: str, chat_id: str, text: str) -> None:
        if self.relay:
            await self.relay.send(platform, chat_id, text)
        elif platform in self.bots:
            await self.bots[platform].send(chat_id, text)

    async def broadcast(self, kind: str, text: str) -> list[str]:
        sent = []
        for platform, cid in self.router.destinations(kind):
            try:
                await self.send(platform, cid, text)
                sent.append(f"{platform}:{cid}")
            except Exception as e:
                tgt = self.relay or self.bots.get(platform)
                if tgt:
                    tgt.status["error"] = f"alert to {cid} failed: {e}"
        return sent

    def on_event(self, e: dict) -> None:
        a = alert_for(e)
        if a and self.cfg["notify"].get(a[0], False) and (self.bots or self.relay):
            asyncio.ensure_future(self.broadcast(*a))

    # ---- linking ----
    async def new_code(self, grant_control: bool) -> dict:
        c = self.router.new_code(grant_control)
        if self.relay:
            await self.relay.sync_codes()
        return c

    async def guild_channels(self, guild_id: str) -> list[dict]:
        if self.relay:
            return await self.relay.guild_channels(guild_id)
        if "discord" in self.bots:
            return await self.bots["discord"].guild_channels(guild_id)
        return []

    async def unlink(self, link_id: str) -> None:
        cfg = settings.load()
        link = next((l for l in cfg.get("links", []) if l["id"] == link_id), None)
        cfg["links"] = [l for l in cfg.get("links", []) if l["id"] != link_id]
        settings.save(cfg)
        if link and self.relay:
            await self.relay.unbind(link["platform"], link.get("guild_id") or link["chat_id"])

    def status(self) -> dict:
        if self.mode == "relay":
            r = self.relay
            info = r.info if r else {}
            return {"mode": "relay", "relay": {**(r.status if r else {"running": False, "error": "relay URL not set"}), "info": info}}
        return {"mode": "own", **{n: {**getattr(self.bots.get(n), "status", {"running": False, "error": None}),
                                      "enabled": self.cfg[n].get("enabled", False)} for n in ("telegram", "discord")}}
