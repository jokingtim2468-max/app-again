# Shared repo rules (Claude Code + Google Antigravity) — Apollo Trading

- Project lives in `apollo-trading/`. Antigravity syncs via `apollo-trading/scripts/antigravity_wsl_sync.ps1` (Windows) or `.sh` (inside WSL).
- Branches: Claude -> `claude/<topic>`, Antigravity -> `antigravity/<topic>`. Never push to `main` directly; merge via PR.
- Pull before starting, `git pull --ff-only`; keep commits small and scoped to one layer (backend / mcp-server / frontend / cloud-training).
- Never commit secrets: Tradovate creds live only in env vars (`TRADOVATE_*`). `.env` is git-ignored.
- Trading defaults to PAPER. Only a human sets `APOLLO_LIVE=1`.
- Ports: backend 5050, MCP SSE 54981, Vite 5173. No AI/LLM code in this repo. All bound to 127.0.0.1.
- Before pushing: `python -m pytest apollo-trading/tests` and `cd apollo-trading/frontend && npm run build`.
