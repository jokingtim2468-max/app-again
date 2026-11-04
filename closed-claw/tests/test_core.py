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


def test_plugin_strategy_and_csv(tmp_path):
    from backend.src.trading.backtester import list_strategies
    assert "example_news_breakout" in list_strategies()
    r = run_backtest(BacktestConfig(strategy_name="example_news_breakout", end_date="2025-03-31"))
    assert r["trades"] >= 0
    csv = tmp_path / "ticks.csv"
    rows = ["timestamp,price"] + [f"2025-01-06T{h:02d}:{m:02d}:00,{2650 + (h - 8) + m / 60:.1f}" for h in range(8, 17) for m in range(60)]
    csv.write_text("\n".join(rows))
    r = run_backtest(BacktestConfig(strategy_name="breakout", start_date="2025-01-06", end_date="2025-01-06", tick_csv=str(csv)))
    assert r["data_source"] == str(csv) and r["trades"] == 1 and r["total_net_pnl"] > 0


def test_state_persists(tmp_path):
    s = RiskSentinel(); a = "LUCID_SLAVE_01"
    s.realize(a, 1000); s.end_of_day(a, "2025-01-02"); s.save(tmp_path / "st.json")
    s2 = RiskSentinel(); assert s2.load(tmp_path / "st.json")
    assert s2.accounts[a].mll == 146500 and s2.accounts[a].last_eod == "2025-01-02"


def test_layouts_roundtrip(tmp_path, monkeypatch):
    from backend.src import layouts
    monkeypatch.setattr(layouts, "LAYOUT_FILE", tmp_path / "layouts.json")
    for name, w in layouts.PRESETS.items():
        layouts.validate(w)
    layouts.save("Mine", [{"i": "c", "type": "widget-chart", "x": 0, "y": 0, "w": 12, "h": 10}], activate=True)
    d = layouts.get_all()
    assert d["active"] == "Mine" and d["layouts"]["Mine"]["widgets"][0]["type"] == "widget-chart"
    import pytest
    with pytest.raises(ValueError):
        layouts.validate([{"type": "widget-chart", "x": 8, "w": 6}])
    with pytest.raises(ValueError):
        layouts.validate([{"type": "widget-news"}])


def test_fills_avg_price_and_kill():
    s = RiskSentinel(); a = "LUCID_SLAVE_01"
    s.apply_fill(a, "Buy", 10, 2650.0); s.apply_fill(a, "Buy", 10, 2652.0)
    assert s.accounts[a].avg_price == 2651.0
    pnl = s.apply_fill(a, "Sell", 20, 2653.0)
    assert pnl == 400.0 and s.accounts[a].position_qty == 0 and s.accounts[a].closed_balance == 150400
    s.kill()
    assert all(x.status == "KILLED" for x in s.accounts.values())
    assert not s.validate_order(a, "EVALUATION", 1, "MGC")["approved"]
    assert s.resume(a) and s.accounts[a].status == "ACTIVE"


def test_graduation_status():
    s = RiskSentinel(); a = "LUCID_SLAVE_04"; s.accounts[a].stage = "FUNDED"
    for _ in range(5):
        s.approve_payout(a, 100)
    assert s.accounts[a].status == "ELIGIBLE_FOR_CASHOUT" and not s.resume(a)
