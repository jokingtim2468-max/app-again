"""Production forecasters: the method that won the Phase 2b walk-forward test per horizon.

    day      full LightGBM bands, widened by conformal factors from out-of-sample errors
    week     simple LightGBM bands (15 features, 4-leaf trees)
    month    volatility-scaled historical ranges (no ML: it beat every model)
    quarter  volatility-scaled historical ranges

Direction: no model beat the plain historical up-rate on Brier score, so the published
probability is the base rate, and the model's probability is shown as "experimental".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import QUANTILES
from .models import SIMPLE_FEATURES, SIMPLE_PARAMS, DirectionModel, QuantileBand, conformal_scale

BAND_METHOD = {"day": "full+conf", "week": "simple", "month": "vol", "quarter": "vol"}
QCOLS = [f"q{int(q * 100)}" for q in QUANTILES]


def vol_scale(X: pd.DataFrame, h: int) -> pd.Series:
    """Converts ATR units into units of (63-day vol scaled to h sessions)."""
    return (X["vol_63"] * np.sqrt(h / 252)) / X["atr_pct"]


def fit_production(name: str, h: int, X: pd.DataFrame, T: pd.DataFrame,
                   oos: pd.DataFrame | None, full_models: dict | None) -> dict:
    ok = T[["up_atr", "dn_atr", "y_up"]].notna().all(axis=1)
    Xo, To = X[ok], T[ok]
    method = BAND_METHOD[name]
    m: dict = {"name": name, "h": h, "method": method, "features": list(X.columns),
               "base_p_up": float(To.y_up.mean()), "trained_through": str(Xo.index[-1].date())}
    for side in ("up", "dn"):
        y = To[f"{side}_atr"]
        if method == "full+conf":
            m[side] = full_models[side]
            m[f"{side}_k"] = {c: conformal_scale(oos[f"{side}_atr"].to_numpy(),
                                                 oos[f"{side}_{c}"].to_numpy(), q)
                              for q, c in zip(QUANTILES, QCOLS)}
        elif method == "simple":
            m[side] = QuantileBand(params=SIMPLE_PARAMS).fit(Xo[SIMPLE_FEATURES], y)
        else:  # vol
            vs = vol_scale(Xo, h)
            m[side] = {c: float((y / vs).quantile(q)) for q, c in zip(QUANTILES, QCOLS)}
    m["dir"] = full_models["dir"] if full_models else DirectionModel(h=h).fit(Xo, To.y_up)
    return m


def predict_bands(m: dict, x: pd.DataFrame) -> dict[str, pd.Series]:
    out = {}
    for side in ("up", "dn"):
        if m["method"] == "full+conf":
            p = m[side].predict(x).iloc[0]
            p = pd.Series({c: p[c] * m[f"{side}_k"][c] for c in QCOLS})
        elif m["method"] == "simple":
            p = m[side].predict(x[SIMPLE_FEATURES]).iloc[0]
        else:
            vs = float(vol_scale(x, m["h"]).iloc[0])
            p = pd.Series({c: m[side][c] * vs for c in QCOLS})
        out[side] = p.sort_values().set_axis(QCOLS)
    return out
