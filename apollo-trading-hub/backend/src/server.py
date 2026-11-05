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
    if "bots" in globals():
        bots.on_event(e)
    for q in list(subscribers):
        if q.full():
            q.get_nowait()
        q.put_nowait(e)


sentinel.on_event = _emit
from .journal import Journal  # noqa: E402

journal = Journal()
sentinel.journal = journal


def sync_costs(sen) -> None:
    """Log each account's purchase cost once (eval fee) so profit reports net it out."""
    logged = {(c["account"], c["kind"]) for c in journal.query("costs", limit=100000)}
    for spec in sen.specs:
        if spec.get("cost") and (spec["id"], "purchase") not in logged:
            journal.cost(spec["id"], spec["firm"], "purchase", float(spec["cost"]), f"{spec['firm']} {spec['plan']} {spec['size']}")


sync_costs(sentinel)
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


_payout_ready: set[str] = set()


async def notify(text: str, data: dict) -> None:
    """Optional push to your phone: APOLLO_NOTIFY_WEBHOOK = Discord/Slack webhook or https://ntfy.sh/<topic>."""
    url = os.getenv("APOLLO_NOTIFY_WEBHOOK")
    if not url:
        return
    import httpx
    body = {"content": text} if "discord" in url else {"text": text} if "slack" in url else None
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await (c.post(url, json=body) if body else c.post(url, content=text.encode()))
    except httpx.HTTPError as e:
        _emit({"type": "notify_error", "error": str(e)})


async def balance_snapshots():
    while True:
        await asyncio.sleep(300)
        for a in list(sentinel.accounts.values()):
            await asyncio.to_thread(journal.balance, a)


async def payout_watch():
    """Semi-auto payouts: announce each account the moment it becomes eligible (once per eligibility window)."""
    while True:
        for aid in list(sentinel.accounts):
            e = sentinel.payout_eligibility(aid)
            if e.get("eligible") and aid not in _payout_ready:
                _payout_ready.add(aid)
                msg = (f"💰 Payout ready: {aid} ({e.get('firm')}) request ${e['max_request']:,.0f} "
                       f"(≈${e['net_to_you']:,.0f} to you) → {e.get('dashboard_url') or 'firm dashboard'}")
                _emit({"type": "payout_ready", **e})
                await notify(msg, e)
            elif not e.get("eligible"):
                _payout_ready.discard(aid)
        await asyncio.sleep(60)


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
        for aid in list(sentinel.pending_flatten):  # just parked (firm funded cap full): flatten now
            sentinel.pending_flatten.discard(aid)
            try:
                await bridge.flatten(aid, SYMBOL, price=feed.last)
            except Exception as e:
                _emit({"type": "route_error", "account": aid, "error": f"flatten on park failed: {e}"})
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
    tasks = [asyncio.create_task(c) for c in (eod_scheduler(), autosave(), feed.run(), mark_to_market(), payout_watch(), balance_snapshots())]
    await bots.start()
    yield
    await bots.stop()
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


@app.get("/api/docker/status")
async def docker_status():
    return {"docker": await asyncio.to_thread(docker_mgr.available)}


@app.get("/api/health")
async def health():
    return {"ok": True, "mode": bridge.mode, "feed": feed.source}  # must stay instant: the desktop app polls it


# ---------------- fleet & risk ----------------
@app.get("/api/fleet/status")
def fleet_status():
    snap = sentinel.snapshot()
    for aid in snap:
        snap[aid]["payout"] = sentinel.payout_eligibility(aid)
        if snap[aid]["parked"]:
            q = sentinel.queue(snap[aid]["firm"])
            snap[aid]["queue_position"] = q.index(aid) + 1 if aid in q else None
    return {"name": sentinel.config.get("name", "fleet"), "mode": bridge.mode, "firms": sentinel.firm_summary(),
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


@app.get("/api/fleet/summary")
def fleet_summary():
    """Per firm: cap, funded/parked/failed/passed counts, queue, cost vs payouts."""
    return sentinel.firm_summary()


@app.get("/api/fleet/ledger")
def fleet_ledger(account: str | None = None, firm: str | None = None, limit: int = 500):
    rows = [e for e in sentinel.ledger if (not account or e["account"] == account) and (not firm or e.get("firm") == firm)]
    return rows[-limit:][::-1]


@app.post("/api/fleet/{account_id}/close")
def close_account(account_id: str, body: dict | None = None):
    """Mark an account closed (e.g. cashout completed / account cancelled): frees its funded slot."""
    if account_id not in sentinel.accounts:
        raise HTTPException(404, "unknown account")
    if sentinel.accounts[account_id].position_qty:
        raise HTTPException(409, "flatten the account first")
    sentinel.close_account(account_id, (body or {}).get("reason", "closed by operator"))
    return {"ok": True, "summary": sentinel.firm_summary().get(sentinel.accounts[account_id].firm)}


@app.get("/api/payouts")
def payouts_overview():
    """Every account: can it request now, exact amount, net after split, blockers, and monthly ceiling."""
    from .trading.payouts import monthly_ceiling
    rows, firms_tot = [], {}
    for aid, a in sentinel.accounts.items():
        e = sentinel.payout_eligibility(aid)
        m = monthly_ceiling(a) if a.stage == "FUNDED" and a.status != "CLOSED" else {"known": False}
        rows.append({**e, "stage": a.stage, "status": a.status, "balance": round(a.closed_balance, 2),
                     "paid_out": round(a.total_paid_out, 2), "monthly": m})
        f = firms_tot.setdefault(a.firm, {"firm_name": a.rules.get("firm_name"), "ready_now_gross": 0.0, "ready_now_net": 0.0,
                                          "month_ceiling_net": 0.0, "uncapped_accounts": 0, "paid_out": 0.0})
        f["paid_out"] += a.total_paid_out
        if e.get("eligible"):
            f["ready_now_gross"] += e["max_request"]; f["ready_now_net"] += e["net_to_you"]
        if m.get("known"):
            if m["uncapped"]:
                f["uncapped_accounts"] += 1
            else:
                f["month_ceiling_net"] += m["net_ceiling"] or 0
    tot = {k: round(sum(f[k] for f in firms_tot.values()), 2) for k in ("ready_now_gross", "ready_now_net", "month_ceiling_net", "paid_out")}
    return {"accounts": rows, "firms": firms_tot, "totals": tot}


class PayoutAmt(BaseModel):
    amount: float | None = None
    reason: str = ""


@app.post("/api/payouts/{account_id}/requested")
def payout_requested(account_id: str, req: PayoutAmt):
    if account_id not in sentinel.accounts:
        raise HTTPException(404, "unknown account")
    amt = req.amount or sentinel.payout_eligibility(account_id).get("max_request", 0)
    return sentinel.request_payout(account_id, amt)


@app.post("/api/payouts/{account_id}/paid")
def payout_paid(account_id: str, req: PayoutAmt):
    if account_id not in sentinel.accounts:
        raise HTTPException(404, "unknown account")
    a = sentinel.accounts[account_id]
    amt = req.amount or a.payout_pending
    if not amt:
        raise HTTPException(400, "no amount: pass amount or mark a request first")
    res = sentinel.approve_payout(account_id, amt)
    if "graduation" in res:
        _emit({"type": "graduation_alert", **res["graduation"]})
    _payout_ready.discard(account_id)
    return res


@app.post("/api/payouts/{account_id}/rejected")
def payout_rejected(account_id: str, req: PayoutAmt):
    sentinel.reject_payout(account_id, req.reason)
    return {"ok": True}


# ---------------- logs & reports ----------------
@app.get("/api/logs/{kind}")
def logs(kind: str, account: str | None = None, firm: str | None = None, start: str | None = None,
         end: str | None = None, limit: int = 2000):
    """kind: balances | fills | payouts | daily_pnl | costs | events"""
    try:
        return journal.query(kind, account, firm, start, end, limit)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/logs/{kind}/export.csv")
def logs_csv(kind: str, account: str | None = None, firm: str | None = None, start: str | None = None, end: str | None = None):
    from fastapi.responses import PlainTextResponse
    try:
        body = journal.csv(kind, account=account, firm=firm, start=start, end=end, limit=1_000_000)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return PlainTextResponse(body, media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="apollo-{kind}{"-" + account if account else ""}.csv"'})


@app.get("/api/reports/profit")
def profit_report(start: str | None = None, end: str | None = None):
    rep = journal.profit_report(start, end)
    rep["live"] = {aid: {"firm": a.firm, "balance": round(a.closed_balance, 2), "equity": round(a.equity, 2),
                         "profit_on_account": round(a.closed_balance - a.starting_balance, 2), "paid_out": a.total_paid_out,
                         "net_received": a.total_net_received, "stage": a.stage, "status": a.status}
                   for aid, a in sentinel.accounts.items()}
    return rep


@app.get("/api/reports/outcomes")
def outcomes(start: str | None = None, end: str | None = None):
    """How many evals passed / hit target / blew up, funded blows, daily-limit hits, payouts, ROI: per firm + fleet."""
    rep = journal.outcome_stats(sentinel.specs, start, end)
    live = {}
    for a in sentinel.accounts.values():
        b = live.setdefault(a.firm, {"evals_trading": 0, "funded_active": 0, "parked_now": 0, "blown_now": 0})
        b["evals_trading"] += a.stage == "EVALUATION" and not a.liquidated and not a.parked and a.status != "CLOSED"
        b["funded_active"] += a.stage == "FUNDED" and not a.liquidated and a.status != "CLOSED"
        b["parked_now"] += a.parked
        b["blown_now"] += a.liquidated
    rep["now"] = live
    return rep


class CostReq(BaseModel):
    account: str
    kind: str = "reset"
    amount: float
    note: str = ""


@app.post("/api/logs/costs")
def add_cost(req: CostReq):
    """Record any spend: resets, activation fees, data/platform fees, so real profit is accurate."""
    firm = sentinel.accounts[req.account].firm if req.account in sentinel.accounts else "other"
    journal.cost(req.account, firm, req.kind, req.amount, req.note)
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
        new = RiskSentinel(cfg, on_event=_emit)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, f"invalid fleet: {e}")
    for aid, a in new.accounts.items():  # keep risk state of accounts that didn't change firm/size
        old = sentinel.accounts.get(aid)
        if old and (old.firm, old.plan, old.size) == (a.firm, a.plan, a.size):
            for k in ("closed_balance", "day_start_balance", "mll", "mll_locked", "peak_equity", "qualifying_days",
                      "payouts_approved", "total_paid_out", "halted", "liquidated", "status", "best_day_profit", "last_eod", "stage",
                      "parked", "parked_at", "passed_at", "failed_at"):
                setattr(a, k, getattr(old, k))
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(CONFIG_PATH)
    if bridge_task:
        bridge_task.cancel()
    new.ledger = sentinel.ledger
    new.journal = journal
    sync_costs(new)
    for firm in {a.firm for a in new.accounts.values()}:  # caps may have changed: re-check queue + parking
        new.rebalance(firm)
        for aid, a in new.accounts.items():
            if a.firm == firm:
                new.check_parking(aid)
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


# ---------------- Telegram / Discord bots ----------------
from .bots import settings as bot_settings  # noqa: E402
from .bots.manager import BotManager  # noqa: E402


async def _bot_kill(account):
    return await kill(KillReq(account_id=account))


async def _bot_flatten():
    return await flatten_all()


bots = BotManager({
    "status": lambda: fleet_status(),
    "payouts": lambda: payouts_overview(),
    "outcomes": lambda: outcomes(),
    "profit": lambda: profit_report(),
    "kill": _bot_kill,
    "flatten": _bot_flatten,
    "resume": lambda a: resume(a),
    "requested": lambda a, amt=None: payout_requested(a, PayoutAmt(amount=amt)),
    "paid": lambda a, amt=None: payout_paid(a, PayoutAmt(amount=amt)),
    "rejected": lambda a: payout_rejected(a, PayoutAmt()),
})


@app.get("/api/settings/bots")
def get_bot_settings():
    cfg = bot_settings.load()
    return {"settings": bot_settings.mask(cfg), "status": bots.status(), "links": cfg.get("links", []),
            "notify_kinds": bot_settings.NOTIFY_KINDS, "commands": bots.router.menu(),
            "variables": sorted(bots.engine.variables())}


@app.post("/api/settings/bots/code")
async def bot_code(body: dict | None = None):
    """Verification code to type in Discord/Telegram as /verify CODE (valid 10 minutes)."""
    if not (bots.bots or bots.relay):
        raise HTTPException(409, "start a bot first: enable your bot (own token) or set the relay URL, then Save")
    return await bots.new_code(bool((body or {}).get("grant_control")))


@app.get("/api/settings/bots/links/recent")
def recent_links():
    return bots.recent_links[-5:]


@app.get("/api/settings/bots/channels")
async def bot_channels(guild_id: str):
    try:
        return await bots.guild_channels(guild_id)
    except Exception as e:
        raise HTTPException(502, f"couldn't list channels: {e}")


@app.put("/api/settings/bots/links/{link_id}")
def update_link(link_id: str, body: dict):
    """Set where alerts go for a linked server/chat: {destinations: {channel_or_chat_id: {name, kinds: [...]}}}."""
    cfg = bot_settings.load()
    for l in cfg.get("links", []):
        if l["id"] == link_id:
            dest = body.get("destinations") or {}
            bad = [k for d in dest.values() for k in d.get("kinds", []) if k not in bot_settings.NOTIFY_KINDS]
            if bad:
                raise HTTPException(400, f"unknown alert kinds {bad}")
            l["destinations"] = dest
            bot_settings.save(cfg)
            return l
    raise HTTPException(404, "link not found")


@app.delete("/api/settings/bots/links/{link_id}")
async def delete_link(link_id: str):
    await bots.unlink(link_id)
    return {"ok": True}


@app.put("/api/settings/bots")
async def put_bot_settings(body: dict):
    """Save settings and relaunch the bots (re-registers custom commands in Telegram's menu / Discord slash list)."""
    body.pop("links", None)  # links only change via /verify and the link endpoints (avoids overwriting a fresh link)
    try:
        bot_settings.save(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await bots.start()
    await asyncio.sleep(2)
    return get_bot_settings()


@app.post("/api/settings/bots/test")
async def test_bots(body: dict | None = None):
    """Run a command locally (preview) and/or send a test alert to every enabled bot."""
    from .bots.commands import Ctx
    cmd = (body or {}).get("command")
    out = {"preview": await bots.engine.run(cmd, Ctx("preview", "app", True))} if cmd else {}
    if (body or {}).get("send_alert"):
        out["sent"] = await bots.broadcast("startup", "✅ Apollo test alert: you're connected.")
    return {**out, "status": bots.status()}


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("BACKEND_PORT", "5050")))


if __name__ == "__main__":
    main()
