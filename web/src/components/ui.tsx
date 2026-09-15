import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { SessionKind } from "../api";
import { KIND_COLOR } from "../charts/Chart";

export function Card({ title, subtitle, action, children, className = "", pad = true }: { title?: ReactNode; subtitle?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`card min-w-0 ${pad ? "p-4" : ""} ${className}`}>
      {(title || action) && (
        <header className={`mb-3 flex flex-wrap items-start justify-between gap-2 ${pad ? "" : "px-4 pt-4"}`}>
          <div>
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="text-xs text-ink-3">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: string }) {
  return (
    <div className="card relative min-w-0 overflow-hidden px-4 py-3">
      {accent && <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: accent }} />}
      <div className="text-xs text-ink-3">{label}</div>
      <div className="mt-0.5 text-xl font-semibold tracking-tight text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

export function Segmented<T extends string | number>({ options, value, onChange, label }: { options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-full border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button key={String(o.value)} role="radio" aria-checked={o.value === value} onClick={() => onChange(o.value)}
          className={`rounded-full px-3 py-1 text-xs transition ${o.value === value ? "bg-surface-3 font-medium text-ink" : "text-ink-3 hover:text-ink"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export const KIND_LABEL: Record<SessionKind, string> = { drive: "Drive", charge: "Charge", idle: "Parked", sleep: "Sleep", unreachable: "Offline" };

export function KindDot({ kind }: { kind: SessionKind }) {
  return <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: KIND_COLOR[kind] }} aria-hidden />;
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-line px-4 py-10 text-center text-sm text-ink-3">{children}</div>;
}

export function Fetching({ busy, children }: { busy: boolean; children: ReactNode }) {
  return <div className={`transition-opacity ${busy ? "opacity-60" : ""}`}>{children}</div>;
}

export function TableView({ children, label = "Show table" }: { children: ReactNode; label?: string }) {
  return (
    <details className="mt-3 group">
      <summary className="cursor-pointer select-none text-xs text-ink-3 hover:text-ink">{label}</summary>
      <div className="mt-2 overflow-x-auto">{children}</div>
    </details>
  );
}

export function NavButton({ to, children, disabled }: { to: string; children: ReactNode; disabled?: boolean }) {
  if (disabled) return <span className="rounded-full border border-line px-3 py-1.5 text-sm text-ink-3 opacity-40">{children}</span>;
  return <Link to={to} className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink">{children}</Link>;
}

export const th = "px-3 py-2 text-left text-xs font-medium text-ink-3 whitespace-nowrap";
export const td = "px-3 py-2 whitespace-nowrap num";
