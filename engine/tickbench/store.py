"""Run history in SQLite (``%APPDATA%/Tickbench/runs.db``)."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import zlib

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  created INTEGER NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  net REAL,
  net_pct REAL,
  trades INTEGER,
  max_dd REAL,
  sharpe REAL,
  summary TEXT NOT NULL,
  blob BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_created ON runs(created DESC);
"""


def data_dir() -> str:
    base = os.environ.get("TICKBENCH_DATA") or os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~/.local/share"), "Tickbench")
    os.makedirs(base, exist_ok=True)
    return base


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(data_dir(), "runs.db")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    def save(self, result: dict, payload_json: str) -> None:
        s = result["stats"]
        summary = {
            "id": result["id"], "createdAt": result["createdAt"], "script": result["script"]["filename"],
            "kind": result["script"]["kind"], "symbol": result["data"]["symbol"],
            "timeframe": result["data"]["timeframe"], "netProfit": s.get("netProfit"),
            "netProfitPct": s.get("netProfitPct"), "trades": s.get("trades"), "maxDrawdownPct": s.get("maxDrawdownPct"),
            "sharpe": s.get("sharpe"), "winRate": s.get("winRate"), "profitFactor": s.get("profitFactor"),
            "params": result["script"].get("params", {}),
            "spark": _spark(result.get("equity", [])),
        }
        self.db.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (result["id"], result["createdAt"], result["script"]["filename"], result["script"]["kind"],
             result["data"]["symbol"], result["data"]["timeframe"], s.get("netProfit"), s.get("netProfitPct"),
             s.get("trades"), s.get("maxDrawdownPct"), s.get("sharpe"), json.dumps(summary),
             zlib.compress(payload_json.encode("utf-8"), 6)))
        self.db.commit()

    def list(self, limit: int = 200) -> list[dict]:
        rows = self.db.execute("SELECT summary FROM runs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get(self, run_id: str) -> str | None:
        row = self.db.execute("SELECT blob FROM runs WHERE id = ?", (run_id,)).fetchone()
        return zlib.decompress(row[0]).decode("utf-8") if row else None

    def delete(self, run_id: str) -> bool:
        cur = self.db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        self.db.commit()
        return cur.rowcount > 0


def _spark(equity: list, n: int = 48) -> list:
    if not equity:
        return []
    step = max(1, len(equity) // n)
    pts = equity[::step]
    if pts[-1] != equity[-1]:
        pts.append(equity[-1])
    return [round(float(x), 2) for x in pts]
