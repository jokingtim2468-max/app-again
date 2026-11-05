import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { bridge, call, EngineFailure, UpdateStatus } from "./api";
import { Logo, Moon, Sun } from "./components/Icons";
import { Rail } from "./components/Rail";
import { useLocal } from "./hooks";
import type { DataInfo, DataSpec, Detection, EngineError, RunResult, RunSettings, RunSummary } from "./types";
import { Compare } from "./views/Compare";
import { Empty, Example } from "./views/Empty";
import { History } from "./views/History";
import { ErrorPanel, Results } from "./views/Results";

export type View = "workspace" | "history" | "compare";

export const DEFAULT_SETTINGS: RunSettings = {
  initial_capital: 10000,
  qty_mode: "percent_equity",
  default_qty: 100,
  commission_per_unit: 0,
  commission_pct: 0,
  slippage_ticks: 0,
  spread: 0,
  contract: "",
  allow_short: true,
  hedging: true,
  prefer_script: true,
};

export interface ScriptState {
  path: string;
  detection: Detection | null;
  kind: string;            // effective kind (override or detected)
  params: Record<string, unknown>;
  signal: { mode: string; a?: string; b?: string | number; lower?: number; upper?: number; short?: boolean; contrarian?: boolean };
  error: EngineError | null;
}

const EMPTY_SCRIPT: ScriptState = { path: "", detection: null, kind: "", params: {}, signal: { mode: "" }, error: null };

export default function App() {
  const [prefs, setPrefs] = useLocal("tickbench.prefs", { theme: "dark" as "dark" | "light" });
  const [view, setView] = useState<View>("workspace");
  const [script, setScript] = useState<ScriptState>(EMPTY_SCRIPT);
  const [dataSpec, setDataSpec] = useLocal<DataSpec>("tickbench.data", { source: "csv" });
  const [dataInfo, setDataInfo] = useState<DataInfo | null>(null);
  const [dataError, setDataError] = useState<EngineError | null>(null);
  const [settings, setSettings] = useLocal<RunSettings>("tickbench.settings", DEFAULT_SETTINGS);
  const [result, setResult] = useState<RunResult | null>(null);
  const [runError, setRunError] = useState<EngineError | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [update, setUpdate] = useState<UpdateStatus>({ state: "idle" });
  const [engineDown, setEngineDown] = useState<string | null>(null);
  const [examples, setExamples] = useState<{ strategies: Example[]; data: Example[] }>({ strategies: [], data: [] });
  const runId = useRef<number | null>(null);

  useEffect(() => { document.documentElement.dataset.theme = prefs.theme; }, [prefs.theme]);

  useEffect(() => {
    const offEv = bridge.onEvent((ev) => {
      if (ev.event === "progress" && ev.id === runId.current) setProgress(ev.pct as number);
      if (ev.event === "fatal") setEngineDown(String(ev.text));
    });
    const offStart = bridge.onStarted((info) => { if (info.method === "run") runId.current = info.id; });
    const offUp = bridge.onUpdate(setUpdate);
    call<{ strategies: Example[]; data: Example[] }>("examples").then(setExamples).catch(() => undefined);
    refreshHistory();
    return () => { offEv(); offStart(); offUp(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshHistory = useCallback(() => {
    call<RunSummary[]>("runs.list").then(setHistory).catch(() => undefined);
  }, []);

  // ------------------------------------------------------------------ script
  const loadScript = useCallback(async (path: string) => {
    setScript({ ...EMPTY_SCRIPT, path });
    try {
      const det = await call<Detection>("detect", { path });
      const params: Record<string, unknown> = {};
      for (const p of det.describe?.params ?? []) params[p.name] = p.default;
      setScript({ path, detection: det, kind: det.type, params, signal: { mode: "" }, error: det.describeError ?? null });
    } catch (e) {
      setScript({ ...EMPTY_SCRIPT, path, error: (e as EngineFailure).detail ?? { message: String(e) } });
    }
  }, []);

  const overrideKind = useCallback(async (kind: string) => {
    setScript((s) => ({ ...s, kind }));
    try {
      const d = await call<Detection["describe"]>("describe", { path: script.path, kind });
      const params: Record<string, unknown> = {};
      for (const p of d?.params ?? []) params[p.name] = p.default;
      setScript((s) => ({ ...s, kind, params, error: null,
        detection: s.detection ? { ...s.detection, describe: d } : s.detection }));
    } catch (e) {
      setScript((s) => ({ ...s, kind, error: (e as EngineFailure).detail }));
    }
  }, [script.path]);

  // ------------------------------------------------------------------ data
  const loadData = useCallback(async (spec: DataSpec) => {
    setDataSpec(spec);
    setDataError(null);
    if (spec.source === "csv" && !spec.path) { setDataInfo(null); return; }
    if (spec.source === "yahoo" && !spec.symbol) { setDataInfo(null); return; }
    try {
      setDataInfo(await call<DataInfo>("loadData", spec));
    } catch (e) {
      setDataInfo(null);
      setDataError((e as EngineFailure).detail);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if ((dataSpec.source === "csv" && dataSpec.path) || (dataSpec.source === "yahoo" && dataSpec.symbol)) loadData(dataSpec);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ------------------------------------------------------------------ run
  const canRun = !!script.path && !!script.kind && script.kind !== "unknown" && !!dataInfo && !running;

  const run = useCallback(async (override?: { script?: string; data?: DataSpec; kind?: string }) => {
    const path = override?.script ?? script.path;
    const data = override?.data ?? dataSpec;
    setRunning(true);
    setProgress(0);
    setRunError(null);
    setView("workspace");
    const params = override ? {} : script.params;
    const options = script.kind === "tradovate-indicator" && script.signal.mode ? { signal: script.signal } : undefined;
    const s: Record<string, unknown> = { ...settings };
    if (!s.contract) delete s.contract;
    if (!s.point_value) delete s.point_value;
    if (!s.tick_size) delete s.tick_size;
    if (!(override?.kind ?? script.kind).startsWith("mql")) delete s.hedging;
    try {
      const r = await call<RunResult>("run", {
        script: { path, kind: override?.kind ?? (override ? undefined : script.kind), options },
        data, settings: s, params,
      });
      setResult(r);
      refreshHistory();
    } catch (e) {
      setRunError((e as EngineFailure).detail ?? { message: String(e) });
    } finally {
      setRunning(false);
      runId.current = null;
    }
  }, [script, dataSpec, settings, refreshHistory]);

  const cancel = useCallback(() => { if (runId.current != null) bridge.cancel(runId.current); }, []);

  const runExample = useCallback(async (ex: Example) => {
    const isFutures = ex.name.startsWith("tradovate");
    const dataPath = examples.data.find((d) => d.name.startsWith(isFutures ? "ES_1h" : "XAUUSD"))?.path;
    if (!dataPath) return;
    const spec: DataSpec = { source: "csv", path: dataPath };
    await loadScript(ex.path);
    await loadData(spec);
    if (isFutures) setSettings({ ...settings, contract: "ES" });
    await run({ script: ex.path, data: spec });
  }, [examples, loadScript, loadData, run, settings, setSettings]);

  const openRun = useCallback(async (id: string) => {
    try {
      setResult(await call<RunResult>("runs.get", { id }));
      setRunError(null);
      setView("workspace");
    } catch (e) {
      setRunError((e as EngineFailure).detail);
    }
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && canRun) { e.preventDefault(); run(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canRun, run]);

  const main = useMemo(() => {
    if (view === "history") {
      return <History runs={history} onOpen={openRun} compareIds={compareIds} setCompareIds={setCompareIds}
        onCompare={() => setView("compare")} onDelete={async (id) => { await call("runs.delete", { id }); refreshHistory(); }} />;
    }
    if (view === "compare") return <Compare ids={compareIds} runs={history} onBack={() => setView("history")} />;
    if (runError) return <ErrorPanel error={runError} preview={script.detection?.preview} onDismiss={() => setRunError(null)} />;
    if (result) return <Results result={result} onRerun={canRun ? () => run() : undefined} />;
    return <Empty examples={examples.strategies} onExample={runExample} busy={running} />;
  }, [view, history, compareIds, runError, result, examples, running, canRun, run, openRun, refreshHistory, runExample, script.detection]);

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand"><Logo /> Tickbench</div>
        <nav className="nav" aria-label="Views">
          <button aria-current={view === "workspace" ? "page" : undefined} onClick={() => setView("workspace")}>Workspace</button>
          <button aria-current={view === "history" ? "page" : undefined} onClick={() => { refreshHistory(); setView("history"); }}>
            History<span className="count">{history.length || ""}</span>
          </button>
          <button aria-current={view === "compare" ? "page" : undefined} onClick={() => setView("compare")} disabled={compareIds.length < 2}
            title={compareIds.length < 2 ? "Tick two or more runs in History to compare them" : undefined}>
            Compare<span className="count">{compareIds.length >= 2 ? compareIds.length : ""}</span>
          </button>
        </nav>
        <div className="spacer" />
        {update.state === "ready" && (
          <button className="update-pill" onClick={() => bridge.installUpdate()}>
            <span className="dot" /> Version {update.version} is ready, restart to update
          </button>
        )}
        {update.state === "downloading" && <span className="engine-state">Downloading update {update.percent ?? 0}%</span>}
        <span className={`engine-state ${engineDown ? "down" : ""}`} title={engineDown ?? "Backtest engine is running"}>
          <span className="led" /> {engineDown ? "Engine stopped" : "Engine ready"}
        </span>
        <button className="icon-btn" aria-label="Toggle light or dark theme"
          onClick={() => setPrefs({ theme: prefs.theme === "dark" ? "light" : "dark" })}>
          {prefs.theme === "dark" ? <Sun /> : <Moon />}
        </button>
      </header>
      <div className="workspace">
        <Rail
          script={script} setScript={setScript} loadScript={loadScript} overrideKind={overrideKind}
          dataSpec={dataSpec} dataInfo={dataInfo} dataError={dataError} loadData={loadData}
          settings={settings} setSettings={setSettings}
          canRun={canRun} running={running} progress={progress} onRun={() => run()} onCancel={cancel}
        />
        <main className="main">
          <div className="main-scroll">{main}</div>
        </main>
      </div>
      {engineDown && (
        <div className="toast" role="alert">
          <b>The backtest engine isn't running.</b>
          <div style={{ color: "var(--ink-2)", marginTop: 4 }}>{engineDown}</div>
        </div>
      )}
    </div>
  );
}
