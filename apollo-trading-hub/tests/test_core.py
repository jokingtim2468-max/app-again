import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.src.trading.risk_sentinel import RiskSentinel, funded_max_contracts  # noqa: E402
from backend.src.trading.backtester import BacktestConfig, run_backtest  # noqa: E402


def test_funded_tiers():
    assert [funded_max_contracts(p) for p in (0, 999, 1000, 2000, 3000, 4500, -50)] == [40, 40, 50, 60, 80, 100, 40]


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


# ---------------- script adapter ----------------
import hashlib  # noqa: E402
SCRIPTS = Path(__file__).parent / "scripts"


def _bt(script, **kw):
    from backend.src.trading.backtester import run_any
    kw.setdefault("timeframe", "5m")
    return run_any(BacktestConfig(strategy_name=Path(script).stem, script_path=str(SCRIPTS / script),
                                  start_date="2025-03-03", end_date="2025-03-07", **kw))


def test_adapter_styles_and_source_untouched():
    expected = {"sma_pandas.py": "vectorized", "vbt_style.py": "vectorized", "bt_style.py": "event_class",
                "btpy_style.py": "event_class", "onbar_func.py": "event_func", "mt5_bot.py": "mt5_python"}
    for f, style in expected.items():
        before = hashlib.sha256((SCRIPTS / f).read_bytes()).hexdigest()
        r = _bt(f)
        assert r["adapter"]["style"] == style, f
        assert r["trades"] > 0, f
        assert hashlib.sha256((SCRIPTS / f).read_bytes()).hexdigest() == before, f"{f} was modified"


def test_lookahead_detected():
    r = _bt("peeks.py")
    assert any("look-ahead bias" in x for x in r["adapter"]["report"])
    assert any("passed" in x for x in _bt("sma_pandas.py")["adapter"]["report"])


def test_infinite_loop_guard(monkeypatch):
    from backend.src.trading import adapter
    monkeypatch.setattr(adapter, "with_deadline", lambda fn, s, w, _o=adapter.with_deadline: _o(fn, 1, w))
    import pytest
    with pytest.raises(adapter.AdapterError, match="exceeded"):
        adapter.adapt(SCRIPTS / "hangs.py")


def test_csv_bars_and_signal_file(tmp_path):
    import pandas as pd
    idx = pd.date_range("2025-03-03 09:00", periods=600, freq="1min", tz="America/New_York")
    px = 2900 + (pd.Series(range(600)) % 50) * 0.3
    pd.DataFrame({"time": idx.strftime("%Y-%m-%d %H:%M:%S"), "open": px, "high": px + .5, "low": px - .5, "close": px,
                  "volume": 10}).to_csv(tmp_path / "bars.csv", index=False)
    r = _bt("sma_pandas.py", data_source="csv", data_path=str(tmp_path / "bars.csv"))
    assert r["data_source"].startswith("csv:") and r["bars"] > 50
    pd.DataFrame({"time": [idx[60], idx[200]], "signal": ["buy", "flat"]}).to_csv(tmp_path / "sig.csv", index=False)
    from backend.src.trading.backtester import run_any
    r = run_any(BacktestConfig(strategy_name="sig", script_path=str(tmp_path / "sig.csv"), data_source="csv",
                               data_path=str(tmp_path / "bars.csv"), start_date="2025-03-03", end_date="2025-03-03"))
    assert r["trades"] == 1


def test_mt5_report_parser_and_replay():
    from backend.src.trading.mt5_tester import parse_deals, replay_deals
    from backend.src.trading.bar_engine import BarConfig
    row = lambda t, d, p: f"<tr><td>{t}</td><td>2</td><td>XAUUSD</td><td>buy</td><td>{d}</td><td>0.10</td><td>2900.00</td><td>3</td><td>0.00</td><td>0.00</td><td>0.00</td><td>{p}</td><td>150 000.00</td><td></td></tr>"
    html_ = "<html><b>Deals</b><table>" + row("2025.03.03 15:00:00", "in", "0.00") + row("2025.03.03 16:00:00", "out", "300.00") + row("2025.03.04 15:00:00", "out", "-50.00") + "</table></html>"
    deals = parse_deals(html_.encode("utf-16"))
    r = replay_deals(deals, BarConfig())
    assert r["trades"] == 2 and r["total_net_pnl"] == 250.0 and len(r["equity_curve"]) == 2


class _FakeMT5:
    """Mimics the MetaTrader5 package (server time = UTC+2) to exercise the direct transport."""
    import numpy as _np
    TIMEFRAME_M1 = TIMEFRAME_M5 = TIMEFRAME_M15 = TIMEFRAME_M30 = TIMEFRAME_H1 = TIMEFRAME_H4 = TIMEFRAME_D1 = 1
    COPY_TICKS_ALL = -1
    OFF = 7200

    def initialize(self, **k): return True
    def symbol_select(self, s, b): return True
    def last_error(self): return (1, "ok")
    def symbol_info(self, s):
        import types
        return types.SimpleNamespace(point=0.01, digits=2, trade_tick_size=0.01, trade_tick_value=1, trade_contract_size=100, description="Gold")
    def symbol_info_tick(self, s):
        import time, types
        return types.SimpleNamespace(time=int(time.time()) + self.OFF, bid=2900.0, ask=2900.3, last=0, volume=0, time_msc=(int(time.time()) + self.OFF) * 1000)
    def copy_rates_range(self, s, tf, a, b):
        import numpy as np
        t0 = int(a.timestamp())
        n = 300
        arr = np.zeros(n, dtype=[("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"), ("tick_volume", "<u8"), ("spread", "<i4")])
        arr["time"] = t0 + np.arange(n) * 60
        px = 2900 + np.sin(np.arange(n) / 9) * 4
        arr["open"], arr["close"], arr["high"], arr["low"] = px, px + .1, px + .6, px - .6
        arr["tick_volume"], arr["spread"] = 20, 25
        return arr


def test_mt5_direct_history_converts_server_time(monkeypatch):
    from backend.src.data import mt5_data, sources
    monkeypatch.delenv("APOLLO_MT5_UTC_OFFSET", raising=False)
    monkeypatch.setattr(mt5_data, "_client", mt5_data._Direct(_FakeMT5()))
    df = sources.load_bars("mt5", "2025-03-03T14:00:00+00:00", "2025-03-03T19:00:00+00:00", "1m", "XAUUSD")
    assert str(df.index[0]) == "2025-03-03 14:00:00+00:00"       # server UTC+2 shifted back to UTC
    assert abs(df["spread"].iloc[0] - 0.25) < 1e-9               # 25 points * 0.01
    r = _bt("sma_pandas.py", data_source="mt5", symbol="XAUUSD", timeframe="1m")
    assert r["data_source"].startswith("mt5:XAUUSD") and r["engine"] == "bar"


def test_forward_test_on_sim_feed():
    import asyncio
    from backend.src.trading.forward_test import ForwardTester
    from backend.src.trading.market_feed import MarketFeed
    async def go():
        events = []
        feed = MarketFeed("MGCZ6", events.append)
        ft = ForwardTester(events.append, sim_feed=feed)
        st = await ft.start(str(SCRIPTS / "sma_pandas.py"), source="sim", timeframe="1m")
        await asyncio.sleep(3)
        s = ft.status(); await ft.stop()
        return st, s
    st, s = asyncio.run(go())
    assert s["error"] is None and s["last_bar"] is not None and st["script"]["style"] == "vectorized"


# ---------------- Pine + other platforms ----------------
def test_pine_indicators_match_reference():
    import numpy as np
    from backend.src.data.sources import load_bars
    from backend.src.trading.pine import PineRuntime
    bars = load_bars("synthetic", "2025-03-03", "2025-03-05", "5m")
    rt = PineRuntime('//@version=5\nindicator("x")\na = ta.sma(close, 14)\nr = ta.rsi(close, 14)\nc1 = close[1]\n')
    rt.run(bars)
    a = np.array(list(rt.H["a"].vals)); ref = bars.close.rolling(14).mean().to_numpy()
    assert np.allclose(a[13:], ref[13:]) and np.isnan(a[:13]).all()
    assert np.allclose(np.array(list(rt.H["c1"].vals))[1:], bars.close.to_numpy()[:-1])
    r = np.array(list(rt.H["r"].vals)); assert np.nanmin(r) >= 0 and np.nanmax(r) <= 100 and np.isnan(r[:14]).all()


def test_all_formats_adapt_without_touching_source():
    expected = {"ma_cross.pine": "pine", "rsi_v4.pine": "pine", "funcs_v6.pine": "pine", "messy.pine": "pine",
                "ft_strategy.py": "freqtrade", "qc_algo.py": "quantconnect", "research.ipynb": "vectorized",
                "signals.json": "vectorized", "tv_trades.csv": "vectorized", "nt_trades.csv": "vectorized"}
    for f, style in expected.items():
        before = hashlib.sha256((SCRIPTS / f).read_bytes()).hexdigest()
        r = _bt(f)
        assert r["adapter"]["style"] == style, f
        assert r["trades"] > 0, f
        assert hashlib.sha256((SCRIPTS / f).read_bytes()).hexdigest() == before, f
        assert not any("look-ahead bias" in x for x in r["adapter"]["report"]), f


def test_pine_inputs_override_and_trade_list_count():
    r = _bt("messy.pine", params={"Mode": "Revert"})
    assert any("'Mode': 'Revert'" in x for x in r["adapter"]["report"])
    assert _bt("nt_trades.csv")["trades"] == 2 and _bt("tv_trades.csv")["trades"] == 2


def test_unsupported_formats_explain(tmp_path):
    from backend.src.trading.adapter import AdapterError, adapt
    import pytest
    for ext, word in ((".cs", "NinjaTrader"), (".els", "TradeStation"), (".mq4", "MQL4")):
        f = tmp_path / f"x{ext}"; f.write_text("x")
        with pytest.raises(AdapterError, match=word):
            adapt(f)


# ---------------- multi-firm / multi-broker ----------------
def _fleet(*accts):
    return {"name": "t", "accounts": [dict(a) for a in accts]}


M = {"id": "M", "role": "master", "firm": "lucid", "plan": "FLEX", "size": "150K", "broker": "tradovate"}


def test_intraday_trailing_and_lock():
    s = RiskSentinel(_fleet(M, {"id": "A", "role": "copy", "firm": "apex", "plan": "INTRADAY", "size": "50K", "broker": "rithmic"}))
    a = s.accounts["A"]
    assert a.mll == 48000 and a.rules["drawdown_type"] == "INTRADAY"
    s.mark("A", 1000)                       # intraday high-water mark trails the MLL immediately
    assert a.mll == 49000
    s.mark("A", 5000)                       # Apex eval: stops trailing at start + target (53,000)
    assert a.mll == 53000 and a.mll_locked


def test_static_drawdown_and_daily_limit():
    s = RiskSentinel(_fleet(M, {"id": "F", "role": "copy", "firm": "ftmo", "plan": "CHALLENGE_2STEP", "size": "100K", "broker": "mt5", "symbol": "XAUUSD"}))
    f = s.accounts["F"]
    s.realize("F", 3000); s.end_of_day("F", "2025-01-02")
    assert f.mll == 90000                   # static: never trails
    s.mark("F", -5000)
    assert f.daily_limit_hit and f.status == "DAILY_LIMIT"
    assert not s.validate_order("F", "EVALUATION", 1, "XAUUSD")["approved"]
    s.mark("F", 0); s.end_of_day("F", "2025-01-03")
    assert not f.daily_limit_hit and f.status == "ACTIVE"


def test_consistency_pct_blocks_eval_pass():
    s = RiskSentinel(_fleet(M, {"id": "T", "role": "copy", "firm": "topstep", "plan": "COMBINE", "size": "50K", "broker": "projectx"}))
    s.realize("T", 2500); s.end_of_day("T", "d1"); s.realize("T", 600); s.end_of_day("T", "d2")
    assert not s.eval_passed("T")           # best day 2,500 > 50% of 3,100
    for d in ("d3", "d4", "d5"):
        s.realize("T", 700); s.end_of_day("T", d)
    t = s.accounts["T"]                     # 55% rule: passed at d5 EOD -> promoted to a fresh funded account
    assert t.stage == "FUNDED" and t.passed_at and t.closed_balance == 50000


def test_mixed_fleet_copy_ratios_paper():
    import asyncio
    from backend.src.trading.tradovate_bridge import Fill, FleetRouter
    s = RiskSentinel(_fleet(M, {"id": "FT", "role": "copy", "firm": "ftmo", "plan": "CHALLENGE_2STEP", "size": "100K", "broker": "mt5", "symbol": "XAUUSD", "copy_ratio": 0.1},
                            {"id": "NT", "role": "copy", "firm": "bulenox", "plan": "TRAILING", "size": "50K", "broker": "rithmic", "copy_ratio": 2}))
    r = FleetRouter(s)
    assert r.mode == "PAPER" and {c.name for c in r.connectors.values()} == {"paper"}
    out = asyncio.run(r.mirror(Fill("M", "Buy", "MGCZ6", 10, 2900.0)))
    by = {o["account"]: o for o in out}
    assert by["FT"]["qty"] == 1.0 and by["FT"]["symbol"] == "XAUUSD"   # 10 MGC -> 1.0 lot XAUUSD
    assert by["NT"]["qty"] == 20


def test_live_refuses_unverified_firm(monkeypatch):
    import asyncio
    from backend.src.brokers.base import BrokerError, Connector
    from backend.src.trading import tradovate_bridge as tb

    class Fake(Connector):
        name = "fake"
        async def connect(self): self.connected = True
        async def place_market(self, a, act, sym, q): return {"orderId": 1}
    monkeypatch.setenv("APOLLO_LIVE", "1")
    monkeypatch.setattr(tb, "make_connector", lambda b, live, sfx="": Fake(live))
    s = RiskSentinel(_fleet(M, {"id": "AP", "role": "copy", "firm": "takeprofittrader", "plan": "TEST", "size": "150K", "broker": "rithmic"}))
    r = tb.FleetRouter(s)
    import pytest
    with pytest.raises(BrokerError, match="unverified"):
        asyncio.run(r.place_market("AP", "Buy", "MGCZ6", 1, 2900.0))
    assert asyncio.run(r.place_market("M", "Buy", "MGCZ6", 1, 2900.0))["orderId"] == 1   # Lucid profile is verified


def test_ninjatrader_oif(tmp_path, monkeypatch):
    import asyncio
    from backend.src.brokers.ninjatrader import NinjaTraderConnector
    (tmp_path / "incoming").mkdir(); (tmp_path / "outgoing").mkdir()
    monkeypatch.setenv("NT8_DIR", str(tmp_path))
    c = NinjaTraderConnector(True)
    asyncio.run(c.connect())
    asyncio.run(c.place_market("APEX-123", "Sell", "MGCZ6", 3))
    line = next((tmp_path / "incoming").glob("oif*.txt")).read_text().strip()
    assert line.startswith("PLACE;APEX-123;MGC 12-26;SELL;3;MARKET;;;DAY;")
    (tmp_path / "outgoing" / "MGC 12-26 APEX-123_position.txt").write_text("SHORT;3;2900.0")
    assert asyncio.run(c.positions("APEX-123")) == {"MGC 12-26": -3.0}


def test_projectx_order_payload(monkeypatch):
    import asyncio
    from backend.src.brokers.projectx import ProjectXConnector
    calls = []

    async def fake_post(self, path, body):
        calls.append((path, body))
        return {"/api/Auth/loginKey": {"token": "t"}, "/api/Account/search": {"accounts": [{"name": "50KTC-1", "id": 7}]},
                "/api/Contract/search": {"contracts": [{"id": "CON.F.US.MGC.Z26", "activeContract": True}]},
                "/api/Order/place": {"orderId": 99, "success": True}}[path]
    monkeypatch.setattr(ProjectXConnector, "_post", fake_post)
    monkeypatch.setenv("PROJECTX_USER", "u"); monkeypatch.setenv("PROJECTX_API_KEY", "k")
    c = ProjectXConnector(True)
    asyncio.run(c.connect())
    r = asyncio.run(c.place_market("50KTC-1", "Buy", "MGCZ6", 2))
    assert r["orderId"] == 99 and calls[-1][1] == {"accountId": 7, "contractId": "CON.F.US.MGC.Z26", "type": 2, "side": 0, "size": 2}


def test_backtest_any_firm_profile():
    r = _bt("sma_pandas.py", firm="topstep", plan="COMBINE", size="50K")
    assert r["rules"]["firm_name"] == "Topstep" and r["rules"]["starting_drawdown"] == 2000 and r["rules"]["verified"] is True


def test_every_firm_profile_loads():
    from backend.src.trading.risk_sentinel import list_firms, resolve_rules
    for firm, meta in list_firms().items():
        for plan, sizes in meta["plans"].items():
            for sz in sizes:
                r = resolve_rules(firm, plan, sz)
                assert r["starting_drawdown"] > 0 and r["drawdown_type"] in ("END_OF_DAY", "INTRADAY", "STATIC")


# ---------------- firm caps: park / unpark queue ----------------
def _lucid_fleet(n_funded=5, n_eval=2):
    acc = [dict(M, stage="FUNDED", cost=0)]
    acc += [{"id": f"F{i}", "role": "copy", "firm": "lucid", "plan": "FLEX", "size": "150K", "broker": "tradovate", "stage": "FUNDED"} for i in range(1, n_funded)]
    acc += [{"id": f"E{i}", "role": "copy", "firm": "lucid", "plan": "FLEX", "size": "150K", "broker": "tradovate", "cost": 150} for i in range(1, n_eval + 1)]
    return RiskSentinel({"accounts": acc})


def test_eval_parks_when_lucid_funded_cap_full_and_unparks_on_failure():
    s = _lucid_fleet()
    assert s.firm_cap("lucid") == 5 and s.slots_free("lucid") == 0
    s.realize("E1", 8000)                      # below 9,000 target - 500 buffer: keeps trading
    assert not s.accounts["E1"].parked
    s.mark("E1", 600)                           # equity profit 8,600 >= 8,500 -> parked + flatten requested
    e1 = s.accounts["E1"]
    assert e1.parked and e1.status == "PARKED" and "E1" in s.pending_flatten
    v = s.validate_order("E1", "EVALUATION", 1, "MGC")
    assert not v["approved"] and "parked" in v["reasons"][-1] and v["approved_qty"] == 0
    s.mark("E1", 0); s.realize("E2", 8600)      # second eval queues behind the first
    assert s.queue("lucid") == ["E1", "E2"]
    s.mark("F1", -4500)                         # a funded account blows its MLL -> slot opens
    assert s.accounts["F1"].liquidated and s.slots_free("lucid") == 1
    assert not s.accounts["E1"].parked and s.accounts["E1"].status == "ACTIVE"   # oldest parked released
    assert s.accounts["E2"].parked                                                # only one slot
    kinds = [e["kind"] for e in s.ledger]
    assert kinds.count("PARKED") == 2 and "FAILED" in kinds and "UNPARKED" in kinds


def test_released_eval_passes_and_fills_slot():
    s = _lucid_fleet()
    s.realize("E1", 8600); s.mark("F1", -4500)
    s.realize("E1", 900); s.end_of_day("E1", "2025-02-03")    # 9,500 profit, best day 9,500 > 3,600 cap
    assert s.accounts["E1"].stage == "EVALUATION"             # Lucid consistency cap still enforced
    s2 = _lucid_fleet()
    s2.mark("F1", -4500)                                        # slot free from the start
    for d in range(1, 4):
        s2.realize("E1", 3100); s2.end_of_day("E1", f"2025-02-0{d}")
    e = s2.accounts["E1"]
    assert e.stage == "FUNDED" and s2.slots_free("lucid") == 0
    s2.realize("E2", 8800)
    assert s2.accounts["E2"].parked                            # cap full again -> next eval parks


def test_funded_outside_app_counts_and_firm_summary():
    s = RiskSentinel({"accounts": [dict(M), {"id": "E1", "role": "copy", "firm": "lucid", "plan": "FLEX", "size": "150K",
                                              "broker": "tradovate", "cost": 140}],
                      "firm_limits": {"lucid": {"funded_outside_app": 5}}})
    s.realize("E1", 8700)
    assert s.accounts["E1"].parked              # 5 funded elsewhere fill the cap
    f = s.firm_summary()["lucid"]
    assert f["funded"] == 5 and f["slots_free"] == 0 and f["parked"] == 1 and f["cost"] == 140 and f["queue"] == ["E1"]


def test_closing_cashout_account_frees_slot():
    s = _lucid_fleet()
    s.realize("E1", 8800)
    assert s.accounts["E1"].parked
    s.close_account("F2", "cashout done")
    assert not s.accounts["E1"].parked


def test_ledger_persists(tmp_path):
    s = _lucid_fleet(); s.realize("E1", 8800); s.save(tmp_path / "st.json")
    s2 = _lucid_fleet(); s2.load(tmp_path / "st.json")
    assert s2.accounts["E1"].parked and any(e["kind"] == "PARKED" for e in s2.ledger)



# ---------------- researched rule details ----------------
def test_lucid_official_rules():
    from backend.src.trading.risk_sentinel import resolve_rules
    r = resolve_rules("lucid", "FLEX", "150K")
    assert r["eval_consistency_pct"] == 0.40 and r["mll_lock_threshold"] == 154600 and r["mll_lock_level"] == 150100
    s = RiskSentinel(_fleet(dict(M, stage="FUNDED")))
    m = s.accounts["M"]
    assert s.validate_order("M", "FUNDED", 50, "MGC")["max_allowed"] == 40
    s.realize("M", 1200); assert s.validate_order("M", "FUNDED", 1, "MGC")["max_allowed"] == 50
    s.realize("M", 3500); assert s.validate_order("M", "FUNDED", 1, "MGC")["max_allowed"] == 100   # $4,700 >= $4,500
    s.approve_payout("M", 500)
    assert m.mll == 150100 and m.mll_locked       # first payout locks the MLL at start + $100


def test_mffu_rapid_switches_to_intraday_when_funded():
    s = RiskSentinel(_fleet(M, {"id": "R", "role": "copy", "firm": "mffu", "plan": "RAPID", "size": "50K", "broker": "tradovate"}))
    r = s.accounts["R"]
    assert r.rules["drawdown_type"] == "END_OF_DAY"
    s.promote("R")
    assert r.rules["drawdown_type"] == "INTRADAY"


def test_size_level_unverified_flag():
    from backend.src.trading.risk_sentinel import resolve_rules
    assert resolve_rules("takeprofittrader", "TEST", "50K")["verified"] is True
    assert resolve_rules("takeprofittrader", "TEST", "150K")["verified"] is False
    assert resolve_rules("ftmo", "CHALLENGE_2STEP", "100K")["sources"]
