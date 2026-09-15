import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { api, type ChargeLocation, type SessionPage } from "../api";
import { bars, categoryAxis, Chart, grid, SERIES, tooltip, valueAxis } from "../charts/Chart";
import { SessionTable } from "../components/SessionTable";
import { Card, Empty, Fetching, PageTitle, Segmented, Stat, TableView, td, th } from "../components/ui";
import { fmtDate, fmtDuration, fmtKwh, fmtMiles, fmtMoney, fmtNum } from "../format";
import { RANGE_PRESETS, useRange, useVid } from "../hooks/useVehicle";

type Mode = "drive" | "charge" | "parked";
const KIND_PARAM: Record<Mode, string> = { drive: "drive", charge: "charge", parked: "idle,sleep" };
const TITLE: Record<Mode, string> = { drive: "Drives", charge: "Charges", parked: "Parked" };

export function RangePicker({ days, setDays }: { days: number; setDays: (d: number) => void }) {
  return <Segmented label="Date range" value={days} onChange={setDays} options={RANGE_PRESETS.map((p) => ({ value: p.days, label: p.label }))} />;
}

export function Sessions({ mode }: { mode: Mode }) {
  const vid = useVid();
  const { days, start, end, setDays, ready } = useRange(vid, 30);
  const [limit, setLimit] = useState(100);
  const q = useQuery({
    queryKey: ["sessions", vid, mode, start, end, limit], enabled: ready,
    queryFn: () => api<SessionPage>(`/api/v1/vehicles/${vid}/session-list?kind=${KIND_PARAM[mode]}&start=${start}&end=${end}&limit=${limit}`),
  });
  const locs = useQuery({
    queryKey: ["charge-locations", vid, start, end], enabled: ready && mode === "charge",
    queryFn: () => api<{ locations: ChargeLocation[] }>(`/api/v1/vehicles/${vid}/charge-locations?start=${start}&end=${end}`),
  });

  const byPeriod = useMemo<EChartsOption | null>(() => {
    const items = q.data?.items;
    if (!items?.length || mode === "parked") return null;
    const keyLen = days > 120 ? 7 : 10;
    const sums = new Map<string, number>();
    for (const s of items) {
      const k = s.start.slice(0, keyLen);
      sums.set(k, (sums.get(k) ?? 0) + (mode === "drive" ? s.distance_miles ?? 0 : s.energy_added_kwh ?? 0));
    }
    const keys = [...sums.keys()].sort();
    const unit = mode === "drive" ? "mi" : "kWh";
    return {
      grid: grid(), tooltip: tooltip({ valueFormatter: (v: number) => `${fmtNum(v, 1)} ${unit}` }),
      xAxis: categoryAxis(keys.map((k) => (keyLen === 7 ? fmtDate(`${k}-15`, { month: "short", year: "2-digit" }) : fmtDate(k, { month: "short", day: "numeric" })))),
      yAxis: valueAxis(),
      series: [bars(mode === "drive" ? "Miles" : "kWh added", SERIES[0], keys.map((k) => Math.round((sums.get(k) ?? 0) * 10) / 10))],
    };
  }, [q.data, mode, days]);

  const locOption = useMemo<EChartsOption | null>(() => {
    const l = locs.data?.locations.slice(0, 8);
    if (!l?.length) return null;
    const rows = [...l].reverse();
    return {
      grid: grid({ right: 48 }), tooltip: tooltip({ trigger: "item", valueFormatter: (v: number) => fmtKwh(v) }),
      yAxis: categoryAxis(rows.map((r) => r.location), { axisLabel: { color: "#b4b8bf", fontSize: 12, width: 160, overflow: "truncate" } }),
      xAxis: valueAxis(),
      series: [{ ...bars("kWh added", SERIES[2], rows.map((r) => Math.round(r.kwh_added))), itemStyle: { borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: "right", color: "#b4b8bf", fontSize: 11, formatter: "{c}" } }],
    };
  }, [locs.data]);

  const t = q.data?.totals;
  return (
    <div>
      <PageTitle title={TITLE[mode]}><RangePicker days={days} setDays={(d) => { setLimit(100); setDays(d); }} /></PageTitle>
      {!q.data ? <div className="card h-96 animate-pulse" /> : (
        <Fetching busy={q.isFetching}>
          <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
            {mode === "drive" && t && <>
              <Stat label="Distance" value={fmtMiles(t.miles, 0)} sub={`${t.count} drives`} />
              <Stat label="Energy used" value={fmtKwh(t.kwh_used, 0)} sub={t.wh_per_mile ? `${fmtNum(t.wh_per_mile)} Wh/mi average` : "–"} />
              <Stat label="Time driving" value={fmtDuration(t.drive_seconds)} sub={t.avg_outside_temp_c != null ? `avg ${fmtNum((t.avg_outside_temp_c * 9) / 5 + 32)}°F outside` : undefined} />
              <Stat label="Energy cost" value={fmtMoney(t.energy_cost)} sub={t.gas_savings ? `${fmtMoney(t.gas_savings)} saved vs gas` : "at your home rate"} />
            </>}
            {mode === "charge" && t && <>
              <Stat label="Charges" value={fmtNum(t.count)} />
              <Stat label="Energy added" value={fmtKwh(t.kwh_added, 0)} />
              <Stat label="Charging cost" value={fmtMoney(t.charge_cost)} />
              <Stat label="Average price" value={t.kwh_added ? `${fmtMoney((t.charge_cost ?? 0) / t.kwh_added)}/kWh` : "–"} />
            </>}
            {mode === "parked" && t && <>
              <Stat label="Parked sessions" value={fmtNum(t.count)} />
              <Stat label="Asleep" value={`${fmtNum((t.sleep_seconds ?? 0) / 3600, 0)} h`} />
              <Stat label="Awake, parked" value={`${fmtNum((t.idle_seconds ?? 0) / 3600, 0)} h`} />
              <Stat label="Parked drain" value={`${fmtNum(t.parked_drain_pct, 1)}%`} sub={days ? `${fmtNum((t.parked_drain_pct ?? 0) / Math.min(days, 3650), 2)}% per day` : undefined} />
            </>}
          </div>

          {(byPeriod || locOption) && (
            <div className={`mb-3 grid gap-3 ${locOption ? "lg:grid-cols-2" : ""}`}>
              {byPeriod && <Card title={mode === "drive" ? "Miles driven" : "Energy added"} subtitle={days > 120 ? "By month" : "By day"}><Chart option={byPeriod} height={220} /></Card>}
              {locOption && <Card title="Where you charge" subtitle="kWh added by location"><Chart option={locOption} height={220} /></Card>}
            </div>
          )}

          {mode === "charge" && locs.data && locs.data.locations.length > 0 && (
            <Card title="Charging locations" className="mb-3">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-line"><tr><th className={th}>Location</th><th className={th}>Charges</th><th className={th}>Energy</th><th className={th}>Time</th><th className={th}>Peak kW</th><th className={th}>Cost</th><th className={th}>Per kWh</th><th className={th}>Last</th></tr></thead>
                  <tbody>{locs.data.locations.map((l) => (
                    <tr key={l.location} className="border-b border-line/60">
                      <td className="px-3 py-2 text-ink">{l.location}</td><td className={td}>{l.charges}</td><td className={td}>{fmtKwh(l.kwh_added, 0)}</td>
                      <td className={td}>{fmtDuration(l.charge_seconds)}</td><td className={td}>{fmtNum(l.max_power_kw)}</td><td className={td}>{fmtMoney(l.cost)}</td>
                      <td className={td}>{l.cost_per_kwh == null ? "–" : fmtMoney(l.cost_per_kwh)}</td><td className={td}>{fmtDate(l.last_charge)}</td>
                    </tr>))}</tbody>
                </table>
              </div>
            </Card>
          )}

          <Card pad={false} title={`${fmtNum(q.data.total)} ${TITLE[mode].toLowerCase()}`} subtitle={`${fmtDate(start)} – ${fmtDate(end)}`}>
            {q.data.items.length === 0 ? <div className="p-4"><Empty>Nothing in this range.</Empty></div> : <SessionTable rows={q.data.items} kind={mode} />}
            {q.data.total > q.data.items.length && (
              <div className="p-3 text-center"><button onClick={() => setLimit(limit + 200)} className="rounded-full border border-line px-4 py-1.5 text-sm text-ink-2 hover:text-ink">Show more</button></div>
            )}
          </Card>
          {byPeriod && <TableView label="About these numbers"><p className="text-xs text-ink-3">Drives under a few hundred feet are hidden. Drive energy comes from the car's energy remaining when it reports it, otherwise from the battery percentage change. Costs use your tariffs file; Supercharger costs use downloaded invoices when available.</p></TableView>}
        </Fetching>
      )}
    </div>
  );
}
