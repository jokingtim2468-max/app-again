# Payout rules & monthly withdrawal ceilings (checked 2026-11-04)

"Ceiling" = the most a firm's rules let you withdraw from **one account in one month**, *assuming your profits always cover
the caps* (≈21 trading days). Real withdrawals are limited by what the strategy earns: most firms pay at most 50% of profit
or only what's above a buffer. Numbers come from each firm's help center (links in `backend/config/firms/*.json`).

| Firm · account (best size) | How often | Per request | Split | Max payouts | Ceiling / acct / month (to you) | Accounts allowed |
|---|---|---|---|---|---|---|
| **Lucid FLEX 150K** | after 5 days of ≥ $250 (≈ weekly) | 50% of profit, ≤ **$3,000** | 90% | 5, then LucidLive | **$10,800** (4×). Lifetime $15,000 gross | 5 funded |
| **Apex EOD PA 150K** | after 5 days of ≥ $350, 50% cycle consistency | above safety net, caps **2,500 / 3,000 / 3,000 / 3,000 / 4,000 / 5,000** | **100%** | 6, then PA closes | **$11,500** (4×). Lifetime $20,500 | **20 PAs** |
| **Topstep XFA 150K**, standard | 5 winning days ≥ $150 | 50% of balance, ≤ **$5,000** | first $10k 100%, then 90% | none | **$19,000** (4×) | 5 XFAs |
| Topstep XFA 150K, consistency path | 3 traded days, best day ≤ 40% | 50% of balance, ≤ **$6,000** | same | none | up to ~7 cycles: profit-limited | 5 XFAs |
| **Tradeify Select Flex 150K** | 5 winning days ≥ $250 | 50% of profit, ≤ **$5,000*** | 90% | 3 → live review | **$18,000** (4×) | 5 funded |
| Tradeify Select Daily 150K | daily | ≤ 2× profit since last, ≤ **$2,500** | 90% | 3 → live review | profit-limited | 5 funded |
| **MFFU Rapid 50K** | **daily** after $2,100 buffer | above buffer, ≤ **$2,000** | 90% | none (auto-live after a $10k day) | profit-limited (cap math: $37.8k) | 5 (25K/50K) |
| MFFU Rapid 150K | daily after $4,600 buffer | above buffer (cap not published) | 90% | none | profit-limited | 3 (100K/150K) |
| MFFU Pro 150K | every 14 days | above $4,600 buffer, ≤ $100k | 80% | 3 → live review | profit-limited | — |
| **Take Profit Trader PRO 150K** | **daily from day one** | everything above $154,500 buffer, no cap | 80% (90% in PRO+) | none | profit-limited | 5 PRO |
| Bulenox 150K (EOD) | not confirmed | $3,000 (#1–3), $3,500 after | 90% | 3 → funded review | ~$12–14k | 5 Master |

\* Tradeify caps shown are for accounts bought before 2026-09-01; newer caps aren't published.

## Which account type is "optimal"
- **Largest monthly ceiling per account:** Topstep XFA 150K (standard: $5k/week, first $10k at 100%) and Tradeify Select Flex 150K ($5k/week).
- **Most scale:** Apex allows **20 PAs** at 100% split (≈ $11.5k/month each, but every PA ends after 6 payouts / $20.5k, so you keep re-buying evals).
- **Fastest cash:** MFFU Rapid, TPT PRO and Tradeify Select Daily (daily payouts, but they need profit above a buffer first).
- **Lucid FLEX** (your current fleet): ≈ **$10.8k/month per account × 5 = $54k/month theoretical**, for ~5 weeks per account before LucidLive.

## Reality check
With a 1:1 copy fleet every account earns about the same. To actually hit Lucid's $3k weekly cap you need about **$3k+ of new
profit per account per week**, and since only 50% of profit can be withdrawn, profit also builds up as cushion. The Payout
Center shows each account's real withdrawable amount from its actual balance, not the ceiling.

## Automation
No firm offers a payout API: requests are made in their dashboards. Apollo is **semi-automatic**:
1. Checks every account's eligibility each minute using the rules above.
2. Alerts you when one becomes eligible: in-app/desktop notification, and to your phone if `APOLLO_NOTIFY_WEBHOOK` is set
   (a Discord or Slack webhook, or `https://ntfy.sh/<your-topic>`).
3. **Open payout page ↗** copies the exact amount and opens the firm's dashboard. You submit it there (one click per account).
4. Mark **Requested**, then **Paid** (or **Rejected**). Apollo updates the balance, cycle, MLL lock, payout count, ledger and graduation.

Fully automatic requests would mean a bot logging into your firm accounts. Firm terms generally treat that as unauthorized
automation and can deny payouts or close accounts, so Apollo doesn't do it.
