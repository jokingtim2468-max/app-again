import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.src.trading.risk_sentinel import RiskSentinel, funded_max_contracts  # noqa: E402
from backend.src.trading.backtester import BacktestConfig, run_backtest  # noqa: E402


def test_funded_tiers():
    assert [funded_max_contracts(p) for p in (0, 1999, 2000, 3000, 4500, 6000, -50)] == [40, 40, 50, 60, 80, 100, 40]


def test_eod_only_trailing_and_lock():
    s = RiskSentinel(); a = "LUCID_SLAVE_01"
    s.mark(a, 3000)  # intraday wick up: MLL must not move
    assert s.accounts[a].mll == 145500
    s.realize(a, 2000); s.end_of_day(a, "2025-01-02")
    assert s.accounts[a].mll == 147500
    s.realize(a, 2600); s.end_of_day(a, "2025-01-03")
    assert s.accounts[a].mll == 150100 and s.accounts[a].mll_locked


def test_liquidation_on_breach():
    s = RiskSentinel(); a = "LUCID_SLAVE_03"
    s.mark(a, -4500)
    assert s.accounts[a].liquidated


def test_funded_clamp():
    s = RiskSentinel(); a = "LUCID_SLAVE_02"; s.accounts[a].stage = "FUNDED"
    r = s.validate_order(a, "FUNDED", 45, "MGCZ6")
    assert not r["approved"] and r["approved_qty"] == 40


def test_graduation_halts():
    s = RiskSentinel(); a = "LUCID_SLAVE_04"; s.accounts[a].stage = "FUNDED"
    for _ in range(5):
        r = s.approve_payout(a, 100)
    assert r["graduation"]["net_payout_usd"] == 2025.0 and s.accounts[a].halted
    assert not s.validate_order(a, "FUNDED", 1, "MGC")["approved"]


def test_backtest_runs_all_strategies():
    for st in ("news_momentum", "news_fade", "breakout"):
        r = run_backtest(BacktestConfig(strategy_name=st, end_date="2025-03-31"))
        assert {"win_rate", "profit_factor", "max_drawdown_eod", "total_net_pnl",
                "qualified_payouts", "liquidated_accounts_count"} <= r.keys()
