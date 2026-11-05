"""Cockpit services: live parameters, engine state, market intelligence, quick orders, trade forensics.

Mounted by server.py with `cockpit.init(ctx)` + `app.include_router(cockpit.router)`. One background loop (`run`)
watches every tick: breakeven steps, pending limit orders, daily-loss circuit breaker, trade open/close tracking and,
in AUTONOMOUS mode, the built-in confluence entries. Trading stays PAPER unless a human sets APOLLO_LIVE=1.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .paths import STATE_DIR
from .trading import confluence as C

router = APIRouter()
PARAMS_FILE = STATE_DIR / "engine_params.json"
TRADES_FILE = STATE_DIR / "trades.json"
NEWS_FILE = STATE_DIR / "news_calendar.json"
ENGINE_FILE = STATE_DIR / "engine_state.json"
MODES = ("AUTONOMOUS", "MANUAL")


@dataclass
class Ctx:
    sentinel: Any
    feed: Any
    bridge: Any
    emit: Callable[[dict], None]
    order: Callable[..., Awaitable[dict]]          # order(action, qty, tp_points, sl_points)
    flatten: Callable[[str], Awaitable[None]]       # flatten(reason)
    kill: Callable[[str | None], Awaitable[dict]]   # kill(account_id | None)
    get_bracket: Callable[[], dict | None]
    set_bracket: Callable[[dict | None], None]


ctx: Ctx | None = None


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


# ---------------- state ----------------
params: dict = {**C.DEFAULT_PARAMS, **_load(PARAMS_FILE, {})}
engine: dict = {"mode": "MANUAL", "gateway_url": "http://127.0.0.1:8001", "dxy_symbol": "DXY", "gvz_symbol": "GVZ",
                **_load(ENGINE_FILE, {})}
engine["mode"] = "MANUAL"  # never resume autonomous trading on its own after a restart
trades: list[dict] = _load(TRADES_FILE, [])
open_trade: dict | None = None
pending_limits: list[dict] = []
last_signal: dict = {}
_cool = {"until": 0.0, "long": 0.0, "short": 0.0}
_macro: dict = {"ts": 0.0, "dxy": None, "gvz": None, "error": None}
_breaker_day: dict[str, str] = {}


def init(c: Ctx) -> None:
    global ctx
    ctx = c


def _master():
    s = ctx.sentinel
    return s.accounts[s.config["master_account"]]


def _pv(acct) -> float:
    return 100.0 if acct.contract == "XAUUSD" else float(params["point_value"])


# ---------------- market intelligence ----------------
def quote() -> dict:  # noqa: C901
    f = ctx.feed
    bids, asks = f.book.get("bids") or [], f.book.get("asks") or []
    bid = bids[0][0] if bids else round(f.last - 0.05, 2)
    ask = asks[0][0] if asks else round(f.last + 0.05, 2)
    spread = round(ask - bid, 2)
    return _plain({"symbol": f.symbol, "source": f.source, "bid": bid, "ask": ask, "last": f.last, "mid": round((bid + ask) / 2, 2),
            "spread": spread, "spread_wide": spread > params["max_spread"], "ts": time.time()})


async def _refresh_macro() -> None:
    """DXY + GVZ from the MT5 gateway (`/rates`), cached for a minute. Missing symbols just show as unavailable."""
    if time.time() - _macro["ts"] < 60:
        return
    _macro["ts"] = time.time()
    out, err = {}, None
    async with httpx.AsyncClient(timeout=4) as cl:
        for key in ("dxy", "gvz"):
            try:
                r = await cl.get(f"{engine['gateway_url'].rstrip('/')}/rates",
                                 params={"symbol": engine[f"{key}_symbol"], "timeframe": "M15", "count": 20})
                r.raise_for_status()
                rows = r.json()
                rows = rows.get("rates", rows) if isinstance(rows, dict) else rows
                closes = [float(x["close"]) for x in rows]
                out[key] = {"last": closes[-1], "first": closes[0], "trend": "up" if closes[-1] > closes[0] else "down"}
            except Exception as e:  # gateway down / symbol not offered by the broker
                out[key] = None
                err = f"{key.upper()}: {type(e).__name__}"
    _macro.update(out, error=err)


async def _macro_bg() -> None:
    try:
        await _refresh_macro()
    finally:
        _macro["busy"] = False


def gvz_regime() -> dict:
    g = _macro.get("gvz")
    if not g:
        return {"available": False}
    v = g["last"]
    return {"available": True, "value": round(v, 2), "regime": "LOW" if v < 15 else "NORMAL" if v < 22 else "HIGH_EXPANSION"}


def _nfp_estimates(n: int = 3) -> list[dict]:
    """First Friday 08:30 ET of the next months. Marked estimated: BLS sometimes moves it; edit the calendar to confirm."""
    out, d = [], date.today().replace(day=1)
    for _ in range(n + 1):
        f = d + timedelta(days=(4 - d.weekday()) % 7)
        out.append({"time": datetime(f.year, f.month, f.day, 8, 30, tzinfo=C.ET).isoformat(), "title": "Non-Farm Payrolls",
                    "impact": "high", "estimated": True})
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def news() -> dict:
    cal = _load(NEWS_FILE, None)
    events = cal if isinstance(cal, list) else _nfp_estimates()
    now = datetime.now(C.ET)
    upcoming = sorted((e for e in events if datetime.fromisoformat(e["time"]) + timedelta(minutes=params["news_after_min"]) >= now),
                      key=lambda e: e["time"])
    nxt = upcoming[0] if upcoming else None
    locked, secs = False, None
    if nxt:
        t = datetime.fromisoformat(nxt["time"])
        secs = int((t - now).total_seconds())
        locked = -params["news_after_min"] * 60 <= secs <= params["news_before_min"] * 60
    return {"next": nxt, "seconds_to_next": secs, "blackout": locked, "events": upcoming[:20],
            "window": {"before_min": params["news_before_min"], "after_min": params["news_after_min"]},
            "custom_calendar": isinstance(cal, list)}


def _plain(o):
    """numpy scalars from the feed -> plain Python for JSON."""
    return json.loads(json.dumps(o, default=lambda x: x.item() if hasattr(x, "item") else str(x)))


def intel() -> dict:
    f = ctx.feed
    m1 = list(f.bars)
    m5, m15 = C.resample(m1, 5), C.resample(m1, 15)
    now = time.time()
    reg = C.regime(m15)
    ad = C.adaptive(params, reg["regime"], reg["atr"])
    asian = C.asian_range(m1, params, now)
    vwap = C.session_vwap(m1, now)
    dxy = _macro.get("dxy")
    conf = C.confluence(m5, f.last, vwap, asian, params, dxy["trend"] if dxy else None)
    today = datetime.now(C.ET).date().isoformat()
    return _plain({"quote": quote(), "regime": reg, "adaptive": ad, "asian": asian, "vwap": vwap, "confluence": conf,
            "dxy": dxy, "gvz": gvz_regime(), "macro_error": _macro.get("error"), "news": news(),
            "trades_today": sum(1 for t in trades if t.get("day") == today), "engine": engine_state()})


def engine_state() -> dict:
    return {"mode": engine["mode"], "live": bool(getattr(ctx.bridge, "live", False)), "broker_mode": ctx.bridge.mode,
            "open_trade": open_trade, "pending_limits": pending_limits, "last_signal": last_signal,
            "cooldown_until": _cool["until"], "gateway_url": engine["gateway_url"]}


# ---------------- trade tracking ----------------
def _trade_tick(px: float) -> None:
    """Open/close round trips on the master account and keep MFE/MAE."""
    global open_trade
    m = _master()
    if m.position_qty and open_trade is None:
        side = "long" if m.position_qty > 0 else "short"
        b = ctx.get_bracket() or {}
        open_trade = {"id": f"T{int(time.time() * 1000)}", "account": m.account_id, "side": side, "qty": abs(m.position_qty),
                      "entry": round(m.avg_price, 2), "entry_time": time.time(), "sl": b.get("sl"), "tp": b.get("tp"),
                      "risk": abs(m.avg_price - b["sl"]) if b.get("sl") else None, "mfe": 0.0, "mae": 0.0, "be": False,
                      "score": last_signal.get("score"), "regime": last_signal.get("regime"), "source": last_signal.get("source", "manual")}
        ctx.emit({"type": "trade_open", **open_trade})
    elif open_trade and m.position_qty == 0:
        t = open_trade
        open_trade = None
        d = 1 if t["side"] == "long" else -1
        gross = (px - t["entry"]) * d * _pv(m) * t["qty"]
        comm = params["commission_rt"] * t["qty"]
        reason = t.get("exit_reason") or "manual"
        if reason == "stop_loss" and t["be"]:
            reason = "breakeven"
        row = {**t, "exit": round(px, 2), "exit_time": time.time(), "hold_s": round(time.time() - t["entry_time"], 1),
               "gross": round(gross, 2), "commission": round(comm, 2), "net": round(gross - comm, 2), "reason": reason,
               "mfe": round(t["mfe"] * _pv(m) * t["qty"], 2), "mae": round(t["mae"] * _pv(m) * t["qty"], 2),
               "day": datetime.now(C.ET).date().isoformat()}
        trades.append(row)
        del trades[:-5000]
        _save(TRADES_FILE, trades)
        _cool["until"] = time.time() + params["cooldown_after_trade_s"]
        if row["net"] < 0:
            _cool[t["side"]] = time.time() + params["cooldown_after_loss_s"]
        ctx.emit({"type": {"take_profit": "tp_hit", "stop_loss": "sl_hit", "breakeven": "breakeven_exit"}.get(reason, "trade_closed"),
                  **row})
    elif open_trade:
        d = 1 if open_trade["side"] == "long" else -1
        open_trade["mfe"] = max(open_trade["mfe"], (px - open_trade["entry"]) * d)
        open_trade["mae"] = max(open_trade["mae"], (open_trade["entry"] - px) * d)
        b = ctx.get_bracket() or {}
        open_trade["sl"], open_trade["tp"] = b.get("sl", open_trade["sl"]), b.get("tp", open_trade["tp"])


def note_exit(reason: str) -> None:
    if open_trade:
        open_trade["exit_reason"] = reason


def _step_breakeven(force: bool = False) -> bool:
    t, b = open_trade, ctx.get_bracket()
    if not t or not b or t["be"]:
        return False
    d = 1 if t["side"] == "long" else -1
    gain = (ctx.feed.last - t["entry"]) * d
    trigger_r = C.adaptive(params, C.regime(C.resample(list(ctx.feed.bars), 15))["regime"], 0)["be_trigger_r"]
    if (force and gain > params["be_lock"]) or (t.get("risk") and gain >= trigger_r * t["risk"]):
        b = {**b, "sl": round(t["entry"] + d * params["be_lock"], 2)}
        ctx.set_bracket(b)
        t["be"], t["sl"] = True, b["sl"]
        ctx.emit({"type": "breakeven_step", "account": t["account"], "sl": b["sl"], "entry": t["entry"],
                  "lock_usd": round(params["be_lock"] * _pv(_master()) * t["qty"] - params["commission_rt"] * t["qty"], 2)})
        return True
    return False


async def _daily_breaker() -> None:
    today = datetime.now(C.ET).date().isoformat()
    for aid, a in ctx.sentinel.accounts.items():
        if a.day_pnl <= -params["daily_loss_kill"] and _breaker_day.get(aid) != today and a.status != "HALTED":
            _breaker_day[aid] = today
            ctx.emit({"type": "daily_loss_breaker", "account": aid, "day_pnl": round(a.day_pnl, 2), "limit": params["daily_loss_kill"]})
            await ctx.kill(aid)


async def _limits(px: float) -> None:
    for o in list(pending_limits):
        hit = px <= o["price"] if o["action"] == "Buy" else px >= o["price"]
        if hit and _master().position_qty == 0:
            pending_limits.remove(o)
            last_signal.update(source=o["label"], score=None, regime=None)
            await _bracketed(o["action"], o["label"])


async def _bracketed(action: str, source: str) -> dict:
    reg = C.regime(C.resample(list(ctx.feed.bars), 15))
    ad = C.adaptive(params, reg["regime"], reg["atr"])
    res = await ctx.order(action, int(params["contracts"]), ad["tp"], ad["sl"])
    ctx.emit({"type": "entry", "side": action, "source": source, "price": ctx.feed.last, "tp": ad["tp"], "sl": ad["sl"],
              "qty": int(params["contracts"])})
    return res


async def _autonomous() -> None:
    global last_signal
    if engine["mode"] != "AUTONOMOUS" or open_trade or _master().position_qty or time.time() < _cool["until"]:
        return
    i = intel()
    if i["news"]["blackout"] or i["quote"]["spread_wide"] or not C.in_session(time.time(), params):
        return
    if i["trades_today"] >= i["adaptive"]["quota"]:
        return
    c = i["confluence"]
    if c["score"] < params["confluence_min"] or _cool[c["side"]] > time.time():
        return
    if not params["allow_counter_trend"] and i["regime"]["regime"] == "TREND_EXPANSION_REGIME" and \
            (c["side"] == "long") != (i["regime"].get("trend") == "up"):
        return
    last_signal = {"source": "autonomous", "score": c["score"], "grade": c["grade"], "side": c["side"],
                   "regime": i["regime"]["regime"], "ts": time.time()}
    try:
        await _bracketed("Buy" if c["side"] == "long" else "Sell", "autonomous")
    except HTTPException as e:  # risk engine refused: show it, pause entries for the trade cooldown
        _cool["until"] = time.time() + params["cooldown_after_trade_s"]
        ctx.emit({"type": "route_error", "account": "master", "error": f"autonomous entry refused: {e.detail}"})


async def run() -> None:
    last_m5 = 0
    while True:
        await asyncio.sleep(0.25)
        try:
            px = ctx.feed.last
            _trade_tick(px)
            _step_breakeven()
            await _limits(px)
            await _daily_breaker()
            if time.time() - _macro["ts"] >= 60 and not _macro.get("busy"):
                _macro["busy"] = True
                asyncio.create_task(_macro_bg())
            m5 = int(time.time() // 300)
            if m5 != last_m5:  # evaluate entries once per M5 bar
                last_m5 = m5
                await _autonomous()
        except Exception as e:  # keep the loop alive; surface the problem
            ctx.emit({"type": "route_error", "account": "cockpit", "error": f"{type(e).__name__}: {e}"})
            await asyncio.sleep(2)


# ---------------- API ----------------
class ParamsPatch(BaseModel):
    values: dict = Field(default_factory=dict)


LIMITS = {"contracts": (1, 20), "base_tp": (0.5, 30), "sl_cap": (0.5, 30), "sl_min": (0.25, 30), "be_trigger_r": (0.1, 3),
          "be_lock": (0, 5), "cooldown_after_trade_s": (0, 7200), "cooldown_after_loss_s": (0, 7200), "confluence_min": (0, 10),
          "quota_range": (0, 50), "quota_balanced": (0, 50), "quota_expansion": (0, 50), "daily_loss_kill": (50, 100000),
          "max_spread": (0.05, 5), "news_before_min": (0, 240), "news_after_min": (0, 240)}


@router.get("/api/engine/params")
def get_params():
    return {"values": params, "defaults": C.DEFAULT_PARAMS, "limits": LIMITS}


@router.put("/api/engine/params")
def put_params(p: ParamsPatch):
    """Hot reload: takes effect on the next tick, no restart."""
    for k, v in p.values.items():
        if k not in C.DEFAULT_PARAMS:
            raise HTTPException(400, f"unknown parameter {k}")
        if k in LIMITS:
            lo, hi = LIMITS[k]
            if not (lo <= float(v) <= hi):
                raise HTTPException(400, f"{k} must be between {lo} and {hi}")
        params[k] = type(C.DEFAULT_PARAMS[k])(v)
    _save(PARAMS_FILE, params)
    ctx.emit({"type": "params_updated", "changed": list(p.values)})
    return get_params()


@router.get("/api/engine/state")
def get_engine():
    return engine_state()


@router.post("/api/engine/mode")
def set_mode(body: dict):
    m = str(body.get("mode", "")).upper()
    if m not in MODES:
        raise HTTPException(400, f"mode must be one of {MODES}")
    engine["mode"] = m
    ctx.emit({"type": "engine_mode", "mode": m})
    return engine_state()


@router.put("/api/engine/connection")
def set_connection(body: dict):
    for k in ("gateway_url", "dxy_symbol", "gvz_symbol"):
        if body.get(k):
            engine[k] = str(body[k])
    _save(ENGINE_FILE, {k: engine[k] for k in ("gateway_url", "dxy_symbol", "gvz_symbol")})
    _macro["ts"] = 0
    return engine_state()


@router.post("/api/engine/panic")
async def panic():
    """PANIC: autonomous off, cancel limits, flatten everything and halt every account."""
    engine["mode"] = "MANUAL"
    pending_limits.clear()
    note_exit("panic")
    ctx.set_bracket(None)
    await ctx.flatten("panic")
    res = await ctx.kill(None)
    ctx.emit({"type": "panic", **res})
    return res


@router.get("/api/market/quote")
def get_quote():
    return quote()


@router.get("/api/market/intel")
def get_intel():
    return intel()  # DXY/GVZ are refreshed by the background loop, never on this request


@router.get("/api/news")
def get_news():
    return news()


@router.put("/api/news")
def put_news(body: list[dict]):
    for e in body:
        datetime.fromisoformat(e["time"])  # validates; raises 500 -> make it a 400
    _save(NEWS_FILE, [{"time": e["time"], "title": e.get("title", "event"), "impact": e.get("impact", "high")} for e in body])
    return news()


class QuickOrder(BaseModel):
    kind: str  # buy_market | sell_market | buy_limit_asian_low | sell_limit_asian_high


@router.post("/api/exec/quick")
async def quick(o: QuickOrder):
    global last_signal
    if o.kind in ("buy_market", "sell_market"):
        last_signal = {"source": "manual", "ts": time.time()}
        return await _bracketed("Buy" if o.kind == "buy_market" else "Sell", "manual")
    if o.kind in ("buy_limit_asian_low", "sell_limit_asian_high"):
        a = C.asian_range(list(ctx.feed.bars), params, time.time())
        if not a:
            raise HTTPException(409, "no Asian session range yet")
        buy = o.kind == "buy_limit_asian_low"
        lim = {"id": f"L{int(time.time() * 1000)}", "action": "Buy" if buy else "Sell",
               "price": a["asian_low"] if buy else a["asian_high"], "label": "limit @ Asian low" if buy else "limit @ Asian high",
               "created": time.time()}
        pending_limits.append(lim)
        ctx.emit({"type": "limit_placed", **lim})
        return lim
    raise HTTPException(400, "unknown order kind")


@router.delete("/api/exec/limits/{lid}")
def cancel_limit(lid: str):
    pending_limits[:] = [x for x in pending_limits if x["id"] != lid]
    return {"pending": pending_limits}


@router.post("/api/exec/breakeven_all")
def breakeven_all():
    if not open_trade:
        return {"moved": False, "reason": "no open position"}
    moved = _step_breakeven(force=True)
    return {"moved": moved, "reason": None if moved else f"position is not yet more than {params['be_lock']} pts in profit"}


@router.get("/api/copier")
def copier():
    s = ctx.sentinel
    master = s.config["master_account"]
    slaves = s.config.get("slave_accounts", [])
    rows = []
    for aid in [master] + list(slaves):
        a = s.accounts[aid]
        rows.append({"account": aid, "role": "master" if aid == master else "follower", "copy_ratio": a.copy_ratio,
                     "contract": a.contract, "firm": a.firm, "stage": a.stage, "status": a.status, "position": a.position_qty,
                     "broker": ctx.bridge.status().get(aid, {}) if isinstance(ctx.bridge.status(), dict) else {}})
    return {"master": master, "rows": rows}


@router.put("/api/copier/{account_id}")
def set_copy_ratio(account_id: str, body: dict):
    from .trading.risk_sentinel import CONFIG_PATH
    s = ctx.sentinel
    if account_id not in s.accounts:
        raise HTTPException(404, "unknown account")
    r = float(body.get("copy_ratio", 1.0))
    if not 0 <= r <= 20:
        raise HTTPException(400, "copy_ratio must be 0-20")
    s.accounts[account_id].copy_ratio = r
    cfg = _load(CONFIG_PATH, None)
    if cfg:
        for spec in cfg.get("accounts", []):
            if spec.get("id") == account_id:
                spec["copy_ratio"] = r
        _save(CONFIG_PATH, cfg)
    return copier()


@router.get("/api/trades")
def get_trades(limit: int = 200, day: str | None = None):
    rows = [t for t in trades if not day or t.get("day") == day]
    nets = [t["net"] for t in rows]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n < 0]
    return {"open": open_trade, "trades": rows[-limit:][::-1],
            "stats": {"count": len(rows), "net": round(sum(nets), 2), "win_rate": round(len(wins) / len(nets), 4) if nets else 0,
                      "profit_factor": round(sum(wins) / -sum(losses), 3) if losses else None,
                      "commission": round(sum(t["commission"] for t in rows), 2)}}


class StudioReq(BaseModel):
    data_source: str = "synthetic"   # synthetic | mt5 | csv
    start_date: str = "2026-09-01"
    end_date: str = "2026-10-01"
    symbol: str = "XAUUSD"
    data_path: str | None = None
    params: dict | None = None
    evaluation: dict | None = None
    grid: dict[str, list] | None = None
    max_drawdown: float | None = None


def _studio_df(r: StudioReq):
    from .data.sources import load_bars
    return load_bars(r.data_source, r.start_date, r.end_date, "1m", r.symbol, r.data_path)


@router.post("/api/studio/backtest")
async def studio_backtest(r: StudioReq):
    from .trading import scalper_backtest as B
    try:
        df = await asyncio.to_thread(_studio_df, r)
        return await asyncio.to_thread(B.run, df, {**params, **(r.params or {})}, r.evaluation)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")


@router.post("/api/studio/optimize")
async def studio_optimize(r: StudioReq):
    from .trading import scalper_backtest as B
    if not r.grid:
        raise HTTPException(400, "grid is required, e.g. {\"be_trigger_r\": [0.4, 0.45, 0.5]}")
    try:
        df = await asyncio.to_thread(_studio_df, r)
        return await asyncio.to_thread(B.grid, df, {**params, **(r.params or {})}, r.grid, r.evaluation, r.max_drawdown)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")
