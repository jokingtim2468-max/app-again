"""Build the production model per horizon (models/prod_<horizon>.pkl) from the winners of
scripts/phase2b_long_horizon.py. Needs scripts/train_phase2.py to have run first."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from goldbot.config import HORIZONS, MODELS, REPORTS  # noqa: E402
from goldbot.data import load_daily, load_macro  # noqa: E402
from goldbot.features import build_features  # noqa: E402
from goldbot.production import fit_production  # noqa: E402
from goldbot.targets import forward_targets  # noqa: E402

if __name__ == "__main__":
    d = load_daily()
    X = build_features(d, load_macro()).loc["2006":]
    for name, h in HORIZONS.items():
        # Safe: written by scripts/train_phase2.py on this machine; git-ignored.
        with open(MODELS / f"phase2_{name}.pkl", "rb") as fh:
            full = pickle.load(fh)
        oos = pd.read_parquet(REPORTS / f"phase2_oos_{name}.parquet")
        T = forward_targets(d, h).loc[X.index]
        prod = fit_production(name, h, X, T, oos, full)
        with open(MODELS / f"prod_{name}.pkl", "wb") as fh:
            pickle.dump(prod, fh)
        ks = {s: prod.get(f"{s}_k") for s in ("up", "dn") if prod.get(f"{s}_k")}
        print(f"{name:8s} method={prod['method']:10s} base P(up)={prod['base_p_up']:.3f} "
              f"trained through {prod['trained_through']} {ks if ks else ''}")
