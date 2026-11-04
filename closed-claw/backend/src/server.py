"""Closed Claw FastAPI service on 127.0.0.1:5050."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .ai import ollama_client
from .containers.docker_manager import DockerManager
from .trading.backtester import BacktestConfig, list_strategies, run_backtest
from .trading.risk_sentinel import ET, RiskSentinel
from .trading.tradovate_bridge import Fill, TradovateBridge

sentinel = RiskSentinel()
sentinel.load()  # resume MLL / payouts / qualifying days across restarts
events: asyncio.Queue = asyncio.Queue(maxsize=1000)


def _emit(e: dict) -> None:
    e.setdefault("ts", datetime.now(ET).isoformat())
    if events.full():
        events.get_nowait()
    events.put_nowait(e)


bridge = TradovateBridge(sentinel, on_event=_emit)
docker_mgr = DockerManager()


async def autosave():
    while True:
        await asyncio.sleep(5)
        await asyncio.to_thread(sentinel.save)


async def eod_scheduler():
    """Roll the MLL once per day at 17:00 ET (EOD drawdown)."""
    while True:
        now = datetime.now(ET)
        if RiskSentinel.is_eod(now):
            for aid in sentinel.accounts:
                if sentinel.accounts[aid].last_eod != now.date().isoformat():
                    sentinel.end_of_day(aid, now.date().isoformat())
                    _emit({"type": "eod", "account": aid, "mll": sentinel.accounts[aid].mll})
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(eod_scheduler()), asyncio.create_task(bridge.run()), asyncio.create_task(autosave())]
    yield
    sentinel.save()
    for t in tasks:
        t.cancel()


app = FastAPI(title="Closed Claw", lifespan=lifespan)
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


class OrderReq(BaseModel):
    account_id: str
    stage: str
    contract_qty: int
    symbol: str = "MGC"


class NewsReq(BaseModel):
    headline: str
    event_name: str
    consensus_forecast: str
    actual_print: str


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
    symbol: str = "MGCZ6"


class PayoutReq(BaseModel):
    amount: float


@app.get("/api/health")
async def health():
    return {"ok": True, "mode": bridge.mode, "ollama": await ollama_client.health(),
            "docker": docker_mgr.available()}


@app.get("/api/fleet/status")
def fleet_status():
    snap = sentinel.snapshot()
    for aid in snap:
        snap[aid]["payout"] = sentinel.payout_eligibility(aid)
    return {"firm": sentinel.config["firm"], "tier": sentinel.config["tier"], "mode": bridge.mode,
            "master": sentinel.config["master_account"], "accounts": snap}


@app.post("/api/fleet/simulate_fill")
async def simulate_fill(req: FillReq):
    if req.action not in ("Buy", "Sell"):
        raise HTTPException(400, "action must be Buy or Sell")
    master = sentinel.config["master_account"]
    await bridge.place_market(master, req.action, req.symbol, req.qty)
    return {"copies": await bridge.mirror(Fill(master, req.action, req.symbol, req.qty))}


@app.post("/api/fleet/{account_id}/payout")
def approve_payout(account_id: str, req: PayoutReq):
    if account_id not in sentinel.accounts:
        raise HTTPException(404, "unknown account")
    res = sentinel.approve_payout(account_id, req.amount)
    if "graduation" in res:
        _emit({"type": "graduation_alert", **res["graduation"]})
    return res


@app.get("/api/strategies")
def strategies():
    return list_strategies()


@app.post("/api/agent/tool_event")
def tool_event(body: dict):
    """MCP server reports each tool call here so the UI chat drawer can render it."""
    _emit({"type": "mcp_tool", **body})
    return {"ok": True}


@app.post("/api/risk/validate")
def validate(req: OrderReq):
    return sentinel.validate_order(req.account_id, req.stage.upper(), req.contract_qty, req.symbol)  # type: ignore[arg-type]


@app.post("/api/backtest")
async def backtest(req: BacktestReq):
    return await asyncio.to_thread(run_backtest, BacktestConfig(**req.model_dump()))


@app.post("/api/news/predict")
async def news(req: NewsReq):
    try:
        return await ollama_client.predict(req.headline, req.event_name, req.consensus_forecast, req.actual_print)
    except Exception as e:  # surface model/connection errors to the caller
        raise HTTPException(502, f"news model error: {e}")


@app.post("/api/chat")
async def chat(body: dict):
    async def gen():
        async for tok in ollama_client.chat_stream(body.get("messages", []), body.get("model")):
            yield f"data: {json.dumps({'token': tok})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/containers")
def containers():
    return docker_mgr.list()


@app.post("/api/containers")
def spawn(req: SpawnReq):
    return docker_mgr.spawn(**req.model_dump())


@app.post("/api/containers/{cid}/exec")
def exec_cmd(cid: str, req: ExecReq):
    return docker_mgr.exec(cid, req.command)


@app.delete("/api/containers/{cid}")
def remove(cid: str):
    return {"removed": docker_mgr.remove(cid)}


@app.websocket("/ws/containers/{cid}")
async def term(ws: WebSocket, cid: str):
    await ws.accept()
    try:
        while True:
            cmd = await ws.receive_text()
            for chunk in await asyncio.to_thread(lambda: list(docker_mgr.stream(cid, cmd))):
                await ws.send_text(chunk)
            await ws.send_text("\u0004")
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json(await events.get())
    except WebSocketDisconnect:
        pass


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("BACKEND_PORT", "5050")))


if __name__ == "__main__":
    main()
