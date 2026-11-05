"""Gold scalper analytics shared by the live cockpit and the backtest studio (same math in both, so tests match live).

Everything works on plain bar dicts: {"time": epoch_s, "open", "high", "low", "close", "volume"}.
Deterministic and rule-based: no AI/LLM.

Confluence (max 10.0):
  liquidity sweep 3.5 | fair value gap 2.0 | VWAP discount/premium 1.5 | volume surge 1.5 | DXY tailwind 1.5
Grades: A+ >= 8.5, A >= 7.0, B >= 5.5, else C.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

WEIGHTS = {"sweep": 3.5, "fvg": 2.0, "vwap": 1.5, "volume": 1.5, "dxy": 1.5}
REGIMES = ("CONSOLIDATION_RANGE_REGIME", "BALANCED_INTRADAY_REGIME", "TREND_EXPANSION_REGIME")

DEFAULT_PARAMS = {
    "contracts": 4,               # micro contracts per trade (1-20)
    "point_value": 10.0,          # MGC: $10 per 1.0 point per contract
    "commission_rt": 3.50,        # round-turn commission per contract
    "base_tp": 3.45,              # points
    "sl_cap": 3.50,               # max stop distance, points
    "sl_min": 2.20,               # min stop distance, points
    "sl_atr_mult": 1.2,           # stop = clamp(M15 ATR * mult, sl_min, sl_cap)
    "be_trigger_r": 0.45,         # move stop to breakeven after this many R in favour
    "be_lock": 0.75,              # breakeven stop = entry +/- this many points
    "cooldown_after_trade_s": 120,
    "cooldown_after_loss_s": 600,  # same-direction pause after a stop-out
    "confluence_min": 6.8,
    "quota_range": 2, "quota_balanced": 3, "quota_expansion": 4,
    "swing_lookback": 9,          # M5 bars for the sweep check
    "volume_surge": 1.15,         # last M5 volume vs 20-bar average
    "max_spread": 0.25,           # points; wider spread blocks entries
    "daily_loss_kill": 600.0,     # $ per account; kill switch
    "news_before_min": 15, "news_after_min": 15,
    "asian_start_h": 18, "asian_end_h": 3,   # ET hours (18:00 -> 03:00)
    "session_filter": "all",      # all | london_ny (03:00-16:00 ET)
    "allow_counter_trend": True,
}

ADAPT = {  # regime -> multipliers on the base params
    "CONSOLIDATION_RANGE_REGIME": {"tp": 0.80, "sl": 0.85, "be": 0.35, "quota": "quota_range"},
    "BALANCED_INTRADAY_REGIME": {"tp": 1.00, "sl": 1.00, "be": None, "quota": "quota_balanced"},
    "TREND_EXPANSION_REGIME": {"tp": 1.30, "sl": 1.15, "be": 0.60, "quota": "quota_expansion"},
}


def resample(bars: list[dict], minutes: int) -> list[dict]:
    out: list[dict] = []
    step = minutes * 60
    for b in bars:
        t = int(b["time"]) - int(b["time"]) % step
        if out and out[-1]["time"] == t:
            o = out[-1]
            o["high"] = max(o["high"], b["high"]); o["low"] = min(o["low"], b["low"])
            o["close"] = b["close"]; o["volume"] += b.get("volume", 0)
        else:
            out.append({"time": t, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
                        "volume": b.get("volume", 0)})
    return out


def atr(bars: list[dict], n: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    trs = [max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"]))
           for p, b in zip(bars[:-1], bars[1:])]
    trs = trs[-n:]
    return sum(trs) / len(trs)


def regime(m15: list[dict]) -> dict:
    """Volatility regime from M15: ATR vs its recent median, and trend efficiency (net move / path length)."""
    if len(m15) < 20:
        return {"regime": "BALANCED_INTRADAY_REGIME", "atr": round(atr(m15), 3), "atr_ratio": 1.0, "efficiency": 0.0}
    a = atr(m15)
    hist = sorted(atr(m15[max(0, i - 14):i + 1]) for i in range(max(15, len(m15) - 96), len(m15)))
    med = hist[len(hist) // 2] or a or 1e-9
    w = m15[-16:]
    path = sum(abs(y["close"] - x["close"]) for x, y in zip(w[:-1], w[1:])) or 1e-9
    eff = abs(w[-1]["close"] - w[0]["close"]) / path
    ratio = a / med
    if ratio >= 1.10 and eff >= 0.35:
        r = "TREND_EXPANSION_REGIME"
    elif ratio <= 0.80 or eff <= 0.15:
        r = "CONSOLIDATION_RANGE_REGIME"
    else:
        r = "BALANCED_INTRADAY_REGIME"
    return {"regime": r, "atr": round(a, 3), "atr_ratio": round(ratio, 3), "efficiency": round(eff, 3),
            "trend": "up" if w[-1]["close"] > w[0]["close"] else "down"}


def adaptive(params: dict, reg: str, m15_atr: float) -> dict:
    """The parameters actually in force for this regime."""
    a = ADAPT[reg]
    sl = min(params["sl_cap"] * a["sl"], max(params["sl_min"], m15_atr * params["sl_atr_mult"]))
    return {"tp": round(params["base_tp"] * a["tp"], 2), "sl": round(sl, 2), "sl_cap": round(params["sl_cap"] * a["sl"], 2),
            "be_trigger_r": a["be"] if a["be"] is not None else params["be_trigger_r"], "be_lock": params["be_lock"],
            "quota": int(params[a["quota"]])}


def _et(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, ET)


def asian_range(bars: list[dict], params: dict, now_ts: float) -> dict:
    """High/low of the most recent completed-or-running Asian window (default 18:00 -> 03:00 ET)."""
    now = _et(now_ts)
    s_h, e_h = int(params["asian_start_h"]), int(params["asian_end_h"])
    start = now.replace(hour=s_h, minute=0, second=0, microsecond=0)
    if start > now:
        start -= timedelta(days=1)
    end = start + timedelta(hours=(e_h - s_h) % 24)
    w = [b for b in bars if start.timestamp() <= b["time"] < end.timestamp()]
    if not w:
        return {}
    return {"asian_high": max(b["high"] for b in w), "asian_low": min(b["low"] for b in w),
            "asian_start": start.isoformat(), "asian_end": end.isoformat(), "active": now < end}


def session_vwap(bars: list[dict], now_ts: float) -> float | None:
    """VWAP since the 18:00 ET session open."""
    now = _et(now_ts)
    start = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if start > now:
        start -= timedelta(days=1)
    w = [b for b in bars if b["time"] >= start.timestamp()]
    vol = sum(max(b.get("volume", 0), 1) for b in w)
    if not w:
        return None
    return round(sum((b["high"] + b["low"] + b["close"]) / 3 * max(b.get("volume", 0), 1) for b in w) / vol, 2)


def fvgs(m5: list[dict], lookback: int = 12) -> list[dict]:
    """Unfilled 3-bar fair value gaps in the last `lookback` M5 bars."""
    out = []
    w = m5[-lookback - 2:]
    for i in range(2, len(w)):
        a, c = w[i - 2], w[i]
        later = w[i + 1:]
        if c["low"] > a["high"]:  # bullish gap
            lo, hi = a["high"], c["low"]
            if not any(b["low"] <= lo for b in later):
                out.append({"side": "bull", "low": lo, "high": hi, "time": c["time"]})
        elif c["high"] < a["low"]:  # bearish gap
            lo, hi = c["high"], a["low"]
            if not any(b["high"] >= hi for b in later):
                out.append({"side": "bear", "low": lo, "high": hi, "time": c["time"]})
    return out


def sweep(m5: list[dict], lookback: int, asian: dict) -> dict:
    """Liquidity sweep in the last 3 closed M5 bars: wick through the prior swing (or Asian) extreme, close back inside."""
    if len(m5) < lookback + 4:
        return {}
    for k in (1, 2, 3):
        b = m5[-k]
        prior = m5[-k - lookback:-k]
        lo = min(x["low"] for x in prior); hi = max(x["high"] for x in prior)
        lows = [lo] + ([asian["asian_low"]] if asian.get("asian_low") else [])
        highs = [hi] + ([asian["asian_high"]] if asian.get("asian_high") else [])
        for lvl in lows:
            if b["low"] < lvl < b["close"]:
                return {"side": "long", "level": lvl, "time": b["time"], "asian": lvl != lo}
        for lvl in highs:
            if b["high"] > lvl > b["close"]:
                return {"side": "short", "level": lvl, "time": b["time"], "asian": lvl != hi}
    return {}


def confluence(m5: list[dict], price: float, vwap: float | None, asian: dict, params: dict,
               dxy_trend: str | None = None) -> dict:
    """Score both directions and return the stronger one."""
    sw = sweep(m5, int(params["swing_lookback"]), asian)
    gaps = fvgs(m5)
    vols = [b.get("volume", 0) for b in m5[-21:-1]]
    surge = bool(vols) and (sum(vols) / len(vols)) > 0 and m5[-1].get("volume", 0) >= params["volume_surge"] * sum(vols) / len(vols)
    best = None
    for side in ("long", "short"):
        f = {
            "sweep": sw.get("side") == side,
            "fvg": any(g["side"] == ("bull" if side == "long" else "bear") for g in gaps),
            "vwap": vwap is not None and ((price < vwap) if side == "long" else (price > vwap)),
            "volume": surge,
            "dxy": dxy_trend == ("down" if side == "long" else "up"),
        }
        score = round(sum(WEIGHTS[k] for k, v in f.items() if v), 2)
        if best is None or score > best["score"]:
            best = {"side": side, "score": score, "factors": f}
    s = best["score"]
    best["grade"] = "A+" if s >= 8.5 else "A" if s >= 7.0 else "B" if s >= 5.5 else "C"
    best["sweep"] = sw
    best["fvgs"] = gaps
    best["max"] = 10.0
    best["dxy_available"] = dxy_trend is not None
    return best


def in_session(ts: float, params: dict) -> bool:
    if params.get("session_filter", "all") == "all":
        return True
    h = _et(ts).hour
    return 3 <= h < 16  # London open through NY afternoon
