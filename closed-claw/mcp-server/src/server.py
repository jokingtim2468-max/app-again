"""Closed Claw MCP server.  stdio (default) or SSE on 127.0.0.1:54981.

    python -m src.server              # stdio (Claude Desktop / Antigravity)
    python -m src.server --sse        # http://127.0.0.1:54981/sse
"""
from __future__ import annotations

import asyncio
import os
import sys

if __package__ in (None, ""):  # allow `python path/to/src/server.py`
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "src"

from mcp.server.fastmcp import FastMCP  # noqa: E402

from src import config  # noqa: E402,F401  (sets backend path)
from src.tools import backtest_tools, container_tools, fleet_tools, risk_tools  # noqa: E402

mcp = FastMCP("closed-claw", host=config.MCP_HOST, port=config.MCP_PORT)


@mcp.tool()
def run_backtest(strategy_name: str = "news_momentum", start_date: str = "2025-01-01",
                 end_date: str = "2025-06-30", initial_balance: float = 150000.0,
                 lot_size_micros: int = 20, event_filter: list[str] | None = None) -> dict:
    """MGC tick backtest with CPI/Core PCE/NFP/FOMC news bursts under LucidFlex 150K EOD rules.
    strategy_name: news_momentum | news_fade | breakout. Synthetic data: validates rules, not edge."""
    return backtest_tools.run_backtest(strategy_name, start_date, end_date, initial_balance,
                                       lot_size_micros, event_filter)


@mcp.tool()
def get_fleet_status() -> dict:
    """Balances, positions, PnL, distance to MLL, qualifying days and payout eligibility for all 5 accounts."""
    return fleet_tools.get_fleet_status()


@mcp.tool()
def validate_order_risk(account_id: str, stage: str, contract_qty: int, symbol: str = "MGC") -> dict:
    """Check an order against LucidFlex 150K scaling (EVALUATION 100 MGC; FUNDED tiered by closed profit)."""
    return risk_tools.validate_order_risk(account_id, stage, contract_qty, symbol)


@mcp.tool()
async def query_news_model(headline: str, event_name: str, consensus_forecast: str, actual_print: str) -> dict:
    """Ask local Ollama news-predictor-3b for gold_bias, confidence and expected_expansion_points."""
    from backend.src.ai import ollama_client
    return await ollama_client.predict(headline, event_name, consensus_forecast, actual_print)


@mcp.tool()
def inspect_containers() -> dict:
    """List Closed Claw Docker sandboxes with CPU/RAM allocation and usage."""
    return container_tools.inspect_containers()


@mcp.tool()
def execute_container_command(container_id: str, command: str) -> dict:
    """Run a shell command inside a Closed Claw sandbox container (only containers labeled by Closed Claw)."""
    return container_tools.execute_container_command(container_id, command)


def main() -> None:
    transport = "sse" if ("--sse" in sys.argv or os.getenv("MCP_TRANSPORT") == "sse") else "stdio"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
