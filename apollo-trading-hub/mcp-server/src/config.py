import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # apollo-trading-hub/
BACKEND_DIR = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # backend engines importable as backend.src.*

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "54981"))
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:5050")
FLEET_CONFIG = BACKEND_DIR / "config" / "fleet.json"
