import { IPriceLine, ISeriesApi, LineStyle, SeriesMarker, UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { date, money, num, price } from "../format";
import { cssVar, useThemeKey } from "../hooks";
import type { RunResult, Trade } from "../types";
import { baseOptions, createChart, syncCharts, toTime } from "./lw";

const SERIES_VARS = ["--data-1", "--data-2", "--data-3", "--data-4", "--data-5"];

interface Props {
  result: RunResult;
  focusTrade: Trade | null;
  onPickTrade: (t: Trade) => void;
}

/** Candles + the script's own plots + every entry and exit, with a pane for oscillator plots. */
export function PriceChart({ result, focusTrade, onPickTrade }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const lower = useRef<HTMLDivElement>(null);
  const api = useRef<{ chart: ReturnType<typeof createChart>; candles: ISeriesApi<"Candlestick">; lines: IPriceLine[] } | null>(null);
  const theme = useThemeKey();
  const [showTrades, setShowTrades] = useState(true);
  const [showPlots, setShowPlots] = useState(true);
  const [legend, setLegend] = useState<{ t: number; o: number; h: number; l: number; c: number } | null>(null);
  const overlays = useMemo(() => result.plots.filter((p) => p.overlay), [result]);
  const panes = useMemo(() => result.plots.filter((p) => !p.overlay).slice(0, 4), [result]);
  const tf = result.data.timeframe;
  const intraday = /m$|h$/.test(tf) && tf !== "1mo";

  useEffect(() => {
    if (!host.current) return;
    const b = result.bars;
    const chart = createChart(host.current, baseOptions(430, { timeVisible: intraday }));
    chart.applyOptions({ rightPriceScale: { minimumWidth: 74 } });
    const candles = chart.addCandlestickSeries({
      upColor: cssVar("--candle-up"), downColor: cssVar("--candle-down"), borderVisible: false,
      wickUpColor: cssVar("--candle-up"), wickDownColor: cssVar("--candle-down"), priceLineVisible: false,
    });
    candles.setData(b.time.map((t, i) => ({ time: toTime(t), open: b.open[i], high: b.high[i], low: b.low[i], close: b.close[i] })));

    if (showPlots) {
      overlays.slice(0, 5).forEach((p, k) => {
        const s = chart.addLineSeries({ color: cssVar(SERIES_VARS[k]), lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false, title: p.name });
        s.setData(p.values.flatMap((v, i) => (v == null ? [] : [{ time: toTime(b.time[i]), value: v }])));
      });
    }
    if (showTrades) {
      const up = cssVar("--data-up"), down = cssVar("--data-down");
      const markers: SeriesMarker<UTCTimestamp>[] = [];
      for (const tr of result.trades) {
        markers.push({ time: toTime(tr.entryTime), position: tr.side === "long" ? "belowBar" : "aboveBar",
          shape: tr.side === "long" ? "arrowUp" : "arrowDown", color: tr.side === "long" ? up : down,
          text: result.trades.length <= 25 ? (tr.side === "long" ? "Buy" : "Sell") : "" , id: `e${tr.id}` });
        if (tr.exitTime != null) {
          markers.push({ time: toTime(tr.exitTime), position: tr.side === "long" ? "aboveBar" : "belowBar", shape: "circle",
            color: tr.pnl >= 0 ? up : down, id: `x${tr.id}`,
            text: result.trades.length <= 25 ? `${tr.pnl >= 0 ? "+" : "−"}${num(Math.abs(tr.pnl), 0)}` : "" });
        }
      }
      markers.sort((a, b2) => (a.time as number) - (b2.time as number));
      candles.setMarkers(markers);
    }
    chart.timeScale().fitContent();
    let lowerChart: ReturnType<typeof createChart> | null = null;
    let unsync = () => {};
    if (showPlots && panes.length && lower.current) {
      lowerChart = createChart(lower.current, baseOptions(130, { timeVisible: intraday }));
      lowerChart.applyOptions({ rightPriceScale: { minimumWidth: 74 } });
      panes.forEach((p, k) => {
        const s = lowerChart!.addLineSeries({ color: cssVar(SERIES_VARS[k]), lineWidth: 2, priceLineVisible: false,
          lastValueVisible: true, title: p.name });
        s.setData(p.values.flatMap((v, i) => (v == null ? [] : [{ time: toTime(b.time[i]), value: v }])));
      });
      lowerChart.timeScale().fitContent();
      unsync = syncCharts(chart, lowerChart);
    }
    const idx = new Map<number, number>();
    b.time.forEach((t, i) => idx.set(toTime(t), i));
    chart.subscribeCrosshairMove((param) => {
      const i = param.time != null ? idx.get(param.time as number) : undefined;
      if (i == null) { setLegend(null); return; }
      setLegend({ t: b.time[i], o: b.open[i], h: b.high[i], l: b.low[i], c: b.close[i] });
    });
    chart.subscribeClick((param) => {
      if (!param.time) return;
      const t = (param.time as number) * 1000;
      const tr = result.trades.find((x) => x.entryTime <= t && (x.exitTime ?? Infinity) >= t);
      if (tr) onPickTrade(tr);
    });
    api.current = { chart, candles, lines: [] };
    return () => { unsync(); chart.remove(); lowerChart?.remove(); api.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, theme, showTrades, showPlots]);

  // Zoom to a trade picked in the table and draw its entry / stop / target levels.
  useEffect(() => {
    const a = api.current;
    if (!a) return;
    a.lines.forEach((l) => a.candles.removePriceLine(l));
    a.lines = [];
    if (!focusTrade) return;
    const b = result.bars;
    const pad = Math.max(12, Math.round(((focusTrade.exitBar ?? focusTrade.entryBar) - focusTrade.entryBar) * 0.6));
    const from = Math.max(0, focusTrade.entryBar - pad);
    const to = Math.min(b.time.length - 1, (focusTrade.exitBar ?? focusTrade.entryBar) + pad);
    a.chart.timeScale().setVisibleRange({ from: toTime(b.time[from]), to: toTime(b.time[to]) });
    const mk = (p: number | null, title: string, color: string, style = LineStyle.Dashed) => {
      if (p == null) return;
      a.lines.push(a.candles.createPriceLine({ price: p, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));
    };
    mk(focusTrade.entryPrice, "Entry", cssVar("--ink-2"), LineStyle.Solid);
    mk(focusTrade.sl, "Stop", cssVar("--data-down"));
    mk(focusTrade.tp, "Target", cssVar("--data-up"));
    if (focusTrade.exitPrice != null) mk(focusTrade.exitPrice, "Exit", cssVar("--accent"), LineStyle.Dotted);
  }, [focusTrade, result]);

  const reset = () => api.current?.chart.timeScale().fitContent();
  return (
    <div className="chart-box">
      <div className="chart-toolbar" role="toolbar" aria-label="Chart options">
        <button aria-pressed={showTrades} onClick={() => setShowTrades(!showTrades)}>Trades</button>
        <button aria-pressed={showPlots} onClick={() => setShowPlots(!showPlots)} disabled={!result.plots.length}>
          Script plots{result.plots.length ? ` (${result.plots.length})` : ""}
        </button>
        <span className="sep" />
        <button onClick={reset}>Fit all</button>
      </div>
      <div style={{ position: "absolute", left: 14, top: 12, zIndex: 4, fontSize: 12, color: "var(--ink-2)", pointerEvents: "none" }} className="mono">
        <b style={{ color: "var(--ink)", fontFamily: "var(--font-ui)" }}>{result.data.symbol}</b> {tf}
        {legend && <> {date(legend.t, intraday)}  O {price(legend.o)} H {price(legend.h)} L {price(legend.l)} C {price(legend.c)}</>}
        {focusTrade && !legend && <>  Trade #{focusTrade.id}: {focusTrade.side}, {money(focusTrade.pnl, { sign: true })}</>}
        {showPlots && overlays.length > 0 && (
          <div style={{ display: "flex", gap: 12, marginTop: 4, fontFamily: "var(--font-ui)" }}>
            {overlays.slice(0, 5).map((p, k) => (
              <span key={p.name}><i style={{ display: "inline-block", width: 12, height: 2, background: `var(${SERIES_VARS[k]})`, verticalAlign: "middle", marginRight: 5 }} />{p.name}</span>
            ))}
          </div>
        )}
      </div>
      <div ref={host} style={{ height: 430 }} />
      {showPlots && panes.length > 0 && (
        <div style={{ borderTop: "1px solid var(--line)", position: "relative" }}>
          <div style={{ position: "absolute", left: 14, top: 6, zIndex: 4, fontSize: 12, color: "var(--ink-2)", display: "flex", gap: 12 }}>
            {panes.map((p, k) => (<span key={p.name}><i style={{ display: "inline-block", width: 12, height: 2, background: `var(${SERIES_VARS[k]})`, verticalAlign: "middle", marginRight: 5 }} />{p.name}</span>))}
          </div>
          <div ref={lower} style={{ height: 130 }} />
        </div>
      )}
    </div>
  );
}
