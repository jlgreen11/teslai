export const cToF = (c: number | null | undefined) => (c == null ? null : c * 9 / 5 + 32);
export const barToPsi = (b: number | null | undefined) => (b == null ? null : b * 14.5038);

export function fmtTemp(c: number | null | undefined, digits = 0): string {
  const f = cToF(c);
  return f == null ? "–" : `${f.toFixed(digits)}°F`;
}

export function fmtNum(n: number | null | undefined, digits = 0): string {
  return n == null || Number.isNaN(n) ? "–" : n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export const fmtMiles = (m: number | null | undefined, digits = 1) => (m == null ? "–" : `${fmtNum(m, digits)} mi`);
export const fmtKwh = (k: number | null | undefined, digits = 1) => (k == null ? "–" : `${fmtNum(k, digits)} kWh`);

export function fmtMoney(n: number | null | undefined, currency = "USD"): string {
  return n == null ? "–" : new Intl.NumberFormat(undefined, { style: "currency", currency }).format(n);
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "–";
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h ${String(m % 60).padStart(2, "0")} m`;
  return `${Math.floor(h / 24)} d ${h % 24} h`;
}

export function fmtTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "now";
}

export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", year: "numeric" }): string {
  if (!iso) return "–";
  const d = iso.length === 10 ? new Date(`${iso}T12:00:00`) : new Date(iso);
  return d.toLocaleDateString([], opts);
}

export const secondsBetween = (a: string, b: string | null) =>
  ((b ? new Date(b).getTime() : Date.now()) - new Date(a).getTime()) / 1000;

export function addDays(isoDate: string, n: number): string {
  const d = new Date(`${isoDate}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
