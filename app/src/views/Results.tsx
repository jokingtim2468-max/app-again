import { useMemo, useState } from "react";
import { ExcursionScatter, PnlHistogram } from "../charts/Distribution";
import { EquityChart } from "../charts/EquityChart";
import { MonthlyHeatmap } from "../charts/MonthlyHeatmap";
import { PriceChart } from "../charts/PriceChart";
import { Refresh } from "../components/Icons";
import { date, duration, isNum, KIND_LABEL, money, num, pct, price } from "../format";
import { useCountUp } from "../hooks";
import type { EngineError, RunResult, Stats, Trade } from "../types";

type Tab = "overview" | "chart" | "trades" | "stats" | "log";

export function Results({ result, onRerun }: { result: RunResult; onRerun?: () => void }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [focus, setFocus] = useState<Trade | null>(null);
  const s = result.stats;
  const pick = (t: Trade) => { setFocus(t); setTab("chart"); };
  const params = Object.entries(result.script.params ?? {});
  return (
    <div className="arrive" key={result.id}>
      <div className="result-head">
        <div style={{ minWidth: 0 }}>
          <h1>{result.script.filename}</h1>
          <div className="sub">
            <span className="chip kind">{KIND_LABEL[result.script.kind] ?? result.script.kind}</span>
            <span className="chip">{result.data.symbol}, {result.data.timeframe}</span>
            <span className="chip">{date(result.data.start)} to {date(result.data.end)}</span>
            <span className="chip">{num(result.data.bars, 0)} bars in {result.elapsedMs < 1000 ? `${Math.round(result.elapsedMs)} ms` : `${(result.elapsedMs / 1000).toFixed(1)} s`}</span>
            {result.contract && <span className="chip">{result.contract.root} contract, ${num(result.contract.point_value, 0)}/pt</span>}
            {params.slice(0, 4).map(([k, v]) => <span className="chip" key={k}>{k} {String(v)}</span>)}
          </div>
        </div>
        <div className="actions">
          {onRerun && <button className="btn small" onClick={onRerun}><Refresh /> Run again</button>}
        </div>
      </div>

      <Kpis s={s} id={result.id} capital={result.settings.initial_capital as number} />

      <div className="tabs" role="tablist">
        {([["overview", "Overview"], ["chart", "Price chart"], ["trades", "Trades", result.trades.length],
          ["stats", "Statistics"], ["log", "What it did", result.events.length]] as [Tab, string, number?][]).map(([k, l, n]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>
            {l}{n != null && <span className="badge">{num(n, 0)}</span>}
          </button>
        ))}
      </div>

      {tab === "overview" && <Overview r={result} />}
      {tab === "chart" && <div className="card" style={{ overflow: "hidden" }}><PriceChart result={result} focusTrade={focus} onPickTrade={setFocus} /></div>}
      {tab === "trades" && <Trades trades={result.trades} onPick={pick} selected={focus?.id} intraday={/m$|h$/.test(result.data.timeframe)} />}
      {tab === "stats" && <StatsPanel s={s} r={result} />}
      {tab === "log" && <Log r={result} onPick={(id) => { const t = result.trades.find((x) => x.id === id); if (t) pick(t); }} />}
    </div>
  );
}

// ---------------------------------------------------------------------------- KPI strip
function Signed({ v, fmt }: { v: number | null; fmt: (x: number) => string }) {
  if (!isNum(v)) return <>—</>;
  return <span className={v > 0 ? "up" : v < 0 ? "down" : ""}><span className="tri" aria-hidden="true">{v > 0 ? "▲" : v < 0 ? "▼" : ""}</span>{fmt(v)}</span>;
}

function Kpis({ s, id, capital }: { s: Stats; id: string; capital: number }) {
  const net = useCountUp(s.netProfit, id);
  const ret = useCountUp(s.netProfitPct, id);
  const vs = isNum(s.netProfitPct) && isNum(s.buyHoldPct) ? s.netProfitPct - s.buyHoldPct : null;
  return (
    <div className="kpis">
      <div className="kpi hero">
        <div className="k">Net profit on {money(capital, { d: 0 })}</div>
        <div className="v num"><Signed v={net} fmt={(x) => money(x, { sign: true, d: Math.abs(x) >= 1000 ? 0 : 2 })} /></div>
        <div className="s"><Signed v={ret} fmt={(x) => pct(x, { sign: true })} /> total, {pct(s.cagr, { sign: true })} a year</div>
      </div>
      <div className="kpi"><div className="k">vs buy and hold</div><div className="v num"><Signed v={vs} fmt={(x) => pct(x, { sign: true, d: 1 })} /></div><div className="s">Holding: {pct(s.buyHoldPct, { sign: true, d: 1 })}</div></div>
      <div className="kpi"><div className="k">Max drawdown</div><div className="v num down">{isNum(s.maxDrawdownPct) ? `−${pct(s.maxDrawdownPct, { d: 1 })}` : "—"}</div><div className="s">{money(s.maxDrawdown ? -s.maxDrawdown : null, { d: 0 })} at worst</div></div>
      <div className="kpi"><div className="k">Sharpe ratio</div><div className="v num">{num(s.sharpe)}</div><div className="s">Sortino {num(s.sortino)}</div></div>
      <div className="kpi"><div className="k">Win rate</div><div className="v num">{pct(s.winRate, { d: 1 })}</div><div className="s">{num(s.trades, 0)} trades</div></div>
      <div className="kpi"><div className="k">Profit factor</div><div className="v num">{s.profitFactor === null ? "—" : num(s.profitFactor)}</div><div className="s">Payoff {num(s.payoffRatio)}</div></div>
      <div className="kpi"><div className="k">Time in market</div><div className="v num">{pct(s.exposurePct, { d: 0 })}</div><div className="s">Avg hold {duration(s.avgHoldHours)}</div></div>
    </div>
  );
}

// ---------------------------------------------------------------------------- overview
function Overview({ r }: { r: RunResult }) {
  const s = r.stats;
  const best = useMemo(() => [...r.trades].sort((a, b) => b.pnl - a.pnl)[0], [r]);
  return (
    <div className="overview">
      <section className="card wide">
        <header>
          <h3>Equity</h3>
          <div className="aside legend">
            <span><i style={{ background: "var(--data-equity)" }} />Strategy {money(s.finalEquity, { d: 0 })}</span>
            <span><i style={{ background: "var(--data-bench)" }} />Buy and hold {money(r.buyHold[r.buyHold.length - 1], { d: 0 })}</span>
            <span><i style={{ background: "var(--data-down)", height: 8, opacity: 0.6 }} />Drawdown</span>
          </div>
        </header>
        <div className="pad"><EquityChart result={r} /></div>
      </section>
      <section className="card">
        <header><h3>Monthly returns</h3><div className="aside">% change in equity each month</div></header>
        <div className="pad"><MonthlyHeatmap months={r.monthly} /></div>
      </section>
      <section className="card">
        <header><h3>At a glance</h3></header>
        <div className="pad">
          <dl className="mini-stats">
            <dt>Gross profit</dt><dd className="up">{money(s.grossProfit, { sign: true })}</dd>
            <dt>Gross loss</dt><dd className="down">{money(s.grossLoss)}</dd>
            <dt>Commission paid</dt><dd>{money(s.commission)}</dd>
            <hr />
            <dt>Average win</dt><dd>{money(s.avgWin, { sign: true })}</dd>
            <dt>Average loss</dt><dd>{money(s.avgLoss)}</dd>
            <dt>Expectancy per trade</dt><dd>{money(s.expectancy, { sign: true })}</dd>
            <hr />
            <dt>Longest losing streak</dt><dd>{num(s.maxConsecLosses, 0)} trades</dd>
            <dt>Longest time underwater</dt><dd>{num(s.longestDrawdownDays, 0)} days</dd>
            <dt>Best trade</dt><dd>{best ? `#${best.id}, ${money(best.pnl, { sign: true })}` : "—"}</dd>
          </dl>
        </div>
      </section>
      <section className="card">
        <header><h3>Trade results</h3><div className="aside">Count of trades by profit or loss</div></header>
        <div className="pad"><PnlHistogram trades={r.trades} /></div>
      </section>
      <section className="card">
        <header><h3>How far trades went</h3><div className="aside">▲ winners, ▼ losers</div></header>
        <div className="pad"><ExcursionScatter trades={r.trades} /></div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------- trades
type SortKey = "id" | "pnl" | "entryTime" | "barsHeld" | "r";

function Trades({ trades, onPick, selected, intraday }: { trades: Trade[]; onPick: (t: Trade) => void; selected?: number; intraday: boolean }) {
  const [filter, setFilter] = useState<"all" | "long" | "short" | "win" | "loss">("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ k: SortKey; dir: 1 | -1 }>({ k: "id", dir: 1 });
  const [limit, setLimit] = useState(500);
  const rows = useMemo(() => {
    let x = trades;
    if (filter === "long" || filter === "short") x = x.filter((t) => t.side === filter);
    if (filter === "win") x = x.filter((t) => t.pnl > 0);
    if (filter === "loss") x = x.filter((t) => t.pnl <= 0);
    if (q) { const s = q.toLowerCase(); x = x.filter((t) => `${t.entryReason} ${t.exitReason} ${t.tag}`.toLowerCase().includes(s)); }
    return [...x].sort((a, b) => ((a[sort.k] ?? 0) as number) > ((b[sort.k] ?? 0) as number) ? sort.dir : -sort.dir);
  }, [trades, filter, q, sort]);
  const th = (k: SortKey, label: string, r = false) => (
    <th className={r ? "r" : ""} onClick={() => setSort({ k, dir: sort.k === k ? (-sort.dir as 1 | -1) : (k === "pnl" ? -1 : 1) })}
      aria-sort={sort.k === k ? (sort.dir > 0 ? "ascending" : "descending") : undefined}>
      {label}{sort.k === k ? (sort.dir > 0 ? " ↑" : " ↓") : ""}
    </th>
  );
  if (!trades.length) {
    return <div className="card pad"><p className="hint" style={{ fontSize: 13 }}>The strategy never traded on this data. Check the Log tab to see which signals fired, or try a longer date range.</p></div>;
  }
  return (
    <div className="card">
      <div className="filters">
        <div className="seg" role="group" aria-label="Filter trades">
          {([["all", "All"], ["long", "Long"], ["short", "Short"], ["win", "Winners"], ["loss", "Losers"]] as const).map(([k, l]) => (
            <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>
          ))}
        </div>
        <input className="input" placeholder="Search reasons, e.g. crossover" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="hint" style={{ marginLeft: "auto" }}>{num(rows.length, 0)} trades. Click one to see it on the chart.</span>
      </div>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              {th("id", "#")}<th>Side</th><th className="r">Size</th>{th("entryTime", "Entry")}<th className="r">Entry price</th>
              <th>Exit</th><th className="r">Exit price</th>{th("barsHeld", "Bars", true)}{th("pnl", "P&L", true)}{th("r", "R", true)}
              <th>Why it entered, and why it exited</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((t) => (
              <tr key={t.id} className={t.id === selected ? "sel" : ""} onClick={() => onPick(t)} style={{ cursor: "pointer" }}>
                <td className="mono">{t.id}</td>
                <td><span className={`side ${t.side}`}>{t.side === "long" ? "Long" : "Short"}</span></td>
                <td className="r mono">{num(t.qty, t.qty % 1 ? 2 : 0)}</td>
                <td className="mono">{date(t.entryTime, intraday)}</td>
                <td className="r mono">{price(t.entryPrice)}</td>
                <td className="mono">{date(t.exitTime, intraday)}</td>
                <td className="r mono">{price(t.exitPrice)}</td>
                <td className="r mono">{t.barsHeld ?? "—"}</td>
                <td className={`r mono ${t.pnl > 0 ? "up" : t.pnl < 0 ? "down" : ""}`}>{money(t.pnl, { sign: true })}</td>
                <td className="r mono">{t.r == null ? "—" : `${t.r > 0 ? "+" : ""}${num(t.r, 1)}R`}</td>
                <td className="reason"><div title={t.entryReason}>{t.entryReason || t.tag || "Entry"}</div><div className="exit" title={t.exitReason}>{t.exitReason}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > limit && <div className="pad"><button className="btn small" onClick={() => setLimit(limit + 1000)}>Show {num(Math.min(1000, rows.length - limit), 0)} more</button></div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- stats
function StatsPanel({ s, r }: { s: Stats; r: RunResult }) {
  const groups: [string, [string, string][]][] = [
    ["Returns", [
      ["Net profit", money(s.netProfit, { sign: true })], ["Net profit %", pct(s.netProfitPct, { sign: true })],
      ["Annual return (CAGR)", pct(s.cagr, { sign: true })], ["Buy and hold", pct(s.buyHoldPct, { sign: true })],
      ["Final equity", money(s.finalEquity)], ["Gross profit", money(s.grossProfit)], ["Gross loss", money(s.grossLoss)],
      ["Commission paid", money(s.commission)],
    ]],
    ["Risk", [
      ["Max drawdown", isNum(s.maxDrawdownPct) ? `−${pct(s.maxDrawdownPct)}` : "—"], ["Max drawdown ($)", money(s.maxDrawdown ? -s.maxDrawdown : null)],
      ["Longest drawdown", `${num(s.longestDrawdownDays, 0)} days`], ["Sharpe ratio", num(s.sharpe)], ["Sortino ratio", num(s.sortino)],
      ["Calmar ratio", num(s.calmar)], ["Recovery factor", num(s.recoveryFactor)], ["Time in market", pct(s.exposurePct, { d: 1 })],
    ]],
    ["Trades", [
      ["Total trades", num(s.trades, 0)], ["Long / short", `${num(s.longTrades, 0)} / ${num(s.shortTrades, 0)}`],
      ["Win rate", pct(s.winRate, { d: 1 })], ["Long / short win rate", `${pct(s.longWinRate, { d: 0 })} / ${pct(s.shortWinRate, { d: 0 })}`],
      ["Profit factor", num(s.profitFactor)], ["Expectancy", money(s.expectancy, { sign: true })],
      ["Average win / loss", `${money(s.avgWin)} / ${money(s.avgLoss)}`], ["Largest win / loss", `${money(s.largestWin)} / ${money(s.largestLoss)}`],
      ["Max wins / losses in a row", `${num(s.maxConsecWins, 0)} / ${num(s.maxConsecLosses, 0)}`],
      ["Average bars held", num(s.avgBarsHeld, 1)], ["Average hold time", duration(s.avgHoldHours)], ["Average R multiple", num(s.avgR, 2)],
    ]],
  ];
  const st = r.settings;
  return (
    <>
      <div className="stats-groups">
        {groups.map(([title, rows]) => (
          <section className="card" key={title}>
            <header><h3>{title}</h3></header>
            <div className="pad">{rows.map(([k, v]) => <div className="stat-row" key={k}><span>{k}</span><span>{v}</span></div>)}</div>
          </section>
        ))}
      </div>
      <section className="card" style={{ marginTop: 14 }}>
        <header><h3>Run settings</h3><div className="aside">Exactly what this result assumed</div></header>
        <div className="pad" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", columnGap: 24 }}>
          {[["Starting capital", money(st.initial_capital as number)], ["Sizing", `${st.qty_mode}, ${st.default_qty}`],
            ["Commission", `${money(st.commission_per_unit as number)} + ${st.commission_pct}%`], ["Slippage", `${st.slippage_ticks} ticks`],
            ["Spread", String(st.spread)], ["Tick size", String(st.tick_size)], ["Point value / contract size", String(st.point_value)],
            ["Pyramiding", String(st.pyramiding)], ["Shorting", st.allow_short ? "Allowed" : "Off"], ["Account", st.hedging ? "Hedging" : "Netting"],
          ].map(([k, v]) => <div className="stat-row" key={k}><span>{k}</span><span>{v}</span></div>)}
        </div>
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------- log
const KINDS = ["signal", "fill", "exit", "order", "log", "info", "warn"];
const KIND_NAMES: Record<string, string> = { signal: "Signals", fill: "Fills", exit: "Exits", order: "Orders", log: "Script output", info: "Info", warn: "Warnings" };

function Log({ r, onPick }: { r: RunResult; onPick: (tradeId: number) => void }) {
  const counts = useMemo(() => { const c: Record<string, number> = {}; r.events.forEach((e) => { c[e.kind] = (c[e.kind] ?? 0) + 1; }); return c; }, [r]);
  const [on, setOn] = useState<Set<string>>(new Set(KINDS.filter((k) => k !== "order")));
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(1500);
  const rows = useMemo(() => r.events.filter((e) => on.has(e.kind) && (!q || e.text.toLowerCase().includes(q.toLowerCase()))), [r, on, q]);
  const intraday = /m$|h$/.test(r.data.timeframe);
  return (
    <div className="card">
      <div className="filters">
        {KINDS.filter((k) => counts[k]).map((k) => (
          <label className="check" key={k}>
            <input type="checkbox" checked={on.has(k)} onChange={() => { const n = new Set(on); if (n.has(k)) n.delete(k); else n.add(k); setOn(n); }} />
            {KIND_NAMES[k]} <span className="hint">{num(counts[k], 0)}</span>
          </label>
        ))}
        <input className="input" placeholder="Search the log" value={q} onChange={(e) => setQ(e.target.value)} style={{ marginLeft: "auto" }} />
      </div>
      <div className="table-wrap">
        {rows.slice(0, limit).map((e, i) => (
          <div className="log-row" key={i} onClick={() => e.trade != null && onPick(e.trade)} style={{ cursor: e.trade != null ? "pointer" : "default" }}>
            <span className="when">{date(e.time, intraday)}</span>
            <span className={`tag ${e.kind}`}>{e.kind}</span>
            <span>{e.text}</span>
          </div>
        ))}
        {!rows.length && <div className="pad hint">Nothing matches these filters.</div>}
        {rows.length > limit && <div className="pad"><button className="btn small" onClick={() => setLimit(limit + 3000)}>Show more</button></div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------- errors
export function ErrorPanel({ error, preview, onDismiss }: { error: EngineError; preview?: string; onDismiss: () => void }) {
  const lines = preview?.split("\n") ?? [];
  const ln = error.line ?? null;
  const peek = ln != null && ln <= lines.length ? lines.slice(Math.max(0, ln - 3), ln + 2).map((t, i) => ({ n: Math.max(1, ln - 2) + i, t })) : [];
  const title = error.kind === "UnsupportedFeature" ? "This script uses something Tickbench can't run yet"
    : error.kind === "DataError" ? "The price data couldn't be used"
    : error.kind === "Cancelled" ? "Backtest stopped"
    : error.kind === "InternalError" ? "Tickbench hit a bug" : "The backtest stopped with an error";
  return (
    <div style={{ maxWidth: 760 }}>
      <h2 style={{ fontSize: 18, margin: "8px 0 12px", fontWeight: 600 }}>{title}</h2>
      <div className="error-card" role="alert">
        <h4>{error.message}</h4>
        {error.hint && <p>{error.hint}</p>}
        {ln != null && <div className="where">{error.file ? `${error.file}, ` : ""}line {ln}</div>}
        {peek.length > 0 && (
          <div className="code-peek">{peek.map((p) => <div key={p.n} className={p.n === ln ? "hit" : ""}><i>{p.n}</i>{p.t || " "}</div>)}</div>
        )}
        {error.trace && <pre>{error.trace}</pre>}
      </div>
      <button className="btn small" style={{ marginTop: 12 }} onClick={onDismiss}>Dismiss</button>
    </div>
  );
}
