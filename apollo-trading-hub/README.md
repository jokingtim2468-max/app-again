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

## Every account, every platform
Accounts live in `backend/config/fleet.json` (edit in the **Account Manager** widget / *Account Setup* layout). Each account has
its own firm rules, platform, symbol and copy ratio; one is the master, the rest copy it.

| Platform (`broker`) | Reaches | Credentials (env only) |
|---|---|---|
| `tradovate` | Lucid, Apex, MFFU, Tradeify, Take Profit Trader, Topstep (Tradovate) | `TRADOVATE_USER/PASS/CID/SEC[/APP_ID/DEVICE_ID/ENV]` |
| `projectx` | TopstepX and other ProjectX-powered firms (set `PROJECTX_URL` per firm) | `PROJECTX_USER`, `PROJECTX_API_KEY` |
| `ninjatrader` / `rithmic` | anything NinjaTrader 8 connects to: Rithmic (Apex, Bulenox, TPT…), CQG, Tradovate, IB, Kinetick, via the ATI | enable *AT Interface* in NT8; `NT8_DIR` |
| `mt5` | FTMO, FundedNext, The5ers, any MT5 broker (orders need Windows Python) | logged-in MT5 terminal (`APOLLO_MT5_*`) |
| `ibkr` | Interactive Brokers (TWS / IB Gateway, `pip install ib_async`) | `IBKR_HOST/PORT/CLIENT_ID` |
| `paper` | local simulation | — |

Second login on the same platform: set the account's `login` to `_2` and use `TRADOVATE_USER_2`, etc.
CFD accounts (`contract: XAUUSD`) copy in lots: `copy_ratio 0.1` means 10 MGC on the master equals 1.0 lot.
Direct Rithmic R|API and cTrader Open API need vendor approval/OAuth apps, so Rithmic goes through NinjaTrader; cTrader is not wired yet.

**Firm rules** (`backend/config/firms/*.json`): Lucid (owner-verified), Topstep, Apex, MyFundedFutures, Take Profit Trader,
Tradeify, Bulenox, FTMO, FundedNext, The5ers, plus *custom*. The engine handles END_OF_DAY, INTRADAY and STATIC drawdown,
MLL locks, daily loss limits, profit targets, $ or % consistency, contract caps, funded scaling tiers, payouts and graduation.
⚠ Every profile except Lucid is a **template marked `verified: false`**. Firms change rules often: check each number against
your dashboard and set `verified: true`. Until then paper trading and backtests work, but **live opening orders are refused**.
Backtests can use any profile (*Firm rules* selector / `firm, plan, size` params).

## Firm caps, the eval queue and lifecycle tracking
Firms limit how many funded accounts you may hold (Lucid: **5**). Apollo tracks every account at every firm and enforces it:
- **Park:** while a firm's funded slots are full, an eval that reaches `target - park buffer` (Lucid: $8,500 of $9,000) is
  **flattened and parked**, so it can't pass. Parked accounts take no new copy trades. Evals further from the target keep trading.
- **Queue:** parked evals wait first-parked-first (`PARKED #1`, `#2`…).
- **Release:** when a funded account **fails** (hits its MLL) or is **closed** (cashout done / cancelled), the slot opens and the
  oldest parked eval is released to trade to the target. If it passes (at the 17:00 ET close, consistency rules included) it
  becomes **funded** and takes the slot, and the next eval that nears its target parks again.
- Set caps per firm in the Account Manager (*max funded*). *Outside app* counts funded accounts you own at that firm but
  don't run here, so they still use up the cap. *Park buffer* sets how far below the target to stop.
- **Ledger:** every PARKED / UNPARKED / PASSED / FAILED / PAYOUT / CLOSED / CASHOUT event is recorded (`/api/fleet/ledger`),
  and the fleet deck shows per firm: funded x/cap, evals trading, parked, passed, failed, the queue, and money **spent vs paid
  out** (enter each account's cost and purchase date).
- When the firm issues the funded account under a new ID, update that account's *Broker account* in the Account Manager.

## Safety
- **PAPER by default**; market data is a seeded **SIM** feed (labelled in every chart). `APOLLO_LIVE=1` switches to Tradovate (`TRADOVATE_ENV=demo` default).
- Broker credentials are **env vars only**, never in `fleet.json`.
- Kill switch (top bar or per account) flattens and halts routing; killed accounts can be resumed, cashout/liquidated accounts cannot.
- DOM brackets are server-side emulated: the backend watches last price and flattens the fleet at TP/SL. They do not exist at the broker,
  so if the backend stops, there is no resting stop. Keep that in mind on live.
- EOD MLL trails only at 17:00 ET; locks at 150,100 once closed balance ≥ 154,600. Payout 5 ⇒ `ELIGIBLE_FOR_CASHOUT`, routing frozen, $2,025 election + 24h alert.
- Synthetic backtests validate rules, not edge. Use a tick CSV before trusting any strategy.
