"""Multi-firm prop risk engine.

Each account carries its own resolved rule profile (config/firms/<firm>.json -> plan -> size):
  drawdown_type END_OF_DAY (MLL trails at 17:00 ET close) | INTRADAY (trails peak equity live) | STATIC (never trails)
  optional MLL lock, daily loss limit, eval target + consistency, contract caps / funded scaling tiers,
  payout cadence, graduation (e.g. Lucid's payout-5 50% cashout).
Profiles with verified=false are usable for paper/backtests; live routing is refused until the owner confirms them.
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
EOD_CLOSE = time(17, 0)
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "fleet.json"
FIRMS_DIR = ROOT / "config" / "firms"
STATE_PATH = ROOT / "state" / "fleet_state.json"

Stage = Literal["EVALUATION", "FUNDED"]

# Lucid FLEX 150K funded tiers (min closed profit, max MGC) kept for callers that import it
FUNDED_TIERS: list[tuple[float, int]] = [(4500, 100), (3000, 80), (2000, 60), (1000, 50), (0, 40)]  # LucidFlex 150K (help center, 2026)
EVAL_MAX_MGC = 100


def load_fleet_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text())


def list_firms() -> dict:
    out = {}
    for f in sorted(FIRMS_DIR.glob("*.json")):
        d = json.loads(f.read_text())
        out[f.stem] = {"name": d["name"], "verified": d.get("verified", False), "note": d.get("note", ""),
                       "platforms": d.get("platforms", []), "contract": d.get("contract", "MGC"),
                       "plans": {p: sorted(s) for p, s in d["plans"].items()}}
    return out


def resolve_rules(firm: str, plan: str, size: str, overrides: dict | None = None) -> dict:
    p = FIRMS_DIR / f"{firm}.json"
    if not p.exists():
        raise ValueError(f"unknown firm {firm!r}; available: {sorted(x.stem for x in FIRMS_DIR.glob('*.json'))}")
    d = json.loads(p.read_text())
    try:
        r = copy.deepcopy(d["plans"][plan][size])
    except KeyError:
        raise ValueError(f"{firm} has no plan/size {plan}/{size}; available: { {k: list(v) for k, v in d['plans'].items()} }")
    r.update(overrides or {})
    r.setdefault("eval_consistency_cap_usd", None)
    r["firm"], r["firm_name"], r["plan"], r["size"] = firm, d["name"], plan, size
    size_verified = r.pop("verified", True)  # a single size can be flagged unverified inside a verified firm
    r["verified"] = bool(d.get("verified", False)) and bool(size_verified) and not (overrides or {}).get("_unverified_override", False)
    r["verified_on"], r["sources"] = d.get("verified_on"), d.get("sources", [])
    r["contract"] = r.get("contract", d.get("contract", "MGC"))
    r.setdefault("max_funded_accounts", d.get("max_funded_accounts"))  # firm-wide cap on simultaneously funded accounts
    r.setdefault("park_buffer_usd", d.get("park_buffer_usd"))
    return r


def funded_max_contracts(closed_profit: float, tiers=None) -> int:
    tiers = tiers or FUNDED_TIERS
    for floor, cap in sorted(tiers, key=lambda t: -t[0]):
        if closed_profit >= floor:
            return int(cap)
    return int(min(tiers, key=lambda t: t[0])[1])


def max_contracts(stage: Stage, closed_profit: float, rules: dict | None = None) -> int | None:
    rules = rules or {"eval_max_micros": EVAL_MAX_MGC, "funded_scaling": FUNDED_TIERS}
    if stage == "FUNDED" and rules.get("funded_scaling"):
        return funded_max_contracts(closed_profit, rules["funded_scaling"])
    return rules.get("eval_max_micros")  # None = no contract cap (e.g. CFD firms)


def legacy_accounts(cfg: dict) -> list[dict]:
    """Old fleet.json (master + slaves, single rules block) -> account list."""
    if cfg.get("accounts"):
        return cfg["accounts"]
    firm = {"LUCID_TRADING": "lucid"}.get(cfg.get("firm", ""), "lucid")
    base = {"firm": firm, "plan": cfg.get("account_model", "FLEX"), "size": cfg.get("tier", "150K"),
            "broker": cfg.get("broker", {}).get("name", "tradovate").lower(), "copy_ratio": 1.0, "enabled": True}
    return [{**base, "id": cfg["master_account"], "role": "master"}] + \
        [{**base, "id": s, "role": "copy"} for s in cfg.get("slave_accounts", [])]


@dataclass
class AccountState:
    account_id: str
    stage: Stage = "EVALUATION"
    starting_balance: float = 150000.0
    closed_balance: float = 150000.0
    open_pnl: float = 0.0
    day_start_balance: float = 150000.0
    mll: float = 145500.0
    mll_locked: bool = False
    peak_equity: float = 150000.0
    qualifying_days: int = 0
    payouts_approved: int = 0
    total_paid_out: float = 0.0
    halted: bool = False
    liquidated: bool = False
    daily_limit_hit: bool = False
    best_day_profit: float = 0.0
    position_qty: float = 0
    avg_price: float = 0.0
    last_eod: str | None = None
    status: str = "ACTIVE"  # ACTIVE | PARKED | ELIGIBLE_FOR_CASHOUT | LIQUIDATED | KILLED | DAILY_LIMIT | CLOSED
    parked: bool = False
    parked_at: str | None = None
    cost: float = 0.0
    purchased_at: str | None = None
    passed_at: str | None = None
    failed_at: str | None = None
    firm: str = "lucid"
    plan: str = "FLEX"
    size: str = "150K"
    broker: str = "paper"
    broker_account: str = ""
    role: str = "copy"
    copy_ratio: float = 1.0
    contract: str = "MGC"
    verified: bool = True
    events: list[str] = field(default_factory=list)
    rules: dict = field(default_factory=dict, repr=False)

    @property
    def closed_profit(self) -> float:
        return self.closed_balance - self.starting_balance

    @property
    def equity(self) -> float:
        return self.closed_balance + self.open_pnl

    @property
    def distance_to_mll(self) -> float:
        return round(self.equity - self.mll, 2)

    @property
    def day_pnl(self) -> float:
        return self.equity - self.day_start_balance

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("rules", None)
        r = self.rules
        d.update(closed_profit=round(self.closed_profit, 2), equity=round(self.equity, 2), distance_to_mll=self.distance_to_mll,
                 max_contracts=max_contracts(self.stage, self.closed_profit, r), drawdown_type=r.get("drawdown_type"),
                 starting_drawdown=r.get("starting_drawdown"), daily_loss_limit=r.get("daily_loss_limit"),
                 firm_name=r.get("firm_name"), day_pnl=round(self.day_pnl, 2))
        d.pop("events", None)
        d["recent_events"] = self.events[-5:]
        return d


def _now() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


class RiskSentinel:
    def __init__(self, config: dict | None = None, on_event=None):
        self.config = config or load_fleet_config()
        self.on_event = on_event or (lambda e: None)
        self.ledger: list[dict] = []          # every lifecycle event, every account, every firm
        self.pending_flatten: set[str] = set()  # accounts the router must flatten (just parked)
        self.accounts: dict[str, AccountState] = {}
        self.specs = [a for a in legacy_accounts(self.config) if a.get("enabled", True)]
        if not self.specs:
            raise ValueError("fleet has no enabled accounts")
        masters = [a for a in self.specs if a.get("role") == "master"]
        if len(masters) != 1:
            raise ValueError(f"fleet needs exactly one master account (found {len(masters)})")
        self.master_id = masters[0]["id"]
        self.config.setdefault("master_account", self.master_id)
        self.config["slave_accounts"] = [a["id"] for a in self.specs if a["id"] != self.master_id]
        self.config.setdefault("contract", "MGC")
        for spec in self.specs:
            self.accounts[spec["id"]] = self._from_spec(spec)
        # default rules (backtests, legacy callers) = master's profile
        self.rules = self.accounts[self.master_id].rules
        self.config["rules"] = self.rules

    def _from_spec(self, spec: dict) -> AccountState:
        rules = resolve_rules(spec["firm"], spec["plan"], spec["size"], spec.get("rule_overrides"))
        a = self._fresh(spec["id"], rules, spec.get("stage", "EVALUATION"))
        a.broker, a.broker_account = spec.get("broker", "paper"), spec.get("broker_account", spec["id"])
        a.role, a.copy_ratio = spec.get("role", "copy"), float(spec.get("copy_ratio", 1.0))
        a.cost = float(spec.get("cost", 0) or 0)
        a.purchased_at = spec.get("purchased_at")
        if spec.get("stage") == "FUNDED":
            a.stage = "FUNDED"
        return a

    @staticmethod
    def _fresh(aid: str, rules: dict, stage: Stage = "EVALUATION") -> AccountState:
        start = float(rules["starting_balance"])
        return AccountState(account_id=aid, stage=stage, starting_balance=start, closed_balance=start, day_start_balance=start,
                            peak_equity=start, mll=start - rules["starting_drawdown"], firm=rules["firm"], plan=rules["plan"],
                            size=rules["size"], contract=rules["contract"], verified=rules["verified"], rules=rules)

    def new_account(self, aid: str, stage: Stage = "EVALUATION", rules: dict | None = None) -> AccountState:
        return self._fresh(aid, rules or self.rules, stage)

    def rules_for(self, aid: str) -> dict:
        a = self.accounts.get(aid)
        return a.rules if a else self.rules

    # ---- order gate -------------------------------------------------------
    def validate_order(self, account_id: str, stage: Stage, contract_qty: float, symbol: str, live: bool = False) -> dict:
        acct = self.accounts.get(account_id)
        rules = acct.rules if acct else self.rules
        contract = acct.contract if acct else self.config.get("contract", "MGC")
        reasons: list[str] = []
        sym = symbol.upper()
        if contract == "MGC" and not (sym.startswith("MGC") or sym.startswith(contract)):
            reasons.append(f"symbol {symbol} not tradable on this account (contract {contract})")
        closed_profit = acct.closed_profit if acct else 0.0
        cap = max_contracts(stage, closed_profit, rules)
        if contract_qty <= 0:
            reasons.append("contract_qty must be positive")
        current = abs(acct.position_qty) if acct else 0
        projected = current + contract_qty
        if acct:
            if acct.halted:
                reasons.append(f"account halted ({acct.status})")
            if acct.liquidated:
                reasons.append("account liquidated (MLL breached)")
            if acct.daily_limit_hit:
                reasons.append("daily loss limit hit; locked until next session")
            if acct.parked:
                q = self.queue(acct.firm)
                reasons.append(f"parked near eval target: {rules.get('firm_name')} funded cap {self.firm_cap(acct.firm)} is full "
                               f"(queue position {q.index(account_id) + 1 if account_id in q else '?'})")
            if live and not acct.verified:
                reasons.append(f"{rules.get('firm_name')} rules are an unverified template; confirm them and set verified=true before live trading")
        approved_qty = contract_qty if cap is None else max(0, min(contract_qty, cap - current))
        if cap is not None and projected > cap:
            reasons.append(f"projected {projected:g} exceeds {stage} cap {cap} (closed profit ${closed_profit:,.2f})")
        blocked = acct is not None and (acct.halted or acct.liquidated or acct.daily_limit_hit or acct.parked or (live and not acct.verified))
        return {"account_id": account_id, "stage": stage, "symbol": symbol, "requested_qty": contract_qty,
                "max_allowed": cap if cap is not None else contract_qty, "approved_qty": 0 if blocked else approved_qty,
                "approved": not reasons, "reasons": reasons, "firm": rules.get("firm_name"), "verified": rules.get("verified")}

    # ---- intraday ---------------------------------------------------------
    def mark(self, account_id: str, open_pnl: float) -> AccountState:
        acct = self.accounts[account_id]
        r = acct.rules
        acct.open_pnl = open_pnl
        eq = acct.equity
        if r.get("drawdown_type") == "INTRADAY" and not acct.mll_locked and eq > acct.peak_equity:
            acct.peak_equity = eq
            self._trail(acct, eq)
        if eq <= acct.mll and not acct.liquidated:
            acct.liquidated, acct.status = True, "LIQUIDATED"
            acct.events.append(f"LIQUIDATED: equity {eq:.2f} <= MLL {acct.mll:.2f}")
            self._fail(acct)
        dll = r.get("daily_loss_limit")
        if dll and not acct.daily_limit_hit and not acct.liquidated and acct.day_pnl <= -dll:
            acct.daily_limit_hit = True
            if acct.status == "ACTIVE":
                acct.status = "DAILY_LIMIT"
            acct.events.append(f"DAILY LOSS LIMIT: day PnL {acct.day_pnl:.2f} <= -{dll}")
        self.check_parking(account_id)
        return acct

    def _trail(self, acct: AccountState, level: float) -> None:
        r = acct.rules
        thr, lock = r.get("mll_lock_threshold"), r.get("mll_lock_level")
        if thr is not None and level >= thr:
            acct.mll, acct.mll_locked = lock, True
            acct.events.append(f"MLL locked at {lock}")
            return
        acct.mll = max(acct.mll, level - r["starting_drawdown"])

    def apply_fill(self, account_id: str, action: str, qty: float, price: float, point_value: float | None = None) -> float:
        a = self.accounts[account_id]
        pv = point_value if point_value is not None else (100.0 if a.contract == "XAUUSD" else 10.0)
        signed = qty if action == "Buy" else -qty
        realized = 0.0
        if a.position_qty == 0 or (a.position_qty > 0) == (signed > 0):
            new = a.position_qty + signed
            a.avg_price = (a.avg_price * abs(a.position_qty) + price * qty) / abs(new)
            a.position_qty = new
        else:
            close = min(qty, abs(a.position_qty))
            direction = 1 if a.position_qty > 0 else -1
            realized = (price - a.avg_price) * direction * close * pv
            a.position_qty += signed
            if abs(a.position_qty) < 1e-9:
                a.position_qty, a.avg_price = 0, 0.0
            elif (a.position_qty > 0) != (direction > 0):
                a.avg_price = price
            self.realize(account_id, realized)
        if a.position_qty == 0:
            a.open_pnl = 0.0
        return realized

    def realize(self, account_id: str, pnl: float) -> AccountState:
        acct = self.accounts[account_id]
        acct.closed_balance += pnl
        acct.open_pnl = 0.0
        if acct.equity <= acct.mll and not acct.liquidated:
            acct.liquidated, acct.status = True, "LIQUIDATED"
            self._fail(acct)
        self.check_parking(account_id)
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
        r = acct.rules
        day_pnl = acct.closed_balance - acct.day_start_balance
        acct.best_day_profit = max(acct.best_day_profit, day_pnl)
        if r.get("qualifying_day_threshold") and day_pnl >= r["qualifying_day_threshold"]:
            acct.qualifying_days += 1
        if r.get("drawdown_type") == "END_OF_DAY" and not acct.mll_locked:
            self._trail(acct, acct.closed_balance)
        if acct.daily_limit_hit and not acct.liquidated:
            acct.daily_limit_hit = False
            if acct.status == "DAILY_LIMIT":
                acct.status = "ACTIVE"
        acct.day_start_balance = acct.closed_balance
        acct.last_eod = session_date
        if acct.stage == "EVALUATION" and not acct.liquidated and self.eval_passed(account_id):
            self.promote(account_id, session_date)
        return acct

    # ---- evaluation / payouts --------------------------------------------
    def eval_passed(self, account_id: str) -> bool:
        acct = self.accounts[account_id]
        r = acct.rules
        profit = acct.closed_profit
        if not r.get("eval_target") or profit < r["eval_target"]:
            return False
        if r.get("eval_consistency_cap_usd") is not None and acct.best_day_profit > r["eval_consistency_cap_usd"]:
            return False
        if r.get("eval_consistency_pct") and profit > 0 and acct.best_day_profit > r["eval_consistency_pct"] * profit:
            return False
        return True

    def payout_eligibility(self, account_id: str) -> dict:
        acct = self.accounts[account_id]
        r = acct.rules
        need = r.get("qualifying_days_required")
        eligible = (acct.stage == "FUNDED" and need is not None and acct.qualifying_days >= need
                    and acct.closed_profit > 0 and not acct.halted and not acct.liquidated)
        cap = r.get("max_payout_per_request") or float("inf")
        amount = min(cap, max(0.0, acct.closed_profit * r.get("payout_pct_of_profit", 0.5))) if eligible else 0.0
        return {"account_id": account_id, "eligible": eligible, "max_request": round(amount, 2) if amount != float("inf") else 0.0,
                "qualifying_days": acct.qualifying_days, "payouts_approved": acct.payouts_approved,
                "rules_known": need is not None}

    def approve_payout(self, account_id: str, amount: float) -> dict:
        acct = self.accounts[account_id]
        acct.closed_balance -= amount
        acct.total_paid_out += amount
        acct.payouts_approved += 1
        acct.qualifying_days = 0
        acct.day_start_balance = acct.closed_balance
        if acct.rules.get("lock_mll_on_first_payout") and acct.rules.get("mll_lock_level") and not acct.mll_locked:
            acct.mll, acct.mll_locked = acct.rules["mll_lock_level"], True  # LucidFlex: payout locks MLL at start+100
        result = {"account_id": account_id, "payout_number": acct.payouts_approved, "amount": amount}
        self.log(account_id, "PAYOUT", amount=amount, number=acct.payouts_approved)
        grad = acct.rules.get("max_payouts_before_graduation")
        if grad and acct.payouts_approved >= grad:
            result["graduation"] = self.trigger_graduation(account_id)
        return result

    def trigger_graduation(self, account_id: str) -> dict:
        acct = self.accounts[account_id]
        r = acct.rules
        acct.halted, acct.status = True, "ELIGIBLE_FOR_CASHOUT"
        now = datetime.now(ET)
        net = r.get("cashout_opt_out_value_net")
        payload = {
            "type": "GRADUATION_CASHOUT_ELECTION", "account_id": account_id, "firm": r.get("firm_name"),
            "election": "CASHOUT_50_PERCENT", "net_payout_usd": net, "decline_live_account": True,
            "generated_at": now.isoformat(), "operator_deadline": now.replace(microsecond=0).isoformat() + " +24h",
            "operator_alert": (f"ACTION REQUIRED within 24h: account {account_id} reached payout {acct.payouts_approved}. "
                               f"Execution halted. Submit 50% cashout election (${(net or 0):,.2f} net) and decline the live account."),
        }
        acct.events.append(payload["operator_alert"])
        self.log(account_id, "GRADUATION_CASHOUT", net=net)
        return payload

    # ---- firm caps: park / unpark queue -----------------------------------
    def log(self, aid: str, kind: str, **data) -> dict:
        a = self.accounts.get(aid)
        e = {"ts": _now(), "account": aid, "firm": a.firm if a else data.get("firm"), "kind": kind, **data}
        self.ledger.append(e)
        self.on_event({"type": "lifecycle", **e})
        return e

    def firm_cap(self, firm: str) -> int | None:
        lim = (self.config.get("firm_limits") or {}).get(firm, {})
        if "max_funded_accounts" in lim:
            return lim["max_funded_accounts"]
        a = next((x for x in self.accounts.values() if x.firm == firm), None)
        return a.rules.get("max_funded_accounts") if a else None

    def external_funded(self, firm: str) -> int:
        """Funded accounts at this firm that exist but aren't in the app (still use up the firm's cap)."""
        return int((self.config.get("firm_limits") or {}).get(firm, {}).get("funded_outside_app", 0))

    @staticmethod
    def occupies_slot(a: AccountState) -> bool:
        return a.stage == "FUNDED" and not a.liquidated and a.status != "CLOSED"

    def funded_count(self, firm: str) -> int:
        return sum(1 for a in self.accounts.values() if a.firm == firm and self.occupies_slot(a)) + self.external_funded(firm)

    def slots_free(self, firm: str) -> int | None:
        cap = self.firm_cap(firm)
        return None if cap is None else max(0, cap - self.funded_count(firm))

    def park_threshold(self, a: AccountState) -> float | None:
        tgt = a.rules.get("eval_target")
        if not tgt:
            return None
        buf = (self.config.get("firm_limits") or {}).get(a.firm, {}).get("park_buffer_usd", a.rules.get("park_buffer_usd"))
        return tgt - (buf if buf is not None else max(250.0, 0.1 * tgt))

    def check_parking(self, aid: str) -> bool:
        """Park an eval that's about to pass while the firm's funded slots are full: flatten + stop opening trades."""
        a = self.accounts[aid]
        if a.stage != "EVALUATION" or a.parked or a.liquidated or a.status == "CLOSED":
            return False
        thr = self.park_threshold(a)
        if thr is None or self.slots_free(a.firm) != 0 or (a.equity - a.starting_balance) < thr:
            return False
        a.parked, a.parked_at, a.status = True, _now(), "PARKED"
        self.pending_flatten.add(aid)
        a.events.append(f"PARKED at +{a.equity - a.starting_balance:,.2f}: {a.rules.get('firm_name')} funded cap {self.firm_cap(a.firm)} full")
        self.log(aid, "PARKED", profit=round(a.equity - a.starting_balance, 2), threshold=thr,
                 queue_position=self.queue(a.firm).index(aid) + 1, cap=self.firm_cap(a.firm))
        return True

    def queue(self, firm: str) -> list[str]:
        """Parked evals waiting for a funded slot, first-parked first."""
        q = [a for a in self.accounts.values() if a.firm == firm and a.parked and not a.liquidated]
        return [a.account_id for a in sorted(q, key=lambda x: (x.parked_at or "", x.account_id))]

    def rebalance(self, firm: str) -> list[str]:
        """A slot opened: release parked evals (oldest first) so they can trade to the target and pass."""
        released = []
        free = self.slots_free(firm)
        pending_pass = sum(1 for a in self.accounts.values() if a.firm == firm and a.stage == "EVALUATION" and not a.parked
                           and not a.liquidated and (self.park_threshold(a) or 1e18) <= a.equity - a.starting_balance)
        n = None if free is None else max(0, free - pending_pass)
        for aid in self.queue(firm)[: n if n is not None else None]:
            a = self.accounts[aid]
            a.parked, a.status = False, ("KILLED" if a.halted else "ACTIVE")
            a.events.append("UNPARKED: funded slot available")
            self.log(aid, "UNPARKED", slots_free=self.slots_free(firm))
            released.append(aid)
        return released

    def _fail(self, a: AccountState) -> None:
        a.failed_at = _now()
        self.log(a.account_id, "FAILED", stage=a.stage, balance=round(a.equity, 2), mll=a.mll)
        a.parked = False
        if a.stage == "FUNDED":
            self.rebalance(a.firm)

    def promote(self, aid: str, session_date: str | None = None) -> None:
        """Eval passed -> funded (firm issues a fresh funded account; update broker_account if the ID changes)."""
        a = self.accounts[aid]
        free = self.slots_free(a.firm)
        if free == 0:
            self.log(aid, "PASSED_OVER_CAP", note="passed while cap full: check the firm dashboard")
        a.stage, a.passed_at = "FUNDED", _now()
        if a.rules.get("funded_drawdown_type"):  # e.g. MFFU Rapid / TPT PRO: EOD eval -> intraday funded
            a.rules = {**a.rules, "drawdown_type": a.rules["funded_drawdown_type"]}
        start = a.starting_balance
        a.closed_balance = a.day_start_balance = a.peak_equity = start
        a.mll, a.mll_locked, a.best_day_profit, a.qualifying_days = start - a.rules["starting_drawdown"], False, 0.0, 0
        a.parked, a.status = False, ("KILLED" if a.halted else "ACTIVE")
        self.log(aid, "PASSED", session=session_date, note="now FUNDED; if the firm gave a new account ID, update broker_account")

    def close_account(self, aid: str, reason: str = "closed by operator") -> None:
        a = self.accounts[aid]
        was_slot = self.occupies_slot(a)
        a.status, a.halted = "CLOSED", True
        self.log(aid, "CLOSED", reason=reason)
        if was_slot:
            self.rebalance(a.firm)

    def firm_summary(self) -> dict:
        out: dict[str, dict] = {}
        for a in self.accounts.values():
            f = out.setdefault(a.firm, {"firm_name": a.rules.get("firm_name"), "cap": self.firm_cap(a.firm),
                                        "funded_outside_app": self.external_funded(a.firm), "funded": 0, "evals_trading": 0,
                                        "parked": 0, "failed": 0, "passed": 0, "closed": 0, "accounts": 0, "cost": 0.0,
                                        "paid_out": 0.0, "open_equity_pnl": 0.0})
            f["accounts"] += 1
            f["cost"] += a.cost
            f["paid_out"] += a.total_paid_out
            f["funded"] += 1 if self.occupies_slot(a) else 0
            f["evals_trading"] += 1 if a.stage == "EVALUATION" and not a.parked and not a.liquidated and a.status != "CLOSED" else 0
            f["parked"] += 1 if a.parked else 0
            f["failed"] += 1 if a.liquidated else 0
            f["passed"] += 1 if a.passed_at else 0
            f["closed"] += 1 if a.status == "CLOSED" else 0
            if not a.liquidated and a.status != "CLOSED":
                f["open_equity_pnl"] += a.equity - a.starting_balance
        for firm, f in out.items():
            f["funded"] += f["funded_outside_app"]
            f["slots_free"] = None if f["cap"] is None else max(0, f["cap"] - f["funded"])
            f["queue"] = self.queue(firm)
            f["net_cash"] = round(f["paid_out"] - f["cost"], 2)
            for k in ("cost", "paid_out", "open_equity_pnl"):
                f[k] = round(f[k], 2)
        return out

    def kill(self, account_id: str | None = None) -> list[str]:
        ids = [account_id] if account_id else list(self.accounts)
        for aid in ids:
            a = self.accounts[aid]
            if a.status in ("ACTIVE", "DAILY_LIMIT", "PARKED"):
                a.status = "KILLED"
            a.halted = True
            a.events.append("KILL SWITCH engaged")
        return ids

    def resume(self, account_id: str) -> bool:
        a = self.accounts[account_id]
        if a.status != "KILLED":
            return False
        a.halted = False
        a.status = "PARKED" if a.parked else "ACTIVE"
        return True

    def save(self, path: Path = STATE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        data = {aid: {k: v for k, v in asdict(a).items() if k != "rules"} for aid, a in self.accounts.items()}
        data["__ledger__"] = self.ledger[-5000:]
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)

    def load(self, path: Path = STATE_PATH) -> bool:
        if not path.exists():
            return False
        data = json.loads(path.read_text())
        self.ledger = data.pop("__ledger__", [])
        keep = ("broker", "broker_account", "role", "copy_ratio", "firm", "plan", "size", "contract", "verified", "starting_balance", "cost", "purchased_at")
        for aid, d in data.items():
            if aid in self.accounts:
                cur = self.accounts[aid]
                if d.get("firm", cur.firm) != cur.firm or d.get("size", cur.size) != cur.size:
                    continue  # account was re-assigned to another firm/size: don't resurrect old state
                fields = {k: v for k, v in d.items() if k in AccountState.__dataclass_fields__ and k not in keep and k != "rules"}
                for k, v in fields.items():
                    setattr(cur, k, v)
        return True

    def snapshot(self) -> dict:
        return {aid: a.to_dict() for aid, a in self.accounts.items()}
