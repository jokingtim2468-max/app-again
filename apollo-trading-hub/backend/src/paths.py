"""Where Apollo keeps user data.

Installed app: the desktop shell sets APOLLO_DATA_DIR (e.g. %APPDATA%/Apollo Trading), so config, state, logs and
strategies live in the user's profile and survive updates/reinstalls. Without it (dev / repo checkout) everything
stays in the repo as before. Bundled defaults are copied into the data dir on first run.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]      # apollo-trading-hub/
BACKEND = APP_ROOT / "backend"
_env = os.getenv("APOLLO_DATA_DIR")
DATA_DIR = Path(_env) if _env else None


def data_path(*parts: str, default: Path) -> Path:
    return DATA_DIR.joinpath(*parts) if DATA_DIR else default


CONFIG_DIR = data_path("config", default=BACKEND / "config")
STATE_DIR = data_path("state", default=BACKEND / "state")
STRATEGY_DIR = data_path("strategies", default=APP_ROOT / "strategies")


def ensure_data_dir() -> None:
    """First run of the installed app: seed the data folder from the bundled defaults (never overwrites)."""
    if not DATA_DIR:
        return
    for d in (CONFIG_DIR, STATE_DIR, STRATEGY_DIR, DATA_DIR / "logs"):
        d.mkdir(parents=True, exist_ok=True)
    if not (CONFIG_DIR / "fleet.json").exists():
        shutil.copy2(BACKEND / "config" / "fleet.json", CONFIG_DIR / "fleet.json")
    for f in (APP_ROOT / "strategies").glob("*"):
        if f.is_file() and not (STRATEGY_DIR / f.name).exists():
            shutil.copy2(f, STRATEGY_DIR / f.name)


ensure_data_dir()
