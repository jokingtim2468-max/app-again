"""Broker, contract and project settings.

Broker: Tradovate (CME futures). Fees checked 2026-11-05 against
https://www.tradovate.com/pricing/ and Tradovate's all-in rates PDF
(TradovateAllInRates120625.pdf). Re-check before trading: fees change.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
MODELS = ROOT / "models"
NY = "America/New_York"

# Session: CME Globex metals trade Sun-Fri 18:00-17:00 ET with a 60-minute break.
# A "session date" d = the session that ends 17:00 ET on calendar day d.
SESSION_CLOSE_HOUR_ET = 17

# Prediction horizons in trading sessions.
HORIZONS: dict[str, int] = {"day": 1, "week": 5, "month": 21, "quarter": 63}
QUANTILES = (0.1, 0.5, 0.9)


@dataclass(frozen=True)
class TradovatePlan:
    name: str
    fixed_cost: str               # what the plan itself costs
    micro_commission_side: float  # $ per contract per side
    std_commission_side: float


PLANS = {
    "free": TradovatePlan("Free", "$0", 0.39, 1.29),
    "monthly": TradovatePlan("Monthly", "$99 / month", 0.29, 0.99),
    "lifetime": TradovatePlan("Lifetime", "$1,499 once", 0.09, 0.59),
}


@dataclass(frozen=True)
class Contract:
    symbol: str
    name: str
    ounces: float
    tick: float                   # price increment, $ per oz
    exchange_clearing_nfa_side: float  # pass-through fees per side
    micro: bool
    verified: bool                # fees read from Tradovate's all-in PDF?

    @property
    def tick_value(self) -> float:
        return self.tick * self.ounces

    def round_turn_cost(self, plan: str = "free", slippage_ticks_per_side: float = 1.0) -> float:
        p = PLANS[plan]
        comm = p.micro_commission_side if self.micro else p.std_commission_side
        per_side = comm + self.exchange_clearing_nfa_side + slippage_ticks_per_side * self.tick_value
        return 2 * per_side


# MGC: exchange 0.62 + clearing 0.19 + NFA 0.02 (Tradovate all-in PDF).
MGC = Contract("MGC", "E-Micro Gold (COMEX)", 10, 0.10, 0.83, micro=True, verified=True)
# GC: pass-through fees NOT verified here; estimate, check the PDF before use.
GC = Contract("GC", "Gold (COMEX)", 100, 0.10, 2.00, micro=False, verified=False)

CONTRACTS = {"MGC": MGC, "GC": GC}
DEFAULT_CONTRACT = MGC
DEFAULT_PLAN = "free"

# MGC/GC listed months used for trading: Feb, Apr, Jun, Aug, Oct, Dec.
# Roll a few sessions before first notice day (end of the prior month).
ACTIVE_MONTHS = (2, 4, 6, 8, 10, 12)
MONTH_CODES = {2: "G", 4: "J", 6: "M", 8: "Q", 10: "V", 12: "Z"}

# Risk settings used by the backtest and the signal script.
RISK = {
    "account_usd": 10_000,
    "risk_per_trade_pct": 0.5,      # % of account lost if the stop is hit
    "max_contracts": 5,
    "prob_long": 0.55,              # calibrated P(up) needed to go long
    "prob_short": 0.45,             # P(up) at or below this -> short
}
