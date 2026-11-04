import { create } from 'zustand';
import { api, onEvent } from '../api';

export type WidgetType = 'widget-chart' | 'widget-dom' | 'widget-fleet' | 'widget-tape' | 'widget-backtest' | 'widget-terminal' | 'widget-accounts';
export interface WidgetItem { i: string; type: WidgetType; x: number; y: number; w: number; h: number; settings: Record<string, unknown> }
export interface SavedLayout { widgets: WidgetItem[]; updated_at?: string; source?: string }

export const WIDGET_META: Record<WidgetType, { name: string; desc: string; w: number; h: number; minW: number; minH: number; settings: Record<string, unknown> }> = {
  'widget-chart': { name: 'MGC Candlestick Viewport', desc: 'Lightweight Charts v5: 1m/5m/15m candles, volume delta, session levels, position markers.', w: 8, h: 13, minW: 3, minH: 6, settings: { timeframe: '1m' } },
  'widget-dom': { name: 'Depth of Market Ladder', desc: 'Resting bid/ask liquidity, volume profile and one-click fleet entries.', w: 4, h: 13, minW: 3, minH: 8, settings: {} },
  'widget-fleet': { name: 'Fleet Command Deck', desc: 'Balances, open contracts, distance to EOD MLL, qualifying days, kill switches.', w: 12, h: 8, minW: 4, minH: 4, settings: { compact: false } },
  'widget-tape': { name: 'Time & Sales Tape', desc: 'Scrolling trade prints with block filter (≥10 lots by default).', w: 4, h: 10, minW: 2, minH: 4, settings: { min_size: 10 } },
  'widget-backtest': { name: 'Tick Backtest Canvas', desc: 'Equity vs MLL, underwater drawdown, spread-slippage stress tester.', w: 7, h: 12, minW: 4, minH: 7, settings: {} },
  'widget-accounts': { name: 'Account Manager', desc: 'Add accounts from any prop firm or broker: firm rules, platform, copy ratio, master/copy.', w: 12, h: 14, minW: 6, minH: 8, settings: {} },
  'widget-terminal': { name: 'VM Sandbox Shell', desc: 'xterm.js shell into an isolated Docker container.', w: 5, h: 10, minW: 3, minH: 5, settings: {} },
};

const W = (i: string, type: WidgetType, x: number, y: number, w: number, h: number, settings: Record<string, unknown> = {}): WidgetItem => ({ i, type, x, y, w, h, settings });
export const FALLBACK_PRESETS: Record<string, WidgetItem[]> = {
  'Execution Focus': [W('chart-1', 'widget-chart', 0, 0, 8, 14, { timeframe: '1m' }), W('dom-1', 'widget-dom', 8, 0, 4, 14), W('fleet-1', 'widget-fleet', 0, 14, 12, 7, { compact: true })],
};

interface LayoutState {
  presets: Record<string, WidgetItem[]>;
  saved: Record<string, SavedLayout>;
  activeName: string;
  widgets: WidgetItem[];
  locked: boolean;
  dirty: boolean;
  maximized: string | null;
  backendOnline: boolean;
  toast: string | null;
  init: () => Promise<void>;
  load: (name: string) => void;
  setWidgets: (w: WidgetItem[]) => void;
  addWidget: (t: WidgetType) => void;
  removeWidget: (i: string) => void;
  updateSettings: (i: string, s: Record<string, unknown>) => void;
  setLocked: (b: boolean) => void;
  setMax: (i: string | null) => void;
  save: (name: string) => Promise<void>;
  deleteSaved: (name: string) => Promise<void>;
  reset: () => void;
  exportJson: () => string;
  importJson: (text: string) => Promise<void>;
  flash: (m: string) => void;
}

const LS_KEY = 'apollo.layouts.offline';
const lsGet = (): Record<string, SavedLayout> => { try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch { return {}; } };
const lsSet = (v: Record<string, SavedLayout>) => { try { localStorage.setItem(LS_KEY, JSON.stringify(v)); } catch { /* storage blocked */ } };

const clone = (w: WidgetItem[]) => w.map((x) => ({ ...x, settings: { ...x.settings } }));

/** First slot scanning rows top-down where a w-wide, h-tall card fits without collision. */
function nextFree(widgets: WidgetItem[], w: number, h: number): { x: number; y: number } {
  const hit = (x: number, y: number) => widgets.some((o) => x < o.x + o.w && x + w > o.x && y < o.y + o.h && y + h > o.y);
  for (let y = 0; y < 400; y++) for (let x = 0; x + w <= 12; x++) if (!hit(x, y)) return { x, y };
  return { x: 0, y: widgets.reduce((m, it) => Math.max(m, it.y + it.h), 0) };
}

export const useLayoutStore = create<LayoutState>((set, get) => ({
  presets: FALLBACK_PRESETS, saved: {}, activeName: 'Execution Focus', widgets: clone(FALLBACK_PRESETS['Execution Focus']),
  locked: false, dirty: false, maximized: null, backendOnline: false, toast: null,

  init: async () => {
    try {
      const d = await api<{ active: string; presets: Record<string, WidgetItem[]>; layouts: Record<string, SavedLayout> }>('/api/layouts');
      set({ presets: d.presets, saved: d.layouts, backendOnline: true });
      get().load(d.active in d.layouts || d.active in d.presets ? d.active : 'Execution Focus');
    } catch {
      set({ saved: lsGet(), backendOnline: false });
      get().load(get().activeName);
    }
    onEvent(async (e) => {
      if (e.type !== 'layout_saved') return;
      const d = await api<{ layouts: Record<string, SavedLayout> }>('/api/layouts');
      set({ saved: d.layouts });
      if (e.activate && e.source !== 'ui') { get().load(String(e.name)); get().flash(`Layout “${e.name}” pushed by ${e.source === 'mcp' ? 'agent (MCP)' : e.source}`); }
    });
  },

  load: (name) => {
    const { saved, presets } = get();
    const w = saved[name]?.widgets ?? presets[name];
    if (!w) return;
    set({ activeName: name, widgets: clone(w), dirty: false, maximized: null });
    if (get().backendOnline) api(`/api/layouts/${encodeURIComponent(name)}/activate`, { method: 'POST' }).catch(() => undefined);
  },

  setWidgets: (w) => {
    const cur = get().widgets;
    const changed = w.length !== cur.length || w.some((n) => { const o = cur.find((c) => c.i === n.i); return !o || o.x !== n.x || o.y !== n.y || o.w !== n.w || o.h !== n.h; });
    if (changed) set({ widgets: w, dirty: true });
  },

  addWidget: (t) => {
    const meta = WIDGET_META[t];
    const ws = get().widgets;
    const base = t.split('-')[1];
    let n = 1; while (ws.some((x) => x.i === `${base}-${n}`)) n++;
    const pos = nextFree(ws, meta.w, meta.h);
    set({ widgets: [...ws, { i: `${base}-${n}`, type: t, ...pos, w: meta.w, h: meta.h, settings: { ...meta.settings } }], dirty: true });
  },
  removeWidget: (i) => set((s) => ({ widgets: s.widgets.filter((w) => w.i !== i), dirty: true, maximized: s.maximized === i ? null : s.maximized })),
  updateSettings: (i, st) => set((s) => ({ widgets: s.widgets.map((w) => (w.i === i ? { ...w, settings: { ...w.settings, ...st } } : w)), dirty: true })),
  setLocked: (locked) => set({ locked }),
  setMax: (maximized) => set({ maximized }),

  save: async (name) => {
    const widgets = get().widgets;
    if (get().backendOnline) {
      await api('/api/layouts', { method: 'POST', body: JSON.stringify({ name, widgets, activate: true, source: 'ui' }) });
    }
    const saved = { ...get().saved, [name]: { widgets: clone(widgets), updated_at: new Date().toISOString(), source: 'ui' } };
    if (!get().backendOnline) lsSet(saved);
    set({ saved, activeName: name, dirty: false });
    get().flash(`Saved “${name}”`);
  },
  deleteSaved: async (name) => {
    if (get().backendOnline) await api(`/api/layouts/${encodeURIComponent(name)}`, { method: 'DELETE' });
    const saved = { ...get().saved }; delete saved[name];
    if (!get().backendOnline) lsSet(saved);
    set({ saved });
    if (get().activeName === name) get().load('Execution Focus');
  },
  reset: () => get().load(get().activeName),

  exportJson: () => JSON.stringify({ app: 'apollo-trading-hub', version: 1, name: get().activeName, widgets: get().widgets }, null, 2),
  importJson: async (text) => {
    const d = JSON.parse(text);
    const widgets: WidgetItem[] = Array.isArray(d) ? d : d.widgets;
    if (!Array.isArray(widgets) || !widgets.every((w) => w.type in WIDGET_META)) throw new Error('Not an Apollo layout file');
    set({ widgets: clone(widgets.map((w) => ({ ...w, settings: w.settings || {} }))), dirty: true });
    await get().save(String(d.name || 'Imported'));
  },
  flash: (toast) => { set({ toast }); setTimeout(() => { if (get().toast === toast) set({ toast: null }); }, 3500); },
}));
