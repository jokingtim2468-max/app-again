"""Run an MQL5 Expert Advisor in MetaTrader 5's Strategy Tester, then replay its deals through LucidFlex rules.

Windows only (MT5 is a Windows app). The EA source is copied to <MT5 data>/MQL5/Experts/Apollo/ and compiled
there: the user's file is never touched. Requires APOLLO_MT5_PATH (terminal64.exe) and, if the MetaTrader5
package isn't installed, APOLLO_MT5_DATA_DIR (File > Open Data Folder in MT5).
Note: MT5 allows one running instance per data folder; close the terminal (or use a portable copy) first.
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

from .bar_engine import BarConfig
from .risk_sentinel import RiskSentinel, load_fleet_config

MODELS = {"every_tick_real": 4, "every_tick": 0, "ohlc_m1": 1, "open_prices": 2}
PERIODS = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30", "1h": "H1", "4h": "H4", "1d": "D1"}


class TesterError(RuntimeError):
    pass


def _paths() -> tuple[Path, Path]:
    term = os.getenv("APOLLO_MT5_PATH")
    if not term or not Path(term).exists():
        raise TesterError("set APOLLO_MT5_PATH to terminal64.exe to run MQL5 EAs (Windows only)")
    data = os.getenv("APOLLO_MT5_DATA_DIR")
    if not data:
        try:
            import MetaTrader5 as mt5  # type: ignore
            if mt5.initialize(path=term):
                data = mt5.terminal_info().data_path
                mt5.shutdown()  # tester needs the terminal free
        except ImportError:
            pass
    if not data:
        raise TesterError("set APOLLO_MT5_DATA_DIR (MT5: File > Open Data Folder)")
    return Path(term), Path(data)


def compile_ea(src: Path, data_dir: Path, term: Path) -> Path:
    dest_dir = data_dir / "MQL5" / "Experts" / "Apollo"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".ex5":
        out = dest_dir / src.name
        shutil.copy2(src, out)
        return out
    copy = dest_dir / src.name
    shutil.copy2(src, copy)
    editor = term.with_name("metaeditor64.exe")
    log = copy.with_suffix(".log")
    subprocess.run([str(editor), f"/compile:{copy}", f"/log:{log}"], timeout=180)
    ex5 = copy.with_suffix(".ex5")
    if not ex5.exists():
        txt = log.read_text(encoding="utf-16", errors="replace") if log.exists() else ""
        raise TesterError(f"MetaEditor compile failed:\n{txt[-2000:]}")
    return ex5


def run_tester(src_path: str, symbol: str, start: str, end: str, timeframe: str = "1m",
               model: str = "every_tick_real", deposit: float = 150000.0, inputs: dict | None = None,
               timeout_s: int = 3600) -> pd.DataFrame:
    term, data = _paths()
    ex5 = compile_ea(Path(src_path), data, term)
    tag = re.sub(r"\W+", "_", ex5.stem)
    report_rel = f"Apollo\\report_{tag}"
    report = data / "Apollo" / f"report_{tag}.htm"
    report.parent.mkdir(exist_ok=True)
    report.unlink(missing_ok=True)
    ini = data / "Apollo" / f"tester_{tag}.ini"
    lines = ["[Tester]", f"Expert=Apollo\\{ex5.name}", f"Symbol={symbol}", f"Period={PERIODS[timeframe]}",
             f"Model={MODELS[model]}", "Optimization=0", f"FromDate={start.replace('-', '.')}", f"ToDate={end.replace('-', '.')}",
             "ForwardMode=0", f"Deposit={int(deposit)}", "Currency=USD", "Leverage=100", "ExecutionMode=0",
             f"Report={report_rel}", "ReplaceReport=1", "ShutdownTerminal=1", "Visual=0"]
    if inputs:
        lines += ["[TesterInputs]"] + [f"{k}={v}" for k, v in inputs.items()]
    ini.write_text("\r\n".join(lines) + "\r\n", encoding="utf-16")
    subprocess.run([str(term), f"/config:{ini}"], timeout=timeout_s)
    found = next((p for p in (report, report.with_suffix(".html"), data / f"{report_rel}.htm") if p.exists()), None)
    if not found:
        raise TesterError(f"tester produced no report at {report} (is another MT5 instance using this data folder?)")
    return parse_deals(found.read_bytes())


def parse_deals(raw: bytes) -> pd.DataFrame:
    """Parse the 'Deals' table of an MT5 tester HTML report (UTF-16 or UTF-8)."""
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", errors="replace")
    k = text.find("Deals")
    if k < 0:
        raise TesterError("no Deals section in report")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text[k:], re.S | re.I)
    out = []
    for r in rows:
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)]
        if len(cells) >= 13 and re.match(r"\d{4}\.\d{2}\.\d{2}", cells[0]):
            # Time, Deal, Symbol, Type, Direction, Volume, Price, Order, Commission, Fee?, Swap, Profit, Balance, Comment
            num = lambda s: float(s.replace(" ", "").replace(",", "") or 0)
            profit_i = -3 if len(cells) >= 14 else -2
            out.append({"time": datetime.strptime(cells[0], "%Y.%m.%d %H:%M:%S"), "type": cells[3].lower(),
                        "direction": cells[4].lower(), "volume": num(cells[5]), "price": num(cells[6]),
                        "commission": num(cells[8]), "swap": num(cells[-4] if len(cells) >= 14 else cells[9]),
                        "profit": num(cells[profit_i])})
    if not out:
        raise TesterError("report contained no deals (EA never traded in this range?)")
    return pd.DataFrame(out)


def replay_deals(deals: pd.DataFrame, cfg: BarConfig, server_utc_offset_h: float = 0.0) -> dict:
    """Apply LucidFlex EOD rules to tester deals (closed-trade PnL; intrabar excursion is not in the report)."""
    rules = load_fleet_config()["rules"]
    s = RiskSentinel()
    a = s.new_account("MT5", stage=cfg.stage)  # type: ignore[arg-type]
    a.closed_balance = a.day_start_balance = cfg.initial_balance
    a.mll = cfg.initial_balance - rules["starting_drawdown"]
    s.accounts["MT5"] = a
    d = deals[deals["direction"].isin(["out", "in/out", "out by"])].copy()
    d["net"] = d["profit"] + d["commission"] + d["swap"]
    t = pd.DatetimeIndex(d["time"]).tz_localize("UTC") - pd.Timedelta(hours=server_utc_offset_h)
    d["session"] = (t.tz_convert("America/New_York") + pd.Timedelta(hours=7)).date
    curve, payouts, liq, peak, mdd = [], 0, 0, cfg.initial_balance, 0.0
    for sess, g in d.groupby("session"):
        for v in g["net"]:
            s.realize("MT5", float(v))
            s.mark("MT5", 0.0)
            if a.liquidated:
                liq += 1
                break
        s.end_of_day("MT5", str(sess))
        if a.stage == "EVALUATION" and s.eval_passed("MT5"):
            a.stage = "FUNDED"
        elif a.stage == "FUNDED":
            el = s.payout_eligibility("MT5")
            if el["eligible"] and el["max_request"] > 0:
                s.approve_payout("MT5", el["max_request"]); payouts += 1
        peak = max(peak, a.closed_balance); mdd = max(mdd, peak - a.closed_balance)
        curve.append({"date": str(sess), "balance": round(a.closed_balance, 2), "mll": a.mll, "drawdown": round(a.closed_balance - peak, 2)})
        if a.liquidated:
            break
    net = d["net"].to_numpy()
    wins, losses = net[net > 0], net[net < 0]
    return {"strategy": cfg.label, "engine": "mt5_tester", "trades": int(net.size),
            "win_rate": round(float(wins.size / max(1, net.size)), 4),
            "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if losses.size else None,
            "max_drawdown_eod": round(mdd, 2), "total_net_pnl": round(float(net.sum()), 2), "sharpe": 0.0,
            "qualified_payouts": payouts, "liquidated_accounts_count": liq, "equity_curve": curve, "news_slippage": [],
            "note": "PnL is the EA's own account-currency result from MT5; MLL checked on closed deals only."}
