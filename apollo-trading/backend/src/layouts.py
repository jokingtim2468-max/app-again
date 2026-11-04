"""Workspace layout persistence: ~/.apollo-trading/layouts.json (shared by Electron UI, API and MCP)."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

LAYOUT_FILE = Path(os.getenv("APOLLO_LAYOUT_FILE", Path.home() / ".apollo-trading" / "layouts.json"))
WIDGET_TYPES = {"widget-chart", "widget-dom", "widget-fleet", "widget-tape", "widget-backtest", "widget-terminal"}
_lock = threading.Lock()


def _w(i, t, x, y, w, h, settings=None):
    return {"i": i, "type": t, "x": x, "y": y, "w": w, "h": h, "settings": settings or {}}


PRESETS = {
    "Execution Focus": [
        _w("chart-1", "widget-chart", 0, 0, 8, 14, {"timeframe": "1m"}),
        _w("dom-1", "widget-dom", 8, 0, 4, 14),
        _w("fleet-1", "widget-fleet", 0, 14, 12, 7, {"compact": True}),
    ],
    "Risk Command": [
        _w("fleet-1", "widget-fleet", 0, 0, 12, 12, {"compact": False}),
        _w("tape-1", "widget-tape", 0, 12, 6, 9, {"min_size": 10}),
        _w("chart-1", "widget-chart", 6, 12, 6, 9, {"timeframe": "5m"}),
    ],
    "Quant Lab": [
        _w("chart-1", "widget-chart", 0, 0, 6, 10, {"timeframe": "1m"}),
        _w("chart-2", "widget-chart", 6, 0, 6, 10, {"timeframe": "15m"}),
        _w("backtest-1", "widget-backtest", 0, 10, 7, 12),
        _w("term-1", "widget-terminal", 7, 10, 5, 12),
    ],
}


def validate(layout: list[dict]) -> list[dict]:
    if not isinstance(layout, list) or not layout:
        raise ValueError("layout must be a non-empty list of widgets")
    seen, out = set(), []
    for item in layout:
        t = item.get("type")
        if t not in WIDGET_TYPES:
            raise ValueError(f"unknown widget type {t!r}; valid: {sorted(WIDGET_TYPES)}")
        i = str(item.get("i") or f"{t.split('-')[1]}-{len(out) + 1}")
        if i in seen:
            raise ValueError(f"duplicate widget id {i}")
        seen.add(i)
        x, y, w, h = (int(item.get(k, d)) for k, d in (("x", 0), ("y", 0), ("w", 6), ("h", 8)))
        if not (0 <= x < 12 and 1 <= w <= 12 and x + w <= 12 and y >= 0 and 2 <= h <= 60):
            raise ValueError(f"widget {i} out of 12-column grid bounds (x={x}, w={w}, h={h})")
        out.append({"i": i, "type": t, "x": x, "y": y, "w": w, "h": h, "settings": item.get("settings") or {}})
    return out


def _read() -> dict:
    if not LAYOUT_FILE.exists():
        return {"active": "Execution Focus", "layouts": {}}
    return json.loads(LAYOUT_FILE.read_text())


def _write(data: dict) -> None:
    LAYOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LAYOUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(LAYOUT_FILE)


def get_all() -> dict:
    with _lock:
        data = _read()
    return {"active": data.get("active"), "presets": PRESETS, "layouts": data.get("layouts", {})}


def save(name: str, layout: list[dict], activate: bool = False, source: str = "ui") -> dict:
    name = name.strip()
    if not name or len(name) > 64:
        raise ValueError("layout name must be 1-64 chars")
    clean = validate(layout)
    with _lock:
        data = _read()
        data.setdefault("layouts", {})[name] = {
            "widgets": clean, "updated_at": datetime.now(timezone.utc).isoformat(), "source": source}
        if activate:
            data["active"] = name
        _write(data)
    return {"name": name, "widgets": clean, "active": activate}


def delete(name: str) -> bool:
    with _lock:
        data = _read()
        gone = data.get("layouts", {}).pop(name, None) is not None
        if data.get("active") == name:
            data["active"] = "Execution Focus"
        _write(data)
    return gone


def set_active(name: str) -> None:
    with _lock:
        data = _read()
        if name not in PRESETS and name not in data.get("layouts", {}):
            raise ValueError(f"no layout named {name}")
        data["active"] = name
        _write(data)
