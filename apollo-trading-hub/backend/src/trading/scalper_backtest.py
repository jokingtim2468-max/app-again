"""Backtest + grid optimizer for the cockpit's gold scalper (same rules as live, see confluence.py).

Conservative fills on purpose:
  - signals are evaluated on a closed M5 bar, entry fills at the NEXT M1 open plus half the spread
  - inside one M1 bar the stop is checked before the target (worst case)
  - breakeven arms on a bar's favourable extreme and only protects from the following bar
  - commission per contract round turn, spread from the data when it has one
Optional evaluation tracking: start balance, profit target, EOD trailing drawdown, best-day consistency %.
"""
from __future__ import annotations

import itertools
from collections import defaultdict
from datetime import datetime

import pandas as pd

from . import confluence as C

MAX_GRID = 60


def _bars(df: pd.DataFrame) -> list[dict]:
    out = []
    for ts, r in df.iterrows():
        out.append({"time": int(ts.timestamp()), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                    "close": float(r["close"]), "volume": float(r.get("volume", 0) or 0),
                    "spread": float(r["spread"]) if "spread" in r and pd.notna(r["spread"]) else None})
    return out


def run(df: pd.DataFrame, params: dict | None = None, evaluation: dict | None = None, keep_trades: bool = True) -> dict:
    p = {**C.DEFAULT_PARAMS, **(params or {})}
    ev = {"start": 50000.0, "target": 3000.0, "trailing_dd": 2000.0, "consistency": 0.40, **(evaluation or {})}
    m1 = _bars(df)
    pv, qty, comm = p["point_value"], int(p["contracts"]), p["commission_rt"] * int(p["contracts"])
    m5: list[dict] = []
    m15: list[dict] = []
    trades: list[dict] = []
    pos = None
    pending = None  # signal waiting for the next bar's open
    cooldown_until = 0.0
    loss_cool: dict[str, float] = {}
    day_count: dict[str, int] = defaultdict(int)
    day_pnl: dict[str, float] = defaultdict(float)
    balance = ev["start"]
    peak_eod = balance
    floor = balance - ev["trailing_dd"]
    blown = passed = None
    equity = []

    def close(b, px, reason):
        nonlocal pos, balance, cooldown_until
        d = 1 if pos["side"] == "long" else -1
        gross = (px - pos["entry"]) * d * pv * qty
        net = gross - comm
        balance += net
        day = datetime.fromtimestamp(b["time"], C.ET).date().isoformat()
        day_pnl[day] += net
        t = {**pos, "exit": round(px, 2), "exit_time": b["time"], "reason": reason, "gross": round(gross, 2),
             "commission": round(comm, 2), "net": round(net, 2), "hold_s": b["time"] - pos["entry_time"],
             "mfe": round(pos["mfe"] * pv * qty, 2), "mae": round(pos["mae"] * pv * qty, 2), "day": day}
        trades.append(t)
        cooldown_until = b["time"] + p["cooldown_after_trade_s"]
        if net < 0:
            loss_cool[pos["side"]] = b["time"] + p["cooldown_after_loss_s"]
        pos = None

    prev_day = None
    for i, b in enumerate(m1):
        day = datetime.fromtimestamp(b["time"], C.ET).date().isoformat()
        if prev_day and day != prev_day:  # EOD: trailing floor follows the closing balance up
            peak_eod = max(peak_eod, balance)
            floor = max(floor, min(peak_eod - ev["trailing_dd"], ev["start"]))  # Lucid-style: locks at start balance
            equity.append({"time": prev_day, "balance": round(balance, 2), "floor": round(floor, 2)})
        prev_day = day
        half_spread = (b["spread"] if b.get("spread") else 0.10) / 2

        if pending and pos is None:  # fill at this bar's open
            d = 1 if pending["side"] == "long" else -1
            entry = b["open"] + d * half_spread
            pos = {"side": pending["side"], "entry": round(entry, 2), "entry_time": b["time"], "sl": entry - d * pending["sl"],
                   "tp": entry + d * pending["tp"], "risk": pending["sl"], "be_r": pending["be_r"], "be_armed": False,
                   "be_next": False, "mfe": 0.0, "mae": 0.0, "score": pending["score"], "regime": pending["regime"]}
            day_count[day] += 1
        pending = None

        if pos:
            d = 1 if pos["side"] == "long" else -1
            if pos["be_next"]:
                pos["sl"] = pos["entry"] + d * p["be_lock"]; pos["be_armed"] = True; pos["be_next"] = False
            fav = (b["high"] - pos["entry"]) if d > 0 else (pos["entry"] - b["low"])
            adv = (pos["entry"] - b["low"]) if d > 0 else (b["high"] - pos["entry"])
            pos["mfe"] = max(pos["mfe"], fav); pos["mae"] = max(pos["mae"], adv)
            hit_sl = b["low"] <= pos["sl"] if d > 0 else b["high"] >= pos["sl"]
            hit_tp = b["high"] >= pos["tp"] if d > 0 else b["low"] <= pos["tp"]
            if hit_sl:
                close(b, pos["sl"] - d * half_spread, "breakeven" if pos["be_armed"] else "stop_loss")
            elif hit_tp:
                close(b, pos["tp"], "take_profit")
            elif not pos["be_armed"] and fav >= pos["be_r"] * pos["risk"]:
                pos["be_next"] = True
            if (balance + (((b["close"] - pos["entry"]) * d * pv * qty) if pos else 0)) <= floor and blown is None:
                blown = day
        if pos is None and passed is None and balance - ev["start"] >= ev["target"]:
            if (max(day_pnl.values()) if day_pnl else 0) <= ev["consistency"] * (balance - ev["start"]):
                passed = day

        # M5/M15 roll-up; evaluate on each M5 close
        for agg, n in ((m5, 5), (m15, 15)):
            t = b["time"] - b["time"] % (n * 60)
            if agg and agg[-1]["time"] == t:
                o = agg[-1]; o["high"] = max(o["high"], b["high"]); o["low"] = min(o["low"], b["low"])
                o["close"] = b["close"]; o["volume"] += b["volume"]
            else:
                agg.append({"time": t, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "volume": b["volume"]})
        if len(m5) > 400:
            del m5[:100]
        if len(m15) > 200:
            del m15[:50]
        nxt = m1[i + 1]["time"] if i + 1 < len(m1) else None
        m5_closed = nxt is None or (nxt - nxt % 300) != (b["time"] - b["time"] % 300)
        if not m5_closed or pos or blown or passed or b["time"] < cooldown_until or len(m5) < 25:
            continue
        if b.get("spread") and b["spread"] > p["max_spread"]:
            continue
        if not C.in_session(b["time"], p):
            continue
        reg = C.regime(m15)
        ad = C.adaptive(p, reg["regime"], reg["atr"])
        if day_count[day] >= ad["quota"]:
            continue
        window = m1[max(0, i - 1500):i + 1]
        sig = C.confluence(m5, b["close"], C.session_vwap(window, b["time"]), C.asian_range(window, p, b["time"]), p)
        if sig["score"] < p["confluence_min"] or loss_cool.get(sig["side"], 0) > b["time"]:
            continue
        if not p["allow_counter_trend"] and reg["regime"] == "TREND_EXPANSION_REGIME" and \
                (sig["side"] == "long") != (reg.get("trend") == "up"):
            continue
        pending = {"side": sig["side"], "tp": ad["tp"], "sl": ad["sl"], "be_r": ad["be_trigger_r"],
                   "score": sig["score"], "regime": reg["regime"]}

    if prev_day:
        equity.append({"time": prev_day, "balance": round(balance, 2), "floor": round(floor, 2)})
    return summarize(trades, equity, ev, day_pnl, blown, passed, p, keep_trades)


def summarize(trades, equity, ev, day_pnl, blown, passed, p, keep_trades=True) -> dict:
    nets = [t["net"] for t in trades]
    wins = [x for x in nets if x > 0]; losses = [x for x in nets if x < 0]
    peak, dd, under = ev["start"], 0.0, []
    for e in equity:
        peak = max(peak, e["balance"])
        dd = max(dd, peak - e["balance"])
        under.append({"time": e["time"], "drawdown": round(e["balance"] - peak, 2)})
    months: dict[str, dict] = {}
    for t in trades:
        m = months.setdefault(t["day"][:7], {"month": t["day"][:7], "net": 0.0, "trades": 0, "wins": 0, "commission": 0.0,
                                                "_eq": 0.0, "_peak": 0.0, "max_dd": 0.0})
        m["net"] += t["net"]; m["trades"] += 1; m["wins"] += t["net"] > 0; m["commission"] += t["commission"]
        m["_eq"] += t["net"]; m["_peak"] = max(m["_peak"], m["_eq"]); m["max_dd"] = max(m["max_dd"], m["_peak"] - m["_eq"])
    monthly = [{"month": m["month"], "net": round(m["net"], 2), "trades": m["trades"],
                "win_rate": round(m["wins"] / m["trades"], 4) if m["trades"] else 0, "max_dd": round(m["max_dd"], 2),
                "commission": round(m["commission"], 2)} for m in sorted(months.values(), key=lambda x: x["month"])]
    total = sum(nets)
    best_day = max(day_pnl.values()) if day_pnl else 0.0
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["reason"]] += 1
    return {
        "trades": len(trades), "net": round(total, 2), "win_rate": round(len(wins) / len(nets), 4) if nets else 0.0,
        "profit_factor": round(sum(wins) / -sum(losses), 3) if losses else None,
        "expectancy": round(total / len(nets), 2) if nets else 0.0, "max_drawdown": round(dd, 2),
        "commission": round(sum(t["commission"] for t in trades), 2), "exits": dict(reasons),
        "days": len(day_pnl), "avg_day": round(total / len(day_pnl), 2) if day_pnl else 0.0, "best_day": round(best_day, 2),
        "consistency_ok": total > 0 and best_day <= ev["consistency"] * total,
        "evaluation": {"passed_on": passed, "blown_on": blown, **ev},
        "monthly": monthly, "equity": equity, "underwater": under,
        "trade_log": trades[-500:] if keep_trades else [], "params": p,
    }


def grid(df: pd.DataFrame, base: dict, axes: dict[str, list], evaluation: dict | None = None, max_dd: float | None = None) -> dict:
    keys = [k for k, v in axes.items() if v]
    combos = list(itertools.product(*[axes[k] for k in keys]))
    if len(combos) > MAX_GRID:
        raise ValueError(f"{len(combos)} combinations; keep it at {MAX_GRID} or fewer")
    rows = []
    for c in combos:
        prm = {**base, **dict(zip(keys, c))}
        r = run(df, prm, evaluation, keep_trades=False)
        rows.append({**dict(zip(keys, c)), "net": r["net"], "trades": r["trades"], "win_rate": r["win_rate"],
                     "profit_factor": r["profit_factor"], "max_drawdown": r["max_drawdown"], "expectancy": r["expectancy"],
                     "passed_on": r["evaluation"]["passed_on"], "blown_on": r["evaluation"]["blown_on"]})
    ok = [r for r in rows if max_dd is None or r["max_drawdown"] <= max_dd]
    ok.sort(key=lambda r: r["net"], reverse=True)
    return {"axes": keys, "rows": sorted(rows, key=lambda r: r["net"], reverse=True), "best": ok[0] if ok else None,
            "note": "Best by net PnL within the drawdown limit. Check it on a second, unseen date range before trusting it."}
