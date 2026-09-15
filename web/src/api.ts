export class Unauthorized extends Error {}

export async function api<T>(path: string): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin" });
  if (r.status === 401) {
    window.location.href = "/login";
    throw new Unauthorized();
  }
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not json */ }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export type SessionKind = "drive" | "charge" | "idle" | "sleep" | "unreachable";

export interface Vehicle { id: number; display_name: string | null; timezone: string; vin_last4: string }

export interface Status {
  name: string; vin_last4: string;
  state: "driving" | "charging" | "parked" | "asleep" | "offline" | "unknown"; state_since: string | null;
  battery_level: number | null; charge_limit: number | null; energy_remaining_kwh: number | null;
  rated_range: number | null; est_100_range: number | null; odometer: number | null; version: string | null;
  fsd_miles: number | null; miles_since_reset: number | null;
  inside_temp_c: number | null; outside_temp_c: number | null; locked: boolean | null; sentry: boolean | null;
  tpms: { fl: number | null; fr: number | null; rl: number | null; rr: number | null };
  charging: { power_kw: number | null; added_kwh: number | null } | null;
  place: string | null; last_seen: string | null;
}

export interface SessionRow {
  id: number; kind: SessionKind; start: string; end: string | null; duration_s: number | null;
  distance_miles: number | null; start_battery: number | null; end_battery: number | null;
  energy_added_kwh: number | null; energy_used_kwh: number | null; rated_miles_used: number | null;
  wh_per_mile: number | null; efficiency_pct: number | null; charger: "ac" | "dc" | null;
  cost: number | null; cost_source: string | null; energy_cost: number | null; gas_savings: number | null;
  start_place: string | null; end_place: string | null; avg_outside_temp_c: number | null;
  avg_inside_temp_c: number | null; max_speed: number | null; avg_speed: number | null;
  max_charger_power: number | null; flags: string[]; start_odometer: number | null; end_odometer: number | null;
}

export interface Totals {
  drives: number; miles: number; kwh_used: number; charges: number; kwh_added: number; charge_cost: number;
  drive_seconds: number; sleep_seconds: number; idle_seconds: number; parked_drain_pct: number;
  wh_per_mile: number | null; avg_outside_temp_c: number | null;
}

export interface SessionPage {
  items: SessionRow[]; total: number;
  totals: Partial<Totals> & { count: number; energy_cost: number; gas_savings: number };
}

export interface SamplePoint {
  ts: string; lat: number | null; lon: number | null; speed: number | null; power: number | null;
  battery_level: number | null; rated_range: number | null; inside_temp_c: number | null;
  outside_temp_c: number | null; charger_power: number | null; charge_energy_added: number | null;
}

export interface SessionDetail { session: SessionRow; samples: SamplePoint[]; prev_id: number | null; next_id: number | null }

export interface Timeline {
  date: string; timezone: string; currency: string; sessions: SessionRow[];
  totals: Totals & { date: string }; week: (Totals & { date: string })[];
  battery: { ts: string; battery_level: number }[];
}

export interface CalendarMonth { year: number; month: number; days: (Totals & { date: string })[]; summary: Totals & { days_driven: number } }
export interface CalendarYear { year: number; months: (Totals & { month: string })[] }

export interface Efficiency {
  start: string; end: string;
  temperature: { temp_f: number; temp_f_to: number; drives: number; miles: number; wh_per_mile: number }[];
  speed: { speed_mph: number; speed_mph_to: number; drives: number; miles: number; wh_per_mile: number }[];
}

export interface ChargeLocation {
  location: string; charges: number; kwh_added: number; cost: number; cost_per_kwh: number | null;
  max_power_kw: number | null; last_charge: string; chargers: string[]; charge_seconds: number;
}

export interface Tires { days: { date: string; fl: number | null; fr: number | null; rl: number | null; rr: number | null; outside_temp: number | null }[] }

export interface MapData {
  tracks: { id: number; start: string; points: [number, number][] }[];
  places: { name: string; kind: string; lat: number; lon: number }[];
}

export interface BatteryReport {
  points: { date: string; battery_level: number; est_100_range: number }[];
  months: { month: string; median_est_100_range: number; charges: number }[];
  baseline: number | null; current: number | null; loss_pct: number | null; max_estimate: number | null;
}
