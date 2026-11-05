export type ScriptKind =
  | "pine" | "mql4" | "mql5" | "python-native" | "backtesting.py" | "backtrader" | "javascript"
  | "tradovate-indicator" | "tradovate-strategy" | "rules-json" | "rules-yaml" | "unknown";

export interface ParamSpec {
  name: string;
  title?: string;
  default: number | string | boolean | null;
  type?: string;
  kind?: string;
  options?: (string | number)[];
  minval?: number;
  maxval?: number;
  step?: number;
}

export interface Detection {
  type: ScriptKind;
  label: string;
  confidence: number;
  evidence: string[];
  scores: Record<string, number>;
  types: Record<string, string>;
  preview: string;
  lines: number;
  describe?: {
    params: ParamSpec[]; flavor?: string; plots?: string[]; handlers?: string[]; declaration?: string;
    className?: string; description?: string;
  };
  describeError?: EngineError;
}

export interface EngineError {
  message: string;
  hint?: string;
  line?: number | null;
  file?: string | null;
  kind?: string;
  trace?: string;
}

export interface DataInfo {
  symbol: string;
  timeframe: string;
  bars: number;
  start: number;
  end: number;
  first: number;
  last: number;
  source: string;
  spark: number[];
  rowsDropped?: number;
}

export interface Trade {
  id: number;
  side: "long" | "short";
  qty: number;
  entryBar: number;
  entryTime: number;
  entryPrice: number;
  exitBar: number | null;
  exitTime: number | null;
  exitPrice: number | null;
  tag: string;
  entryReason: string;
  exitReason: string;
  pnl: number;
  commission: number;
  mae: number;
  mfe: number;
  sl: number | null;
  tp: number | null;
  barsHeld: number | null;
  r: number | null;
}

export interface EventRow { bar: number; time: number; kind: string; text: string; trade?: number }

export interface PlotSeries { name: string; values: (number | null)[]; overlay: boolean; color: string | null; kind: string }

export type Stats = Record<string, number | null>;

export interface RunResult {
  id: string;
  createdAt: number;
  label?: string;
  script: { filename: string; kind: ScriptKind; detected: Detection; params: Record<string, unknown> };
  data: { symbol: string; timeframe: string; bars: number; source: string; start: number; end: number };
  settings: Record<string, number | string | boolean>;
  contract: { root: string; name: string; tick: number; point_value: number; commission: number } | null;
  bars: { time: number[]; open: number[]; high: number[]; low: number[]; close: number[]; volume: number[] };
  equity: number[];
  buyHold: number[];
  drawdownPct: number[];
  trades: Trade[];
  stats: Stats;
  monthly: { year: number; month: number; pct: number }[];
  events: EventRow[];
  plots: PlotSeries[];
  elapsedMs: number;
  warnings?: string[];
}

export interface RunSummary {
  id: string;
  createdAt: number;
  script: string;
  kind: ScriptKind;
  symbol: string;
  timeframe: string;
  netProfit: number | null;
  netProfitPct: number | null;
  trades: number | null;
  maxDrawdownPct: number | null;
  sharpe: number | null;
  winRate: number | null;
  profitFactor: number | null;
  params: Record<string, unknown>;
  spark: number[];
}

export interface DataSpec {
  source: "csv" | "yahoo";
  path?: string;
  symbol?: string;
  interval?: string;
  start?: string;
  end?: string;
  timeframe?: string;
  from?: string;
  to?: string;
}

export interface RunSettings {
  initial_capital: number;
  qty_mode: "fixed" | "percent_equity" | "cash";
  default_qty: number;
  commission_per_unit: number;
  commission_pct: number;
  slippage_ticks: number;
  spread: number;
  contract: string;
  allow_short: boolean;
  hedging: boolean;
  prefer_script: boolean;
  point_value?: number;
  tick_size?: number;
}
