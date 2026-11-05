"""Re-run the MGC backtests from saved walk-forward predictions (reports/phase2_oos_*.parquet)
without retraining. Usage: python scripts/backtest_phase2.py [day week month quarter]"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from goldbot.config import HORIZONS, REPORTS  # noqa: E402
from goldbot.data import load_daily  # noqa: E402
from train_phase2 import trade_tests  # noqa: E402

if __name__ == "__main__":
    names = sys.argv[1:] or list(HORIZONS)
    d = load_daily()
    rows = []
    for n in names:
        f = REPORTS / f"phase2_oos_{n}.parquet"
        if f.exists():
            rows += trade_tests(d, pd.read_parquet(f), n, HORIZONS[n])
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(R.to_string(index=False))
    if set(names) == set(HORIZONS):
        R.to_csv(REPORTS / "phase2_mgc_backtest.csv", index=False)
