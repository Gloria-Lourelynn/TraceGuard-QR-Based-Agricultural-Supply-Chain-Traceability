import QrScanner from "qr-scanner";
import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, AppUser, Checkpoint, EventType, VerifyResult } from "../api/client";
import { errMsg } from "../hooks";
import { ErrorBox, Field, Icon, PageHeader, StatusPill, VerdictBadge } from "../components/ui";

const ACTIONS: EventType[] = ["DISPATCHED", "IN_TRANSIT", "RECEIVED", "DELIVERED"];

export default function Scan({ role }: { role: AppUser["role"] }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [scanning, setScanning] = useState(false); const [camError, setCamError] = useState<string>();
  const [scanned, setScanned] = useState(""); const [checkpointId, setCheckpointId] = useState("");
  const handoverIntent = useRef<{ fingerprint: string; key: string } | null>(null);
  const manualIntent = useRef<{ fingerprint: string; key: string } | null>(null);
  const [action, setAction] = useState<EventType>("DISPATCHED"); const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string>();
  const [message, setMessage] = useState<string>(); const [result, setResult] = useState<VerifyResult>();
  const [nextLabelShipment, setNextLabelShipment] = useState<string>(); const [labelBusy, setLabelBusy] = useState(false);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [manualId, setManualId] = useState(""); const [manualReason, setManualReason] = useState("");
  const [manualCheckpoint, setManualCheckpoint] = useState(""); const [manualAction, setManualAction] = useState<EventType>("IN_TRANSIT");

  useEffect(() => { api.checkpoints().then(c => { setCheckpoints(c); if (c[0]) { setCheckpointId(c[0].id); setManualCheckpoint(c[0].id); } }).catch(e => setError(errMsg(e))); }, []);

  async function lookup(raw: string) {
    setBusy(true); setError(undefined); setMessage(undefined); setResult(undefined);
    try {
      const res = await api.verify(raw.trim().slice(0, 120)); setScanned(raw.trim().slice(0, 120)); setResult(res);
      const next = res.detail?.expected_next[0]; if (next && ACTIONS.includes(next as EventType)) setAction(next as EventType);
    } catch (e) { setResult(undefined); setError(errMsg(e)); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    if (!scanning || !videoRef.current) return;
    const scanner = new QrScanner(videoRef.current, r => { setScanning(false); handoverIntent.current = null; void lookup(r.data); },
      { preferredCamera: "environment", highlightScanRegion: true, returnDetailedScanResult: true });
    scanner.start().catch(() => { setCamError("Could not open the camera. Allow camera access; browsers require localhost or HTTPS. If the label or camera fails, ask an inspector/admin to record a documented exception."); setScanning(false); });
    return () => { scanner.stop(); scanner.destroy(); };
  }, [scanning]);

  function startCamera() { setCamError(undefined); setResult(undefined); setError(undefined); setMessage(undefined); setScanning(true); }

  async function handleImageFile(file: File) {
    setCamError(undefined); setError(undefined); setMessage(undefined); setBusy(true);
    try {
      const res = await QrScanner.scanImage(file, { returnDetailedScanResult: true });
      if (res && res.data) {
        handoverIntent.current = null;
        await lookup(res.data);
        setMessage("Signed QR label successfully decoded from image file.");
      } else {
        setError("Could not read a QR code from this image. Please provide a clear QR label.");
      }
    } catch {
      setError("No valid QR code detected in the uploaded image. Check the label image.");
    } finally {
      setBusy(false);
    }
  }

  async function submitHandover(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(undefined); setMessage(undefined);
    try {
      const requestBody = { scanned, checkpoint_id: checkpointId, action, note };
      const fingerprint = JSON.stringify(requestBody);
      if (!handoverIntent.current || handoverIntent.current.fingerprint !== fingerprint) {
        handoverIntent.current = { fingerprint, key: crypto.randomUUID() };
      }
      const res = await api.handover({ ...requestBody, idempotency_key: handoverIntent.current.key });
      if (!res.found || !res.detail) { setError(res.message || "The QR was not accepted."); return; }
      setMessage(res.duplicate ? "This handover was already recorded. The repeat request was not duplicated." : `Handover recorded at ${checkpoints.find(c => c.id === checkpointId)?.name ?? checkpointId}. Scan #${res.scan_id}. Download the new QR label before the next checkpoint.`);
      if (!res.duplicate && res.detail?.shipment?.id) setNextLabelShipment(res.detail.shipment.id);
      // Require a fresh physical scan before another handover can be submitted.
      setScanned(""); setResult(undefined); setNote(""); handoverIntent.current = null;
    } catch (e) {
      if (e instanceof ApiError && e.status === 400) {
        setMessage("Rejected QR attempt recorded. No shipment details were disclosed and no handover was created.");
        setScanned(""); setResult(undefined); setNote(""); handoverIntent.current = null;
      } else setError(errMsg(e));
    }
    finally { setBusy(false); }
  }

  async function submitManual(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(undefined); setMessage(undefined);
    try {
      const requestBody = { shipment_id: manualId.trim(), checkpoint_id: manualCheckpoint,
        action: manualAction, reason: manualReason.trim() };
      const fingerprint = JSON.stringify(requestBody);
      if (!manualIntent.current || manualIntent.current.fingerprint !== fingerprint) {
        manualIntent.current = { fingerprint, key: crypto.randomUUID() };
      }
      const res = await api.manualHandover({ ...requestBody, idempotency_key: manualIntent.current.key });
      setMessage(`Manual exception recorded for ${res.detail.shipment.id}. It is visibly marked in the journey and audit trail.`);
      setManualId(""); setManualReason(""); manualIntent.current = null;
    } catch (e) { setError(errMsg(e)); }
    finally { setBusy(false); }
  }

  const d = result?.detail;
  return <>
    <PageHeader title="Scan & handover" sub="A successful camera scan is not itself a handover. Choose the checkpoint action to persist a signed-QR scan and the journey event together." />
    {error && <div className="mb-4"><ErrorBox message={error} /></div>}
    {message && <p className="mb-4 rounded-lg border border-ok/30 bg-ok/10 p-3 text-sm text-ok">{message}</p>}
    {nextLabelShipment && <div className="mb-4 rounded-lg border border-brand/30 bg-raised p-4">
      <p className="text-sm font-semibold">Next checkpoint label required</p>
      <p className="mt-1 text-sm text-mute">The QR token used for the last handover is now invalid. Download and print/display the new label before the shipment continues. Downloading again rotates the active token, so use the latest file only.</p>
      <button className="btn-primary mt-3" disabled={labelBusy} onClick={async () => { setLabelBusy(true); try { const url = await api.fetchQr(nextLabelShipment); const a = document.createElement("a"); a.href = url; a.download = `${nextLabelShipment}-current.png`; a.click(); URL.revokeObjectURL(url); setMessage("A fresh one-use QR label was downloaded. Use only this latest label."); } catch (e) { setError(errMsg(e)); } finally { setLabelBusy(false); } }}>{labelBusy ? "Preparing label…" : "Download next checkpoint QR"}</button>
    </div>}
    <div className="grid gap-6 lg:grid-cols-2">
      <section
        className="card overflow-hidden"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer.files?.[0];
          if (f) void handleImageFile(f);
        }}
      >
        <div className="relative aspect-video bg-ink">
          <video ref={videoRef} className={`h-full w-full object-cover ${scanning ? "" : "hidden"}`} muted playsInline />
          {!scanning && (
            <div className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-white/60">
              <div>
                <Icon name="scan" className="mx-auto mb-2 h-8 w-8 text-white/50" />
                <p className="font-medium text-white">Camera is off</p>
                <p className="mt-1 text-xs">Click Start Camera or drag and drop a QR label image here</p>
              </div>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 p-4">
          {scanning ? (
            <button className="btn-ghost" onClick={() => setScanning(false)}>Stop camera</button>
          ) : (
            <button className="btn-primary" onClick={startCamera}>{result || error ? "Scan with camera" : "Start camera"}</button>
          )}
          <label className="btn-ghost cursor-pointer">
            <span>Upload QR image</span>
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void handleImageFile(f);
                e.target.value = "";
              }}
            />
          </label>
        </div>
        {camError && <p className="px-4 pb-3 text-sm text-warn">{camError}</p>}
        <div className="space-y-2 border-t border-line p-4">
          <p className="text-xs text-mute">Scanned signed payload</p>
          <p className="break-all rounded-lg bg-raised p-3 font-mono text-xs">{scanned || "Waiting for camera scan or image drop…"}</p>
          <p className="text-xs leading-5 text-mute">Normal transporter handovers use signed QR labels (camera scan or image file). A typed shipment ID is not accepted. If the label or camera fails, an inspector/admin must record a documented manual exception.</p>
        </div>
      </section>

      <section className="space-y-6">
        {result && <div className="card p-5">
          <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="card-title">Label result</h2><VerdictBadge verdict={result.verdict} /></div>
          {!result.found || !d ? <p className="mt-3 text-sm text-bad">{result.flags[0]?.explanation ?? "The code was not accepted."} No shipment details are shown. If this label is genuine, ask an admin to assign the shipment to you.</p> : <>
            <p className="mt-3 text-xs font-mono text-mute">{d.shipment.id}</p><h3 className="mt-1 text-lg font-semibold">{d.shipment.product}</h3>
            <p className="mt-1 text-sm text-mute">{d.shipment.origin} → {d.shipment.destination} · {d.shipment.quantity} {d.shipment.unit}</p>
            <div className="mt-3 flex flex-wrap items-center gap-2"><StatusPill status={d.status} /><span className="text-xs text-mute">{result.signature_checked ? "Signed QR verified" : "ID lookup only — not a signed label"}</span></div>
            <Link className="mt-3 inline-block text-sm text-brand hover:underline" to={`/shipments/${d.shipment.id}`}>Open shipment history →</Link>
          </>}
        </div>}

        <form className="card space-y-4 p-5" onSubmit={submitHandover}>
          <h2 className="card-title">Confirm checkpoint handover</h2>
          <Field label="Checkpoint"><select className="input" required value={checkpointId} onChange={e => setCheckpointId(e.target.value)}>{checkpoints.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</select></Field>
          <Field label="Action"><select className="input" required value={action} onChange={e => setAction(e.target.value as EventType)}>{ACTIONS.map(a => <option key={a} value={a}>{a.replace("_", " ")}</option>)}</select></Field>
          <Field label="Note (optional)"><input className="input" maxLength={280} value={note} onChange={e => setNote(e.target.value)} placeholder="Seal intact, quantity checked…" /></Field>
          <button className="btn-primary w-full" disabled={busy || !result || !scanned || !checkpointId}>{busy ? "Recording…" : result?.found && result.signature_checked ? "Record signed-QR handover" : "Log rejected scan attempt"}</button>
          <p className="text-xs leading-5 text-mute">The server supplies the timestamp. Repeated network requests are collapsed using an idempotency key. Suspicious travel patterns create evidence-backed flags; they do not prove fraud.</p>
        </form>
      </section>
    </div>

    {role === "inspector" || role === "admin" ? <form onSubmit={submitManual} className="card mt-6 space-y-3 border-warn/30 p-5">
      <h2 className="card-title">Manual exception (inspector/admin only)</h2>
      <p className="text-sm text-mute">Use only when the label is damaged or the camera cannot operate. Every exception is separately marked and added to the audit trail.</p>
      <div className="grid gap-3 sm:grid-cols-2"><Field label="Shipment ID"><input className="input font-mono" required value={manualId} onChange={e => setManualId(e.target.value)} placeholder="TG-2026-ABC234" /></Field>
      <Field label="Checkpoint"><select className="input" value={manualCheckpoint} onChange={e => setManualCheckpoint(e.target.value)}>{checkpoints.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</select></Field>
      <Field label="Action"><select className="input" value={manualAction} onChange={e => setManualAction(e.target.value as EventType)}>{ACTIONS.map(a => <option key={a} value={a}>{a}</option>)}</select></Field>
      <Field label="Reason (required)"><input className="input" required minLength={10} maxLength={280} value={manualReason} onChange={e => setManualReason(e.target.value)} placeholder="e.g. label damaged; shipment checked manually" /></Field></div>
      <button className="btn-ghost" disabled={busy}>Record manual exception</button>
    </form> : null}
  </>;
}
