import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, AppUser } from "../api/client";
import { errMsg, useAsync } from "../hooks";
import { ErrorBox, fmtDate, JourneyTracker, Loading, PageHeader, Section, SeverityBadge, STATUS_COLOR, StatusPill, VerdictBadge } from "../components/ui";
import { BarList, Gauge } from "../components/charts";

export default function Shipment({ role }: { role: AppUser["role"] }) {
  const { id = "" } = useParams();
  const { data, error, reload } = useAsync(() => api.getShipment(id), [id]);
  const [qrAsset, setQrAsset] = useState<{ shipmentId: string; url: string }>(); const [qrError, setQrError] = useState<string>();
  const qrUrl = (id && qrAsset?.shipmentId === id) ? qrAsset.url : undefined;
  const [formError, setFormError] = useState<string>();
  const canLabel = role === "seller" || role === "admin";
  const canReview = role === "inspector" || role === "admin";
  const [reviewTarget, setReviewTarget] = useState<{ flagId: number; ruleCode: string; status: "reviewed" | "dismissed" } | null>(null);
  const [reviewReason, setReviewReason] = useState("");
  const [reviewBusy, setReviewBusy] = useState(false);
  useEffect(() => {
    let active = true; let localUrl: string | undefined;
    setQrAsset(undefined); setQrError(undefined);
    if (canLabel && id) api.fetchQr(id).then(url => { localUrl = url; if (active) setQrAsset({ shipmentId: id, url }); else URL.revokeObjectURL(url); }).catch(e => { if (active) setQrError(errMsg(e)); });
    return () => { active = false; if (localUrl) URL.revokeObjectURL(localUrl); };
  }, [id, canLabel]);

  if (error) return <ErrorBox message={error} />;
  if (!data) return <Loading what="Loading shipment" />;
  const s = data.shipment;
  const byRule = new Map<string, number>();
  data.risk.contributions.forEach((c) => byRule.set(c.rule_code, (byRule.get(c.rule_code) ?? 0) + c.points));
  const contribData = [...byRule.entries()].sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value, color: "var(--color-warn)" }));

  function openReview(flagId: number, ruleCode: string, status: "reviewed" | "dismissed") {
    setReviewTarget({ flagId, ruleCode, status });
    setReviewReason("");
    setFormError(undefined);
  }

  async function submitReview() {
    if (!reviewTarget || reviewReason.trim().length < 3) return;
    setReviewBusy(true); setFormError(undefined);
    try {
      await api.patchFlag(reviewTarget.flagId, reviewTarget.status, reviewReason.trim());
      setReviewTarget(null); setReviewReason(""); reload();
    } catch (e) {
      setFormError(errMsg(e));
    } finally {
      setReviewBusy(false);
    }
  }

  return <>
    <PageHeader title={s.product} sub={`${s.origin} → ${s.destination} · ${s.quantity} ${s.unit} · dispatch ${s.dispatch_date}`} actions={<div className="flex items-center gap-2"><VerdictBadge verdict={data.verdict} /><Link className="btn-ghost" to={`/shipments/${s.id}/report`}>Report</Link></div>} />
    {formError && <div className="mb-4"><ErrorBox message={formError} /></div>}
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="min-w-0 space-y-6 lg:col-span-2">
        <Section title="Journey progress" right={<span className="text-xs text-mute"><span className="font-mono text-ink">{s.id}</span> · registered by {s.created_by}</span>}>
          <JourneyTracker status={data.status} />
        </Section>

        <Section title="Rule-based prioritisation" right={<span className="rounded-full border border-line bg-raised px-2.5 py-0.5 text-xs text-mute">{data.open_flag_count} open finding(s)</span>}>
          <div className="grid items-center gap-6 sm:grid-cols-2">
            <div>
              <Gauge score={data.risk.score} label={data.risk.band} />
              <p className="mt-3 text-center text-sm text-mute">{data.risk.meaning}</p>
            </div>
            <div>
              <p className="label">Score contributions by rule</p>
              {contribData.length === 0 ? <p className="rounded-lg bg-raised px-3 py-4 text-sm text-mute">No rules have added points to this score.</p> : <BarList data={contribData} suffix=" pts" />}
            </div>
          </div>
          <p className="mt-5 border-t border-line pt-3 text-xs leading-5 text-mute">{data.risk.disclaimer} The score prioritises review; it is not a probability that a shipment is fraudulent.</p>
        </Section>

        <Section title={`Investigation findings (${data.flags.length})`} flush>
          {data.flags.length === 0 ? <p className="px-5 py-8 text-center text-sm text-mute">No findings raised by the currently configured rules. This does not prove authenticity.</p> : <ul className="divide-y divide-line">{data.flags.map(f => <li key={f.id} className="px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2"><SeverityBadge severity={f.severity} /><span className="font-mono text-xs">{f.rule_code}</span><span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${f.status === "open" ? "bg-warn/10 text-warn" : "bg-raised text-mute"}`}>{f.status}</span></div>
              {canReview && f.status === "open" && <div className="flex gap-2"><button className="btn-ghost !px-3 !py-1 text-xs" onClick={() => openReview(f.id, f.rule_code, "reviewed")}>Review</button><button className="btn-ghost !px-3 !py-1 text-xs" onClick={() => openReview(f.id, f.rule_code, "dismissed")}>Dismiss</button></div>}
            </div>
            <p className="mt-2 text-sm leading-6 text-mute">{f.explanation}</p>
            {f.evidence?.why_suspicious && <p className="mt-2 text-sm leading-6">{f.evidence.why_suspicious}</p>}
            {((f.evidence?.unknowns?.length ?? 0) > 0 || (f.evidence?.next_steps?.length ?? 0) > 0) && <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {f.evidence?.unknowns && f.evidence.unknowns.length > 0 && <div className="rounded-lg bg-raised p-3 text-xs text-mute"><p className="font-medium text-ink">What remains unknown</p><ul className="mt-1 list-disc space-y-1 pl-4">{f.evidence.unknowns.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
              {f.evidence?.next_steps && f.evidence.next_steps.length > 0 && <div className="rounded-lg bg-raised p-3 text-xs text-mute"><p className="font-medium text-ink">Suggested investigation steps</p><ul className="mt-1 list-disc space-y-1 pl-4">{f.evidence.next_steps.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
            </div>}
            {f.evidence?.observed && <details className="mt-3 text-xs"><summary className="cursor-pointer text-brand">Show observed evidence and thresholds</summary><pre className="mt-2 overflow-x-auto rounded-lg bg-raised p-3 text-[10px] leading-5">{JSON.stringify({observed:f.evidence.observed, expected:f.evidence.expected, scan_ids:f.evidence.scan_ids}, null, 2)}</pre></details>}
            {f.incident_key && <p className="mt-2 break-all font-mono text-[10px] text-mute">Incident: {f.incident_key}</p>}
          </li>)}</ul>}
        </Section>

        <Section title={`Verified journey events (${data.events.length})`} flush>
          {data.events.length === 0 ? <p className="px-5 py-8 text-center text-sm text-mute">No handovers recorded yet. An authorised transporter should scan the physical QR label at the first checkpoint.</p> : <ol className="relative space-y-5 px-5 py-5 before:absolute before:bottom-8 before:left-[29px] before:top-8 before:w-px before:bg-line">{data.events.map(e => <li key={e.id} className="relative flex gap-4">
            <span className="z-[1] mt-1 h-4 w-4 shrink-0 rounded-full border-2 border-white" style={{ background: STATUS_COLOR[e.type], boxShadow: "0 0 0 1px var(--color-line)" }} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><StatusPill status={e.type} />{!e.valid && <span className="text-xs text-warn">did not advance status</span>}</div><span className="text-xs text-mute">{fmtDate(e.timestamp)}</span></div>
              <p className="mt-1 text-sm">{e.checkpoint} <span className="text-mute">· {e.actor}</span></p>
              {e.note && <p className="text-sm text-mute">{e.note}</p>}
              {e.flags.map(f => <p key={f.id} className="mt-2 rounded-lg bg-raised px-3 py-2 text-xs leading-5 text-mute"><SeverityBadge severity={f.severity} /> <span className="font-mono">{f.rule_code}</span> — {f.explanation}</p>)}
            </div>
          </li>)}</ol>}
        </Section>

        <Section title={`Raw scan records (${data.scans.length})`} flush>
          {data.scans.length === 0 ? <p className="px-5 py-5 text-sm text-mute">No scan records yet.</p> : <div className="overflow-x-auto"><table className="w-full min-w-[620px] text-left text-xs"><thead className="border-b border-line bg-raised/50"><tr><th className="th">Scan</th><th className="th">Time (server)</th><th className="th">Checkpoint</th><th className="th">Operator</th><th className="th">Result</th><th className="th">Event</th></tr></thead><tbody className="divide-y divide-line">{data.scans.map(scan => <tr key={scan.id}><td className="td font-mono">#{scan.id}</td><td className="td">{fmtDate(scan.scanned_at)}</td><td className="td">{scan.checkpoint}</td><td className="td">{scan.scanned_by}</td><td className="td"><span className={scan.signature_valid ? "text-ok" : "text-warn"}>{scan.scan_result}</span></td><td className="td">{scan.event_id ? `#${scan.event_id}` : "—"}</td></tr>)}</tbody></table></div>}
        </Section>
      </div>

      <aside className="space-y-6 lg:sticky lg:top-6 lg:self-start">
        {canLabel && <section className="card p-5 text-center"><h2 className="card-title">Shipment label</h2>{qrUrl ? <img src={qrUrl} alt={`Signed QR code for ${s.id}`} width={200} height={200} className="mx-auto mt-4 rounded-xl border border-line bg-white p-2" /> : qrError ? <p className="mt-3 text-xs text-warn">{qrError}</p> : <p className="py-8 text-sm text-mute">Loading signed QR…</p>}<p className="mt-2 font-mono text-xs text-mute">{s.id}</p>{qrUrl && <a className="btn-ghost mt-3 inline-flex" href={qrUrl} download={`${s.id}.png`}>Download label</a>}<p className="mt-3 text-xs leading-5 text-mute">Give the physical label to the authorised transporter. Reprints should be controlled and recorded.</p></section>}
        <section className="card p-5"><h2 className="card-title">Shipment record</h2><dl className="mt-4 divide-y divide-line text-sm">{[["Created", fmtDate(s.created_at)], ["Dispatch date", s.dispatch_date], ["Origin", s.origin], ["Destination", s.destination], ["Quantity", `${s.quantity} ${s.unit}`], ["Lifecycle state", data.status.replace("_", " ")]].map(([k,v]) => <div key={k} className="flex justify-between gap-4 py-2.5"><dt className="text-mute">{k}</dt><dd className="text-right font-medium">{v}</dd></div>)}</dl>{role !== "seller" && <Link className="btn-primary mt-4 w-full" to="/scan">Open scan workflow</Link>}</section>
      </aside>
    </div>

    {reviewTarget && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4 backdrop-blur-sm">
        <div className="card w-full max-w-lg space-y-4 p-6 shadow-2xl">
          <div className="flex items-center justify-between border-b border-line pb-3">
            <h3 className="text-lg font-semibold">
              {reviewTarget.status === "dismissed" ? "Dismiss Finding" : "Mark Finding as Reviewed"}
            </h3>
            <button
              className="btn-ghost !px-2 !py-1 text-xs"
              onClick={() => setReviewTarget(null)}
            >
              ✕
            </button>
          </div>
          <div>
            <p className="font-mono text-xs text-mute">
              Rule Code: <span className="text-ink">{reviewTarget.ruleCode}</span> · Finding #{reviewTarget.flagId}
            </p>
            <p className="mt-2 text-xs leading-5 text-mute">
              {reviewTarget.status === "dismissed"
                ? "Dismissing marks this finding as non-actionable (e.g. verified false alarm or operator explanation). Evidence is permanently preserved in the audit log."
                : "Reviewing confirms inspection was conducted. The finding remains in the risk prioritisation assessment and audit trail."}
            </p>
          </div>
          <label className="block">
            <span className="label">Inspector Reason (required, 3-280 chars)</span>
            <textarea
              className="input h-24 resize-none"
              required
              minLength={3}
              maxLength={280}
              placeholder={
                reviewTarget.status === "dismissed"
                  ? "Explain why this finding is dismissed (e.g. operator confirmed scanner bounce; physical consignment verified)..."
                  : "Explain inspection actions taken (e.g. verified seals intact, checked physical weight and manifest)..."
              }
              value={reviewReason}
              onChange={(e) => setReviewReason(e.target.value)}
            />
            <span className="mt-1 block text-right text-[10px] text-mute">{reviewReason.length}/280</span>
          </label>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setReviewTarget(null)}
              disabled={reviewBusy}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={reviewBusy || reviewReason.trim().length < 3}
              onClick={() => void submitReview()}
            >
              {reviewBusy
                ? "Saving…"
                : reviewTarget.status === "dismissed"
                ? "Confirm Dismissal"
                : "Confirm Review"}
            </button>
          </div>
        </div>
      </div>
    )}
  </>;
}
