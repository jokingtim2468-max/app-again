import { useState } from 'react';
import { useAgentStore, ToolCard } from '../../stores/useAgentStore';

function Card({ t }: { t: ToolCard }) {
  return (
    <div className="wire" style={{ padding: 10, fontFamily: 'var(--mono)', fontSize: 11 }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span style={{ color: 'var(--accent-2)' }}>⚙ {t.tool}</span>
        <span className={t.error ? 'neg' : t.result ? 'pos' : 'mut'}>{t.error ? 'error' : t.result ? 'done' : 'running'}</span>
      </div>
      <pre style={{ margin: '6px 0 0', whiteSpace: 'pre-wrap', color: 'var(--muted)' }}>{JSON.stringify(t.args)}</pre>
      {t.result !== undefined && <pre style={{ margin: '6px 0 0', whiteSpace: 'pre-wrap', maxHeight: 160, overflow: 'auto' }}>{JSON.stringify(t.result, null, 1).slice(0, 2000)}</pre>}
      {t.error && <div className="neg">{t.error}</div>}
    </div>
  );
}

export default function RightChatDrawer() {
  const { chatOpen, messages, send, streaming, model, setModel } = useAgentStore();
  const [text, setText] = useState('');
  if (!chatOpen) return null;
  return (
    <aside style={{ width: 360, display: 'flex', flexDirection: 'column', borderLeft: '1px solid var(--line)', background: 'var(--panel)' }}>
      <div className="row" style={{ padding: 12, borderBottom: '1px solid var(--line)', justifyContent: 'space-between' }}>
        <span className="h" style={{ margin: 0 }}>Agent</span>
        <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model">
          <option>news-predictor-3b</option><option>qwen2.5:7b</option><option>llama3.1:8b</option>
        </select>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {messages.length === 0 && <div className="mut">Local Ollama chat. MCP tool calls from Antigravity / Claude appear here as cards.</div>}
        {messages.map((m, i) => m.tool ? <Card key={i} t={m.tool} /> : (
          <div key={i} style={{ alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '88%',
            background: m.role === 'user' ? 'var(--panel-2)' : 'transparent', border: '1px solid var(--line)',
            borderRadius: 8, padding: '8px 10px', whiteSpace: 'pre-wrap' }}>{m.content || (streaming ? '…' : '')}</div>
        ))}
      </div>
      <form style={{ padding: 12, borderTop: '1px solid var(--line)', display: 'flex', gap: 8 }}
        onSubmit={(e) => { e.preventDefault(); if (text.trim() && !streaming) { send(text.trim()); setText(''); } }}>
        <input style={{ flex: 1 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask the local model…" aria-label="Message" />
        <button disabled={streaming}>Send</button>
      </form>
    </aside>
  );
}
