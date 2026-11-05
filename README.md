# XAU Relay Terminal

A single-file, dark-mode trading terminal and dual-bot relay dashboard for a $50,000 prop evaluation account trading gold (XAUUSD).

Open `index.html` in a browser. It needs no build step: Tailwind CSS (Play CDN 3.4.16), Lucide 0.469.0 and IBM Plex fonts load from CDNs.

> Everything on the page is simulated (30× replay of a London session). It is not connected to a broker or a prop firm account, and it sends no orders.

## What's on the page

| Area | Contents |
| --- | --- |
| Account header | Equity/balance ticker, progress bar toward the $53,000 target, daily circuit breaker (−$450 halt, −$1,000 limit) showing the worst case on the open trade, a ladder showing distance above the $47,500 floor, and a "Day 2 of 4" pace badge |
| Bot 1: Scout | Asian high/low, previous-day high/low and FVG levels, each with live distance from price and a sweep state |
| Consensus | Weighted conviction ring with a 65% threshold mark; either APPROVED HIGH-RISK ENTRY ($475 risk) or HOLD OUT ($0 risk); the lot-size calculation behind each entry |
| Bot 2: Arbiter | Four confluence meters (HTF trend 30%, VWAP location 25%, sweep depth 25%, volume 20%) and the weighted sum written out |
| Chart | Canvas M5 candles with the Asian range box, session VWAP, FVG zone, previous-day high/low, and entry, breakeven trigger, stop and target lines; scroll to zoom, drag to pan, double-click to reset |
| Relay transcript | Live Scout ⇄ Arbiter dialogue that auto-scrolls |
| Executions | Toggle between live executions and filtered-out setups (each with the confluence leg that blocked it) |

## Engine rules (simulated)

- Refreshes every 1 s; each refresh advances the clock 30 s. The feed pauses while the tab is hidden.
- Lot size = floor($475 ÷ (stop distance × 100 oz), 0.01), so a full stop never costs more than $475.
- At +1R the breakeven trigger moves the stop to the entry price.
- If today's PnL, including the open trade, reaches −$450, the position is closed and trading stops for the rest of the day.
- Once balance reaches $53,000, no new trades are opened. At 21:00 UTC the session closes and any open trade is closed.

## Design tokens

| Token | Hex | Use |
| --- | --- | --- |
| Obsidian | `#0B0F17` | page background |
| Panel / Panel 2 | `#111722` / `#151C29` | surfaces |
| Line | `#1C2431` | dividers |
| Emerald | `#1FC98E` | approvals, profit, take profit |
| Rose | `#F2506E` | stop loss, losses, breaker trip |
| Amber | `#F5A623` | hold-outs, breakeven trigger |
| Electric blue | `#2F8CFF` | Scout telemetry, Asian range |
| Steel | `#A9B8CC` | Arbiter, VWAP |

Fonts: IBM Plex Sans Condensed (headings), IBM Plex Sans (UI), IBM Plex Mono (all numbers, tabular).
