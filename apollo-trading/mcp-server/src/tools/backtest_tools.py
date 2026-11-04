from .. import config  # noqa: F401  (adds repo root to sys.path)
from backend.src.trading.backtester import BacktestConfig, run_any


def run_backtest(**kw) -> dict:
    res = run_any(BacktestConfig(**{k: v for k, v in kw.items() if v is not None}))
    res["equity_curve"] = res["equity_curve"][-60:]   # keep MCP payload small
    res["trade_log"] = res.get("trade_log", [])[-30:]
    return res
