# Closed Claw

Local-first AI workspace + LucidFlex 150K MGC fleet engine.

| Layer | Path | Port |
|---|---|---|
| Electron + React UI (`#090A0F` wireframe, 3-panel) | `frontend/` | 5173 (dev) |
| FastAPI backend (risk, copy-trader, backtester, Docker, Ollama) | `backend/` | 5050 |
| MCP server (stdio + SSE) | `mcp-server/` | 54981 |
| Ollama `news-predictor-3b` | `cloud-training/` | 11434 |

## Quick start
```bash
bash scripts/setup_dev.sh            # Linux/WSL   (Windows: scripts\setup_dev.bat)
python -m backend.src.server         # backend
cd mcp-server && python -m src.server --sse
cd frontend && npm run electron:dev  # or: npm run dist:win  -> NSIS installer w/ auto-update
python -m pytest tests
```
Antigravity (WSL): `powershell -ExecutionPolicy Bypass -File scripts\antigravity_wsl_sync.ps1 -Branch <branch>`.

## Safety defaults
- **PAPER mode by default.** No broker orders unless `CLAW_LIVE=1`; `TRADOVATE_ENV=demo` is the default target even then.
- Every slave order goes through `RiskSentinel.validate_order` (funded tier clamp, halted/liquidated block).
- MLL trails **only** at the 17:00 ET close and locks at 150,100 once the closed balance reaches 154,600.
- Payout #5 halts the account and emits the 50% cashout election ($2,025 net) + a 24h operator alert.
- Backtests use **synthetic** seeded ticks: they validate rule logic, not edge. On coin-flip data
  all bundled strategies lose to spread + slippage + commissions — feed real tick data before trusting any strategy.
- Verify current Lucid rules (copy-trading across accounts, scaling tiers, payout policy) against your account agreement; the numbers in `fleet.json` are what you specified, not fetched from the firm.
