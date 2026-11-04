"""Bot settings (Telegram + Discord), stored locally in backend/state/settings.json (git-ignored).

Tokens never leave this machine and are masked in every API response.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

PATH = Path(os.getenv("APOLLO_SETTINGS", Path(__file__).resolve().parents[2] / "state" / "settings.json"))
_lock = threading.Lock()
SECRET_KEYS = {"token", "secret"}
NOTIFY_KINDS = ["startup", "payout_ready", "PASSED", "FAILED", "PARKED", "UNPARKED", "TARGET_HIT", "DAILY_LIMIT_HIT",
                "PAYOUT", "kill_switch", "graduation_alert", "route_error"]

DEFAULTS = {
    # "relay": use the shared Apollo bot (users just add it and /verify); "own": run your own bot token in this app
    "mode": "own",
    "relay": {"url": "", "access_key": "", "install_id": "", "secret": ""},
    "links": [],
    "tutorial_done": False,
    "telegram": {"enabled": False, "token": "", "alert_chat_ids": [], "allowed_user_ids": [], "control_user_ids": []},
    "discord": {"enabled": False, "token": "", "alert_channel_ids": [], "allowed_user_ids": [], "control_user_ids": [],
                "prefix": "!", "guild_id": ""},
    "notify": {k: True for k in NOTIFY_KINDS},
    "custom_commands": [
        {"name": "gm", "description": "Morning brief", "type": "alias", "value": "status; ready; outcomes"},
        {"name": "money", "description": "Money summary", "type": "template",
         "value": "Ready now: {ready_now_net} to you | Paid so far: {paid_out_net} | Real profit: {real_profit}"},
    ],
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load() -> dict:
    with _lock:
        raw = json.loads(PATH.read_text()) if PATH.exists() else {}
    return _merge(DEFAULTS, raw)


def mask(cfg: dict) -> dict:
    c = copy.deepcopy(cfg)
    for bot in ("telegram", "discord"):
        t = c[bot].get("token") or ""
        c[bot]["token"] = (t[:4] + "…" + t[-4:]) if len(t) > 12 else ("set" if t else "")
        c[bot]["token_set"] = bool(t)
    c["relay"]["secret"] = "set" if c["relay"].get("secret") else ""
    c["relay"]["access_key"] = "set" if c["relay"].get("access_key") else ""
    return c


def save(new: dict) -> dict:
    cur = load()
    for bot in ("telegram", "discord"):  # a masked/blank token in the update means "keep the current one"
        t = (new.get(bot) or {}).get("token")
        if t is None or "…" in str(t) or t == "set":
            new.setdefault(bot, {})["token"] = cur[bot]["token"]
    rs = (new.get("relay") or {}).get("secret")
    if "relay" in new and (rs is None or rs == "set"):
        new["relay"]["secret"] = cur["relay"]["secret"]
    if "relay" in new and new["relay"].get("access_key") in (None, "set"):
        new["relay"]["access_key"] = cur["relay"].get("access_key", "")
    if "relay" in new and new["relay"].get("url", cur["relay"]["url"]) != cur["relay"]["url"]:
        new["relay"].update(install_id="", secret="")  # new relay -> register again
    if "links" not in new:
        new["links"] = cur.get("links", [])
    for c in new.get("custom_commands", []):
        c["name"] = str(c["name"]).strip().lstrip("/!").lower()
        if not c["name"].replace("_", "").isalnum() or len(c["name"]) > 32:
            raise ValueError(f"command name {c['name']!r} must be 1-32 letters/digits/_")
        if c.get("type") not in ("template", "alias"):
            raise ValueError("custom command type must be 'template' or 'alias'")
    if new.get("custom_commands", None) is not None and any(c["name"] == "verify" for c in new["custom_commands"]):
        raise ValueError("'verify' is reserved for linking chats")
    merged = _merge(cur, new)  # partial updates keep everything else that is already stored
    merged["links"] = new.get("links", cur.get("links", []))
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(merged, indent=2))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(PATH)
    return merged
