import httpx

from ..config import BACKEND_API_URL


def validate_order_risk(account_id: str, stage: str, contract_qty: int, symbol: str = "MGC") -> dict:
    body = {"account_id": account_id, "stage": stage.upper(), "contract_qty": contract_qty, "symbol": symbol}
    try:
        r = httpx.post(f"{BACKEND_API_URL}/api/risk/validate", json=body, timeout=5)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        from backend.src.trading.risk_sentinel import RiskSentinel
        return RiskSentinel().validate_order(account_id, stage.upper(), contract_qty, symbol)  # type: ignore[arg-type]
