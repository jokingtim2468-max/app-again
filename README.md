# Tickbench

A Windows desktop app for backtesting trading bots. Drop in a strategy file, load price history, and see every trade it would have taken, why it took it, and how the account would have done.

## Script types (detected automatically)

| Type | What runs |
|---|---|
| Pine Script v4 / v5 / v6 | `strategy()` scripts: `ta.*`, `math.*`, `input.*`, `strategy.entry/exit/close/order`, `var`, functions, tuples, `switch`, loops, arrays |
| MQL4 / MQL5 Expert Advisors | `OnInit/OnTick/OnDeinit` or `start()`, `iMA/iRSI/iMACD/iATR/iBands/iStochastic/iCCI`, `CopyBuffer`, `OrderSend/OrderSelect/OrderClose/OrderModify`, `CTrade`, positions, `MqlTick/MqlRates` |
| Tradovate custom indicators | Code Explorer `module.exports = { calculator, params, plots }` with Tradovate's own `tools/` helpers bundled; a signal rule turns plots into trades |
| Tradovate API strategies | AutoTrade-style `class X extends Strategy` with `init`/`next(state, [event, payload])`; `startOrderStrategy` brackets, `placeOrder`, `placeOCO`, `liquidatePosition` |
| Python | Native `on_bar(ctx)`, plus unchanged **backtesting.py** and **backtrader** strategies |
| JavaScript | `module.exports = { params, init(ctx), onBar(ctx) }`, run in a sealed V8 sandbox |
| No-code rules | JSON or YAML: indicators, crossing/threshold conditions, stops and targets |

The detector scores each file on content (not just extension) and shows its evidence; you can override it.

The same SMA-cross strategy is included in every format under `engine/examples/strategies`, and the test suite checks that all of them produce identical trades.

## Price data
- **CSV**: MetaTrader 4/5 history exports, TradingView exports, Yahoo downloads, or any Date/Open/High/Low/Close/Volume file.
- **Yahoo Finance**: free download, cached on your PC (stocks, ETFs, futures like `ES=F`, forex like `EURUSD`, crypto like `BTC-USD`).
- Resample to a higher timeframe and pick a date range.

## Results
Net profit, CAGR, buy-and-hold comparison, Sharpe/Sortino/Calmar, max drawdown and duration, win rate, profit factor, expectancy, streaks, exposure, commission, R-multiples, MAE/MFE. Charts: equity vs buy-and-hold with drawdown, monthly returns heatmap, trade P&L histogram, excursion scatter, and the price chart with every entry/exit and the script's own plots. A trade table and a full event log record what the bot did. Runs are saved to History and can be compared side by side.

## Install (Windows)
1. Download `Tickbench-Setup-x.y.z.exe` from this repo's Releases page.
2. Run it. The wizard lets you choose the folder and creates a **desktop shortcut** and a Start menu entry.
3. The app is not code-signed (a certificate costs money), so Windows SmartScreen may warn once: click **More info → Run anyway**.

Updates install automatically: the app checks GitHub Releases, downloads in the background, and shows "restart to update". Auto-update only works if the Releases are publicly downloadable (a public repo, or a public releases-only repo).

### Building the installer
Push a version tag (e.g. `git tag v0.1.0 && git push origin v0.1.0`). The GitHub Actions workflow `.github/workflows/release.yml` tests the engine, freezes it with PyInstaller, builds the NSIS installer and publishes the release. Run the workflow manually to get the installer as an artifact without publishing.

## Developing
```bash
cd engine && pip install -r requirements-dev.txt && python -m pytest
cd app && npm install && npm run build && npm start
```
CLI: `python -m tickbench run examples/strategies/sma_cross.pine examples/data/XAUUSD_GC_daily.csv --trades`

## Limits
- Pine: no `request.security` (multi-symbol), libraries, methods or user types. MQL: no classes/structs of your own, DLL imports or `iCustom`. Unsupported calls stop the run with the exact line, never silently.
- MQL runs in MetaTrader's "open prices only" model; strategies on other platforms fill at the next bar's open.
- Python strategies run with the app's own permissions, so only open scripts you trust. JavaScript runs isolated (no file or network access).
- Backtests are simulations, not a promise of future profit.

Third-party: Tradovate custom-indicator `tools/` (ISC), TradingView Lightweight Charts (Apache-2.0), Apache ECharts (Apache-2.0).
