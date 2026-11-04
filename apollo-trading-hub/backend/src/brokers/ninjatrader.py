"""NinjaTrader 8 Automated Trading Interface (ATI) via Order Instruction Files.

NinjaTrader connects to Rithmic, CQG, Tradovate, Kinetick, IB... so this one connector reaches every account NT can
log into (Apex/Bulenox/TPT on Rithmic, etc.). Enable in NT8: Tools > Options > Automated trading interface > AT
Interface checked. Apollo writes OIF files to <Documents>/NinjaTrader 8/incoming and reads fills from .../outgoing.
Env: NT8_DIR (default ~/Documents/NinjaTrader 8). From WSL point it at /mnt/c/Users/<you>/Documents/NinjaTrader 8.
Instrument names use NT format, e.g. "MGC 12-26". Set per-account `instrument` in fleet.json or NT8_INSTRUMENT."""
from __future__ import annotations

import asyncio
import itertools
import os
import time
from pathlib import Path

from .base import BrokerError, Connector

_seq = itertools.count()


class NinjaTraderConnector(Connector):
    name = "ninjatrader"

    def __init__(self, live: bool, suffix: str = ""):
        super().__init__(live)
        self.dir = Path(os.getenv("NT8_DIR", Path.home() / "Documents" / "NinjaTrader 8")).expanduser()
        self.instrument = os.getenv("NT8_INSTRUMENT", "")

    async def connect(self):
        inc = self.dir / "incoming"
        if not inc.is_dir():
            raise BrokerError(f"NinjaTrader 8 folder not found at {self.dir} (set NT8_DIR; enable ATI in NT8 options)")
        self.connected = True

    def _nt_symbol(self, symbol: str) -> str:
        if self.instrument:
            return self.instrument
        if " " in symbol:
            return symbol  # already NT format
        # MGCZ6 -> "MGC 12-26"
        months = "FGHJKMNQUVXZ"
        root, m, y = symbol[:-2], symbol[-2], symbol[-1]
        if m not in months:
            raise BrokerError(f"can't convert {symbol} to NinjaTrader instrument; set NT8_INSTRUMENT like 'MGC 12-26'")
        return f"{root} {months.index(m) + 1:02d}-2{y}"

    def _write(self, line: str) -> Path:
        f = self.dir / "incoming" / f"oif{int(time.time() * 1000)}_{next(_seq)}.txt"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(line + "\n")
        tmp.replace(f)  # NT picks up files atomically
        return f

    async def place_market(self, account, action, symbol, qty):
        # PLACE;<ACCOUNT>;<INSTRUMENT>;<ACTION>;<QTY>;<ORDER TYPE>;[LIMIT];[STOP];<TIF>;[OCO];[ORDER ID];[STRATEGY];[STRATEGY ID]
        oid = f"apollo{int(time.time() * 1000)}{next(_seq)}"
        f = self._write(f"PLACE;{account};{self._nt_symbol(symbol)};{action.upper()};{int(qty)};MARKET;;;DAY;;{oid};;")
        return {"mode": self.mode, "orderId": oid, "file": f.name, "account": account}

    async def flatten(self, account, symbol):
        self._write(f"CLOSEPOSITION;{account};{self._nt_symbol(symbol)};DAY")

    async def positions(self, account):
        # NT writes <Instrument> <Account>_position.txt = "LONG;3;2900.1" / "FLAT;0;0"
        out = {}
        for p in (self.dir / "outgoing").glob(f"*{account}_position.txt"):
            try:
                side, qty, _ = p.read_text().strip().split(";")[:3]
            except ValueError:
                continue
            q = float(qty) * (1 if side == "LONG" else -1 if side == "SHORT" else 0)
            out[p.name.split(f" {account}_")[0]] = q
        await asyncio.sleep(0)
        return out
