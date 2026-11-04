# Firm rules audit — 2026-11-04

Every profile in `backend/config/firms/` was checked against the firm's own help center (links stored in each file's
`sources`). Profiles are now `verified: true` with `verified_on: 2026-11-04`, except where noted. Firms change rules
often: re-check before buying new accounts.

## Corrections that affect live trading

| Firm | What was wrong | Now |
|---|---|---|
| **Lucid FLEX 150K** | Funded scaling tiers: 40/50/60/80/100 at $0/$2k/$3k/$4.5k/$6k profit | **40 / 50 / 60 / 80 / 100 at $0 / $1,000 / $2,000 / $3,000 / $4,500** (official table) |
| **Lucid FLEX** | Eval consistency as a fixed $3,600 cap | **40% of total profit** (50% if you bought the add-on): the allowed best day grows as profit grows |
| **Lucid FLEX** | MLL only locked at $154,600 | Also **locks at $150,100 on the first payout** (Lucid drawdown article) |
| Apex | 50K/100K/150K drawdown 2,500/3,000/5,000, intraday only | 2026 evals: **2,000 / 3,000 / 4,000**, EOD **or** intraday plans, max 6/8/12 minis, stops trailing at start + target, up to 20 PAs |
| Topstep | 50% consistency | **55%**; MLL stops trailing at the **starting balance** |
| MFFU | "CORE" plan (no longer offered) | **RAPID** (EOD eval → **intraday** when funded), **PRO**, **BUILDER** (soft DLL) |
| Tradeify | One "GROWTH" plan without DLL | **SELECT** (40% consistency, 4.5k DD on 150K) and **GROWTH** (no consistency, soft DLL, 3.5k/5k DD on 100K/150K) |
| Bulenox | 50K EOD DLL 1,100; contract caps | EOD 50K: 2,000 DD / **1,200** DLL / 40 micros; 150K: 4,500 / 3,300 / 120 micros; trailing 150K 150 micros |
| The5ers High Stakes | Phase-1 target 8% | **10%** (phase 2 5%) |
| FTMO | — | Confirmed: static 10% max loss, 5% daily (resets 00:00 CE(S)T, not 17:00 ET) |

## Funded-account caps now enforced (park/unpark queue)
Lucid 5 · Tradeify 5 · Take Profit Trader 5 (PRO) · Bulenox 5 (Master-level) · MFFU 5 (25K/50K Rapid; 3 for 100K/150K) ·
Apex 20 PAs · Topstep: no count limit ($750K combined XFA buying power) · CFD firms: none set.

## Still needs your confirmation
- **Lucid $2,025 "50% cashout election" after payout 5**: not in Lucid's public docs, which say accounts move to LucidLive
  after payout 5. Kept as you supplied it; confirm on your dashboard.
- **Take Profit Trader 150K**: numbers only from a third-party review, so that size stays `verified: false` (live orders blocked).
- Optional add-ons you choose at purchase (Lucid/Tradeify 50% consistency, Topstep/Lucid optional DLL): set them per account
  with `rule_overrides`, e.g. `{"eval_consistency_pct": 0.5}` or `{"daily_loss_limit": 1000}`.
- Apex/Tradeify accounts bought **before** their 2025–2026 rule changes keep legacy numbers: use `rule_overrides`.
