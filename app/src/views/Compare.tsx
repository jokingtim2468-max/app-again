import { useEffect, useState } from "react";
import { call } from "../api";
import { CompareChart, COMPARE_VARS } from "../charts/CompareChart";
import { KIND_LABEL, money, num, pct } from "../format";
import type { RunResult, RunSummary } from "../types";

const ROWS: [string, string, (v: number | null) => string, 1 | -1][] = [
  ["Net profit", "netProfit", (v) => money(v, { sign: true }), 1],
  ["Return", "netProfitPct", (v) => pct(v, { sign: true }), 1],
  ["Annual return", "cagr", (v) => pct(v, { sign: true }), 1],
  ["Max drawdown", "maxDrawdownPct", (v) => (v == null ? "—" : `−${pct(v, { d: 1 })}`), -1],
  ["Sharpe", "sharpe", (v) => num(v), 1],
  ["Sortino", "sortino", (v) => num(v), 1],
  ["Profit factor", "profitFactor", (v) => num(v), 1],
  ["Win rate", "winRate", (v) => pct(v, { d: 1 }), 1],
  ["Trades", "trades", (v) => num(v, 0), 0 as never],
  ["Expectancy", "expectancy", (v) => money(v, { sign: true }), 1],
  ["Time in market", "exposurePct", (v) => pct(v, { d: 0 }), 0 as never],
];

export function Compare({ ids, runs, onBack }: { ids: string[]; runs: RunSummary[]; onBack: () => void }) {
  const [full, setFull] = useState<RunResult[]>([]);
  useEffect(() => {
    Promise.all(ids.slice(0, 4).map((id) => call<RunResult>("runs.get", { id }))).then(setFull).catch(() => setFull([]));
  }, [ids]);
  if (ids.length < 2) return <div className="empty"><h2>Pick runs to compare</h2><p className="lead">Tick two to four runs in History.</p><button className="btn" onClick={onBack}>Open history</button></div>;
  const label = (r: RunResult) => `${r.script.filename}${Object.keys(r.script.params ?? {}).length ? ` (${Object.entries(r.script.params).slice(0, 2).map(([k, v]) => `${k} ${v}`).join(", ")})` : ""}`;
  void runs;
  return (
    <div>
      <div className="result-head">
        <div><h1>Comparing {ids.length} runs</h1><div className="sub"><span className="chip">Equity shown as % return so different capital sizes line up</span></div></div>
        <div className="actions"><button className="btn small" onClick={onBack}>Back to history</button></div>
      </div>
      <section className="card">
        <header>
          <h3>Return over time</h3>
          <div className="aside legend">
            {full.map((r, k) => <span key={r.id}><i style={{ background: `var(${COMPARE_VARS[k]})` }} />{label(r)}</span>)}
          </div>
        </header>
        <div className="pad">{full.length >= 2 && <CompareChart runs={full} />}</div>
      </section>
      <section className="card" style={{ marginTop: 14 }}>
        <table className="data">
          <thead><tr><th>Metric</th>{full.map((r, k) => (
            <th key={r.id} className="r"><i style={{ display: "inline-block", width: 10, height: 2, background: `var(${COMPARE_VARS[k]})`, marginRight: 6, verticalAlign: "middle" }} />
              {KIND_LABEL[r.script.kind]}, {r.data.symbol}</th>))}</tr></thead>
          <tbody>
            {ROWS.map(([name, key, fmt, better]) => {
              const vals = full.map((r) => r.stats[key] ?? null);
              const nums = vals.filter((v): v is number => v != null);
              const best = better ? (better > 0 ? Math.max(...nums) : Math.min(...nums)) : null;
              return (
                <tr key={key}>
                  <td>{name}</td>
                  {vals.map((v, k) => <td key={k} className="r mono" style={v === best && nums.length > 1 ? { fontWeight: 600, color: "var(--ink)" } : { color: "var(--ink-2)" }}>
                    {fmt(v)}{v === best && nums.length > 1 ? " ★" : ""}</td>)}
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
