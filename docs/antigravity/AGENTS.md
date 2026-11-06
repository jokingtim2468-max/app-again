# Rules for this workspace: trading bots and backtesting

You are building and testing trading bots and the backtester that evaluates them. Wrong numbers here
cost real money, so correctness beats speed, confidence and politeness every time.

## 1. Verify everything. Never state anything you have not checked.

- Every factual claim must come from something you did in THIS session: a file you read, a command you
  ran and its output, a test result, or a doc page you opened. If you did not check it, it is unknown.
- Before you say any of these, run the check and show its output:
  - "it works" / "it's fixed" -> run it and paste the real output.
  - "tests pass" -> run the tests and paste the pass/fail summary.
  - "this function/library/API exists" -> open the file or the official docs and quote it.
  - "the backtest made X%" -> paste the command and the result it printed.
- Never invent: functions, parameters, library features, file paths, API endpoints, broker rules,
  indicator formulas, prices, statistics or results. If you don't know, say "I don't know yet" and go
  find out.
- Label every claim in your final report as one of:
  - **VERIFIED** (say how: command, file, test, doc URL)
  - **NOT VERIFIED** (say why, and what would verify it)
- If a check fails, report the failure exactly as it happened. Never hide it, soften it, or replace real
  output with what you expected.
- Never fake data. Never hard-code results, never skip or weaken a test to make it pass, and never mock a
  calculation and then present it as real.
- After you finish, re-read your own changes and look for mistakes before reporting. Assume your first
  version has a bug.

## 2. How to build the backtester (build it in this order, testing each step)

### 2.1 Data
- Load OHLCV bars from CSV (MetaTrader 4/5 exports, TradingView exports, generic Date/Open/High/Low/Close/Volume).
- Sort by time, drop duplicate timestamps, reject rows with missing prices, and check that high >= max(open, close)
  and low <= min(open, close).
- Store times in UTC as integers. Report how many rows were dropped and why.
- Test: load a small hand-written CSV and assert the exact bar count, first and last close.

### 2.2 No look-ahead (the most important rule)
- The strategy sees bar i only after bar i has closed. It may only read bars 0..i.
- An order decided on bar i fills at the OPEN of bar i+1 (or at bar i's close only if that is explicitly configured).
- Indicators at bar i may only use data up to bar i.
- Test: a strategy that tries to read bar i+1 must get nothing/NaN. Shift the data by one bar and confirm
  results change the way they should.

### 2.3 Broker simulation
- Market, limit and stop orders. Stop-loss and take-profit checked against each bar's high/low.
- If price gaps through a stop or target, fill at the bar's open, not at the level.
- If one bar touches both stop and target, assume the STOP hit first (conservative).
- Costs: commission (per contract/share and/or % of value, per side), slippage in ticks, and spread.
- Position sizing: fixed size, % of equity, cash amount. Futures use contract point value (ES = $50/point,
  MES = $5, NQ = $20, MNQ = $2, GC = $100, MGC = $10, CL = $1,000) and whole contracts only.
  Verify any contract spec you use against the exchange (CME) spec page before relying on it.
- Track every trade: entry/exit time and price, size, side, P&L after costs, reason for entry and exit,
  max adverse and max favorable excursion.
- Tests (hand-calculated, exact numbers): fill at next open; stop fills at stop; gap fills at open;
  stop-before-target on a bar touching both; commission and point value math; reversing a position.

### 2.4 Statistics (compute from the equity curve and the trade list)
Net profit and %, CAGR, max drawdown (% and $) and its duration, Sharpe and Sortino (annualized from the
real bar frequency), profit factor, win rate, average win/loss, expectancy, largest win/loss, longest
win/loss streak, exposure (% of time in a trade), total commission, and buy-and-hold over the same period.
- Buy-and-hold must use the same starting capital and comparable sizing, or the comparison is meaningless.
- Test each metric against a tiny equity curve and trade list you calculated by hand.

### 2.5 Running the bot's own scripts
- Run the strategy code the bot actually uses (not a rewritten summary of it). If the bot's language can't
  run directly, write an adapter and prove it with a test that compares its trades to a known-correct run.
- Cross-check: write the same simple strategy (for example SMA 10/30 crossover, long only) two different
  ways and assert they produce IDENTICAL trades on the same data. Any difference is a bug to find, not to explain away.

### 2.6 Validating results (before anyone trusts them)
- Sanity checks: no trade enters before its signal bar; equity changes only when trades open/close/mark;
  sum of trade P&L equals net profit; no position size exceeds what the account can afford.
- Red flags that mean "probably a bug" until proven otherwise: returns far above buy-and-hold with low
  drawdown, win rate above ~80%, profit factor above ~3, a smooth straight equity line, or results that
  change wildly with tiny parameter changes. Investigate and report the cause.
- Out-of-sample: tune on an earlier period, then test once on a later period you did not tune on. Report both.
- Include realistic costs in every reported result. Report results without costs only as a comparison.
- Reproducibility: the same data, script and settings must always give the same numbers.

## 3. How to report

- Start with what you actually ran, and paste the real output.
- List anything not done or not verified, plainly.
- Never say a strategy "will make money". A backtest is a simulation on past data; say what it showed
  and what its limits are.
