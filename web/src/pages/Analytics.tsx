import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { api, type BatteryReport, type Efficiency, type MapData, type Tires } from "../api";
import { bars, categoryAxis, Chart, grid, INK, legend, line, SERIES, timeAxis, tooltip, valueAxis } from "../charts/Chart";
import { RouteMap } from "../components/RouteMap";
import { Card, Empty, Fetching, PageTitle, Stat, TableView, td, th } from "../components/ui";
import { barToPsi, cToF, fmtDate, fmtMiles, fmtNum } from "../format";
import { useRange, useStatus, useVid } from "../hooks/useVehicle";
import { RangePicker } from "./Sessions";

export function Battery() {
  const vid = useVid();
  const q = useQuery({ queryKey: ["battery", vid], queryFn: () => api<BatteryReport>(`/api/v1/vehicles/${vid}/battery`) });
  const option = useMemo<EChartsOption | null>(() => {
    if (!q.data?.points.length) return null;
    return {
      grid: grid({ top: 32 }), legend: legend(), tooltip: tooltip({ trigger: "item", valueFormatter: (v: number) => fmtMiles(v, 1) }),
      xAxis: timeAxis(), yAxis: valueAxis({ scale: true, axisLabel: { color: INK.muted, fontSize: 11, formatter: "{value} mi" } }),
      series: [
        { type: "scatter", name: "Estimated 100% range, per charge", color: SERIES[0], symbolSize: 8, itemStyle: { borderColor: INK.surface, borderWidth: 2, opacity: 0.85 },
          data: q.data.points.map((p) => [new Date(`${p.date}T12:00:00`).getTime(), p.est_100_range]) },
        line("Monthly median", SERIES[1], q.data.months.map((mm) => [new Date(`${mm.month}-15T12:00:00`).getTime(), mm.median_est_100_range]), { showSymbol: true, symbolSize: 8, itemStyle: { borderColor: INK.surface, borderWidth: 2 } }),
      ],
    } as EChartsOption;
  }, [q.data]);
  const r = q.data;
  return (
    <div>
      <PageTitle title="Battery health" />
      {!r ? <div className="card h-96 animate-pulse" /> : !option ? <Empty>No charges ending above 50% with a rated range yet.</Empty> : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Range at 100%, when new" value={fmtMiles(r.baseline, 0)} sub="best of the first 90 days" />
            <Stat label="Range at 100%, now" value={fmtMiles(r.current, 0)} sub="median of the last 5 charges" />
            <Stat label="Degradation" value={r.loss_pct == null ? "–" : `${fmtNum(r.loss_pct, 1)}%`} sub={r.baseline && r.current ? `${fmtNum(r.baseline - r.current, 1)} miles lost` : undefined} />
            <Stat label="Charges measured" value={fmtNum(r.points.length)} sub={`highest ${fmtMiles(r.max_estimate, 0)}`} />
          </div>
          <Card title="Estimated full-charge range" subtitle="Rated range at the end of each charge, scaled to 100%">
            <Chart option={option} height={320} />
            <TableView>
              <table className="w-full text-sm"><thead className="border-b border-line"><tr><th className={th}>Month</th><th className={th}>Median 100% range</th><th className={th}>Charges</th></tr></thead>
                <tbody>{r.months.map((mm) => <tr key={mm.month} className="border-b border-line/60"><td className={td}>{fmtDate(`${mm.month}-15`, { month: "short", year: "numeric" })}</td><td className={td}>{fmtMiles(mm.median_est_100_range)}</td><td className={td}>{mm.charges}</td></tr>)}</tbody></table>
            </TableView>
          </Card>
        </>
      )}
    </div>
  );
}

function bucketChart(labels: string[], values: number[], rows: { drives: number; miles: number }[]): EChartsOption {
  return {
    grid: grid(), xAxis: categoryAxis(labels), yAxis: valueAxis({ scale: false, axisLabel: { color: INK.muted, fontSize: 11, formatter: "{value}" } }),
    tooltip: tooltip({ trigger: "item", formatter: (p: { dataIndex: number; value: number; name: string }) => `${p.name}<br/><b>${fmtNum(p.value)} Wh/mi</b><br/>${rows[p.dataIndex].drives} drives · ${fmtMiles(rows[p.dataIndex].miles, 0)}` }),
    series: [bars("Wh/mi", SERIES[0], values)],
  } as EChartsOption;
}

export function EfficiencyPage() {
  const vid = useVid();
  const { days, start, end, setDays, ready } = useRange(vid, 365);
  const q = useQuery({ queryKey: ["efficiency", vid, start, end], enabled: ready, queryFn: () => api<Efficiency>(`/api/v1/vehicles/${vid}/efficiency?start=${start}&end=${end}`) });
  const e = q.data;
  return (
    <div>
      <PageTitle title="Efficiency"><RangePicker days={days} setDays={setDays} /></PageTitle>
      {!e ? <div className="card h-96 animate-pulse" /> : (
        <Fetching busy={q.isFetching}>
          <div className="grid gap-3 lg:grid-cols-2">
            <Card title="Consumption by outside temperature" subtitle="Wh per mile, all drives of a mile or more">
              {e.temperature.length ? <>
                <Chart option={bucketChart(e.temperature.map((b) => `${b.temp_f}–${b.temp_f_to}°F`), e.temperature.map((b) => b.wh_per_mile), e.temperature)} height={260} />
                <TableView><table className="w-full text-sm"><thead className="border-b border-line"><tr><th className={th}>Outside</th><th className={th}>Wh/mi</th><th className={th}>Drives</th><th className={th}>Miles</th></tr></thead>
                  <tbody>{e.temperature.map((b) => <tr key={b.temp_f} className="border-b border-line/60"><td className={td}>{b.temp_f}–{b.temp_f_to}°F</td><td className={td}>{fmtNum(b.wh_per_mile)}</td><td className={td}>{b.drives}</td><td className={td}>{fmtNum(b.miles)}</td></tr>)}</tbody></table></TableView>
              </> : <Empty>No drives with temperature readings.</Empty>}
            </Card>
            <Card title="Consumption by average speed" subtitle="Wh per mile; faster drives use more energy per mile">
              {e.speed.length ? <>
                <Chart option={bucketChart(e.speed.map((b) => `${b.speed_mph}–${b.speed_mph_to}`), e.speed.map((b) => b.wh_per_mile), e.speed)} height={260} />
                <TableView><table className="w-full text-sm"><thead className="border-b border-line"><tr><th className={th}>Avg speed (mph)</th><th className={th}>Wh/mi</th><th className={th}>Drives</th><th className={th}>Miles</th></tr></thead>
                  <tbody>{e.speed.map((b) => <tr key={b.speed_mph} className="border-b border-line/60"><td className={td}>{b.speed_mph}–{b.speed_mph_to}</td><td className={td}>{fmtNum(b.wh_per_mile)}</td><td className={td}>{b.drives}</td><td className={td}>{fmtNum(b.miles)}</td></tr>)}</tbody></table></TableView>
              </> : <Empty>No drives with speed readings.</Empty>}
            </Card>
          </div>
        </Fetching>
      )}
    </div>
  );
}

const TIRES = [["fl", "Front left"], ["fr", "Front right"], ["rl", "Rear left"], ["rr", "Rear right"]] as const;

export function TiresPage() {
  const vid = useVid();
  const { days, start, end, setDays, ready } = useRange(vid, 90);
  const status = useStatus(vid).data;
  const q = useQuery({ queryKey: ["tires", vid, start, end], enabled: ready, queryFn: () => api<Tires>(`/api/v1/vehicles/${vid}/tires?start=${start}&end=${end}`) });
  const options = useMemo(() => {
    if (!q.data?.days.length) return null;
    const x = (d: string) => new Date(`${d}T12:00:00`).getTime();
    const psi: EChartsOption = {
      grid: grid({ top: 32 }), legend: legend(), tooltip: tooltip({ valueFormatter: (v: number) => `${fmtNum(v, 1)} psi` }),
      xAxis: timeAxis(), yAxis: valueAxis({ scale: true, axisLabel: { color: INK.muted, fontSize: 11, formatter: "{value} psi" } }),
      series: TIRES.map(([k, label], i) => line(label, SERIES[i], q.data!.days.map((d) => [x(d.date), d[k] == null ? null : Math.round(barToPsi(d[k])! * 10) / 10]))),
    } as EChartsOption;
    const temp: EChartsOption = {
      grid: grid(), tooltip: tooltip({ valueFormatter: (v: number) => `${fmtNum(v)}°F` }), xAxis: timeAxis(),
      yAxis: valueAxis({ scale: true, axisLabel: { color: INK.muted, fontSize: 11, formatter: "{value}°F" } }),
      series: [line("Outside temperature", SERIES[0], q.data!.days.map((d) => [x(d.date), d.outside_temp == null ? null : Math.round(cToF(d.outside_temp)!)]))],
    } as EChartsOption;
    return { psi, temp };
  }, [q.data]);
  return (
    <div>
      <PageTitle title="Tire pressure"><RangePicker days={days} setDays={setDays} /></PageTitle>
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        {TIRES.map(([k, label]) => {
          const v = barToPsi(status?.tpms[k]);
          const low = v != null && v < 38;
          return <Stat key={k} label={label} value={v == null ? "–" : `${fmtNum(v)} psi`} sub={low ? "⚠ Low, check this tire" : "latest reading"} accent={low ? "var(--color-critical)" : undefined} />;
        })}
      </div>
      {!q.data ? <div className="card h-96 animate-pulse" /> : !options ? <Empty>No tire pressure readings in this range.</Empty> : (
        <Fetching busy={q.isFetching}>
          <Card title="Daily average pressure" className="mb-3"><Chart option={options.psi} height={300} group="tires" /></Card>
          <Card title="Outside temperature" subtitle="Pressure drops about 1 psi for every 10°F colder"><Chart option={options.temp} height={160} group="tires" /></Card>
        </Fetching>
      )}
    </div>
  );
}

export function MapPage() {
  const vid = useVid();
  const { days, start, end, setDays, ready } = useRange(vid, 365);
  const q = useQuery({ queryKey: ["map", vid, start, end], enabled: ready, queryFn: () => api<MapData>(`/api/v1/vehicles/${vid}/map?start=${start}&end=${end}`) });
  const lines = useMemo(() => q.data?.tracks.map((t) => t.points) ?? [], [q.data]);
  const places = useMemo(() => q.data?.places ?? [], [q.data]);
  return (
    <div>
      <PageTitle title="Lifetime map"><span className="text-sm text-ink-3">{q.data ? `${fmtNum(q.data.tracks.length)} drives` : ""}</span><RangePicker days={days} setDays={setDays} /></PageTitle>
      <Card pad={false} className="overflow-hidden">
        {q.data ? <RouteMap lines={lines} places={places} height="72vh" opacity={0.55} /> : <div className="h-[72vh] animate-pulse" />}
      </Card>
    </div>
  );
}
