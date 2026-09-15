import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import type { EChartsOption } from "echarts";
import { api, type CalendarMonth, type CalendarYear } from "../api";
import { bars, categoryAxis, Chart, grid, SERIES, tooltip, valueAxis } from "../charts/Chart";
import { Card, Fetching, PageTitle, Segmented, Stat, TableView, td, th } from "../components/ui";
import { fmtDate, fmtKwh, fmtMiles, fmtMoney, fmtNum, fmtTemp } from "../format";
import { useLatestDay, useVid } from "../hooks/useVehicle";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function shiftMonth(ym: string, n: number) {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function MonthView({ vid, ym, latest }: { vid: number; ym: string; latest: string }) {
  const [y, m] = ym.split("-").map(Number);
  const q = useQuery({ queryKey: ["calendar", vid, ym], queryFn: () => api<CalendarMonth>(`/api/v1/vehicles/${vid}/calendar/${y}/${m}`) });
  if (!q.data) return <div className="card h-[560px] animate-pulse" />;
  const { days, summary } = q.data;
  const lead = new Date(`${days[0].date}T12:00:00`).getDay();
  const maxMiles = Math.max(1, ...days.map((d) => d.miles));
  return (
    <Fetching busy={q.isFetching}>
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Distance" value={fmtMiles(summary.miles, 0)} sub={`${summary.drives} drives on ${summary.days_driven} days`} />
        <Stat label="Energy used" value={fmtKwh(summary.kwh_used, 0)} sub={summary.wh_per_mile ? `${fmtNum(summary.wh_per_mile)} Wh/mi` : "–"} />
        <Stat label="Charged" value={fmtKwh(summary.kwh_added, 0)} sub={`${summary.charges} sessions`} />
        <Stat label="Charging cost" value={fmtMoney(summary.charge_cost)} sub={summary.avg_outside_temp_c != null ? `avg ${fmtTemp(summary.avg_outside_temp_c)} while driving` : undefined} />
      </div>
      <Card>
        <div className="grid grid-cols-7 gap-1.5">
          {WEEKDAYS.map((w) => <div key={w} className="pb-1 text-center text-xs text-ink-3">{w}</div>)}
          {Array.from({ length: lead }).map((_, i) => <div key={`b${i}`} />)}
          {days.map((d) => {
            const future = d.date > latest;
            const wash = d.miles ? 0.06 + 0.34 * (d.miles / maxMiles) : 0;
            return (
              <Link key={d.date} to={future ? "#" : `/?date=${d.date}`} aria-disabled={future}
                className={`group relative min-h-[64px] rounded-xl border border-line p-1.5 transition sm:min-h-[104px] sm:p-2 ${future ? "pointer-events-none opacity-30" : "hover:border-ink-3"}`}
                style={{ background: wash ? `rgba(57,135,229,${wash.toFixed(2)})` : "var(--color-surface-2)" }}>
                <div className="flex items-baseline justify-between">
                  <span className="text-xs font-medium text-ink-2">{Number(d.date.slice(8))}</span>
                  {d.charges > 0 && <span className="h-1.5 w-1.5 rounded-full bg-charge" title={`${d.charges} charges`} />}
                </div>
                {d.drives > 0 && <div className="mt-1 text-sm font-semibold leading-tight text-ink sm:text-base">{fmtNum(d.miles, 0)}<span className="text-xs font-normal text-ink-2"> mi</span></div>}
                <div className="hidden text-[11px] leading-snug text-ink-2 sm:block num">
                  {d.drives > 0 && <div>{d.drives} drives{d.wh_per_mile ? ` · ${fmtNum(d.wh_per_mile)} Wh/mi` : ""}</div>}
                  {d.kwh_added > 0 && <div>+{fmtNum(d.kwh_added, 1)} kWh{d.charge_cost ? ` · ${fmtMoney(d.charge_cost)}` : ""}</div>}
                  {d.avg_outside_temp_c != null && <div>{fmtTemp(d.avg_outside_temp_c)}</div>}
                </div>
              </Link>
            );
          })}
        </div>
        <p className="mt-3 text-xs text-ink-3">Deeper blue means more miles. A green dot marks a day with charging.</p>
      </Card>
    </Fetching>
  );
}

function YearView({ vid, year }: { vid: number; year: number }) {
  const q = useQuery({ queryKey: ["calendar-year", vid, year], queryFn: () => api<CalendarYear>(`/api/v1/vehicles/${vid}/calendar/${year}`) });
  const option = useMemo<EChartsOption | null>(() => {
    if (!q.data) return null;
    const months = Array.from({ length: 12 }, (_, i) => `${year}-${String(i + 1).padStart(2, "0")}`);
    const by = new Map(q.data.months.map((mm) => [mm.month, mm]));
    return {
      grid: grid(), tooltip: tooltip({ valueFormatter: (v: number) => fmtMiles(v, 0) }),
      xAxis: categoryAxis(months.map((mm) => fmtDate(`${mm}-15`, { month: "short" }))), yAxis: valueAxis(),
      series: [bars("Miles", SERIES[0], months.map((mm) => (by.has(mm) ? Math.round(by.get(mm)!.miles) : null)))],
    };
  }, [q.data, year]);
  if (!q.data || !option) return <div className="card h-96 animate-pulse" />;
  const tot = q.data.months.reduce((a, mm) => ({ miles: a.miles + mm.miles, kwh: a.kwh + mm.kwh_used, added: a.added + mm.kwh_added, cost: a.cost + mm.charge_cost, drives: a.drives + mm.drives }), { miles: 0, kwh: 0, added: 0, cost: 0, drives: 0 });
  return (
    <Fetching busy={q.isFetching}>
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Distance" value={fmtMiles(tot.miles, 0)} sub={`${fmtNum(tot.drives)} drives`} />
        <Stat label="Energy used" value={fmtKwh(tot.kwh, 0)} sub={tot.miles ? `${fmtNum((tot.kwh * 1000) / tot.miles)} Wh/mi` : "–"} />
        <Stat label="Charged" value={fmtKwh(tot.added, 0)} />
        <Stat label="Charging cost" value={fmtMoney(tot.cost)} />
      </div>
      <Card title={`Miles per month, ${year}`}>
        <Chart option={option} height={260} />
        <TableView>
          <table className="w-full text-sm">
            <thead className="border-b border-line"><tr><th className={th}>Month</th><th className={th}>Drives</th><th className={th}>Miles</th><th className={th}>kWh used</th><th className={th}>Wh/mi</th><th className={th}>kWh added</th><th className={th}>Cost</th><th className={th}>Avg temp</th></tr></thead>
            <tbody>{q.data.months.map((mm) => (
              <tr key={mm.month} className="border-b border-line/60">
                <td className={td}><Link className="text-ink hover:underline" to={`/calendar?m=${mm.month}`}>{fmtDate(`${mm.month}-15`, { month: "long" })}</Link></td>
                <td className={td}>{mm.drives}</td><td className={td}>{fmtNum(mm.miles)}</td><td className={td}>{fmtNum(mm.kwh_used, 1)}</td>
                <td className={td}>{fmtNum(mm.wh_per_mile)}</td><td className={td}>{fmtNum(mm.kwh_added, 1)}</td><td className={td}>{fmtMoney(mm.charge_cost)}</td><td className={td}>{fmtTemp(mm.avg_outside_temp_c)}</td>
              </tr>))}</tbody>
          </table>
        </TableView>
      </Card>
    </Fetching>
  );
}

export function Calendar() {
  const vid = useVid();
  const latest = useLatestDay(vid);
  const [params, setParams] = useSearchParams();
  if (!latest) return <div className="card h-96 animate-pulse" />;
  const view = params.get("view") === "year" ? "year" : "month";
  const ym = params.get("m") ?? latest.slice(0, 7);
  const year = Number(ym.slice(0, 4));
  const go = (next: string) => setParams(view === "year" ? { view, m: next } : { m: next });
  const step = view === "year" ? 12 : 1;
  return (
    <div>
      <PageTitle title={view === "year" ? String(year) : fmtDate(`${ym}-15`, { month: "long", year: "numeric" })}>
        <Segmented label="Calendar view" value={view} onChange={(v) => setParams(v === "year" ? { view: v, m: ym } : { m: ym })}
          options={[{ value: "month", label: "Month" }, { value: "year", label: "Year" }]} />
        <button onClick={() => go(shiftMonth(ym, -step))} className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-ink-2 hover:text-ink" aria-label="Previous">←</button>
        <button onClick={() => go(shiftMonth(ym, step))} disabled={shiftMonth(ym, step) > latest.slice(0, 7)} className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-ink-2 hover:text-ink disabled:opacity-30" aria-label="Next">→</button>
      </PageTitle>
      {view === "year" ? <YearView vid={vid} year={year} /> : <MonthView vid={vid} ym={ym} latest={latest} />}
    </div>
  );
}
