from __future__ import annotations

from ...contracts import CONTRACTS, MONTH_CODES, root_of
from ...core.bars import Bars


def contract_for(bars: Bars, tick_size: float, chosen: str | None = None) -> dict:
    """Build the Tradovate-style contract object a script expects (name like 'ESZ6', tick size)."""
    root = root_of(chosen or "") or root_of(bars.symbol) or (bars.symbol.split("=")[0][:6] or "SYM")
    import datetime as _dt
    last = _dt.datetime.fromtimestamp(int(bars.time[-1]) / 1000, tz=_dt.timezone.utc)
    quarter = ((last.month - 1) // 3 + 1) * 3
    code = MONTH_CODES[quarter - 1] + str(last.year % 10)
    tick = CONTRACTS[root]["tick"] if root in CONTRACTS else tick_size
    return {"name": f"{root}{code}", "id": 1, "providerTickSize": tick, "contractMaturityId": 1,
            "product": root, "tickSize": tick}
