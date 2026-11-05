"""Phase 2: multi-horizon high / low / direction forecasts, evaluated walk-forward,
then traded in a Tradovate MGC backtest.

For each horizon (day=1, week=5, month=21, quarter=63 sessions), at every session
close the model forecasts:
  * how far ABOVE today's close the highest high will reach  (q10 / q50 / q90)
  * how far BELOW today's close the lowest low will reach     (q10 / q50 / q90)
  * P(close in h sessions > close today), calibrated
All in ATR units, converted to prices with today's close and ATR.

Outputs -> reports/phase2_*.csv and models/phase2_*.pkl (final models on all data).
Research only, not financial advice.
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from goldbot.backtest import simulate, summarize  # noqa: E402
from goldbot.config import (DEFAULT_CONTRACT, DEFAULT_PLAN, HORIZONS, MODELS,  # noqa: E402
                            QUANTILES, REPORTS, RISK)
from goldbot.cv import yearly_purged_splits  # noqa: E402
from goldbot.data import load_daily, load_macro  # noqa: E402
from goldbot.features import build_features  # noqa: E402
from goldbot.models import DirectionModel, QuantileBand, pinball  # noqa: E402
from goldbot.targets import forward_targets  # noqa: E402

START = "2006-01-01"


def walk_forward(X: pd.DataFrame, T: pd.DataFrame, h: int) -> pd.DataFrame:
    ok = T[["up_atr", "dn_atr", "y_up"]].notna().all(axis=1)
    Xv, Tv = X[ok], T[ok]
    out = []
    for year, tr, te in yearly_purged_splits(Xv.index, h):
        Xtr, Ttr, Xte, Tte = Xv.iloc[tr], Tv.iloc[tr], Xv.iloc[te], Tv.iloc[te]
        res = pd.DataFrame(index=Xte.index)
        for side in ("up", "dn"):
            band = QuantileBand().fit(Xtr, Ttr[f"{side}_atr"]).predict(Xte)
            res[[f"{side}_{c}" for c in band.columns]] = band.to_numpy()
            for q in QUANTILES:  # baseline: plain historical ATR multiples
                res[f"base_{side}_q{int(q * 100)}"] = Ttr[f"{side}_atr"].quantile(q)
        res["p_up"] = DirectionModel(h=h).fit(Xtr, Ttr["y_up"]).predict_proba(Xte)
        res["base_p"] = Ttr["y_up"].mean()
        out.append(res.join(Tte))
        print(f"   h={h:2d} {year} done", end="\r")
    print()
    return pd.concat(out)


def band_metrics(P: pd.DataFrame, name: str, h: int) -> list[dict]:
    rows = []
    for side in ("up", "dn"):
        y = P[f"{side}_atr"].to_numpy()
        for q in QUANTILES:
            c = f"q{int(q * 100)}"
            m, b = P[f"{side}_{c}"].to_numpy(), P[f"base_{side}_{c}"].to_numpy()
            pl_m, pl_b = pinball(y, m, q), pinball(y, b, q)
            rows.append({
                "horizon": name, "h": h, "side": "high" if side == "up" else "low",
                "quantile": q,
                "hit_rate": round(float((y <= m).mean()), 3),  # should be ~= q
                "pinball_model": round(pl_m, 4), "pinball_base": round(pl_b, 4),
                "skill%": round(100 * (1 - pl_m / pl_b), 1),
                # median error in $/oz at the median quantile
                "mae_$_model": round(float(np.mean(np.abs(y - m) * P.atr)), 2) if q == .5 else None,
                "mae_$_base": round(float(np.mean(np.abs(y - b) * P.atr)), 2) if q == .5 else None,
            })
        lo, hi = P[f"{side}_q10"], P[f"{side}_q90"]
        rows.append({"horizon": name, "h": h, "side": "high" if side == "up" else "low",
                     "quantile": "10-90 band",
                     "hit_rate": round(float(((y >= lo) & (y <= hi)).mean()), 3)})
    return rows


def direction_metrics(P: pd.DataFrame, name: str, h: int) -> dict:
    y, p, b = P.y_up, P.p_up, P.base_p
    conf = (p >= RISK["prob_long"]) | (p <= RISK["prob_short"])
    return {
        "horizon": name, "h": h, "n": len(P),
        "up_rate": round(float(y.mean()), 3),
        "auc": round(roc_auc_score(y, p), 3),
        "brier": round(brier_score_loss(y, p), 4),
        "brier_base": round(brier_score_loss(y, b), 4),
        "brier_skill%": round(100 * (1 - brier_score_loss(y, p) / brier_score_loss(y, b)), 2),
        "acc": round(float(((p > .5) == (y == 1)).mean()), 3),
        "acc_always_long": round(float(y.mean()), 3),
        "calls%": round(float(conf.mean() * 100), 1),
        "acc_on_calls": round(float(((p[conf] > .5) == (y[conf] == 1)).mean()), 3),
        "short_calls%": round(float((p <= RISK["prob_short"]).mean() * 100), 1),
    }


def trade_tests(d: pd.DataFrame, P: pd.DataFrame, name: str, h: int) -> list[dict]:
    sig = P.copy()
    model_side = np.select([sig.p_up >= RISK["prob_long"], sig.p_up <= RISK["prob_short"]],
                           [1, -1], 0)
    years = (P.index[-1] - P.index[0]).days / 365.25
    rows = []
    configs = [  # (label, stop, target, entry)
        ("hold to horizon end", None, None, "market"),
        ("stop=low q90, hold", "dn_q90", None, "market"),
        ("stop=low q90, target=high q50", "dn_q90", "up_q50", "market"),
        ("stop=low q50, target=high q50", "dn_q50", "up_q50", "market"),
        ("stop=low q90, target=high q90", "dn_q90", "up_q90", "market"),
        ("limit@low q50, stop q90, tgt high q50", "dn_q90", "up_q50", "limit"),
    ]
    for who, side in (("model", model_side), ("always long", np.ones(len(sig), int))):
        s = sig.assign(side=side)
        for label, stop, tgt, entry in configs:
            # for shorts the roles of the high / low bands swap
            if who == "model" and (s.side < 0).any():
                s_long, s_short = s[s.side > 0], s[s.side < 0]
                swap = {"dn_q90": "up_q90", "dn_q50": "up_q50", "up_q50": "dn_q50",
                        "up_q90": "dn_q90"}
                t1 = simulate(d, s_long, h, stop, tgt, entry)
                t2 = simulate(d, s_short, h, swap.get(stop), swap.get(tgt), entry)
                tr = pd.concat([t1, t2]).sort_values("signal") if len(t2) else t1
                # re-impose one-position-at-a-time across both directions
                tr = _non_overlapping(tr)
            else:
                tr = simulate(d, s, h, stop, tgt, entry)
            rows.append({"horizon": name, "h": h, "signals": who, "rule": label,
                         **summarize(tr, years)})
    return rows


def _non_overlapping(tr: pd.DataFrame) -> pd.DataFrame:
    keep, busy_until = [], pd.Timestamp.min
    for _, r in tr.iterrows():
        if r.signal >= busy_until:
            keep.append(r)
            busy_until = r.exit_date
    return pd.DataFrame(keep)


def main() -> None:
    t0 = time.time()
    REPORTS.mkdir(exist_ok=True)
    MODELS.mkdir(exist_ok=True)
    d = load_daily()
    X = build_features(d, load_macro()).loc[START:]
    print(f"sessions {len(d)} ({d.index[0].date()} -> {d.index[-1].date()}), "
          f"features {X.shape[1]}, contract {DEFAULT_CONTRACT.symbol} on Tradovate "
          f"'{DEFAULT_PLAN}' plan, round-turn cost ${DEFAULT_CONTRACT.round_turn_cost():.2f}")
    bands, dirs, trades = [], [], []
    for name, h in HORIZONS.items():
        T = forward_targets(d, h).loc[X.index]
        P = walk_forward(X, T, h)
        P.to_parquet(REPORTS / f"phase2_oos_{name}.parquet")
        bands += band_metrics(P, name, h)
        dirs.append(direction_metrics(P, name, h))
        trades += trade_tests(d, P, name, h)

        # final models on all data, for daily use by predict_now.py
        ok = T[["up_atr", "dn_atr", "y_up"]].notna().all(axis=1)
        final = {"features": list(X.columns), "h": h,
                 "up": QuantileBand().fit(X[ok], T.up_atr[ok]),
                 "dn": QuantileBand().fit(X[ok], T.dn_atr[ok]),
                 "dir": DirectionModel(h=h).fit(X[ok], T.y_up[ok]),
                 "trained_through": str(X[ok].index[-1].date())}
        with open(MODELS / f"phase2_{name}.pkl", "wb") as fh:
            pickle.dump(final, fh)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    B, D, TR = pd.DataFrame(bands), pd.DataFrame(dirs), pd.DataFrame(trades)
    B.to_csv(REPORTS / "phase2_highlow_bands.csv", index=False)
    D.to_csv(REPORTS / "phase2_direction.csv", index=False)
    TR.to_csv(REPORTS / "phase2_mgc_backtest.csv", index=False)
    print("\n=== HIGH / LOW BANDS (hit_rate should equal the quantile; skill% > 0 beats ATR baseline)")
    print(B.to_string(index=False))
    print("\n=== DIRECTION")
    print(D.to_string(index=False))
    print("\n=== MGC BACKTEST (1 contract, Tradovate free plan, costs + 1 tick slippage/side)")
    print(TR.to_string(index=False))
    print(f"\ndone in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
