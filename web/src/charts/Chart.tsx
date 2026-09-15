import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import { GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";

echarts.use([LineChart, BarChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, MarkAreaComponent,
  MarkLineComponent, SVGRenderer]);

/** Dark chart ink and the validated categorical steps (dataviz reference palette, dark column). */
export const INK = { primary: "#f4f5f7", secondary: "#b4b8bf", muted: "#898781", grid: "rgba(255,255,255,0.07)", axis: "rgba(255,255,255,0.18)", surface: "#15171a" };
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
export const KIND_COLOR: Record<string, string> = { drive: "#3987e5", charge: "#199e70", sleep: "#9085e9", unreachable: "#d95926", idle: "#4a4f57" };

export const tooltip = (extra: object = {}) => ({
  trigger: "axis" as const, confine: true, backgroundColor: "#1c1f23", borderColor: "rgba(255,255,255,0.1)",
  textStyle: { color: INK.primary, fontSize: 12 }, axisPointer: { type: "line" as const, lineStyle: { color: INK.axis, width: 1 } },
  ...extra,
});

export const grid = (extra: object = {}) => ({ left: 8, right: 16, top: 16, bottom: 8, containLabel: true, ...extra });

export const valueAxis = (extra: object = {}) => ({
  type: "value" as const, splitLine: { lineStyle: { color: INK.grid, width: 1 } },
  axisLabel: { color: INK.muted, fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false }, ...extra,
});

export const timeAxis = (extra: object = {}) => ({
  type: "time" as const, splitLine: { show: false }, axisLine: { lineStyle: { color: INK.axis } },
  axisTick: { show: false }, axisLabel: { color: INK.muted, fontSize: 11, hideOverlap: true }, ...extra,
});

export const categoryAxis = (data: string[], extra: object = {}) => ({
  type: "category" as const, data, axisLine: { lineStyle: { color: INK.axis } }, axisTick: { show: false },
  axisLabel: { color: INK.muted, fontSize: 11, hideOverlap: true }, ...extra,
});

export const legend = (extra: object = {}) => ({ top: 0, right: 0, icon: "roundRect", itemWidth: 12, itemHeight: 4, textStyle: { color: INK.secondary, fontSize: 12 }, ...extra });

export const line = (name: string, color: string, data: [number, number | null][], extra: object = {}) => ({
  type: "line" as const, name, data, showSymbol: false, symbolSize: 8, connectNulls: false, color,
  lineStyle: { width: 2, cap: "round" as const, join: "round" as const }, emphasis: { disabled: true }, ...extra,
});

export const bars = (name: string, color: string, data: (number | null)[], extra: object = {}) => ({
  type: "bar" as const, name, data, color, barMaxWidth: 24, itemStyle: { borderRadius: [4, 4, 0, 0] }, ...extra,
});

type ClickParams = { dataIndex: number; seriesName?: string };

export function Chart({ option, height = 240, group, onClick }: { option: EChartsOption; height?: number; group?: string; onClick?: (p: ClickParams) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const click = useRef(onClick);
  click.current = onClick;

  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, undefined, { renderer: "svg" });
    chart.current = c;
    c.on("click", (p) => click.current?.(p as unknown as ClickParams));
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); c.dispose(); chart.current = null; };
  }, []);

  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    c.setOption({ animationDuration: 400, textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif" }, ...option }, { notMerge: true, lazyUpdate: true });
    if (group) { c.group = group; echarts.connect(group); }
  }, [option, group]);

  return <div ref={ref} className="min-w-0 overflow-hidden" style={{ height, width: "100%" }} />;
}
