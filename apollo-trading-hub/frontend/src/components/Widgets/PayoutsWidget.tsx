import { useEffect, useState } from 'react';
import { api, onEvent } from '../../api';
import { usd } from '../../stores/useFleetStore';

interface Monthly { known: boolean; payouts_per_month?: number; gross_ceiling?: number | null; net_ceiling?: number | null; uncapped?: boolean; lifetime_gross_cap?: number | null; payouts_left?: number | null; profit_needed_note?: string }
interface Row {
  account_id: string; firm: string; path: string | null; eligible: boolean; max_request: number; net_to_you: number; blockers: string[];
  payout_number: number; dashboard_url: string | null; pending: number; verified: boolean | null; qualifying_days?: string; cycle_profit?: number;
  stage: string; status: string; balance: number; paid_out: number; monthly: Monthly; note?: string;
}
interface Data { accounts: Row[]; firms: Record<string, { firm_name: string; ready_now_net: number; month_ceiling_net: number; uncapped_accounts: number; paid_out: number }>; totals: Record<string, number> }

interface Outcome {
  accounts: number; evals_bought: number; evals_passed: number; evals_hit_target: number; evals_blown: number; pass_rate: number | null;
  funded_accounts: number; funded_blown: number; funded_blow_rate: number | null; total_blown: number; daily_limit_hits: number;
  accounts_hit_daily_limit: number; ever_parked: number; maxed_out: number; graduated: number; closed: number; payouts: number;
  accounts_paid: number; avg_payouts_per_funded: number | null; payouts_net: number; costs: number; real_profit: number;
  return_per_dollar: number | null; cost_per_funded: number | null; avg_days_to_pass: number | null;
}
interface Outcomes { fleet: Outcome; by_firm: Record<string, Outcome>; now: Record<string, { evals_trading: number; funded_active: number; parked_now: number; blown_now: number }> }
const pct = (v: number | null) => (v == null ? '—' : `${Math.round(v * 100)}%`);

function OutcomeStats({ o, firmNames }: { o: Outcomes; firmNames: Record<string, string> }) {
  const f = o.fleet;
  const tiles: [string, string, string, string][] = [
    ['Evals passed', `${f.evals_passed}`, 'pos', `pass rate ${pct(f.pass_rate)}`],
    ['Hit profit target', `${f.evals_hit_target}`, 'pos', `${f.ever_parked} parked at cap`],
    ['Accounts blown', `${f.total_blown}`, f.total_blown ? 'neg' : '', `${f.evals_blown} eval · ${f.funded_blown} funded`],
    ['Daily loss limit hits', `${f.daily_limit_hits}`, f.daily_limit_hits ? 'warn' : '', `${f.accounts_hit_daily_limit} account(s)`],
    ['Payouts received', `${f.payouts}`, 'pos', `${f.accounts_paid} accounts · avg ${f.avg_payouts_per_funded ?? '—'}/funded`],
    ['Maxed out / graduated', `${f.maxed_out + f.graduated}`, '', `${f.closed} closed`],
    ['Return per $1 spent', f.return_per_dollar == null ? '—' : `$${f.return_per_dollar.toFixed(2)}`, (f.return_per_dollar ?? 0) >= 1 ? 'pos' : 'neg', `cost per funded ${f.cost_per_funded == null ? '—' : usd(f.cost_per_funded, 0)}`],
    ['Avg days to pass', f.avg_days_to_pass == null ? '—' : `${f.avg_days_to_pass}`, '', `real profit ${usd(f.real_profit, 0)}`],
  ];
  return (
    <div style={{ padding: 8, borderBottom: '1px solid var(--line)' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 6 }}>
        {tiles.map(([l, v, c, sub]) => (
          <div key={l} style={{ border: '1px solid var(--line)', borderRadius: 6, padding: '5px 9px' }}>
            <p className="h">{l}</p><div className={`mono ${c}`} style={{ fontSize: 17 }}>{v}</div>
            <div className="mut" style={{ fontSize: 10.5 }}>{sub}</div>
          </div>))}
      </div>
      {Object.keys(o.by_firm).length > 0 && (
        <table style={{ marginTop: 6 }}>
          <thead><tr><th>Firm</th><th>Evals bought</th><th>Hit target</th><th>Passed</th><th>Pass rate</th><th>Evals blown</th><th>Funded</th><th>Funded blown</th><th>Daily-limit hits</th><th>Parked</th><th>Payouts</th><th>Net received</th><th>Costs</th><th>Real profit</th><th>Now: trading / funded / parked / blown</th></tr></thead>
          <tbody>{Object.entries(o.by_firm).map(([k, x]) => { const n = o.now[k]; return (
            <tr key={k}><td>{firmNames[k] ?? k}</td><td>{x.evals_bought}</td><td className="pos">{x.evals_hit_target}</td><td className="pos">{x.evals_passed}</td><td>{pct(x.pass_rate)}</td>
              <td className={x.evals_blown ? 'neg' : ''}>{x.evals_blown}</td><td>{x.funded_accounts}</td><td className={x.funded_blown ? 'neg' : ''}>{x.funded_blown} <span className="mut">({pct(x.funded_blow_rate)})</span></td>
              <td className={x.daily_limit_hits ? 'warn' : ''}>{x.daily_limit_hits}</td><td>{x.ever_parked}</td><td>{x.payouts}</td><td className="pos">{usd(x.payouts_net, 0)}</td>
              <td className="neg">{usd(x.costs, 0)}</td><td className={x.real_profit >= 0 ? 'pos' : 'neg'}><b>{usd(x.real_profit, 0)}</b></td>
              <td className="mono mut">{n ? `${n.evals_trading} / ${n.funded_active} / ${n.parked_now} / ${n.blown_now}` : '—'}</td></tr>); })}</tbody>
        </table>)}
    </div>
  );
}

export default function PayoutsWidget() {
  const [oc, setOc] = useState<Outcomes | null>(null);
  const [showOc, setShowOc] = useState(true);
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState(''); const [msg, setMsg] = useState('');
  const [notifyOn, setNotifyOn] = useState(typeof Notification !== 'undefined' && Notification.permission === 'granted');
  const load = () => {
    api<Outcomes>('/api/reports/outcomes').then(setOc).catch(() => undefined);
    return api<Data>('/api/payouts').then((x) => { setD(x); setErr(''); }).catch((e) => setErr(String(e)));
  };
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);
  useEffect(() => onEvent((e) => {
    if (e.type !== 'payout_ready') return;
    load();
    if (notifyOn) new Notification('Apollo: payout ready', { body: `${e.account_id} (${e.firm}) → request ${usd(Number(e.max_request), 0)}` });
  }), [notifyOn]);

  const act = async (id: string, what: 'requested' | 'paid' | 'rejected', amount?: number) => {
    try { await api(`/api/payouts/${id}/${what}`, { method: 'POST', body: JSON.stringify({ amount: amount ?? null }) }); setMsg(`${id}: marked ${what}`); load(); }
    catch (e) { setErr(String(e)); }
  };
  const open = async (r: Row) => {
    try { await navigator.clipboard.writeText(String(r.max_request)); setMsg(`Copied ${usd(r.max_request, 0)} for ${r.account_id}; paste it in the firm's payout form, then click "Requested".`); } catch { /* clipboard blocked */ }
    if (r.dashboard_url) window.open(r.dashboard_url, '_blank', 'noopener');
  };
  if (!d) return <div className="empty">{err || 'Loading payouts…'}</div>;
  const funded = d.accounts.filter((r) => r.stage === 'FUNDED' && r.status !== 'CLOSED' && r.status !== 'LIQUIDATED');
  const ready = funded.filter((r) => r.eligible);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="row" style={{ padding: 8, gap: 8, borderBottom: '1px solid var(--line)', flexWrap: 'wrap' }}>
        {[['Ready now (to you)', usd(d.totals.ready_now_net, 0), ready.length ? 'pos' : ''], ['Month ceiling (to you)', usd(d.totals.month_ceiling_net, 0), ''],
          ['Paid out so far', usd(d.totals.paid_out, 0), ''], ['Funded accounts', String(funded.length), '']].map(([l, v, c]) => (
          <div key={l} style={{ border: '1px solid var(--line)', borderRadius: 6, padding: '6px 10px', minWidth: 150 }}>
            <p className="h">{l}</p><div className={`mono ${c}`} style={{ fontSize: 16 }}>{v}</div></div>))}
        <div style={{ flex: 1 }} />
        {typeof Notification !== 'undefined' && !notifyOn && <button onClick={() => Notification.requestPermission().then((p) => setNotifyOn(p === 'granted'))}>🔔 Enable payout alerts</button>}
        {notifyOn && <span className="pill pos"><span className="dot" />alerts on</span>}
      </div>
      <div className="row" style={{ padding: '2px 8px', borderBottom: '1px solid var(--line)' }}>
        <button className="ghost" onClick={() => setShowOc((v) => !v)}>{showOc ? '▾' : '▸'} Account outcomes (all time)</button>
      </div>
      {showOc && oc && <OutcomeStats o={oc} firmNames={Object.fromEntries(Object.entries(d.firms).map(([k, v]) => [k, v.firm_name]))} />}
      {msg && <div className="pos" style={{ padding: '4px 10px', fontSize: 11.5 }}>{msg}</div>}
      {err && <div className="neg" style={{ padding: '4px 10px' }}>{err}</div>}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <table>
          <thead><tr><th>Account</th><th>Firm · path</th><th>Payout #</th><th>Cycle</th><th>Request now</th><th>To you</th><th>Month ceiling</th><th>Lifetime cap</th><th>Status</th><th /></tr></thead>
          <tbody>{funded.map((r) => (
            <tr key={r.account_id} style={{ background: r.eligible ? 'rgba(61,220,151,.06)' : undefined }}>
              <td>{r.account_id}</td>
              <td>{r.firm} <span className="mut">· {r.path ?? '—'}</span>{r.verified === false && <span className="warn" title="Payout policy not fully confirmed from the firm's site"> ⚠</span>}</td>
              <td>{r.payout_number}{r.monthly.payouts_left != null ? <span className="mut"> ({r.monthly.payouts_left} left)</span> : ''}</td>
              <td className="mut">{r.qualifying_days ?? ''} {r.cycle_profit != null ? `· ${usd(r.cycle_profit, 0)}` : ''}</td>
              <td className={r.eligible ? 'pos' : 'mut'}>{r.max_request ? usd(r.max_request, 0) : '—'}</td>
              <td className={r.eligible ? 'pos' : 'mut'}>{r.net_to_you ? usd(r.net_to_you, 0) : '—'}</td>
              <td title={r.monthly.profit_needed_note}>{!r.monthly.known ? '—' : r.monthly.uncapped ? <span className="mut">uncapped · profit-limited</span> : `${usd(r.monthly.net_ceiling ?? 0, 0)} (${r.monthly.payouts_per_month}×)`}</td>
              <td className="mut">{r.monthly.lifetime_gross_cap ? usd(r.monthly.lifetime_gross_cap, 0) : '—'}</td>
              <td style={{ whiteSpace: 'normal', maxWidth: 260, fontSize: 11 }}>
                {r.pending ? <span className="warn">requested {usd(r.pending, 0)} · awaiting firm</span> : r.eligible ? <span className="pos">ELIGIBLE</span> : <span className="mut">{r.blockers[0]}</span>}
              </td>
              <td><div className="row" style={{ justifyContent: 'flex-end' }}>
                {r.eligible && <button className="primary" onClick={() => open(r)} title="Copies the amount and opens the firm's payout page">Open payout page ↗</button>}
                {r.eligible && <button onClick={() => act(r.account_id, 'requested', r.max_request)}>Requested</button>}
                {r.pending > 0 && <><button className="primary" onClick={() => act(r.account_id, 'paid')}>Paid ✓</button><button className="ghost" onClick={() => act(r.account_id, 'rejected')}>Rejected</button></>}
              </div></td>
            </tr>))}</tbody>
        </table>
        {!funded.length && <div className="empty">No funded accounts yet. Payouts appear here once accounts pass.</div>}
      </div>
      <div className="mut" style={{ padding: '6px 10px', borderTop: '1px solid var(--line)', fontSize: 11 }}>
        Semi-auto: Apollo checks eligibility every minute, alerts you (here + phone via APOLLO_NOTIFY_WEBHOOK), copies the exact amount and opens the firm page. You submit, then mark it requested → paid. Ceilings assume profit always covers the caps; real withdrawals are limited by what you earn.
      </div>
    </div>
  );
}
