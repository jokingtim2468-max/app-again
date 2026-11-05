import { monthName, pct } from "../format";

/** Calendar of monthly returns. Diverging colour (loss red ↔ neutral ↔ gain green) plus the signed value in every cell. */
export function MonthlyHeatmap({ months }: { months: { year: number; month: number; pct: number }[] }) {
  if (!months.length) return null;
  const years = Array.from(new Set(months.map((m) => m.year))).sort();
  const by = new Map(months.map((m) => [`${m.year}-${m.month}`, m.pct]));
  const maxAbs = Math.max(2, ...months.map((m) => Math.abs(m.pct)));
  const yearTotal = (y: number) => months.filter((m) => m.year === y).reduce((acc, m) => acc * (1 + m.pct / 100), 1) * 100 - 100;
  const cellBg = (v: number) => {
    const a = Math.min(1, Math.abs(v) / maxAbs);
    const c = v >= 0 ? "var(--data-up)" : "var(--data-down)";
    return `color-mix(in srgb, ${c} ${Math.round(12 + a * 58)}%, var(--panel-2))`;
  };
  const shown = years.slice(-12);
  return (
    <div className="heat" style={{ gridTemplateColumns: `48px repeat(12, 1fr) 64px` }} role="table" aria-label="Monthly returns">
      <div />
      {Array.from({ length: 12 }, (_, i) => <div className="h" key={i}>{monthName(i + 1)}</div>)}
      <div className="h">Year</div>
      {shown.map((y) => (
        <Row key={y} y={y} by={by} cellBg={cellBg} total={yearTotal(y)} />
      ))}
      {years.length > shown.length && <div className="h" style={{ gridColumn: "1 / -1", textAlign: "left" }}>Showing the last 12 years</div>}
    </div>
  );
}

function Row({ y, by, cellBg, total }: { y: number; by: Map<string, number>; cellBg: (v: number) => string; total: number }) {
  return (
    <>
      <div className="y">{y}</div>
      {Array.from({ length: 12 }, (_, i) => {
        const v = by.get(`${y}-${i + 1}`);
        return v == null
          ? <div key={i} className="cell" style={{ background: "var(--inset)" }} />
          : <div key={i} className="cell" style={{ background: cellBg(v), color: "var(--ink)" }} title={`${monthName(i + 1)} ${y}: ${pct(v, { sign: true })}`}>
              {Math.abs(v) < 0.05 ? "0" : `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(Math.abs(v) >= 10 ? 0 : 1)}`}
            </div>;
      })}
      <div className="cell" style={{ background: cellBg(total), color: "var(--ink)", fontWeight: 500 }}>{pct(total, { sign: true, d: 1 })}</div>
    </>
  );
}
