# Apollo Trading cockpit

The app is a gold scalping cockpit and prop fleet manager. It is still branded Apollo Trading, and it still installs
with the Windows setup wizard and updates itself.

## Architecture

```
 MT5 terminal ──► MT5 gateway (your PC, :8001)  ─┐  /rates for DXY + GVZ, history for backtests
 Tradovate / other brokers ◄──────────────────┐ │
                                              │ ▼
 ┌──────────────────────── Apollo engine (FastAPI, 127.0.0.1:5150 desktop / 5050 dev) ───────────────────────┐
 │ market_feed ─► ticks ─► cockpit.run() every 250 ms:                                                       │
 │                          trade tracking (MFE/MAE) · breakeven steps · Asian-range limits · daily breaker │
 │                          on each M5 close in AUTONOMOUS: confluence ≥ threshold, quota, cooldowns,       │
 │                          spread, news lock → bracketed order                                             │
 │ FleetRouter (master order → followers × multiplier, each checked by RiskSentinel firm rules)            │
 │ RiskSentinel (trailing floor, DLL, targets, consistency, payouts) · Journal (SQLite) · bots (TG/Discord)│
 │ REST /api/* · WebSocket /ws/events (ticks + every engine event)                                         │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                              │
 Electron shell (installer, auto-update, starts/stops the engine) ─► React UI (Vite build, slate theme)
```

### Files

```
backend/src/
  server.py                 REST + WebSocket, order routing, brackets, kill switch
  cockpit.py                live params, engine mode, intel, quick orders, copier, trades, studio endpoints
  trading/confluence.py     regime, adaptive params, Asian range, VWAP, FVGs, sweeps, 5-factor score (live + backtest)
  trading/scalper_backtest.py  strict-fill backtester, evaluation tracking, grid optimizer
  trading/risk_sentinel.py  prop-firm rules engine;  trading/tradovate_bridge.py  copy router
frontend/src/
  App.tsx                   shell: sidebar, header (account switcher, price pill, regime, PANIC), pages
  cockpit/store.ts          live state (intel poll 1 s + tick stream)
  cockpit/panels.tsx        fleet cards, regime banner, confluence radar, macro/news, engine controls,
                            params form, quick orders, copier matrix, live feed, trade ledger + forensics
  cockpit/CockpitChart.tsx  candles + Asian H/L, VWAP, FVGs, sweep markers, entry/SL/TP
  cockpit/Studio.tsx        backtest, month table, equity + underwater, grid optimizer
```

## Modules

| Module | Where | Notes |
|---|---|---|
| 1 Fleet dashboard | Fleet Dashboard | Safe buffer above the trailing floor, target progress and daily loss breaker on every card. The account switcher at the top filters everything. |
| 2 Market intel | Market Intel, header | Bid/ask/last/spread (amber above max spread). Regime and the adaptive TP/SL/BE/quota in force. 5-factor score out of 10. DXY/GVZ from the gateway. News lock countdown. |
| 3 Bot control | Bot Control | AUTONOMOUS / MANUAL and PANIC. Every parameter applies on the next tick, no restart. The engine always starts in MANUAL. |
| 4 Execution | Execution, dashboard | Buy/sell market with the adaptive bracket. Limits at the Asian low/high. Breakeven All. Copier multipliers per follower. |
| 5 Backtest studio | Backtest Studio | MT5, CSV or synthetic data. Month-by-month table, equity vs floor, underwater chart, grid of up to 60 combinations. |
| 6 Ledger and alerts | Ledger, Settings | Colour-coded feed and every trade's MFE/MAE/commission/net (click a row). Telegram/Discord alerts for entry, breakeven_step, tp_hit, sl_hit, daily_loss_breaker and panic. |

### Confluence score (max 10)
Liquidity sweep 3.5 · fair value gap 2.0 · VWAP discount/premium 1.5 · volume ≥115% of the 20-bar average 1.5 ·
DXY moving against the trade's USD side 1.5. Grades: A+ ≥ 8.5, A ≥ 7, B ≥ 5.5, otherwise C.

### Regimes
M15 ATR(14) against its recent median, plus trend efficiency (net move ÷ path length over 16 bars):
- **Trend expansion** (ATR ≥ 1.1× and efficiency ≥ 0.35): TP ×1.3, SL cap ×1.15, breakeven at 0.6R, expansion quota.
- **Consolidation range** (ATR ≤ 0.8× or efficiency ≤ 0.15): TP ×0.8, SL cap ×0.85, breakeven at 0.35R, range quota.
- **Balanced** (anything else): base values.

### Backtest fill rules
These are stricter than the old `test_same_day_mt5.py`:
- A signal comes from a closed M5 bar. Entry fills at the next M1 open plus half the spread.
- If one bar hits both the stop and the target, it counts as the stop.
- Breakeven protects from the following bar onwards.
- Commission is charged per contract on every trade.

## Running it

**Installed app (Windows):** open Apollo Trading. It updates itself from the branch and then starts the engine.

**Developer:**
```
pip install -r apollo-trading-hub/backend/requirements.txt
cd apollo-trading-hub && python -m backend.src.server          # engine on 127.0.0.1:5050
cd frontend && npm install && npm run dev                       # UI on http://127.0.0.1:5173
```

## Connecting your MT5 gateway (port 8001) and daemons

1. **Live prices from MT5.** Set these before starting the engine:
   - `APOLLO_FEED=mt5`
   - `APOLLO_MT5_SYMBOL=XAUUSD`

   The engine reads MT5 directly with the MetaTrader5 package, or through `scripts/mt5_bridge.py`. The header pill
   then shows `MT5:XAUUSD`.
2. **DXY / GVZ.** The engine calls `GET {gateway}/rates?symbol=DXY&timeframe=M15&count=20` (and the same for GVZ):
   - The default gateway is `http://127.0.0.1:8001`. If your gateway runs in WSL or on another machine, change it:
     `PUT /api/engine/connection {"gateway_url": "http://172.28.144.1:8001", "dxy_symbol": "USDX", "gvz_symbol": "GVZ"}`.
   - If your broker doesn't offer a symbol, that panel shows "not available" and the DXY factor scores 0.
3. **News calendar.** Until you add one, the engine uses estimated NFP dates only. To load your own:
   `PUT /api/news [{"time": "2026-11-13T08:30:00-05:00", "title": "CPI", "impact": "high"}, …]`.
4. **Your own trading daemon.** Point it at the engine instead of at the broker:
   - Market orders: `POST /api/exec/quick {"kind": "buy_market"}` or `"sell_market"`.
   - Orders with your own bracket: `POST /api/fleet/order {"action": "Buy", "qty": 4, "tp_ticks": 35, "sl_ticks": 30}`.

   Every order then goes through the copier, the firm rules, the breakeven logic and the ledger.
5. **Backtests on real data.** In Backtest Studio choose "MetaTrader 5 history", or "CSV file" with columns
   `time,open,high,low,close[,volume,spread]`.
6. **Going live.** Trading is PAPER until a person sets `APOLLO_LIVE=1` and the firm profile is verified.
