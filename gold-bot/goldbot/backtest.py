"""Trade simulator on daily bars for CME gold futures (default: 1 MGC on Tradovate).

Conservative fill rules, because daily bars hide the order of moves inside a session:
  * if a stop and a target are both touched in the same session, the stop wins
  * on the session a limit entry fills, only the stop can trigger (the target is
    assumed to have come before the fill), and the trade otherwise rolls on
  * gaps through a stop exit at the open (worse price)
One position at a time per run (no overlapping trades).
Prices are spot-equivalent; $ P&L per contract = price move * ounces.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DEFAULT_CONTRACT, DEFAULT_PLAN, Contract


def simulate(d: pd.DataFrame, sig: pd.DataFrame, h: int, stop_col: str | None,
             tgt_col: str | None, entry: str = "market", contract: Contract = DEFAULT_CONTRACT,
             plan: str = DEFAULT_PLAN) -> pd.DataFrame:
    """sig: index = signal dates (session closes), columns: side (+1/-1/0), atr,
    up_q10/50/90, dn_q10/50/90 (ATR units). Returns one row per trade."""
    O, H, L, C = (d[c].to_numpy() for c in ("Open", "High", "Low", "Close"))
    pos_of = {t: i for i, t in enumerate(d.index)}
    cost = contract.round_turn_cost(plan)
    trades, next_free = [], -1
    for t, row in sig.iterrows():
        side = int(row.side)
        i = pos_of.get(t)
        if side == 0 or i is None or i < next_free or i + h >= len(C):
            continue
        ref, a = C[i], row.atr
        stop = ref - side * row[stop_col] * a if stop_col else None
        tgt = ref + side * row[tgt_col] * a if tgt_col else None
        fill_px, fill_j = None, None
        if entry == "market":
            fill_px, fill_j = O[i + 1], i + 1
        else:  # limit at the predicted median low (long) / high (short)
            lim = ref - row["dn_q50"] * a if side > 0 else ref + row["up_q50"] * a
            for j in range(i + 1, i + h + 1):
                if side > 0 and L[j] <= lim:
                    fill_px, fill_j = min(lim, O[j]), j
                    break
                if side < 0 and H[j] >= lim:
                    fill_px, fill_j = max(lim, O[j]), j
                    break
            if fill_px is None:
                next_free = i + h
                continue
        exit_px, exit_j, why = None, None, "time"
        for j in range(fill_j, i + h + 1):
            first_bar_limit = entry == "limit" and j == fill_j
            if stop is not None:
                gap = (O[j] <= stop) if side > 0 else (O[j] >= stop)
                hit = (L[j] <= stop) if side > 0 else (H[j] >= stop)
                if gap and not first_bar_limit:
                    exit_px, exit_j, why = O[j], j, "stop"
                    break
                if hit:
                    exit_px, exit_j, why = stop, j, "stop"
                    break
            if tgt is not None and not first_bar_limit:
                hit = (H[j] >= tgt) if side > 0 else (L[j] <= tgt)
                if hit:
                    exit_px = max(tgt, O[j]) if side > 0 else min(tgt, O[j])
                    exit_j, why = j, "target"
                    break
        if exit_px is None:
            exit_px, exit_j = C[i + h], i + h
        pnl = side * (exit_px - fill_px) * contract.ounces - cost
        trades.append({"signal": t, "entry_date": d.index[fill_j], "exit_date": d.index[exit_j],
                       "side": side, "entry": fill_px, "exit": exit_px, "why": why,
                       "pnl_usd": pnl})
        # a signal at the exit session's close enters at the NEXT open, so it is allowed
        next_free = exit_j
    return pd.DataFrame(trades)


def summarize(tr: pd.DataFrame, years: float) -> dict:
    if tr.empty:
        return {"trades": 0}
    p = tr.pnl_usd
    eq = p.cumsum()
    dd = float((eq - eq.cummax()).min())
    per_year = len(tr) / years
    gross_win, gross_loss = p[p > 0].sum(), -p[p < 0].sum()
    by_year = tr.groupby(pd.to_datetime(tr.exit_date).dt.year).pnl_usd.sum()
    return {
        "trades": len(tr),
        "trades_per_yr": round(per_year, 1),
        "win%": round(float((p > 0).mean() * 100), 1),
        "avg_$": round(float(p.mean()), 2),
        "$_per_yr": round(float(p.sum() / years), 0),
        "max_dd_$": round(dd, 0),
        "profit_factor": round(float(gross_win / gross_loss), 2) if gross_loss > 0 else np.inf,
        "sharpe": round(float(p.mean() / p.std() * np.sqrt(per_year)), 2) if p.std() > 0 else 0,
        "pos_years%": round(float((by_year > 0).mean() * 100), 0),
    }
