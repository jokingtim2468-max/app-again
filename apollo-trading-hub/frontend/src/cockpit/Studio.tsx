import { useEffect, useRef, useState } from 'react';
import { AreaSeries, ColorType, createChart, LineSeries, LineStyle } from 'lightweight-charts';
import { api } from '../api';
import { fmt, money } from './store';
import { Panel, tone } from './ui';

interface Month { month: string; net: number; trades: number; win_rate: number; max_dd: number; commission: number }
interface Result {
  trades: number; net: number; win_rate: number; profit_factor: number | null; expectancy: number; max_drawdown: number; commission: number;
  exits: Record<string, number>; days: number; avg_day: number; best_day: number; consistency_ok: boolean;
  evaluation: { passed_on: string | null; blown_on: string | null; start: number; target: number; trailing_dd: number };
  monthly: Month[]; equity: { time: string; balance: number; floor: number }[]; underwater: { time: string; drawdown: number }[];
}
interface GridRes { axes: string[]; rows: Record<string, number | string | null>[]; best: Record<string, number | string | null> | null; note: string }

function EquityChart({ r }: { r: Result }) {
  const a = useRef<HTMLDivElement>(null), b = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!a.current || !b.current || !r.equity.length) return;
    const opts = { autoSize: true, layout: { background: { type: ColorType.Solid, color: '#0F172A' }, textColor: '#94A3B8', fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: '#162036' }, horzLines: { color: '#162036' } }, rightPriceScale: { borderColor: '#1E293B' }, timeScale: { borderColor: '#1E293B' } } as const;
    const c1 = createChart(a.current, opts), c2 = createChart(b.current, opts);
    c1.addSeries(LineSeries, { color: '#10B981', lineWidth: 2 }).setData(r.equity.map((e) => ({ time: e.time, value: e.balance })));
    c1.addSeries(LineSeries, { color: '#F43F5E', lineWidth: 1, lineStyle: LineStyle.Dashed, title: 'floor' }).setData(r.equity.map((e) => ({ time: e.time, value: e.floor })));
    c2.addSeries(AreaSeries, { lineColor: '#F43F5E', topColor: '#F43F5E10', bottomColor: '#F43F5E55', lineWidth: 1 }).setData(r.underwater.map((e) => ({ time: e.time, value: e.drawdown })));
    c1.timeScale().fitContent(); c2.timeScale().fitContent();
    return () => { c1.remove(); c2.remove(); };
  }, [r]);
  return <><div className="sub">Equity vs trailing floor</div><div ref={a} style={{ height: 220 }} /><div className="sub" style={{ marginTop: 6 }}>Underwater (drawdown from peak)</div><div ref={b} style={{ height: 110 }} /></>;
}

const AXES: [string, string, string][] = [
  ['be_trigger_r', 'Breakeven trigger R', '0.40, 0.45, 0.50'], ['be_lock', 'Breakeven lock pts', '0.60, 0.76, 0.90'],
  ['base_tp', 'Take profit pts', ''], ['sl_cap', 'SL cap pts', ''], ['confluence_min', 'Confluence min', ''],
  ['session_filter', 'Session (all / london_ny)', 'all, london_ny'],
];

export default function Studio() {
  const [src, setSrc] = useState({ data_source: 'synthetic', start_date: '2026-09-01', end_date: '2026-10-01', symbol: 'XAUUSD', data_path: '' });
  const [ev, setEv] = useState({ start: 50000, target: 3000, trailing_dd: 2000, consistency: 0.4 });
  const [axes, setAxes] = useState<Record<string, string>>(Object.fromEntries(AXES.map(([k, , d]) => [k, d])));
  const [maxDd, setMaxDd] = useState('250');
  const [res, setRes] = useState<Result | null>(null); const [grid, setGrid] = useState<GridRes | null>(null);
  const [busy, setBusy] = useState(''); const [err, setErr] = useState('');
  const body = (extra: object) => JSON.stringify({ ...src, data_path: src.data_path || null, evaluation: ev, ...extra });
  const run = async () => {
    setBusy('Running backtest…'); setErr('');
    try { setRes(await api<Result>('/api/studio/backtest', { method: 'POST', body: body({}) })); } catch (e) { setErr(String(e)); }
    setBusy('');
  };
  const optimize = async () => {
    const g: Record<string, (number | string)[]> = {};
    for (const [k, v] of Object.entries(axes)) {
      const xs = v.split(',').map((s) => s.trim()).filter(Boolean);
      if (xs.length) g[k] = xs.map((x) => (Number.isNaN(Number(x)) ? x : Number(x)));
    }
    setBusy('Optimizing… (each combination is a full backtest)'); setErr('');
    try { setGrid(await api<GridRes>('/api/studio/optimize', { method: 'POST', body: body({ grid: g, max_drawdown: maxDd ? Number(maxDd) : null }) })); } catch (e) { setErr(String(e)); }
    setBusy('');
  };
  const num = (v: string) => Number(v);
  return (
    <div className="grid">
      <Panel title="Data & evaluation rules">
        <div className="form">
          <label>Data source<select value={src.data_source} onChange={(e) => setSrc({ ...src, data_source: e.target.value })}>
            <option value="synthetic">Synthetic (logic check only)</option><option value="mt5">MetaTrader 5 history</option><option value="csv">CSV file</option></select></label>
          <label>Start date<input type="date" value={src.start_date} onChange={(e) => setSrc({ ...src, start_date: e.target.value })} /></label>
          <label>End date<input type="date" value={src.end_date} onChange={(e) => setSrc({ ...src, end_date: e.target.value })} /></label>
          <label>Symbol<input value={src.symbol} onChange={(e) => setSrc({ ...src, symbol: e.target.value })} /></label>
          {src.data_source === 'csv' && <label>CSV path<input value={src.data_path} placeholder="C:\data\xauusd_m1.csv" onChange={(e) => setSrc({ ...src, data_path: e.target.value })} /></label>}
          <label>Start balance<input type="number" value={ev.start} onChange={(e) => setEv({ ...ev, start: num(e.target.value) })} /></label>
          <label>Profit target ($)<input type="number" value={ev.target} onChange={(e) => setEv({ ...ev, target: num(e.target.value) })} /></label>
          <label>Trailing drawdown ($)<input type="number" value={ev.trailing_dd} onChange={(e) => setEv({ ...ev, trailing_dd: num(e.target.value) })} /></label>
          <label>Best-day consistency (0.40 = 40%)<input type="number" step={0.05} value={ev.consistency} onChange={(e) => setEv({ ...ev, consistency: num(e.target.value) })} /></label>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="primary" disabled={!!busy} onClick={run}>Run backtest (current live params)</button>
          <span className="sub">{busy}</span><span className="neg">{err}</span>
        </div>
        <p className="sub" style={{ marginBottom: 0 }}>Fills are deliberately strict: entry on the next bar's open plus half the spread, stop checked before target inside a bar, breakeven protects from the next bar. Synthetic data has no edge: use MT5 history or a CSV for real numbers.</p>
      </Panel>

      {res && (
        <div className="grid g2">
          <Panel title="Result">
            <div className="grid g3" style={{ gap: 10 }}>
              {([['Net PnL', money(res.net), tone(res.net)], ['Trades', String(res.trades), ''], ['Win rate', `${fmt(res.win_rate * 100, 1)}%`, ''],
                ['Profit factor', res.profit_factor == null ? '—' : fmt(res.profit_factor), ''], ['Expectancy / trade', money(res.expectancy), tone(res.expectancy)],
                ['Max drawdown', money(res.max_drawdown), 'neg'], ['Avg day', money(res.avg_day), tone(res.avg_day)], ['Best day', money(res.best_day), ''],
                ['Commission', money(res.commission), '']] as [string, string, string][]).map(([k, v, c]) => <div key={k}><div className="sub">{k}</div><div className={`kpi ${c}`} style={{ fontSize: 16 }}>{v}</div></div>)}
            </div>
            <div className="row" style={{ marginTop: 12, flexWrap: 'wrap' }}>
              <span className={`chip ${res.evaluation.passed_on ? 'good' : res.evaluation.blown_on ? 'bad' : 'mut'}`}>
                {res.evaluation.passed_on ? `PASSED ${res.evaluation.passed_on}` : res.evaluation.blown_on ? `BLOWN ${res.evaluation.blown_on}` : 'NOT PASSED IN RANGE'}</span>
              <span className={`chip ${res.consistency_ok ? 'good' : 'warn'}`}>CONSISTENCY {res.consistency_ok ? 'OK' : 'FAIL'}</span>
              {Object.entries(res.exits).map(([k, v]) => <span key={k} className="chip mut">{k} {v}</span>)}
            </div>
          </Panel>
          <Panel title="Equity curve"><EquityChart r={res} /></Panel>
          <Panel title="Month by month" className="span2">
            <table><thead><tr><th>Month</th><th>Net PnL</th><th>Win rate</th><th>Trades</th><th>Max DD</th><th>Commission</th></tr></thead>
              <tbody>{res.monthly.map((m) => <tr key={m.month}><td>{m.month}</td><td className={tone(m.net)}>{money(m.net)}</td><td>{fmt(m.win_rate * 100, 1)}%</td><td>{m.trades}</td><td className="neg">{money(m.max_dd)}</td><td>{money(m.commission)}</td></tr>)}</tbody></table>
          </Panel>
        </div>
      )}

      <Panel title="Parameter grid optimizer">
        <div className="form">
          {AXES.map(([k, lbl]) => <label key={k}>{lbl} (comma list)<input className="mono" value={axes[k]} onChange={(e) => setAxes({ ...axes, [k]: e.target.value })} placeholder="leave empty = current value" /></label>)}
          <label>Max drawdown allowed ($)<input type="number" value={maxDd} onChange={(e) => setMaxDd(e.target.value)} /></label>
        </div>
        <div className="row" style={{ marginTop: 12 }}><button className="primary" disabled={!!busy} onClick={optimize}>Run grid (max 60 combinations)</button><span className="sub">{busy}</span></div>
        {grid && (
          <div style={{ marginTop: 12 }}>
            {grid.best ? <div className="chip good" style={{ marginBottom: 8 }}>BEST: {grid.axes.map((k) => `${k}=${grid.best![k]}`).join(' · ')} → {money(Number(grid.best.net))}</div> : <div className="chip warn">No combination stayed under the drawdown limit</div>}
            <div className="sub" style={{ marginBottom: 8 }}>{grid.note}</div>
            <div style={{ maxHeight: 360, overflow: 'auto' }}>
              <table><thead><tr>{grid.axes.map((k) => <th key={k}>{k}</th>)}<th>Net</th><th>Trades</th><th>Win</th><th>PF</th><th>Max DD</th><th>Eval</th></tr></thead>
                <tbody>{grid.rows.map((r, k) => (
                  <tr key={k}>{grid.axes.map((a) => <td key={a}>{String(r[a])}</td>)}<td className={tone(Number(r.net))}>{money(Number(r.net))}</td><td>{r.trades}</td>
                    <td>{fmt(Number(r.win_rate) * 100, 1)}%</td><td>{r.profit_factor ?? '—'}</td><td className="neg">{money(Number(r.max_drawdown))}</td>
                    <td>{r.passed_on ? `pass ${r.passed_on}` : r.blown_on ? `blown ${r.blown_on}` : '—'}</td></tr>))}</tbody></table>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
