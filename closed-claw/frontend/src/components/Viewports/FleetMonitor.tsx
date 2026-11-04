import { useEffect, useState } from 'react';
import { useFleetStore } from '../../stores/useFleetStore';
import Spark from './Spark';

const usd = (n: number) => (n < 0 ? '-' : '') + '$' + Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 });

export default function FleetMonitor() {
  const { accounts, mode, master, events, error, history, connect, simulateFill } = useFleetStore();
  const [qty, setQty] = useState(5);
  useEffect(() => connect(), [connect]);
  const totalDay = accounts.reduce((s, a) => s + (a.closed_balance - a.day_start_balance) + a.open_pnl, 0);
  return (
    <div className="grid">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div>
          <p className="h">LucidFlex 150K · 5-account MGC fleet</p>
          <div className="row">
            <span className={`pill ${mode.startsWith('LIVE') ? 'neg' : 'pos'}`}>{mode}</span>
            <span className="mut">master {master}</span>
            <span>Fleet day PnL <b className={totalDay >= 0 ? 'pos' : 'neg'}>{usd(totalDay)}</b></span>
          </div>
        </div>
        {!mode.startsWith('LIVE') && (
          <div className="row">
            <input type="number" min={1} max={100} value={qty} onChange={(e) => setQty(+e.target.value)} style={{ width: 64 }} aria-label="Qty" />
            <button onClick={() => simulateFill('Buy', qty)}>Paper Buy</button>
            <button onClick={() => simulateFill('Sell', qty)}>Paper Sell</button>
          </div>
        )}
      </div>
      {error && <div className="wire neg" style={{ padding: 10 }}>Backend offline at :5050 — {error}</div>}
      <div className="wire" style={{ overflowX: 'auto' }}>
        <table>
          <thead><tr><th>Account</th><th>Stage</th><th>Balance</th><th>Day PnL</th><th>Open</th><th>Pos</th><th>MLL</th><th>To MLL</th><th>Max MGC</th><th>Qual days</th><th>Payouts</th><th>Equity</th><th>Status</th></tr></thead>
          <tbody>
            {accounts.map((a) => {
              const day = a.closed_balance - a.day_start_balance;
              const status = a.liquidated ? <span className="neg">LIQUIDATED</span> : a.halted ? <span className="warn">HALTED · cashout</span> : a.payout.eligible ? <span className="pos">payout ✓</span> : <span className="mut">active</span>;
              return (
                <tr key={a.account_id}>
                  <td>{a.account_id === master ? '★ ' : ''}{a.account_id}</td>
                  <td>{a.stage}</td>
                  <td>{usd(a.closed_balance)}</td>
                  <td className={day >= 0 ? 'pos' : 'neg'}>{usd(day)}</td>
                  <td className={a.open_pnl >= 0 ? 'pos' : 'neg'}>{usd(a.open_pnl)}</td>
                  <td>{a.position_qty}</td>
                  <td>{usd(a.mll)}{a.mll_locked ? ' 🔒' : ''}</td>
                  <td className={a.distance_to_mll < 1000 ? 'neg' : a.distance_to_mll < 2000 ? 'warn' : ''}>{usd(a.distance_to_mll)}</td>
                  <td>{a.max_contracts}</td>
                  <td>{a.qualifying_days}/5</td>
                  <td>{a.payouts_approved}/5</td>
                  <td><Spark data={history[a.account_id] || []} w={90} h={22} /></td>
                  <td>{status}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="wire" style={{ padding: 12 }}>
        <p className="h">Event stream</p>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 11, maxHeight: 220, overflow: 'auto' }}>
          {events.length === 0 && <span className="mut">No events yet.</span>}
          {events.map((e, i) => (
            <div key={i} className={e.type === 'graduation_alert' || e.type === 'risk_clamp' ? 'warn' : ''}>
              <span className="mut">{String(e.ts ?? '').slice(11, 19)}</span> {e.type} {JSON.stringify({ ...e, ts: undefined, type: undefined })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
