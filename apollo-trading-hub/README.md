# Apollo Trading

Local-first, modular prop-fleet execution terminal. **Zero AI / pure systematic:** every execution, risk gate,
copy-trade and backtest is deterministic and rule-based.

| Layer | Path | Port |
|---|---|---|
| Electron + React grid workspace (`#090A0F` / `#12151E` / `#212636`) | `frontend/` | 5173 dev |
| FastAPI backend: risk sentinel, Tradovate copier, market feed, backtester, layouts, Docker | `backend/` | 5050 |
| MCP server (stdio + SSE) | `mcp-server/` | 54981 |

## Run
```bash
bash scripts/setup_dev.sh                 # Linux/WSL   (Windows: scripts\setup_dev.bat)
python -m backend.src.server              # backend
cd mcp-server && python -m src.server --sse
cd frontend && npm run electron:dev       # npm run dist:win -> NSIS wizard installer + auto-update
python -m pytest tests
```

## Workspace
- Every tool is a widget: `widget-chart`, `widget-dom`, `widget-fleet`, `widget-tape`, `widget-backtest`, `widget-terminal`.
- **Builder tab** (`#/builder`): catalog → *Add to Workspace*, 12-col snap grid with collision prevention, per-widget settings (⚙),
  maximize, close, presets (*Execution Focus*, *Risk Command*, *Quant Lab*), Save / Save as / Reset / Delete, Export & Import JSON, Edit ↔ Lock.
- Layouts persist in `~/.apollo-trading-hub/layouts.json` (override with `APOLLO_LAYOUT_FILE`). Agents write them via MCP `save_custom_layout`; the open UI hot-swaps.

## Testing any script (your file is never modified)
Drop scripts in `strategies/` or pass any path (UI *Script path*, API `script_path`, MCP `run_backtest(script_path=...)`).
Apollo hashes the file, copies it to `~/.apollo-trading-hub/adapted/<hash>/` and adapts **that copy**. Supported, auto-detected:

| Style | Example |
|---|---|
| pandas / vectorized | `generate_signals(df)` / `signals(df)` / `strategy(df)` returning 1/0/-1, `"buy"/"sell"`, a `signal`/`position` column |
| vectorbt | `return entries, exits` (or `short_entries`, `short_exits` columns) |
| backtrader | `class X(bt.Strategy): next()` using `self.data.close[0]`, `bt.indicators.SMA`, `self.buy()/self.close()` |
| backtesting.py | `init()` with `self.I(...)`, `next()` with `crossover`, `self.position.close()` |
| event function | `on_bar(bar)` / `next(bar)` returning an action |
| **MetaTrader5 Python bot** | `while True:` loop with `mt5.copy_rates_from_pos`, `positions_get`, `order_send`, `time.sleep`. Each sleep advances one bar on a simulated MT5 |
| **MQL5 EA** `.mq5/.ex5` | runs in MT5's own Strategy Tester (Windows), deals replayed through LucidFlex rules |
| **Pine Script v4/v5/v6** `.pine` | `strategy()` scripts: `ta.*` (sma/ema/rma/wma/hma/vwma/rsi/atr/macd/bb/stoch/cci/supertrend/dmi/vwap/pivots/…), `math.*`, `input.*` (override via params by title), `var`, `x[n]`, `=>` functions, tuples, `switch`, `for`/`while`, `strategy.entry/close/close_all/exit` (stop/limit/profit/loss). Indicators verified against reference math |
| Freqtrade | `IStrategy` with `populate_indicators` / `populate_entry_trend` / `populate_exit_trend` (or legacy buy/sell) |
| QuantConnect / LEAN | `QCAlgorithm` with `Initialize` / `OnData`, `SetHoldings`, `Liquidate`, `MarketOrder`, `Portfolio`, `SMA/EMA/RSI`, `History` |
| Jupyter notebook `.ipynb` | code cells extracted (magics dropped), then auto-detected like any `.py` |
| Trade-list exports | TradingView "List of trades", NinjaTrader trades, MT4/MT5 history, any CSV with entry/exit time + side, re-simulated with Apollo costs and Lucid rules |
| signal CSV / JSON | `time,signal` rows, or `{"signals":[{time, signal}]}` |
| Apollo native | `generate_signals(secs, px, spread, events)` on the 1-second tick engine |

Missing platform packages (backtrader, backtesting, MetaTrader5) are shimmed. A script that loops forever at import is stopped after 20s.
Every vectorized run gets a **look-ahead check**: if past signals change when future bars are removed, the report warns you.
Fills happen at the next bar's open plus half the spread plus 1 tick. Intrabar lows/highs are checked against the MLL.
Can't be executed directly (Apollo explains how to export instead): NinjaScript C#, EasyLanguage, MQL4, AmiBroker AFL,
Pine `request.security` on another timeframe/symbol, Pine libraries/UDTs. Pine stop/limit *entries* fill as market orders.

## MetaTrader 5 data (past + live)
- **Past:** data source *MetaTrader 5* + broker symbol (e.g. `XAUUSD`/`GOLD`) loads real bars via `copy_rates_range` (ticks via `copy_ticks_range` for tick strategies).
  MT5 server time is converted to UTC (auto-detected; override `APOLLO_MT5_UTC_OFFSET`).
- **Live:** *Forward test* tab paper-trades your script on each newly closed live MT5 bar (no orders sent anywhere). `APOLLO_FEED=mt5` streams MT5 into the charts/DOM/tape.
- **Windows:** `pip install MetaTrader5`, keep the MT5 terminal open and logged in. Optional `APOLLO_MT5_LOGIN/PASSWORD/SERVER/PATH`.
- **WSL (Antigravity):** run `python scripts\mt5_bridge.py` on Windows (read-only data bridge, port 54982); the WSL backend uses it automatically
  via `APOLLO_MT5_BRIDGE_URL` (Windows host IP + `--host 0.0.0.0` under WSL2 NAT, or 127.0.0.1 with mirrored networking).
- MT5 gold is usually the broker's **spot/CFD XAUUSD**, not CME MGC. It tracks MGC closely, but futures basis and sessions differ.
  PnL is always computed with MGC economics ($10/pt per micro).

## Safety
- **PAPER by default**; market data is a seeded **SIM** feed (labelled in every chart). `APOLLO_LIVE=1` switches to Tradovate (`TRADOVATE_ENV=demo` default).
- Tradovate credentials are **env vars only** (`TRADOVATE_*`), never in `fleet.json`.
- Kill switch (top bar or per account) flattens and halts routing; killed accounts can be resumed, cashout/liquidated accounts cannot.
- DOM brackets are server-side emulated: the backend watches last price and flattens the fleet at TP/SL. They do not exist at the broker,
  so if the backend stops, there is no resting stop. Keep that in mind on live.
- EOD MLL trails only at 17:00 ET; locks at 150,100 once closed balance ≥ 154,600. Payout 5 ⇒ `ELIGIBLE_FOR_CASHOUT`, routing frozen, $2,025 election + 24h alert.
- Synthetic backtests validate rules, not edge. Use a tick CSV before trusting any strategy.
