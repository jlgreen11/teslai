import { Component, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useVehicleId, useVehicles } from "../hooks/useVehicle";
import { StatusBar } from "./StatusBar";

const NAV = [
  { to: "/", label: "Today", end: true },
  { to: "/drives", label: "Drives" },
  { to: "/charges", label: "Charges" },
  { to: "/parked", label: "Parked" },
  { to: "/calendar", label: "Calendar" },
  { to: "/battery", label: "Battery" },
  { to: "/efficiency", label: "Efficiency" },
  { to: "/tires", label: "Tires" },
  { to: "/map", label: "Map" },
];

class PageBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div className="card p-6">
          <h1 className="text-lg font-semibold">This page hit an error</h1>
          <p className="mt-1 text-sm text-ink-3">{this.state.error.message}</p>
          <button onClick={() => this.setState({ error: null })} className="mt-3 rounded-full border border-line px-3 py-1.5 text-sm text-ink-2 hover:text-ink">Try again</button>
        </div>
      );
    }
    return this.props.children;
  }
}

export function Layout() {
  const loc = useLocation();
  const vehicleId = useVehicleId();
  const { data: vehicles, isLoading } = useVehicles();
  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-16 pt-[max(12px,env(safe-area-inset-top))]">
      <header className="mb-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <svg viewBox="0 0 24 24" className="h-6 w-6" aria-hidden>
            <path d="M12 3c3.6 0 7 .8 9.5 2.2l-1.2 1.6C18 5.6 15.2 5 12 5s-6 .6-8.3 1.8L2.5 5.2C5 3.8 8.4 3 12 3zm0 4c1.4 0 2.6.1 3.7.4L12 21 8.3 7.4C9.4 7.1 10.6 7 12 7z" fill="var(--color-accent)" />
          </svg>
          <span className="text-lg font-semibold tracking-tight">teslai</span>
        </div>
        <div className="flex items-center gap-3">
          {vehicles && vehicles.length > 1 && (
            <select className="rounded-lg border border-line bg-surface px-2 py-1 text-sm" value={vehicleId ?? ""}
              onChange={(e) => { localStorage.setItem("teslai.vehicle", e.target.value); location.reload(); }}>
              {vehicles.map((v) => <option key={v.id} value={v.id}>{v.display_name ?? "Car"} ···{v.vin_last4}</option>)}
            </select>
          )}
          <form method="post" action="/api/v1/logout" onSubmit={async (e) => { e.preventDefault(); await fetch("/api/v1/logout", { method: "POST" }); location.href = "/login"; }}>
            <button className="rounded-lg px-2 py-1 text-sm text-ink-3 hover:text-ink">Sign out</button>
          </form>
        </div>
      </header>
      {vehicleId != null && <StatusBar vehicleId={vehicleId} />}
      <nav className="sticky top-[env(safe-area-inset-top)] z-20 -mx-4 mt-3 overflow-x-auto bg-page/85 px-4 py-2 backdrop-blur">
        <ul className="flex gap-1">
          {NAV.map((n) => (
            <li key={n.to}>
              <NavLink to={n.to} end={n.end}
                className={({ isActive }) => `block whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm transition ${isActive ? "bg-ink text-page font-medium" : "text-ink-2 hover:bg-surface-2 hover:text-ink"}`}>
                {n.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className="mt-3">
        {isLoading ? <div className="card h-64 animate-pulse" /> :
          vehicleId == null ? <div className="card p-8 text-ink-2">No vehicles yet. Run <code className="text-ink">teslai demo seed</code> or import TeslaFi history.</div> :
          <PageBoundary key={loc.pathname}><Outlet context={{ vehicleId }} /></PageBoundary>}
      </main>
    </div>
  );
}
