import { create } from 'zustand';
import { API } from '../api';

export type View = 'fleet' | 'backtest' | 'vm';
export interface ToolCard { tool: string; args: Record<string, unknown>; result?: unknown; error?: string }
export interface Msg { role: 'user' | 'assistant'; content: string; tool?: ToolCard }

interface AgentState {
  view: View; setView: (v: View) => void;
  chatOpen: boolean; toggleChat: () => void;
  model: string; setModel: (m: string) => void;
  messages: Msg[]; streaming: boolean;
  containerId: string | null; setContainer: (id: string | null) => void;
  send: (text: string) => Promise<void>;
  pushTool: (card: ToolCard) => void;
}

export const useAgentStore = create<AgentState>((set, get) => ({
  view: 'fleet', setView: (view) => set({ view }),
  chatOpen: true, toggleChat: () => set((s) => ({ chatOpen: !s.chatOpen })),
  model: 'news-predictor-3b', setModel: (model) => set({ model }),
  messages: [], streaming: false,
  containerId: null, setContainer: (containerId) => set({ containerId }),
  pushTool: (tool) => set((s) => ({ messages: [...s.messages, { role: 'assistant', content: '', tool }] })),
  send: async (text) => {
    const history = [...get().messages.filter((m) => !m.tool), { role: 'user' as const, content: text }];
    set({ messages: [...get().messages, { role: 'user', content: text }, { role: 'assistant', content: '' }], streaming: true });
    try {
      const r = await fetch(`${API}/api/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: get().model, messages: history.map(({ role, content }) => ({ role, content })) }),
      });
      if (!r.body) throw new Error('no stream');
      const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split('\n\n'); buf = parts.pop() || '';
        for (const p of parts) {
          const data = p.replace(/^data: /, '');
          if (data === '[DONE]') continue;
          const tok = JSON.parse(data).token as string;
          set((s) => { const m = [...s.messages]; m[m.length - 1] = { ...m[m.length - 1], content: m[m.length - 1].content + tok }; return { messages: m }; });
        }
      }
    } catch (e) {
      set((s) => { const m = [...s.messages]; m[m.length - 1] = { role: 'assistant', content: `⚠ ${e}` }; return { messages: m }; });
    } finally { set({ streaming: false }); }
  },
}));
