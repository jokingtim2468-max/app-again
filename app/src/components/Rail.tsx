import { useEffect, useState } from "react";
import { bridge, call } from "../api";
import type { ScriptState } from "../App";
import { basename, date, KIND_LABEL, num } from "../format";
import type { DataInfo, DataSpec, EngineError, ParamSpec, RunSettings } from "../types";
import { Chevron, Folder, Play, Spark, Stop } from "./Icons";

interface Props {
  script: ScriptState;
  setScript: (s: ScriptState) => void;
  loadScript: (path: string) => void;
  overrideKind: (k: string) => void;
  dataSpec: DataSpec;
  dataInfo: DataInfo | null;
  dataError: EngineError | null;
  loadData: (s: DataSpec) => void;
  settings: RunSettings;
  setSettings: (s: RunSettings) => void;
  canRun: boolean;
  running: boolean;
  progress: number;
  onRun: () => void;
  onCancel: () => void;
}

const EXTS = [".pine", ".mq4", ".mq5", ".py", ".js", ".json", ".yaml"];

function Section({ title, aside, children, startOpen = true }: { title: string; aside?: React.ReactNode; children: React.ReactNode; startOpen?: boolean }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <section className={`section ${open ? "" : "collapsed"}`}>
      <header>
        <span>{title}</span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {aside && <span className="aside">{aside}</span>}
          <button className="fold" aria-expanded={open} aria-label={`${open ? "Collapse" : "Expand"} ${title}`} onClick={() => setOpen(!open)}>
            <Chevron open={open} />
          </button>
        </span>
      </header>
      <div className="body">{children}</div>
    </section>
  );
}

export function Rail(p: Props) {
  return (
    <aside className="rail">
      <div className="rail-scroll">
        <ScriptSection {...p} />
        {p.script.detection && <InputsSection {...p} />}
        <DataSection {...p} />
        <CostsSection {...p} />
      </div>
      <div className="run-bar">
        {p.running ? (
          <button className="run-btn" onClick={p.onCancel} aria-label="Cancel the running backtest">
            <span className="fill" style={{ width: `${Math.round(p.progress * 100)}%` }} />
            <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><Stop /> Running {Math.round(p.progress * 100)}%, click to stop</span>
          </button>
        ) : (
          <button className="run-btn" disabled={!p.canRun} onClick={p.onRun}>
            <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><Play /> Run backtest</span>
          </button>
        )}
        <div className="run-meta">
          <span>{!p.script.path ? "Add a strategy to start" : !p.dataInfo ? "Load price data to run" : `${num(p.dataInfo.bars, 0)} bars ready`}</span>
          <span><span className="kbd">Ctrl</span> <span className="kbd">Enter</span></span>
        </div>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------- script
function ScriptSection({ script, loadScript, overrideKind }: Props) {
  const [over, setOver] = useState(false);
  const det = script.detection;
  const pick = async () => { const f = await bridge.openScript(); if (f) loadScript(f); };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files[0];
    if (f) loadScript(bridge.pathForFile(f));
  };
  return (
    <Section title="Strategy" aside={det ? `${det.lines} lines` : undefined}>
      {!script.path ? (
        <div className={`drop ${over ? "over" : ""}`} role="button" tabIndex={0} onClick={pick}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && pick()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}>
          <strong>Drop a strategy file here</strong>
          <p>Tickbench works out which language it is: Pine Script, MetaTrader EAs, Python, JavaScript, Tradovate or no-code rules.</p>
          <div className="exts">{EXTS.map((x) => <span className="ext" key={x}>{x}</span>)}</div>
        </div>
      ) : (
        <div onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
          <div className="file-card">
            <div className="file-glyph">{basename(script.path).split(".").pop()?.slice(0, 4)}</div>
            <div style={{ minWidth: 0 }}>
              <div className="name" title={script.path}>{basename(script.path)}</div>
              <div className="sub">{det?.describe?.className ?? det?.describe?.description ?? (det ? KIND_LABEL[script.kind] : "Reading…")}</div>
            </div>
            <button className="btn small ghost" onClick={pick}>Change</button>
          </div>
        </div>
      )}
      {det && (
        <div className="detect">
          <div className="row">
            <span className="label">{det.type === "unknown" ? "Couldn't identify this file" : det.label}</span>
            {det.type !== "unknown" && (
              <span className="conf" title="How sure the detector is">
                <span className="bar"><i style={{ width: `${Math.round(det.confidence * 100)}%` }} /></span>
                {Math.round(det.confidence * 100)}%
              </span>
            )}
          </div>
          {det.evidence.length > 0 && (
            <div className="evidence">{det.evidence.slice(0, 6).map((e) => <span key={e}>{e}</span>)}</div>
          )}
          <label className="field" style={{ marginTop: 2 }}>
            <span>{det.type === "unknown" ? "Pick the type to run it as" : "Not right? Run it as"}</span>
            <select className="input" value={script.kind} onChange={(e) => overrideKind(e.target.value)}>
              {det.type === "unknown" && <option value="unknown">Choose…</option>}
              {Object.entries(det.types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
      )}
      {script.error && <InlineError e={script.error} />}
    </Section>
  );
}

function InlineError({ e }: { e: EngineError }) {
  return (
    <div className="error-card" role="alert">
      <h4>{e.message}</h4>
      {e.hint && <p>{e.hint}</p>}
      {e.line != null && <div className="where">{e.file ? `${e.file}, ` : ""}line {e.line}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------- inputs
function ParamField({ spec, value, onChange }: { spec: ParamSpec; value: unknown; onChange: (v: unknown) => void }) {
  const label = spec.title && spec.title !== spec.name ? spec.title : spec.name;
  if (typeof spec.default === "boolean" || spec.type === "bool" || spec.type === "boolean") {
    return (
      <label className="check"><input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {label}</label>
    );
  }
  if (spec.options && spec.options.length) {
    return (
      <label className="field"><span title={spec.name}>{label}</span>
        <select className="input" value={String(value)} onChange={(e) => {
          const raw = e.target.value;
          const opt = spec.options!.find((o) => String(o) === raw);
          onChange(opt ?? raw);
        }}>
          {spec.options.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
        </select>
      </label>
    );
  }
  if (typeof spec.default === "number" || ["int", "float", "double", "number"].includes(spec.type ?? "")) {
    const isInt = spec.type === "int" || (Number.isInteger(spec.default) && spec.type !== "float" && spec.type !== "double");
    return (
      <label className="field"><span title={spec.name}>{label}</span>
        <input className="input num" type="number" value={value as number ?? ""} step={spec.step ?? (isInt ? 1 : "any")}
          min={spec.minval} max={spec.maxval}
          onChange={(e) => onChange(e.target.value === "" ? spec.default : isInt ? parseInt(e.target.value, 10) : parseFloat(e.target.value))} />
      </label>
    );
  }
  return (
    <label className="field"><span title={spec.name}>{label}</span>
      <input className="input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function InputsSection({ script, setScript }: Props) {
  const specs = script.detection?.describe?.params ?? [];
  const plots = script.detection?.describe?.plots ?? [];
  const isIndicator = script.kind === "tradovate-indicator";
  const set = (k: string, v: unknown) => setScript({ ...script, params: { ...script.params, [k]: v } });
  const changed = specs.some((s) => script.params[s.name] !== s.default);
  if (!specs.length && !isIndicator) return null;
  const sig = script.signal;
  const setSig = (patch: Partial<ScriptState["signal"]>) => setScript({ ...script, signal: { ...sig, ...patch } });
  return (
    <Section title="Inputs" aside={changed ? (
      <button className="btn small ghost" onClick={() => {
        const p: Record<string, unknown> = {};
        specs.forEach((s) => { p[s.name] = s.default; });
        setScript({ ...script, params: p });
      }}>Reset</button>) : `${specs.length}`}>
      {specs.map((s) => <ParamField key={s.name} spec={s} value={script.params[s.name]} onChange={(v) => set(s.name, v)} />)}
      {isIndicator && (
        <>
          <p className="hint">Indicators don't trade on their own. Choose the rule that turns this one into entries and exits.</p>
          <div className="seg" role="group" aria-label="Signal rule">
            {[["", "Automatic"], ["cross", "Cross"], ["threshold", "Levels"]].map(([k, l]) => (
              <button key={k} aria-pressed={sig.mode === k} onClick={() => setSig({ mode: k })}>{l}</button>
            ))}
          </div>
          {sig.mode === "cross" && (
            <div className="grid2">
              <select className="input" value={sig.a ?? plots[0] ?? ""} onChange={(e) => setSig({ a: e.target.value })} aria-label="Line that crosses">
                {["close", ...plots].map((x) => <option key={x}>{x}</option>)}
              </select>
              <select className="input" value={String(sig.b ?? plots[1] ?? 0)} onChange={(e) => setSig({ b: isNaN(+e.target.value) ? e.target.value : +e.target.value })} aria-label="Line it crosses">
                {[...plots, "close", "0"].map((x) => <option key={x}>{x}</option>)}
              </select>
            </div>
          )}
          {sig.mode === "threshold" && (
            <div className="grid2">
              <select className="input" value={sig.a ?? plots[0] ?? ""} onChange={(e) => setSig({ a: e.target.value })}>
                {plots.map((x) => <option key={x}>{x}</option>)}
              </select>
              <div className="grid2">
                <input className="input num" type="number" value={sig.lower ?? 30} onChange={(e) => setSig({ lower: +e.target.value })} aria-label="Lower level" />
                <input className="input num" type="number" value={sig.upper ?? 70} onChange={(e) => setSig({ upper: +e.target.value })} aria-label="Upper level" />
              </div>
            </div>
          )}
          {sig.mode && (
            <label className="check"><input type="checkbox" checked={!!sig.short} onChange={(e) => setSig({ short: e.target.checked })} /> Take short trades on the opposite signal</label>
          )}
        </>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------- data
const INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d", "1w"];
const RESAMPLE = ["", "5m", "15m", "30m", "1h", "4h", "1d", "1w"];

function DataSection({ dataSpec, dataInfo, dataError, loadData }: Props) {
  const [sym, setSym] = useState(dataSpec.symbol ?? "");
  const [interval, setInterval] = useState(dataSpec.interval ?? "1d");
  const [start, setStart] = useState(dataSpec.start ?? "2018-01-01");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setSym(dataSpec.symbol ?? ""); }, [dataSpec.symbol]);
  const load = async (spec: DataSpec) => { setBusy(true); await loadData(spec); setBusy(false); };
  const pickCsv = async () => { const f = await bridge.openData(); if (f) load({ ...dataSpec, source: "csv", path: f }); };
  return (
    <Section title="Price data" aside={dataInfo ? dataInfo.source === "yahoo" ? "Yahoo Finance" : "CSV" : undefined}>
      <div className="seg" role="group" aria-label="Data source">
        <button aria-pressed={dataSpec.source === "csv"} onClick={() => loadData({ ...dataSpec, source: "csv" })}>CSV or MT5 export</button>
        <button aria-pressed={dataSpec.source === "yahoo"} onClick={() => loadData({ ...dataSpec, source: "yahoo" })}>Yahoo Finance</button>
      </div>
      {dataSpec.source === "csv" ? (
        <>
          <button className="btn" onClick={pickCsv}><Folder /> {dataSpec.path ? basename(dataSpec.path) : "Choose a CSV file…"}</button>
          <p className="hint">MetaTrader 4/5 history exports, TradingView exports and plain Date, Open, High, Low, Close, Volume files all work.</p>
        </>
      ) : (
        <>
          <div className="grid2">
            <input className="input" placeholder="GC=F, SPY, EURUSD…" value={sym} onChange={(e) => setSym(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sym && load({ ...dataSpec, source: "yahoo", symbol: sym, interval, start })} aria-label="Yahoo symbol" />
            <select className="input" value={interval} onChange={(e) => setInterval(e.target.value)} aria-label="Bar interval">
              {INTERVALS.map((i) => <option key={i}>{i}</option>)}
            </select>
          </div>
          <div className="grid2">
            <input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} aria-label="Start date" disabled={interval !== "1d" && interval !== "1w"} />
            <button className="btn" disabled={!sym || busy} onClick={() => load({ ...dataSpec, source: "yahoo", symbol: sym, interval, start: interval === "1d" || interval === "1w" ? start : undefined })}>
              {busy ? "Downloading…" : "Download"}
            </button>
          </div>
          <p className="hint">Free and cached on this PC. Futures use =F (ES=F), forex =X or plain pairs (EURUSD). Yahoo keeps 1m bars for 7 days and 1h bars for 2 years.</p>
        </>
      )}
      {dataInfo && (
        <div className="data-strip">
          <div className="meta">
            <b>{dataInfo.symbol}</b> {dataInfo.timeframe} with {num(dataInfo.bars, 0)} bars<br />
            {date(dataInfo.start)} to {date(dataInfo.end)}
            {dataInfo.rowsDropped ? <><br /><span style={{ color: "var(--warn)" }}>{dataInfo.rowsDropped} unreadable rows skipped</span></> : null}
          </div>
          <Spark values={dataInfo.spark} w={84} h={30} color="var(--ink-3)" />
        </div>
      )}
      {dataInfo && (
        <div className="grid2">
          <label className="field wide"><span>Resample to</span>
            <select className="input" value={dataSpec.timeframe ?? ""} onChange={(e) => load({ ...dataSpec, timeframe: e.target.value || undefined })}>
              {RESAMPLE.map((r) => <option key={r} value={r}>{r || "As loaded"}</option>)}
            </select>
          </label>
          <label className="field wide"><span>From</span>
            <input className="input" type="date" value={dataSpec.from ?? ""} onChange={(e) => load({ ...dataSpec, from: e.target.value || undefined })} />
          </label>
        </div>
      )}
      {dataError && <InlineError e={dataError} />}
    </Section>
  );
}

// ---------------------------------------------------------------------------- costs
interface Contract { root: string; name: string; tick: number; point_value: number; commission: number }

function CostsSection({ settings, setSettings, script }: Props) {
  const [contracts, setContracts] = useState<Contract[]>([]);
  useEffect(() => { call<Contract[]>("contracts").then(setContracts).catch(() => undefined); }, []);
  const set = <K extends keyof RunSettings>(k: K, v: RunSettings[K]) => setSettings({ ...settings, [k]: v });
  const isMql = script.kind.startsWith("mql");
  const c = contracts.find((x) => x.root === settings.contract);
  return (
    <Section title="Account, sizing and costs" startOpen={true}>
      <label className="field"><span>Starting capital</span>
        <input className="input num" type="number" value={settings.initial_capital} min={1}
          onChange={(e) => set("initial_capital", +e.target.value || 10000)} />
      </label>
      <label className="field"><span>Futures contract<small>{c ? `${c.name}: $${num(c.point_value * c.tick, 2)} per tick, sized in contracts` : "Leave as none for stocks, crypto, CFDs"}</small></span>
        <select className="input" value={settings.contract} onChange={(e) => set("contract", e.target.value)}>
          <option value="">None</option>
          <option value="auto">Detect from symbol</option>
          {contracts.map((x) => <option key={x.root} value={x.root}>{x.root}, {x.name}</option>)}
        </select>
      </label>
      <div className="field"><span>Default order size<small>Used when the script doesn't set a quantity</small></span>
        <input className="input num" type="number" value={settings.default_qty} min={0} step="any"
          onChange={(e) => set("default_qty", +e.target.value)} />
      </div>
      <div className="seg" role="group" aria-label="Sizing mode">
        {([["fixed", isMql ? "Lots" : "Units"], ["percent_equity", "% of equity"], ["cash", "Cash amount"]] as const).map(([k, l]) => (
          <button key={k} aria-pressed={settings.qty_mode === k} onClick={() => set("qty_mode", k)}>{l}</button>
        ))}
      </div>
      <div className="grid2">
        <label className="field wide"><span>Commission per side, per {isMql ? "lot" : "unit"} ($)</span>
          <input className="input num" type="number" step="any" min={0} value={settings.commission_per_unit} onChange={(e) => set("commission_per_unit", +e.target.value)} />
        </label>
        <label className="field wide"><span>Commission (% of value)</span>
          <input className="input num" type="number" step="any" min={0} value={settings.commission_pct} onChange={(e) => set("commission_pct", +e.target.value)} />
        </label>
        <label className="field wide"><span>Slippage (ticks)</span>
          <input className="input num" type="number" step="any" min={0} value={settings.slippage_ticks} onChange={(e) => set("slippage_ticks", +e.target.value)} />
        </label>
        <label className="field wide"><span>Spread (price)</span>
          <input className="input num" type="number" step="any" min={0} value={settings.spread} onChange={(e) => set("spread", +e.target.value)} />
        </label>
      </div>
      {isMql && (
        <label className="field"><span>Contract size per lot<small>Blank uses 100,000 for forex and 100 for gold</small></span>
          <input className="input num" type="number" step="any" min={0} value={settings.point_value ?? ""} placeholder="auto"
            onChange={(e) => setSettings({ ...settings, point_value: e.target.value === "" ? undefined : +e.target.value })} />
        </label>
      )}
      <label className="check"><input type="checkbox" checked={settings.allow_short} onChange={(e) => set("allow_short", e.target.checked)} /> Allow short selling</label>
      {script.kind === "pine" && (
        <label className="check"><input type="checkbox" checked={settings.prefer_script} onChange={(e) => set("prefer_script", e.target.checked)} /> Use the capital, sizing and commission set in the script's strategy()</label>
      )}
      {isMql && (
        <label className="check"><input type="checkbox" checked={settings.hedging} onChange={(e) => set("hedging", e.target.checked)} /> Hedging account (each order is its own position)</label>
      )}
    </Section>
  );
}
