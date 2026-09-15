import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import type { EChartsOption } from "echarts";
import { api, type SessionRow, type Timeline } from "../api";
import { bars, categoryAxis, Chart, grid, INK, KIND_COLOR, SERIES, timeAxis, tooltip, valueAxis } from "../charts/Chart";
import { addDays, fmtDate, fmtDuration, fmtKwh, fmtMiles, fmtMoney, fmtNum, fmtTemp, fmtTime } from "../format";
import { useLatestDay, useVid } from "../hooks/useVehicle";
import { Card, Empty, Fetching, KIND_LABEL, KindDot, Segmented, Stat } from "../components/ui";

type Filter = "all" | "drive" | "charge" | "parked";

function title(s: SessionRow) {
  if (s.kind === "drive") return `${s.start_place ?? "Unknown"} → ${s.end_place ?? "Unknown"}`;
  const at = s.end_place ?? s.start_place;
  if (s.kind === "charge") return `Charging${at ? ` at ${at}` : s.charger === "dc" ? " at a Supercharger" : ""}`;
  if (s.kind === "sleep") return `Asleep${at ? ` at ${at}` : ""}`;
  if (s.kind === "idle") return `Parked${at ? ` at ${at}` : ""}`;
  return "Offline";
}

function Metrics({ s, currency }: { s: SessionRow; currency: string }) {
  const chips: string[] = [];
  if (s.kind === "drive") {
    chips.push(fmtMiles(s.distance_miles), fmtKwh(s.energy_used_kwh, 2));
    if (s.wh_per_mile) chips.push(`${fmtNum(s.wh_per_mile)} Wh/mi`);
    if (s.avg_outside_temp_c != null) chips.push(fmtTemp(s.avg_outside_temp_c));
  } else if (s.kind === "charge") {
    chips.push(`+${fmtKwh(s.energy_added_kwh, 2)}`);
    if (s.max_charger_power) chips.push(`${fmtNum(s.max_charger_power)} kW peak`);
    if (s.cost != null) chips.push(fmtMoney(s.cost, currency));
  } else if (s.start_battery != null && s.end_battery != null) {
    chips.push(`${fmtNum(Math.max(0, s.start_battery - s.end_battery), 1)}% drain`);
  }
  return (
    <div className="mt-1 flex flex-wrap gap-1.5">
      {chips.map((c) => <span key={c} className="rounded-md bg-surface-2 px-1.5 py-0.5 text-xs text-ink-2 num">{c}</span>)}
    </div>
  );
}

export function Today() {
  const vid = useVid();
  const latest = useLatestDay(vid);
  const [params, setParams] = useSearchParams();
  const day = params.get("date") ?? latest;
  const [filter, setFilter] = useState<Filter>("all");
  const q = useQuery({
    queryKey: ["timeline", vid, day], enabled: day != null,
    queryFn: () => api<Timeline>(`/api/v1/vehicles/${vid}/timeline/${day}`),
  });
  const setDay = (d: string) => setParams(d === latest ? {} : { date: d });
  const t = q.data;

  const batteryOption = useMemo<EChartsOption | null>(() => {
    if (!t) return null;
    const start = new Date(`${t.date}T00:00:00`).getTime();
    const end = start + 86_400_000;
    const bands = t.sessions.filter((s) => s.kind !== "idle").map((s) => [
      { xAxis: Math.max(new Date(s.start).getTime(), start), itemStyle: { color: KIND_COLOR[s.kind], opacity: 0.18 } },
      { xAxis: Math.min(s.end ? new Date(s.end).getTime() : Date.now(), end) },
    ]);
    return {
      grid: grid({ top: 12 }), tooltip: tooltip({ valueFormatter: (v: number) => `${fmtNum(v)}%` }),
      xAxis: timeAxis({ min: start, max: end, axisLabel: { color: INK.muted, fontSize: 11, formatter: "{h}:{mm}", hideOverlap: true } }),
      yAxis: valueAxis({ min: 0, max: 100, interval: 25, axisLabel: { color: INK.muted, fontSize: 11, formatter: "{value}%" } }),
      series: [{
        type: "line", name: "Battery", data: t.battery.map((p) => [new Date(p.ts).getTime(), p.battery_level]),
        showSymbol: false, color: "#e6e8eb", lineStyle: { width: 2 }, areaStyle: { color: "#e6e8eb", opacity: 0.05 },
        markArea: { silent: true, data: bands as never },
      }],
    };
  }, [t]);

  const weekOption = useMemo<EChartsOption | null>(() => {
    if (!t) return null;
    return {
      grid: grid({ top: 8 }), tooltip: tooltip({ trigger: "item", valueFormatter: (v: number) => fmtMiles(v) }),
      xAxis: categoryAxis(t.week.map((d) => fmtDate(d.date, { weekday: "short" }))),
      yAxis: valueAxis({ splitNumber: 3 }),
      series: [bars("Miles", SERIES[0], t.week.map((d) => ({ value: Math.round(d.miles * 10) / 10, itemStyle: { color: d.date === t.date ? SERIES[0] : "#3a3f46", borderRadius: [4, 4, 0, 0] } })) as never)],
    };
  }, [t]);

  if (!day || (!t && q.isLoading)) return <div className="card h-[520px] animate-pulse" />;
  if (!t) return <Empty>Could not load this day. {String(q.error ?? "")}</Empty>;

  const sessions = t.sessions.filter((s) => !(s.kind === "drive" && s.flags.includes("short"))).filter((s) =>
    filter === "all" ? true : filter === "parked" ? ["idle", "sleep", "unreachable"].includes(s.kind) : s.kind === filter);
  const x = t.totals;
  const parkedHours = (x.sleep_seconds + x.idle_seconds) / 3600;

  return (
    <Fetching busy={q.isFetching}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{fmtDate(t.date, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</h1>
          <p className="text-sm text-ink-3">{x.drives} drives · {fmtMiles(x.miles)} · {x.charges} charges</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setDay(addDays(t.date, -1))} className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-ink-2 hover:text-ink" aria-label="Previous day">←</button>
          <input type="date" value={t.date} max={latest ?? undefined} onChange={(e) => e.target.value && setDay(e.target.value)}
            className="rounded-full border border-line bg-surface px-3 py-1 text-sm text-ink [color-scheme:dark]" aria-label="Pick a day" />
          <button onClick={() => setDay(addDays(t.date, 1))} disabled={latest != null && t.date >= latest} className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-ink-2 hover:text-ink disabled:opacity-30" aria-label="Next day">→</button>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
        <div className="grid gap-3">
          <Card title="Battery" subtitle="State of charge through the day, shaded by what the car was doing"
            action={<div className="flex flex-wrap gap-3 text-xs text-ink-2">{(["drive", "charge", "sleep"] as const).map((k) => <span key={k} className="inline-flex items-center gap-1.5"><KindDot kind={k} />{KIND_LABEL[k]}</span>)}</div>}>
            {batteryOption && t.battery.length ? <Chart option={batteryOption} height={240} /> : <Empty>No battery readings on this day.</Empty>}
          </Card>

          <Card title="Timeline" action={<Segmented label="Filter sessions" value={filter} onChange={setFilter}
            options={[{ value: "all", label: "All" }, { value: "drive", label: "Drives" }, { value: "charge", label: "Charges" }, { value: "parked", label: "Parked" }]} />}>
            {sessions.length === 0 ? <Empty>Nothing recorded.</Empty> : (
              <ol className="relative">
                {sessions.map((s) => {
                  const body = (
                    <div className="flex gap-3 rounded-xl px-2 py-2.5 transition hover:bg-surface-2">
                      <div className="w-[72px] shrink-0 pt-0.5 text-right text-xs text-ink-3 num">{fmtTime(s.start)}<br />{fmtDuration(s.duration_s)}</div>
                      <div className="relative flex flex-col items-center">
                        <span className="mt-1.5 h-3 w-3 rounded-full ring-4 ring-surface" style={{ background: KIND_COLOR[s.kind] }} />
                        <span className="w-px flex-1 bg-line" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-ink">{title(s)}</div>
                        <div className="text-xs text-ink-3 num">{s.start_battery != null ? `${fmtNum(s.start_battery)}% → ${fmtNum(s.end_battery)}%` : ""}</div>
                        <Metrics s={s} currency={t.currency} />
                      </div>
                      {(s.kind === "drive" || s.kind === "charge") && <span className="self-center text-ink-3" aria-hidden>›</span>}
                    </div>
                  );
                  return <li key={s.id}>{s.kind === "drive" || s.kind === "charge" ? <Link to={`/session/${s.id}`}>{body}</Link> : body}</li>;
                })}
              </ol>
            )}
          </Card>
        </div>

        <div className="grid content-start gap-3">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Distance" value={fmtMiles(x.miles)} sub={`${x.drives} drives · ${fmtDuration(x.drive_seconds)}`} accent={KIND_COLOR.drive} />
            <Stat label="Energy used" value={fmtKwh(x.kwh_used)} sub={x.wh_per_mile ? `${fmtNum(x.wh_per_mile)} Wh/mi` : "–"} accent={KIND_COLOR.drive} />
            <Stat label="Charged" value={fmtKwh(x.kwh_added)} sub={`${x.charges} sessions · ${fmtMoney(x.charge_cost, t.currency)}`} accent={KIND_COLOR.charge} />
            <Stat label="Parked" value={`${fmtNum(parkedHours, 1)} h`} sub={`${fmtNum(x.parked_drain_pct, 1)}% drain`} accent={KIND_COLOR.sleep} />
          </div>
          <Card title="This week" subtitle="Miles per day; tap a bar to open that day">
            {weekOption && <Chart option={weekOption} height={150} onClick={(p) => setDay(t.week[p.dataIndex].date)} />}
          </Card>
          <Card title="Conditions">
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-ink-3">Avg outside on drives</dt><dd className="text-right num">{fmtTemp(x.avg_outside_temp_c)}</dd>
              <dt className="text-ink-3">Sleeping</dt><dd className="text-right num">{fmtNum(x.sleep_seconds / 3600, 1)} h</dd>
              <dt className="text-ink-3">Awake, parked</dt><dd className="text-right num">{fmtNum(x.idle_seconds / 3600, 1)} h</dd>
            </dl>
          </Card>
        </div>
      </div>
    </Fetching>
  );
}
