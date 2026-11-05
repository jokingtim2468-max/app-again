import { create } from 'zustand';
import { api, onEvent } from '../api';

export interface Quote { symbol: string; source: string; bid: number; ask: number; last: number; mid: number; spread: number; spread_wide: boolean }
export interface Regime { regime: string; atr: number; atr_ratio: number; efficiency: number; trend?: string }
export interface Adaptive { tp: number; sl: number; sl_cap: number; be_trigger_r: number; be_lock: number; quota: number }
export interface Gap { side: 'bull' | 'bear'; low: number; high: number; time: number }
export interface Confluence {
  side: 'long' | 'short'; score: number; grade: string; max: number; factors: Record<string, boolean>;
  sweep: { side?: string; level?: number; time?: number; asian?: boolean }; fvgs: Gap[]; dxy_available: boolean;
}
export interface NewsEvent { time: string; title: string; impact: string; estimated?: boolean }
export interface Trade {
  id: string; account: string; side: 'long' | 'short'; qty: number; entry: number; exit?: number; entry_time: number; exit_time?: number;
  sl?: number; tp?: number; mfe: number; mae: number; gross?: number; commission?: number; net?: number; hold_s?: number;
  reason?: string; be?: boolean; score?: number | null; regime?: string | null; source?: string;
}
export interface Limit { id: string; action: 'Buy' | 'Sell'; price: number; label: string }
export interface EngineState {
  mode: 'AUTONOMOUS' | 'MANUAL'; live: boolean; broker_mode: string; open_trade: Trade | null; pending_limits: Limit[];
  last_signal: Record<string, unknown>; cooldown_until: number; gateway_url: string;
}
export interface Intel {
  quote: Quote; regime: Regime; adaptive: Adaptive; asian: { asian_high?: number; asian_low?: number; active?: boolean };
  vwap: number | null; confluence: Confluence; dxy: { last: number; trend: string } | null;
  gvz: { available: boolean; value?: number; regime?: string }; macro_error: string | null;
  news: { next: NewsEvent | null; seconds_to_next: number | null; blackout: boolean; events: NewsEvent[]; window: { before_min: number; after_min: number }; custom_calendar: boolean };
  trades_today: number; engine: EngineState;
}
export interface FeedItem { type: string; ts?: string; [k: string]: unknown }

interface S {
  intel: Intel | null; online: boolean; quote: Quote | null; feed: FeedItem[]; account: string; // '' = fleet aggregate
  setAccount: (a: string) => void;
  start: () => () => void;
  refresh: () => Promise<void>;
}

const LOUD = new Set(['entry', 'breakeven_step', 'tp_hit', 'sl_hit', 'breakeven_exit', 'trade_closed', 'trade_open', 'limit_placed', 'panic',
  'kill_switch', 'daily_loss_breaker', 'engine_mode', 'params_updated', 'route_error', 'risk_clamp', 'bracket_exit', 'PASSED', 'FAILED',
  'TARGET_HIT', 'DAILY_LIMIT_HIT', 'payout_ready']);
let n = 0; let timer: ReturnType<typeof setInterval> | undefined; let unsub: (() => void) | undefined;

export const useCockpit = create<S>((set, get) => ({
  intel: null, online: false, quote: null, feed: [], account: '',
  setAccount: (account) => set({ account }),
  refresh: async () => {
    try { const intel = await api<Intel>('/api/market/intel'); set({ intel, online: true, quote: { ...intel.quote, ...(get().quote ? { last: get().quote!.last } : {}) } }); }
    catch { set({ online: false }); }
  },
  start: () => {
    if (n++ === 0) {
      get().refresh();
      timer = setInterval(() => get().refresh(), 1000);
      unsub = onEvent((e) => {
        if (e.type === 'trade') {  // tick: update the price pill without waiting for the next poll
          const q = get().quote; const p = Number(e.price);
          if (q && p) set({ quote: { ...q, last: p } });
          return;
        }
        if (LOUD.has(String(e.type)) || String(e.type).toUpperCase() === e.type) set((s) => ({ feed: [e as FeedItem, ...s.feed].slice(0, 300) }));
      });
    }
    return () => { if (--n === 0) { clearInterval(timer); unsub?.(); } };
  },
}));

export const REGIME_LABEL: Record<string, [string, string]> = {
  CONSOLIDATION_RANGE_REGIME: ['RANGE', 'warn'], BALANCED_INTRADAY_REGIME: ['BALANCED', 'live'], TREND_EXPANSION_REGIME: ['TREND EXPANSION', 'good'],
};
export const fmt = (v: number | null | undefined, dp = 2) => (v == null || Number.isNaN(v) ? '—' : v.toFixed(dp));
export const money = (v: number | null | undefined, dp = 2) => (v == null ? '—' : (v < 0 ? '-$' : '$') + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp }));
export const clock = (s: number | null) => {
  if (s == null) return '—';
  const neg = s < 0; s = Math.abs(s);
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return (neg ? '+' : '') + (d ? `${d}d ` : '') + `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`;
};
