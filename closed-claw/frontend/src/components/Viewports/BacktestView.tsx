import { useState } from 'react';
import { api } from '../../api';

interface Result {
  strategy: string; trades: number; win_rate: number; profit_factor: number | null; max_drawdown_eod: number;
  total_net_pnl: number; sharpe: number; qualified_payouts: number; liquidated_accounts_count: number;
  equity_curve: { date: string; balance: number; mll: number }[];
  news_slippage: { date: string; slip_ticks: number; cost_usd: number }[]; data_source: string;
}

function Curve({ data }: { data: Result['equity_curve'] }) {
  const W = 900, H = 260;
  if (data.length < 2) return null;
  const vals = data.flatMap((d) => [d.balance, d.mll]);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const x = (i: number) => (i / (data.length - 1)) * W, y = (v: number) => H - ((v - min) / span) * (H - 20) - 10;
  const line = (k: 'balance' | 'mll') => data.map((d, i) => `${x(i)},${y(d[k])}`).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: H }} role="img" aria-label="Equity curve vs MLL">
      {[0.25, 0.5, 0.75].map((f) => <line key={f} x1={0} x2={W} y1={H * f} y2={H * f} stroke="var(--line)" />)}
      <polyline points={line('mll')} fill="none" stroke="var(--bad)" strokeDasharray="4 4" strokeWidth={1.2} />
      <polyline points={line('balance')} fill="none" stroke="var(--accent)" strokeWidth={1.8} />
    </svg>
  );
}

export default function BacktestView() {
  const [form, setForm] = useState({ strategy_name: 'news_momentum', start_date: '2025-01-01', end_date: '2025-12-31', lot_size_micros: 20, event_filter: 'CPI,CORE_PCE,NFP,FOMC' });
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setErr('');
    try {
      setRes(await api<Result>('/api/backtest', { method: 'POST', body: JSON.stringify({ ...form, event_filter: form.event_filter.split(',').map((s) => s.trim()).filter(Boolean) }) }));
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const stat = (label: string, v: string, cls = '') => (
    <div className="wire" style={{ padding: 12 }}><p className="h" style={{ marginBottom: 4 }}>{label}</p><div className={cls} style={{ fontSize: 20, fontFamily: 'var(--mono)' }}>{v}</div></div>
  );
  return (
    <div className="grid">
      <p className="h">MGC news backtest · LucidFlex 150K EOD rules</p>
      <div className="row wire" style={{ padding: 12 }}>
        <select value={form.strategy_name} onChange={(e) => setForm({ ...form, strategy_name: e.target.value })} aria-label="Strategy">
          <option>news_momentum</option><option>news_fade</option><option>breakout</option>
        </select>
        <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} aria-label="Start" />
        <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} aria-label="End" />
        <input type="number" value={form.lot_size_micros} onChange={(e) => setForm({ ...form, lot_size_micros: +e.target.value })} style={{ width: 70 }} aria-label="Micros" />
        <input value={form.event_filter} onChange={(e) => setForm({ ...form, event_filter: e.target.value })} style={{ width: 220 }} aria-label="Events" />
        <button onClick={run} disabled={busy}>{busy ? 'Running…' : 'Run backtest'}</button>
      </div>
      {err && <div className="neg">{err}</div>}
      {res && (<>
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
          {stat('Net PnL', `$${res.total_net_pnl.toLocaleString()}`, res.total_net_pnl >= 0 ? 'pos' : 'neg')}
          {stat('Win rate', `${(res.win_rate * 100).toFixed(1)}%`)}
          {stat('Profit factor', res.profit_factor?.toFixed(2) ?? '∞')}
          {stat('Sharpe', res.sharpe.toFixed(2))}
          {stat('Max EOD DD', `$${res.max_drawdown_eod.toLocaleString()}`, 'warn')}
          {stat('Payouts', String(res.qualified_payouts))}
          {stat('Liquidations', String(res.liquidated_accounts_count), res.liquidated_accounts_count ? 'neg' : '')}
        </div>
        <div className="wire" style={{ padding: 12 }}>
          <p className="h">Closed balance vs MLL · {res.trades} trades · data: {res.data_source}</p>
          <Curve data={res.equity_curve} />
        </div>
        <div className="wire" style={{ padding: 12 }}>
          <p className="h">News slippage (last {res.news_slippage.length})</p>
          <table><thead><tr><th>Date</th><th>Slip ticks</th><th>Cost</th></tr></thead>
            <tbody>{res.news_slippage.map((s, i) => <tr key={i}><td>{s.date}</td><td>{s.slip_ticks}</td><td className="neg">${s.cost_usd}</td></tr>)}</tbody></table>
        </div>
      </>)}
    </div>
  );
}
