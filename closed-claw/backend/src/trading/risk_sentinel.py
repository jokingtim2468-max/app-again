"""LucidFlex 150K risk engine: EOD trailing MLL, funded scaling tiers, payouts, graduation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
EOD_CLOSE = time(17, 0)
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "fleet.json"

Stage = Literal["EVALUATION", "FUNDED"]

# (min closed profit, max MGC)
FUNDED_TIERS: list[tuple[float, int]] = [(6000, 100), (4500, 80), (3000, 60), (2000, 50), (0, 40)]
EVAL_MAX_MGC = 100  # 10 minis == 100 micros


def load_fleet_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text())


def funded_max_contracts(closed_profit: float) -> int:
    for floor, cap in FUNDED_TIERS:
        if closed_profit >= floor:
            return cap
    return FUNDED_TIERS[-1][1]  # below zero profit -> base tier


def max_contracts(stage: Stage, closed_profit: float) -> int:
    return EVAL_MAX_MGC if stage == "EVALUATION" else funded_max_contracts(closed_profit)


@dataclass
class AccountState:
    account_id: str
    stage: Stage = "EVALUATION"
    closed_balance: float = 150000.0
    open_pnl: float = 0.0
    day_start_balance: float = 150000.0
    mll: float = 145500.0
    mll_locked: bool = False
    qualifying_days: int = 0
    payouts_approved: int = 0
    total_paid_out: float = 0.0
    halted: bool = False
    liquidated: bool = False
    best_day_profit: float = 0.0
    position_qty: int = 0
    last_eod: str | None = None
    events: list[str] = field(default_factory=list)

    @property
    def closed_profit(self) -> float:
        return self.closed_balance - 150000.0

    @property
    def equity(self) -> float:
        return self.closed_balance + self.open_pnl

    @property
    def distance_to_mll(self) -> float:
        return round(self.equity - self.mll, 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(closed_profit=round(self.closed_profit, 2), equity=round(self.equity, 2),
                 distance_to_mll=self.distance_to_mll,
                 max_contracts=max_contracts(self.stage, self.closed_profit))
        return d


class RiskSentinel:
    def __init__(self, config: dict | None = None):
        self.config = config or load_fleet_config()
        self.rules = self.config["rules"]
        self.accounts: dict[str, AccountState] = {}
        ids = [self.config["master_account"], *self.config["slave_accounts"]]
        for aid in ids:
            self.accounts[aid] = self.new_account(aid)

    def new_account(self, aid: str, stage: Stage = "EVALUATION") -> AccountState:
        start = self.rules["starting_balance"]
        return AccountState(account_id=aid, stage=stage, closed_balance=start, day_start_balance=start,
                            mll=start - self.rules["starting_drawdown"])

    # ---- order gate -------------------------------------------------------
    def validate_order(self, account_id: str, stage: Stage, contract_qty: int, symbol: str) -> dict:
        acct = self.accounts.get(account_id)
        reasons: list[str] = []
        if not symbol.upper().startswith(self.config["contract"]):
            reasons.append(f"symbol {symbol} not in fleet contract {self.config['contract']}")
        closed_profit = acct.closed_profit if acct else 0.0
        cap = max_contracts(stage, closed_profit)
        if contract_qty <= 0:
            reasons.append("contract_qty must be positive")
        if acct:
            if acct.halted:
                reasons.append("account halted (graduation/cashout pending)")
            if acct.liquidated:
                reasons.append("account liquidated (MLL breached)")
            projected = abs(acct.position_qty) + contract_qty
        else:
            projected = contract_qty
        approved_qty = max(0, min(contract_qty, cap - (projected - contract_qty)))
        if projected > cap:
            reasons.append(f"projected {projected} MGC exceeds {stage} cap {cap} (closed profit ${closed_profit:,.2f})")
        return {"account_id": account_id, "stage": stage, "symbol": symbol, "requested_qty": contract_qty,
                "max_allowed": cap, "approved_qty": approved_qty if not (acct and (acct.halted or acct.liquidated)) else 0,
                "approved": not reasons, "reasons": reasons,
                "news_blackout": False}  # news trading permitted by fleet rules

    # ---- intraday ---------------------------------------------------------
    def mark(self, account_id: str, open_pnl: float) -> AccountState:
        """Intraday mark. MLL is NOT trailed here (EOD drawdown). Breach of equity < MLL liquidates."""
        acct = self.accounts[account_id]
        acct.open_pnl = open_pnl
        if acct.equity <= acct.mll and not acct.liquidated:
            acct.liquidated = True
            acct.events.append(f"LIQUIDATED: equity {acct.equity:.2f} <= MLL {acct.mll:.2f}")
        return acct

    def realize(self, account_id: str, pnl: float) -> AccountState:
        acct = self.accounts[account_id]
        acct.closed_balance += pnl
        acct.open_pnl = 0.0
        return acct

    # ---- 5:00 PM ET close -------------------------------------------------
    @staticmethod
    def is_eod(now: datetime | None = None) -> bool:
        now = (now or datetime.now(ET)).astimezone(ET)
        return now.time() >= EOD_CLOSE

    def end_of_day(self, account_id: str, session_date: str) -> AccountState:
        acct = self.accounts[account_id]
        if acct.last_eod == session_date:
            return acct
        r = self.rules
        day_pnl = acct.closed_balance - acct.day_start_balance
        acct.best_day_profit = max(acct.best_day_profit, day_pnl)
        if day_pnl >= r["qualifying_day_threshold"]:
            acct.qualifying_days += 1
        if not acct.mll_locked:
            trailed = acct.closed_balance - r["starting_drawdown"]
            if acct.closed_balance >= r["mll_lock_threshold"]:
                acct.mll = r["mll_lock_level"]
                acct.mll_locked = True
                acct.events.append(f"{session_date}: MLL locked at {r['mll_lock_level']}")
            elif trailed > acct.mll:
                acct.mll = trailed
        acct.day_start_balance = acct.closed_balance
        acct.last_eod = session_date
        return acct

    # ---- evaluation / payouts --------------------------------------------
    def eval_passed(self, account_id: str) -> bool:
        acct = self.accounts[account_id]
        profit = acct.closed_profit
        if profit < self.rules["eval_target"]:
            return False
        return acct.best_day_profit <= self.rules["eval_consistency_cap_usd"]

    def payout_eligibility(self, account_id: str) -> dict:
        acct = self.accounts[account_id]
        r = self.rules
        eligible = (acct.stage == "FUNDED" and acct.qualifying_days >= r["qualifying_days_required"]
                    and acct.closed_profit > 0 and not acct.halted and not acct.liquidated)
        amount = min(r["max_payout_per_request"], max(0.0, acct.closed_profit / 2)) if eligible else 0.0
        return {"account_id": account_id, "eligible": eligible, "max_request": round(amount, 2),
                "qualifying_days": acct.qualifying_days, "payouts_approved": acct.payouts_approved}

    def approve_payout(self, account_id: str, amount: float) -> dict:
        acct = self.accounts[account_id]
        acct.closed_balance -= amount
        acct.total_paid_out += amount
        acct.payouts_approved += 1
        acct.qualifying_days = 0
        acct.day_start_balance = acct.closed_balance
        result = {"account_id": account_id, "payout_number": acct.payouts_approved, "amount": amount}
        if acct.payouts_approved >= self.rules["max_payouts_before_graduation"]:
            result["graduation"] = self.trigger_graduation(account_id)
        return result

    def trigger_graduation(self, account_id: str) -> dict:
        """Payout 5 approved: halt the ID and build the 50% cashout election payload."""
        acct = self.accounts[account_id]
        acct.halted = True
        now = datetime.now(ET)
        payload = {
            "type": "GRADUATION_CASHOUT_ELECTION",
            "account_id": account_id,
            "election": "CASHOUT_50_PERCENT",
            "net_payout_usd": self.rules["cashout_opt_out_value_net"],
            "decline_live_account": True,
            "generated_at": now.isoformat(),
            "operator_deadline": (now.replace(microsecond=0)).isoformat() + " +24h",
            "operator_alert": (f"ACTION REQUIRED within 24h: account {account_id} reached payout "
                               f"{acct.payouts_approved}. Execution halted. Submit 50% cashout election "
                               f"(${self.rules['cashout_opt_out_value_net']:,.2f} net) and decline the live account."),
        }
        acct.events.append(payload["operator_alert"])
        return payload

    def snapshot(self) -> dict:
        return {aid: a.to_dict() for aid, a in self.accounts.items()}
