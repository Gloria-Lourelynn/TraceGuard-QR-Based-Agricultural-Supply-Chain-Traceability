import { FormEvent, useEffect, useState } from "react";
import { api, AppUser, AuditAnchorReceipt, AuditAnchorVerification, AuditRecord, Checkpoint, ShipmentSummary } from "../api/client";
import { errMsg } from "../hooks";
import { ErrorBox, fmtDate, PageHeader, StatCard } from "../components/ui";
import { DonutChart } from "../components/charts";

export default function Admin() {
  const [users, setUsers] = useState<AppUser[]>([]);
  const [shipments, setShipments] = useState<ShipmentSummary[]>([]);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [username, setUsername] = useState(""); const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<AppUser["role"]>("transporter"); const [password, setPassword] = useState("");
  const [shipmentId, setShipmentId] = useState(""); const [transporter, setTransporter] = useState("");
  const [checkpointId, setCheckpointId] = useState("");
  const [audit, setAudit] = useState<Awaited<ReturnType<typeof api.auditVerify>> | null>(null);
  const [auditRecords, setAuditRecords] = useState<AuditRecord[]>([]);
  const [exportedReceipt, setExportedReceipt] = useState<AuditAnchorReceipt | null>(null);
  const [externalAnchorInput, setExternalAnchorInput] = useState("");
  const [externalVerification, setExternalVerification] = useState<AuditAnchorVerification | null>(null);
  const [error, setError] = useState<string>(); const [message, setMessage] = useState<string>();
  const [tab, setTab] = useState<"accounts" | "assign" | "audit">("accounts");

  async function reload() {
    const [u, s, c, log] = await Promise.all([
      api.users(),
      api.listShipments(),
      api.checkpoints(),
      api.auditRecords(20, 0).catch(() => ({ total: 0, limit: 20, offset: 0, records: [] })),
    ]);
    setUsers(u); setShipments(s); setCheckpoints(c); setAuditRecords(log.records);
    if (!shipmentId && s[0]) setShipmentId(s[0].id);
    const t = u.find(x => x.role === "transporter"); if (!transporter && t) setTransporter(t.username);
  }
  useEffect(() => { void reload().catch(e => setError(errMsg(e))); }, []);

  async function createAccount(e: FormEvent) {
    e.preventDefault(); setError(undefined); setMessage(undefined);
    try {
      await api.createUser({ username, display_name: displayName, role, password });
      setUsername(""); setDisplayName(""); setPassword(""); setMessage("Account created.");
      await reload();
    } catch (e) { setError(errMsg(e)); }
  }

  async function assign(e: FormEvent) {
    e.preventDefault(); setError(undefined); setMessage(undefined);
    try {
      await api.assign({ shipment_id: shipmentId, username: transporter, checkpoint_id: checkpointId || null });
      setMessage("Shipment assigned to transporter.");
    } catch (e) { setError(errMsg(e)); }
  }

  async function verifyAudit() {
    setError(undefined);
    try { setAudit(await api.auditVerify()); } catch (e) { setError(errMsg(e)); }
  }

  async function exportAnchor() {
    setError(undefined);
    try {
      const receipt = await api.getAnchor();
      setExportedReceipt(receipt);
      const blob = new Blob([JSON.stringify(receipt, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `traceguard-audit-anchor-seq${receipt.sequence}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setMessage(`Exported cryptographic anchor receipt for sequence #${receipt.sequence}. Store this receipt externally.`);
    } catch (e) { setError(errMsg(e)); }
  }

  async function runExternalVerification(e?: FormEvent) {
    if (e) e.preventDefault();
    setError(undefined); setExternalVerification(null);
    try {
      if (!externalAnchorInput.trim()) {
        setError("Paste or upload an anchor receipt JSON first.");
        return;
      }
      const parsed = JSON.parse(externalAnchorInput.trim());
      const res = await api.verifyAnchor(parsed);
      setExternalVerification(res);
    } catch (e) {
      setError(e instanceof SyntaxError ? "Invalid JSON in anchor receipt." : errMsg(e));
    }
  }

  function handleAnchorFile(file: File) {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      if (text) {
        setExternalAnchorInput(text);
        try {
          const parsed = JSON.parse(text);
          api.verifyAnchor(parsed).then(setExternalVerification).catch(err => setError(errMsg(err)));
        } catch {
          setError("The selected file is not valid JSON.");
        }
      }
    };
    reader.readAsText(file);
  }

  const roleColors: Record<AppUser["role"], string> = { seller: "var(--color-brand)", transporter: "#3b82f6", inspector: "#d49b2c", admin: "#8b5cf6" };
  const roleCount = (r: AppUser["role"]) => users.filter(u => u.role === r).length;
  const tabs = [["accounts", "Accounts"], ["assign", "Assign shipments"], ["audit", "Audit & trust anchoring"]] as const;

  return <>
    <PageHeader title="Administration" sub="Manage accounts, shipment assignments, and cryptographic audit proofs." />
    {error && <div className="mb-4"><ErrorBox message={error} /></div>}
    {message && <p className="mb-4 rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok">{message}</p>}

    <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Accounts" value={users.length} icon="users" />
      <StatCard label="Active" value={users.filter(u => u.active).length} icon="check" tone="ok" />
      <StatCard label="Shipments" value={shipments.length} icon="box" />
      <StatCard label="Checkpoints" value={checkpoints.length} icon="route" />
    </div>

    <div className="mb-6 flex gap-1 overflow-x-auto border-b border-line" role="tablist">
      {tabs.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className={`tab shrink-0 ${tab === k ? "tab-active" : ""}`} onClick={() => setTab(k)}>{label}</button>)}
    </div>

    {tab === "accounts" && <div className="grid gap-6 lg:grid-cols-3">
      <form onSubmit={createAccount} className="card space-y-4 p-5 lg:col-span-1">
        <h2 className="card-title">Create account</h2>
        <label className="block"><span className="label">Username</span><input className="input" required minLength={3} maxLength={40} value={username} onChange={e => setUsername(e.target.value)} /></label>
        <label className="block"><span className="label">Display name</span><input className="input" required maxLength={80} value={displayName} onChange={e => setDisplayName(e.target.value)} /></label>
        <label className="block"><span className="label">Role</span><select className="input" value={role} onChange={e => setRole(e.target.value as AppUser["role"])}><option value="seller">Seller / farmer</option><option value="transporter">Transporter / checkpoint operator</option><option value="inspector">Inspector</option><option value="admin">Admin</option></select></label>
        <label className="block"><span className="label">Temporary password (10+ characters)</span><input className="input" type="password" required minLength={10} value={password} onChange={e => setPassword(e.target.value)} /></label>
        <button className="btn-primary w-full">Create account</button>
      </form>
      <div className="space-y-6 lg:col-span-2">
        <section className="card p-5">
          <h2 className="card-title mb-4">Accounts by role</h2>
          <DonutChart centerValue={users.length} centerLabel="accounts" segments={(["seller", "transporter", "inspector", "admin"] as const).map(r => ({ label: r[0].toUpperCase() + r.slice(1), value: roleCount(r), color: roleColors[r] }))} />
        </section>
        <section className="card overflow-hidden">
          <div className="card-head"><h2 className="card-title">All accounts</h2><button className="btn-ghost !px-3 !py-1 text-xs" onClick={() => void reload().catch(e => setError(errMsg(e)))}>Refresh</button></div>
          <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-left text-sm"><thead className="border-b border-line bg-raised/50"><tr><th className="th">Name</th><th className="th">Username</th><th className="th">Role</th><th className="th">Status</th></tr></thead><tbody className="divide-y divide-line">{users.map(u => <tr key={u.id}><td className="td font-medium">{u.display_name}</td><td className="td font-mono text-xs">{u.username}</td><td className="td"><span className="inline-flex items-center gap-1.5 capitalize"><span className="h-2 w-2 rounded-full" style={{ background: roleColors[u.role] }} />{u.role}</span></td><td className="td"><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${u.active ? "bg-ok/10 text-ok" : "bg-raised text-mute"}`}>{u.active ? "Active" : "Disabled"}</span></td></tr>)}</tbody></table></div>
        </section>
      </div>
    </div>}

    {tab === "assign" && <form onSubmit={assign} className="card mx-auto max-w-xl space-y-4 p-6">
      <h2 className="card-title">Assign shipment</h2>
      <p className="text-sm text-mute">Transporters can only see and hand over shipments assigned to them.</p>
      <label className="block"><span className="label">Shipment</span><select className="input" required value={shipmentId} onChange={e => setShipmentId(e.target.value)}>{shipments.map(s => <option key={s.id} value={s.id}>{s.id} · {s.product}</option>)}</select></label>
      <label className="block"><span className="label">Transporter</span><select className="input" required value={transporter} onChange={e => setTransporter(e.target.value)}>{users.filter(u => u.role === "transporter" && u.active).map(u => <option key={u.id} value={u.username}>{u.display_name} (@{u.username})</option>)}</select></label>
      <label className="block"><span className="label">Checkpoint restriction (optional)</span><select className="input" value={checkpointId} onChange={e => setCheckpointId(e.target.value)}><option value="">Any registered checkpoint</option>{checkpoints.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
      <button className="btn-primary w-full" disabled={!shipmentId || !transporter}>Assign shipment</button>
    </form>}

    {tab === "audit" && <section className="card space-y-5 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
          <div>
            <h2 className="font-semibold">Cryptographic Audit Chain & External Trust Anchoring</h2>
            <p className="mt-1 text-xs text-mute">Export signed point-in-time anchor receipts to prove database integrity against internal rewrites or rollbacks.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-ghost" onClick={() => void verifyAudit()}>Verify local chain</button>
            <button className="btn-primary" onClick={() => void exportAnchor()}>Export anchor receipt</button>
          </div>
        </div>

        {audit && (
          <div className="rounded-lg border border-line bg-raised/50 p-4 text-sm">
            <p className={audit.ok ? "text-ok" : "text-bad"}>
              {audit.ok ? `✓ Local integrity check passed for all ${audit.checked} records.` : `✗ Integrity failure at sequence ${audit.first_bad_seq}: ${audit.reason}`}
            </p>
            <p className="mt-1 break-all font-mono text-xs text-mute">Current Head Hash: {audit.head_hash || "empty chain"}</p>
          </div>
        )}

        {exportedReceipt && (
          <div className="rounded-lg border border-ok/30 bg-ok/5 p-3 text-xs space-y-1">
            <p className="font-medium text-ok">Signed Anchor Receipt Generated (Sequence #{exportedReceipt.sequence})</p>
            <p className="break-all font-mono text-mute">Head: {exportedReceipt.head_hash}</p>
            <p className="break-all font-mono text-mute">HMAC Signature: {exportedReceipt.signature}</p>
          </div>
        )}

        <form onSubmit={runExternalVerification} className="rounded-xl border border-line bg-raised/40 p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Verify against an external anchor receipt</h3>
            <label className="btn-ghost cursor-pointer !px-3 !py-1 text-xs">
              <span>Select anchor .json file</span>
              <input type="file" accept=".json,application/json" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) handleAnchorFile(f); }} />
            </label>
          </div>
          <p className="text-xs text-mute">Paste or upload a previously exported anchor receipt to verify that history has not been truncated, deleted, or rewritten.</p>
          <textarea
            className="input font-mono text-xs h-20 resize-none"
            placeholder='{"system": "TraceGuard V2", "sequence": 14, "head_hash": "...", "signature": "..."}'
            value={externalAnchorInput}
            onChange={e => setExternalAnchorInput(e.target.value)}
          />
          <button type="submit" className="btn-ghost text-xs">Verify external receipt</button>

          {externalVerification && (
            <div className={`mt-3 rounded-lg border p-3 text-xs ${externalVerification.ok ? "border-ok/40 bg-ok/10 text-ok" : "border-bad/40 bg-bad/10 text-bad"}`}>
              {externalVerification.ok ? (
                <div>
                  <p className="font-semibold">✓ Cryptographic external anchor verified successfully!</p>
                  <p className="mt-1 text-ink">Anchored at Sequence #{externalVerification.anchored_sequence} ({externalVerification.anchored_at}). Zero modifications or deletions detected across {externalVerification.records_checked} total records ({externalVerification.records_since_anchor} new records since anchor).</p>
                  <p className="mt-1 font-mono break-all text-mute">Anchored Hash: {externalVerification.anchored_hash}</p>
                </div>
              ) : (
                <div>
                  <p className="font-semibold">✗ Anchor Verification Failed!</p>
                  <p className="mt-1 text-ink">{externalVerification.reason}</p>
                </div>
              )}
            </div>
          )}
        </form>

        <div className="space-y-2 pt-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Live Audit Trail (Recent 20 Records)</h3>
            <button className="btn-ghost !px-2 !py-1 text-xs" onClick={() => void reload()}>Refresh log</button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[650px] text-left text-xs">
              <thead className="border-b border-line text-mute uppercase">
                <tr>
                  <th className="py-2 px-3">Seq</th>
                  <th className="py-2 px-3">Timestamp</th>
                  <th className="py-2 px-3">Event Kind</th>
                  <th className="py-2 px-3">Actor</th>
                  <th className="py-2 px-3">Hash (SHA-256)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {auditRecords.length === 0 ? (
                  <tr><td colSpan={5} className="py-4 text-center text-mute">No audit records yet.</td></tr>
                ) : (
                  auditRecords.map(r => (
                    <tr key={r.seq}>
                      <td className="py-2 px-3 font-mono font-medium">#{r.seq}</td>
                      <td className="py-2 px-3 text-mute">{fmtDate(r.ts)}</td>
                      <td className="py-2 px-3 font-mono text-brand">{r.kind}</td>
                      <td className="py-2 px-3 text-mute">{r.actor_username ? `@${r.actor_username}` : "system"}</td>
                      <td className="py-2 px-3 font-mono text-mute">{r.hash.slice(0, 16)}…</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
    </section>}
  </>;
}
