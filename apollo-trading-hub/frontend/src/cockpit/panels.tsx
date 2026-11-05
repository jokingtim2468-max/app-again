import { useEffect, useState } from 'react';
import { api } from '../api';
import { Account, useFleetStore } from '../stores/useFleetStore';
import { clock, fmt, money, REGIME_LABEL, Trade, useCockpit } from './store';
import { Bar, Confirm, Gauge, Panel, tone } from './ui';

export function useParams() {
  const [p, setP] = useState<{ values: Record<string, number | string | boolean>; defaults: Record<string, number | string | boolean>; limits: Record<string, [number, number]> } | null>(null);
  const load = () => api<typeof p>('/api/engine/params').then(setP).catch(() => undefined);
  useEffect(() => { load(); }, []);
  return { p, reload: load, setP };
}

// ---------------- Module 1: fleet ----------------
export function visibleAccounts(accounts: Account[], sel: string) { return sel ? accounts.filter((a) => a.account_id === sel) : accounts; }

export function FleetTotals() {
  const { accounts } = useFleetStore(); const sel = useCockpit((s) => s.account);
  const xs = visibleAccounts(accounts, sel);
  const bal = xs.reduce((s, a) => s + a.closed_balance, 0), eq = xs.reduce((s, a) => s + a.equity, 0);
  const net = xs.reduce((s, a) => s + (a.equity - (a as Account & { starting_balance: number }).starting_balance), 0);
  const day = xs.reduce((s, a) => s + a.day_pnl, 0);
  const k = (label: string, v: string, cls = '') => <div><div className="sub">{label}</div><div className={`kpi ${cls}`}>{v}</div></div>;
  return (
    <div className="panel" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
      {k(sel ? sel : `Fleet aggregate · ${xs.length} accounts`, money(bal, 0))}
      {k('Equity', money(eq, 0), 'live')}{k('Net PnL (since start)', money(net), tone(net))}{k('Today', money(day), tone(day))}
    </div>
  );
}

export function AccountCard({ a, dailyKill }: { a: Account; dailyKill: number }) {
  const start = (a as Account & { starting_balance: number }).starting_balance;
  const target = (a as Account & { eval_target?: number }).eval_target;
  const buffer = a.equity - a.mll, dd = a.starting_drawdown || 1, pct = (buffer / dd) * 100;
  const prog = target ? ((a.equity - start) / target) * 100 : null;
  const dayLimit = Math.min(dailyKill, a.daily_loss_limit ?? Infinity);
  const dayPct = (Math.max(0, -a.day_pnl) / dayLimit) * 100;
  const col = pct > 60 ? 'var(--good)' : pct > 30 ? 'var(--warn)' : 'var(--bad)';
  const st = a.liquidated ? ['BLOWN', 'bad'] : a.halted ? ['HALTED', 'bad'] : a.parked ? ['PARKED', 'warn'] : a.position_qty ? [`${a.position_qty > 0 ? 'LONG' : 'SHORT'} ${Math.abs(a.position_qty)}`, 'live'] : ['FLAT', 'mut'];
  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div><div style={{ fontWeight: 600 }} className="mono">{a.account_id}</div><div className="sub">{a.firm_name} · {a.plan} {a.size} · {a.stage}</div></div>
        <span className={`chip ${st[1]}`}>{st[0]}</span>
      </div>
      <div className="row" style={{ justifyContent: 'space-between', margin: '10px 0' }}>
        <div><div className="sub">Equity</div><div className="kpi">{money(a.equity)}</div></div>
        <div style={{ textAlign: 'right' }}><div className="sub">Open / Today</div><div className="mono"><span className={tone(a.open_pnl)}>{money(a.open_pnl)}</span> / <span className={tone(a.day_pnl)}>{money(a.day_pnl)}</span></div></div>
      </div>
      <div className="sub row" style={{ justifyContent: 'space-between' }}><span>Safe buffer · floor {money(a.mll, 0)} ({a.drawdown_type})</span><span className="mono" style={{ color: col }}>{money(buffer)} · {fmt(pct, 1)}%</span></div>
      <Bar pct={pct} color={col} />
      {prog != null && <><div className="sub row" style={{ justifyContent: 'space-between', marginTop: 8 }}><span>Target {money(start + (target ?? 0), 0)}</span><span className="mono">{fmt(Math.max(0, prog), 1)}%</span></div><Bar pct={prog} color="var(--good)" /></>}
      <div className="sub row" style={{ justifyContent: 'space-between', marginTop: 8 }}><span>Daily loss breaker {money(dayLimit, 0)}</span><span className="mono" style={{ color: dayPct > 70 ? 'var(--bad)' : undefined }}>{fmt(dayPct, 0)}%</span></div>
      <Bar pct={dayPct} color={dayPct > 70 ? 'var(--bad)' : 'var(--warn)'} />
    </div>
  );
}

export function FleetCards() {
  const { accounts } = useFleetStore(); const sel = useCockpit((s) => s.account); const { p } = useParams();
  const kill = Number(p?.values.daily_loss_kill ?? 600);
  const xs = visibleAccounts(accounts, sel);
  if (!xs.length) return <div className="panel sub">No accounts yet. Add them under Accounts.</div>;
  return <div className="grid g4">{xs.map((a) => <AccountCard key={a.account_id} a={a} dailyKill={kill} />)}</div>;
}

// ---------------- Module 2: market intelligence ----------------
export function RegimeBanner() {
  const i = useCockpit((s) => s.intel);
  if (!i) return null;
  const [lbl, cls] = REGIME_LABEL[i.regime.regime] ?? [i.regime.regime, 'mut'];
  const a = i.adaptive;
  return (
    <div className="panel row" style={{ flexWrap: 'wrap', gap: 14 }}>
      <span className={`chip ${cls}`} title={i.regime.regime}>{i.regime.regime}</span>
      <span className="sub">ATR(M15) <b className="mono">{fmt(i.regime.atr)}</b> · ×{fmt(i.regime.atr_ratio)} of normal · efficiency {fmt(i.regime.efficiency)}</span>
      <span className="row" style={{ marginLeft: 'auto', gap: 14, flexWrap: 'wrap' }}>
        <span className="sub">Adaptive TP <b className="mono pos">{fmt(a.tp)}</b></span>
        <span className="sub">SL cap <b className="mono neg">{fmt(a.sl_cap)}</b></span>
        <span className="sub">BE at <b className="mono warn">{fmt(a.be_trigger_r)}R</b></span>
        <span className="sub">Quota <b className="mono">{i.trades_today}/{a.quota}</b></span>
        <span className="chip mut">{lbl}</span>
      </span>
    </div>
  );
}

export function PricePill() {
  const q = useCockpit((s) => s.quote); const online = useCockpit((s) => s.online);
  if (!q) return <span className="chip bad">{online ? 'NO DATA' : 'ENGINE OFFLINE'}</span>;
  return (
    <span className="row mono" style={{ gap: 10, fontSize: 12 }}>
      <span className="chip live">{q.symbol} · {q.source}</span>
      <span>BID <b className="pos">{fmt(q.bid)}</b></span><span>ASK <b className="neg">{fmt(q.ask)}</b></span>
      <span>LAST <b style={{ color: 'var(--live)' }}>{fmt(q.last)}</b></span>
      <span className={`chip ${q.spread_wide ? 'warn' : 'mut'}`} title="Entries are blocked when the spread is wider than the max spread setting">SPR {fmt(q.spread)}</span>
    </span>
  );
}

const FACTOR_LABEL: Record<string, [string, number]> = {
  sweep: ['Liquidity sweep', 3.5], fvg: ['Fair value gap', 2], vwap: ['VWAP discount/premium', 1.5], volume: ['Volume surge ≥115%', 1.5], dxy: ['DXY tailwind', 1.5],
};
export function ConfluenceRadar({ min }: { min?: number }) {
  const i = useCockpit((s) => s.intel);
  if (!i) return <Panel title="Confluence radar"><div className="sub">Waiting for the engine…</div></Panel>;
  const c = i.confluence; const need = min ?? 6.8;
  const col = c.score >= need ? 'var(--good)' : c.score >= need - 1.5 ? 'var(--warn)' : 'var(--dim)';
  return (
    <Panel title="5-factor confluence" right={<span className={`chip ${c.score >= need ? 'good' : 'mut'}`}>GRADE {c.grade} · {c.side.toUpperCase()}</span>}>
      <div className="row" style={{ alignItems: 'flex-start', gap: 16 }}>
        <div style={{ width: 160 }}><Gauge value={c.score} max={10} label={`score · entry ≥ ${need}`} color={col} /></div>
        <div style={{ flex: 1 }}>
          {Object.entries(FACTOR_LABEL).map(([k, [lbl, w]]) => (
            <div key={k} className="row" style={{ justifyContent: 'space-between', padding: '3px 0', borderBottom: '1px solid var(--line)' }}>
              <span style={{ color: c.factors[k] ? 'var(--text)' : 'var(--dim)' }}>{c.factors[k] ? '●' : '○'} {lbl}{k === 'dxy' && !c.dxy_available ? ' (no DXY feed)' : ''}</span>
              <span className={`mono ${c.factors[k] ? 'pos' : 'mut'}`}>+{w}</span>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

export function MacroPanel() {
  const i = useCockpit((s) => s.intel);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  if (!i) return null;
  const n = i.news; const secs = n.next ? Math.round((new Date(n.next.time).getTime() - now) / 1000) : null;
  return (
    <Panel title="Macro & news circuit" right={<span className={`chip ${n.blackout ? 'bad' : 'good'}`}>{n.blackout ? 'ENTRIES LOCKED' : 'CLEAR'}</span>}>
      <div className="grid g2" style={{ gap: 10 }}>
        <div><div className="sub">DXY (dollar)</div><div className="mono">{i.dxy ? <>{fmt(i.dxy.last, 3)} <span className={i.dxy.trend === 'down' ? 'pos' : 'neg'}>{i.dxy.trend === 'down' ? '▼ gold tailwind' : '▲ gold headwind'}</span></> : <span className="mut">not available</span>}</div></div>
        <div><div className="sub">GVZ (gold volatility)</div><div className="mono">{i.gvz.available ? <>{fmt(i.gvz.value)} <span className={i.gvz.regime === 'HIGH_EXPANSION' ? 'warn' : 'mut'}>{i.gvz.regime}</span></> : <span className="mut">not available</span>}</div></div>
      </div>
      <div style={{ marginTop: 12 }}>
        <div className="sub">Next high-impact event{n.next?.estimated ? ' (estimated date)' : ''}</div>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <b>{n.next?.title ?? 'none scheduled'}</b>
          <span className={`kpi ${n.blackout ? 'neg' : ''}`} style={{ fontSize: 16 }}>{clock(secs)}</span>
        </div>
        <div className="sub">Lock window: {n.window.before_min} min before → {n.window.after_min} min after</div>
      </div>
      {i.macro_error && <div className="sub" style={{ marginTop: 8 }}>Gateway {i.engine.gateway_url}: {i.macro_error}</div>}
    </Panel>
  );
}

// ---------------- Module 3: engine controls ----------------
export function EngineControls() {
  const i = useCockpit((s) => s.intel); const refresh = useCockpit((s) => s.refresh);
  const mode = i?.engine.mode ?? 'MANUAL';
  const set = async (m: string) => { await api('/api/engine/mode', { method: 'POST', body: JSON.stringify({ mode: m }) }); refresh(); };
  return (
    <Panel title="Engine state" right={<span className={`chip ${i?.engine.live ? 'bad' : 'mut'}`}>{i?.engine.live ? 'LIVE' : 'PAPER'} · {i?.engine.broker_mode}</span>}>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <button className={mode === 'AUTONOMOUS' ? 'primary' : ''} onClick={() => set('AUTONOMOUS')}>● AUTONOMOUS EXECUTION</button>
        <button className={mode === 'MANUAL' ? 'primary' : ''} onClick={() => set('MANUAL')}>MANUAL OVERRIDE ONLY</button>
        <PanicButton />
      </div>
      <p className="sub" style={{ marginBottom: 0 }}>Autonomous takes entries when confluence, regime quota, cooldowns, spread and the news lock all allow it, checked on every M5 close. It always starts in Manual after a restart.</p>
    </Panel>
  );
}

export function PanicButton() {
  const refresh = useCockpit((s) => s.refresh);
  return <Confirm className="panic" confirmText="CONFIRM: FLATTEN ALL" onConfirm={async () => { await api('/api/engine/panic', { method: 'POST' }); refresh(); }}>PANIC / CLOSE ALL & FLATTEN</Confirm>;
}

const FIELDS: [string, string, number][] = [
  ['contracts', 'Contracts per trade (micros)', 1], ['base_tp', 'Base take profit (pts)', 0.05], ['sl_cap', 'Stop loss cap (pts)', 0.05],
  ['sl_min', 'Stop loss floor (pts)', 0.05], ['be_trigger_r', 'Breakeven trigger (R)', 0.05], ['be_lock', 'Breakeven lock cushion (pts)', 0.01],
  ['cooldown_after_trade_s', 'Cooldown after any trade (s)', 10], ['cooldown_after_loss_s', 'Cooldown after a loss, same side (s)', 10],
  ['confluence_min', 'Confluence entry threshold (/10)', 0.1], ['quota_range', 'Daily quota · range regime', 1],
  ['quota_balanced', 'Daily quota · balanced regime', 1], ['quota_expansion', 'Daily quota · expansion regime', 1],
  ['max_spread', 'Max spread for entries (pts)', 0.01], ['daily_loss_kill', 'Daily loss circuit breaker ($)', 10],
  ['news_before_min', 'News lock before (min)', 1], ['news_after_min', 'News lock after (min)', 1],
];
export function ParamsForm() {
  const { p, setP } = useParams();
  const [draft, setDraft] = useState<Record<string, number | string | boolean>>({}); const [msg, setMsg] = useState('');
  if (!p) return <Panel title="Live parameters"><div className="sub">Loading…</div></Panel>;
  const v = { ...p.values, ...draft };
  const save = async () => {
    try { setP(await api('/api/engine/params', { method: 'PUT', body: JSON.stringify({ values: draft }) })); setDraft({}); setMsg('Applied. The engine uses them from the next tick.'); }
    catch (e) { setMsg(String(e)); }
  };
  const lot = Number(v.contracts) * Number(v.point_value);
  return (
    <Panel title="Live parameters (hot reload)" right={<span className="row"><button className="ghost" onClick={() => { setDraft({ ...p.defaults }); setMsg('Defaults loaded; press Apply to use them.'); }}>Defaults</button><button className="primary" disabled={!Object.keys(draft).length} onClick={save}>Apply</button></span>}>
      <div className="form">
        {FIELDS.map(([k, lbl, step]) => {
          const [lo, hi] = p.limits[k] ?? [0, 100];
          return (
            <label key={k}>{lbl}
              <span className="row">
                {k === 'contracts' && <input type="range" min={lo} max={hi} step={1} value={Number(v[k])} onChange={(e) => setDraft({ ...draft, [k]: Number(e.target.value) })} style={{ flex: 1 }} />}
                <input type="number" min={lo} max={hi} step={step} value={Number(v[k])} onChange={(e) => setDraft({ ...draft, [k]: Number(e.target.value) })} style={{ width: k === 'contracts' ? 70 : '100%' }} className="mono" />
              </span>
            </label>
          );
        })}
        <label>Session filter
          <select value={String(v.session_filter)} onChange={(e) => setDraft({ ...draft, session_filter: e.target.value })}>
            <option value="all">All sessions (24h)</option><option value="london_ny">London + New York (03:00–16:00 ET)</option>
          </select>
        </label>
        <label>Counter-trend entries in expansion
          <select value={String(v.allow_counter_trend)} onChange={(e) => setDraft({ ...draft, allow_counter_trend: e.target.value === 'true' })}>
            <option value="true">Allowed</option><option value="false">Blocked</option>
          </select>
        </label>
      </div>
      <p className="sub" style={{ marginBottom: 0 }}>
        At {String(v.contracts)} micros: 1 point = {money(lot, 0)} · TP {money(Number(v.base_tp) * lot, 0)} · max risk {money(Number(v.sl_cap) * lot, 0)} · breakeven lock nets {money(Number(v.be_lock) * lot - Number(v.commission_rt) * Number(v.contracts))} after commission. {msg}
      </p>
    </Panel>
  );
}

// ---------------- Module 4: execution ----------------
export function QuickOrders() {
  const i = useCockpit((s) => s.intel); const refresh = useCockpit((s) => s.refresh);
  const [msg, setMsg] = useState('');
  const go = async (kind: string) => {
    try { await api('/api/exec/quick', { method: 'POST', body: JSON.stringify({ kind }) }); setMsg(''); }
    catch (e) { setMsg(String(e)); }
    refresh();
  };
  const be = async () => { const r = await api<{ moved: boolean; reason: string | null }>('/api/exec/breakeven_all', { method: 'POST' }); setMsg(r.moved ? 'Stops moved to breakeven.' : r.reason ?? ''); refresh(); };
  const t = i?.engine.open_trade;
  return (
    <Panel title="Quick-order terminal" right={<span className="sub">auto-bracket TP {fmt(i?.adaptive.tp)} / SL {fmt(i?.adaptive.sl)} pts</span>}>
      <div className="grid g2" style={{ gap: 8 }}>
        <button className="primary" style={{ padding: 12, fontWeight: 700 }} onClick={() => go('buy_market')}>BUY MARKET</button>
        <button className="danger" style={{ padding: 12, fontWeight: 700 }} onClick={() => go('sell_market')}>SELL MARKET</button>
        <button onClick={() => go('buy_limit_asian_low')} disabled={!i?.asian.asian_low}>BUY LIMIT @ ASIAN LOW {fmt(i?.asian.asian_low)}</button>
        <button onClick={() => go('sell_limit_asian_high')} disabled={!i?.asian.asian_high}>SELL LIMIT @ ASIAN HIGH {fmt(i?.asian.asian_high)}</button>
        <button className="span2" style={{ borderColor: '#78350F', color: '#FCD34D' }} onClick={be}>BREAKEVEN ALL</button>
      </div>
      {t && <div className="sub mono" style={{ marginTop: 10 }}>OPEN {t.side.toUpperCase()} {t.qty} @ {fmt(t.entry)} · SL {fmt(t.sl)}{t.be ? ' (BE)' : ''} · TP {fmt(t.tp)} · MFE {fmt(t.mfe)} pts</div>}
      {!!i?.engine.pending_limits.length && (
        <div style={{ marginTop: 8 }}>{i.engine.pending_limits.map((o) => (
          <div key={o.id} className="row sub mono"><span>{o.action.toUpperCase()} LIMIT {fmt(o.price)} ({o.label})</span>
            <button className="ghost" onClick={async () => { await api(`/api/exec/limits/${o.id}`, { method: 'DELETE' }); refresh(); }}>cancel</button></div>))}</div>
      )}
      {msg && <div className="sub" style={{ marginTop: 8, color: 'var(--warn)' }}>{msg}</div>}
    </Panel>
  );
}

interface CopyRow { account: string; role: string; copy_ratio: number; contract: string; firm: string; stage: string; status: string; position: number }
export function CopierMatrix() {
  const [rows, setRows] = useState<CopyRow[]>([]); const feed = useCockpit((s) => s.feed);
  const load = () => api<{ rows: CopyRow[] }>('/api/copier').then((d) => setRows(d.rows)).catch(() => undefined);
  useEffect(() => { load(); const t = setInterval(load, 2000); return () => clearInterval(t); }, []);
  const lastErr = (a: string) => feed.find((e) => (e.type === 'route_error' || e.type === 'risk_clamp') && e.account === a);
  return (
    <Panel title="Fleet copy-trader matrix">
      <table>
        <thead><tr><th>Account</th><th>Role</th><th>Firm / stage</th><th>Multiplier</th><th>Position</th><th>Status</th></tr></thead>
        <tbody>{rows.map((r) => {
          const err = lastErr(r.account);
          return (
            <tr key={r.account}>
              <td>{r.account}</td><td><span className={`chip ${r.role === 'master' ? 'live' : 'mut'}`}>{r.role.toUpperCase()}</span></td>
              <td>{r.firm} · {r.stage}</td>
              <td>{r.role === 'master' ? '1.00 (source)' : <input type="number" min={0} max={20} step={0.25} defaultValue={r.copy_ratio} style={{ width: 70 }} className="mono"
                onBlur={async (e) => { await api(`/api/copier/${r.account}`, { method: 'PUT', body: JSON.stringify({ copy_ratio: Number(e.target.value) }) }); load(); }} />}</td>
              <td className={tone(r.position)}>{r.position}</td>
              <td><span className={`chip ${err ? 'bad' : r.status === 'ACTIVE' ? 'good' : 'warn'}`} title={err ? String(err.error ?? err.reason ?? '') : ''}>{err ? (err.type === 'risk_clamp' ? 'CLAMPED' : 'ERROR') : r.status}</span></td>
            </tr>
          );
        })}</tbody>
      </table>
      <p className="sub" style={{ marginBottom: 0 }}>Every master fill is mirrored to followers at their multiplier, after each account's own firm-rule check. Change a multiplier and click away to save.</p>
    </Panel>
  );
}

// ---------------- Module 6: ledger ----------------
const FEED_COLOR: Record<string, string> = {
  entry: '', breakeven_step: '#F59E0B', tp_hit: '#34D399', sl_hit: '#FB7185', breakeven_exit: '#F59E0B', panic: '#F43F5E', kill_switch: '#F43F5E',
  daily_loss_breaker: '#F43F5E', route_error: '#FB7185', risk_clamp: '#F59E0B', params_updated: '#94A3B8', engine_mode: '#22D3EE', limit_placed: '#60A5FA',
};
function feedText(e: Record<string, unknown>) {
  const n = (k: string) => (e[k] == null ? '' : typeof e[k] === 'number' ? fmt(Number(e[k])) : String(e[k]));
  switch (e.type) {
    case 'entry': return `${String(e.side).toUpperCase()} ${n('qty')} @ ${n('price')} · TP ${n('tp')} / SL ${n('sl')} pts · ${n('source')}`;
    case 'breakeven_step': return `Breakeven step ${n('account')} · stop → ${n('sl')} (locks ${money(Number(e.lock_usd))})`;
    case 'tp_hit': return `TP hit ${n('side')} ${n('entry')} → ${n('exit')} · net ${money(Number(e.net))}`;
    case 'sl_hit': return `SL hit ${n('side')} ${n('entry')} → ${n('exit')} · net ${money(Number(e.net))}`;
    case 'breakeven_exit': return `Breakeven exit ${n('entry')} → ${n('exit')} · net ${money(Number(e.net))}`;
    case 'trade_closed': return `Closed (${n('reason')}) ${n('entry')} → ${n('exit')} · net ${money(Number(e.net))}`;
    case 'daily_loss_breaker': return `Daily loss breaker: ${n('account')} day ${money(Number(e.day_pnl))} — halted`;
    case 'engine_mode': return `Engine → ${n('mode')}`;
    case 'route_error': return `Route error ${n('account')}: ${n('error')}`;
    case 'limit_placed': return `${n('action')} limit placed @ ${n('price')} (${n('label')})`;
    default: return `${e.type} ${n('account')} ${n('reason')}`;
  }
}
export function LiveFeed({ max = 320 }: { max?: number }) {
  const feed = useCockpit((s) => s.feed);
  return (
    <Panel title="Live execution feed">
      <div className="feed" style={{ maxHeight: max }}>
        {!feed.length && <div className="sub">Entries, breakeven steps, TP/SL hits and risk events appear here as they happen.</div>}
        {feed.map((e, k) => {
          const col = e.type === 'entry' ? (String(e.side) === 'Buy' ? '#34D399' : '#FB7185') : FEED_COLOR[e.type] ?? 'var(--muted)';
          return <div key={k}><span className="mut">{e.ts ? String(e.ts).slice(11, 19) : ''}</span><span style={{ color: col }}>{feedText(e)}</span></div>;
        })}
      </div>
    </Panel>
  );
}

export function TradeForensics({ t, onClose }: { t: Trade; onClose: () => void }) {
  const row = (k: string, v: string, cls = '') => <tr><td>{k}</td><td className={cls}>{v}</td></tr>;
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Trade details">
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
          <b>{t.side.toUpperCase()} {t.qty} · {t.account}</b><button className="ghost" onClick={onClose}>Close</button>
        </div>
        <table><tbody>
          {row('Entry price', fmt(t.entry))}{row('Exit price', fmt(t.exit))}
          {row('Entry time', new Date(t.entry_time * 1000).toLocaleString())}{row('Hold duration', clock(Math.round(t.hold_s ?? 0)))}
          {row('Exit reason', t.reason ?? '—')}{row('Stop / target', `${fmt(t.sl)} / ${fmt(t.tp)}${t.be ? ' (breakeven armed)' : ''}`)}
          {row('MFE (best open profit)', money(t.mfe), 'pos')}{row('MAE (worst open loss)', money(-t.mae), 'neg')}
          {row('Gross PnL', money(t.gross), tone(t.gross ?? 0))}{row('Commission', money(-(t.commission ?? 0)))}
          {row('Net PnL', money(t.net), tone(t.net ?? 0))}
          {row('Signal', `${t.source ?? 'manual'}${t.score != null ? ` · score ${fmt(t.score, 1)}` : ''}${t.regime ? ` · ${t.regime}` : ''}`)}
        </tbody></table>
      </div>
    </div>
  );
}

export function TradesTable() {
  const [d, setD] = useState<{ trades: Trade[]; stats: { count: number; net: number; win_rate: number; profit_factor: number | null; commission: number } } | null>(null);
  const [sel, setSel] = useState<Trade | null>(null);
  useEffect(() => { const f = () => api<typeof d>('/api/trades?limit=300').then(setD).catch(() => undefined); f(); const t = setInterval(f, 3000); return () => clearInterval(t); }, []);
  return (
    <Panel title="Trade ledger" right={d && <span className="sub mono">{d.stats.count} trades · net <span className={tone(d.stats.net)}>{money(d.stats.net)}</span> · win {fmt(d.stats.win_rate * 100, 1)}% · PF {d.stats.profit_factor ?? '—'} · comm {money(d.stats.commission)}</span>}>
      <div style={{ maxHeight: 420, overflow: 'auto' }}>
        <table>
          <thead><tr><th>Time</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Exit</th><th>MFE</th><th>MAE</th><th>Net</th></tr></thead>
          <tbody>{d?.trades.map((t) => (
            <tr key={t.id} className="click" onClick={() => setSel(t)}>
              <td>{new Date(t.entry_time * 1000).toLocaleString()}</td><td className={t.side === 'long' ? 'pos' : 'neg'}>{t.side}</td><td>{t.qty}</td>
              <td>{fmt(t.entry)}</td><td>{fmt(t.exit)}</td><td>{t.reason}</td><td className="pos">{money(t.mfe, 0)}</td><td className="neg">{money(-t.mae, 0)}</td>
              <td className={tone(t.net ?? 0)}>{money(t.net)}</td>
            </tr>))}</tbody>
        </table>
        {!d?.trades.length && <div className="sub" style={{ padding: 10 }}>No closed trades yet. Click any trade for its full breakdown.</div>}
      </div>
      {sel && <TradeForensics t={sel} onClose={() => setSel(null)} />}
    </Panel>
  );
}
