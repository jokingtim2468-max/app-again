import { useEffect, useMemo, useState } from 'react';
import { API, api } from '../../api';
import { usd } from '../../stores/useFleetStore';

type Tab = 'profit' | 'payouts' | 'balances' | 'daily_pnl' | 'fills' | 'costs' | 'events';
const TABS: [Tab, string][] = [['profit', 'Profit report'], ['payouts', 'Payout log'], ['balances', 'Balance history'], ['daily_pnl', 'Daily P&L'], ['fills', 'Trades'], ['costs', 'Costs'], ['events', 'Events']];
interface Bucket { trading_pnl: number; winning_days: number; losing_days: number; payouts_gross: number; payouts_net: number; payout_count: number; costs: number; real_profit: number; firm?: string }
interface Report { totals: Record<string, number>; by_account: Record<string, Bucket>; by_firm: Record<string, Bucket>; by_month: Record<string, Bucket>; fleet_curve: { session: string; cumulative: number; fleet_pnl: number }[]; live: Record<string, { firm: string; balance: number; profit_on_account: number; paid_out: number; net_received: number; stage: string; status: string }> }
type Row = Record<string, string | number | null>;

function Spark({ pts, keys, colors, h = 140 }: { pts: Row[]; keys: string[]; colors: string[]; h?: number }) {
  if (pts.length < 2) return <div className="mut" style={{ padding: 8 }}>Not enough history yet.</div>;
  const W = 1000, vals = pts.flatMap((p) => keys.map((k) => Number(p[k]))).filter((v) => !Number.isNaN(v));
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const x = (i: number) => (i / (pts.length - 1)) * W, y = (v: number) => h - 4 - ((v - min) / span) * (h - 8);
  return (
    <svg viewBox={`0 0 ${W} ${h}`} preserveAspectRatio="none" style={{ width: '100%', height: h }} aria-hidden>
      {keys.map((k, j) => <polyline key={k} vectorEffect="non-scaling-stroke" fill="none" stroke={colors[j]} strokeWidth={1.6} strokeDasharray={k === 'mll' ? '5 4' : undefined}
        points={pts.map((p, i) => `${x(i)},${y(Number(p[k]))}`).join(' ')} />)}
    </svg>
  );
}

function BucketTable({ title, data, first }: { title: string; data: Record<string, Bucket>; first: string }) {
  const rows = Object.entries(data);
  if (!rows.length) return null;
  return (
    <div>
      <p className="h" style={{ margin: '8px 0 4px' }}>{title}</p>
      <table><thead><tr><th>{first}</th><th>Trading P&L (sim)</th><th>Win / loss days</th><th>Payouts</th><th>Gross paid</th><th>Net to you</th><th>Costs</th><th>Real profit</th></tr></thead>
        <tbody>{rows.map(([k, b]) => (
          <tr key={k}><td>{k}{b.firm ? <span className="mut"> · {b.firm}</span> : ''}</td>
            <td className={b.trading_pnl >= 0 ? 'pos' : 'neg'}>{usd(b.trading_pnl, 0)}</td><td>{b.winning_days} / {b.losing_days}</td><td>{b.payout_count}</td>
            <td>{usd(b.payouts_gross, 0)}</td><td className="pos">{usd(b.payouts_net, 0)}</td><td className="neg">{usd(b.costs, 0)}</td>
            <td className={b.real_profit >= 0 ? 'pos' : 'neg'}><b>{usd(b.real_profit, 0)}</b></td></tr>))}</tbody></table>
    </div>
  );
}

export default function ReportsWidget() {
  const [tab, setTab] = useState<Tab>('profit');
  const [account, setAccount] = useState(''); const [start, setStart] = useState(''); const [end, setEnd] = useState('');
  const [rep, setRep] = useState<Report | null>(null); const [rows, setRows] = useState<Row[]>([]); const [err, setErr] = useState('');
  const [cost, setCost] = useState({ kind: 'reset', amount: 0, note: '' });
  const q = useMemo(() => new URLSearchParams(Object.entries({ account, start, end }).filter(([, v]) => v)).toString(), [account, start, end]);

  const load = () => {
    setErr('');
    if (tab === 'profit') api<Report>(`/api/reports/profit?${new URLSearchParams(Object.entries({ start, end }).filter(([, v]) => v))}`).then(setRep).catch((e) => setErr(String(e)));
    else api<Row[]>(`/api/logs/${tab}?${q}&limit=3000`).then(setRows).catch((e) => setErr(String(e)));
  };
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [tab, q]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!rep) api<Report>('/api/reports/profit').then(setRep).catch(() => undefined); }, [rep]);
  const accounts = rep ? Object.keys(rep.live) : [];
  const addCost = async () => {
    if (!account || cost.amount <= 0) { setErr('Pick an account and an amount'); return; }
    await api('/api/logs/costs', { method: 'POST', body: JSON.stringify({ account, ...cost }) }); setCost({ ...cost, amount: 0, note: '' }); load();
  };
  const cols = rows[0] ? Object.keys(rows[0]) : [];
  const money = new Set(['balance', 'equity', 'mll', 'open_pnl', 'day_pnl', 'realized', 'gross', 'net_to_you', 'balance_after', 'start_balance', 'end_balance', 'pnl', 'amount']);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="row" style={{ padding: '6px 8px', borderBottom: '1px solid var(--line)', flexWrap: 'wrap', gap: 4 }}>
        {TABS.map(([k, l]) => <button key={k} className={tab === k ? 'primary' : 'ghost'} onClick={() => setTab(k)}>{l}</button>)}
        <div style={{ flex: 1 }} />
        {tab !== 'profit' && <select aria-label="Account" value={account} onChange={(e) => setAccount(e.target.value)}><option value="">All accounts</option>{accounts.map((a) => <option key={a}>{a}</option>)}</select>}
        <input type="date" aria-label="From" value={start} onChange={(e) => setStart(e.target.value)} />
        <input type="date" aria-label="To" value={end} onChange={(e) => setEnd(e.target.value)} />
        {tab !== 'profit' && <a href={`${API}/api/logs/${tab}/export.csv?${q}`} download><button>⤓ CSV</button></a>}
        {tab === 'profit' && <><a href={`${API}/api/logs/payouts/export.csv`} download><button>⤓ Payouts CSV</button></a><a href={`${API}/api/logs/daily_pnl/export.csv`} download><button>⤓ P&L CSV</button></a></>}
      </div>
      {err && <div className="neg" style={{ padding: '4px 10px' }}>{err}</div>}
      <div style={{ flex: 1, overflow: 'auto', padding: tab === 'profit' ? 10 : 0 }}>
        {tab === 'profit' && rep && (<>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
            {[['Trading P&L (sim)', rep.totals.trading_pnl ?? 0], ['Payouts gross', rep.totals.payouts_gross ?? 0], ['Net to you', rep.totals.payouts_net ?? 0], ['Costs (evals/resets/fees)', -(rep.totals.costs ?? 0)], ['Real profit', rep.totals.real_profit ?? 0]].map(([l, v]) => (
              <div key={String(l)} style={{ border: '1px solid var(--line)', borderRadius: 6, padding: '6px 10px' }}><p className="h">{l}</p>
                <div className={`mono ${Number(v) >= 0 ? 'pos' : 'neg'}`} style={{ fontSize: 17 }}>{usd(Number(v), 0)}</div></div>))}
          </div>
          <p className="h" style={{ margin: '10px 0 2px' }}>Fleet cumulative trading P&L</p>
          <Spark pts={rep.fleet_curve as unknown as Row[]} keys={['cumulative']} colors={['#6CF0C2']} />
          <BucketTable title="By month" data={rep.by_month} first="Month" />
          <BucketTable title="By firm" data={rep.by_firm} first="Firm" />
          <BucketTable title="By account" data={rep.by_account} first="Account" />
          <p className="h" style={{ margin: '8px 0 4px' }}>Live balances</p>
          <table><thead><tr><th>Account</th><th>Firm</th><th>Stage</th><th>Balance</th><th>Profit on account</th><th>Paid out (gross)</th><th>Received (net)</th><th>Status</th></tr></thead>
            <tbody>{Object.entries(rep.live).map(([k, a]) => <tr key={k}><td>{k}</td><td>{a.firm}</td><td className="mut">{a.stage}</td><td>{usd(a.balance)}</td>
              <td className={a.profit_on_account >= 0 ? 'pos' : 'neg'}>{usd(a.profit_on_account)}</td><td>{usd(a.paid_out)}</td><td className="pos">{usd(a.net_received)}</td><td className="mut">{a.status}</td></tr>)}</tbody></table>
        </>)}
        {tab === 'balances' && account && rows.length > 1 && <div style={{ padding: 10 }}><p className="h">{account}: balance vs MLL</p><Spark pts={[...rows].reverse()} keys={['balance', 'mll']} colors={['#6CF0C2', '#FF5D6C']} /></div>}
        {tab === 'balances' && !account && <div className="mut" style={{ padding: '6px 10px' }}>Pick an account to chart its balance and MLL.</div>}
        {tab === 'costs' && (
          <div className="row" style={{ padding: 8, flexWrap: 'wrap', borderBottom: '1px solid var(--line)' }}>
            <span className="mut">Add cost for {account || '(pick account)'}:</span>
            <select value={cost.kind} onChange={(e) => setCost({ ...cost, kind: e.target.value })} aria-label="Cost type">{['purchase', 'reset', 'activation', 'data_fee', 'platform', 'other'].map((k) => <option key={k}>{k}</option>)}</select>
            <input type="number" min={0} value={cost.amount || ''} placeholder="$" onChange={(e) => setCost({ ...cost, amount: +e.target.value })} style={{ width: 90 }} aria-label="Amount" />
            <input value={cost.note} placeholder="note" onChange={(e) => setCost({ ...cost, note: e.target.value })} aria-label="Note" />
            <button className="primary" onClick={addCost}>Add</button>
          </div>)}
        {tab !== 'profit' && (rows.length ? (
          <table><thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => {
              const v = r[c]; const n = typeof v === 'number' && money.has(c);
              return <td key={c} className={n && ['pnl', 'realized', 'day_pnl', 'open_pnl'].includes(c) ? (Number(v) >= 0 ? 'pos' : 'neg') : ''}
                style={c === 'data' || c === 'note' ? { whiteSpace: 'normal', maxWidth: 360 } : undefined}>{n ? usd(Number(v)) : String(v ?? '')}</td>;
            })}</tr>)}</tbody></table>) : <div className="empty">No {tab.replace('_', ' ')} recorded yet.</div>)}
      </div>
    </div>
  );
}
