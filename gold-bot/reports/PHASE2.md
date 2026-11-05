# Phase 2 results — multi-horizon highs / lows / direction, traded as MGC on Tradovate

Run date 2026-11-05. Walk-forward with yearly retraining, purge and embargo, out-of-sample
2012 → 2026-11. Costs: Tradovate free plan, MGC all-in **$1.22 per side** plus 1 tick of
slippage per side, so **$4.44 per round trip**. Research only, not financial advice.

## 1. Highs and lows (what the bot is best at)

Each evening the bot forecasts how far above and below tonight's close price will stretch
over the next 1, 5, 21 and 63 sessions. q50 is the most likely extreme; q10 to q90 is the 80% range.

| Horizon | Winning method | 80% range catches (target 80%) | Typical miss on the q50 level |
|---|---|---|---|
| Day | full LightGBM + conformal widening | 80.8% | $9.75/oz ≈ $98 per MGC |
| Week | simple LightGBM (15 inputs, 4-leaf trees) | 77.3% | $21.92/oz |
| Month | volatility-scaled range (no ML) | 77.6% | $49.10/oz |
| Quarter | volatility-scaled range (no ML) | 78.0% | $88.89/oz |

- The 134-feature model **overfit** the month and quarter horizons. Its 80% range caught
  only 51% and 40% of outcomes. Overlapping 63-day windows give only about 85 independent quarters.
- For month and quarter, a simple volatility rule beat every model. This is now the
  production method (`goldbot/production.py`).

## 2. Direction (bullish / bearish)

| Horizon | Model accuracy | Always guessing "up" | Best Brier score |
|---|---|---|---|
| Day | 52.4% | 52.7% | historical up-rate |
| Week | 52.3–54.0% | 54.2% | historical up-rate |
| Month | 55.9–56.3% | 54.6% | historical up-rate |
| Quarter | 55.3–58.3% (AUC 0.62) | 61.3% | historical up-rate |

No direction model has beaten the plain historical up-rate on Brier score yet. The bias is
shown as **experimental**.

## 3. MGC backtest (1 contract, fixed simulator, `reports/phase2_mgc_backtest.csv`)

| Horizon | Best model rule | $/yr | Max drawdown | Buy and hold (same rule) $/yr / drawdown |
|---|---|---|---|---|
| Day | stop at q90 low, exit at close | +$210 | −$5.1k | +$396 / −$18.1k |
| Week | stop at q90 low, hold 5 days | +$1,388 | −$5.5k | +$1,538 / −$14.3k |
| Month | hold 21 days | +$1,218 | −$7.2k | +$1,612 / −$10.9k |
| Quarter | hold 63 days (56 trades only) | +$2,400 | −$5.4k | +$1,941 / −$8.0k |

**Verdict:** the profits come mostly from gold's 2012–2026 bull market. The model mainly
halves drawdowns by being flat or short some of the time; it does not prove a forecasting
edge. **Not ready for live money.**

## 4. Position size reality on Tradovate

Stops placed at the q90 extreme (2026-11-04 forecast, MGC ≈ $4,110):

| Horizon | Stop distance | Risk per MGC | Account needed to risk 1% per trade |
|---|---|---|---|
| Day | $77 | ≈ $774 | ≈ $77k |
| Week | $219 | ≈ $2,195 | ≈ $220k |
| Month | $472 | ≈ $4,720 | ≈ $472k |

For a small account or a prop evaluation (typically $2–3k of trailing drawdown on a $50k
account), even **one MGC with a statistically sensible stop is too big** beyond the
daily horizon. Options: (a) trade the day horizon only, (b) use CME's 1-ounce gold
contract (1OZ, one tenth of MGC) if Tradovate lists it, or (c) use the forecasts as levels for
discretionary entries rather than as an automatic system.

## 5. Bug found and fixed during this phase

The first backtest blocked a new signal at the same close where the previous trade
exited, so one-day strategies traded only every other day. In the very volatile 2025–26
market this flipped results (buy and hold appeared to lose $1.7k a year). Fixed in
`goldbot/backtest.py`; all numbers above use the corrected simulator.

## 6. Tradovate running costs

| Item | Cost |
|---|---|
| Free plan | $0/month, MGC $1.22 per side all-in |
| Monthly plan | $99/month, MGC ≈ $1.12 per side: not worth it below ~1,000 sides a month |
| Real-time data through the Tradovate API | **CME license, reported at $290–$500/month**. Avoided: the bot runs once a day on free end-of-day data |
| Compute | your own PC, ≈ $15–22/yr of power |
