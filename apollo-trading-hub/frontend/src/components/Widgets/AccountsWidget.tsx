import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api';
import { useFleetStore } from '../../stores/useFleetStore';

interface Firm { name: string; verified: boolean; note: string; platforms: string[]; contract: string; plans: Record<string, string[]> }
interface Acct { id: string; role: 'master' | 'copy'; firm: string; plan: string; size: string; broker: string; broker_account?: string; symbol?: string; copy_ratio?: number; login?: string; enabled?: boolean; stage?: string; cost?: number; purchased_at?: string }
interface FirmLimit { max_funded_accounts?: number | null; funded_outside_app?: number; park_buffer_usd?: number | null }
interface Fleet { name?: string; contract?: string; front_month_symbol?: string; accounts: Acct[]; firm_limits?: Record<string, FirmLimit>; [k: string]: unknown }
interface Brokers { available: Record<string, string>; mode: string; connectors: Record<string, { connected: boolean; error?: string }> }

export default function AccountsWidget() {
  const [firms, setFirms] = useState<Record<string, Firm>>({});
  const [brokers, setBrokers] = useState<Brokers | null>(null);
  const [cfg, setCfg] = useState<Fleet | null>(null);
  const [msg, setMsg] = useState(''); const [err, setErr] = useState(''); const [saving, setSaving] = useState(false);
  const refreshFleet = useFleetStore((s) => s.refresh);

  const load = () => Promise.all([api<Record<string, Firm>>('/api/firms').then(setFirms), api<Brokers>('/api/brokers').then(setBrokers),
    api<Fleet>('/api/fleet/config').then((c) => setCfg({ ...c, accounts: c.accounts ?? [] }))]).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  const accounts = cfg?.accounts ?? [];
  const update = (i: number, patch: Partial<Acct>) => {
    if (!cfg) return;
    let next = accounts.map((a, j) => (j === i ? { ...a, ...patch } : a));
    if (patch.role === 'master') next = next.map((a, j) => (j === i ? a : { ...a, role: 'copy' as const }));
    if (patch.firm) {
      const f = firms[patch.firm]; const plan = Object.keys(f.plans)[0];
      next[i] = { ...next[i], plan, size: f.plans[plan][0], broker: f.platforms[0] ?? 'paper', symbol: f.contract === 'XAUUSD' ? 'XAUUSD' : undefined, copy_ratio: f.contract === 'XAUUSD' ? 0.1 : 1 };
    }
    if (patch.plan) next[i] = { ...next[i], size: firms[next[i].firm].plans[patch.plan][0] };
    setCfg({ ...cfg, accounts: next }); setMsg('');
  };
  const add = () => cfg && setCfg({ ...cfg, accounts: [...accounts, { id: `ACCT_${accounts.length + 1}`, role: accounts.length ? 'copy' : 'master', firm: 'lucid', plan: 'FLEX', size: '150K', broker: 'tradovate', copy_ratio: 1, enabled: true }] });
  const remove = (i: number) => cfg && setCfg({ ...cfg, accounts: accounts.filter((_, j) => j !== i) });
  const save = async () => {
    if (!cfg) return;
    setSaving(true); setErr(''); setMsg('');
    try {
      const r = await api<{ accounts: string[]; mode: string }>('/api/fleet/config', { method: 'PUT', body: JSON.stringify(cfg) });
      setMsg(`Saved · ${r.accounts.length} accounts · ${r.mode}`); refreshFleet(); load();
    } catch (e) { setErr(String(e)); } finally { setSaving(false); }
  };
  const unverified = useMemo(() => [...new Set(accounts.filter((a) => firms[a.firm] && !firms[a.firm].verified).map((a) => firms[a.firm].name))], [accounts, firms]);
  if (!cfg) return <div className="empty">{err || 'Loading accounts…'}</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="row" style={{ padding: '6px 10px', borderBottom: '1px solid var(--line)', flexWrap: 'wrap' }}>
        <span className="mut">{accounts.length} accounts · {new Set(accounts.map((a) => a.firm)).size} firms · {new Set(accounts.map((a) => a.broker)).size} platforms</span>
        {brokers && <span className="pill" style={{ color: brokers.mode === 'PAPER' ? 'var(--accent)' : 'var(--warn)' }}><span className="dot" />{brokers.mode}</span>}
        <div style={{ flex: 1 }} />
        <button onClick={add}>+ Add account</button>
        <button className="primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save & apply'}</button>
      </div>
      {unverified.length > 0 && <div className="warn" style={{ padding: '6px 10px', fontSize: 11.5, borderBottom: '1px solid var(--line)' }}>
        ⚠ Unverified rule templates: {unverified.join(', ')}. Paper trading and backtests work; live orders stay blocked until you confirm the numbers in <span className="mono">backend/config/firms/</span> and set <span className="mono">verified: true</span>.</div>}
      {err && <div className="neg" style={{ padding: '6px 10px' }}>{err}</div>}
      {msg && <div className="pos" style={{ padding: '6px 10px' }}>{msg}</div>}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <table>
          <thead><tr><th>Account ID</th><th>Role</th><th>Firm</th><th>Plan</th><th>Size</th><th>Platform</th><th>Broker account</th><th>Symbol</th><th>Copy ×</th><th>Stage</th><th>Cost $</th><th>Bought</th><th>Login</th><th>On</th><th /></tr></thead>
          <tbody>{accounts.map((a, i) => {
            const f = firms[a.firm];
            const conn = brokers?.connectors[`${brokers.mode === 'PAPER' ? a.broker : a.broker}${a.login ?? ''}`];
            return (
              <tr key={i}>
                <td><input value={a.id} onChange={(e) => update(i, { id: e.target.value })} style={{ width: 140 }} aria-label="Account ID" /></td>
                <td><select value={a.role} onChange={(e) => update(i, { role: e.target.value as Acct['role'] })} aria-label="Role"><option value="master">★ master</option><option value="copy">copy</option></select></td>
                <td><select value={a.firm} onChange={(e) => update(i, { firm: e.target.value })} aria-label="Firm">{Object.entries(firms).map(([k, v]) => <option key={k} value={k}>{v.name}{v.verified ? '' : ' (unverified)'}</option>)}</select></td>
                <td><select value={a.plan} onChange={(e) => update(i, { plan: e.target.value })} aria-label="Plan">{f && Object.keys(f.plans).map((p) => <option key={p}>{p}</option>)}</select></td>
                <td><select value={a.size} onChange={(e) => update(i, { size: e.target.value })} aria-label="Size">{f?.plans[a.plan]?.map((s) => <option key={s}>{s}</option>)}</select></td>
                <td><select value={a.broker} onChange={(e) => update(i, { broker: e.target.value })} aria-label="Platform" title={brokers?.available[a.broker]}>
                  {brokers && Object.keys(brokers.available).map((b) => <option key={b} value={b}>{b}{f && !f.platforms.includes(b) && b !== 'paper' ? ' (not typical for firm)' : ''}</option>)}</select>
                  {conn?.error && <div className="neg" style={{ fontSize: 10.5, whiteSpace: 'normal', maxWidth: 180 }}>{conn.error}</div>}</td>
                <td><input value={a.broker_account ?? ''} placeholder={a.id} onChange={(e) => update(i, { broker_account: e.target.value || undefined })} style={{ width: 120 }} aria-label="Broker account" /></td>
                <td><input value={a.symbol ?? ''} placeholder={a.broker === 'ninjatrader' || a.broker === 'rithmic' ? 'MGC 12-26' : 'auto'} onChange={(e) => update(i, { symbol: e.target.value || undefined })} style={{ width: 90 }} aria-label="Symbol" /></td>
                <td><input type="number" step="0.01" min={0} value={a.copy_ratio ?? 1} disabled={a.role === 'master'} onChange={(e) => update(i, { copy_ratio: +e.target.value })} style={{ width: 60 }} aria-label="Copy ratio" /></td>
                <td><select value={a.stage ?? 'EVALUATION'} onChange={(e) => update(i, { stage: e.target.value })} aria-label="Stage"><option value="EVALUATION">eval</option><option value="FUNDED">funded</option></select></td>
                <td><input type="number" min={0} value={a.cost ?? 0} onChange={(e) => update(i, { cost: +e.target.value })} style={{ width: 70 }} aria-label="Cost" /></td>
                <td><input type="date" value={a.purchased_at ?? ''} onChange={(e) => update(i, { purchased_at: e.target.value || undefined })} style={{ width: 130 }} aria-label="Purchased" /></td>
                <td><input value={a.login ?? ''} placeholder="—" onChange={(e) => update(i, { login: e.target.value || undefined })} style={{ width: 44 }} aria-label="Login suffix" title="Env suffix for a 2nd login of the same platform, e.g. _2 -> TRADOVATE_USER_2" /></td>
                <td><input type="checkbox" checked={a.enabled !== false} onChange={(e) => update(i, { enabled: e.target.checked })} aria-label="Enabled" /></td>
                <td><button className="ghost" onClick={() => remove(i)} aria-label="Remove account">✕</button></td>
              </tr>);
          })}</tbody>
        </table>
      </div>
      <div style={{ padding: '6px 10px', borderTop: '1px solid var(--line)' }}>
        <p className="h" style={{ marginBottom: 4 }}>Firm caps (funded accounts allowed at once)</p>
        <div className="row" style={{ flexWrap: 'wrap', gap: 14 }}>
          {[...new Set(accounts.map((a) => a.firm))].map((fk) => {
            const lim = cfg.firm_limits?.[fk] ?? {};
            const setLim = (patch: FirmLimit) => setCfg({ ...cfg, firm_limits: { ...(cfg.firm_limits ?? {}), [fk]: { ...lim, ...patch } } });
            const funded = accounts.filter((a) => a.firm === fk && a.stage === 'FUNDED').length + (lim.funded_outside_app ?? 0);
            return (
              <div key={fk} className="row" style={{ border: '1px solid var(--line)', borderRadius: 6, padding: '4px 8px', fontSize: 11.5 }}>
                <b>{firms[fk]?.name ?? fk}</b>
                <label className="row mut">max funded <input type="number" min={0} placeholder="none" value={lim.max_funded_accounts ?? ''} onChange={(e) => setLim({ max_funded_accounts: e.target.value === '' ? undefined : +e.target.value })} style={{ width: 54 }} aria-label={`${fk} max funded`} /></label>
                <label className="row mut" title="Funded accounts you own at this firm that are NOT in this app; they still use up the cap">outside app <input type="number" min={0} value={lim.funded_outside_app ?? 0} onChange={(e) => setLim({ funded_outside_app: +e.target.value })} style={{ width: 46 }} aria-label={`${fk} outside`} /></label>
                <label className="row mut" title="Park evals this many $ before the profit target while the cap is full">park buffer $ <input type="number" min={0} placeholder="auto" value={lim.park_buffer_usd ?? ''} onChange={(e) => setLim({ park_buffer_usd: e.target.value === '' ? undefined : +e.target.value })} style={{ width: 60 }} aria-label={`${fk} park buffer`} /></label>
                <span className="mono mut">{funded} funded now</span>
              </div>);
          })}
        </div>
      </div>
      <div className="mut" style={{ padding: '6px 10px', borderTop: '1px solid var(--line)', fontSize: 11 }}>
        Platforms: {brokers && Object.entries(brokers.available).map(([k, v]) => <span key={k} title={v} style={{ marginRight: 10 }}><b className="mono">{k}</b></span>)} · credentials are read from env vars only, never stored here.
      </div>
    </div>
  );
}
