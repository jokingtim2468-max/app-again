import uuid

from .base import Connector


class PaperConnector(Connector):
    """Fills locally at the market feed's last price. Default for every account until a human enables live."""
    name = "paper"

    async def connect(self) -> None:
        self.connected = True

    @property
    def mode(self) -> str:
        return "PAPER"

    async def place_market(self, account, action, symbol, qty):
        return {"mode": "PAPER", "account": account, "action": action, "symbol": symbol, "qty": qty,
                "orderId": f"paper-{uuid.uuid4().hex[:8]}"}
