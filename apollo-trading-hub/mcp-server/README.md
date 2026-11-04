# Apollo Trading MCP Server

Deterministic tools (no AI): `run_backtest`, `list_strategies`, `get_fleet_status`,
`validate_order_risk`, `save_custom_layout`, `get_workspace_layouts`.

```bash
pip install -r requirements.txt -r ../backend/requirements.txt
python -m src.server          # stdio
python -m src.server --sse    # SSE at http://127.0.0.1:54981/sse
```
Register: `python ../scripts/setup_antigravity.py` / `python ../scripts/setup_claude.py`.
Layouts are shared through `~/.apollo-trading-hub/layouts.json`; with the backend running, a saved layout hot-swaps into the open UI.
