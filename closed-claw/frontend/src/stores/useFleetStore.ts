import { create } from 'zustand';
import { api, onEvent } from '../api';

export interface Account {
  account_id: string; stage: 'EVALUATION' | 'FUNDED'; status: string; closed_balance: number; open_pnl: number;
  equity: number; mll: number; mll_locked: boolean; distance_to_mll: number; closed_profit: number;
  day_start_balance: number; qualifying_days: number; payouts_approved: number; position_qty: number; avg_price: number;
  max_contracts: number; halted: boolean; liquidated: boolean;
  payout: { eligible: boolean; max_request: number };
}
export interface FleetEvent { type: string; ts?: string; [k: string]: unknown }

interface FleetState {
  online: boolean; mode: string; master: string; symbol: string; last: number;
  accounts: Account[]; events: FleetEvent[]; lastError: string | null;
  start: () => () => void;
  refresh: () => Promise<void>;
  order: (action: 'Buy' | 'Sell', qty: number) => Promise<void>;
  kill: (account_id?: string) => Promise<void>;
  resume: (account_id: string) => Promise<void>;
}

let started = 0;
let timer: ReturnType<typeof setInterval> | undefined;
let unsub: (() => void) | undefined;

export const useFleetStore = create<FleetState>((set, get) => ({
  online: false, mode: '—', master: '', symbol: 'MGC', last: 0, accounts: [], events: [], lastError: null,
  refresh: async () => {
    try {
      const d = await api<{ mode: string; master: string; symbol: string; last: number; accounts: Record<string, Account> }>('/api/fleet/status');
      set({ online: true, mode: d.mode, master: d.master, symbol: d.symbol, last: d.last, accounts: Object.values(d.accounts) });
    } catch { set({ online: false }); }
  },
  start: () => {
    if (started++ === 0) {
      get().refresh();
      timer = setInterval(() => get().refresh(), 1500);
      unsub = onEvent((e) => {
        if (e.type === 'trade' || e.type === 'dom') return; // high-frequency; widgets subscribe directly
        set((s) => ({ events: [e as FleetEvent, ...s.events].slice(0, 150) }));
      });
    }
    return () => { if (--started === 0) { clearInterval(timer); unsub?.(); } };
  },
  order: async (action, qty) => {
    try { await api('/api/fleet/order', { method: 'POST', body: JSON.stringify({ action, qty }) }); set({ lastError: null }); }
    catch (e) { set({ lastError: String(e) }); }
    await get().refresh();
  },
  kill: async (account_id) => {
    await api('/api/fleet/kill', { method: 'POST', body: JSON.stringify({ account_id: account_id ?? null }) });
    await get().refresh();
  },
  resume: async (account_id) => {
    await api(`/api/fleet/${account_id}/resume`, { method: 'POST' });
    await get().refresh();
  },
}));

export const usd = (n: number, dp = 2) => (n < 0 ? '-' : '') + '$' + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
