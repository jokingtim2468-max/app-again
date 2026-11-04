"""App side of the shared-bot relay: one outbound WebSocket, so nothing has to be opened on the user's PC."""
from __future__ import annotations

import asyncio
import uuid

import httpx
import websockets

from . import settings


class RelayClient:
    def __init__(self, router):
        self.router = router
        self.ws = None
        self.info: dict = {}
        self.status = {"running": False, "error": None}
        self.waiters: dict[str, asyncio.Future] = {}

    def _base(self) -> tuple[str, str]:
        url = settings.load()["relay"]["url"].rstrip("/")
        if not url:
            raise RuntimeError("set the relay URL in Settings")
        return url, url.replace("https://", "wss://").replace("http://", "ws://")

    async def ensure_registered(self) -> None:
        cfg = settings.load()
        r = cfg["relay"]
        if r.get("install_id") and r.get("secret"):
            return
        base, _ = self._base()
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(f"{base}/api/register", headers={"X-Relay-Key": r.get("access_key", "")})
            if resp.status_code == 403:
                raise RuntimeError("the relay requires an access key (ask the relay owner, enter it in Settings)")
            resp.raise_for_status()
            d = resp.json()
        cfg["relay"].update(install_id=d["install_id"], secret=d["secret"])
        settings.save(cfg)

    async def run(self) -> None:
        while True:
            try:
                await self.ensure_registered()
                r = settings.load()["relay"]
                _, wsbase = self._base()
                async with websockets.connect(f"{wsbase}/ws?install_id={r['install_id']}&secret={r['secret']}", max_size=2 ** 22) as ws:
                    self.ws = ws
                    self.status.update(running=True, error=None)
                    await self.sync_codes()
                    async for raw in ws:
                        m = __import__("json").loads(raw)
                        t = m.get("type")
                        if t == "hello":
                            self.info = m
                        elif t == "command":
                            asyncio.create_task(self._answer(m))
                        elif t == "channels" and m.get("req_id") in self.waiters:
                            self.waiters[m["req_id"]].set_result(m.get("channels", []))
                        elif t == "error":
                            self.status["error"] = m.get("error")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.status.update(running=False, error=str(e))
            self.ws = None
            await asyncio.sleep(5)

    async def _answer(self, m: dict) -> None:
        reply = await self.router.handle(m["text"], m["meta"])
        await self._send({"type": "reply", "req_id": m["req_id"], "text": reply or "Done."})

    async def _send(self, msg: dict) -> None:
        if not self.ws:
            raise RuntimeError("not connected to the relay")
        await self.ws.send(__import__("json").dumps(msg))

    async def sync_codes(self) -> None:
        if self.ws:
            await self._send({"type": "codes", "codes": self.router.pending_codes()})

    async def send(self, platform: str, chat_id: str, text: str) -> None:
        await self._send({"type": "send", "platform": platform, "chat_id": chat_id, "text": text})

    async def guild_channels(self, guild_id: str) -> list[dict]:
        rid = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self.waiters[rid] = fut
        await self._send({"type": "list_channels", "req_id": rid, "guild_id": guild_id})
        try:
            return await asyncio.wait_for(fut, 10)
        finally:
            self.waiters.pop(rid, None)

    async def unbind(self, platform: str, key: str) -> None:
        await self._send({"type": "unbind", "platform": platform, "key": key})
