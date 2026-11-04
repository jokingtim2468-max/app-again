import AppLogo from '../UI/AppLogo';

export type Route = 'workspace' | 'builder' | 'settings';
const items: { id: Route; label: string; glyph: string }[] = [
  { id: 'workspace', label: 'Workspace', glyph: '▦' },
  { id: 'builder', label: 'Builder (Layout Studio)', glyph: '⊞' },
  { id: 'settings', label: 'Settings (bots, alerts, commands)', glyph: '⚙' },
];

export default function LeftRail({ route, go }: { route: Route; go: (r: Route) => void }) {
  return (
    <nav data-tour="rail" aria-label="Primary" style={{
      gridRow: '1 / 3', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: '10px 0',
      background: 'linear-gradient(to right, #0E1018 0%, #0E1018 70%, rgba(14,16,24,0) 100%)',
      borderRight: '1px solid transparent', borderImage: 'linear-gradient(to bottom, transparent, #212636 15%, #212636 85%, transparent) 1',
    }}>
      <div style={{ color: '#EEF1F8', marginBottom: 14 }}><AppLogo size={26} /></div>
      {items.map((i) => (
        <button key={i.id} title={i.label} aria-label={i.label} aria-current={route === i.id ? 'page' : undefined} onClick={() => go(i.id)}
          style={{ width: 36, height: 36, padding: 0, fontSize: 16, background: route === i.id ? '#0F2A22' : 'transparent',
            borderColor: route === i.id ? '#1D5A47' : 'transparent', color: route === i.id ? 'var(--accent)' : 'var(--muted)' }}>
          {i.glyph}
        </button>
      ))}
    </nav>
  );
}
