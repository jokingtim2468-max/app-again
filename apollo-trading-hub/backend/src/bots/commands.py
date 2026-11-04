"""Shared command engine for the Telegram and Discord bots.

Read commands are open to allowed users (or everyone if the allow-list is empty).
Control commands (kill/flatten/resume/requested/paid/rejected) ONLY run for user IDs in control_user_ids.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

MAX_LEN = 1900  # Discord limit is 2000, Telegram 4096


@dataclass
class Ctx:
    platform: str
    user_id: str
    can_control: bool


def money(v) -> str:
    v = float(v or 0)
    return ("-" if v < 0 else "") + f"${abs(v):,.0f}"


class CommandEngine:
    def __init__(self, api: dict[str, Callable]):
        """api: hooks into the running server (status, payouts, outcomes, profit, kill, flatten, resume, paid...)."""
        self.api = api
        self.builtins: dict[str, tuple[str, Callable, bool]] = {
            "help": ("List commands", self.c_help, False),
            "status": ("Fleet mode, price, day P&L, firm caps", self.c_status, False),
            "fleet": ("Every account: balance, cushion to MLL, status", self.c_fleet, False),
            "ready": ("Accounts eligible for a payout right now", self.c_ready, False),
            "payouts": ("Payout status of every funded account", self.c_payouts, False),
            "outcomes": ("Passed / blown / target hits / daily-limit hits / ROI", self.c_outcomes, False),
            "profit": ("Real profit: payouts minus costs, by firm", self.c_profit, False),
            "pnl": ("Today's P&L by account", self.c_pnl, False),
            "kill": ("CONTROL: flatten + halt all (or: kill <account>)", self.c_kill, True),
            "flatten": ("CONTROL: flatten the whole fleet", self.c_flatten, True),
            "resume": ("CONTROL: resume <account>", self.c_resume, True),
            "requested": ("CONTROL: requested <account> [amount]", self.c_requested, True),
            "paid": ("CONTROL: paid <account> [amount]", self.c_paid, True),
            "rejected": ("CONTROL: rejected <account>", self.c_rejected, True),
        }
        self.custom: list[dict] = []

    def set_custom(self, cmds: list[dict]) -> None:
        self.custom = [c for c in cmds if c.get("name") and c["name"] not in self.builtins]

    def menu(self) -> list[tuple[str, str]]:
        return [(k, v[0]) for k, v in self.builtins.items()] + [(c["name"], c.get("description") or "custom") for c in self.custom]

    async def run(self, text: str, ctx: Ctx, depth: int = 0) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        name, *args = text.split()
        name = name.lstrip("/!").split("@")[0].lower()
        if name in self.builtins:
            _, fn, control = self.builtins[name]
            if control and not ctx.can_control:
                return f"⛔ /{name} is a control command. Add your {ctx.platform} user ID ({ctx.user_id}) to Control users in Apollo Settings."
            try:
                out = fn(args, ctx)
                if inspect.isawaitable(out):
                    out = await out
                return str(out)[:MAX_LEN]
            except Exception as e:  # never crash the bot loop
                return f"⚠ {name} failed: {e}"
        cc = next((c for c in self.custom if c["name"] == name), None)
        if cc:
            if cc["type"] == "alias":
                if depth > 2:
                    return "⚠ alias nesting too deep"
                parts = [p.strip() for p in cc["value"].split(";") if p.strip()]
                outs = [await self.run(p, ctx, depth + 1) for p in parts]
                return "\n\n".join(o for o in outs if o)[:MAX_LEN]
            return self.render(cc["value"])[:MAX_LEN]
        return f"Unknown command '{name}'. Send /help."

    # ---- template variables for custom commands ----
    def variables(self) -> dict:
        st, po, oc, pr = self.api["status"](), self.api["payouts"](), self.api["outcomes"](), self.api["profit"]()
        accts = list(st["accounts"].values())
        f = oc["fleet"]
        v = {"mode": st["mode"], "price": f"{st.get('last', 0):.1f}", "symbol": st.get("symbol", ""),
             "accounts": len(accts), "funded": sum(a["stage"] == "FUNDED" for a in accts),
             "evals": sum(a["stage"] == "EVALUATION" for a in accts),
             "fleet_day_pnl": money(sum(a["day_pnl"] for a in accts)),
             "ready_count": sum(1 for r in po["accounts"] if r.get("eligible")),
             "ready_now_net": money(po["totals"]["ready_now_net"]), "month_ceiling": money(po["totals"]["month_ceiling_net"]),
             "paid_out_net": money(pr["totals"].get("payouts_net", 0)), "costs": money(pr["totals"].get("costs", 0)),
             "real_profit": money(pr["totals"].get("real_profit", 0)), "trading_pnl": money(pr["totals"].get("trading_pnl", 0)),
             "passed": f["evals_passed"], "blown": f["total_blown"], "target_hits": f["evals_hit_target"],
             "daily_limit_hits": f["daily_limit_hits"], "pass_rate": "—" if f["pass_rate"] is None else f"{f['pass_rate']:.0%}",
             "parked": sum(a["parked"] for a in accts)}
        return v

    def render(self, tpl: str) -> str:
        v = self.variables()
        return re.sub(r"\{(\w+)\}", lambda m: str(v.get(m.group(1), m.group(0))), tpl)

    # ---- built-ins ----
    def c_help(self, args, ctx):
        lines = ["Apollo commands:"]
        for name, desc in self.menu():
            lock = " 🔒" if name in self.builtins and self.builtins[name][2] else ""
            lines.append(f"/{name} — {desc}{lock}")
        lines.append("\nCustom template variables: " + ", ".join("{" + k + "}" for k in sorted(self.variables())))
        return "\n".join(lines)

    def c_status(self, args, ctx):
        st = self.api["status"]()
        accts = list(st["accounts"].values())
        day = sum(a["day_pnl"] for a in accts)
        lines = [f"Apollo · {st['mode']} · {st.get('symbol')} {st.get('last', 0):.1f}",
                 f"Fleet day P&L {money(day)} · {len(accts)} accounts"]
        for k, f in (st.get("firms") or {}).items():
            lines.append(f"{f['firm_name']}: {f['funded']}/{f['cap'] if f['cap'] is not None else '∞'} funded · "
                         f"{f['evals_trading']} evals · {f['parked']} parked · {f['failed']} blown")
        return "\n".join(lines)

    def c_fleet(self, args, ctx):
        st = self.api["status"]()
        rows = [f"{'★' if a['account_id'] == st['master'] else ' '}{a['account_id']}: {money(a['closed_balance'])} "
                f"| cushion {money(a['distance_to_mll'])} | {a['stage'][:4]} {a['status']}" for a in st["accounts"].values()]
        return "\n".join(rows) or "No accounts."

    def c_ready(self, args, ctx):
        po = self.api["payouts"]()
        ready = [r for r in po["accounts"] if r.get("eligible")]
        if not ready:
            return "No payouts ready right now."
        out = [f"💰 {len(ready)} ready · {money(po['totals']['ready_now_net'])} to you"]
        out += [f"{r['account_id']} ({r['firm']}): request {money(r['max_request'])} → {money(r['net_to_you'])} to you\n  {r.get('dashboard_url') or ''}"
                for r in ready]
        return "\n".join(out)

    def c_payouts(self, args, ctx):
        po = self.api["payouts"]()
        rows = [r for r in po["accounts"] if r["stage"] == "FUNDED" and r["status"] not in ("CLOSED", "LIQUIDATED")]
        if not rows:
            return "No funded accounts."
        return "\n".join(f"{r['account_id']}: " + (f"READY {money(r['max_request'])}" if r["eligible"] else
                         f"pending {money(r['pending'])}" if r.get("pending") else (r["blockers"] or ["—"])[0]) for r in rows)

    def c_outcomes(self, args, ctx):
        f = self.api["outcomes"]()["fleet"]
        pr = "—" if f["pass_rate"] is None else f"{f['pass_rate']:.0%}"
        rpd = "—" if f["return_per_dollar"] is None else f"${f['return_per_dollar']:.2f}"
        return (f"Evals passed {f['evals_passed']} (pass rate {pr}) · hit target {f['evals_hit_target']}\n"
                f"Blown {f['total_blown']} ({f['evals_blown']} eval, {f['funded_blown']} funded) · daily-limit hits {f['daily_limit_hits']}\n"
                f"Payouts {f['payouts']} · net {money(f['payouts_net'])} · costs {money(f['costs'])} · real profit {money(f['real_profit'])} · {rpd} back per $1")

    def c_profit(self, args, ctx):
        pr = self.api["profit"]()
        t = pr["totals"]
        lines = [f"Real profit {money(t.get('real_profit'))} = net payouts {money(t.get('payouts_net'))} − costs {money(t.get('costs'))}",
                 f"Trading P&L (sim) {money(t.get('trading_pnl'))}"]
        lines += [f"{k}: {money(b['real_profit'])} ({b['payout_count']} payouts)" for k, b in pr["by_firm"].items()]
        return "\n".join(lines)

    def c_pnl(self, args, ctx):
        st = self.api["status"]()
        return "\n".join(f"{a['account_id']}: {money(a['day_pnl'])}" for a in st["accounts"].values()) or "No accounts."

    async def c_kill(self, args, ctx):
        r = await self.api["kill"](args[0] if args else None)
        return f"🛑 Kill switch: halted {', '.join(r['halted'])} ({len(r['flatten_orders'])} flatten orders)"

    async def c_flatten(self, args, ctx):
        await self.api["flatten"]()
        return "Flatten sent to the fleet."

    def c_resume(self, args, ctx):
        if not args:
            return "Usage: resume <account>"
        return f"{args[0]}: " + ("resumed" if self.api["resume"](args[0])["resumed"] else "not killed (cashout/blown accounts can't resume)")

    def _acct_amt(self, args):
        if not args:
            raise ValueError("usage: <account> [amount]")
        return args[0], (float(args[1].replace("$", "").replace(",", "")) if len(args) > 1 else None)

    def c_requested(self, args, ctx):
        a, amt = self._acct_amt(args)
        r = self.api["requested"](a, amt)
        return f"{a}: payout of {money(r['pending'])} marked requested."

    def c_paid(self, args, ctx):
        a, amt = self._acct_amt(args)
        r = self.api["paid"](a, amt)
        return f"✅ {a}: payout #{r['payout_number']} {money(r['amount'])} recorded ({money(r.get('net_to_you', 0))} to you)."

    def c_rejected(self, args, ctx):
        a, _ = self._acct_amt(args)
        self.api["rejected"](a)
        return f"{a}: pending payout cleared as rejected."


ALERT_TEXT: dict[str, Callable[[dict], str]] = {
    "payout_ready": lambda e: f"💰 Payout ready: {e.get('account_id')} ({e.get('firm')}) request {money(e.get('max_request'))} → {money(e.get('net_to_you'))} to you\n{e.get('dashboard_url') or ''}",
    "PASSED": lambda e: f"🎉 {e['account']} PASSED its evaluation and is now funded",
    "FAILED": lambda e: f"💥 {e['account']} BLOWN ({e.get('stage', '').lower()}) at {money(e.get('balance'))}",
    "PARKED": lambda e: f"🅿 {e['account']} parked at {money(e.get('profit'))} profit (firm cap full, queue #{e.get('queue_position')})",
    "UNPARKED": lambda e: f"▶ {e['account']} released from the queue: a funded slot opened",
    "TARGET_HIT": lambda e: f"🎯 {e['account']} hit its profit target ({money(e.get('profit'))})",
    "DAILY_LIMIT_HIT": lambda e: f"⚠ {e['account']} hit its daily loss limit ({money(e.get('day_pnl'))})",
    "PAYOUT": lambda e: f"✅ {e['account']} payout recorded: {money(e.get('amount'))} ({money(e.get('net'))} to you)",
    "kill_switch": lambda e: f"🛑 Kill switch engaged: {', '.join(e.get('accounts', []))}",
    "graduation_alert": lambda e: f"🎓 {e.get('operator_alert')}",
    "route_error": lambda e: f"⚠ Order routing error on {e.get('account')}: {e.get('error')}",
}


def alert_for(e: dict) -> tuple[str, str] | None:
    """Server event -> (notify kind, text) or None."""
    kind = e.get("kind") if e.get("type") == "lifecycle" else e.get("type")
    fn = ALERT_TEXT.get(kind or "")
    return (kind, fn(e)) if fn else None


Hook = Callable[..., Awaitable]
