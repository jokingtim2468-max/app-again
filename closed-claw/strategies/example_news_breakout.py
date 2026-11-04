"""Copy to strategies/<name>.py, then backtest with strategy_name="<name>" (UI, API or MCP).

generate_signals(secs, px, spread, events) -> list of (entry_idx, side, exit_idx)
  secs   : np.ndarray seconds-of-day, one per second 08:00-16:59 ET (index 0 == 08:00:00)
  px     : np.ndarray MGC price per second
  spread : np.ndarray spread in ticks per second (widens around news)
  events : list of {"event","ts": datetime,"burst_points","spread_ticks"} for that day
  side   : +1 long, -1 short. Exit index must be > entry. Sizing/slippage/rules are applied by the engine.
"""
import numpy as np


def generate_signals(secs, px, spread, events):
    trades = []
    for ev in events:
        i0 = ev["ts"].hour * 3600 + ev["ts"].minute * 60 - int(secs[0])
        e = i0 + 30
        if i0 < 0 or e + 600 >= px.size:
            continue
        move = px[e] - px[i0]
        if abs(move) >= 1.5:
            trades.append((e, int(np.sign(move)), e + 600))
    return trades
