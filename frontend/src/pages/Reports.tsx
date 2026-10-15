import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Status, STATUSES } from "../api/client";
import { useAsync } from "../hooks";
import { Empty, ErrorBox, fmtDate, Icon, Loading, PageHeader, ShipmentLink, StatusPill, VerdictBadge } from "../components/ui";
import { scoreColor } from "../components/charts";

export default function Reports() {
  const { id } = useParams();
  return id ? <ReportView id={id} /> : <ShipmentList />;
}

function ShipmentList() {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [stage, setStage] = useState<Status | "ALL">("ALL");
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250); // debounce typing
    return () => clearTimeout(t);
  }, [text]);
  const { data, error, reload } = useAsync(() => api.listShipments(q || undefined), [q]);
  const rows = data ? (stage === "ALL" ? data : data.filter((s) => s.status === stage)) : [];

  return (
    <>
      <PageHeader title="Farm-to-market trail" sub="Search by ID, product, origin or destination. Open a shipment for its history and report." />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mute" />
          <input className="input !pl-9" placeholder="Search shipments…" value={text} maxLength={60} onChange={(e) => setText(e.target.value)} aria-label="Search shipments" />
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by stage">
          {(["ALL", ...STATUSES] as const).map((st) => (
            <button key={st} onClick={() => setStage(st)} className={`rounded-full border px-3 py-1 text-xs font-medium transition ${stage === st ? "border-brand bg-brand text-white" : "border-line bg-white text-mute hover:border-brand/40 hover:text-ink"}`}>
              {st === "ALL" ? "All" : st.replace("_", " ")}
              {data && <span className="ml-1.5 opacity-70">{st === "ALL" ? data.length : data.filter((s) => s.status === st).length}</span>}
            </button>
          ))}
        </div>
      </div>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!error && !data && <Loading />}
      {data && (
        <div className="card overflow-x-auto">
          {rows.length === 0 ? (
            <Empty>{q || stage !== "ALL" ? "No shipments match your search." : "No shipments yet."}</Empty>
          ) : (
            <table className="w-full min-w-[700px] text-left text-sm">
              <thead className="border-b border-line bg-raised/50">
                <tr>
                  <th className="th">ID</th>
                  <th className="th">Product</th>
                  <th className="th">Route</th>
                  <th className="th">Status</th>
                  <th className="th">Verdict</th>
                  <th className="th">Flags</th>
                  <th className="th" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((s) => (
                  <tr key={s.id} className="transition hover:bg-raised/40">
                    <td className="td"><ShipmentLink id={s.id} /></td>
                    <td className="td font-medium">{s.product}</td>
                    <td className="td text-mute">{s.origin} → {s.destination}</td>
                    <td className="td"><StatusPill status={s.status} /></td>
                    <td className="td"><VerdictBadge verdict={s.verdict} /></td>
                    <td className="td tabular-nums" style={{ color: s.open_flag_count ? scoreColor(70) : undefined }}>{s.open_flag_count || "—"}</td>
                    <td className="td text-right"><Link className="text-brand hover:underline" to={`/shipments/${s.id}/report`}>Report</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  );
}

function ReportView({ id }: { id: string }) {
  const { data: r, error, reload } = useAsync(() => api.report(id), [id]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!r) return <Loading what="Building report" />;
  const s = r.shipment;

  return (
    <>
      <div className="no-print mb-4 flex items-center justify-between">
        <Link to={`/shipments/${s.id}`} className="text-sm text-mute hover:text-ink">← Back to shipment</Link>
        <button className="btn-primary" onClick={() => window.print()}>Print / save as PDF</button>
      </div>

      <article className="print-area card mx-auto max-w-4xl space-y-7 p-8">
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-4">
          <div>
            <p className="text-xs uppercase tracking-widest text-mute">TraceGuard · Verification report</p>
            <h1 className="mt-1 font-mono text-2xl">{s.id}</h1>
          </div>
          <div className="text-right text-xs text-mute">
            Generated {fmtDate(r.generated_at)}
            <div className="mt-2"><VerdictBadge verdict={r.verdict} /></div>
          </div>
        </header>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-brand-dark">Registered record</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 rounded-xl bg-raised/60 p-4 text-sm sm:grid-cols-3">
            {([
              ["Product", s.product],
              ["Quantity", `${s.quantity} ${s.unit}`],
              ["Origin", s.origin],
              ["Destination", s.destination],
              ["Dispatch date", s.dispatch_date],
              ["Registered by", s.created_by],
              ["Current status", r.status.replace("_", " ")],
              ["Review priority", `${r.risk.score}/100 · ${r.risk.band}`],
            ] as const).map(([k, v]) => (
              <div key={k}><dt className="text-xs text-mute">{k}</dt><dd className="font-medium">{v}</dd></div>
            ))}
          </dl>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-brand-dark">Conclusion</h2>
          <p className="text-sm">{r.conclusion}</p>
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-brand-dark">Flags ({r.flags.length})</h2>
          {r.flags.length === 0 ? (
            <p className="text-sm text-mute">No flags were raised for this shipment.</p>
          ) : (
            <ul className="space-y-2">
              {r.flags.map((f) => (
                <li key={f.id} className="rounded-lg border border-line p-3 text-sm">
                  <span className="font-mono text-xs">{f.rule_code}</span> · {f.severity} · <span className="text-mute">{f.status}</span>
                  <p className="mt-1 text-mute">{f.explanation}</p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-brand-dark">Event history ({r.events.length})</h2>
          {r.events.length === 0 ? (
            <p className="text-sm text-mute">No events recorded.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-line text-xs uppercase text-mute">
                  <tr><th className="py-2 pr-3 font-medium">Time</th><th className="pr-3 font-medium">Event</th><th className="pr-3 font-medium">Checkpoint</th><th className="pr-3 font-medium">By</th><th className="font-medium">Flags</th></tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {r.events.map((e) => (
                    <tr key={e.id}>
                      <td className="py-2 pr-3 whitespace-nowrap">{fmtDate(e.timestamp)}</td>
                      <td className="pr-3">{e.type.replace("_", " ")}</td>
                      <td className="pr-3">{e.checkpoint}</td>
                      <td className="pr-3">{e.actor}</td>
                      <td className="font-mono text-xs">{e.flags.map((f) => f.rule_code).join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <footer className="border-t border-line pt-3 text-xs text-mute">
          Rules checked: {r.rules_checked.join(", ")}. A flag means the record requires human investigation; it is not a finding of fraud.
        </footer>
      </article>
    </>
  );
}
