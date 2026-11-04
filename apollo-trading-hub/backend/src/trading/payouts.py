"""Firm payout policies: eligibility, request size, and monthly withdrawal ceilings.

Each firm profile size may carry `payouts`: a list of payout paths (e.g. Topstep standard vs consistency, Tradeify
Select Flex vs Select Daily). The account uses rule_overrides.payout_path, else the first path.

Fields: cadence cycle|daily|interval, min_days, min_day_profit, interval_days, cycle_consistency_pct,
basis profit|above_buffer|cycle_profit_x2, pct, caps (per payout #, last repeats; null = uncapped), min_request,
buffer (balance offset above start that must remain), max_payouts, split, first_split, profit_since_last.
"""
from __future__ import annotations

from datetime import date, datetime

TRADING_DAYS_PER_MONTH = 21


def path_for(rules: dict) -> dict | None:
    paths = rules.get("payouts") or []
    if not paths:
        return None
    want = rules.get("payout_path")
    return next((p for p in paths if p["name"] == want), paths[0])


def cap_for(path: dict, n: int) -> float | None:
    caps = path.get("caps")
    if not caps:
        return None
    return float(caps[min(n, len(caps) - 1)])


def net_of_split(path: dict, gross: float, paid_before: float) -> float:
    """Trader's take-home after the split (incl. e.g. Topstep's first $10k at 100%)."""
    fs = path.get("first_split")
    if fs:
        at_first = max(0.0, min(gross, fs["amount"] - paid_before))
        return at_first * fs["split"] + (gross - at_first) * path["split"]
    return gross * path.get("split", 1.0)


def evaluate(a, today: date | None = None) -> dict:
    """Eligibility + exact request amount for one account right now."""
    r = a.rules
    path = path_for(r)
    base = {"account_id": a.account_id, "firm": r.get("firm_name"), "path": path["name"] if path else None,
            "eligible": False, "max_request": 0.0, "net_to_you": 0.0, "blockers": [], "payout_number": a.payouts_approved + 1,
            "dashboard_url": r.get("payout_dashboard_url"), "pending": a.payout_pending, "verified": path.get("verified", True) if path else None}
    if not path:
        base["blockers"].append("no payout policy on file for this firm/plan")
        return base
    b = base["blockers"]
    today = today or datetime.now().date()
    days = a.cycle_day_pnls
    cycle_profit = a.closed_balance - a.cycle_start_balance
    if a.stage != "FUNDED":
        b.append("not funded yet")
    if a.halted or a.liquidated or a.status == "CLOSED":
        b.append(f"account {a.status.lower()}")
    if a.payout_pending:
        b.append(f"payout of ${a.payout_pending:,.0f} already requested; mark it paid or rejected")
    if path.get("max_payouts") and a.payouts_approved >= path["max_payouts"]:
        b.append(f"max {path['max_payouts']} payouts reached")
    cad = path["cadence"]
    if cad == "cycle":
        q = sum(1 for d in days if d >= (path.get("min_day_profit") or 0.01))
        base["qualifying_days"] = f"{q}/{path['min_days']}"
        if q < path["min_days"]:
            b.append(f"{path['min_days'] - q} more day(s) of ${path.get('min_day_profit', 0):,.0f}+ needed")
    elif cad == "daily":
        if a.last_payout_date == today.isoformat():
            b.append("already paid out today")
    elif cad == "interval":
        if a.last_payout_date:
            gap = (today - date.fromisoformat(a.last_payout_date)).days
            if gap < path["interval_days"]:
                b.append(f"next request in {path['interval_days'] - gap} day(s)")
    cc = path.get("cycle_consistency_pct")
    if cc and cycle_profit > 0:
        best = max(days, default=0.0)
        if best >= cc * cycle_profit:
            b.append(f"best day ${best:,.0f} is >= {cc:.0%} of cycle profit ${cycle_profit:,.0f}")
    if path.get("profit_since_last") and a.payouts_approved > 0 and cycle_profit <= 0:
        b.append("not profitable since last payout")
    basis = path["basis"]
    if basis == "profit":
        amt = path["pct"] * max(0.0, a.closed_balance - a.starting_balance)
    elif basis == "above_buffer":
        amt = max(0.0, a.closed_balance - (a.starting_balance + (path.get("buffer") or 0)))
    else:  # cycle_profit_x2
        if path.get("buffer") and a.closed_balance < a.starting_balance + path["buffer"]:
            b.append(f"balance must exceed buffer (+${path['buffer']:,.0f})")
        amt = 2 * max(0.0, cycle_profit)
    cap = cap_for(path, a.payouts_approved)
    if cap is not None:
        amt = min(amt, cap)
    amt = float(int(amt))  # whole dollars
    if amt < (path.get("min_request") or 0):
        b.append(f"withdrawable ${amt:,.0f} < minimum ${path.get('min_request', 0):,.0f}")
    base.update(max_request=amt, cap=cap, cycle_profit=round(cycle_profit, 2),
                net_to_you=round(net_of_split(path, amt, a.total_paid_out), 2), eligible=not b, note=path.get("note", ""))
    return base


def monthly_ceiling(a, trading_days: int = TRADING_DAYS_PER_MONTH) -> dict:
    """Theoretical max you can pull from this account in a month IF profits always cover the caps.
    Real withdrawals are limited by what the strategy actually earns."""
    r = a.rules
    path = path_for(r)
    if not path:
        return {"account_id": a.account_id, "known": False}
    cad = path["cadence"]
    per_month = (trading_days // path["min_days"]) if cad == "cycle" else trading_days if cad == "daily" else max(1, 30 // path["interval_days"])
    left = (path["max_payouts"] - a.payouts_approved) if path.get("max_payouts") else per_month
    n = max(0, min(per_month, left))
    caps = [cap_for(path, a.payouts_approved + i) for i in range(n)]
    uncapped = any(c is None for c in caps)
    gross = None if uncapped else sum(caps)
    lifetime = None
    if path.get("max_payouts") and path.get("caps"):
        lifetime = sum(cap_for(path, i) for i in range(path["max_payouts"]))
    return {"account_id": a.account_id, "firm": r.get("firm_name"), "path": path["name"], "known": True,
            "payouts_per_month": n, "gross_ceiling": gross, "uncapped": uncapped,
            "net_ceiling": None if gross is None else round(net_of_split(path, gross, a.total_paid_out), 2),
            "lifetime_gross_cap": lifetime, "payouts_left": None if not path.get("max_payouts") else left,
            "profit_needed_note": ("needs >= 2x each payout in profit (50% rule)" if path["basis"] == "profit" and path["pct"] == 0.5 else
                                   f"needs balance above start + ${path.get('buffer') or 0:,.0f} buffer" if path["basis"] == "above_buffer" else
                                   "up to 2x profit since last payout"),
            "verified": path.get("verified", True)}
