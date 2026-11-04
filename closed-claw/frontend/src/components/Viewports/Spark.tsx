export default function Spark({ data, w = 120, h = 28, color = 'var(--accent)' }: { data: number[]; w?: number; h?: number; color?: string }) {
  if (data.length < 2) return <svg width={w} height={h} />;
  const min = Math.min(...data), max = Math.max(...data), span = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / span) * (h - 2) - 1}`).join(' ');
  return <svg width={w} height={h} aria-hidden><polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" /></svg>;
}
