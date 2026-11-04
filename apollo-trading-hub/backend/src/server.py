"""Apollo Trading backend (FastAPI) on 127.0.0.1:5050. Deterministic, rule-based: no AI/LLM."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import layouts
from .containers.docker_manager import DockerManager
from .data import mt5_data
from .trading.adapter import AdapterError, adapt
from .trading.backtester import BacktestConfig, list_strategies, run_any, strategy_path
from .trading.forward_test import ForwardTester
from .trading.market_feed import MarketFeed
from .trading.risk_sentinel import ET, RiskSentinel
from .brokers import BROKERS
from .trading.risk_sentinel import CONFIG_PATH, list_firms, load_fleet_config
from .trading.tradovate_bridge import Fill, FleetRouter

sentinel = RiskSentinel()
sentinel.load()  # resume MLL / payouts / qualifying days across restarts
SYMBOL = sentinel.config.get("front_month_symbol") or sentinel.config.get("broker", {}).get("front_month_symbol", "MGCZ6")
subscribers: set[asyncio.Queue] = set()


def _emit(e: dict) -> None:
    e.setdefault("ts", datetime.now(ET).isoformat())
    for q in list(subscribers):
        if q.full():
            q.get_nowait()
        q.put_nowait(e)


bridge = FleetRouter(sentinel, on_event=_emit)
bridge_task: asyncio.Task | None = None
feed = MarketFeed(SYMBOL, on_event=_emit)
feed.token_getter = lambda: bridge.token
docker_mgr = DockerManager()
forward = ForwardTester(_emit, sim_feed=feed)


async def autosave():
    while True:
        await asyncio.sleep(5)
        await asyncio.to_thread(sentinel.save)


async def eod_scheduler():
    """Roll the MLL once per day at 17:00 ET settlement (EOD drawdown)."""
    while True:
        now = datetime.now(ET)
        if RiskSentinel.is_eod(now):
            for aid, a in sentinel.accounts.items():
                if a.last_eod != now.date().isoformat():
                    sentinel.end_of_day(aid, now.date().isoformat())
                    _emit({"type": "eod", "account": aid, "mll": a.mll})
        await asyncio.sleep(30)


async def mark_to_market():
    """Revalue open positions on every tick so distance-to-MLL is live."""
    global bracket
    while True:
        await asyncio.sleep(0.25)
        for aid, a in sentinel.accounts.items():
            if a.position_qty and a.avg_price:
                pv = 100.0 if a.contract == "XAUUSD" else 10.0
                sentinel.mark(aid, (feed.last - a.avg_price) * pv * a.position_qty)
        if bracket:
            px, b = feed.last, bracket
            hit_tp = px >= b["tp"] if b["side"] > 0 else px <= b["tp"]
            hit_sl = px <= b["sl"] if b["side"] > 0 else px >= b["sl"]
            if hit_tp or hit_sl:
                bracket = None
                await flatten_fleet("take_profit" if hit_tp else "stop_loss")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bridge_task
    bridge_task = asyncio.create_task(bridge.run())
    tasks = [asyncio.create_task(c) for c in (eod_scheduler(), autosave(), feed.run(), mark_to_market())]
    yield
    for t in tasks:
        t.cancel()
    sentinel.save()


app = FastAPI(title="Apollo Trading", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "app://.", "file://", "null"],
                   allow_methods=["*"], allow_headers=["*"])


class BacktestReq(BaseModel):
    strategy_name: str = "news_momentum"
    start_date: str = "2025-01-01"
    end_date: str = "2025-06-30"
    initial_balance: float = 150000.0
    lot_size_micros: int = 20
    event_filter: list[str] | None = None
    stage: str = "EVALUATION"
    tick_csv: str | None = None
    spread_multiplier: float = 1.0
    data_source: str = "synthetic"
    symbol: str = "XAUUSD"
    timeframe: str = "1m"
    data_path: str | None = None
    script_path: str | None = None
    params: dict | None = None
    contract: str = "MGC"
    mt5_model: str = "every_tick_real"
    firm: str | None = None
    plan: str | None = None
    size: str | None = None


class ForwardReq(BaseModel):
    script: str
    source: str = "mt5"
    symbol: str = "XAUUSD"
    timeframe: str = "1m"
    lot_size_micros: int = 5
    params: dict | None = None


class OrderReq(BaseModel):
    account_id: str
    stage: str
    contract_qty: int
    symbol: str = "MGC"


class ExecReq(BaseModel):
    command: str


class SpawnReq(BaseModel):
    image: str = "python:3.11-slim"
    name: str | None = None
    cpus: float = 1.0
    mem: str = "1g"
    network: bool = False


class FillReq(BaseModel):
    action: str
    qty: int
    symbol: str | None = None
    tp_ticks: int | None = None  # server-side bracket (emulated, works paper + live)
    sl_ticks: int | None = None


bracket: dict | None = None  # one fleet bracket on the master position


class PayoutReq(BaseModel):
    amount: float


class LayoutReq(BaseModel):
    name: str
    widgets: list[dict]
    activate: bool = False
    source: str = "ui"


class KillReq(BaseModel):
    account_id: str | None = None


@app.get("/api/health")
async def health():
    return {"ok": True, "mode": bridge.mode, "feed": feed.source, "docker": docker_mgr.available()}


# ---------------- fleet & risk ----------------
@app.get("/api/fleet/status")
def fleet_status():
    snap = sentinel.snapshot()
    for aid in snap:
        snap[aid]["payout"] = sentinel.payout_eligibility(aid)
    return {"name": sentinel.config.get("name", "fleet"), "mode": bridge.mode,
            "master": sentinel.config["master_account"], "symbol": SYMBOL, "last": feed.last, "accounts": snap}


@app.post("/api/fleet/order")
async def fleet_order(req: FillReq):
    """Master order (PAPER in sim; routed to Tradovate when live) mirrored 1:1 to slaves."""
    if req.action not in ("Buy", "Sell"):
        raise HTTPException(400, "action must be Buy or Sell")
    master = sentinel.config["master_account"]
    m = sentinel.accounts[master]
    check = sentinel.validate_order(master, m.stage, req.qty, req.symbol or SYMBOL)
    reducing = (m.position_qty > 0 and req.action == "Sell") or (m.position_qty < 0 and req.action == "Buy")
    if not check["approved"] and not reducing:
        raise HTTPException(409, {"rejected": check})
    sym = req.symbol or SYMBOL
    master_res = await bridge.place_market(master, req.action, sym, req.qty, price=feed.last)
    copies = await bridge.mirror(Fill(master, req.action, sym, req.qty, feed.last))
    global bracket
    if m.position_qty == 0:
        bracket = None
    elif req.tp_ticks or req.sl_ticks:
        d = 1 if m.position_qty > 0 else -1
        bracket = {"side": d, "tp": round(m.avg_price + d * (req.tp_ticks or 10_000) * 0.1, 1),
                   "sl": round(m.avg_price - d * (req.sl_ticks or 10_000) * 0.1, 1)}
        _emit({"type": "bracket_set", **bracket})
    return {"master": master_res, "copies": copies, "bracket": bracket}


async def flatten_fleet(reason: str) -> None:
    master = sentinel.config["master_account"]
    m = sentinel.accounts[master]
    if m.position_qty == 0:
        return
    action, qty = ("Sell" if m.position_qty > 0 else "Buy"), abs(m.position_qty)
    await bridge.place_market(master, action, SYMBOL, qty, price=feed.last)
    await bridge.mirror(Fill(master, action, SYMBOL, qty, feed.last))
    _emit({"type": "bracket_exit", "reason": reason, "price": feed.last})


@app.get("/api/fleet/bracket")
def get_bracket():
    return bracket or {}


@app.post("/api/fleet/flatten")
async def flatten_all():
    global bracket
    bracket = None
    await flatten_fleet("manual")
    return {"ok": True}


@app.get("/api/firms")
def firms():
    return list_firms()


@app.get("/api/brokers")
def brokers():
    return {"available": {k: v[2] for k, v in BROKERS.items()}, **bridge.status()}


@app.get("/api/fleet/config")
def fleet_config():
    return load_fleet_config()


@app.put("/api/fleet/config")
async def put_fleet_config(cfg: dict):
    """Validate, save and hot-reload the fleet (accounts across any firms/brokers). Open positions must be flat."""
    global sentinel, bridge, bridge_task
    if any(a.position_qty for a in sentinel.accounts.values()):
        raise HTTPException(409, "flatten all accounts before changing the fleet")
    try:
        new = RiskSentinel(cfg)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, f"invalid fleet: {e}")
    for aid, a in new.accounts.items():  # keep risk state of accounts that didn't change firm/size
        old = sentinel.accounts.get(aid)
        if old and (old.firm, old.plan, old.size) == (a.firm, a.plan, a.size):
            for k in ("closed_balance", "day_start_balance", "mll", "mll_locked", "peak_equity", "qualifying_days",
                      "payouts_approved", "total_paid_out", "halted", "liquidated", "status", "best_day_profit", "last_eod", "stage"):
                setattr(a, k, getattr(old, k))
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(CONFIG_PATH)
    if bridge_task:
        bridge_task.cancel()
    sentinel = new
    bridge = FleetRouter(sentinel, on_event=_emit)
    bridge_task = asyncio.create_task(bridge.run())
    _emit({"type": "fleet_reloaded", "accounts": list(new.accounts), "mode": bridge.mode})
    return {"ok": True, "accounts": list(new.accounts), "mode": bridge.mode}


@app.post("/api/fleet/kill")
async def kill(req: KillReq):
    """Emergency kill switch: flatten and halt one account, or the whole fleet."""
    ids = sentinel.kill(req.account_id)
    flattened = [r for aid in ids if (r := await bridge.flatten(aid, SYMBOL, price=feed.last))]
    _emit({"type": "kill_switch", "accounts": ids, "flattened": len(flattened)})
    return {"halted": ids, "flatten_orders": flattened}


@app.post("/api/fleet/{account_id}/resume")
def resume(account_id: str):
    if account_id not in sentinel.accounts:
        raise HTTPException(404, "unknown account")
    return {"resumed": sentinel.resume(account_id), "status": sentinel.accounts[account_id].status}


@app.post("/api/fleet/{account_id}/payout")
def approve_payout(account_id: str, req: PayoutReq):
    if account_id not in sentinel.accounts:
        raise HTTPException(404, "unknown account")
    res = sentinel.approve_payout(account_id, req.amount)
    if "graduation" in res:
        _emit({"type": "graduation_alert", **res["graduation"]})
    return res


@app.post("/api/risk/validate")
def validate(req: OrderReq):
    return sentinel.validate_order(req.account_id, req.stage.upper(), req.contract_qty, req.symbol)  # type: ignore[arg-type]


# ---------------- market data ----------------
@app.get("/api/market/bars")
def bars(tf: str = "1m", limit: int = 600):
    try:
        data = feed.bars_tf(tf)[-limit:]
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"symbol": SYMBOL, "source": feed.source, "tf": tf, "bars": data, "levels": feed.session_levels(),
            "positions": [{"account": a.account_id, "qty": a.position_qty, "avg_price": a.avg_price}
                          for a in sentinel.accounts.values() if a.position_qty]}


@app.get("/api/market/dom")
def dom():
    return {"symbol": SYMBOL, "source": feed.source, "last": feed.last, **feed.book}


@app.get("/api/market/tape")
def tape(min_size: int = 1, limit: int = 200):
    return [t for t in list(feed.trades)[::-1] if t["size"] >= min_size][:limit]


# ---------------- backtest ----------------
@app.get("/api/strategies")
def strategies():
    return list_strategies()


@app.post("/api/backtest")
async def backtest(req: BacktestReq):
    try:
        return await asyncio.to_thread(run_any, BacktestConfig(**req.model_dump()))
    except (ValueError, FileNotFoundError, RuntimeError) as e:  # adapter / data / MT5 errors -> readable 400
        raise HTTPException(400, f"{type(e).__name__}: {e}")


def _resolve(script: str) -> str:
    p = strategy_path(script)
    return str(p) if p else script


@app.post("/api/strategies/inspect")
def inspect_script(body: dict):
    """Show how a script will be adapted (no backtest run)."""
    try:
        return adapt(_resolve(body["script"]), body.get("params")).describe()
    except (AdapterError, KeyError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/mt5/status")
async def mt5_status():
    return await asyncio.to_thread(mt5_data.status)


@app.post("/api/forward/start")
async def forward_start(req: ForwardReq):
    try:
        return await forward.start(_resolve(req.script), req.source, req.symbol, req.timeframe, req.lot_size_micros, params=req.params)
    except (AdapterError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/forward/stop")
async def forward_stop():
    return await forward.stop()


@app.get("/api/forward/status")
def forward_status():
    return forward.status()


# ---------------- layouts ----------------
@app.get("/api/layouts")
def get_layouts():
    return layouts.get_all()


@app.post("/api/layouts")
def save_layout(req: LayoutReq):
    try:
        res = layouts.save(req.name, req.widgets, req.activate, req.source)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _emit({"type": "layout_saved", "name": res["name"], "activate": req.activate, "source": req.source})
    return res


@app.post("/api/layouts/{name}/activate")
def activate_layout(name: str):
    try:
        layouts.set_active(name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"active": name}


@app.delete("/api/layouts/{name}")
def delete_layout(name: str):
    return {"deleted": layouts.delete(name)}


@app.post("/api/agent/tool_event")
def tool_event(body: dict):
    """MCP server reports each tool call here so the UI can show agent activity."""
    _emit({"type": "mcp_tool", **body})
    return {"ok": True}


# ---------------- containers ----------------
@app.get("/api/containers")
def containers():
    return docker_mgr.list() if docker_mgr.available() else []


@app.post("/api/containers")
def spawn(req: SpawnReq):
    if not docker_mgr.available():
        raise HTTPException(503, "Docker engine not reachable")
    return docker_mgr.spawn(**req.model_dump())


@app.post("/api/containers/{cid}/exec")
def exec_cmd(cid: str, req: ExecReq):
    return docker_mgr.exec(cid, req.command)


@app.delete("/api/containers/{cid}")
def remove(cid: str):
    return {"removed": docker_mgr.remove(cid)}


@app.websocket("/ws/containers/{cid}")
async def term(ws: WebSocket, cid: str):
    """Interactive TTY shell for xterm.js: raw bytes both directions."""
    await ws.accept()
    try:
        sock = await asyncio.to_thread(docker_mgr.attach_shell, cid)
    except Exception as e:
        await ws.send_text(f"\r\n[error] {e}\r\n")
        await ws.close()
        return
    raw = sock._sock
    raw.setblocking(False)
    loop = asyncio.get_running_loop()

    async def pump_out():
        while True:
            data = await loop.sock_recv(raw, 4096)
            if not data:
                break
            await ws.send_bytes(data)

    out = asyncio.create_task(pump_out())
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes") or (msg.get("text") or "").encode()
            await loop.sock_sendall(raw, data)
    except WebSocketDisconnect:
        pass
    finally:
        out.cancel()
        raw.close()


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    subscribers.add(q)
    try:
        while True:
            await ws.send_json(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        subscribers.discard(q)


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("BACKEND_PORT", "5050")))


if __name__ == "__main__":
    main()
