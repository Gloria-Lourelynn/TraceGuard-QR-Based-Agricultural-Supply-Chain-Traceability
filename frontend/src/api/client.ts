// Typed API client. All requests go to /api (proxied to FastAPI by Vite).
export type Status = "REGISTERED" | "DISPATCHED" | "IN_TRANSIT" | "RECEIVED" | "DELIVERED";
export type EventType = Exclude<Status, "REGISTERED">;
export type Verdict = "VERIFIED" | "REQUIRES_INVESTIGATION";
export type Severity = "high" | "medium" | "low";
export type FlagStatus = "open" | "reviewed" | "dismissed";

export const STATUSES: Status[] = ["REGISTERED", "DISPATCHED", "IN_TRANSIT", "RECEIVED", "DELIVERED"];
export const UNITS = ["kg", "quintal", "tonne", "crate", "bag", "litre", "unit"] as const;

export interface Shipment {
  id: string;
  product: string;
  origin: string;
  destination: string;
  quantity: number;
  unit: string;
  dispatch_date: string;
  created_at: string;
  created_by: string;
}
export interface ShipmentSummary extends Shipment {
  status: Status;
  verdict: Verdict;
  open_flag_count: number;
}
export interface FlagEvidence {
  summary?: string;
  why_suspicious?: string;
  observed?: Record<string, unknown>;
  expected?: Record<string, unknown>;
  unknowns?: string[];
  next_steps?: string[];
  scan_ids?: number[];
}
export interface Flag {
  id: number;
  shipment_id: string;
  event_id: number | null;
  rule_code: string;
  severity: Severity;
  explanation: string;
  status: FlagStatus;
  created_at: string;
  incident_key?: string | null;
  evidence?: FlagEvidence | null;
}
export interface ShipmentEvent {
  id: number;
  shipment_id: string;
  type: EventType;
  checkpoint: string;
  actor: string;
  timestamp: string;
  note: string;
  destination: string | null;
  quantity: number | null;
  valid: boolean;
  flags: Flag[];
}
export interface ScanRecord {
  id: number; shipment_id: string | null; scanned_by: string; checkpoint_id: string | null; checkpoint: string;
  action: EventType | null; scanned_at: string; signature_valid: number; scan_result: string; event_id: number | null; note: string;
  destination: string | null; quantity: number | null;
}
export interface RiskAssessment { score: number; band: string; meaning: string; uncapped: number; contributions: { incident_key: string; rule_code: string; points: number; reason: string }[]; disclaimer: string; }
export interface ShipmentDetail {
  shipment: Shipment;
  status: Status;
  verdict: Verdict;
  open_flag_count: number;
  expected_next: string[];
  events: ShipmentEvent[];
  flags: Flag[];
  scans: ScanRecord[];
  risk: RiskAssessment;
}
export interface FlagDraft {
  rule_code: string;
  severity: Severity;
  explanation: string;
}
export interface VerifyResult {
  found: boolean;
  verdict: Verdict | "UNKNOWN";
  signature_checked: boolean;
  flags: FlagDraft[];
  detail: ShipmentDetail | null;
}
export interface ReportData extends ShipmentDetail {
  generated_at: string;
  conclusion: string;
  rules_checked: string[];
}
export interface DashboardData {
  total_shipments: number;
  verified: number;
  under_investigation: number;
  by_status: Record<Status, number>;
  open_flags: number;
  investigation_list: ShipmentSummary[];
  recent_events: { id: number; shipment_id: string; type: EventType; checkpoint: string; actor: string; timestamp: string; product: string }[];
  alerts: (Flag & { product: string })[];
}

export interface NewShipment {
  product: string;
  origin: string;
  destination: string;
  quantity: number;
  unit: string;
  dispatch_date: string;
  created_by: string;
}
export interface AppUser { id: string; username: string; display_name: string; role: "seller" | "transporter" | "inspector" | "admin"; active: boolean; created_at: string; }
export interface Checkpoint { id: string; name: string; demo_coordinates: boolean; }
export interface NewUser { username: string; display_name: string; role: AppUser["role"]; password: string; }
export interface Assignment { shipment_id: string; username: string; checkpoint_id?: string | null; }
export interface HandoverBody { scanned: string; checkpoint_id: string; action: EventType; idempotency_key: string; note?: string; destination?: string; quantity?: number; }
export interface ManualHandoverBody { shipment_id: string; checkpoint_id: string; action: EventType; reason: string; idempotency_key: string; }
export interface NewEvent {
  type: EventType;
  checkpoint: string;
  actor: string;
  note?: string;
  timestamp?: string;
  destination?: string;
  quantity?: number;
}

export interface AuditAnchorReceipt {
  v: number;
  system: string;
  anchored_at: string;
  sequence: number;
  head_hash: string;
  record_count: number;
  signature: string;
}

export interface AuditAnchorVerification {
  ok: boolean;
  records_checked?: number;
  anchored_sequence?: number;
  anchored_hash?: string;
  records_since_anchor?: number;
  anchored_at?: string;
  reason?: string | null;
}

export interface AuditRecord {
  seq: number;
  kind: string;
  ts: string;
  actor_id: string | null;
  actor_username: string | null;
  actor_name: string | null;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface AuditLogResponse {
  total: number;
  limit: number;
  offset: number;
  records: AuditRecord[];
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = sessionStorage.getItem("traceguard_token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  try {
    res = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError("Cannot reach the server. Is the backend running?", 0);
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail))
        msg = body.detail
          .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? "invalid"}`)
          .join("; ");
    } catch {
      /* non-JSON error body: keep the generic message */
    }
    if (res.status === 404) msg = "Not found";
    if (res.status === 429) msg = "Too many requests. Please wait a moment.";
    throw new ApiError(msg, res.status);
  }
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const api = {
  login: (username: string, password: string) => request<{ access_token: string; token_type: string; expires_in: number; user: AppUser }>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => request<{ status: string; message: string }>("/auth/logout", { method: "POST" }),
  me: () => request<AppUser>("/auth/me"),
  users: () => request<AppUser[]>("/users"),
  createUser: (body: NewUser) => request<AppUser>("/users", { method: "POST", body: JSON.stringify(body) }),
  assign: (body: Assignment) => request<{ id: number; shipment_id: string; user: AppUser; checkpoint_id: string | null }>("/assignments", { method: "POST", body: JSON.stringify(body) }),
  checkpoints: () => request<Checkpoint[]>("/checkpoints"),
  handover: (body: HandoverBody) => request<{ found: boolean; duplicate: boolean; scan_id: number; event_id: number | null; detail: ShipmentDetail | null; new_flags: FlagDraft[]; message?: string }>("/scans/handover", { method: "POST", body: JSON.stringify(body) }),
  manualHandover: (body: ManualHandoverBody) => request<{ detail: ShipmentDetail; new_flags: FlagDraft[] }>("/scans/manual-handover", { method: "POST", body: JSON.stringify(body) }),
  auditVerify: () => request<{ ok: boolean; checked: number | null; first_bad_seq: number | null; reason: string | null; head_hash: string | null; warning: string }>("/audit/verify"),
  getAnchor: () => request<AuditAnchorReceipt>("/audit/anchor"),
  verifyAnchor: (anchor: AuditAnchorReceipt | Record<string, unknown>) => request<AuditAnchorVerification>("/audit/verify-anchor", { method: "POST", body: JSON.stringify({ anchor }) }),
  auditRecords: (limit?: number, offset?: number) => request<AuditLogResponse>(`/audit/records?limit=${limit ?? 50}&offset=${offset ?? 0}`),
  dashboard: () => request<DashboardData>("/dashboard"),
  listShipments: (q?: string) => request<ShipmentSummary[]>(`/shipments${q ? `?q=${enc(q)}` : ""}`),
  getShipment: (id: string) => request<ShipmentDetail>(`/shipments/${enc(id)}`),
  register: (body: NewShipment) =>
    request<ShipmentDetail>("/shipments", { method: "POST", body: JSON.stringify(body) }),
  addEvent: (id: string, body: NewEvent) =>
    request<{ event_id: number; new_flags: FlagDraft[]; detail: ShipmentDetail }>(
      `/shipments/${enc(id)}/events`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  verify: (scanned: string) => request<VerifyResult>(`/verify/${enc(scanned)}`),
  report: (id: string) => request<ReportData>(`/shipments/${enc(id)}/report`),
  patchFlag: (id: number, status: "reviewed" | "dismissed", reason: string) =>
    request<Flag>(`/flags/${id}`, { method: "PATCH", body: JSON.stringify({ status, reason }) }),
  qrUrl: (id: string) => `/api/shipments/${enc(id)}/qr`,
  fetchQr: async (id: string): Promise<string> => {
    const headers = new Headers(); const token = sessionStorage.getItem("traceguard_token");
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const res = await fetch(`/api/shipments/${enc(id)}/qr`, { headers });
    if (!res.ok) throw new ApiError(res.status === 403 ? "Your role cannot download this label." : "Could not load QR label", res.status);
    return URL.createObjectURL(await res.blob());
  },
};
