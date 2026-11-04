from .base import BrokerError, Connector  # noqa: F401

BROKERS = {
    "paper": ("paper", "PaperConnector", "Local paper fills at the feed price"),
    "tradovate": ("tradovate", "TradovateConnector", "Tradovate API: Lucid, Apex, MFFU, Tradeify, TPT, Topstep (Tradovate)"),
    "projectx": ("projectx", "ProjectXConnector", "ProjectX Gateway: TopstepX and other ProjectX prop platforms"),
    "ninjatrader": ("ninjatrader", "NinjaTraderConnector", "NinjaTrader 8 ATI: anything NT connects to (Rithmic, CQG, Tradovate, IB, Kinetick)"),
    "rithmic": ("ninjatrader", "NinjaTraderConnector", "Rithmic accounts, routed through NinjaTrader 8 (R|Trader API needs Rithmic conformance)"),
    "mt5": ("mt5", "MT5Connector", "MetaTrader 5: FTMO, FundedNext, The5ers, any MT5 broker (Windows)"),
    "ibkr": ("ibkr", "IBKRConnector", "Interactive Brokers TWS / IB Gateway"),
}


def make_connector(broker: str, live: bool, suffix: str = "") -> Connector:
    import importlib
    if broker not in BROKERS:
        raise BrokerError(f"unknown broker {broker!r}; supported: {sorted(BROKERS)}")
    mod, cls, _ = BROKERS[broker]
    c = getattr(importlib.import_module(f"{__name__}.{mod}"), cls)
    return c(live) if mod == "paper" else c(live, suffix) if mod in ("tradovate", "projectx") else c(live)
