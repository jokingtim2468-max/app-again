#!/usr/bin/env python3
"""Register Apollo Trading MCP in Claude Desktop (claude_desktop_config.json) and optionally Claude Code."""
import argparse
import os
import platform
import shutil
import subprocess
from pathlib import Path

from _common import MCP_DIR, check_port, merge_server, python_exe


def desktop_config() -> Path:
    s = platform.system()
    if s == "Windows":
        return Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    if s == "Darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    return Path.home() / ".config/Claude/claude_desktop_config.json"


ap = argparse.ArgumentParser()
ap.add_argument("--claude-code", action="store_true", help="also run `claude mcp add` for Claude Code")
a = ap.parse_args()

check_port()
server = (MCP_DIR / "src" / "server.py").as_posix()
merge_server(desktop_config(), {
    "command": python_exe(),
    "args": [server],
    "env": {"MCP_PORT": "54981", "PYTHONPATH": MCP_DIR.as_posix(), "BACKEND_API_URL": "http://localhost:5050"},
})
if a.claude_code:
    if shutil.which("claude"):
        subprocess.run(["claude", "mcp", "add", "apollo-trading", "--scope", "user",
                        "-e", f"PYTHONPATH={MCP_DIR.as_posix()}", "--", python_exe(), server], check=False)
    else:
        print("[warn] `claude` CLI not on PATH; skipped Claude Code registration")
print("Restart Claude Desktop to load the server.")
