import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Severity, Status, Verdict } from "../api/client";

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: string; actions?: ReactNode }) {
  return (
    <div className="no-print mb-7 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {sub && <p className="mt-1 max-w-2xl text-sm leading-6 text-mute">{sub}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="py-10 text-center text-sm text-mute">{what}…</p>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-bad">
      {message}
      {onRetry && (
        <button onClick={onRetry} className="ml-3 underline">
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-4 py-8 text-center text-sm text-mute">{children}</p>;
}

const VERDICTS: Record<string, { label: string; cls: string }> = {
  VERIFIED: { label: "Verified", cls: "border-ok/40 bg-ok/10 text-ok" },
  REQUIRES_INVESTIGATION: { label: "Requires investigation", cls: "border-warn/40 bg-warn/10 text-warn" },
  UNKNOWN: { label: "Unknown code", cls: "border-bad/40 bg-bad/10 text-bad" },
};
export function VerdictBadge({ verdict }: { verdict: Verdict | "UNKNOWN" }) {
  const v = VERDICTS[verdict];
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${v.cls}`}>{v.label}</span>;
}

export const STATUS_COLOR: Record<Status, string> = {
  REGISTERED: "#94a3b8",
  DISPATCHED: "#3b82f6",
  IN_TRANSIT: "#d49b2c",
  RECEIVED: "#8b5cf6",
  DELIVERED: "#23834b",
};

export function StatusPill({ status }: { status: Status }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-raised px-2.5 py-0.5 text-[11px] font-medium text-ink">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATUS_COLOR[status] }} />
      {status.replace("_", " ")}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const cls = severity === "high" ? "bg-bad/15 text-bad" : severity === "medium" ? "bg-warn/15 text-warn" : "bg-mute/15 text-mute";
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cls}`}>{severity}</span>;
}

export function ShipmentLink({ id }: { id: string }) {
  return (
    <Link to={`/shipments/${id}`} className="font-mono text-sm text-brand hover:underline">
      {id}
    </Link>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-mute">{hint}</span>}
    </label>
  );
}

const ICONS: Record<string, ReactNode> = {
  dashboard: <><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></>,
  box: <><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" /><path d="m3.3 7 8.7 5 8.7-5" /><path d="M12 22V12" /></>,
  scan: <><path d="M3 7V5a2 2 0 0 1 2-2h2" /><path d="M17 3h2a2 2 0 0 1 2 2v2" /><path d="M21 17v2a2 2 0 0 1-2 2h-2" /><path d="M7 21H5a2 2 0 0 1-2-2v-2" /><path d="M7 12h10" /></>,
  route: <><circle cx="6" cy="19" r="3" /><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15" /><circle cx="18" cy="5" r="3" /></>,
  shield: <><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" /><path d="m9 12 2 2 4-4" /></>,
  check: <><circle cx="12" cy="12" r="10" /><path d="m9 12 2 2 4-4" /></>,
  alert: <><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /><path d="M12 9v4" /><path d="M12 17h.01" /></>,
  flag: <><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><path d="M4 22v-7" /></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></>,
  logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5" /><path d="M21 12H9" /></>,
  search: <><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></>,
  settings: <><path d="M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z" /><path d="M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" /><path d="M12 2v2" /><path d="M12 22v-2" /><path d="m17 20.66-1-1.73" /><path d="M11 10.27 7 3.34" /><path d="m20.66 17-1.73-1" /><path d="m3.34 7 1.73 1" /><path d="M14 12h8" /><path d="M2 12h2" /><path d="m20.66 7-1.73 1" /><path d="m3.34 17 1.73-1" /><path d="m17 3.34-1 1.73" /><path d="m11 13.73-4 6.93" /></>,
  activity: <path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2" />,
};

export type IconName = keyof typeof ICONS;

export function Icon({ name, className = "h-5 w-5" }: { name: IconName; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      {ICONS[name]}
    </svg>
  );
}

const TONES = {
  neutral: "bg-raised text-brand",
  ok: "bg-ok/10 text-ok",
  warn: "bg-warn/10 text-warn",
  bad: "bg-bad/10 text-bad",
} as const;

export function StatCard({ label, value, icon, tone = "neutral", hint }: { label: string; value: ReactNode; icon: IconName; tone?: keyof typeof TONES; hint?: string }) {
  return (
    <div className="card flex items-center gap-4 p-5">
      <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${TONES[tone]}`}><Icon name={icon} /></span>
      <div className="min-w-0">
        <div className="text-xs font-medium uppercase tracking-wide text-mute">{label}</div>
        <div className="text-2xl font-semibold tabular-nums leading-tight">{value}</div>
        {hint && <div className="text-xs text-mute">{hint}</div>}
      </div>
    </div>
  );
}

/** Card with a titled header strip. */
export function Section({ title, right, children, className = "", flush = false }: { title: ReactNode; right?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={`card overflow-hidden ${className}`}>
      <div className="card-head"><h2 className="card-title">{title}</h2>{right}</div>
      <div className={flush ? "" : "p-5"}>{children}</div>
    </section>
  );
}

const STAGES: Status[] = ["REGISTERED", "DISPATCHED", "IN_TRANSIT", "RECEIVED", "DELIVERED"];

/** Horizontal journey tracker used on shipment pages. */
export function JourneyTracker({ status }: { status: Status }) {
  const idx = STAGES.indexOf(status);
  return (
    <ol className="flex items-start">
      {STAGES.map((st, i) => (
        <li key={st} className="flex flex-1 flex-col items-center text-center last:flex-none">
          <div className="flex w-full items-center">
            <span className={`h-0.5 flex-1 ${i === 0 ? "bg-transparent" : i <= idx ? "bg-brand" : "bg-line"}`} />
            <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border-2 text-xs font-semibold ${i < idx ? "border-brand bg-brand text-white" : i === idx ? "border-brand bg-white text-brand ring-4 ring-brand/15" : "border-line bg-white text-mute"}`}>
              {i < idx ? "✓" : i + 1}
            </span>
            <span className={`h-0.5 flex-1 ${i === STAGES.length - 1 ? "bg-transparent" : i < idx ? "bg-brand" : "bg-line"}`} />
          </div>
          <span className={`mt-2 px-1 text-[11px] font-medium leading-tight ${i === idx ? "text-ink" : "text-mute"}`}>{st.replace("_", " ")}</span>
        </li>
      ))}
    </ol>
  );
}

export function Logo({ className = "h-9 w-9" }: { className?: string }) {
  return <span className={`grid place-items-center rounded-xl bg-brand text-white ${className}`}><Icon name="shield" className="h-5 w-5" /></span>;
}
