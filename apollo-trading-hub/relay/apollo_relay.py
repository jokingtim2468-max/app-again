"""Apollo Bot Relay: ONE shared Telegram + Discord bot for every Apollo app.

Why a relay: Telegram (getUpdates) and Discord (gateway) allow a single connection per bot, so a bot can't run inside
every user's app. The relay runs the bot once; each Apollo app opens an OUTBOUND WebSocket to it (no ports to open on
the user's PC). Users add the Apollo bot to their server / start it in Telegram, and type /verify CODE (the code comes
from their app) to bind that chat to their app. Commands are forwarded to the right app; the app sends alerts back.

Run (Docker):  docker build -t apollo-relay -f relay/Dockerfile . && docker run -p 8787:8787 --env-file relay.env apollo-relay
Env: RELAY_TELEGRAM_TOKEN, RELAY_DISCORD_TOKEN (either or both), RELAY_ACCESS_KEY (optional: required to register an app),
     RELAY_STATE (default relay_state.json), PORT (8787). Put it behind HTTPS (Caddy/nginx/Cloudflare) for wss://.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.src.bots.discord import DiscordBot  # noqa: E402
from backend.src.bots.telegram import TelegramBot  # noqa: E402

STATE = Path(os.getenv("RELAY_STATE", "relay_state.json"))
ACCESS_KEY = os.getenv("RELAY_ACCESS_KEY", "")
BUILTIN_MENU = [("verify", "Link this chat/server to your Apollo app: /verify CODE"), ("help", "List commands"),
                ("status", "Fleet status"), ("fleet", "Every account"), ("ready", "Payouts ready now"), ("payouts", "Payout status"),
                ("outcomes", "Passed / blown / ROI"), ("profit", "Real profit"), ("pnl", "Today's P&L"),
                ("kill", "CONTROL: kill switch"), ("flatten", "CONTROL: flatten fleet"), ("resume", "CONTROL: resume account"),
                ("requested", "CONTROL: payout requested"), ("paid", "CONTROL: payout paid"), ("rejected", "CONTROL: payout rejected"),
                ("apollo", "Run any (incl. custom) command: /apollo <command>")]


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Relay:
    def __init__(self):
        self.state = json.loads(STATE.read_text()) if STATE.exists() else {"installs": {}, "bindings": []}
        self.conns: dict[str, WebSocket] = {}
        self.codes: dict[str, str] = {}          # code -> install_id (synced from each app)
        self.waiters: dict[str, asyncio.Future] = {}
        self.bots: dict[str, object] = {}
        self.channel_guild: dict[str, str] = {}

    def save(self):
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        tmp.replace(STATE)

    # ---- installs ----
    def register(self) -> dict:
        iid, sec = uuid.uuid4().hex[:16], secrets.token_urlsafe(24)
        self.state["installs"][iid] = {"secret": _h(sec), "created": time.time()}
        self.save()
        return {"install_id": iid, "secret": sec}

    def auth(self, iid: str, sec: str) -> bool:
        i = self.state["installs"].get(iid)
        return bool(i) and secrets.compare_digest(i["secret"], _h(sec))

    def binding_for(self, meta: dict) -> str | None:
        for b in self.state["bindings"]:
            if b["platform"] != meta["platform"]:
                continue
            if (meta["platform"] == "discord" and meta.get("guild_id") and b.get("guild_id") == meta.get("guild_id")) or b["chat_id"] == meta["chat_id"]:
                return b["install_id"]
        return None

    def bind(self, iid: str, meta: dict):
        key = (meta["platform"], meta.get("guild_id") or meta["chat_id"])
        self.state["bindings"] = [b for b in self.state["bindings"] if (b["platform"], b.get("guild_id") or b["chat_id"]) != key]
        self.state["bindings"].append({"install_id": iid, "platform": meta["platform"], "chat_id": meta["chat_id"], "guild_id": meta.get("guild_id")})
        self.save()

    async def owns_destination(self, iid: str, platform: str, chat_id: str) -> bool:
        for b in self.state["bindings"]:
            if b["install_id"] == iid and b["platform"] == platform and b["chat_id"] == chat_id:
                return True
        if platform == "discord" and "discord" in self.bots:  # any channel inside a guild that this app linked
            g = self.channel_guild.get(chat_id)
            if g is None:
                try:
                    g = str((await self.bots["discord"].rest("GET", f"/channels/{chat_id}")).get("guild_id"))
                    self.channel_guild[chat_id] = g
                except Exception:
                    return False
            return any(b["install_id"] == iid and b.get("guild_id") == g for b in self.state["bindings"])
        return False

    # ---- bot -> app ----
    async def forward(self, iid: str, text: str, meta: dict) -> str:
        ws = self.conns.get(iid)
        if not ws:
            return "⚠ The Apollo app linked to this chat is offline right now. Start Apollo and try again."
        rid = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self.waiters[rid] = fut
        await ws.send_json({"type": "command", "req_id": rid, "text": text, "meta": meta})
        try:
            return await asyncio.wait_for(fut, 20)
        except asyncio.TimeoutError:
            return "⚠ Apollo didn't answer in time."
        finally:
            self.waiters.pop(rid, None)

    async def handle(self, text: str, meta: dict) -> str | None:
        parts = (text or "").strip().lstrip("/!").split()
        if not parts:
            return None
        cmd = parts[0].split("@")[0].lower()
        if cmd == "apollo":  # generic passthrough so custom commands work on the shared bot's fixed menu
            parts = parts[1:] or ["help"]
            cmd = parts[0].lower()
        if cmd == "verify" and len(parts) > 1:
            iid = self.codes.get(parts[1].strip().upper())
            if not iid:
                return "❌ Invalid or expired code. Generate a new one in Apollo → Settings → Connect (the app must be running)."
            reply = await self.forward(iid, " ".join(parts), meta)
            if reply.startswith("✅"):
                self.bind(iid, meta)
                self.codes = {c: i for c, i in self.codes.items() if c != parts[1].strip().upper()}
            return reply
        iid = self.binding_for(meta)
        if not iid:
            return ("👋 This is the Apollo Trading bot. To connect it to your Apollo app: open Apollo → Settings → Connect, "
                    "generate a code, then send /verify CODE here.")
        return await self.forward(iid, " ".join(parts), meta)


relay = Relay()


@asynccontextmanager
async def lifespan(app):
    tasks = []
    if os.getenv("RELAY_TELEGRAM_TOKEN"):
        relay.bots["telegram"] = TelegramBot(os.environ["RELAY_TELEGRAM_TOKEN"], relay.handle, lambda: BUILTIN_MENU)
    if os.getenv("RELAY_DISCORD_TOKEN"):
        relay.bots["discord"] = DiscordBot(os.environ["RELAY_DISCORD_TOKEN"], relay.handle, lambda: BUILTIN_MENU)
    for b in relay.bots.values():
        tasks.append(asyncio.create_task(b.run()))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Apollo Bot Relay", lifespan=lifespan)


@app.get("/api/info")
def info():
    d = relay.bots.get("discord"); t = relay.bots.get("telegram")
    return {"discord": {"online": bool(d and d.status["running"]), "invite_url": d.status.get("invite_url") if d else None},
            "telegram": {"online": bool(t and t.status["running"]), "username": t.status.get("username") if t else None},
            "apps_connected": len(relay.conns), "access_key_required": bool(ACCESS_KEY)}


@app.post("/api/register")
def register(x_relay_key: str = Header(default="")):
    if ACCESS_KEY and not secrets.compare_digest(x_relay_key, ACCESS_KEY):
        raise HTTPException(403, "relay access key required")
    return relay.register()


@app.websocket("/ws")
async def ws(sock: WebSocket, install_id: str, secret: str):
    if not relay.auth(install_id, secret):
        await sock.close(code=4401)
        return
    await sock.accept()
    relay.conns[install_id] = sock
    await sock.send_json({"type": "hello", **info()})
    try:
        while True:
            m = await sock.receive_json()
            t = m.get("type")
            if t == "reply" and m.get("req_id") in relay.waiters:
                relay.waiters[m["req_id"]].set_result(m.get("text") or "")
            elif t == "codes":
                relay.codes = {c: i for c, i in relay.codes.items() if i != install_id}
                relay.codes.update({c.upper(): install_id for c in m.get("codes", [])})
            elif t == "send":
                bot = relay.bots.get(m["platform"])
                if bot and await relay.owns_destination(install_id, m["platform"], str(m["chat_id"])):
                    try:
                        await bot.send(m["chat_id"], m["text"])
                    except Exception as e:
                        await sock.send_json({"type": "error", "error": f"send failed: {e}"})
            elif t == "list_channels":
                g = str(m.get("guild_id"))
                ok = any(b["install_id"] == install_id and b.get("guild_id") == g for b in relay.state["bindings"])
                chans = await relay.bots["discord"].guild_channels(g) if ok and "discord" in relay.bots else []
                await sock.send_json({"type": "channels", "req_id": m.get("req_id"), "channels": chans})
            elif t == "unbind":
                relay.state["bindings"] = [b for b in relay.state["bindings"] if not (
                    b["install_id"] == install_id and b["platform"] == m["platform"] and (b.get("guild_id") or b["chat_id"]) == m["key"])]
                relay.save()
    except WebSocketDisconnect:
        pass
    finally:
        if relay.conns.get(install_id) is sock:
            relay.conns.pop(install_id, None)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8787")))
