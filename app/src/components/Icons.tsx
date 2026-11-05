// Small hand-drawn icon set (stroke icons, currentColor).
const S = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.5,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

export const Logo = () => (
  <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
    <rect x="0.5" y="0.5" width="21" height="21" rx="6" fill="var(--accent-soft)" stroke="var(--accent)" />
    <path d="M5 14.5 8.2 11l2.4 2.2L16.8 7" stroke="var(--accent)" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M5 17h12" stroke="var(--accent)" strokeWidth="1.2" strokeLinecap="round" opacity=".5" />
  </svg>
);
export const Sun = () => (<svg {...S}><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" /></svg>);
export const Moon = () => (<svg {...S}><path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7Z" /></svg>);
export const Folder = () => (<svg {...S}><path d="M1.5 4.5v8h13v-6.5h-6.5l-1.5-1.5h-5Z" /></svg>);
export const Play = () => (<svg {...S}><path d="M4.5 3v10l8.5-5Z" fill="currentColor" stroke="none" /></svg>);
export const Stop = () => (<svg {...S}><rect x="4" y="4" width="8" height="8" rx="1" fill="currentColor" stroke="none" /></svg>);
export const Chevron = ({ open }: { open: boolean }) => (
  <svg {...S} style={{ transform: open ? "rotate(0)" : "rotate(-90deg)", transition: "transform .15s" }}><path d="M4 6l4 4 4-4" /></svg>
);
export const Refresh = () => (<svg {...S}><path d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5v3h-3" /></svg>);
export const Trash = () => (<svg {...S}><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" /></svg>);
export const Spark = ({ values, w = 120, h = 28, color }: { values: number[]; w?: number; h?: number; color?: string }) => {
  if (!values || values.length < 2) return <svg width={w} height={h} />;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - lo) / span) * (h - 4)}`).join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={w} height={h} aria-hidden="true">
      <polyline points={pts} fill="none" stroke={color ?? (up ? "var(--data-up)" : "var(--data-down)")} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
};
