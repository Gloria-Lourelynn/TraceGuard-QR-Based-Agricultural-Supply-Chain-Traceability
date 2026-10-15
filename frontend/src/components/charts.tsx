import type { ReactNode } from "react";

export type Segment = { label: string; value: number; color: string };

/** Donut chart with a centre label and a legend. Pure SVG, no dependencies. */
export function DonutChart({ segments, centerValue, centerLabel }: { segments: Segment[]; centerValue: ReactNode; centerLabel: string }) {
  const total = segments.reduce((a, s) => a + s.value, 0);
  let acc = 0;
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-4">
      <div className="relative h-36 w-36 shrink-0">
        <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" role="img" aria-label={segments.map((s) => `${s.label}: ${s.value}`).join(", ")}>
          <circle cx="50" cy="50" r="38" fill="none" stroke="var(--color-raised)" strokeWidth="13" />
          {total > 0 && segments.filter((s) => s.value > 0).map((s) => {
            const pct = (s.value / total) * 100;
            const el = <circle key={s.label} cx="50" cy="50" r="38" fill="none" stroke={s.color} strokeWidth="13" pathLength={100} strokeDasharray={`${Math.max(pct - 0.8, 0.2)} ${100 - Math.max(pct - 0.8, 0.2)}`} strokeDashoffset={-acc} />;
            acc += pct;
            return el;
          })}
        </svg>
        <div className="absolute inset-0 grid place-items-center text-center">
          <div><div className="text-2xl font-semibold tabular-nums leading-none">{centerValue}</div><div className="mt-1 text-[10px] uppercase tracking-wide text-mute">{centerLabel}</div></div>
        </div>
      </div>
      <ul className="space-y-2 text-sm">
        {segments.map((s) => (
          <li key={s.label} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            <span className="text-mute">{s.label}</span>
            <span className="ml-auto pl-3 font-medium tabular-nums">{s.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Vertical column chart. */
export function ColumnChart({ data, height = 150 }: { data: { label: string; value: number; color?: string }[]; height?: number }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="flex items-end gap-2 sm:gap-3" style={{ height: height + 40 }}>
      {data.map((d) => (
        <div key={d.label} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1.5">
          <span className="text-xs font-semibold tabular-nums">{d.value}</span>
          <div className="flex w-full items-end justify-center rounded-t-md bg-raised/60" style={{ height }}>
            <div className="w-full rounded-t-md transition-all duration-500" style={{ height: `${Math.max((d.value / max) * 100, d.value ? 3 : 0)}%`, background: d.color ?? "var(--color-brand)" }} />
          </div>
          <span className="w-full truncate text-center text-[10px] font-medium uppercase tracking-wide text-mute">{d.label}</span>
        </div>
      ))}
    </div>
  );
}

/** Horizontal labelled bars. */
export function BarList({ data, suffix = "" }: { data: { label: string; value: number; color?: string }[]; suffix?: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <ul className="space-y-3">
      {data.map((d) => (
        <li key={d.label}>
          <div className="mb-1 flex justify-between gap-3 text-xs"><span className="truncate font-mono text-mute">{d.label}</span><span className="font-medium tabular-nums">{d.value}{suffix}</span></div>
          <div className="h-2 rounded-full bg-raised"><div className="h-2 rounded-full transition-all duration-500" style={{ width: `${(d.value / max) * 100}%`, background: d.color ?? "var(--color-brand)" }} /></div>
        </li>
      ))}
    </ul>
  );
}

export function scoreColor(score: number): string {
  return score >= 67 ? "var(--color-bad)" : score >= 34 ? "var(--color-warn)" : "var(--color-ok)";
}

/** Semicircle gauge for a 0-100 score. */
export function Gauge({ score, label }: { score: number; label: string }) {
  const s = Math.min(100, Math.max(0, score));
  return (
    <div className="relative mx-auto w-52">
      <svg viewBox="0 0 200 110" className="w-full" role="img" aria-label={`Score ${s} out of 100`}>
        <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke="var(--color-raised)" strokeWidth="16" strokeLinecap="round" pathLength={100} />
        {s > 0 && <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke={scoreColor(s)} strokeWidth="16" strokeLinecap="round" pathLength={100} strokeDasharray={`${s} 100`} />}
      </svg>
      <div className="absolute inset-x-0 bottom-0 text-center">
        <div className="text-3xl font-semibold tabular-nums leading-none">{s}<span className="text-sm font-medium text-mute">/100</span></div>
        <div className="mt-1 text-xs font-medium uppercase tracking-wide" style={{ color: scoreColor(s) }}>{label}</div>
      </div>
    </div>
  );
}
