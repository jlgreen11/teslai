import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import type { EChartsOption } from "echarts";
import { api, type SamplePoint, type SessionDetail as Detail } from "../api";
import { Chart, grid, legend, line, SERIES, timeAxis, tooltip, valueAxis } from "../charts/Chart";
import { RouteMap } from "../components/RouteMap";
import { Card, Empty, Fetching, KIND_LABEL, KindDot, NavButton, Stat } from "../components/ui";
import { cToF, fmtDate, fmtDuration, fmtKwh, fmtMiles, fmtMoney, fmtNum, fmtTemp, fmtTime } from "../format";
import { useVid } from "../hooks/useVehicle";

type Key = keyof SamplePoint;

function series(samples: SamplePoint[], key: Key, map: (v: number) => number = (v) => v): [number, number | null][] {
  return samples.map((p) => [new Date(p.ts).getTime(), p[key] == null ? null : Math.round(map(p[key] as number) * 10) / 10]);
}

function chart(name: string, unit: string, data: [number, number | null][], extra: object = {}): EChartsOption {
  return {
    grid: grid(), tooltip: tooltip({ valueFormatter: (v: number) => (v == null ? "–" : `${fmtNum(v, 1)} ${unit}`) }),
    xAxis: timeAxis(), yAxis: valueAxis({ scale: true }),
    series: [line(name, SERIES[0], data, { areaStyle: { opacity: 0.1 } })], ...extra,
  };
}

export function SessionDetail() {
  const vid = useVid();
  const { id } = useParams();
  const q = useQuery({ queryKey: ["session", vid, id], queryFn: () => api<Detail>(`/api/v1/vehicles/${vid}/session/${id}`) });
  const d = q.data;

  const charts = useMemo(() => {
    if (!d) return [];
    const s = d.samples;
    if (d.session.kind === "drive") {
      return [
        { title: "Speed", option: chart("Speed", "mph", series(s, "speed")) },
        { title: "Battery", option: chart("Battery", "%", series(s, "battery_level")) },
        { title: "Power", option: chart("Power", "kW", series(s, "power")) },
        { title: "Temperature", option: {
          grid: grid({ top: 28 }), legend: legend(), tooltip: tooltip({ valueFormatter: (v: number) => (v == null ? "–" : `${fmtNum(v)}°F`) }),
          xAxis: timeAxis(), yAxis: valueAxis({ scale: true }),
          series: [line("Outside", SERIES[0], series(s, "outside_temp_c", (c) => cToF(c)!)), line("Cabin", SERIES[1], series(s, "inside_temp_c", (c) => cToF(c)!))],
        } as EChartsOption },
      ];
    }
    return [
      { title: "Charger power", option: chart("Charger power", "kW", series(s, "charger_power")) },
      { title: "Battery", option: chart("Battery", "%", series(s, "battery_level")) },
      { title: "Energy added", option: chart("Energy added", "kWh", series(s, "charge_energy_added")) },
      { title: "Rated range", option: chart("Rated range", "mi", series(s, "rated_range")) },
    ];
  }, [d]);

  const route = useMemo(() => (d ? [d.samples.filter((p) => p.lat != null && p.lon != null).map((p) => [p.lon!, p.lat!] as [number, number])] : []), [d]);

  if (q.isLoading) return <div className="card h-[600px] animate-pulse" />;
  if (!d) return <Empty>Session not found.</Empty>;
  const s = d.session;
  const drive = s.kind === "drive";
  const base = drive ? "/drives" : "/charges";

  return (
    <Fetching busy={q.isFetching}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to={base} className="text-sm text-ink-3 hover:text-ink">← {drive ? "Drives" : "Charges"}</Link>
          <h1 className="mt-1 flex items-center gap-2 text-2xl font-semibold tracking-tight"><KindDot kind={s.kind} />
            {drive ? `${s.start_place ?? "Unknown"} → ${s.end_place ?? "Unknown"}` : `${KIND_LABEL[s.kind]} at ${s.end_place ?? s.start_place ?? (s.charger === "dc" ? "a Supercharger" : "an unnamed location")}`}
          </h1>
          <p className="text-sm text-ink-3">{fmtDate(s.start, { weekday: "long", month: "long", day: "numeric", year: "numeric" })} · {fmtTime(s.start)} – {fmtTime(s.end)} · {fmtDuration(s.duration_s)}</p>
        </div>
        <div className="flex gap-2">
          <NavButton to={`/session/${d.prev_id}`} disabled={!d.prev_id}>← Previous</NavButton>
          <NavButton to={`/session/${d.next_id}`} disabled={!d.next_id}>Next →</NavButton>
        </div>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {drive ? <>
          <Stat label="Distance" value={fmtMiles(s.distance_miles)} sub={`odometer ${fmtNum(s.end_odometer)} mi`} />
          <Stat label="Energy used" value={fmtKwh(s.energy_used_kwh, 2)} sub={`${fmtNum(s.rated_miles_used, 1)} rated mi`} />
          <Stat label="Consumption" value={s.wh_per_mile ? `${fmtNum(s.wh_per_mile)} Wh/mi` : "–"} sub={s.efficiency_pct ? `${fmtNum(s.efficiency_pct)}% of rated` : undefined} />
          <Stat label="Battery" value={`${fmtNum(s.start_battery)}% → ${fmtNum(s.end_battery)}%`} sub={s.start_battery != null && s.end_battery != null ? `${fmtNum(s.start_battery - s.end_battery)}% used` : undefined} />
          <Stat label="Speed" value={`${fmtNum(s.avg_speed)} mph`} sub={`max ${fmtNum(s.max_speed)} mph`} />
          <Stat label="Cost" value={fmtMoney(s.energy_cost)} sub={s.gas_savings != null ? `${fmtMoney(s.gas_savings)} saved vs gas` : `outside ${fmtTemp(s.avg_outside_temp_c)}`} />
        </> : <>
          <Stat label="Energy added" value={fmtKwh(s.energy_added_kwh, 2)} />
          <Stat label="Battery" value={`${fmtNum(s.start_battery)}% → ${fmtNum(s.end_battery)}%`} />
          <Stat label="Peak power" value={`${fmtNum(s.max_charger_power)} kW`} sub={s.charger === "dc" ? "DC fast charging" : "AC charging"} />
          <Stat label="Duration" value={fmtDuration(s.duration_s)} />
          <Stat label="Cost" value={fmtMoney(s.cost)} sub={s.cost_source === "invoice" ? "from Tesla invoice" : "estimate from tariffs"} />
          <Stat label="Outside" value={fmtTemp(s.avg_outside_temp_c)} />
        </>}
      </div>

      {drive && route[0].length > 1 && <Card pad={false} className="mb-3 overflow-hidden"><RouteMap lines={route} endpoints height={380} /></Card>}

      {d.samples.length < 2 ? <Empty>No time series was recorded for this session.</Empty> : (
        <div className="grid gap-3 md:grid-cols-2">
          {charts.map((c) => <Card key={c.title} title={c.title}><Chart option={c.option} height={200} group={`session-${s.id}`} /></Card>)}
        </div>
      )}
    </Fetching>
  );
}
