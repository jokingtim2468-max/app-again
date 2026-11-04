import { create } from 'zustand';
import { api, WS } from '../api';

export interface Account {
  account_id: string; stage: 'EVALUATION' | 'FUNDED'; closed_balance: number; open_pnl: number;
  equity: number; mll: number; mll_locked: boolean; distance_to_mll: number; closed_profit: number;
  day_start_balance: number; qualifying_days: number; payouts_approved: number; position_qty: number;
  max_contracts: number; halted: boolean; liquidated: boolean;
  payout: { eligible: boolean; max_request: number };
}
export interface FleetEvent { type: string; ts?: string; [k: string]: unknown }

interface FleetState {
  mode: string; master: string; accounts: Account[]; events: FleetEvent[]; error: string | null;
  history: Record<string, number[]>;
  refresh: () => Promise<void>;
  connect: () => () => void;
  simulateFill: (action: 'Buy' | 'Sell', qty: number) => Promise<void>;
}

export const useFleetStore = create<FleetState>((set, get) => ({
  mode: '—', master: '', accounts: [], events: [], error: null, history: {},
  refresh: async () => {
    try {
      const d = await api<{ mode: string; master: string; accounts: Record<string, Account> }>('/api/fleet/status');
      const accounts = Object.values(d.accounts);
      const history = { ...get().history };
      for (const a of accounts) history[a.account_id] = [...(history[a.account_id] || []), a.equity].slice(-120);
      set({ mode: d.mode, master: d.master, accounts, history, error: null });
    } catch (e) { set({ error: String(e) }); }
  },
  connect: () => {
    let ws: WebSocket | null = null; let alive = true;
    const open = () => {
      ws = new WebSocket(`${WS}/ws/events`);
      ws.onmessage = (m) => set((s) => ({ events: [JSON.parse(m.data), ...s.events].slice(0, 200) }));
      ws.onclose = () => { if (alive) setTimeout(open, 3000); };
    };
    open();
    const t = setInterval(() => get().refresh(), 2000);
    get().refresh();
    return () => { alive = false; clearInterval(t); ws?.close(); };
  },
  simulateFill: async (action, qty) => {
    await api('/api/fleet/simulate_fill', { method: 'POST', body: JSON.stringify({ action, qty }) });
    await get().refresh();
  },
}));
