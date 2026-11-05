---
tags: [research, data, xauusd, free]
folder: Gold Bias Bot/Research
---
Free gold data sources, tested 2026-11-05. Part of [[Gold Daily Bias Bot]]. The fetcher is `scripts/fetch_data.py`.

## Worked
| Source | What | Span | Notes |
|---|---|---|---|
| Hugging Face `fokan/xauusd-2009-2026` | HistData XAUUSD **M1** | 2009 → 2026-01 | ~380 MB, EST with no DST (UTC-5). Best spot source. |
| Hugging Face `ZombitX64/xauusd-gold-price-historical-data-2004-2025` | 5m/15m/30m/1h/4h/D/W/M (+1m) | 2004-06 → 2025-09 | Kaggle mirror, broker time (NY+7h). Gaps in 2025, so it is only used for 2004–2008. |
| Yahoo (yfinance) | GC=F daily 2000→, 1h last 730 days, 5m 60 days, 1m 7 days | to today | Rebuilt on the 17:00 NY close, futures and spot agree on direction 95% of the time (86% if the close times are not aligned). |
| Yahoo | DXY, US 3m/5y/10y/30y, VIX, GVZ, MOVE, S&P 500, silver, platinum, copper, WTI, EURUSD, USDJPY, USDCNY, GLD, GDX, TIP, BTC | 1995 → today | Cross-asset drivers |
| Hugging Face `ghbacct/gold-headlines-price-talk-classification` | ~9k labelled gold headlines | undated | For training a sentiment model only |

## Blocked from the cloud sandbox (try on your own PC)
Stooq (connection reset), FRED real yields `DFII10` (blocked), Dukascopy ticks (503), CFTC COT (not tested).

## Still wanted from the user
1. Broker or futures-platform history export (M1/M5) with the server-time offset
2. Spread and commission on gold
3. Economic calendar history (FOMC/CPI/NFP)
