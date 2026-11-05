"""Baseline study: how predictable is XAUUSD daily direction?

Two prediction times are tested (features use ONLY data available at that time):
  A) "Daily open"  - at 17:00 NY (00:00 MT5 server).  Target: Close > Open.
  B) "London open" - at 07:00 UTC, after the Asian session. Target: NY close > 07:00 price.

Walk-forward: train on all years before Y, test on year Y (2012 -> 2026).
Models: always-long, logistic regression, LightGBM.
Cost model: 0.02% round trip (~$0.60 spread+commission at $3000 gold).

This is research, not financial advice.
"""
from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data" / "processed"
COST = 0.0002


def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def price_features(d: pd.DataFrame) -> pd.DataFrame:
    """Features for day t computed from bars up to and including t-1."""
    c, h, l, o = d.Close, d.High, d.Low, d.Open
    r = np.log(c).diff()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    f = pd.DataFrame(index=d.index)
    for k in (1, 2, 3, 5, 10, 20, 60):
        f[f"ret_{k}"] = np.log(c / c.shift(k))
    f["body"] = (c - o) / atr
    f["upper_wick"] = (h - np.maximum(o, c)) / atr
    f["lower_wick"] = (np.minimum(o, c) - l) / atr
    f["range_atr"] = (h - l) / atr
    f["close_loc"] = (c - l) / (h - l)
    f["atr_pct"] = atr / c
    f["vol_20"] = r.rolling(20).std()
    f["vol_ratio"] = r.rolling(5).std() / r.rolling(60).std()
    f["rsi_14"] = rsi(c)
    f["rsi_2"] = rsi(c, 2)
    for n in (10, 20, 50, 100, 200):
        f[f"dist_sma{n}"] = (c / c.rolling(n).mean() - 1) / f["atr_pct"]
    f["dist_hi20"] = (c / h.rolling(20).max() - 1) / f["atr_pct"]
    f["dist_lo20"] = (c / l.rolling(20).min() - 1) / f["atr_pct"]
    f["up_streak"] = (r > 0).astype(int).groupby((r <= 0).cumsum()).cumsum()
    f["dn_streak"] = (r < 0).astype(int).groupby((r >= 0).cumsum()).cumsum()
    f = f.shift(1)  # everything known only after the prior close
    f["dow"] = d.index.day_of_week
    f["month"] = d.index.month
    f["gap"] = np.log(o / c.shift(1))  # weekend/holiday gap at the open
    return f


def macro_features(dates: pd.DatetimeIndex) -> pd.DataFrame:
    m = pd.read_parquet(P / "macro_d1.parquet").ffill()
    f = pd.DataFrame(index=m.index)
    for col in ("dxy", "spx", "silver_fut", "wti_fut", "copper_fut", "eurusd", "usdjpy",
                "tip", "gdx", "gld"):
        f[f"{col}_r1"] = np.log(m[col]).diff()
        f[f"{col}_r5"] = np.log(m[col]).diff(5)
    for col in ("us10y", "us3m", "us30y"):
        f[f"{col}_d1"] = m[col].diff()
        f[f"{col}_d5"] = m[col].diff(5)
    f["curve_10y3m"] = m["us10y"] - m["us3m"]
    f["vix"] = m["vix"]
    f["vix_d1"] = m["vix"].diff()
    f["gold_silver_ratio"] = m["gold_fut"] / m["silver_fut"]
    # gold day t starts 17:00 NY on t-1 -> use the latest macro close strictly before t
    left = pd.DataFrame({"date": dates})
    right = f.reset_index().rename(columns={f.index.name or "index": "mdate"})
    right = right.rename(columns={right.columns[0]: "mdate"})
    out = pd.merge_asof(left.sort_values("date"), right.sort_values("mdate"),
                        left_on="date", right_on="mdate", allow_exact_matches=False)
    return out.set_index("date").drop(columns="mdate")


def london_open_features(d1: pd.DataFrame) -> pd.DataFrame:
    """Asian-session features + target for prediction at 07:00 UTC."""
    h = pd.read_parquet(P / "xau_h1.parquet")
    day = (h.index.tz_convert("America/New_York") + pd.Timedelta(hours=7)).normalize().tz_localize(None)
    h = h.assign(day=day, hr=h.index.hour)
    asia = h[(h.hr >= 22) | (h.hr < 7)]
    g = asia.groupby("day")
    a = pd.DataFrame({"a_open": g.Open.first(), "a_high": g.High.max(), "a_low": g.Low.min(),
                      "a_last": g.Close.last()})
    lo = h[h.hr == 7].groupby("day").Open.first().rename("p07")
    a = a.join(lo, how="inner")
    out = pd.DataFrame(index=a.index)
    out["asia_ret"] = np.log(a.p07 / a.a_open)
    out["asia_range"] = np.log(a.a_high / a.a_low)
    out["asia_loc"] = (a.p07 - a.a_low) / (a.a_high - a.a_low)
    out["p07"] = a.p07
    out = out.join(d1[["Close"]], how="inner")
    out["y_lo"] = (out.Close > out.p07).astype(int)
    out["ret_lo"] = np.log(out.Close / out.p07)
    return out.drop(columns=["Close", "p07"])


def walk_forward(X: pd.DataFrame, y: pd.Series, ret: pd.Series, name: str) -> pd.DataFrame:
    rows, preds = [], []
    for year in range(2012, X.index.year.max() + 1):
        tr = X.index.year < year
        te = X.index.year == year
        if te.sum() < 20:
            continue
        Xtr, ytr, Xte = X[tr], y[tr], X[te]
        lr = make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=2000))
        lr.fit(Xtr.fillna(0), ytr)
        gb = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.02, num_leaves=15,
                                min_child_samples=100, subsample=0.8, subsample_freq=1,
                                colsample_bytree=0.7, reg_lambda=5.0, verbose=-1)
        gb.fit(Xtr, ytr)
        preds.append(pd.DataFrame({"y": y[te], "ret": ret[te],
                                   "p_lr": lr.predict_proba(Xte.fillna(0))[:, 1],
                                   "p_gb": gb.predict_proba(Xte)[:, 1]}, index=Xte.index))
    P_ = pd.concat(preds)
    for model in ("long", "p_lr", "p_gb"):
        p = pd.Series(0.51, index=P_.index) if model == "long" else P_[model]
        side = np.where(p > 0.5, 1, -1)
        pnl = side * P_.ret - COST
        conf = (p - 0.5).abs() >= 0.05
        rows.append({
            "setup": name, "model": model, "n": len(P_),
            "acc": round(float(((p > 0.5).astype(int) == P_.y).mean()), 4),
            "auc": round(roc_auc_score(P_.y, p), 4) if model != "long" else 0.5,
            "ann_ret%": round(float(pnl.mean() * 252 * 100), 1),
            "sharpe": round(float(pnl.mean() / pnl.std() * np.sqrt(252)), 2),
            "conf_trades%": round(float(conf.mean() * 100), 1),
            "conf_acc": round(float(((p[conf] > 0.5).astype(int) == P_.y[conf]).mean()), 4)
            if conf.any() else np.nan,
        })
    return pd.DataFrame(rows), P_


def main() -> None:
    d1 = pd.read_parquet(P / "xau_d1.parquet")
    today = pd.Timestamp.now(tz="America/New_York")
    if today.hour < 17:  # drop the still-forming session
        d1 = d1[d1.index < today.normalize().tz_localize(None)]
    y = (d1.Close > d1.Open).astype(int)
    ret = np.log(d1.Close / d1.Open)
    print(f"days {len(d1)}  {d1.index[0].date()} -> {d1.index[-1].date()}  "
          f"up-day base rate {y.mean():.3f}")
    yr = y.groupby(y.index.year).mean().round(3)
    print("up-day rate by year:", dict(yr.tail(8)))

    pf = price_features(d1)
    mf = macro_features(d1.index)
    X = pf.join(mf).loc["2006":]
    X = X.replace([np.inf, -np.inf], np.nan).dropna(thresh=int(X.shape[1] * 0.8))
    res_a, Pa = walk_forward(X, y[X.index], ret[X.index], "A_daily_open")

    lo = london_open_features(d1)
    Xb = X.join(lo.drop(columns=["y_lo", "ret_lo"]), how="inner")
    Xb = Xb.replace([np.inf, -np.inf], np.nan)
    res_b, Pb = walk_forward(Xb, lo.y_lo[Xb.index], lo.ret_lo[Xb.index], "B_london_open")

    res = pd.concat([res_a, res_b])
    pd.set_option("display.width", 200)
    print(res.to_string(index=False))
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    res.to_csv(out / "baseline_results.csv", index=False)
    by_year = Pa.assign(hit=((Pa.p_gb > 0.5).astype(int) == Pa.y)).groupby(Pa.index.year).hit.mean()
    by_year_b = Pb.assign(hit=((Pb.p_gb > 0.5).astype(int) == Pb.y)).groupby(Pb.index.year).hit.mean()
    pd.DataFrame({"A_gb_acc": by_year, "B_gb_acc": by_year_b}).round(3).to_csv(
        out / "baseline_by_year.csv")
    print(pd.DataFrame({"A_gb_acc": by_year, "B_gb_acc": by_year_b}).round(3).T.to_string())

    # feature importance on full sample for B (descriptive only)
    gb = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.02, num_leaves=15,
                            min_child_samples=100, verbose=-1).fit(Xb, lo.y_lo[Xb.index])
    imp = pd.Series(gb.booster_.feature_importance("gain"), index=Xb.columns)
    imp = (imp / imp.sum()).sort_values(ascending=False).head(15).round(3)
    imp.to_csv(out / "feature_importance_B.csv")
    print("top features (B):", dict(imp))


if __name__ == "__main__":
    main()
