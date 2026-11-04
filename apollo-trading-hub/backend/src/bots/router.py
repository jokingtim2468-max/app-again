"""Per-app command router: /verify linking, permissions and alert destinations.

Linking flow (no IDs to copy by hand):
 1. Apollo -> Settings -> "Generate code" (optionally granting control commands to whoever verifies).
 2. In the Discord channel / Telegram chat: /verify CODE
 3. That chat (and for Discord, its whole server) is linked to this app; the verifying user becomes an allowed user
    (and a control user if granted). In Settings you then pick which channels/chats get which alerts.
"""
from __future__ import annotations

import secrets
import string
import time
from datetime import datetime

from . import settings
from .commands import CommandEngine, Ctx

CODE_TTL = 600
ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "O0I1")


class Router:
    def __init__(self, engine: CommandEngine):
        self.engine = engine
        self.codes: dict[str, dict] = {}
        self.listeners = []  # callbacks(link) after a successful /verify

    # ---- verification codes ----
    def new_code(self, grant_control: bool = False, label: str = "") -> dict:
        self._expire()
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        self.codes[code] = {"expires": time.time() + CODE_TTL, "control": grant_control, "label": label}
        return {"code": code, "expires_in": CODE_TTL, "control": grant_control}

    def _expire(self):
        now = time.time()
        for c in [c for c, v in self.codes.items() if v["expires"] < now]:
            self.codes.pop(c)

    def pending_codes(self) -> list[str]:
        self._expire()
        return list(self.codes)

    def verify(self, code: str, meta: dict) -> tuple[bool, str, dict | None]:
        self._expire()
        info = self.codes.pop(code.strip().upper(), None)
        if not info:
            return False, "❌ That code is invalid or expired. Generate a new one in Apollo → Settings → Connect.", None
        cfg = settings.load()
        plat = meta["platform"]
        link_id = f"{plat}:{meta.get('guild_id') or meta['chat_id']}"
        links = [l for l in cfg.get("links", []) if l["id"] != link_id]
        old = next((l for l in cfg.get("links", []) if l["id"] == link_id), None)
        link = {"id": link_id, "platform": plat, "chat_id": meta["chat_id"], "guild_id": meta.get("guild_id"),
                "title": meta.get("chat_title") or plat, "linked_by": meta["user_id"], "linked_by_name": meta.get("user_name"),
                "linked_at": datetime.now().isoformat(timespec="seconds"),
                # default: alerts go to the channel/chat where /verify was typed; change in Settings
                "destinations": (old or {}).get("destinations") or {meta["chat_id"]: {"name": meta.get("chat_title"), "kinds": list(settings.NOTIFY_KINDS)}}}
        links.append(link)
        bot = cfg[plat]
        if meta["user_id"] not in [str(x) for x in bot.get("allowed_user_ids", [])]:
            bot.setdefault("allowed_user_ids", []).append(meta["user_id"])
        if info["control"] and meta["user_id"] not in [str(x) for x in bot.get("control_user_ids", [])]:
            bot.setdefault("control_user_ids", []).append(meta["user_id"])
        cfg["links"] = links
        settings.save(cfg)
        for fn in self.listeners:
            fn(link)
        where = f"server **{link['title']}**" if plat == "discord" and meta.get("guild_id") else f"**{link['title']}**"
        ctl = " You can also run control commands (kill/flatten/paid…)." if info["control"] else ""
        return True, (f"✅ Linked {where} to your Apollo app. Alerts will post here; pick other channels and alert types in "
                      f"Apollo → Settings → Destinations.{ctl} Send /help for commands."), link

    # ---- permissions + dispatch ----
    @staticmethod
    def is_linked(meta: dict) -> bool:
        return any(l["platform"] == meta["platform"] and (l["chat_id"] == meta["chat_id"] or (l.get("guild_id") and l.get("guild_id") == meta.get("guild_id")))
                   for l in settings.load().get("links", []))

    def perms(self, meta: dict) -> tuple[bool, bool]:
        """Only verified/allowed users may read; only control users may act. Other members of a linked server are refused."""
        bot = settings.load()[meta["platform"]]
        allowed = {str(x) for x in bot.get("allowed_user_ids", [])}
        control = {str(x) for x in bot.get("control_user_ids", [])}
        uid = meta["user_id"]
        return (uid in allowed or uid in control), uid in control

    async def handle(self, text: str, meta: dict) -> str | None:
        parts = (text or "").strip().lstrip("/!").split()
        if not parts:
            return None
        cmd = parts[0].split("@")[0].lower()
        if cmd == "verify":
            if len(parts) < 2:
                return "Usage: /verify CODE (get a code in Apollo → Settings → Connect)"
            return self.verify(parts[1], meta)[1]
        ok, ctl = self.perms(meta)
        if not ok:
            if self.is_linked(meta):
                return (f"⛔ You're not an allowed user for this Apollo app. Ask the owner to add your {meta['platform']} ID "
                        f"({meta['user_id']}) in Apollo → Settings, or verify yourself with a code from the app.")
            return (f"⛔ This chat isn't linked to your Apollo app yet. In Apollo → Settings → Connect, generate a code and "
                    f"send /verify CODE here. Your {meta['platform']} user ID is {meta['user_id']}.")
        return await self.engine.run(" ".join(parts), Ctx(meta["platform"], meta["user_id"], ctl))

    def menu(self) -> list[tuple[str, str]]:
        return [("verify", "Link this chat/server to your Apollo app: /verify CODE")] + self.engine.menu()

    # ---- alert destinations ----
    @staticmethod
    def destinations(kind: str) -> list[tuple[str, str]]:
        """[(platform, chat_or_channel_id)] that subscribed to this alert kind (links + legacy alert IDs)."""
        cfg = settings.load()
        out = []
        for l in cfg.get("links", []):
            for cid, d in (l.get("destinations") or {}).items():
                if kind in d.get("kinds", []):
                    out.append((l["platform"], str(cid)))
        for cid in cfg["telegram"].get("alert_chat_ids") or []:
            out.append(("telegram", str(cid)))
        for cid in cfg["discord"].get("alert_channel_ids") or []:
            out.append(("discord", str(cid)))
        return list(dict.fromkeys(out))
