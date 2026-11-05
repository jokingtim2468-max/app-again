import { BarChart, ScatterChart } from "echarts/charts";
import { GridComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import { money, num } from "../format";
import { cssVar, useThemeKey } from "../hooks";
import type { Trade } from "../types";

echarts.use([BarChart, ScatterChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer]);

function useEChart(build: () => echarts.EChartsCoreOption, deps: unknown[]) {
  const el = useRef<HTMLDivElement>(null);
  const theme = useThemeKey();
  useEffect(() => {
    if (!el.current) return;
    const c = echarts.init(el.current, undefined, { renderer: "canvas" });
    c.setOption(build());
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el.current);
    return () => { ro.disconnect(); c.dispose(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, theme]);
  return el;
}

const axisStyle = () => ({
  axisLine: { show: false }, axisTick: { show: false },
  axisLabel: { color: cssVar("--data-axis"), fontFamily: "JetBrains Mono", fontSize: 10.5 },
  splitLine: { lineStyle: { color: cssVar("--data-grid") } },
});

const tooltipStyle = () => ({
  backgroundColor: cssVar("--glass-solid"), borderColor: cssVar("--line-strong"), borderWidth: 1,
  textStyle: { color: cssVar("--ink"), fontFamily: "IBM Plex Sans", fontSize: 12 }, padding: [8, 10],
  extraCssText: "border-radius:8px; box-shadow: 0 18px 40px -16px rgba(0,0,0,.6);",
});

/** Histogram of closed-trade P&L: bins left of zero are losses, right are wins (sign + colour). */
export function PnlHistogram({ trades }: { trades: Trade[] }) {
  const el = useEChart(() => {
    const pnls = trades.filter((t) => t.exitBar != null).map((t) => t.pnl);
    if (!pnls.length) return {};
    const lo = Math.min(...pnls, 0), hi = Math.max(...pnls, 0);
    const bins = Math.min(28, Math.max(8, Math.round(Math.sqrt(pnls.length) * 2)));
    const w = (hi - lo) / bins || 1;
    const counts = new Array(bins).fill(0);
    pnls.forEach((p) => { counts[Math.min(bins - 1, Math.floor((p - lo) / w))]++; });
    const up = cssVar("--data-up"), down = cssVar("--data-down");
    return {
      grid: { left: 36, right: 10, top: 12, bottom: 30 },
      tooltip: { ...tooltipStyle(), trigger: "item",
        formatter: (p: { dataIndex: number; value: number }) => `${money(lo + p.dataIndex * w, { sign: true })} to ${money(lo + (p.dataIndex + 1) * w, { sign: true })}<br/><b>${p.value}</b> trade${p.value === 1 ? "" : "s"}` },
      xAxis: { type: "category", data: counts.map((_, i) => lo + (i + 0.5) * w), ...axisStyle(), splitLine: { show: false },
        axisLabel: { ...axisStyle().axisLabel, interval: Math.ceil(bins / 6) - 1, formatter: (v: string) => money(+v, { sign: true, d: 0 }) } },
      yAxis: { type: "value", minInterval: 1, ...axisStyle() },
      series: [{
        type: "bar", barCategoryGap: 2, data: counts.map((c, i) => ({
          value: c, itemStyle: { color: lo + (i + 0.5) * w >= 0 ? up : down, borderRadius: [4, 4, 0, 0] },
        })),
      }],
    };
  }, [trades]);
  return <div ref={el} style={{ height: 210 }} role="img" aria-label="Histogram of trade profit and loss" />;
}

/** Maximum adverse vs favourable excursion per trade, in price points. Winners ▲, losers ▼. */
export function ExcursionScatter({ trades }: { trades: Trade[] }) {
  const el = useEChart(() => {
    const closed = trades.filter((t) => t.exitBar != null).slice(0, 4000);
    const up = cssVar("--data-up"), down = cssVar("--data-down");
    const mk = (win: boolean) => closed.filter((t) => (t.pnl > 0) === win).map((t) => ({ value: [t.mae, t.mfe], t }));
    return {
      grid: { left: 46, right: 12, top: 12, bottom: 34 },
      tooltip: { ...tooltipStyle(), trigger: "item",
        formatter: (p: { data: { t: Trade } }) => `Trade #${p.data.t.id} (${p.data.t.side})<br/>Worst against: ${num(p.data.t.mae)} pts<br/>Best in favour: ${num(p.data.t.mfe)} pts<br/>Result: <b>${money(p.data.t.pnl, { sign: true })}</b>` },
      xAxis: { type: "value", name: "Worst move against (pts)", nameLocation: "middle", nameGap: 22, nameTextStyle: { color: cssVar("--ink-3"), fontSize: 11 }, ...axisStyle() },
      yAxis: { type: "value", ...axisStyle() },
      series: [
        { name: "Winners", type: "scatter", symbol: "triangle", symbolSize: 8, data: mk(true), itemStyle: { color: up, borderColor: cssVar("--panel"), borderWidth: 1 } },
        { name: "Losers", type: "scatter", symbol: "path://M0,0 L10,0 L5,8 Z", symbolSize: 8, data: mk(false), itemStyle: { color: down, borderColor: cssVar("--panel"), borderWidth: 1 } },
      ],
    };
  }, [trades]);
  return <div ref={el} style={{ height: 210 }} role="img" aria-label="Scatter of each trade's worst adverse move versus best favourable move" />;
}
