import { useEffect, useState } from 'react';
import { api } from '../../api';
import { usd } from '../../stores/useFleetStore';

interface Pt { date: string; balance: number; mll: number; drawdown: number }
interface Adapter { name: string; style: string; entrypoint: string; source_path: string; source_sha256: string; report: string[] }
interface Trade { exit_time?: string; side?: string; qty?: number; entry?: number; exit?: number; pnl?: number; event?: string; liquidation?: boolean }
interface Result {
  strategy: string; engine?: string; trades: number; win_rate: number; profit_factor: number | null; max_drawdown_eod: number;
  total_net_pnl: number; sharpe: number; qualified_payouts: number; liquidated_accounts_count: number;
  equity_curve: Pt[]; data_source: string; adapter?: Adapter; trade_log?: Trade[]; note?: string; slippage_cost_usd?: number;
}
interface Fwd { running: boolean; source?: string; symbol?: string; position?: number; entry?: number; realized?: number; open_pnl?: number; mark?: number; last_bar?: string; error?: string | null; trades?: { pnl: number }[]; script?: Adapter }

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

function Report({ a }: { a: Adapter }) {
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 5, padding: '6px 8px', fontSize: 11.5 }}>
      <p className="h">Adapter · <span style={{ color: 'var(--accent)' }}>{a.style}</span> · entry <span className="mono">{a.entrypoint}</span></p>
      {a.report.map((r, i) => <div key={i} className={r.startsWith('WARNING') ? 'warn' : 'mut'}>• {r}</div>)}
    </div>
  );
}

export default function BacktestWidget() {
  const [tab, setTab] = useState<'backtest' | 'forward'>('backtest');
  const [strategies, setStrategies] = useState<string[]>([]);
  const [f, setF] = useState({ strategy_name: 'news_momentum', script_path: '', start_date: '2025-01-01', end_date: '2025-03-31',
    lot_size_micros: 20, stage: 'EVALUATION', data_source: 'synthetic', symbol: 'XAUUSD', timeframe: '5m', data_path: '' });
  const [res, setRes] = useState<Result | null>(null);
  const [inspect, setInspect] = useState<Adapter | null>(null);
  const [stress, setStress] = useState<{ m: number; pnl: number; liq: number }[]>([]);
  const [mt5, setMt5] = useState<{ connected: boolean; transport: string; error?: string; server?: string } | null>(null);
  const [fwd, setFwd] = useState<Fwd>({ running: false });
  const [busy, setBusy] = useState(''); const [err, setErr] = useState('');
  useEffect(() => { api<string[]>('/api/strategies').then(setStrategies).catch(() => undefined); }, []);
  useEffect(() => { if (f.data_source === 'mt5' || tab === 'forward') api<typeof mt5>('/api/mt5/status').then(setMt5).catch(() => undefined); }, [f.data_source, tab]);
  useEffect(() => {
    if (tab !== 'forward') return;
    const t = setInterval(() => api<Fwd>('/api/forward/status').then(setFwd).catch(() => undefined), 2000);
    api<Fwd>('/api/forward/status').then(setFwd).catch(() => undefined);
    return () => clearInterval(t);
  }, [tab]);

  const script = f.script_path.trim() || f.strategy_name;
  const body = (m = 1) => JSON.stringify({ ...f, script_path: f.script_path.trim() || null, data_path: f.data_path.trim() || null, spread_multiplier: m });
  const guard = async (k: string, fn: () => Promise<void>) => { setBusy(k); setErr(''); try { await fn(); } catch (e) { setErr(String(e)); } finally { setBusy(''); } };

  const run = () => guard('run', async () => { setRes(await api<Result>('/api/backtest', { method: 'POST', body: body() })); setStress([]); setInspect(null); });
  const doInspect = () => guard('inspect', async () => setInspect(await api<Adapter>('/api/strategies/inspect', { method: 'POST', body: JSON.stringify({ script }) })));
  const runStress = () => guard('stress', async () => {
    const out = [];
    for (const m of [1, 1.5, 2, 3]) { const r = await api<Result>('/api/backtest', { method: 'POST', body: body(m) }); out.push({ m, pnl: r.total_net_pnl, liq: r.liquidated_accounts_count }); }
    setStress(out);
  });
  const fwdStart = () => guard('fwd', async () => setFwd(await api<Fwd>('/api/forward/start', { method: 'POST', body: JSON.stringify({ script, source: f.data_source === 'mt5' ? 'mt5' : 'sim', symbol: f.symbol, timeframe: f.timeframe, lot_size_micros: f.lot_size_micros }) })));
  const fwdStop = () => guard('fwd', async () => setFwd(await api<Fwd>('/api/forward/stop', { method: 'POST' })));
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: k === 'lot_size_micros' ? +e.target.value : e.target.value });

  return (
    <div style={{ padding: 10, display: 'grid', gap: 9 }}>
      <div className="row" role="tablist">
        {(['backtest', 'forward'] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'primary' : 'ghost'} onClick={() => setTab(t)}>
            {t === 'backtest' ? 'Backtest (past data)' : 'Forward test (live data)'}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        {mt5 && <span className="pill" style={{ color: mt5.connected ? 'var(--good)' : 'var(--muted)' }} title={mt5.error || mt5.server || ''}><span className="dot" />MT5 {mt5.connected ? `${mt5.transport}` : 'offline'}</span>}
      </div>

      <div className="row" style={{ flexWrap: 'wrap' }}>
        <select aria-label="Strategy" value={f.strategy_name} onChange={set('strategy_name')} disabled={!!f.script_path.trim()}>
          {(strategies.length ? strategies : [f.strategy_name]).map((s) => <option key={s}>{s}</option>)}
        </select>
        <input aria-label="Script path" placeholder="…or any script path (.pine .py .ipynb .mq5 .ex5 .csv .json)" value={f.script_path} onChange={set('script_path')} style={{ flex: 1, minWidth: 200 }} />
        <button onClick={doInspect} disabled={!!busy}>{busy === 'inspect' ? '…' : 'Inspect'}</button>
      </div>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <select aria-label="Data source" value={f.data_source} onChange={set('data_source')}>
          <option value="synthetic">Synthetic (seeded)</option><option value="csv">CSV file</option><option value="mt5">MetaTrader 5</option>
        </select>
        {f.data_source === 'mt5' && <input aria-label="MT5 symbol" value={f.symbol} onChange={set('symbol')} style={{ width: 90 }} title="Broker symbol, e.g. XAUUSD or GOLD" />}
        {f.data_source === 'csv' && <input aria-label="Data CSV path" placeholder="bars or ticks CSV path" value={f.data_path} onChange={set('data_path')} style={{ width: 200 }} />}
        <select aria-label="Timeframe" value={f.timeframe} onChange={set('timeframe')}>{['1m', '5m', '15m', '30m', '1h', '4h', '1d'].map((t) => <option key={t}>{t}</option>)}</select>
        {tab === 'backtest' && <>
          <input aria-label="Start" type="date" value={f.start_date} onChange={set('start_date')} />
          <input aria-label="End" type="date" value={f.end_date} onChange={set('end_date')} />
          <select aria-label="Stage" value={f.stage} onChange={set('stage')}><option>EVALUATION</option><option>FUNDED</option></select>
        </>}
        <label className="row mut">MGC <input type="number" min={1} max={100} value={f.lot_size_micros} onChange={set('lot_size_micros')} style={{ width: 54 }} /></label>
        {tab === 'backtest'
          ? <><button className="primary" onClick={run} disabled={!!busy}>{busy === 'run' ? 'Running…' : 'Run'}</button>
              <button onClick={runStress} disabled={!!busy}>{busy === 'stress' ? 'Stressing…' : 'Slippage stress'}</button></>
          : fwd.running ? <button className="danger" onClick={fwdStop} disabled={!!busy}>Stop</button>
            : <button className="primary" onClick={fwdStart} disabled={!!busy}>Start paper forward test</button>}
      </div>
      {err && <div className="neg" style={{ whiteSpace: 'pre-wrap' }}>{err}</div>}
      {inspect && <Report a={inspect} />}

      {tab === 'forward' && (
        <div style={{ display: 'grid', gap: 6 }}>
          <div className="mut" style={{ fontSize: 11.5 }}>Runs your script on each newly closed live bar and paper-fills at the live price. No orders reach any broker. {f.data_source !== 'mt5' && 'Source: SIM feed (choose MetaTrader 5 above for real live data).'}</div>
          {fwd.running || fwd.trades?.length ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))', gap: 6 }}>
              {[['Status', fwd.running ? 'RUNNING' : 'stopped', fwd.running ? 'pos' : 'mut'], ['Source', `${fwd.source ?? ''} ${fwd.symbol ?? ''}`, ''],
                ['Position', String(fwd.position ?? 0), ''], ['Mark', fwd.mark ? fwd.mark.toFixed(2) : '—', ''],
                ['Open PnL', usd(fwd.open_pnl ?? 0), (fwd.open_pnl ?? 0) >= 0 ? 'pos' : 'neg'], ['Realized', usd(fwd.realized ?? 0), (fwd.realized ?? 0) >= 0 ? 'pos' : 'neg'],
                ['Trades', String(fwd.trades?.length ?? 0), ''], ['Last bar', fwd.last_bar ? fwd.last_bar.slice(5, 16) : '—', 'mut'],
              ].map(([l, v, c]) => <div key={l} style={{ border: '1px solid var(--line)', borderRadius: 5, padding: '6px 8px' }}><p className="h">{l}</p><div className={`mono ${c}`}>{v}</div></div>)}
            </div>) : null}
          {fwd.error && <div className="neg">{fwd.error}</div>}
          {fwd.script && <Report a={fwd.script} />}
        </div>
      )}

      {tab === 'backtest' && res && (<>
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
        {res.adapter && <Report a={res.adapter} />}
        {res.note && <div className="mut" style={{ fontSize: 11.5 }}>{res.note}</div>}
        <div><p className="h">Closed balance vs MLL · {res.engine} engine · data {res.data_source}</p><Line data={res.equity_curve} keys={['balance', 'mll']} colors={['#6CF0C2', '#FF5D6C']} height={150} /></div>
        <div><p className="h">Underwater (drawdown from EOD peak)</p><Line data={res.equity_curve} keys={['drawdown']} colors={['#FF5D6C']} height={70} fillZero /></div>
        {!!res.trade_log?.length && (
          <details><summary className="h" style={{ cursor: 'pointer' }}>Trade log (last {res.trade_log.length})</summary>
            <table><thead><tr><th>Exit time</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>PnL</th></tr></thead>
              <tbody>{res.trade_log.slice().reverse().map((t, i) => t.event
                ? <tr key={i}><td>{t.exit_time?.slice(0, 16)}</td><td colSpan={5} className="pos">{t.event}</td></tr>
                : <tr key={i}><td>{t.exit_time?.slice(0, 16)}</td><td>{t.side}{t.liquidation ? ' ⚠' : ''}</td><td>{t.qty}</td><td>{t.entry}</td><td>{t.exit}</td><td className={(t.pnl ?? 0) >= 0 ? 'pos' : 'neg'}>{usd(t.pnl ?? 0)}</td></tr>)}</tbody></table>
          </details>)}
      </>)}
      {tab === 'backtest' && stress.length > 0 && (
        <table><thead><tr><th>Spread ×</th><th>Net PnL</th><th>Liquidations</th></tr></thead>
          <tbody>{stress.map((s) => <tr key={s.m}><td>{s.m}×</td><td className={s.pnl >= 0 ? 'pos' : 'neg'}>{usd(s.pnl, 0)}</td><td>{s.liq}</td></tr>)}</tbody></table>
      )}
      {tab === 'backtest' && !res && !err && !inspect && <div className="mut">Pick a script (any style) and a data source. Your file is never changed: Apollo adapts a private copy.</div>}
    </div>
  );
}
