"""Vectorized MGC tick backtester with scheduled-event spread-expansion simulation and LucidFlex 150K EOD rules.

Uses a seeded synthetic tick stream (regular-hours random walk + scheduled CPI/Core PCE/
NFP/FOMC momentum bursts). Synthetic results validate rule logic only -- they are NOT
evidence of real-market edge. Pass tick_csv for real data; drop strategies in apollo-trading/strategies/.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from .risk_sentinel import RiskSentinel, funded_max_contracts, load_fleet_config

TICK = 0.10            # MGC tick size
TICK_VALUE = 1.00      # $ per tick per micro
POINT_VALUE = 10.0     # $ per point per micro
COMMISSION_RT = 1.24   # $ round trip per micro (approx)

NEWS_CALENDAR = {
    # event -> (day-of-month rule, hour, minute, typical burst points, spread ticks during print)
    "NFP": ("first_friday", 8, 30, 14.0, 6),
    "CPI": ("day_12", 8, 30, 12.0, 5),
    "CORE_PCE": ("last_friday", 8, 30, 8.0, 4),
    "FOMC": ("third_wednesday", 14, 0, 16.0, 8),
}

STRATEGIES = ("news_momentum", "news_fade", "breakout")


@dataclass
class BacktestConfig:
    strategy_name: str = "news_momentum"
    start_date: str = "2025-01-01"
    end_date: str = "2025-06-30"
    initial_balance: float = 150000.0
    lot_size_micros: int = 20
    event_filter: list[str] | None = None
    seed: int = 7
    spread_multiplier: float = 1.0  # stress test: scale all spreads/slippage
    tick_csv: str | None = None  # CSV with timestamp,price (ET). Overrides synthetic data.
    stage: str = "EVALUATION"


def _event_dates(start: date, end: date, rule: str) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        month_days = [d + timedelta(days=i) for i in range(31) if (d + timedelta(days=i)).month == d.month]
        fridays = [x for x in month_days if x.weekday() == 4]
        weds = [x for x in month_days if x.weekday() == 2]
        pick = {"first_friday": fridays[0], "last_friday": fridays[-1],
                "third_wednesday": weds[2], "day_12": month_days[11]}[rule]
        while pick.weekday() >= 5:
            pick += timedelta(days=1)
        if start <= pick <= end:
            out.append(pick)
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def build_news_schedule(start: date, end: date, event_filter: list[str] | None) -> list[dict]:
    wanted = {e.upper().replace(" ", "_") for e in event_filter} if event_filter else set(NEWS_CALENDAR)
    sched = []
    for name, (rule, hh, mm, pts, spread) in NEWS_CALENDAR.items():
        if name not in wanted:
            continue
        for d in _event_dates(start, end, rule):
            sched.append({"event": name, "date": d, "ts": datetime(d.year, d.month, d.day, hh, mm),
                          "burst_points": pts, "spread_ticks": spread})
    return sorted(sched, key=lambda x: x["ts"])


def synthetic_day_ticks(rng: np.random.Generator, day: date, open_px: float, events: list[dict]):
    """1-second ticks 08:00-16:59 ET. Returns (timestamps[sec of day], price, spread_ticks)."""
    secs = np.arange(8 * 3600, 17 * 3600)
    vol = np.full(secs.size, 0.012)
    spread = np.ones(secs.size)
    drift = np.zeros(secs.size)
    for ev in events:
        i0 = ev["ts"].hour * 3600 + ev["ts"].minute * 60 - secs[0]
        if not 0 <= i0 < secs.size:
            continue
        direction = rng.choice([-1, 1])
        size = ev["burst_points"] * rng.uniform(0.5, 1.4)
        # initial impulse (~20s) then a coin-flip continuation/reversal, so the post-entry
        # path is NOT known from the first move (no look-ahead edge baked into the data)
        n1 = 20
        drift[i0:i0 + n1] += direction * size * 0.4 / n1
        follow = direction * rng.choice([1, -1]) * size * rng.uniform(0.2, 0.9)
        drift[i0 + n1:i0 + n1 + 280] += follow / 280
        vol[i0:i0 + 300] *= 6
        spread[i0:i0 + 30] = ev["spread_ticks"]
        spread[i0 + 30:i0 + 120] = max(2, ev["spread_ticks"] // 2)
    steps = drift + rng.standard_normal(secs.size) * vol
    px = open_px + np.cumsum(steps)
    px = np.round(px / TICK) * TICK
    return secs, px, spread


def load_tick_csv(path: str) -> dict[date, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """CSV columns: timestamp (ISO, ET), price, optional spread_ticks. Resampled to 1s grid
    08:00-16:59 per day (forward-filled) so strategies see the same shape as synthetic data."""
    import csv
    by_day: dict[date, list[tuple[int, float, float]]] = {}
    with Path(path).open() as f:
        for r in csv.DictReader(f):
            ts = datetime.fromisoformat(r["timestamp"])
            sec = ts.hour * 3600 + ts.minute * 60 + ts.second
            if 8 * 3600 <= sec < 17 * 3600:
                by_day.setdefault(ts.date(), []).append((sec, float(r["price"]), float(r.get("spread_ticks") or 1)))
    out = {}
    secs = np.arange(8 * 3600, 17 * 3600)
    for d, rows in by_day.items():
        rows.sort()
        s_arr = np.array([r[0] for r in rows]); p_arr = np.array([r[1] for r in rows]); sp = np.array([r[2] for r in rows])
        idx = np.clip(np.searchsorted(s_arr, secs, side="right") - 1, 0, len(rows) - 1)
        out[d] = (secs, p_arr[idx], sp[idx])
    return out


STRATEGY_DIR = Path(__file__).resolve().parents[3] / "strategies"


def list_strategies() -> list[str]:
    plugins = [p.stem for p in STRATEGY_DIR.glob("*.py") if not p.name.startswith("_")]
    return sorted(set(STRATEGIES) | set(plugins))


def _plugin(name: str):
    import importlib.util
    path = STRATEGY_DIR / f"{name}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"apollo_strategy_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    if not hasattr(mod, "generate_signals"):
        raise ValueError(f"{path} must define generate_signals(secs, px, spread, events)")
    return mod.generate_signals


def _signals(strategy: str, secs: np.ndarray, px: np.ndarray, events: list[dict], spread=None):
    """Return list of (entry_idx, side, exit_idx)."""
    plugin = _plugin(strategy) if strategy not in STRATEGIES else None
    if plugin:
        raw = plugin(secs, px, spread if spread is not None else np.ones(px.size), events)
        return [(int(e), int(np.sign(sd)), int(min(x, px.size - 1))) for e, sd, x in raw
                if 0 <= int(e) < px.size and sd != 0 and int(x) > int(e)]
    trades = []
    if strategy in ("news_momentum", "news_fade"):
        for ev in events:
            i0 = ev["ts"].hour * 3600 + ev["ts"].minute * 60 - secs[0]
            e = i0 + 20  # enter 20s after print once direction is shown
            if e + 300 >= px.size or i0 < 0:
                continue
            move = px[e] - px[i0]
            if abs(move) < 1.0:
                continue
            side = int(np.sign(move)) * (1 if strategy == "news_momentum" else -1)
            trades.append((e, side, e + 300))  # 5-min hold
    elif strategy == "breakout":
        orb_start = 5400  # 09:30 ET (index 0 == 08:00)
        orb_end = 7200    # 10:00 ET
        if orb_end < px.size:
            hi, lo = px[orb_start:orb_end].max(), px[orb_start:orb_end].min()
            post = px[orb_end:]
            up = np.argmax(post > hi) if (post > hi).any() else None
            dn = np.argmax(post < lo) if (post < lo).any() else None
            cand = [(i, 1) for i in [up] if i is not None] + [(i, -1) for i in [dn] if i is not None]
            if cand:
                i, side = min(cand)
                trades.append((orb_end + i, side, min(px.size - 1, orb_end + i + 1800)))
    else:
        raise ValueError(f"unknown strategy {strategy}; choose from {list_strategies()}")
    return trades


def run_backtest(cfg: BacktestConfig) -> dict:
    rules = load_fleet_config()["rules"]
    sentinel = RiskSentinel()
    acct = sentinel.new_account("BACKTEST", stage=cfg.stage)  # type: ignore[arg-type]
    acct.closed_balance = acct.day_start_balance = cfg.initial_balance
    acct.mll = cfg.initial_balance - rules["starting_drawdown"]
    sentinel.accounts["BACKTEST"] = acct

    start, end = date.fromisoformat(cfg.start_date), date.fromisoformat(cfg.end_date)
    sched = build_news_schedule(start, end, cfg.event_filter)
    rng = np.random.default_rng(cfg.seed)
    real = load_tick_csv(cfg.tick_csv) if cfg.tick_csv else None
    px_open = 2650.0
    pnl_list, equity_curve, news_slips = [], [], []
    liquidations, payouts = 0, 0
    eod_peak, max_dd_eod = cfg.initial_balance, 0.0

    d = start
    while d <= end:
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        day_events = [e for e in sched if e["date"] == d]
        if real is not None:
            if d not in real:
                d += timedelta(days=1)
                continue
            secs, px, spread = real[d]
        else:
            secs, px, spread = synthetic_day_ticks(rng, d, px_open, day_events)
        px_open = float(px[-1])
        if acct.liquidated:
            # restart a fresh account after liquidation (models buying a reset)
            acct = sentinel.new_account("BACKTEST", stage=cfg.stage)  # type: ignore[arg-type]
            sentinel.accounts["BACKTEST"] = acct
        for e_idx, side, x_idx in _signals(cfg.strategy_name, secs, px, day_events, spread):
            cap = funded_max_contracts(acct.closed_profit) if cfg.stage == "FUNDED" else 100
            qty = min(cfg.lot_size_micros, cap)
            spread = spread * cfg.spread_multiplier if cfg.spread_multiplier != 1.0 else spread
            slip_e = spread[e_idx] / 2 + (2 if spread[e_idx] > 1 else 0)
            slip_x = spread[x_idx] / 2
            entry = px[e_idx] + side * slip_e * TICK
            exit_ = px[x_idx] - side * slip_x * TICK
            # intraday adverse excursion check vs MLL
            path = px[e_idx:x_idx + 1]
            worst = (path.min() - entry) if side > 0 else (entry - path.max())
            sentinel.mark("BACKTEST", worst * POINT_VALUE * qty)
            if acct.liquidated:
                pnl = (worst * POINT_VALUE - COMMISSION_RT) * qty
                liquidations += 1
            else:
                pnl = ((exit_ - entry) * side * POINT_VALUE - COMMISSION_RT) * qty
            sentinel.realize("BACKTEST", pnl)
            pnl_list.append(pnl)
            if spread[e_idx] > 1:
                news_slips.append({"date": d.isoformat(), "slip_ticks": float(slip_e + slip_x),
                                   "cost_usd": round(float((slip_e + slip_x) * TICK_VALUE * qty), 2)})
            if acct.liquidated:
                break
        sentinel.end_of_day("BACKTEST", d.isoformat())
        if cfg.stage == "EVALUATION" and sentinel.eval_passed("BACKTEST"):
            acct.stage = "FUNDED"
            acct.qualifying_days = 0
        elif acct.stage == "FUNDED":
            elig = sentinel.payout_eligibility("BACKTEST")
            if elig["eligible"] and elig["max_request"] > 0:
                sentinel.approve_payout("BACKTEST", elig["max_request"])
                payouts += 1
        eod_peak = max(eod_peak, acct.closed_balance)
        max_dd_eod = max(max_dd_eod, eod_peak - acct.closed_balance)
        equity_curve.append({"date": d.isoformat(), "balance": round(acct.closed_balance, 2), "mll": acct.mll,
                             "drawdown": round(acct.closed_balance - eod_peak, 2)})
        d += timedelta(days=1)

    arr = np.array(pnl_list) if pnl_list else np.zeros(1)
    wins, losses = arr[arr > 0], arr[arr < 0]
    daily = np.diff([cfg.initial_balance] + [e["balance"] for e in equity_curve]) if equity_curve else np.zeros(1)
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
    return {
        "strategy": cfg.strategy_name, "trades": len(pnl_list),
        "win_rate": round(float(len(wins) / max(1, len(pnl_list))), 4),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3) if losses.size else None,
        "max_drawdown_eod": round(float(max_dd_eod), 2),
        "total_net_pnl": round(float(arr.sum()), 2),
        "sharpe": round(sharpe, 3),
        "qualified_payouts": payouts,
        "liquidated_accounts_count": liquidations,
        "news_slippage": news_slips[-50:],
        "equity_curve": equity_curve,
        "data_source": cfg.tick_csv or "synthetic_seeded",
    }
