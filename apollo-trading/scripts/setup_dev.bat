@echo off
REM Apollo Trading dev bootstrap (Windows). Requires Python 3.11+, Node 20+, Docker Desktop (for sandbox terminal).
setlocal
cd /d %~dp0\..
where python >nul 2>nul || (echo Python not found & exit /b 1)
where npm >nul 2>nul || (echo Node/npm not found & exit /b 1)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r backend\requirements.txt -r mcp-server\requirements.txt || exit /b 1
REM MetaTrader5 is installed by requirements on Windows. For Antigravity in WSL also run: python scripts\mt5_bridge.py
pushd frontend && call npm install && popd
python scripts\setup_antigravity.py
python scripts\setup_claude.py
echo.
echo Start backend:  .venv\Scripts\python -m backend.src.server
echo Start MCP SSE:  cd mcp-server ^&^& ..\.venv\Scripts\python -m src.server --sse
echo Start UI:       cd frontend ^&^& npm run electron:dev
endlocal
