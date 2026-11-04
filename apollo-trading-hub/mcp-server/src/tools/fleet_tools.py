import httpx

from ..config import BACKEND_API_URL


def get_fleet_status() -> dict:
    """Live telemetry from the backend; falls back to a fresh rules-only snapshot if it's down."""
    try:
        r = httpx.get(f"{BACKEND_API_URL}/api/fleet/status", timeout=5)
        r.raise_for_status()
        return {"source": "backend", **r.json()}
    except httpx.HTTPError as e:
        from backend.src.trading.risk_sentinel import RiskSentinel
        s = RiskSentinel()
        snap = s.snapshot()
        for aid in snap:
            snap[aid]["payout"] = s.payout_eligibility(aid)
        return {"source": f"config_only (backend unreachable: {e.__class__.__name__})", "accounts": snap}
