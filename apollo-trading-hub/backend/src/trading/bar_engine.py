"""Bar-driven backtest engine for adapted scripts.

Fills: a target change decided on bar i's close is filled at bar i+1's open (no look-ahead),
plus half the spread and `extra_slippage_ticks`. Intrabar adverse excursion (bar low/high) is checked
against the MLL so liquidations aren't hidden by closes. LucidFlex rules come from RiskSentinel:
EOD MLL roll at the 17:00 ET session boundary, funded scaling clamp, payouts, graduation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .risk_sentinel import ET, RiskSentinel, resolve_rules

CONTRACTS = {  # price-unit economics per contract
    "MGC": {"tick_size": 0.10, "point_value": 10.0, "commission_rt": 1.24},
    "GC": {"tick_size": 0.10, "point_value": 100.0, "commission_rt": 4.50},
}


@dataclass
class BarConfig:
    initial_balance: float = 150000.0
    lot_size_micros: int = 20
    stage: str = "EVALUATION"
    contract: str = "MGC"
    spread_multiplier: float = 1.0
    extra_slippage_ticks: float = 1.0
    default_spread_ticks: float = 1.0
    restart_after_liquidation: bool = True
    label: str = ""
    firm: str | None = None   # e.g. "topstep"; None = fleet master's profile
    plan: str | None = None
    size: str | None = None
    extra: dict = field(default_factory=dict)


def session_dates(index: pd.DatetimeIndex) -> np.ndarray:
    """CME session date: 18:00 ET prev day .. 17:00 ET. Shift +7h so the 17:00 close lands on midnight."""
    return (index.tz_convert(ET) + pd.Timedelta(hours=7)).date


def run_bars(bars: pd.DataFrame, target: np.ndarray, cfg: BarConfig) -> dict:
    if len(bars) < 2:
        raise ValueError("need at least 2 bars")
    spec = CONTRACTS[cfg.contract]
    tick, pv, comm = spec["tick_size"], spec["point_value"], spec["commission_rt"]
    sentinel = RiskSentinel()
    rules = resolve_rules(cfg.firm, cfg.plan, cfg.size) if cfg.firm else sentinel.rules
    aid = "BACKTEST"

    def fresh():
        a = sentinel.new_account(aid, stage=cfg.stage, rules=rules)  # type: ignore[arg-type]
        if not cfg.firm:  # legacy: caller-chosen balance
            a.starting_balance = a.closed_balance = a.day_start_balance = a.peak_equity = cfg.initial_balance
            a.mll = cfg.initial_balance - rules["starting_drawdown"]
        sentinel.accounts[aid] = a
        return a

    acct = fresh()
    o, h, l = bars["open"].to_numpy(), bars["high"].to_numpy(), bars["low"].to_numpy()
    c = bars["close"].to_numpy()
    spread = bars["spread"].to_numpy(dtype=float)
    spread = np.where(np.isnan(spread), cfg.default_spread_ticks * tick, spread) * cfg.spread_multiplier
    sess = session_dates(bars.index)
    tgt = np.nan_to_num(np.asarray(target, dtype=float))

    pos, entry = 0, 0.0
    trades, curve, slips = [], [], []
    liquidations = payouts = clamped = 0
    eod_peak = acct.starting_balance
    max_dd = 0.0

    def contracts_for(v: float) -> int:
        q = int(round(abs(v) * cfg.lot_size_micros)) if abs(v) <= 1 else int(round(abs(v)))
        return int(np.sign(v)) * q

    def fill(new_pos: int, px_mid: float, sp: float, ts) -> None:
        nonlocal pos, entry
        delta = new_pos - pos
        if delta == 0:
            return
        side = 1 if delta > 0 else -1
        px = px_mid + side * (sp / 2 + cfg.extra_slippage_ticks * tick)
        slips.append(round(abs(px - px_mid) * pv * abs(delta), 2))
        # realize closed part
        if pos != 0 and np.sign(delta) != np.sign(pos):
            closing = min(abs(delta), abs(pos))
            pnl = (px - entry) * np.sign(pos) * closing * pv - comm * closing
            sentinel.realize(aid, pnl)
            trades.append({"exit_time": str(ts), "side": "long" if pos > 0 else "short", "qty": closing,
                           "entry": round(entry, 2), "exit": round(px, 2), "pnl": round(pnl, 2)})
        remaining = pos + delta
        if remaining != 0 and (pos == 0 or np.sign(remaining) != np.sign(pos)):
            entry = px  # new or flipped position
        elif remaining != 0 and abs(remaining) > abs(pos):
            entry = (entry * abs(pos) + px * (abs(remaining) - abs(pos))) / abs(remaining)
        pos = remaining
        acct.position_qty = pos

    for i in range(len(bars)):
        # 1) execute the decision from the previous bar at this bar's open
        if i > 0 and not acct.liquidated and not acct.halted:
            want = contracts_for(tgt[i - 1])
            cap = sentinel.validate_order(aid, acct.stage, max(1, abs(want)), "MGC")["max_allowed"]
            if abs(want) > cap:
                want, clamped = int(np.sign(want)) * cap, clamped + 1
            fill(want, o[i], spread[i], bars.index[i])
        # 2) intrabar worst case vs MLL
        if pos:
            worst = (l[i] - entry) if pos > 0 else (entry - h[i])
            sentinel.mark(aid, worst * pv * abs(pos))
            if acct.liquidated:
                liq_px = entry + np.sign(pos) * (acct.mll - acct.closed_balance) / (pv * abs(pos))
                liquidations += 1
                fill(0, liq_px, spread[i], bars.index[i])
                trades[-1]["liquidation"] = True
            else:
                sentinel.mark(aid, (c[i] - entry) * np.sign(pos) * pv * abs(pos))
        # 3) session close at 17:00 ET: roll MLL, qualify days, payouts
        last_of_session = i == len(bars) - 1 or sess[i + 1] != sess[i]
        if last_of_session:
            d = str(sess[i])
            sentinel.end_of_day(aid, d)
            if acct.stage == "EVALUATION" and sentinel.eval_passed(aid):
                acct.stage, acct.qualifying_days = "FUNDED", 0
                trades.append({"exit_time": str(bars.index[i]), "event": "EVAL_PASSED"})
            elif acct.stage == "FUNDED":
                el = sentinel.payout_eligibility(aid)
                if el["eligible"] and el["max_request"] > 0:
                    sentinel.approve_payout(aid, el["max_request"])
                    payouts += 1
            eod_peak = max(eod_peak, acct.closed_balance)
            max_dd = max(max_dd, eod_peak - acct.closed_balance)
            curve.append({"date": d, "balance": round(acct.closed_balance, 2), "mll": acct.mll,
                          "drawdown": round(acct.closed_balance - eod_peak, 2)})
            if acct.liquidated and cfg.restart_after_liquidation and i < len(bars) - 1:
                pos, entry = 0, 0.0
                acct = fresh()
                eod_peak = acct.starting_balance

    pnl = np.array([t["pnl"] for t in trades if "pnl" in t]) if trades else np.zeros(0)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    bal = np.array([acct.starting_balance] + [p["balance"] for p in curve])
    daily = np.diff(bal)
    return {
        "strategy": cfg.label, "engine": "bar", "bars": len(bars), "trades": int(pnl.size),
        "win_rate": round(float(wins.size / pnl.size), 4) if pnl.size else 0.0,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if losses.size else None,
        "max_drawdown_eod": round(float(max_dd), 2), "total_net_pnl": round(float(pnl.sum()), 2),
        "sharpe": round(float(daily.mean() / daily.std() * np.sqrt(252)), 3) if daily.size > 1 and daily.std() > 0 else 0.0,
        "qualified_payouts": payouts, "liquidated_accounts_count": liquidations, "size_clamps": clamped,
        "slippage_cost_usd": round(float(sum(slips)), 2), "equity_curve": curve, "trade_log": trades[-200:],
        "news_slippage": [], "rules": {k: rules.get(k) for k in ("firm_name", "plan", "size", "drawdown_type", "starting_drawdown",
                                                                     "daily_loss_limit", "eval_target", "verified")},
    }
