import { IChartApi, ISeriesApi, LineData, UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { date, money, pct } from "../format";
import { cssVar, useThemeKey } from "../hooks";
import type { RunResult } from "../types";
import { baseOptions, createChart, syncCharts, toTime } from "./lw";

interface Tip { x: number; y: number; time: number; eq: number; bh: number; dd: number }

/** Strategy equity vs buy-and-hold (one axis, same units) with an underwater drawdown pane below. */
export function EquityChart({ result, height = 300 }: { result: RunResult; height?: number }) {
  const top = useRef<HTMLDivElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const theme = useThemeKey();

  useEffect(() => {
    if (!top.current || !bottom.current) return;
    const t = result.bars.time;
    const eqData: LineData[] = result.equity.map((v, i) => ({ time: toTime(t[i]), value: v }));
    const bhData: LineData[] = result.buyHold.map((v, i) => ({ time: toTime(t[i]), value: v }));
    const ddData = result.drawdownPct.map((v, i) => ({ time: toTime(t[i]), value: v }));

    const chart = createChart(top.current, { ...baseOptions(height, { showTime: false }) });
    const dd = createChart(bottom.current, { ...baseOptions(96) });
    chart.applyOptions({ rightPriceScale: { minimumWidth: 74 } });
    dd.applyOptions({ rightPriceScale: { minimumWidth: 74, scaleMargins: { top: 0.06, bottom: 0.02 } } });

    const bh = chart.addLineSeries({ color: cssVar("--data-bench"), lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerRadius: 4, crosshairMarkerBorderColor: cssVar("--panel"),
      priceFormat: { type: "custom", formatter: (v: number) => money(v, { d: 0 }) } });
    const eq = chart.addLineSeries({ color: cssVar("--data-equity"), lineWidth: 2, priceLineVisible: false,
      crosshairMarkerRadius: 4, crosshairMarkerBorderColor: cssVar("--panel"),
      priceFormat: { type: "custom", formatter: (v: number) => money(v, { d: 0 }) } });
    const ddSeries = dd.addAreaSeries({ lineColor: cssVar("--data-down"), topColor: "rgba(230,103,103,0.05)",
      bottomColor: "rgba(230,103,103,0.32)", lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      invertFilledArea: true,
      priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(0)}%` } } as never) as ISeriesApi<"Area">;
    ddSeries.setData(ddData);
    bh.setData(bhData);

    // results-arrive moment: the equity line draws itself left to right
    let raf = 0;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || eqData.length < 30) {
      eq.setData(eqData);
      chart.timeScale().fitContent();
    } else {
      chart.timeScale().fitContent();
      const t0 = performance.now();
      const step = (now: number) => {
        const p = Math.min(1, (now - t0) / 750);
        const n = Math.max(2, Math.floor(eqData.length * (1 - Math.pow(1 - p, 3))));
        eq.setData(eqData.slice(0, n));
        if (p < 1) raf = requestAnimationFrame(step);
        else chart.timeScale().fitContent();
      };
      raf = requestAnimationFrame(step);
    }
    dd.timeScale().fitContent();
    const unsync = syncCharts(chart, dd);

    const index = new Map<number, number>();
    t.forEach((ms, i) => index.set(toTime(ms), i));
    const onMove = (param: { time?: unknown; point?: { x: number; y: number } }) => {
      if (!param.time || !param.point) { setTip(null); return; }
      const i = index.get(param.time as UTCTimestamp);
      if (i == null) { setTip(null); return; }
      setTip({ x: param.point.x, y: param.point.y, time: t[i], eq: result.equity[i], bh: result.buyHold[i], dd: result.drawdownPct[i] });
    };
    chart.subscribeCrosshairMove(onMove);
    return () => {
      cancelAnimationFrame(raf);
      unsync();
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      dd.remove();
    };
  }, [result, height, theme]);

  const w = top.current?.clientWidth ?? 800;
  return (
    <div className="chart-box">
      <div ref={top} style={{ height }} />
      <div ref={bottom} style={{ height: 96, borderTop: "1px solid var(--line)" }} aria-label="Drawdown from the previous equity high" />
      {tip && (
        <div className="tooltip-float" style={{ left: Math.min(tip.x + 16, w - 200), top: Math.max(4, tip.y - 70) }}>
          <div className="t">{date(tip.time, true)}</div>
          <div className="r"><span style={{ color: "var(--ink-2)" }}><i style={{ display: "inline-block", width: 8, height: 2, background: "var(--data-equity)", marginRight: 6, verticalAlign: "middle" }} />Strategy</span><span>{money(tip.eq, { d: 0 })}</span></div>
          <div className="r"><span style={{ color: "var(--ink-2)" }}><i style={{ display: "inline-block", width: 8, height: 2, background: "var(--data-bench)", marginRight: 6, verticalAlign: "middle" }} />Buy and hold</span><span>{money(tip.bh, { d: 0 })}</span></div>
          <div className="r"><span style={{ color: "var(--ink-2)" }}>Drawdown</span><span>{pct(tip.dd, { d: 1 })}</span></div>
        </div>
      )}
    </div>
  );
}

export type { IChartApi };
