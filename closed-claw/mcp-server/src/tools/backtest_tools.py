from .. import config  # noqa: F401  (adds repo root to sys.path)
from backend.src.trading.backtester import BacktestConfig, run_backtest as _run


def run_backtest(strategy_name: str = "news_momentum", start_date: str = "2025-01-01",
                 end_date: str = "2025-06-30", initial_balance: float = 150000.0,
                 lot_size_micros: int = 20, event_filter: list[str] | None = None) -> dict:
    res = _run(BacktestConfig(strategy_name, start_date, end_date, initial_balance, lot_size_micros, event_filter))
    res["equity_curve"] = res["equity_curve"][-60:]  # keep MCP payload small
    return res
