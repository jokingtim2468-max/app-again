"""Permanent journal (SQLite): balance history, fills, payouts, daily P&L, costs, lifecycle events.

backend/state/apollo.db by default (APOLLO_DB to override). Everything the fleet does is appended here, so balances,
payout logs and profit logs can be reported and exported at any time, across restarts and fleet reloads.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DB_PATH = Path(os.getenv("APOLLO_DB", Path(__file__).resolve().parents[1] / "state" / "apollo.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS balances (ts TEXT, account TEXT, firm TEXT, kind TEXT, balance REAL, equity REAL, mll REAL,
    open_pnl REAL, day_pnl REAL, stage TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS fills (ts TEXT, account TEXT, firm TEXT, action TEXT, qty REAL, symbol TEXT, price REAL,
    realized REAL, mode TEXT, order_id TEXT);
CREATE TABLE IF NOT EXISTS payouts (ts TEXT, account TEXT, firm TEXT, event TEXT, payout_number INTEGER, gross REAL,
    net_to_you REAL, split REAL, balance_after REAL, note TEXT);
CREATE TABLE IF NOT EXISTS daily_pnl (session TEXT, account TEXT, firm TEXT, stage TEXT, start_balance REAL,
    end_balance REAL, pnl REAL, mll REAL, status TEXT, PRIMARY KEY (session, account));
CREATE TABLE IF NOT EXISTS costs (ts TEXT, account TEXT, firm TEXT, kind TEXT, amount REAL, note TEXT);
CREATE TABLE IF NOT EXISTS events (ts TEXT, account TEXT, firm TEXT, kind TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS ix_bal ON balances(account, ts);
CREATE INDEX IF NOT EXISTS ix_fill ON fills(account, ts);
"""
TABLES = ("balances", "fills", "payouts", "daily_pnl", "costs", "events")


def now() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


class Journal:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def _ins(self, table: str, row: dict) -> None:
        cols = ",".join(row)
        with self.lock:
            self.db.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values()))
            self.db.commit()

    # ---- writers ----
    def balance(self, a, kind: str = "snapshot") -> None:
        self._ins("balances", {"ts": now(), "account": a.account_id, "firm": a.firm, "kind": kind,
                               "balance": round(a.closed_balance, 2), "equity": round(a.equity, 2), "mll": a.mll,
                               "open_pnl": round(a.open_pnl, 2), "day_pnl": round(a.equity - a.day_start_balance, 2),
                               "stage": a.stage, "status": a.status})

    def fill(self, a, action, qty, symbol, price, realized, mode="", order_id="") -> None:
        self._ins("fills", {"ts": now(), "account": a.account_id, "firm": a.firm, "action": action, "qty": qty,
                            "symbol": symbol, "price": price, "realized": round(realized, 2), "mode": mode, "order_id": str(order_id)})

    def payout(self, a, event, gross, net, split, note="") -> None:
        self._ins("payouts", {"ts": now(), "account": a.account_id, "firm": a.firm, "event": event,
                              "payout_number": a.payouts_approved + (0 if event == "PAID" else 1), "gross": round(gross, 2),
                              "net_to_you": round(net, 2), "split": split, "balance_after": round(a.closed_balance, 2), "note": note})

    def day(self, a, session: str, start_balance: float) -> None:
        self._ins("daily_pnl", {"session": session, "account": a.account_id, "firm": a.firm, "stage": a.stage,
                                "start_balance": round(start_balance, 2), "end_balance": round(a.closed_balance, 2),
                                "pnl": round(a.closed_balance - start_balance, 2), "mll": a.mll, "status": a.status})

    def cost(self, account: str, firm: str, kind: str, amount: float, note: str = "") -> None:
        self._ins("costs", {"ts": now(), "account": account, "firm": firm, "kind": kind, "amount": round(amount, 2), "note": note})

    def event(self, e: dict) -> None:
        self._ins("events", {"ts": e.get("ts", now()), "account": e.get("account"), "firm": e.get("firm"), "kind": e.get("kind"),
                             "data": json.dumps({k: v for k, v in e.items() if k not in ("ts", "account", "firm", "kind")}, default=str)})

    # ---- readers ----
    def query(self, table: str, account: str | None = None, firm: str | None = None, start: str | None = None,
              end: str | None = None, limit: int = 5000) -> list[dict]:
        if table not in TABLES:
            raise ValueError(f"unknown log {table}; one of {TABLES}")
        tcol = "session" if table == "daily_pnl" else "ts"
        where, args = [], []
        for col, val in (("account", account), ("firm", firm)):
            if val:
                where.append(f"{col} = ?"); args.append(val)
        if start:
            where.append(f"{tcol} >= ?"); args.append(start)
        if end:
            where.append(f"{tcol} <= ?"); args.append(end + ("T99" if len(end) == 10 and tcol == "ts" else ""))
        sql = f"SELECT * FROM {table}{' WHERE ' + ' AND '.join(where) if where else ''} ORDER BY {tcol} DESC, rowid DESC LIMIT ?"
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args + [limit])]

    def csv(self, table: str, **kw) -> str:
        rows = self.query(table, **kw)[::-1]
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        return buf.getvalue()

    def outcome_stats(self, specs: list[dict] | None = None, start: str | None = None, end: str | None = None) -> dict:
        """Account outcomes from the permanent event log: passes, blows, target/daily-limit hits, payouts, ROI."""
        ev = self.query("events", start=start, end=end, limit=1_000_000)[::-1]
        pays = [p for p in self.query("payouts", start=start, end=end, limit=1_000_000) if p["event"] == "PAID"]
        costs = self.query("costs", start=start, end=end, limit=1_000_000)
        days = self.query("daily_pnl", start=start, end=end, limit=1_000_000)
        first_day: dict[str, str] = {}
        for d in days:
            first_day[d["account"]] = min(first_day.get(d["account"], d["session"]), d["session"])
        bought = {s["id"]: s.get("purchased_at") for s in (specs or [])}
        firms: dict[str, dict] = {}

        def F(f):
            return firms.setdefault(f or "unknown", {"accounts": set(), "evals": set(), "funded_seen": set(), "passed": set(),
                                                     "target_hit": set(), "blown_eval": set(), "blown_funded": set(),
                                                     "daily_limit_hits": 0, "daily_limit_accounts": set(), "parked": set(),
                                                     "maxed_out": set(), "graduated": set(), "closed": set(),
                                                     "payouts": 0, "payouts_gross": 0.0, "payouts_net": 0.0, "paid_accounts": set(),
                                                     "costs": 0.0, "days_to_pass": []})
        for s in specs or []:
            f = F(s.get("firm"))
            f["accounts"].add(s["id"])
            (f["funded_seen"] if s.get("stage") == "FUNDED" else f["evals"]).add(s["id"])
        for e in ev:
            f, a, k = F(e["firm"]), e["account"], e["kind"]
            f["accounts"].add(a)
            data = json.loads(e["data"] or "{}")
            if k == "PASSED":
                f["passed"].add(a); f["funded_seen"].add(a); f["evals"].add(a)
                start_d = bought.get(a) or first_day.get(a)
                if start_d:
                    try:
                        f["days_to_pass"].append((datetime.fromisoformat(e["ts"][:10]) - datetime.fromisoformat(start_d[:10])).days)
                    except ValueError:
                        pass
            elif k == "TARGET_HIT":
                f["target_hit"].add(a); f["evals"].add(a)
            elif k == "FAILED":
                (f["blown_funded"] if data.get("stage") == "FUNDED" else f["blown_eval"]).add(a)
            elif k == "DAILY_LIMIT_HIT":
                f["daily_limit_hits"] += 1; f["daily_limit_accounts"].add(a)
            elif k == "PARKED":
                f["parked"].add(a)
            elif k == "GRADUATION_CASHOUT":
                f["graduated"].add(a)
            elif k == "CLOSED":
                f["closed"].add(a)
                if "max" in str(data.get("reason", "")):
                    f["maxed_out"].add(a)
        for p in pays:
            f = F(p["firm"]); f["payouts"] += 1; f["payouts_gross"] += p["gross"]; f["payouts_net"] += p["net_to_you"]
            f["paid_accounts"].add(p["account"])
        for c in costs:
            F(c["firm"])["costs"] += c["amount"]

        def finish(f):
            n = lambda k: len(f[k])
            evals = n("evals")
            resolved = n("passed") + n("blown_eval")
            funded = n("funded_seen")
            out = {"accounts": n("accounts"), "evals_bought": evals, "evals_passed": n("passed"),
                   "evals_hit_target": n("target_hit"), "evals_blown": n("blown_eval"),
                   "pass_rate": round(n("passed") / resolved, 3) if resolved else None,
                   "funded_accounts": funded, "funded_blown": n("blown_funded"),
                   "funded_blow_rate": round(n("blown_funded") / funded, 3) if funded else None,
                   "total_blown": len(f["blown_eval"] | f["blown_funded"]),
                   "daily_limit_hits": f["daily_limit_hits"], "accounts_hit_daily_limit": n("daily_limit_accounts"),
                   "ever_parked": n("parked"), "maxed_out": n("maxed_out"), "graduated": n("graduated"), "closed": n("closed"),
                   "payouts": f["payouts"], "accounts_paid": n("paid_accounts"),
                   "avg_payouts_per_funded": round(f["payouts"] / funded, 2) if funded else None,
                   "payouts_gross": round(f["payouts_gross"], 2), "payouts_net": round(f["payouts_net"], 2),
                   "costs": round(f["costs"], 2), "real_profit": round(f["payouts_net"] - f["costs"], 2),
                   "return_per_dollar": round(f["payouts_net"] / f["costs"], 2) if f["costs"] else None,
                   "cost_per_funded": round(f["costs"] / n("passed"), 2) if n("passed") else None,
                   "avg_days_to_pass": round(sum(f["days_to_pass"]) / len(f["days_to_pass"]), 1) if f["days_to_pass"] else None}
            return out
        by_firm = {k: finish(v) for k, v in firms.items()}
        merged = {k: set() if isinstance(v, set) else [] if isinstance(v, list) else 0 for k, v in F("__fleet__").items()}
        firms.pop("__fleet__")
        for v in firms.values():
            for k, x in v.items():
                merged[k] = merged[k] | x if isinstance(x, set) else merged[k] + x
        return {"fleet": finish(merged), "by_firm": by_firm}

    def profit_report(self, start: str | None = None, end: str | None = None) -> dict:
        """Trading P&L (sim balances) vs real money (payouts received minus costs), by account, firm, month."""
        days = self.query("daily_pnl", start=start, end=end, limit=100000)
        pays = [p for p in self.query("payouts", start=start, end=end, limit=100000) if p["event"] == "PAID"]
        costs = self.query("costs", start=start, end=end, limit=100000)
        acc: dict[str, dict] = {}
        firm: dict[str, dict] = {}
        month: dict[str, dict] = {}

        def bucket(d, k, **base):
            return d.setdefault(k, {"trading_pnl": 0.0, "winning_days": 0, "losing_days": 0, "payouts_gross": 0.0,
                                    "payouts_net": 0.0, "payout_count": 0, "costs": 0.0, **base})
        for r in days:
            for b in (bucket(acc, r["account"], firm=r["firm"]), bucket(firm, r["firm"]), bucket(month, r["session"][:7])):
                b["trading_pnl"] += r["pnl"]
                b["winning_days" if r["pnl"] > 0 else "losing_days"] += 1 if r["pnl"] else 0
        for p in pays:
            for b in (bucket(acc, p["account"], firm=p["firm"]), bucket(firm, p["firm"]), bucket(month, p["ts"][:7])):
                b["payouts_gross"] += p["gross"]; b["payouts_net"] += p["net_to_you"]; b["payout_count"] += 1
        for c in costs:
            for b in (bucket(acc, c["account"], firm=c["firm"]), bucket(firm, c["firm"]), bucket(month, c["ts"][:7])):
                b["costs"] += c["amount"]
        for d in (acc, firm, month):
            for b in d.values():
                for k in ("trading_pnl", "payouts_gross", "payouts_net", "costs"):
                    b[k] = round(b[k], 2)
                b["real_profit"] = round(b["payouts_net"] - b["costs"], 2)
        tot = {k: round(sum(b[k] for b in firm.values()), 2) for k in ("trading_pnl", "payouts_gross", "payouts_net", "costs", "real_profit")}
        curve: dict[str, float] = {}
        for r in sorted(days, key=lambda x: x["session"]):
            curve[r["session"]] = curve.get(r["session"], 0.0) + r["pnl"]
        run, cum = 0.0, []
        for s, v in curve.items():
            run += v; cum.append({"session": s, "fleet_pnl": round(v, 2), "cumulative": round(run, 2)})
        return {"totals": tot, "by_account": acc, "by_firm": firm, "by_month": dict(sorted(month.items())), "fleet_curve": cum}
