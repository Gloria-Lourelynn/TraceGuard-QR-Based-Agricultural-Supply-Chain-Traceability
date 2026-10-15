import { Link } from "react-router-dom";
import { api, AppUser, STATUSES } from "../api/client";
import { useAsync } from "../hooks";
import { Empty, ErrorBox, fmtDate, Icon, Loading, PageHeader, Section, SeverityBadge, ShipmentLink, StatCard, STATUS_COLOR, StatusPill } from "../components/ui";
import { ColumnChart, DonutChart } from "../components/charts";

export default function Dashboard({ role }: { role: AppUser["role"] }) {
  const canRegister = role === "seller" || role === "admin";
  const { data, error, reload } = useAsync(() => api.dashboard(), []);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Loading what="Loading dashboard" />;

  const other = Math.max(0, data.total_shipments - data.verified - data.under_investigation);
  const sev = { high: 0, medium: 0, low: 0 };
  data.alerts.forEach((a) => { sev[a.severity] += 1; });

  return (
    <>
      <PageHeader
        title="Farm-to-market dashboard"
        sub="Track agricultural produce from collection to destination. Alerts mean a shipment needs review—not that fraud is confirmed."
        actions={canRegister ? <Link to="/register" className="btn-primary"><Icon name="box" className="h-4 w-4" />Register shipment</Link> : undefined}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Produce shipments" value={data.total_shipments} icon="box" />
        <StatCard label="Verified" value={data.verified} icon="check" tone="ok" />
        <StatCard label="Under investigation" value={data.under_investigation} icon="alert" tone={data.under_investigation ? "warn" : "neutral"} />
        <StatCard label="Open flags" value={data.open_flags} icon="flag" tone={data.open_flags ? "bad" : "neutral"} />
      </div>

      {data.total_shipments === 0 ? (
        <div className="card mt-6">
          <Empty>
            {canRegister ? <>No shipments yet. <Link to="/register" className="text-brand underline">Register the first one</Link>, or run{" "}
              <code className="font-mono text-ink">python seed.py</code> to load demo data.</>
              : role === "transporter" ? "No shipments are assigned to this transporter account yet. Ask an admin to assign a shipment."
              : "No shipments are available to review yet. Ask an admin to check the database and assignments."}
          </Empty>
        </div>
      ) : (
        <div className="mt-6 space-y-6">
          <div className="grid gap-6 lg:grid-cols-3">
            <Section title="Shipments by journey stage">
              <ColumnChart height={130} data={STATUSES.map((s) => ({ label: s.replace("_", " "), value: data.by_status[s], color: STATUS_COLOR[s] }))} />
            </Section>
            <Section title="Verification outcome">
              <DonutChart
                centerValue={data.total_shipments ? `${Math.round((data.verified / data.total_shipments) * 100)}%` : "–"}
                centerLabel="verified"
                segments={[
                  { label: "Verified", value: data.verified, color: "var(--color-ok)" },
                  { label: "Under investigation", value: data.under_investigation, color: "var(--color-warn)" },
                  ...(other ? [{ label: "Other", value: other, color: "#94a3b8" }] : []),
                ]}
              />
            </Section>
            <Section title="Open alerts by severity">
              {data.alerts.length === 0 ? <p className="py-10 text-center text-sm text-mute">No open alerts.</p> : (
                <DonutChart
                  centerValue={data.alerts.length}
                  centerLabel="alerts"
                  segments={[
                    { label: "High", value: sev.high, color: "var(--color-bad)" },
                    { label: "Medium", value: sev.medium, color: "var(--color-warn)" },
                    { label: "Low", value: sev.low, color: "#94a3b8" },
                  ]}
                />
              )}
            </Section>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Section title="Shipments needing review" flush className="lg:col-span-2">
              {data.investigation_list.length === 0 ? (
                <Empty>Nothing needs review right now.</Empty>
              ) : (
                <ul className="divide-y divide-line">
                  {data.investigation_list.map((s) => (
                    <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5">
                      <div>
                        <ShipmentLink id={s.id} />
                        <div className="text-sm text-mute">{s.product} · {s.origin} → {s.destination}</div>
                      </div>
                      <div className="flex items-center gap-2">
                        <StatusPill status={s.status} />
                        <span className="rounded-full bg-warn/10 px-2 py-0.5 text-xs font-medium text-warn">{s.open_flag_count} open</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title="Recent activity" flush>
              {data.recent_events.length === 0 ? <Empty>No activity yet.</Empty> : (
                <ol className="relative space-y-4 px-5 py-4 before:absolute before:bottom-6 before:left-[27px] before:top-6 before:w-px before:bg-line">
                  {data.recent_events.map((e) => (
                    <li key={e.id} className="relative flex gap-3 text-sm">
                      <span className="z-[1] mt-1 h-3.5 w-3.5 shrink-0 rounded-full border-2 border-white" style={{ background: STATUS_COLOR[e.type], boxShadow: "0 0 0 1px var(--color-line)" }} />
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-x-2"><StatusPill status={e.type} /><span className="text-xs text-mute">{fmtDate(e.timestamp)}</span></div>
                        <div className="mt-1 truncate text-mute"><ShipmentLink id={e.shipment_id} /> · {e.checkpoint}</div>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </Section>
          </div>

          <Section title="Supply-chain alerts" flush>
            {data.alerts.length === 0 ? (
              <Empty>No open alerts.</Empty>
            ) : (
              <ul className="grid divide-y divide-line md:grid-cols-2 md:divide-y-0">
                {data.alerts.map((f) => (
                  <li key={f.id} className="border-line px-5 py-4 md:border-b md:odd:border-r">
                    <div className="flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={f.severity} />
                      <span className="font-mono text-xs">{f.rule_code}</span>
                      <span className="text-mute">·</span>
                      <ShipmentLink id={f.shipment_id} />
                    </div>
                    <p className="mt-1.5 text-sm leading-6 text-mute">{f.explanation}</p>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      )}
    </>
  );
}
