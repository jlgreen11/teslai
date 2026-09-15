import type { Status } from "../api";
import { useStatus } from "../hooks/useVehicle";
import { fmtDuration, fmtMiles, fmtNum, secondsBetween } from "../format";
import { CarDiagram } from "./CarDiagram";

const STATE_LABEL: Record<Status["state"], string> = {
  driving: "Driving", charging: "Charging", parked: "Parked", asleep: "Asleep", offline: "Offline", unknown: "Unknown",
};
const STATE_COLOR: Record<Status["state"], string> = {
  driving: "bg-drive", charging: "bg-charge", parked: "bg-idle", asleep: "bg-sleep", offline: "bg-unreachable", unknown: "bg-idle",
};

function Battery({ level, limit }: { level: number | null; limit: number | null }) {
  const pct = Math.max(0, Math.min(100, level ?? 0));
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-5 w-24 rounded-md border border-line bg-surface-3 p-[2px]" aria-hidden>
        <div className={`h-full rounded-[4px] ${pct < 20 ? "bg-critical" : "bg-charge"}`} style={{ width: `${pct}%` }} />
        {limit != null && <div className="absolute top-0 bottom-0 w-px bg-ink-2" style={{ left: `${limit}%` }} />}
        <div className="absolute -right-[5px] top-1/2 h-2 w-[3px] -translate-y-1/2 rounded-r bg-line" />
      </div>
      <span className="text-lg font-semibold">{level == null ? "–" : `${level.toFixed(0)}%`}</span>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] uppercase tracking-wide text-ink-3">{label}</div>
      <div className="truncate text-base font-semibold text-ink">{value}</div>
      {sub && <div className="truncate text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

export function StatusBar({ vehicleId }: { vehicleId: number }) {
  const { data: s } = useStatus(vehicleId);
  if (!s) return <div className="card glass h-[132px] animate-pulse" />;
  const since = s.state_since ? fmtDuration(secondsBetween(s.state_since, null)) : null;
  const fsdPct = s.fsd_miles != null && s.miles_since_reset ? (s.fsd_miles / s.miles_since_reset) * 100 : null;
  return (
    <section className="card glass grid grid-cols-2 items-center gap-x-6 gap-y-4 p-4 md:grid-cols-[1.2fr_1fr_1fr_1fr_220px]">
      <div className="col-span-2 flex items-center gap-3 md:col-span-1">
        <span className="relative flex h-3 w-3">
          {s.state === "driving" || s.state === "charging" ? <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${STATE_COLOR[s.state]} opacity-60`} /> : null}
          <span className={`relative inline-flex h-3 w-3 rounded-full ${STATE_COLOR[s.state]}`} />
        </span>
        <div className="min-w-0">
          <div className="truncate text-lg font-semibold">{s.name} is {STATE_LABEL[s.state].toLowerCase()}</div>
          <div className="truncate text-xs text-ink-3">{[since && `for ${since}`, s.place].filter(Boolean).join(" · ") || " "}</div>
        </div>
      </div>
      <div>
        <Battery level={s.battery_level} limit={s.charge_limit} />
        <div className="mt-1 text-xs text-ink-3">
          {s.charging ? `+${fmtNum(s.charging.added_kwh, 1)} kWh at ${fmtNum(s.charging.power_kw, 0)} kW` : [s.charge_limit != null && `limit ${fmtNum(s.charge_limit)}%`, s.energy_remaining_kwh != null && `${fmtNum(s.energy_remaining_kwh, 1)} kWh`].filter(Boolean).join(" · ")}
        </div>
      </div>
      <Stat label="Rated range" value={fmtMiles(s.rated_range, 0)} sub={`${fmtMiles(s.est_100_range, 0)} at 100%`} />
      <Stat label="Odometer · software" value={fmtMiles(s.odometer, 0)}
        sub={<span>{s.version ?? "–"}{fsdPct != null && <> · FSD {fsdPct.toFixed(0)}%</>}</span>} />
      <div className="col-span-2 flex justify-center md:col-span-1">
        <CarDiagram tpms={s.tpms} insideC={s.inside_temp_c} outsideC={s.outside_temp_c} locked={s.locked} />
      </div>
    </section>
  );
}
