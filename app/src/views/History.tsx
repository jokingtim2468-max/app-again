import { Spark, Trash } from "../components/Icons";
import { ago, KIND_LABEL, money, num, pct } from "../format";
import type { RunSummary } from "../types";

interface Props {
  runs: RunSummary[];
  onOpen: (id: string) => void;
  compareIds: string[];
  setCompareIds: (ids: string[]) => void;
  onCompare: () => void;
  onDelete: (id: string) => void;
}

export function History({ runs, onOpen, compareIds, setCompareIds, onCompare, onDelete }: Props) {
  const toggle = (id: string) => setCompareIds(compareIds.includes(id) ? compareIds.filter((x) => x !== id) : [...compareIds, id].slice(-4));
  if (!runs.length) {
    return (
      <div className="empty">
        <h2>No runs yet</h2>
        <p className="lead">Every backtest you run is saved here with its settings, so you can reopen it or compare it against a variation later.</p>
      </div>
    );
  }
  return (
    <div>
      <div className="result-head">
        <div><h1>Run history</h1><div className="sub"><span className="chip">{runs.length} saved on this PC</span></div></div>
        <div className="actions">
          <span className="hint" style={{ alignSelf: "center" }}>{compareIds.length < 2 ? "Tick 2 to 4 runs to compare them" : `${compareIds.length} selected`}</span>
          <button className="btn small" disabled={compareIds.length < 2} onClick={onCompare}>Compare selected</button>
        </div>
      </div>
      <div className="history-list">
        {runs.map((r) => (
          <div className="history-item" key={r.id} onClick={() => onOpen(r.id)} role="button" tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && onOpen(r.id)}>
            <input type="checkbox" aria-label={`Select ${r.script} for comparison`} checked={compareIds.includes(r.id)}
              onClick={(e) => e.stopPropagation()} onChange={() => toggle(r.id)} style={{ accentColor: "var(--accent)" }} />
            <div style={{ minWidth: 0 }}>
              <div className="title">{r.script}</div>
              <div className="sub">{KIND_LABEL[r.kind] ?? r.kind} on {r.symbol} {r.timeframe}, {ago(r.createdAt)}
                {Object.keys(r.params ?? {}).length ? `, ${Object.entries(r.params).slice(0, 3).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}</div>
            </div>
            <Spark values={r.spark} w={130} h={30} />
            <div className="r"><span className="lbl">Net profit</span><span className={(r.netProfit ?? 0) >= 0 ? "up" : "down"}>{money(r.netProfit, { sign: true, d: 0 })}</span></div>
            <div className="r"><span className="lbl">Max DD</span>{pct(r.maxDrawdownPct ? -r.maxDrawdownPct : null, { d: 1 })}</div>
            <div className="r"><span className="lbl">Sharpe</span>{num(r.sharpe)}</div>
            <div className="r"><span className="lbl">Trades</span>{num(r.trades, 0)}</div>
            <button className="icon-btn" aria-label={`Delete run ${r.script}`} onClick={(e) => { e.stopPropagation(); onDelete(r.id); }}><Trash /></button>
          </div>
        ))}
      </div>
    </div>
  );
}
