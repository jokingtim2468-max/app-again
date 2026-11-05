"""Phase 2b: fix long-horizon overfitting.

Compares, walk-forward (purged, yearly), for every horizon:
  bands:      full LightGBM (134 feats)  vs  simple LightGBM (15 feats, 4-leaf trees)
              vs ATR-multiple baseline   vs  vol_63-scaled baseline
              each with and without conformal widening learned from PRIOR years only
  direction:  full ensemble vs simple logistic (15 feats) vs trend rule vs always long
Research only, not financial advice.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from goldbot.config import HORIZONS, QUANTILES, REPORTS  # noqa: E402
from goldbot.cv import yearly_purged_splits  # noqa: E402
from goldbot.data import load_daily, load_macro  # noqa: E402
from goldbot.features import build_features  # noqa: E402
from goldbot.models import (SIMPLE_FEATURES, SIMPLE_PARAMS, QuantileBand,  # noqa: E402
                            conformal_scale, pinball)
from goldbot.targets import forward_targets  # noqa: E402


def run(h: int, name: str, X: pd.DataFrame, T: pd.DataFrame) -> tuple[list, list, pd.DataFrame]:
    ok = T[["up_atr", "dn_atr", "y_up"]].notna().all(axis=1)
    Xv, Tv = X[ok], T[ok]
    # vol_63-scaled target: extension in units of (annual vol * sqrt(h/252) * close) / ATR
    vscale = (Xv["vol_63"] * np.sqrt(h / 252)) / Xv["atr_pct"]
    full = pd.read_parquet(REPORTS / f"phase2_oos_{name}.parquet")
    preds = []
    for year, tr, te in yearly_purged_splits(Xv.index, h):
        Xtr, Ttr, Xte = Xv.iloc[tr], Tv.iloc[tr], Xv.iloc[te]
        r = pd.DataFrame(index=Xte.index)
        for side in ("up", "dn"):
            y = Ttr[f"{side}_atr"]
            band = QuantileBand(params=SIMPLE_PARAMS).fit(Xtr[SIMPLE_FEATURES], y) \
                .predict(Xte[SIMPLE_FEATURES])
            for q in QUANTILES:
                c = f"q{int(q * 100)}"
                r[f"simple_{side}_{c}"] = band[c].to_numpy()
                r[f"atr_{side}_{c}"] = y.quantile(q)
                r[f"vol_{side}_{c}"] = (y / vscale.iloc[tr]).quantile(q) * vscale.iloc[te]
                r[f"full_{side}_{c}"] = full.loc[Xte.index, f"{side}_{c}"]
        # direction
        lr = make_pipeline(StandardScaler(), LogisticRegression(C=0.01, max_iter=3000))
        lr.fit(Xtr[SIMPLE_FEATURES].fillna(0), Ttr.y_up)
        r["p_simple"] = lr.predict_proba(Xte[SIMPLE_FEATURES].fillna(0))[:, 1]
        r["p_full"] = full.loc[Xte.index, "p_up"]
        r["p_base"] = Ttr.y_up.mean()
        r["year"] = year
        preds.append(r.join(Tv.iloc[te]))
    P = pd.concat(preds)
    # trend rule: long when above the 200-day average and 63-day slope is up
    trend = ((X.loc[P.index, "dist_sma200"] > 0) & (X.loc[P.index, "slope_63"] > 0))
    P["p_trend"] = np.where(trend, 0.6, 0.4)

    # conformal widening per year from PRIOR years' out-of-sample errors
    for m in ("full", "simple", "atr", "vol"):
        for side in ("up", "dn"):
            for q in QUANTILES:
                c = f"q{int(q * 100)}"
                adj = P[f"{m}_{side}_{c}"].copy()
                for y in P.year.unique():
                    past = P[(P.year < y) & (P.index < P[P.year == y].index[0] -
                                             pd.Timedelta(days=int(h * 1.5)))]
                    k = conformal_scale(past[f"{side}_atr"].to_numpy(),
                                        past[f"{m}_{side}_{c}"].to_numpy(), q)
                    adj[P.year == y] = P.loc[P.year == y, f"{m}_{side}_{c}"] * k
                P[f"{m}+conf_{side}_{c}"] = adj

    band_rows, dir_rows = [], []
    E = P[P.year >= 2014]  # conformal needs >= 2 prior years
    for m in ("full", "simple", "atr", "vol", "full+conf", "simple+conf", "atr+conf",
              "vol+conf"):
        tot_pl, cov = 0.0, []
        for side in ("up", "dn"):
            y = E[f"{side}_atr"].to_numpy()
            for q in QUANTILES:
                tot_pl += pinball(y, E[f"{m}_{side}_q{int(q * 100)}"].to_numpy(), q)
            cov.append(((y >= E[f"{m}_{side}_q10"]) & (y <= E[f"{m}_{side}_q90"])).mean())
        mae = np.mean([np.mean(np.abs(E[f"{s}_atr"] - E[f"{m}_{s}_q50"]) * E.atr)
                       for s in ("up", "dn")])
        band_rows.append({"horizon": name, "method": m, "pinball_sum": round(tot_pl, 4),
                          "cover_80%band": round(float(np.mean(cov)), 3),
                          "mae_$_median": round(float(mae), 2)})
    for m in ("full", "simple", "trend", "base"):
        p = E[f"p_{m}"]
        dir_rows.append({"horizon": name, "method": m,
                         "auc": round(roc_auc_score(E.y_up, p), 3) if p.nunique() > 1 else 0.5,
                         "brier": round(brier_score_loss(E.y_up, p), 4),
                         "acc": round(float(((p > .5) == (E.y_up == 1)).mean()), 3)})
    return band_rows, dir_rows, P


def main() -> None:
    d = load_daily()
    X = build_features(d, load_macro()).loc["2006":]
    B, D = [], []
    for name, h in HORIZONS.items():
        T = forward_targets(d, h).loc[X.index]
        b, dr, P = run(h, name, X, T)
        P.to_parquet(REPORTS / f"phase2b_oos_{name}.parquet")
        B += b
        D += dr
        print(f"{name} done")
    B, D = pd.DataFrame(B), pd.DataFrame(D)
    for df in (B, D):
        best = df.groupby("horizon")[df.columns[2]].transform("min")
        df["best"] = np.where(df[df.columns[2]] == best, "<-", "")
    B.to_csv(REPORTS / "phase2b_bands.csv", index=False)
    D.to_csv(REPORTS / "phase2b_direction.csv", index=False)
    pd.set_option("display.width", 200)
    print("\n=== HIGH/LOW BANDS 2014-2026 (lower pinball = better; 80% band should cover 0.80)")
    print(B.to_string(index=False))
    print("\n=== DIRECTION 2014-2026 (lower brier = better)")
    print(D.to_string(index=False))


if __name__ == "__main__":
    main()
