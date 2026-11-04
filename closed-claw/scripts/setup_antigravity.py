#!/usr/bin/env python3
"""Register Apollo Trading MCP in Google Antigravity: <workspace>/.agents/mcp_config.json."""
import argparse
from pathlib import Path

from _common import ROOT, check_port, merge_server, python_exe

ap = argparse.ArgumentParser()
ap.add_argument("--workspace", default=str(ROOT), help="Antigravity workspace root (default: closed-claw/)")
ap.add_argument("--literal-cwd", action="store_true", help="write absolute cwd instead of ${workspaceFolder}")
a = ap.parse_args()

check_port()
ws = Path(a.workspace).resolve()
cwd = str(ROOT / "mcp-server") if a.literal_cwd or ws != ROOT else "${workspaceFolder}/mcp-server"
merge_server(ws / ".agents" / "mcp_config.json", {
    "command": python_exe() if a.literal_cwd else "python",
    "args": ["-m", "src.server"],
    "cwd": cwd,
    "env": {"MCP_PORT": "54981", "BACKEND_API_URL": "http://localhost:5050"},
})
print("Reload the Antigravity window to pick up the server.")
