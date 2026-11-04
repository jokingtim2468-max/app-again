import { useFleetStore, usd } from '../../stores/useFleetStore';

const STATUS_COLOR: Record<string, string> = { ACTIVE: 'var(--good)', KILLED: 'var(--bad)', LIQUIDATED: 'var(--bad)', ELIGIBLE_FOR_CASHOUT: 'var(--warn)', DAILY_LIMIT: 'var(--warn)' };

function Gauge({ distance, full }: { distance: number; full: number }) {
  const pct = Math.max(0, Math.min(1, distance / (full || 4500)));
  const color = pct < 0.25 ? 'var(--bad)' : pct < 0.5 ? 'var(--warn)' : 'var(--good)';
  return (
    <div title={`${usd(distance)} above MLL`} style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'flex-end' }}>
      <div style={{ width: 70, height: 6, background: '#212636', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct * 100}%`, height: '100%', background: color }} />
      </div>
      <span style={{ color, minWidth: 74, display: 'inline-block' }}>{usd(distance, 0)}</span>
    </div>
  );
}

export default function FleetWidget({ compact = false }: { compact?: boolean }) {
  const { accounts, master, online, kill, resume, events } = useFleetStore();
  if (!online && !accounts.length) return <div className="empty">Backend offline (127.0.0.1:5050)</div>;
  const alerts = events.filter((e) => ['graduation_alert', 'kill_switch', 'risk_clamp', 'bracket_exit', 'eod'].includes(e.type)).slice(0, 4);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <table>
          <thead><tr>
            <th>Account</th>{!compact && <th>Firm · platform</th>}{!compact && <th>Stage</th>}<th>Balance</th><th>Day PnL</th><th>Open</th><th>Pos</th>
            {!compact && <th>MLL</th>}<th>Cushion to MLL</th>{!compact && <th>Max MGC</th>}<th>Qual</th>{!compact && <th>Payouts</th>}<th>Status</th><th />
          </tr></thead>
          <tbody>
            {accounts.map((a) => {
              const day = a.closed_balance - a.day_start_balance;
              return (
                <tr key={a.account_id}>
                  <td>{a.account_id === master ? '★ ' : ''}{a.account_id}</td>
                  {!compact && <td title={`${a.drawdown_type} drawdown ${a.starting_drawdown}${a.daily_loss_limit ? ` · daily limit ${a.daily_loss_limit}` : ''}`}>{a.firm_name} {a.size} <span className="mut">· {a.broker}{a.contract !== 'MGC' ? ` · ${a.contract}` : ''}</span>{!a.verified && <span className="warn" title="Unverified rule template: live orders blocked"> ⚠</span>}</td>}
                  {!compact && <td className="mut">{a.stage === 'EVALUATION' ? 'EVAL' : 'FUNDED'}</td>}
                  <td>{usd(a.closed_balance)}</td>
                  <td className={day >= 0 ? 'pos' : 'neg'}>{usd(day)}</td>
                  <td className={a.open_pnl >= 0 ? 'pos' : 'neg'}>{usd(a.open_pnl)}</td>
                  <td>{a.position_qty || '—'}</td>
                  {!compact && <td>{usd(a.mll, 0)}{a.mll_locked ? ' 🔒' : ''}</td>}
                  <td><Gauge distance={a.distance_to_mll} full={a.starting_drawdown} /></td>
                  {!compact && <td>{a.max_contracts ?? '—'}</td>}
                  <td>{a.qualifying_days}/5</td>
                  {!compact && <td>{a.payouts_approved}/5</td>}
                  <td style={{ color: STATUS_COLOR[a.status] ?? 'var(--muted)' }}>{a.status.replace(/_/g, ' ')}</td>
                  <td>{a.status === 'KILLED'
                    ? <button className="ghost" onClick={() => resume(a.account_id)}>Resume</button>
                    : a.status === 'ACTIVE' && <button className="ghost" style={{ color: 'var(--bad)' }} title="Flatten + halt this account" onClick={() => kill(a.account_id)}>Kill</button>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!compact && alerts.length > 0 && (
        <div className="mono" style={{ borderTop: '1px solid var(--line)', padding: '6px 10px', fontSize: 11, maxHeight: 90, overflow: 'auto' }}>
          {alerts.map((e, i) => (
            <div key={i} className={e.type === 'graduation_alert' || e.type === 'kill_switch' ? 'warn' : 'mut'}>
              {String(e.ts ?? '').slice(11, 19)} {e.type === 'graduation_alert' ? String(e.operator_alert) : `${e.type} ${JSON.stringify({ ...e, ts: undefined, type: undefined })}`}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
