# Closed Claw MCP Server

Tools: `run_backtest`, `get_fleet_status`, `validate_order_risk`, `query_news_model`,
`inspect_containers`, `execute_container_command`.

```bash
pip install -r requirements.txt -r ../backend/requirements.txt
python -m src.server          # stdio
python -m src.server --sse    # SSE at http://127.0.0.1:54981/sse
```
Register with hosts: `python ../scripts/setup_antigravity.py` / `python ../scripts/setup_claude.py`.
Bound to 127.0.0.1 only; nothing listens on external interfaces.
