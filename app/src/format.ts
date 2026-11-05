const cache = new Map<number, Intl.NumberFormat>();
function fmtN(v: number, d: number) {
  let f = cache.get(d);
  if (!f) {
    f = new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
    cache.set(d, f);
  }
  return f.format(v);
}

export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function money(v: number | null | undefined, opts: { sign?: boolean; d?: number } = {}): string {
  if (!isNum(v)) return "—";
  const d = opts.d ?? (Math.abs(v) >= 1000 ? 0 : 2);
  const sign = v < 0 ? "−" : opts.sign && v > 0 ? "+" : "";
  return `${sign}$${fmtN(Math.abs(v), d)}`;
}

export function pct(v: number | null | undefined, opts: { sign?: boolean; d?: number } = {}): string {
  if (!isNum(v)) return "—";
  const d = opts.d ?? (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2);
  const sign = v < 0 ? "−" : opts.sign && v > 0 ? "+" : "";
  return `${sign}${fmtN(Math.abs(v), d)}%`;
}

export function num(v: number | null | undefined, d = 2): string {
  if (!isNum(v)) return "—";
  return (v < 0 ? "−" : "") + fmtN(Math.abs(v), d);
}

export function price(v: number | null | undefined): string {
  if (!isNum(v)) return "—";
  const a = Math.abs(v);
  return fmtN(v, a >= 10 ? 2 : a >= 1 ? 4 : 5);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const monthName = (m: number) => MONTHS[m - 1];

export function date(ms: number | null | undefined, withTime = false): string {
  if (!isNum(ms)) return "—";
  const d = new Date(ms);
  const s = `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  if (!withTime) return s;
  return `${s}, ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

export function ago(ms: number): string {
  const s = (Date.now() - ms) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return date(ms);
}

export function duration(hours: number | null | undefined): string {
  if (!isNum(hours)) return "—";
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  if (hours < 48) return `${num(hours, 1)} h`;
  return `${num(hours / 24, 1)} days`;
}

export const KIND_LABEL: Record<string, string> = {
  pine: "Pine Script", mql4: "MQL4 EA", mql5: "MQL5 EA", "python-native": "Python",
  "backtesting.py": "backtesting.py", backtrader: "backtrader", javascript: "JavaScript",
  "tradovate-indicator": "Tradovate indicator", "tradovate-strategy": "Tradovate strategy",
  "rules-json": "Rules (JSON)", "rules-yaml": "Rules (YAML)", unknown: "Unknown",
};

export const basename = (p: string) => p.split(/[\\/]/).pop() ?? p;
