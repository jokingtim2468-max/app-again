# Apollo Trading

Local-first, modular prop-fleet execution terminal. **Zero AI / pure systematic:** every execution, risk gate,
copy-trade and backtest is deterministic and rule-based.

| Layer | Path | Port |
|---|---|---|
| Electron + React grid workspace (`#090A0F` / `#12151E` / `#212636`) | `frontend/` | 5173 dev |
| FastAPI backend: risk sentinel, Tradovate copier, market feed, backtester, layouts, Docker | `backend/` | 5050 |
| MCP server (stdio + SSE) | `mcp-server/` | 54981 |

## Run
```bash
bash scripts/setup_dev.sh                 # Linux/WSL   (Windows: scripts\setup_dev.bat)
python -m backend.src.server              # backend
cd mcp-server && python -m src.server --sse
cd frontend && npm run electron:dev       # npm run dist:win -> NSIS wizard installer + auto-update
python -m pytest tests
```

## Workspace
- Every tool is a widget: `widget-chart`, `widget-dom`, `widget-fleet`, `widget-tape`, `widget-backtest`, `widget-terminal`.
- **Builder tab** (`#/builder`): catalog → *Add to Workspace*, 12-col snap grid with collision prevention, per-widget settings (⚙),
  maximize, close, presets (*Execution Focus*, *Risk Command*, *Quant Lab*), Save / Save as / Reset / Delete, Export & Import JSON, Edit ↔ Lock.
- Layouts persist in `~/.apollo-trading/layouts.json` (override with `APOLLO_LAYOUT_FILE`). Agents write them via MCP `save_custom_layout`; the open UI hot-swaps.

## Safety
- **PAPER by default**; market data is a seeded **SIM** feed (labelled in every chart). `APOLLO_LIVE=1` switches to Tradovate (`TRADOVATE_ENV=demo` default).
- Tradovate credentials are **env vars only** (`TRADOVATE_*`), never in `fleet.json`.
- Kill switch (top bar or per account) flattens and halts routing; killed accounts can be resumed, cashout/liquidated accounts cannot.
- DOM brackets are server-side emulated: the backend watches last price and flattens the fleet at TP/SL. They do not exist at the broker,
  so if the backend stops, there is no resting stop. Keep that in mind on live.
- EOD MLL trails only at 17:00 ET; locks at 150,100 once closed balance ≥ 154,600. Payout 5 ⇒ `ELIGIBLE_FOR_CASHOUT`, routing frozen, $2,025 election + 24h alert.
- Synthetic backtests validate rules, not edge. Use a tick CSV before trusting any strategy.
