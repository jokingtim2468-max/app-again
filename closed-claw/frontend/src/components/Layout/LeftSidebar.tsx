import ClawLogo from '../UI/ClawLogo';
import { useAgentStore, View } from '../../stores/useAgentStore';

const items: { id: View; label: string; glyph: string }[] = [
  { id: 'fleet', label: 'Fleet', glyph: '◫' },
  { id: 'backtest', label: 'Backtest', glyph: '∿' },
  { id: 'vm', label: 'Sandboxes', glyph: '▣' },
];

export default function LeftSidebar() {
  const { view, setView, toggleChat, chatOpen } = useAgentStore();
  return (
    <nav style={{
      position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: '14px 0',
      background: 'var(--panel)',
      WebkitMaskImage: 'linear-gradient(to right, #000 82%, rgba(0,0,0,.35) 100%)',
      maskImage: 'linear-gradient(to right, #000 82%, rgba(0,0,0,.35) 100%)',
    }}>
      <ClawLogo />
      <div style={{ height: 14 }} />
      {items.map((i) => (
        <button key={i.id} title={i.label} aria-label={i.label} aria-current={view === i.id}
          onClick={() => setView(i.id)}
          style={{ width: 40, height: 40, fontSize: 18, padding: 0,
            borderColor: view === i.id ? 'var(--accent)' : 'var(--line)', color: view === i.id ? 'var(--accent)' : 'var(--muted)' }}>
          {i.glyph}
        </button>
      ))}
      <div style={{ flex: 1 }} />
      <button title="Toggle AI chat" aria-label="Toggle AI chat" onClick={toggleChat}
        style={{ width: 40, height: 40, padding: 0, color: chatOpen ? 'var(--accent-2)' : 'var(--muted)' }}>✦</button>
    </nav>
  );
}
