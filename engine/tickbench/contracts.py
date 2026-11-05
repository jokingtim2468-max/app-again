"""Futures contract specifications (CME Group product specs).

Tick value = tick size x point value. Commission is an approximate all-in per-side cost
(broker + exchange fees). Check your own plan's rates and change it in the run settings.
"""

from __future__ import annotations

import re

from .core.broker import Settings

CONTRACTS: dict[str, dict] = {
    "ES": {"name": "E-mini S&P 500", "tick": 0.25, "point_value": 50.0, "commission": 1.99},
    "MES": {"name": "Micro E-mini S&P 500", "tick": 0.25, "point_value": 5.0, "commission": 0.79},
    "NQ": {"name": "E-mini Nasdaq-100", "tick": 0.25, "point_value": 20.0, "commission": 1.99},
    "MNQ": {"name": "Micro E-mini Nasdaq-100", "tick": 0.25, "point_value": 2.0, "commission": 0.79},
    "YM": {"name": "E-mini Dow", "tick": 1.0, "point_value": 5.0, "commission": 1.99},
    "MYM": {"name": "Micro E-mini Dow", "tick": 1.0, "point_value": 0.5, "commission": 0.79},
    "RTY": {"name": "E-mini Russell 2000", "tick": 0.1, "point_value": 50.0, "commission": 1.99},
    "M2K": {"name": "Micro E-mini Russell 2000", "tick": 0.1, "point_value": 5.0, "commission": 0.79},
    "CL": {"name": "Crude Oil", "tick": 0.01, "point_value": 1000.0, "commission": 2.09},
    "MCL": {"name": "Micro Crude Oil", "tick": 0.01, "point_value": 100.0, "commission": 0.89},
    "GC": {"name": "Gold", "tick": 0.1, "point_value": 100.0, "commission": 2.09},
    "MGC": {"name": "Micro Gold", "tick": 0.1, "point_value": 10.0, "commission": 0.89},
    "SI": {"name": "Silver", "tick": 0.005, "point_value": 5000.0, "commission": 2.09},
    "HG": {"name": "Copper", "tick": 0.0005, "point_value": 25000.0, "commission": 2.09},
    "NG": {"name": "Natural Gas", "tick": 0.001, "point_value": 10000.0, "commission": 2.09},
    "ZB": {"name": "30-Year T-Bond", "tick": 0.03125, "point_value": 1000.0, "commission": 1.79},
    "ZN": {"name": "10-Year T-Note", "tick": 0.015625, "point_value": 1000.0, "commission": 1.79},
    "6E": {"name": "Euro FX", "tick": 0.00005, "point_value": 125000.0, "commission": 2.09},
    "6J": {"name": "Japanese Yen", "tick": 0.0000005, "point_value": 12500000.0, "commission": 2.09},
    "6B": {"name": "British Pound", "tick": 0.0001, "point_value": 62500.0, "commission": 2.09},
    "MBT": {"name": "Micro Bitcoin", "tick": 5.0, "point_value": 0.1, "commission": 2.25},
}

MONTH_CODES = "FGHJKMNQUVXZ"


def root_of(symbol: str) -> str | None:
    """'ESZ6', 'ES=F', 'MNQ', 'GCZ2026' -> contract root, or None."""
    if not symbol:
        return None
    s = symbol.upper().replace("=F", "").split(".")[0]
    if s in CONTRACTS:
        return s
    m = re.fullmatch(r"([A-Z0-9]{1,3}?)([" + MONTH_CODES + r"])(\d{1,4})", s)
    if m and m.group(1) in CONTRACTS:
        return m.group(1)
    return None


def spec(symbol: str) -> dict | None:
    r = root_of(symbol)
    return {"root": r, **CONTRACTS[r]} if r else None


def apply_contract(settings: Settings, contract: str | None, symbol: str) -> dict | None:
    """Fill tick size / point value / commission from a contract when the user picked one
    (or the data symbol is a futures contract and contract == 'auto')."""
    choice = contract if contract not in (None, "", "auto") else (symbol if contract == "auto" else None)
    if not choice:
        return None
    c = spec(choice)
    if not c:
        return None
    settings.tick_size = c["tick"]
    settings.point_value = c["point_value"]
    if settings.commission_per_unit == 0:
        settings.commission_per_unit = c["commission"]
    settings.integer_qty = True
    if settings.qty_mode == "fixed":
        settings.default_qty = max(1.0, round(settings.default_qty))
    else:
        # futures are sized in whole contracts; % of equity would usually round to zero
        settings.qty_mode = "fixed"
        settings.default_qty = 1.0
    return c
