import json
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_DIR = ROOT / "mcp-server"
PORT = 54981


def port_free(port: int = PORT, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def check_port() -> None:
    if port_free():
        print(f"[ok] port {PORT} is free on 127.0.0.1")
    else:
        print(f"[warn] port {PORT} is in use (already-running Apollo SSE server, or a conflict). "
              f"Set MCP_PORT to another 49152-65535 port if it isn't ours.")


def python_exe() -> str:
    return sys.executable or shutil.which("python3") or shutil.which("python") or "python"


def merge_server(cfg_path: Path, entry: dict) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text() or "{}")
        except json.JSONDecodeError:
            backup = cfg_path.with_suffix(".json.bak")
            shutil.copy(cfg_path, backup)
            print(f"[warn] invalid JSON in {cfg_path}; backed up to {backup}")
    servers = data.setdefault("mcpServers", {})
    servers["apollo-trading"] = entry
    cfg_path.write_text(json.dumps(data, indent=2))
    print(f"[ok] registered apollo-trading in {cfg_path}")
