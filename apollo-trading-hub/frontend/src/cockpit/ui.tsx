import { ReactNode, useState } from 'react';

/** Small stroke icons (Lucide-style, inline so the app needs no icon package). */
const P: Record<string, ReactNode> = {
  dashboard: <><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></>,
  radar: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><path d="M12 12 19 5" /></>,
  bot: <><rect x="4" y="8" width="16" height="12" rx="2" /><path d="M12 8V4M8 14h.01M16 14h.01M9 18h6" /></>,
  zap: <path d="M13 2 4 14h7l-1 8 9-12h-7z" />,
  flask: <><path d="M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3" /><path d="M7 15h10" /></>,
  list: <><path d="M8 6h13M8 12h13M8 18h13" /><circle cx="3.5" cy="6" r=".5" /><circle cx="3.5" cy="12" r=".5" /><circle cx="3.5" cy="18" r=".5" /></>,
  wallet: <><rect x="3" y="6" width="18" height="14" rx="2" /><path d="M3 10h18M16 15h2" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3.1 15H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 4.1V4a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9h.1a2 2 0 1 1 0 4z" /></>,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01" /></>,
};
export function Icon({ name, size = 17 }: { name: keyof typeof P | string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>{P[name]}</svg>;
}

export function Panel({ title, right, children, className = '' }: { title: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}><h3 className="h"><span>{title}</span>{right}</h3>{children}</section>;
}

export function Bar({ pct, color }: { pct: number; color: string }) {
  return <div className="bar"><i style={{ width: `${Math.max(0, Math.min(100, pct))}%`, background: color }} /></div>;
}

/** Semicircle gauge 0..max. */
export function Gauge({ value, max, label, color }: { value: number; max: number; label: string; color: string }) {
  const f = Math.max(0, Math.min(1, value / max));
  const a = Math.PI * (1 - f);
  const x = 50 + 40 * Math.cos(a), y = 50 - 40 * Math.sin(a);
  return (
    <svg viewBox="0 0 100 58" width="100%" style={{ maxWidth: 180 }} role="img" aria-label={`${label} ${value.toFixed(1)} of ${max}`}>
      <path d="M10 50 A40 40 0 0 1 90 50" fill="none" stroke="var(--line)" strokeWidth="8" strokeLinecap="round" />
      {f > 0 && <path d={`M10 50 A40 40 0 0 1 ${x.toFixed(2)} ${y.toFixed(2)}`} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round" />}
      <text x="50" y="44" textAnchor="middle" fill="var(--text)" style={{ font: '600 15px var(--mono)' }}>{value.toFixed(1)}</text>
      <text x="50" y="56" textAnchor="middle" fill="var(--muted)" style={{ font: '8px var(--sans)' }}>{label}</text>
    </svg>
  );
}

/** Button that needs a second click within 3 s (for destructive actions). */
export function Confirm({ children, onConfirm, className, confirmText = 'Click again to confirm' }: { children: ReactNode; onConfirm: () => void; className?: string; confirmText?: string }) {
  const [armed, setArmed] = useState(false);
  return (
    <button className={className} onClick={() => { if (armed) { setArmed(false); onConfirm(); } else { setArmed(true); setTimeout(() => setArmed(false), 3000); } }}>
      {armed ? confirmText : children}
    </button>
  );
}

export const tone = (v: number) => (v > 0 ? 'pos' : v < 0 ? 'neg' : 'mut');
