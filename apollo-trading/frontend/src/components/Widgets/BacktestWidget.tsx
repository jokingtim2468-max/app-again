import { useEffect, useState } from 'react';
import { api } from '../../api';
import { usd } from '../../stores/useFleetStore';

interface Pt { date: string; balance: number; mll: number; drawdown: number }
interface Result {
  strategy: string; trades: number; win_rate: number; profit_factor: number | null; max_drawdown_eod: number;
  total_net_pnl: number; sharpe: number; qualified_payouts: number; liquidated_accounts_count: number;
  equity_curve: Pt[]; data_source: string;
}

function Line({ data, keys, colors, height, fillZero }: { data: Pt[]; keys: (keyof Pt)[]; colors: string[]; height: number; fillZero?: boolean }) {
  const W = 1000;
  if (data.length < 2) return null;
  const vals = data.flatMap((d) => keys.map((k) => Number(d[k])));
  if (fillZero) vals.push(0);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const x = (i: number) => (i / (data.length - 1)) * W, y = (v: number) => height - 4 - ((v - min) / span) * (height - 8);
  return (
    <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" style={{ width: '100%', height }} aria-hidden>
      {fillZero && <path d={`M0,${y(0)} ${data.map((d, i) => `L${x(i)},${y(Number(d[keys[0]]))}`).join(' ')} L${W},${y(0)} Z`} fill="rgba(255,93,108,.18)" />}
      {keys.map((k, j) => <polyline key={k} vectorEffect="non-scaling-stroke" points={data.map((d, i) => `${x(i)},${y(Number(d[k]))}`).join(' ')} fill="none" stroke={colors[j]} strokeWidth={1.5} strokeDasharray={k === 'mll' ? '5 4' : undefined} />)}
    </svg>
  );
}

export default function BacktestWidget() {
  const [strategies, setStrategies] = useState<string[]>(['news_momentum', 'news_fade', 'breakout']);
  const [f, setF] = useState({ strategy_name: 'news_momentum', start_date: '2025-01-01', end_date: '2025-12-31', lot_size_micros: 20, stage: 'EVALUATION', tick_csv: '' });
  const [res, setRes] = useState<Result | null>(null);
  const [stress, setStress] = useState<{ m: number; pnl: number; liq: number }[]>([]);
  const [busy, setBusy] = useState(''); const [err, setErr] = useState('');
  useEffect(() => { api<string[]>('/api/strategies').then(setStrategies).catch(() => undefined); }, []);
  const body = (m = 1) => JSON.stringify({ ...f, tick_csv: f.tick_csv || null, spread_multiplier: m });

  const run = async () => {
    setBusy('run'); setErr('');
    try { setRes(await api<Result>('/api/backtest', { method: 'POST', body: body() })); setStress([]); }
    catch (e) { setErr(String(e)); } finally { setBusy(''); }
  };
  const runStress = async () => {
    setBusy('stress'); setErr('');
    try {
      const out = [];
      for (const m of [1, 1.5, 2, 3]) {
        const r = await api<Result>('/api/backtest', { method: 'POST', body: body(m) });
        out.push({ m, pnl: r.total_net_pnl, liq: r.liquidated_accounts_count });
      }
      setStress(out);
    } catch (e) { setErr(String(e)); } finally { setBusy(''); }
  };

  return (
    <div style={{ padding: 10, display: 'grid', gap: 10 }}>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <select aria-label="Strategy" value={f.strategy_name} onChange={(e) => setF({ ...f, strategy_name: e.target.value })}>{strategies.map((s) => <option key={s}>{s}</option>)}</select>
        <input aria-label="Start" type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} />
        <input aria-label="End" type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} />
        <label className="row mut">MGC <input type="number" min={1} max={100} value={f.lot_size_micros} onChange={(e) => setF({ ...f, lot_size_micros: +e.target.value })} style={{ width: 56 }} /></label>
        <select aria-label="Stage" value={f.stage} onChange={(e) => setF({ ...f, stage: e.target.value })}><option>EVALUATION</option><option>FUNDED</option></select>
        <input aria-label="Tick CSV path" placeholder="tick CSV (optional)" value={f.tick_csv} onChange={(e) => setF({ ...f, tick_csv: e.target.value })} style={{ width: 160 }} />
        <button className="primary" onClick={run} disabled={!!busy}>{busy === 'run' ? 'Running…' : 'Run'}</button>
        <button onClick={runStress} disabled={!!busy}>{busy === 'stress' ? 'Stressing…' : 'Slippage stress'}</button>
      </div>
      {err && <div className="neg">{err}</div>}
      {res && (<>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(96px, 1fr))', gap: 6 }}>
          {[
            ['Net PnL', usd(res.total_net_pnl, 0), res.total_net_pnl >= 0 ? 'pos' : 'neg'], ['Trades', String(res.trades), ''],
            ['Win rate', `${(res.win_rate * 100).toFixed(1)}%`, ''], ['Profit factor', res.profit_factor?.toFixed(2) ?? '∞', ''],
            ['Sharpe', res.sharpe.toFixed(2), ''], ['Max EOD DD', usd(res.max_drawdown_eod, 0), 'warn'],
            ['Payouts', String(res.qualified_payouts), ''], ['Liquidations', String(res.liquidated_accounts_count), res.liquidated_accounts_count ? 'neg' : ''],
          ].map(([l, v, c]) => (
            <div key={l} style={{ border: '1px solid var(--line)', borderRadius: 5, padding: '6px 8px' }}>
              <p className="h">{l}</p><div className={`mono ${c}`} style={{ fontSize: 15 }}>{v}</div>
            </div>
          ))}
        </div>
        <div><p className="h">Closed balance vs MLL · data {res.data_source}</p><Line data={res.equity_curve} keys={['balance', 'mll']} colors={['#6CF0C2', '#FF5D6C']} height={150} /></div>
        <div><p className="h">Underwater (drawdown from EOD peak)</p><Line data={res.equity_curve} keys={['drawdown']} colors={['#FF5D6C']} height={70} fillZero /></div>
      </>)}
      {stress.length > 0 && (
        <table><thead><tr><th>Spread ×</th><th>Net PnL</th><th>Liquidations</th></tr></thead>
          <tbody>{stress.map((s) => <tr key={s.m}><td>{s.m}×</td><td className={s.pnl >= 0 ? 'pos' : 'neg'}>{usd(s.pnl, 0)}</td><td>{s.liq}</td></tr>)}</tbody></table>
      )}
      {!res && !err && <div className="mut">Synthetic data validates rule logic only. Point at a tick CSV for real-market results.</div>}
    </div>
  );
}
