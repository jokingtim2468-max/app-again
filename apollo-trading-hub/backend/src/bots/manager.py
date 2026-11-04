"""Starts/stops the bots from Settings, registers custom commands at launch, and fans out alerts."""
from __future__ import annotations

import asyncio

from . import settings
from .commands import CommandEngine, alert_for
from .discord import DiscordBot
from .telegram import TelegramBot


class BotManager:
    def __init__(self, api: dict):
        self.engine = CommandEngine(api)
        self.bots: dict[str, object] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.cfg = settings.load()

    async def start(self) -> None:
        """(Re)launch every enabled bot with the current settings and custom commands."""
        await self.stop()
        self.cfg = settings.load()
        self.engine.set_custom(self.cfg.get("custom_commands", []))
        for name, cls in (("telegram", TelegramBot), ("discord", DiscordBot)):
            c = self.cfg[name]
            if c.get("enabled") and c.get("token"):
                bot = cls(c, self.engine)
                self.bots[name] = bot
                self.tasks[name] = asyncio.create_task(self._guard(name, bot))
        if self.cfg["notify"].get("startup"):
            asyncio.get_running_loop().call_later(3, lambda: asyncio.ensure_future(
                self.broadcast("🚀 Apollo Trading online. Send /help for commands.")))

    async def _guard(self, name, bot):
        try:
            await bot.run()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # bad token etc.: surface in Settings instead of crashing the server
            bot.status.update(running=False, error=str(e))

    async def stop(self) -> None:
        for t in self.tasks.values():
            t.cancel()
        self.tasks.clear()
        for b in self.bots.values():
            try:
                await b.client.aclose()
            except Exception:
                pass
        self.bots.clear()

    async def broadcast(self, text: str) -> None:
        for b in list(self.bots.values()):
            await b.alert(text)

    def on_event(self, e: dict) -> None:
        a = alert_for(e)
        if a and self.cfg["notify"].get(a[0], False) and self.bots:
            asyncio.ensure_future(self.broadcast(a[1]))

    def status(self) -> dict:
        return {n: {**getattr(self.bots.get(n), "status", {"running": False, "error": None}),
                    "enabled": self.cfg[n].get("enabled", False)} for n in ("telegram", "discord")}
