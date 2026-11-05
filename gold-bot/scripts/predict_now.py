"""Tonight's forecast: expected highs / lows / bias for the next day, week, month, quarter,
in CME micro gold (MGC) futures prices, plus a Tradovate-ready signal file.

Run after the 17:00 ET session close:
    python scripts/predict_now.py
Writes signals/latest.json and appends to signals/history.csv.
Research only, not financial advice.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from goldbot.config import (ACTIVE_MONTHS, DEFAULT_CONTRACT, DEFAULT_PLAN, HORIZONS,  # noqa: E402
                            MODELS, MONTH_CODES, RISK, ROOT)
from goldbot.data import latest_futures_close, load_daily, load_macro  # noqa: E402
from goldbot.features import atr, build_features  # noqa: E402


def front_contract(today: pd.Timestamp, roll_days_before_fnd: int = 7) -> str:
    """Active MGC month to trade: roll ~1 week before first notice day
    (last business day of the month before delivery)."""
    for k in range(0, 14):
        m = (today.month - 1 + k) % 12 + 1
        y = today.year + (today.month - 1 + k) // 12
        if m not in ACTIVE_MONTHS:
            continue
        fnd = pd.Timestamp(year=y, month=m, day=1) - pd.offsets.BDay(1)
        if today <= fnd - pd.Timedelta(days=roll_days_before_fnd):
            return f"{DEFAULT_CONTRACT.symbol}{MONTH_CODES[m]}{y % 10}"
    raise RuntimeError("no active month found")


def main() -> None:
    d = load_daily()
    X = build_features(d, load_macro())
    t = X.index[-1]
    spot_close = float(d.Close.loc[t])
    a = float(atr(d).loc[t])
    fut_date, fut_close = latest_futures_close("micro_gold_fut")
    scale = fut_close / spot_close if abs((fut_date - t).days) <= 3 else 1.0
    ref = spot_close * scale
    a_fut = a * scale
    contract = front_contract(t)

    rows, out = [], {"as_of_session": str(t.date()), "contract": contract,
                     "reference_price": round(ref, 1), "atr14": round(a_fut, 2),
                     "broker": "Tradovate", "plan": DEFAULT_PLAN, "horizons": {}}
    for name, h in HORIZONS.items():
        f = MODELS / f"phase2_{name}.pkl"
        if not f.exists():
            raise SystemExit(f"missing {f}; run scripts/train_phase2.py first")
        # Safe: these pickles are written only by scripts/train_phase2.py on this machine
        # and are git-ignored. Never load a model file downloaded from elsewhere.
        with open(f, "rb") as fh:
            m = pickle.load(fh)
        x = X.loc[[t], m["features"]]
        up, dn = m["up"].predict(x).iloc[0], m["dn"].predict(x).iloc[0]
        p = float(m["dir"].predict_proba(x)[0])
        bias = ("BULLISH" if p >= RISK["prob_long"] else
                "BEARISH" if p <= RISK["prob_short"] else "NO CALL")
        lv = {f"high_{q}": round(ref + up[q] * a_fut, 1) for q in up.index}
        lv |= {f"low_{q}": round(ref - dn[q] * a_fut, 1) for q in dn.index}
        # suggested bracket + size (risk % of account to the q90 extreme against you)
        if bias == "BULLISH":
            stop, target = lv["low_q90"], lv["high_q50"]
        elif bias == "BEARISH":
            stop, target = lv["high_q90"], lv["low_q50"]
        else:
            stop = target = None
        size = 0
        if stop is not None:
            risk_per_contract = abs(ref - stop) * DEFAULT_CONTRACT.ounces + \
                DEFAULT_CONTRACT.round_turn_cost(DEFAULT_PLAN)
            size = int(min(RISK["max_contracts"],
                           np.floor(RISK["account_usd"] * RISK["risk_per_trade_pct"] / 100
                                    / risk_per_contract)))
        out["horizons"][name] = {"sessions": h, "p_up": round(p, 3), "bias": bias, **lv,
                                 "stop": stop, "target": target, "contracts": size,
                                 "model_trained_through": m["trained_through"]}
        rows.append({"horizon": f"{name} ({h})", "P(up)": f"{p:.0%}", "bias": bias,
                     "high q10/q50/q90": f"{lv['high_q10']} / {lv['high_q50']} / {lv['high_q90']}",
                     "low q10/q50/q90": f"{lv['low_q10']} / {lv['low_q50']} / {lv['low_q90']}",
                     "stop": stop, "target": target, f"{DEFAULT_CONTRACT.symbol}": size})

    print(f"\nGold forecast after the {t.date()} close | {contract} ref {ref:.1f} | "
          f"ATR14 {a_fut:.1f}")
    print("q50 = most likely extreme; q10..q90 = 80% range for how far price stretches.\n")
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nSizing: {RISK['risk_per_trade_pct']}% of ${RISK['account_usd']:,} per trade. "
          "Research only, not financial advice.")

    sd = ROOT / "signals"
    sd.mkdir(exist_ok=True)
    (sd / "latest.json").write_text(json.dumps(out, indent=2))
    flat = [{"as_of": out["as_of_session"], "contract": contract, "ref": out["reference_price"],
             "horizon": k, **v} for k, v in out["horizons"].items()]
    hist = sd / "history.csv"
    pd.DataFrame(flat).to_csv(hist, mode="a", header=not hist.exists(), index=False)


if __name__ == "__main__":
    main()
