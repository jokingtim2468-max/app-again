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
