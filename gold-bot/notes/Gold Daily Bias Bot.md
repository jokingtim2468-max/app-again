---
tags: [trading-bot, xauusd, gold, hub, ml]
folder: Gold Bias Bot
---
Bot that predicts whether gold (XAUUSD / GC futures) is **bullish, bearish or no-call** for the day, with a calibrated probability.

- **Repo:** `jokingtim2468-max/app-again` → `gold-bot/`
- **Stack:** Python, pandas, LightGBM, scikit-learn, yfinance; later the MetaTrader5 package or a futures-platform bridge, plus a Windows installer with auto-update
- **Status:** Phase 1 done (free data + baseline). Signal-only / demo until it passes the go-live gate.
- **Hardware:** [[Trading Bot Hardware Buy Plan]]

## Key notes
- [[XAUUSD free data sources]]
- [[Gold bias baseline results Nov 2026]] (in NexusNotes)
- [[Gold bias bot roadmap]] (in NexusNotes)
- [[2026-11-05 Gold data collection and bot plan]]

## Core definitions
- Trading day = the session that closes at **17:00 New York** (the MT5 daily candle and the CME gold day).
- Default decision time = **07:00 UTC (London open)**, after the Asian session.
- Target = close vs price at decision time; bullish/bearish if the move is beyond ±0.25 × ATR14, otherwise neutral (no-call).

## Go-live gate
Hold-out AUC ≥ 0.53, accuracy on calls ≥ 55%, positive in at least 70% of years, Sharpe ≥ 0.5 after costs, max drawdown ≤ 15%.
