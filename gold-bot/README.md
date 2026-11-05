# gold-bot — XAUUSD daily bias research

Predicts whether gold (XAUUSD) will be **bullish or bearish for the day**. The roadmap,
the findings so far and the go/no-go rules are in **[PLAN.md](PLAN.md)**.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install pandas pyarrow scikit-learn lightgbm yfinance requests
python scripts/fetch_data.py --m1     # ~620 MB of free data into data/raw/ (git-ignored)
python scripts/build_dataset.py       # -> data/processed/*.parquet (committed)
python scripts/baseline.py            # phase 1 walk-forward baseline -> reports/
python scripts/train_phase2.py        # phase 2 multi-horizon models (~4 min)
python scripts/phase2b_long_horizon.py  # picks the best high/low method per horizon
python scripts/finalize_models.py     # -> models/prod_*.pkl
python scripts/predict_now.py         # tonight's MGC levels -> signals/latest.json
```

Run `predict_now.py` after the 17:00 ET close. It prints the expected high and low ranges
for the next day, week, month and quarter in MGC (Tradovate) prices.

## Layout

| Path | What |
|---|---|
| `scripts/fetch_data.py` | Downloads XAUUSD M1 to monthly bars (Hugging Face), gold futures and 20 macro series (Yahoo), and gold headlines |
| `scripts/build_dataset.py` | Builds spot hourly/daily bars on the 17:00 New York (MT5) daily close and merges the sources |
| `scripts/baseline.py` | Walk-forward baseline (logistic regression and LightGBM, 2012–2026) |
| `goldbot/` | Package: Tradovate/MGC config, features, targets, purged CV, models, backtest, production |
| `scripts/train_phase2.py` | Multi-horizon walk-forward and MGC backtests |
| `scripts/phase2b_long_horizon.py` | Compares full, simple and volatility-only high/low methods |
| `scripts/finalize_models.py`, `scripts/predict_now.py` | Production models and nightly forecast |
| `data/processed/` | `xau_d1`, `xau_h1`, `macro_d1`, `gc_h1` parquet files |
| `reports/` | Baseline results, accuracy by year, feature importance |

Research only — not financial advice.
