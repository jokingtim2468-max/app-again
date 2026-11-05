"""Models: quantile bands for future highs/lows + calibrated direction probability."""
from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import QUANTILES

GB_PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=100,
                 subsample=0.8, subsample_freq=1, colsample_bytree=0.6, reg_lambda=5.0,
                 verbose=-1)


@dataclass
class QuantileBand:
    """LightGBM quantile regressors for one target (e.g. up_atr) at several quantiles."""
    quantiles: tuple[float, ...] = QUANTILES
    models: dict[float, lgb.LGBMRegressor] = field(default_factory=dict)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "QuantileBand":
        for q in self.quantiles:
            m = lgb.LGBMRegressor(objective="quantile", alpha=q, **GB_PARAMS)
            m.fit(X, y)
            self.models[q] = m
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        P = np.column_stack([self.models[q].predict(X) for q in self.quantiles])
        P = np.sort(np.clip(P, 0, None), axis=1)  # extensions are >= 0, no quantile crossing
        return pd.DataFrame(P, index=X.index, columns=[f"q{int(q * 100)}" for q in self.quantiles])


@dataclass
class DirectionModel:
    """Average of regularised logistic + LightGBM, isotonic-calibrated on a held-out tail."""
    h: int = 1
    cal_frac: float = 0.25
    lr: object = None
    gb: object = None
    iso: IsotonicRegression | None = None

    def _raw(self, X: pd.DataFrame) -> np.ndarray:
        p_lr = self.lr.predict_proba(X.fillna(0))[:, 1]
        p_gb = self.gb.predict_proba(X)[:, 1]
        return (p_lr + p_gb) / 2

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "DirectionModel":
        n = len(X)
        n_cal = int(n * self.cal_frac)
        fit_end = n - n_cal - self.h  # purge so fit-targets don't overlap the calibration tail
        Xf, yf = X.iloc[:fit_end], y.iloc[:fit_end]
        self.lr = make_pipeline(StandardScaler(), LogisticRegression(C=0.02, max_iter=3000))
        self.lr.fit(Xf.fillna(0), yf)
        self.gb = lgb.LGBMClassifier(**GB_PARAMS).fit(Xf, yf)
        raw = self._raw(X.iloc[n - n_cal:])
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.02, y_max=0.98)
        self.iso.fit(raw, y.iloc[n - n_cal:])
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.iso.predict(self._raw(X))


def pinball(y: np.ndarray, q_pred: np.ndarray, q: float) -> float:
    e = y - q_pred
    return float(np.mean(np.maximum(q * e, (q - 1) * e)))
