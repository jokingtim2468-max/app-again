/* Demo mode (VITE_DEMO=1): the whole app runs in the browser on recorded sample data from a real Apollo backend
   run, with a simulated live MGC feed. Orders, kill switch, payouts and layouts work in memory. Nothing is sent anywhere. */
import fx from './fixtures.json';

type J = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const F = fx as unknown as J;
const API = 'http://127.0.0.1:5050';
const subs = new Set<FakeSocket>();
const status: J = F['/api/fleet/status'];
const payouts: J = F['/api/payouts'];
const settingsResp: J = F['/api/settings/bots'];
const layouts: J = F['/api/layouts'];
let last: number = status.last || 2611.5;
const TICK = 0.1;

// ---- shift recorded bars/tape so the last bar is "now" ----
const nowMin = Math.floor(Date.now() / 60000) * 60;
for (const tf of ['1m', '5m', '15m']) {
  const b = F[`/api/market/bars?tf=${tf}`].bars as J[];
  const step = tf === '1m' ? 60 : tf === '5m' ? 300 : 900;
  const shift = Math.floor(nowMin / step) * step - b[b.length - 1].time;
  for (const x of b) x.time += shift;
}
{ const b = F['/api/market/bars?tf=1m&limit=1440'].bars as J[]; const s = nowMin - b[b.length - 1].time; for (const x of b) x.time += s; }
last = F['/api/market/bars?tf=1m'].bars.slice(-1)[0].close;

function emit(e: J) { e.ts = e.ts ?? new Date().toISOString(); const s = JSON.stringify(e); subs.forEach((w) => w.url.includes('/ws/events') && w.onmessage?.({ data: s } as MessageEvent)); }
function accounts(): J[] { return Object.values(status.accounts); }
function pv(a: J) { return a.contract === 'XAUUSD' ? 100 : 10; }
function revalue() {
  status.last = last;
  for (const a of accounts()) {
    a.open_pnl = a.position_qty ? Math.round((last - a.avg_price) * pv(a) * a.position_qty * 100) / 100 : 0;
    a.equity = Math.round((a.closed_balance + a.open_pnl) * 100) / 100;
    a.distance_to_mll = Math.round((a.equity - a.mll) * 100) / 100;
    a.day_pnl = Math.round((a.equity - a.day_start_balance) * 100) / 100;
  }
}
function fill(a: J, action: string, qty: number) {
  const signed = action === 'Buy' ? qty : -qty;
  if (!a.position_qty || Math.sign(a.position_qty) === Math.sign(signed)) {
    const n = a.position_qty + signed; a.avg_price = (a.avg_price * Math.abs(a.position_qty) + last * qty) / Math.abs(n); a.position_qty = n;
  } else {
    const close = Math.min(qty, Math.abs(a.position_qty)); const dir = Math.sign(a.position_qty);
    a.closed_balance += (last - a.avg_price) * dir * close * pv(a); a.position_qty += signed;
    if (!a.position_qty) a.avg_price = 0;
  }
  emit({ type: 'order', mode: 'PAPER', account: a.account_id, action, qty, symbol: status.symbol, orderId: `demo-${Math.random().toString(36).slice(2, 8)}` });
}
const live = (a: J) => !a.liquidated && !a.halted && !a.parked && !['CLOSED', 'KILLED', 'DAILY_LIMIT'].includes(a.status);

// ---- simulated market ----
function book() {
  const bid = Math.round((last - TICK / 2) / TICK) * TICK; const sz = () => 3 + Math.floor(Math.random() * 57);
  return { bids: Array.from({ length: 10 }, (_, i) => [+(bid - i * TICK).toFixed(1), sz()]), asks: Array.from({ length: 10 }, (_, i) => [+(bid + (i + 1) * TICK).toFixed(1), sz()]) };
}
setInterval(() => {
  const n = 1 + Math.floor(Math.random() * 3);
  for (let i = 0; i < n; i++) {
    const step = [-1, 0, 0, 1][Math.floor(Math.random() * 4)] * TICK; last = +(last + step).toFixed(1);
    const size = [1, 1, 1, 2, 3, 5, 8, 12, 25][Math.floor(Math.random() * 9)];
    const t = { time: Date.now() / 1000, price: last, size, side: step >= 0 ? 'B' : 'S' };
    (F['/api/market/tape'] as J[]).unshift(t); (F['/api/market/tape'] as J[]).length = Math.min(300, (F['/api/market/tape'] as J[]).length);
    emit({ type: 'trade', ...t });
  }
  F['/api/market/dom'] = { ...F['/api/market/dom'], ...book(), last };
  emit({ type: 'dom', ...F['/api/market/dom'] });
  revalue();
}, 350);

// ---- request handlers ----
const ok = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { 'Content-Type': 'application/json' } });
async function handle(method: string, url: URL, body: J): Promise<Response> {
  const p = url.pathname; const q = url.searchParams;
  if (method === 'GET') {
    if (p === '/api/fleet/status') { revalue(); return ok(status); }
    if (p === '/api/market/bars') {
      const key = q.get('limit') === '1440' ? '/api/market/bars?tf=1m&limit=1440' : `/api/market/bars?tf=${q.get('tf') ?? '1m'}`;
      const d = F[key] ?? F['/api/market/bars?tf=1m'];
      return ok({ ...d, positions: accounts().filter((a) => a.position_qty).map((a) => ({ account: a.account_id, qty: a.position_qty, avg_price: a.avg_price })) });
    }
    if (p === '/api/market/tape') { const m = +(q.get('min_size') ?? 1); return ok((F['/api/market/tape'] as J[]).filter((t) => t.size >= m)); }
    if (p.startsWith('/api/logs/')) {
      const rows = (F[`/api/logs/${p.split('/')[3]}`] as J[] | undefined) ?? [];
      const acct = q.get('account');
      return ok(acct ? rows.filter((r) => r.account === acct) : rows);
    }
    if (p === '/api/settings/bots') return ok(settingsResp);
    if (p === '/api/settings/bots/channels') return ok([{ id: '111', name: 'general' }, { id: '222', name: 'blown-accounts' }, { id: '333', name: 'payouts' }, { id: '444', name: 'trade-log' }]);
    if (p === '/api/payouts') return ok(payouts);
    const hit = F[p] ?? F[p + url.search];
    return ok(hit ?? {});
  }
  // ---- writes (in memory) ----
  if (p === '/api/fleet/order') {
    const master = accounts().find((a) => a.account_id === status.master)!;
    if (!live(master)) return ok({ detail: 'master account is halted (demo)' }, 409);
    for (const a of accounts().filter(live)) fill(a, body.action, a.contract === 'MGC' ? Math.round(body.qty * (a.copy_ratio || 1)) : body.qty * 0.1);
    revalue(); return ok({ master: { mode: 'PAPER' }, copies: [] });
  }
  if (p === '/api/fleet/flatten' || p === '/api/fleet/kill') {
    const ids = p.endsWith('kill') && body.account_id ? [body.account_id] : accounts().map((a) => a.account_id);
    for (const id of ids) { const a = status.accounts[id]; if (a.position_qty) fill(a, a.position_qty > 0 ? 'Sell' : 'Buy', Math.abs(a.position_qty)); if (p.endsWith('kill') && a.status === 'ACTIVE') { a.status = 'KILLED'; a.halted = true; } }
    if (p.endsWith('kill')) emit({ type: 'kill_switch', accounts: ids, flattened: ids.length });
    revalue(); return ok({ halted: ids, flatten_orders: [] });
  }
  const mResume = p.match(/^\/api\/fleet\/(.+)\/resume$/);
  if (mResume) { const a = status.accounts[mResume[1]]; if (a?.status === 'KILLED') { a.status = 'ACTIVE'; a.halted = false; } return ok({ resumed: true, status: a?.status }); }
  if (p === '/api/backtest') {
    const r = structuredClone(F.backtests[body.script_path ? 'example_sma_pandas' : body.strategy_name] ?? F.backtests.news_momentum);
    if (body.spread_multiplier && body.spread_multiplier !== 1) r.total_net_pnl = F.stress[String(body.spread_multiplier)] ?? r.total_net_pnl;
    if (body.script_path) r.adapter = { ...(r.adapter ?? {}), source_path: body.script_path, report: [`Demo: ran the sample pandas strategy in place of ${body.script_path}`] };
    await new Promise((res) => setTimeout(res, 600)); return ok(r);
  }
  if (p === '/api/strategies/inspect') return ok({ name: body.script, style: 'vectorized', entrypoint: 'generate_signals', source_path: body.script, report: ['Demo: in the real app this shows how your script was detected and adapted'] });
  const mPay = p.match(/^\/api\/payouts\/(.+)\/(requested|paid|rejected)$/);
  if (mPay) {
    const row = (payouts.accounts as J[]).find((r) => r.account_id === mPay[1]);
    if (row) {
      if (mPay[2] === 'requested') { row.pending = body.amount ?? row.max_request; row.eligible = false; row.blockers = ['payout requested; mark it paid or rejected']; }
      if (mPay[2] === 'paid') { const amt = row.pending || row.max_request; row.paid_out += amt; payouts.totals.paid_out += amt; row.pending = 0; row.eligible = false; row.payout_number += 1; row.blockers = ['new cycle: 5 more qualifying days needed']; emit({ type: 'lifecycle', kind: 'PAYOUT', account: row.account_id, amount: amt }); }
      if (mPay[2] === 'rejected') { row.pending = 0; row.blockers = ['rejected; fix the issue and request again']; }
    }
    return ok({ ok: true, pending: row?.pending ?? 0, payout_number: row?.payout_number ?? 1, amount: body.amount ?? 0 });
  }
  if (p === '/api/layouts') { layouts.layouts[body.name] = { widgets: body.widgets, updated_at: new Date().toISOString(), source: 'ui' }; if (body.activate) layouts.active = body.name; return ok({ name: body.name, widgets: body.widgets }); }
  if (p.startsWith('/api/layouts/')) return ok({ ok: true });
  if (p === '/api/settings/bots/code') {
    const code = Array.from({ length: 6 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');
    setTimeout(() => { // simulate someone typing /verify CODE in a Discord server
      settingsResp.links.push({ id: `discord:demo${code}`, platform: 'discord', chat_id: '555', guild_id: `demo${code}`, title: 'Demo server (simulated /verify)', linked_by: 'demo', linked_by_name: 'you', linked_at: new Date().toISOString().slice(0, 19), destinations: { '555': { name: 'general', kinds: [...settingsResp.notify_kinds] } } });
    }, 6000);
    return ok({ code, expires_in: 600, control: !!body.grant_control });
  }
  if (p === '/api/settings/bots/test') return ok(body.command ? { preview: `Demo preview of /${body.command}: in the real app this runs against your live fleet.` } : { sent: ['discord:111', 'telegram:-100'] });
  if (p === '/api/settings/bots' && method === 'PUT') { Object.assign(settingsResp.settings, body); return ok(settingsResp); }
  return ok({ ok: true });
}

// ---- fake WebSocket ----
class FakeSocket {
  url: string; readyState = 0; binaryType = 'blob';
  onopen: ((e: Event) => void) | null = null; onmessage: ((e: MessageEvent) => void) | null = null; onclose: ((e: CloseEvent) => void) | null = null; onerror: ((e: Event) => void) | null = null;
  constructor(url: string) { this.url = url; subs.add(this); setTimeout(() => { this.readyState = 1; this.onopen?.(new Event('open')); }, 30); }
  send(data: unknown) {
    if (this.url.includes('/ws/containers/')) { const t = typeof data === 'string' ? data : new TextDecoder().decode(data as ArrayBuffer); this.onmessage?.({ data: t === '\r' ? '\r\n$ ' : t } as MessageEvent); }
  }
  close() { this.readyState = 3; subs.delete(this); }
  addEventListener() { /* not used */ }
}

export function installDemo() {
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
    if (!url.href.startsWith(API)) return realFetch(input as RequestInfo, init);
    let body: J = {};
    try { body = init?.body ? JSON.parse(String(init.body)) : {}; } catch { /* non-json */ }
    return handle((init?.method ?? 'GET').toUpperCase(), url, body);
  };
  (window as unknown as { WebSocket: unknown }).WebSocket = FakeSocket;
  window.confirm = () => true; // the artifact viewer blocks dialogs; demo actions are harmless
  const tag = document.createElement('div');
  tag.textContent = 'DEMO · sample data · simulated market';
  Object.assign(tag.style, { position: 'fixed', left: '64px', bottom: '8px', zIndex: '150', fontSize: '11px', padding: '3px 9px', borderRadius: '999px',
    border: '1px solid #F5C451', color: '#F5C451', background: '#12151E', letterSpacing: '.06em', pointerEvents: 'none' });
  document.addEventListener('DOMContentLoaded', () => document.body.appendChild(tag));
  if (document.readyState !== 'loading') document.body.appendChild(tag);
}
