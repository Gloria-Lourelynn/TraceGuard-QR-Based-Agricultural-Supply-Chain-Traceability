import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, NewShipment, ShipmentDetail, UNITS } from "../api/client";
import { errMsg } from "../hooks";
import { ErrorBox, Field, PageHeader } from "../components/ui";

const today = () => new Date().toISOString().slice(0, 10);
const EMPTY = { product: "", origin: "", destination: "", quantity: "", unit: "kg", dispatch_date: today(), created_by: "" };

export default function Register() {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [created, setCreated] = useState<ShipmentDetail>();
  const [qrAsset, setQrAsset] = useState<{ shipmentId: string; url: string }>();
  const createdId = created?.shipment.id;
  const qrUrl = (createdId && qrAsset?.shipmentId === createdId) ? qrAsset.url : undefined;
  useEffect(() => {
    let active = true; let url: string | undefined;
    setQrAsset(undefined);
    if (createdId) api.fetchQr(createdId).then(value => { url = value; if (active) setQrAsset({ shipmentId: createdId, url: value }); else URL.revokeObjectURL(value); }).catch(err => setError(errMsg(err)));
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [createdId]);

  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const body: NewShipment = { ...form, quantity: Number(form.quantity) };
      setCreated(await api.register(body));
      setForm({ ...EMPTY, created_by: form.created_by });
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setBusy(false);
    }
  }

  const id = created?.shipment.id;

  return (
    <>
      <PageHeader title="Register shipment" sub="The system issues the shipment ID and a signed QR code. You never type an ID." />
      <div className="grid gap-6 lg:grid-cols-5">
        <form onSubmit={submit} className="card space-y-5 p-6 lg:col-span-3">
          <h2 className="card-title">Shipment details</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Product"><input className="input" required maxLength={80} value={form.product} onChange={set("product")} placeholder="Tomatoes" /></Field>
            <Field label="Registered by"><input className="input" required maxLength={60} value={form.created_by} onChange={set("created_by")} placeholder="Name or cooperative" /></Field>
            <Field label="Origin"><input className="input" required maxLength={80} value={form.origin} onChange={set("origin")} placeholder="Coimbatore" /></Field>
            <Field label="Destination"><input className="input" required maxLength={80} value={form.destination} onChange={set("destination")} placeholder="Chennai" /></Field>
            <Field label="Quantity"><input className="input" required type="number" min="0.001" step="any" value={form.quantity} onChange={set("quantity")} placeholder="500" /></Field>
            <Field label="Unit">
              <select className="input" value={form.unit} onChange={set("unit")}>
                {UNITS.map((u) => <option key={u}>{u}</option>)}
              </select>
            </Field>
            <Field label="Dispatch date"><input className="input" required type="date" value={form.dispatch_date} onChange={set("dispatch_date")} /></Field>
          </div>
          {error && <ErrorBox message={error} />}
          <button className="btn-primary" disabled={busy}>{busy ? "Registering…" : "Register and issue QR"}</button>
        </form>

        <aside className="lg:sticky lg:top-6 lg:col-span-2 lg:self-start">
          {created && id ? (
            <div className="card p-6">
              <p className="inline-flex items-center gap-2 rounded-full bg-ok/10 px-3 py-1 text-sm font-medium text-ok">✓ Registered successfully</p>
              <div className="print-area mt-3 text-center">
                {qrUrl ? <img src={qrUrl} alt={`Signed QR code for ${id}`} width={220} height={220} className="mx-auto rounded-xl border border-line bg-white p-2" /> : <p className="py-10 text-sm text-mute">Loading signed label…</p>}
                <p className="mt-3 font-mono text-lg tracking-wider">{id}</p>
                <p className="text-sm text-mute">{created.shipment.product} · {created.shipment.origin} → {created.shipment.destination}</p>
              </div>
              <div className="no-print mt-4 flex flex-wrap justify-center gap-2">
                {qrUrl && <a className="btn-ghost" href={qrUrl} download={`${id}.png`}>Download QR label</a>}
                <button className="btn-ghost" onClick={() => window.print()}>Print label</button>
                <Link className="btn-primary" to={`/shipments/${id}`}>Open shipment</Link>
              </div>
              <p className="no-print mt-3 text-center text-xs text-mute">Give the signed physical label to the assigned transporter. An ID typed by hand cannot authorise an ordinary handover.</p>
            </div>
          ) : (
            <div className="card grid min-h-[280px] place-items-center border-dashed p-5 text-center text-sm text-mute">
              The QR code appears here after registration.
            </div>
          )}
        </aside>
      </div>
    </>
  );
}
