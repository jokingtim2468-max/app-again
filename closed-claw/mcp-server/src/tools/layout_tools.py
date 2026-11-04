import httpx

from .. import config  # noqa: F401  (adds repo root to sys.path)
from backend.src import layouts


def save_custom_layout(layout_name: str, layout_json: list[dict] | dict, activate: bool = True) -> dict:
    """Prefer the backend (so the open UI hot-reloads); fall back to writing the shared file directly."""
    widgets = layout_json.get("widgets") if isinstance(layout_json, dict) else layout_json
    layouts.validate(widgets)  # fail fast with a clear message
    body = {"name": layout_name, "widgets": widgets, "activate": activate, "source": "mcp"}
    try:
        r = httpx.post(f"{config.BACKEND_API_URL}/api/layouts", json=body, timeout=5)
        if r.status_code == 400:
            raise ValueError(r.json().get("detail"))
        r.raise_for_status()
        return {"via": "backend", **r.json()}
    except httpx.HTTPError:
        return {"via": "file", **layouts.save(layout_name, widgets, activate, source="mcp")}


def get_workspace_layouts() -> dict:
    data = layouts.get_all()
    data["widget_types"] = sorted(layouts.WIDGET_TYPES)
    data["grid"] = {"columns": 12, "row_height_px": 30, "rules": "0<=x, x+w<=12, 2<=h<=60, unique i"}
    return data
