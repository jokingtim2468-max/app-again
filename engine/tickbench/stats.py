"""Performance statistics computed from an equity curve and a list of closed trades."""

from __future__ import annotations

import math
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np

from .core.bars import Bars
from .core.broker import Trade

MS_PER_YEAR = 365.25 * 24 * 3600 * 1000


def _finite(x):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def periods_per_year(times: np.ndarray) -> float:
    if len(times) < 3:
        return 252.0
    # Count the bars actually present per year, so weekends/sessions are handled for any timeframe.
    span = (times[-1] - times[0]) / MS_PER_YEAR
    return max(1.0, (len(times) - 1) / span) if span > 0 else 252.0


def drawdown(equity: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    peak = np.maximum.accumulate(equity)
    dd_abs = equity - peak
    with np.errstate(divide="ignore", invalid="ignore"):
        dd_pct = np.where(peak > 0, dd_abs / peak * 100.0, 0.0)
    return dd_abs, dd_pct


def _longest_streak(flags: list[bool], value: bool) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f == value else 0
        best = max(best, cur)
    return best


def compute(bars: Bars, equity: np.ndarray, trades: list[Trade], initial: float, buyhold: np.ndarray) -> dict:
    eq = np.asarray(equity, dtype=float)
    times = bars.time
    final = float(eq[-1]) if len(eq) else initial
    net = final - initial
    years = max((times[-1] - times[0]) / MS_PER_YEAR, 1e-9)
    cagr = ((final / initial) ** (1 / years) - 1) * 100 if final > 0 and initial > 0 else -100.0

    rets = np.diff(eq) / np.where(eq[:-1] == 0, np.nan, eq[:-1])
    rets = rets[np.isfinite(rets)]
    ppy = periods_per_year(times)
    sharpe = sortino = None
    if len(rets) > 2 and np.std(rets) > 0:
        sharpe = float(np.mean(rets) / np.std(rets, ddof=1) * math.sqrt(ppy))
        downside = rets[rets < 0]
        if len(downside) > 1:
            dd_dev = math.sqrt(float(np.mean(np.minimum(rets, 0) ** 2)))
            if dd_dev > 0:
                sortino = float(np.mean(rets) / dd_dev * math.sqrt(ppy))

    dd_abs, dd_pct = drawdown(eq)
    max_dd_pct = float(-dd_pct.min()) if len(dd_pct) else 0.0
    max_dd_abs = float(-dd_abs.min()) if len(dd_abs) else 0.0
    # longest time spent below a previous equity high
    longest_dd_ms = 0
    start = None
    for i, v in enumerate(dd_abs):
        if v < 0 and start is None:
            start = i
        elif v >= 0 and start is not None:
            longest_dd_ms = max(longest_dd_ms, int(times[i] - times[start]))
            start = None
    if start is not None:
        longest_dd_ms = max(longest_dd_ms, int(times[-1] - times[start]))
    calmar = (cagr / max_dd_pct) if max_dd_pct > 0 else None

    closed = [t for t in trades if not t.is_open]
    pnls = [t.pnl for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    n = len(closed)
    win_rate = len(wins) / n * 100 if n else None
    pf = (gross_win / gross_loss) if gross_loss > 0 else (None if not wins else math.inf)
    avg_win = gross_win / len(wins) if wins else None
    avg_loss = -gross_loss / len(losses) if losses else None
    expectancy = sum(pnls) / n if n else None
    held = [t.exit_bar - t.entry_bar for t in closed]
    held_ms = [t.exit_time - t.entry_time for t in closed]
    in_market = np.zeros(len(bars), dtype=bool)
    for t in trades:
        end = t.exit_bar if t.exit_bar is not None else len(bars) - 1
        in_market[t.entry_bar:end + 1] = True
    rs = []
    for t in closed:
        if t.initial_sl is not None and t.exit_price is not None:
            risk = abs(t.entry_price - t.initial_sl)
            if risk > 0:
                rs.append((t.exit_price - t.entry_price) * t.side / risk)

    bh_final = float(buyhold[-1]) if len(buyhold) else initial
    longs = [t for t in closed if t.side > 0]
    shorts = [t for t in closed if t.side < 0]

    s = OrderedDict()
    s["netProfit"] = net
    s["netProfitPct"] = net / initial * 100 if initial else None
    s["finalEquity"] = final
    s["cagr"] = cagr
    s["buyHoldPct"] = (bh_final / initial - 1) * 100 if initial else None
    s["sharpe"] = sharpe
    s["sortino"] = sortino
    s["calmar"] = calmar
    s["maxDrawdownPct"] = max_dd_pct
    s["maxDrawdown"] = max_dd_abs
    s["longestDrawdownDays"] = longest_dd_ms / 86_400_000
    s["trades"] = n
    s["longTrades"] = len(longs)
    s["shortTrades"] = len(shorts)
    s["winRate"] = win_rate
    s["longWinRate"] = (sum(1 for t in longs if t.pnl > 0) / len(longs) * 100) if longs else None
    s["shortWinRate"] = (sum(1 for t in shorts if t.pnl > 0) / len(shorts) * 100) if shorts else None
    s["profitFactor"] = pf
    s["expectancy"] = expectancy
    s["avgWin"] = avg_win
    s["avgLoss"] = avg_loss
    s["payoffRatio"] = (avg_win / -avg_loss) if (avg_win and avg_loss) else None
    s["largestWin"] = max(pnls) if pnls else None
    s["largestLoss"] = min(pnls) if pnls else None
    s["grossProfit"] = gross_win
    s["grossLoss"] = -gross_loss
    s["maxConsecWins"] = _longest_streak([p > 0 for p in pnls], True)
    s["maxConsecLosses"] = _longest_streak([p > 0 for p in pnls], False)
    s["avgBarsHeld"] = (sum(held) / len(held)) if held else None
    s["avgHoldHours"] = (sum(held_ms) / len(held_ms) / 3_600_000) if held_ms else None
    s["exposurePct"] = float(in_market.mean() * 100) if len(bars) else 0.0
    s["commission"] = sum(t.commission for t in trades)
    s["avgR"] = (sum(rs) / len(rs)) if rs else None
    s["recoveryFactor"] = (net / max_dd_abs) if max_dd_abs > 0 else None
    s["bars"] = len(bars)
    s["start"] = int(times[0])
    s["end"] = int(times[-1])
    out = {}
    for k, v in s.items():
        if isinstance(v, (bool, np.bool_)):
            out[k] = bool(v)
        elif isinstance(v, (int, np.integer)):
            out[k] = int(v)
        elif isinstance(v, (float, np.floating)):
            out[k] = _finite(v)
        else:
            out[k] = v
    return out


def monthly_returns(times: np.ndarray, equity: np.ndarray) -> list[dict]:
    """Return per-month % change of the equity curve: [{year, month, pct}]."""
    out: list[dict] = []
    if len(equity) == 0:
        return out
    last_key = None
    month_start = float(equity[0])
    prev_close = float(equity[0])
    for t, e in zip(times, equity):
        dt = datetime.fromtimestamp(int(t) / 1000, tz=timezone.utc)
        key = (dt.year, dt.month)
        if last_key is None:
            last_key = key
        if key != last_key:
            out.append({"year": last_key[0], "month": last_key[1],
                        "pct": (prev_close / month_start - 1) * 100 if month_start else 0.0})
            month_start = prev_close
            last_key = key
        prev_close = float(e)
    out.append({"year": last_key[0], "month": last_key[1],
                "pct": (prev_close / month_start - 1) * 100 if month_start else 0.0})
    return out
