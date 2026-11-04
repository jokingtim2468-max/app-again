"""Apollo Trading MCP server. Deterministic tools only (no AI inference).

    python -m src.server              # stdio (Claude Desktop / Claude Code / Antigravity)
    python -m src.server --sse        # SSE at http://127.0.0.1:54981/sse
"""
from __future__ import annotations

import functools
import inspect
import os
import sys

if __package__ in (None, ""):  # allow `python path/to/src/server.py`
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "src"

import httpx  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from src import config  # noqa: E402  (adds repo root to sys.path)
from src.tools import backtest_tools, fleet_tools, layout_tools, risk_tools  # noqa: E402

mcp = FastMCP("apollo-trading-hub", host=config.MCP_HOST, port=config.MCP_PORT)


def _report(tool: str, args: dict, result=None, error: str | None = None) -> None:
    """Mirror each tool call into the Apollo UI event stream (best effort)."""
    try:
        httpx.post(f"{config.BACKEND_API_URL}/api/agent/tool_event", timeout=1,
                   json={"tool": tool, "args": args, "result": result, "error": error})
    except httpx.HTTPError:
        pass


def reported(fn):
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*a, **k):
        args = dict(sig.bind_partial(*a, **k).arguments)
        try:
            r = fn(*a, **k)
        except Exception as e:
            _report(fn.__name__, args, error=str(e))
            raise
        short = {kk: v for kk, v in r.items() if kk not in ("equity_curve", "news_slippage", "presets", "trade_log")} \
            if isinstance(r, dict) else r
        _report(fn.__name__, args, short)
        return r
    return wrapper


@mcp.tool()
@reported
def run_backtest(strategy_name: str = "news_momentum", start_date: str = "2025-01-01", end_date: str = "2025-06-30",
                 initial_balance: float = 150000.0, lot_size_micros: int = 20, script_path: str | None = None,
                 data_source: str = "synthetic", symbol: str = "XAUUSD", timeframe: str = "1m",
                 data_path: str | None = None, stage: str = "EVALUATION", spread_multiplier: float = 1.0,
                 params: dict | None = None) -> dict:
    """Backtest ANY strategy script under LucidFlex 150K EOD rules (MGC economics).
    script_path: any .py (pandas/vectorbt/backtrader/backtesting.py/on_bar/MetaTrader5 bot), .mq5/.ex5 EA (MT5 tester),
                 or signal .csv. The user's file is never modified; a harness copy is adapted. Omit to use strategy_name
                 (built-in or a file in apollo-trading-hub/strategies/).
    data_source: synthetic | csv (data_path to bars or ticks) | mt5 (real broker history for `symbol`, e.g. XAUUSD).
    Returns metrics, equity curve, trade log and the adapter report (incl. look-ahead check)."""
    return backtest_tools.run_backtest(strategy_name=strategy_name, start_date=start_date, end_date=end_date,
                                       initial_balance=initial_balance, lot_size_micros=lot_size_micros,
                                       script_path=script_path, data_source=data_source, symbol=symbol,
                                       timeframe=timeframe, data_path=data_path, stage=stage,
                                       spread_multiplier=spread_multiplier, params=params)


@mcp.tool()
@reported
def inspect_strategy(script: str) -> dict:
    """Show how a script would be adapted (style, entry point, shims) without running a backtest."""
    from backend.src.trading.adapter import adapt
    from backend.src.trading.backtester import strategy_path
    p = strategy_path(script)
    return adapt(str(p) if p else script).describe()


@mcp.tool()
@reported
def list_strategies() -> list[str]:
    """Strategy names available to run_backtest (built-ins + files in apollo-trading-hub/strategies/)."""
    from backend.src.trading.backtester import list_strategies as ls
    return ls()


@mcp.tool()
@reported
def forward_test(action: str = "status", script: str = "", source: str = "mt5", symbol: str = "XAUUSD",
                 timeframe: str = "1m", lot_size_micros: int = 5) -> dict:
    """Paper-trade a script on LIVE data (action: start | stop | status). source: mt5 | sim. Never sends broker orders."""
    url = f"{config.BACKEND_API_URL}/api/forward/{action}"
    body = {"script": script, "source": source, "symbol": symbol, "timeframe": timeframe, "lot_size_micros": lot_size_micros}
    r = httpx.get(url, timeout=10) if action == "status" else httpx.post(url, json=body, timeout=30)
    if r.status_code >= 400:
        raise ValueError(r.json().get("detail", r.text))
    return r.json()


@mcp.tool()
@reported
def mt5_status() -> dict:
    """Is MetaTrader 5 reachable (direct package or Windows bridge)?"""
    from backend.src.data import mt5_data
    return mt5_data.status()


@mcp.tool()
@reported
def get_fleet_status() -> dict:
    """Balances, open MGC contracts, daily PnL, distance to MLL, qualifying days, status for all 5 accounts."""
    return fleet_tools.get_fleet_status()


@mcp.tool()
@reported
def validate_order_risk(account_id: str, stage: str, contract_qty: int, symbol: str = "MGC") -> dict:
    """Check an order against LucidFlex 150K scaling: EVALUATION 100 MGC; FUNDED 40/50/60/80/100 by closed profit."""
    return risk_tools.validate_order_risk(account_id, stage, contract_qty, symbol)


@mcp.tool()
@reported
def save_custom_layout(layout_name: str, layout_json: list[dict], activate: bool = True) -> dict:
    """Create/update a workspace layout and (optionally) switch the open Apollo UI to it.
    layout_json: list of {i, type, x, y, w, h, settings} on a 12-column grid (row = 30px).
    type: widget-chart | widget-dom | widget-fleet | widget-tape | widget-backtest | widget-terminal.
    settings: chart {timeframe: 1m|5m|15m}, tape {min_size: int}, fleet {compact: bool}."""
    return layout_tools.save_custom_layout(layout_name, layout_json, activate)


@mcp.tool()
@reported
def get_workspace_layouts() -> dict:
    """All saved layouts, built-in presets, the active layout and grid rules."""
    return layout_tools.get_workspace_layouts()


def main() -> None:
    transport = "sse" if ("--sse" in sys.argv or os.getenv("MCP_TRANSPORT") == "sse") else "stdio"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
