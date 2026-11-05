# Gold Daily Bias Bot — Plan

> Goal: each trading day, output **Bullish / Bearish / No-call** for XAUUSD with a
> calibrated probability, and (later, optionally) let an MT5 Expert Advisor act on it.
>
> Research tool, not financial advice. Nothing here guarantees profit.

---

> **Phase 2 status (2026-11-05):** high/low ranges are calibrated at all four horizons
> (day/week/month/quarter); direction has no proven edge yet; MGC backtests are profitable only
> as much as buy-and-hold was. Details: [reports/PHASE2.md](reports/PHASE2.md).

## 0. What the data already told us (baseline, Nov 2026)

Walk-forward test 2012 → 2026, ~3,600–3,800 out-of-sample days, 0.02% round-trip cost
(full table: `reports/baseline_results.csv`).

| Setup | Model | Accuracy | AUC | Ann. return (1× notional) | Sharpe |
|---|---|---|---|---|---|
| A — predict at daily open (17:00 NY) | always long | 52.2% | 0.50 | −0.2% | −0.01 |
| A | logistic | 51.7% | 0.512 | +5.6% | 0.35 |
| A | LightGBM | 50.8% | 0.511 | −1.4% | −0.09 |
| **B — predict at London open (07:00 UTC), target = NY close vs 07:00** | logistic | 52.2% | 0.531 | +3.0% | 0.22 |
| **B** | **LightGBM** | **53.2%** | **0.531** | **+5.5%** | **0.41** |

**Takeaways**
1. Daily gold direction is close to a coin flip. Anyone selling a "75% accurate" daily
   signal is overfitting or lying. A realistic target is **53–56% accuracy plus a sensible
   no-call rule**.
2. **Waiting for the Asian session helps.** Setup B beats A. `asia_ret`, the weekend
   `gap`, silver's 1-day return, distance from the 200-day SMA and the gold/silver ratio
   were the top features.
3. The edge changes from year to year (B was above 50% in 10 of 14 years; 2022 was 44%).
   The bot needs a **regime filter** and a **confidence threshold**, not always-on trading.
4. The definition of a "day" matters. Futures settle at 13:30 NY and spot closes at
   17:00 NY. Mixing them drops direction agreement from 95% to 86%. Everything here
   uses the **17:00 NY close (the MT5 daily candle)**.

---

## 1. Data inventory (free, already downloaded)

| Data | Source | Span | Granularity |
|---|---|---|---|
| XAUUSD spot | HF `fokan/xauusd-2009-2026` (HistData) | 2009 → 2026-01 | M1 (~6M bars) |
| XAUUSD spot | HF `ZombitX64/...2004-2025` (Kaggle mirror) | 2004 → 2025-09 | 5m / 15m / 30m / 1h / 4h / D / W / M |
| Gold futures GC=F | Yahoo | 2000 → today (D), 2024-06 → today (1h), 60d (5m), 7d (1m) | |
| Drivers | Yahoo | 1995 → today | DXY, US 3m/5y/10y/30y, VIX, **GVZ**, MOVE, S&P 500, silver, platinum, copper, WTI, EURUSD, USDJPY, USDCNY, GLD, GDX, TIP, BTC |
| News headlines | HF `ghbacct/gold-headlines-...` | ~9k labelled (undated) | for training a headline-sentiment model |

Processed files are in `data/processed/` (built by `scripts/build_dataset.py`):
`xau_d1` (5,758 days, 2004-06 → 2026-11-05), `xau_h1` (127k bars), `macro_d1`, `gc_h1`.

**Gaps and what you could give me later (this would help the most):**
1. **MT5 history export from your broker** (XAUUSD M1 or M5, as far back as it goes,
   plus your broker's server-time offset). This replaces the futures-based fill for
   2026-01 → today and matches the prices the bot will actually trade.
2. **Your broker's real spread and commission on XAUUSD** (sets the cost model).
3. **Real yields** (FRED `DFII10`) and **CFTC COT** reports. These are free but blocked from
   this sandbox. A CSV from you, or running the fetcher on your PC, adds them.
4. **Economic calendar** history (FOMC, CPI, NFP, PCE dates). Event days behave
   differently, and the bot should probably no-call or reduce size on them.

---

## 2. Target definition

- **Primary label (3-class):** at decision time T, compare the 17:00 NY close with the
  price at T:
  - Bullish if the return is > +0.25 × ATR14
  - Bearish if the return is < −0.25 × ATR14
  - Neutral otherwise (the bot learns to say "no-call")
- **Decision times to support:** `T=17:00 NY` (daily open, Setup A) and `T=07:00 UTC`
  (London open, Setup B, the default). An optional `T=13:30 UTC` (NY open) run gets
  more information but less of the day left to trade.
- **Secondary label:** the sign of the return plus its magnitude (regression), used for
  position sizing.

---

## 3. Features (strictly point-in-time, so nothing from after T leaks in)

| Group | Examples |
|---|---|
| Price action (D1) | returns over 1/2/3/5/10/20/60 days, candle body and wicks / ATR, close location, RSI 2/14, distance from SMA 10…200, 20-day high/low, up/down streaks |
| Volatility | ATR %, realised vol over 5/20/60 days, **GVZ** level and change, VIX, MOVE |
| Sessions (H1) | Asian return, range and position in range, overnight gap, previous NY session return, London pre-open drift |
| Multi-timeframe | H4/H1 trend slope, weekly position, monthly pivot distance |
| Cross-asset | DXY, EURUSD, USDJPY, US10y/30y changes, 10y-3m curve, real-yield proxy (TIP), silver, GDX/GLD ratio, S&P 500, oil, copper, BTC |
| Positioning / flows (to add) | CFTC COT managed-money net, GLD holdings change |
| Calendar | day of week, month, **event-day flags** (FOMC, CPI, NFP), days to month end |
| Sentiment (phase 3) | FinBERT fine-tuned on the 9k labelled headlines, applied to a live RSS feed (Kitco, Reuters, FXStreet) for the previous 24 hours |

---

## 4. Modelling

1. **Baselines:** always-long, yesterday's direction, logistic regression (already done).
2. **Main model:** LightGBM (multi-class) with strong regularisation, monotone
   constraints where theory is clear (e.g. a stronger DXY is bearish for gold).
3. **Ensemble:** average of logistic, LightGBM and a small temporal CNN/GRU on 60 days of H1
   bars. Keep a deep model only if it adds out-of-sample AUC.
4. **Calibration:** isotonic regression on the walk-forward predictions, so that "62%"
   really means about 62%.
5. **Regime filter:** an HMM or a simple rule (GVZ percentile × trend strength) that switches
   the bot off in regimes where it has historically lost money.
6. **No-call rule:** publish a call only when the calibrated probability is ≥ 0.56. On the
   baseline this cuts calls to ~40–60% of days with ~53% accuracy; the target is ≥ 55%.

---

## 5. Validation (decides go / no-go)

- **Walk-forward**, retrained yearly (or monthly), with a **purge and embargo** of 5 days
  between train and test.
- **Locked hold-out:** never touch 2025-07 → today until the final check.
- **Metrics:** AUC, Brier score, accuracy on calls, coverage (% of days called), P&L
  after realistic spread and commission plus swap, max drawdown, Sharpe, and worst year.
- **Robustness:** shuffle-label test (the edge must vanish), feature-drop ablation,
  results on futures vs spot, and results by GVZ regime.
- **Go-live gate:** hold-out AUC ≥ 0.53, call accuracy ≥ 55%, positive in at least 70% of
  years, Sharpe ≥ 0.5 after costs, and max drawdown ≤ 15% at the planned risk level.

---

## 6. Is it worth running? (profit and cost check)

Numbers per **0.01 lot (1 oz ≈ $4,090 notional)**, using the baseline Setup B result
(+5.5% a year on notional, Sharpe 0.41):

| Item | Per year |
|---|---|
| Expected gross edge | ≈ +$225 |
| Typical swing (1 standard deviation of the yearly result) | ≈ ±$550 |
| VPS (if used) | −$120 to −$240 |
| Running on your own PC (a few minutes of compute a day) | ≈ −$5 to −$15 of electricity |
| Data | $0 (all free sources) |

**Verdict at the current baseline:** the edge is too thin. One year in three could lose
money, and a VPS would eat most of the profit on small lot sizes. **Do not trade it live
yet.** Run it on your own PC (almost free) in **signal-only or demo mode** until it passes
the go-live gate in section 5. Only after that, size positions with
**≤ 0.5% account risk per trade**, a daily stop, and a kill switch after an 8% drawdown.

### 6b. If this runs on a futures prop firm (e.g. Lucid Trading)

Your hardware plan mentions Lucid Trading, which is a **futures** prop firm. If that is
where the signal is traded:
- The instrument is **MGC** (micro gold, 10 oz, $1 per $0.10 move) or **GC** (100 oz), not
  the XAUUSD CFD. One MGC contract is about $40k notional, so the yearly edge at baseline is
  ≈ +$2.2k and the yearly swing is ≈ ±$5.5k.
- CME gold trades 18:00–17:00 NY, the same window as the spot "day" used here, so labels
  carry over. Retrain on GC=F hourly bars (`data/processed/gc_h1.parquet`) plus your data
  feed's history.
- **Prop rules come first:** trailing or end-of-day drawdown, a daily loss limit, the
  consistency rule, news-trading bans, and whether bots or automation are allowed. Size so
  that a 3-standard-deviation day stays inside the daily loss limit.
- Execution would go through the firm's platform (Tradovate/Rithmic/NinjaTrader), not MT5.
  The signal service stays the same; only the order bridge changes.

---

## 7. Architecture

```
fetch_data.py  ──►  build_dataset.py  ──►  features.py  ──►  train.py (walk-forward)
                                                               │
                                                     models/ + calibration
                                                               │
     MT5 terminal ◄── MetaTrader5 python pkg ◄── daily_signal.py (scheduled 07:00 UTC)
          │                                               │
   GoldBias.mq5 panel (shows call + prob)        logs/ + Telegram/Discord alert
```

- **Language:** Python 3.11+, with LightGBM, scikit-learn and the MetaTrader5 package.
- **Live data:** read bars from your MT5 terminal with `copy_rates_from_pos` so the bot uses
  your broker's own prices and server time.
- **Display:** an MQL5 indicator panel on the chart showing "Bullish 61% / Bearish /
  No-call", read from a CSV the Python service writes.
- **Execution (optional, phase 5):** an EA places one trade at decision time with an
  ATR-based stop and exit at the NY close. A demo account comes first, always.
- **Install:** a Windows setup wizard (Inno Setup) that installs the Python runtime, the
  service and the MT5 indicator files, plus **auto-update** from GitHub Releases.
- **Retraining:** a monthly job retrains, re-validates against the gate, and deploys only
  if the new model beats the old one on the latest out-of-sample window.

---

## 8. Roadmap and estimates

| Phase | Work | Estimate |
|---|---|---|
| 1 ✅ | Free data collection, cleaning, baseline study | "1 h" |
| 2 ✅ | `goldbot` package, Tradovate MGC costs, multi-horizon high/low bands, purged walk-forward, conformal calibration, MGC backtests, `predict_now.py` (see [reports/PHASE2.md](reports/PHASE2.md)) | "2 h" |
| 2c | London-open (07:00 UTC) day model, 1OZ contract sizing, day-horizon bracket on intraday bars | "2–3 h" |
| 3 | Add COT, real yields, event calendar, GVZ regime, headline sentiment model | "4–6 h" |
| 4 | Ensemble and regime filter, hold-out test, go/no-go report | "3–4 h" |
| 5 | `daily_signal.py`, MT5 data bridge, MQL5 panel, alerts | "3–4 h" |
| 6 | Windows installer, auto-update, monthly retrain job | "3–4 h" |
| 7 | 3 months of demo forward test, then review before any live money | "3 months (calendar)" |

---

## 9. Risks and limits

- **Overfitting:** hundreds of features against ~5k days means the hold-out and the
  shuffle test are mandatory.
- **Regime change:** central-bank buying and geopolitics drove 2024–26 and broke older
  relationships (for example, gold rising alongside real yields).
- **Data mismatch:** HistData, Zombit and broker feeds differ by cents to dollars and in
  server time. The final model must be retrained on your broker's data.
- **Event risk:** FOMC, CPI and NFP can move gold 2–3% in minutes. The bot should no-call
  or cut size on those days.
- **Execution:** swap (financing) costs on held positions, spread widening at the rollover
  and on news.
