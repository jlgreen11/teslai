import { useNavigate } from "react-router-dom";
import type { SessionRow } from "../api";
import { fmtDate, fmtDuration, fmtKwh, fmtMiles, fmtMoney, fmtNum, fmtTemp, fmtTime } from "../format";
import { KIND_LABEL, KindDot, td, th } from "./ui";

function where(s: SessionRow) {
  if (s.kind === "drive") return `${s.start_place ?? "Unknown"} → ${s.end_place ?? "Unknown"}`;
  return s.end_place ?? s.start_place ?? (s.charger === "dc" ? "Supercharger" : "Unknown location");
}

function battery(s: SessionRow) {
  return s.start_battery == null ? "–" : `${fmtNum(s.start_battery)}% → ${fmtNum(s.end_battery)}%`;
}

export function SessionTable({ rows, kind, currency = "USD" }: { rows: SessionRow[]; kind: "drive" | "charge" | "parked"; currency?: string }) {
  const nav = useNavigate();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-line">
          <tr>
            <th className={th}>Date</th>
            <th className={th}>{kind === "drive" ? "Route" : "Location"}</th>
            <th className={th}>Duration</th>
            <th className={th}>Battery</th>
            {kind === "drive" && <><th className={th}>Distance</th><th className={th}>Energy</th><th className={th}>Wh/mi</th><th className={th}>Efficiency</th><th className={th}>Temp</th><th className={th}>Cost</th></>}
            {kind === "charge" && <><th className={th}>Added</th><th className={th}>Peak kW</th><th className={th}>Type</th><th className={th}>Cost</th></>}
            {kind === "parked" && <><th className={th}>State</th><th className={th}>Drain</th><th className={th}>Per day</th></>}
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const drain = s.start_battery != null && s.end_battery != null ? s.start_battery - s.end_battery : null;
            const perDay = drain != null && s.duration_s ? drain / (s.duration_s / 86400) : null;
            return (
              <tr key={s.id} tabIndex={0} onClick={() => kind !== "parked" && nav(`/session/${s.id}`)}
                onKeyDown={(e) => { if (e.key === "Enter" && kind !== "parked") nav(`/session/${s.id}`); }}
                className={`border-b border-line/60 ${kind !== "parked" ? "cursor-pointer hover:bg-surface-2 focus:bg-surface-2 focus:outline-none" : ""}`}>
                <td className={td}>
                  <div className="text-ink">{fmtDate(s.start, { weekday: "short", month: "short", day: "numeric" })}</div>
                  <div className="text-xs text-ink-3">{fmtTime(s.start)} – {fmtTime(s.end)}</div>
                </td>
                <td className="max-w-[280px] truncate px-3 py-2 text-ink-2">
                  <span className="inline-flex items-center gap-2"><KindDot kind={s.kind} />{where(s)}</span>
                </td>
                <td className={td}>{fmtDuration(s.duration_s)}</td>
                <td className={td}>{battery(s)}</td>
                {kind === "drive" && <>
                  <td className={td}>{fmtMiles(s.distance_miles)}</td>
                  <td className={td}>{fmtKwh(s.energy_used_kwh, 2)}</td>
                  <td className={td}>{fmtNum(s.wh_per_mile)}</td>
                  <td className={td}>{s.efficiency_pct == null ? "–" : `${fmtNum(s.efficiency_pct)}%`}</td>
                  <td className={td}>{fmtTemp(s.avg_outside_temp_c)}</td>
                  <td className={td}>{fmtMoney(s.energy_cost, currency)}</td>
                </>}
                {kind === "charge" && <>
                  <td className={td}>{fmtKwh(s.energy_added_kwh, 2)}</td>
                  <td className={td}>{fmtNum(s.max_charger_power)}</td>
                  <td className={td}>{s.charger === "dc" ? "DC fast" : s.charger === "ac" ? "AC" : "–"}</td>
                  <td className={td}>{fmtMoney(s.cost, currency)}{s.cost_source === "estimate" && <span className="ml-1 text-xs text-ink-3">est.</span>}</td>
                </>}
                {kind === "parked" && <>
                  <td className={td}>{KIND_LABEL[s.kind]}</td>
                  <td className={td}>{drain == null ? "–" : `${fmtNum(drain, 1)}%`}</td>
                  <td className={td}>{perDay == null || (s.duration_s ?? 0) < 3600 ? "–" : `${fmtNum(perDay, 1)}%/day`}</td>
                </>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
