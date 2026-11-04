import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.src.bots.commands import CommandEngine, Ctx, alert_for  # noqa: E402
from backend.src.bots.discord import DiscordBot  # noqa: E402
from backend.src.bots.telegram import TelegramBot  # noqa: E402

STATUS = {"mode": "PAPER", "symbol": "MGCZ6", "last": 2900.0, "master": "M",
          "accounts": {"M": {"account_id": "M", "closed_balance": 151000, "distance_to_mll": 4500, "stage": "FUNDED",
                             "status": "ACTIVE", "day_pnl": 250.0, "parked": False}},
          "firms": {"lucid": {"firm_name": "Lucid Trading", "funded": 1, "cap": 5, "evals_trading": 0, "parked": 0, "failed": 0}}}
PAYOUTS = {"accounts": [{"account_id": "M", "firm": "Lucid Trading", "eligible": True, "max_request": 500, "net_to_you": 450,
                         "dashboard_url": "https://x", "stage": "FUNDED", "status": "ACTIVE", "pending": 0, "blockers": []}],
           "totals": {"ready_now_net": 450, "month_ceiling_net": 10800}}
OUT = {"fleet": {"evals_passed": 1, "pass_rate": 0.5, "evals_hit_target": 1, "total_blown": 1, "evals_blown": 1, "funded_blown": 0,
                 "daily_limit_hits": 0, "payouts": 2, "payouts_net": 1800, "costs": 300, "real_profit": 1500, "return_per_dollar": 6.0}}
PROFIT = {"totals": {"real_profit": 1500, "payouts_net": 1800, "costs": 300, "trading_pnl": 5000},
          "by_firm": {"lucid": {"real_profit": 1500, "payout_count": 2}}}
calls = []


async def _kill(a):
    calls.append(("kill", a))
    return {"halted": [a or "M"], "flatten_orders": []}


def engine():
    e = CommandEngine({"status": lambda: STATUS, "payouts": lambda: PAYOUTS, "outcomes": lambda: OUT, "profit": lambda: PROFIT,
                       "kill": _kill, "flatten": _kill, "resume": lambda a: {"resumed": True},
                       "requested": lambda a, amt=None: {"pending": amt or 500},
                       "paid": lambda a, amt=None: {"payout_number": 1, "amount": amt or 500, "net_to_you": 450},
                       "rejected": lambda a: None})
    e.set_custom([{"name": "gm", "type": "alias", "value": "status; ready"},
                  {"name": "money", "type": "template", "value": "ready {ready_now_net} · profit {real_profit} · passed {passed}"},
                  {"name": "status", "type": "template", "value": "can't shadow built-ins"}])
    return e


def run(c):
    return asyncio.run(c)


def test_engine_builtins_custom_and_permissions():
    e = engine()
    viewer, admin = Ctx("t", "1", False), Ctx("t", "2", True)
    assert "Lucid Trading: 1/5 funded" in run(e.run("/status", viewer))
    assert "request $500 → $450 to you" in run(e.run("ready", viewer))
    assert run(e.run("money", viewer)) == "ready $450 · profit $1,500 · passed 1"
    gm = run(e.run("!gm", viewer))
    assert "Apollo · PAPER" in gm and "1 ready" in gm
    assert "control command" in run(e.run("kill", viewer)) and not calls
    assert "Kill switch" in run(e.run("kill ACC1", admin)) and calls[-1] == ("kill", "ACC1")
    assert "$1,000" in run(e.run("paid ACC1 1,000", admin))
    assert [n for n, _ in e.menu()].count("status") == 1          # custom can't override a built-in


def test_alert_formatting():
    k, t = alert_for({"type": "lifecycle", "kind": "FAILED", "account": "E1", "stage": "EVALUATION", "balance": 145500})
    assert k == "FAILED" and "E1 BLOWN" in t
    assert alert_for({"type": "payout_ready", "account_id": "M", "firm": "Lucid", "max_request": 500, "net_to_you": 450})[0] == "payout_ready"
    assert alert_for({"type": "trade"}) is None


def _router(tmp_path, monkeypatch):
    from backend.src.bots import settings
    from backend.src.bots.router import Router
    monkeypatch.setattr(settings, "PATH", tmp_path / "s.json")
    return Router(engine()), settings


def test_verify_links_chat_grants_roles_and_routes_alerts(tmp_path, monkeypatch):
    r, settings = _router(tmp_path, monkeypatch)
    meta = {"platform": "discord", "user_id": "77", "user_name": "tim", "chat_id": "C1", "guild_id": "G1", "chat_title": "Apollo HQ"}
    assert "isn't linked" in run(r.handle("status", meta))                       # unlinked chat is refused
    assert "invalid or expired" in run(r.handle("verify NOPE12", meta))
    code = r.new_code(grant_control=True)["code"]
    reply = run(r.handle(f"/verify {code.lower()}", meta))
    assert reply.startswith("✅ Linked server **Apollo HQ**") and "control commands" in reply
    cfg = settings.load()
    assert cfg["links"][0]["id"] == "discord:G1" and "77" in cfg["discord"]["allowed_user_ids"] and "77" in cfg["discord"]["control_user_ids"]
    assert "1 ready" in run(r.handle("ready", meta))
    assert "Kill switch" in run(r.handle("kill", meta))                          # granted control
    assert "invalid" in run(r.handle(f"verify {code}", meta))                    # codes are single use
    other = {**meta, "user_id": "88", "chat_id": "C2"}                          # same server, unverified member: refused
    assert "not an allowed user" in run(r.handle("ready", other)) and "88" in run(r.handle("ready", other))
    cfg = settings.load(); cfg["discord"]["allowed_user_ids"].append("88"); settings.save(cfg)
    assert "1 ready" in run(r.handle("ready", other)) and "control command" in run(r.handle("kill", other))   # added: read only
    cfg = settings.load()
    assert r.destinations("FAILED") == [("discord", "C1")]                      # default: where /verify was typed
    cfg["links"][0]["destinations"] = {"C1": {"kinds": ["payout_ready"]}, "C9": {"kinds": ["FAILED", "PASSED"]}}
    settings.save(cfg)
    assert r.destinations("FAILED") == [("discord", "C9")] and r.destinations("payout_ready") == [("discord", "C1")]


def test_verify_code_without_control_and_telegram_menu(tmp_path, monkeypatch):
    r, settings = _router(tmp_path, monkeypatch)
    sent = []

    def h(req):
        sent.append((req.url.path.rsplit("/", 1)[-1], json.loads(req.content or b"{}")))
        return httpx.Response(200, json={"ok": True, "result": True})
    bot = TelegramBot("123:abc", r.handle, r.menu, httpx.AsyncClient(transport=httpx.MockTransport(h)))
    run(bot.register_commands())
    menu = [c["command"] for c in sent[-1][1]["commands"]]
    assert menu[0] == "verify" and {"gm", "money", "payouts"} <= set(menu)
    code = r.new_code(False)["code"]
    rep = run(bot.handle({"update_id": 1, "message": {"text": f"/verify {code}", "from": {"id": 5, "first_name": "T"}, "chat": {"id": -100, "title": "Gold desk", "type": "group"}}}))
    assert rep.startswith("✅ Linked **Gold desk**") and sent[-1][1]["chat_id"] == -100
    assert "control command" in run(bot.handle({"update_id": 2, "message": {"text": "/kill", "from": {"id": 5}, "chat": {"id": -100}}}))
    assert run(bot.handle({"update_id": 3, "message": {"text": "/money", "from": {"id": 5}, "chat": {"id": -100}}})).startswith("ready $450")


def test_discord_transport_slash_prefix_and_channels(tmp_path, monkeypatch):
    r, _ = _router(tmp_path, monkeypatch)
    sent = []

    def h(req):
        sent.append((req.method, req.url.path, json.loads(req.content or b"null")))
        if req.url.path.endswith("/oauth2/applications/@me"):
            return httpx.Response(200, json={"id": "42"})
        if req.url.path.endswith("/guilds/G/channels"):
            return httpx.Response(200, json=[{"id": "a", "name": "alerts", "type": 0, "position": 2}, {"id": "v", "name": "voice", "type": 2},
                                             {"id": "p", "name": "payouts", "type": 0, "position": 1}])
        return httpx.Response(200, json={})
    bot = DiscordBot("t", r.handle, r.menu, "!", "G", httpx.AsyncClient(transport=httpx.MockTransport(h)))
    run(bot.register_commands())
    assert sent[-1][1] == "/api/v10/applications/42/guilds/G/commands" and sent[-1][2][0]["name"] == "verify"
    assert "client_id=42" in bot.status["invite_url"] and "applications.commands" in bot.status["invite_url"]
    code = r.new_code(True)["code"]
    rep = run(bot.on_interaction({"type": 2, "id": "I", "token": "T", "guild_id": "G", "channel_id": "a", "member": {"user": {"id": "9"}},
                                  "data": {"name": "verify", "options": [{"name": "args", "value": code}]}}))
    assert rep.startswith("✅") and sent[-1][1] == "/api/v10/interactions/I/T/callback"
    run(bot.on_message({"content": "!money", "channel_id": "a", "guild_id": "G", "author": {"id": "9"}}))
    assert sent[-1][2]["content"].startswith("ready $450")
    assert [c["name"] for c in run(bot.guild_channels("G"))] == ["payouts", "alerts"]   # text channels only, in order


def test_relay_binds_on_verify_and_forwards(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("RELAY_STATE", str(tmp_path / "relay.json"))
    rmod = importlib.reload(importlib.import_module("relay.apollo_relay"))
    app_router, _ = _router(tmp_path, monkeypatch)
    relay = rmod.Relay()
    reg = relay.register()
    assert relay.auth(reg["install_id"], reg["secret"]) and not relay.auth(reg["install_id"], "wrong")

    class FakeAppSocket:  # stands in for the app's WebSocket: answers commands with the app's own router
        async def send_json(self, m):
            if m["type"] == "command":
                relay.waiters[m["req_id"]].set_result(await app_router.handle(m["text"], m["meta"]))
    relay.conns[reg["install_id"]] = FakeAppSocket()
    meta = {"platform": "telegram", "user_id": "5", "chat_id": "-100", "chat_title": "Desk"}
    assert "To connect it to your Apollo app" in run(relay.handle("status", meta))     # unbound chat
    code = app_router.new_code(False)["code"]
    relay.codes[code] = reg["install_id"]                                           # synced by the app's RelayClient
    assert run(relay.handle(f"/verify {code}", meta)).startswith("✅")
    assert relay.binding_for(meta) == reg["install_id"]
    assert run(relay.handle("/apollo money", meta)).startswith("ready $450")          # custom command via passthrough
    assert run(relay.owns_destination(reg["install_id"], "telegram", "-100"))
    assert not run(relay.owns_destination(reg["install_id"], "telegram", "-999"))    # can't send to chats it didn't link
    relay.conns.clear()
    assert "offline" in run(relay.handle("status", meta))


def test_settings_mask_and_keep_token(tmp_path, monkeypatch):
    from backend.src.bots import settings
    monkeypatch.setattr(settings, "PATH", tmp_path / "s.json")
    settings.save({"telegram": {"enabled": True, "token": "123456:ABCDEFGHIJKL"}})
    assert settings.load()["custom_commands"]           # partial save keeps defaults/other settings
    shown = settings.mask(settings.load())
    assert shown["telegram"]["token"] == "1234…IJKL" and shown["telegram"]["token_set"]
    settings.save({"telegram": {"enabled": True, "token": shown["telegram"]["token"], "alert_chat_ids": [1]}})
    assert settings.load()["telegram"]["token"] == "123456:ABCDEFGHIJKL"        # masked value kept the real token
    import pytest
    with pytest.raises(ValueError):
        settings.save({"custom_commands": [{"name": "bad name!", "type": "template", "value": "x"}]})
