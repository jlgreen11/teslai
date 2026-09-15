import { useQuery } from "@tanstack/react-query";
import { useOutletContext, useSearchParams } from "react-router-dom";
import { api, type Status, type Vehicle } from "../api";
import { addDays, todayIso } from "../format";

export function useVehicles() {
  return useQuery({ queryKey: ["vehicles"], queryFn: () => api<Vehicle[]>("/api/v1/vehicles") });
}

export function useVehicleId(): number | null {
  const { data } = useVehicles();
  let stored = Number(new URLSearchParams(window.location.search).get("vehicle") ?? 0);
  try {
    if (stored) localStorage.setItem("teslai.vehicle", String(stored));
    else stored = Number(localStorage.getItem("teslai.vehicle"));
  } catch { /* storage blocked */ }
  if (!data?.length) return null;
  return data.find((v) => v.id === stored)?.id ?? data[0].id;
}

export function useVid(): number {
  return useOutletContext<{ vehicleId: number }>().vehicleId;
}

export function useStatus(vehicleId: number) {
  return useQuery({
    queryKey: ["status", vehicleId], queryFn: () => api<Status>(`/api/v1/vehicles/${vehicleId}/status`),
    refetchInterval: 30_000,
  });
}

/** The last day with data (so a parked demo car or a sleeping car still opens on real history). */
export function useLatestDay(vehicleId: number): string | null {
  const { data, isLoading } = useStatus(vehicleId);
  if (isLoading) return null;
  return data?.last_seen?.slice(0, 10) ?? todayIso();
}

export const RANGE_PRESETS = [
  { days: 7, label: "7D" }, { days: 30, label: "30D" }, { days: 90, label: "90D" },
  { days: 365, label: "1Y" }, { days: 3650, label: "All" },
];

export function useRange(vehicleId: number, defaultDays = 30) {
  const [params, setParams] = useSearchParams();
  const latest = useLatestDay(vehicleId);
  const days = Number(params.get("days") ?? defaultDays);
  const end = latest;
  const start = latest ? addDays(latest, -(days - 1)) : null;
  const setDays = (d: number) => {
    const next = new URLSearchParams(params);
    next.set("days", String(d));
    setParams(next, { replace: true });
  };
  return { days, start, end, setDays, ready: latest != null };
}
