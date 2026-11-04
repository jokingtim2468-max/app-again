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


def test_telegram_handles_commands_and_registers_menu():
    sent = []

    def h(req):
        body = json.loads(req.content or b"{}")
        m = req.url.path.rsplit("/", 1)[-1]
        sent.append((m, body))
        return httpx.Response(200, json={"ok": True, "result": {"username": "apollo_bot"} if m == "getMe" else True})
    bot = TelegramBot({"token": "123:abc", "allowed_user_ids": ["7"], "control_user_ids": ["9"], "alert_chat_ids": [55]},
                      engine(), httpx.AsyncClient(transport=httpx.MockTransport(h)))
    run(bot.register_commands())
    menu = [c["command"] for c in sent[-1][1]["commands"]]
    assert "gm" in menu and "money" in menu and "payouts" in menu
    reply = run(bot.handle({"update_id": 1, "message": {"text": "/money", "from": {"id": 7}, "chat": {"id": 7}}}))
    assert reply.startswith("ready $450") and sent[-1][0] == "sendMessage" and sent[-1][1]["chat_id"] == 7
    assert "Not authorised" in run(bot.handle({"update_id": 2, "message": {"text": "/status", "from": {"id": 3}, "chat": {"id": 3}}}))
    run(bot.alert("hi"))
    assert sent[-1][1] == {"chat_id": 55, "text": "hi", "disable_web_page_preview": True}


def test_discord_prefix_slash_and_registration():
    sent = []

    def h(req):
        sent.append((req.method, req.url.path, json.loads(req.content or b"null")))
        if req.url.path.endswith("/oauth2/applications/@me"):
            return httpx.Response(200, json={"id": "42"})
        return httpx.Response(200, json={})
    bot = DiscordBot({"token": "t", "prefix": "!", "guild_id": "G", "control_user_ids": ["9"], "alert_channel_ids": ["C"]},
                     engine(), httpx.AsyncClient(transport=httpx.MockTransport(h)))
    run(bot.register_commands())
    m, path, body = sent[-1]
    assert m == "PUT" and path == "/api/v10/applications/42/guilds/G/commands" and {"gm", "money", "kill"} <= {c["name"] for c in body}
    run(bot.on_message({"content": "!money", "channel_id": "C", "author": {"id": "1"}}))
    assert sent[-1][1] == "/api/v10/channels/C/messages" and sent[-1][2]["content"].startswith("ready $450")
    assert run(bot.on_message({"content": "!status", "channel_id": "C", "author": {"id": "1", "bot": True}})) is None
    r = run(bot.on_interaction({"type": 2, "id": "I", "token": "T", "member": {"user": {"id": "9"}},
                                "data": {"name": "kill", "options": [{"name": "args", "value": "ACC2"}]}}))
    assert "Kill switch" in r and sent[-1][1] == "/api/v10/interactions/I/T/callback"


def test_settings_mask_and_keep_token(tmp_path, monkeypatch):
    from backend.src.bots import settings
    monkeypatch.setattr(settings, "PATH", tmp_path / "s.json")
    settings.save({"telegram": {"enabled": True, "token": "123456:ABCDEFGHIJKL"}})
    shown = settings.mask(settings.load())
    assert shown["telegram"]["token"] == "1234…IJKL" and shown["telegram"]["token_set"]
    settings.save({"telegram": {"enabled": True, "token": shown["telegram"]["token"], "alert_chat_ids": [1]}})
    assert settings.load()["telegram"]["token"] == "123456:ABCDEFGHIJKL"        # masked value kept the real token
    import pytest
    with pytest.raises(ValueError):
        settings.save({"custom_commands": [{"name": "bad name!", "type": "template", "value": "x"}]})
