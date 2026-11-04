#!/usr/bin/env bash
# Linux/WSL bootstrap (used by Antigravity's WSL workspace)
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv && . .venv/bin/activate
pip install -U pip && pip install -r backend/requirements.txt -r mcp-server/requirements.txt
(cd frontend && npm install)
python scripts/setup_antigravity.py
echo "backend: python -m backend.src.server | mcp: (cd mcp-server && python -m src.server --sse) | ui: (cd frontend && npm run dev)"
