"""High-level entry point: data + script + settings -> complete result payload for the UI."""

from __future__ import annotations

import math
import os
import time
import uuid
from typing import Callable

import numpy as np

from . import stats as st
from .adapters import build_adapter
from .contracts import apply_contract
from .core.bars import Bars
from .core.broker import Settings
from .core.engine import buy_and_hold, run_backtest
from .data import load_csv, resample
from .detect import detect
from .errors import TickbenchError


def load_data(spec: dict) -> Bars:
    """spec: {source: 'csv', path} | {source: 'yahoo', symbol, interval, start, end} (+ timeframe, start/end filter)."""
    src = spec.get("source", "csv")
    if src == "csv":
        bars = load_csv(spec["path"], spec.get("symbol"))
    elif src == "yahoo":
        from .data.yahoo import download
        bars = download(spec["symbol"], spec.get("interval", "1d"), spec.get("start"), spec.get("end"))
    else:
        raise TickbenchError(f"Unknown data source '{src}'.")
    if spec.get("timeframe") and spec["timeframe"] != bars.timeframe:
        bars = resample(bars, spec["timeframe"])
    lo, hi = spec.get("from"), spec.get("to")
    if lo or hi:
        import pandas as pd
        t = bars.time
        a = int(pd.Timestamp(lo, tz="UTC").as_unit("ms").value) if lo else t[0]
        b = int(pd.Timestamp(hi, tz="UTC").as_unit("ms").value) if hi else t[-1]
        idx = np.where((t >= a) & (t <= b))[0]
        if len(idx) < 2:
            raise TickbenchError("No bars inside the chosen date range.", hint="Widen the From/To dates.")
        bars = bars.slice(int(idx[0]), int(idx[-1]) + 1)
    return bars


def infer_tick(bars: Bars) -> float:
    """Smallest price increment implied by the data's decimals (e.g. 2 decimals -> 0.01)."""
    sample = np.concatenate([bars.open[:300], bars.close[:300]])
    decimals = 0
    for v in sample:
        s = f"{float(v):.8f}".rstrip("0")
        d = len(s.split(".")[1]) if "." in s else 0
        decimals = max(decimals, d)
        if decimals >= 5:
            break
    return 10 ** -min(decimals, 5) if decimals else 1.0


def read_script(path: str) -> tuple[str, dict[str, str]]:
    """Return (source, sibling files) — siblings let multi-file Tradovate strategies `require` each other."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        src = f.read()
    extra: dict[str, str] = {}
    root = os.path.dirname(os.path.abspath(path))
    if path.lower().endswith(".js"):
        for base, _dirs, files in os.walk(root):
            if base.count(os.sep) - root.count(os.sep) > 3 or "node_modules" in base:
                continue
            for fn in files:
                if fn.endswith(".js") and len(extra) < 300:
                    full = os.path.join(base, fn)
                    try:
                        with open(full, "r", encoding="utf-8", errors="replace") as f:
                            extra[os.path.relpath(full, root).replace(os.sep, "/")] = f.read()
                    except OSError:
                        pass
    return src, extra


def run(script: dict, data: dict, settings: dict | None = None, params: dict | None = None,
        progress: Callable[[float], None] | None = None, cancelled: Callable[[], bool] | None = None) -> dict:
    """script: {path} or {source, filename}; optional kind (auto-detected), options."""
    t0 = time.perf_counter()
    if "source" in script:
        source, extra = script["source"], script.get("files") or {}
        filename = script.get("filename", "strategy")
    else:
        source, extra = read_script(script["path"])
        filename = os.path.basename(script["path"])
    det = detect(source, filename)
    kind = script.get("kind") or det["type"]
    if kind == "unknown":
        raise TickbenchError("Couldn't tell what kind of script this is.",
                             hint="Choose the type manually in the script panel.", file=filename)
    bars = load_data(data)
    s = Settings.from_dict(settings)
    contract = apply_contract(s, (settings or {}).get("contract"), bars.symbol)
    if kind in ("mql4", "mql5"):
        from .adapters.mql.adapter import guess_contract_size
        s.hedging = (settings or {}).get("hedging", True)
        if "point_value" not in (settings or {}) and not contract:
            s.point_value = guess_contract_size(bars.symbol)
        if "default_qty" not in (settings or {}):
            s.default_qty = 0.1
    if "tick_size" not in (settings or {}) and not contract:
        s.tick_size = infer_tick(bars)
    params = dict(params or {})
    # "prefer_script": settings declared inside the script (Pine strategy(...)) override the run settings
    prefer_script = bool((settings or {}).get("prefer_script", False))
    params["_user_settings"] = [] if prefer_script else sorted((settings or {}).keys())
    if (settings or {}).get("contract"):
        params["_contract"] = settings["contract"]
    adapter = build_adapter(kind, source, filename, script.get("options"), extra)
    ctx = run_backtest(bars, adapter, s, params, progress, cancelled)
    equity = np.asarray(ctx.broker.equity_curve, dtype=float)
    bh = buy_and_hold(bars, s.initial_capital)
    stats = st.compute(bars, equity, ctx.broker.trades, s.initial_capital, bh)
    dd_abs, dd_pct = st.drawdown(equity)
    trades = [t.to_dict() for t in ctx.broker.trades]
    for d in trades:
        for k, v in list(d.items()):
            if isinstance(v, float) and not math.isfinite(v):
                d[k] = None
    return {
        "id": uuid.uuid4().hex[:12],
        "createdAt": int(time.time() * 1000),
        "script": {"filename": filename, "kind": kind, "detected": det,
                   "params": {k: v for k, v in (params or {}).items() if not k.startswith("_")}},
        "data": {"symbol": bars.symbol, "timeframe": bars.timeframe, "bars": len(bars),
                 "source": bars.meta.get("source", data.get("source")), "start": int(bars.time[0]),
                 "end": int(bars.time[-1])},
        "settings": s.to_dict(),
        "contract": contract,
        "bars": bars.to_payload(),
        "equity": [round(float(x), 4) for x in equity],
        "buyHold": [round(float(x), 4) for x in bh],
        "drawdownPct": [round(float(x), 4) for x in dd_pct],
        "trades": trades,
        "stats": stats,
        "monthly": st.monthly_returns(bars.time, equity),
        "events": ctx.events,
        "plots": [p.to_dict() for p in ctx.plots.values()],
        "elapsedMs": round((time.perf_counter() - t0) * 1000, 1),
    }
